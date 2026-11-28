# -*- coding: utf-8 -*-
"""实验的一句话说明：把训练命令、配置、日志开头交给模型，让它用一句短话说这个实验在做什么。
两种模型任选（都走本机已登录的命令行，在临时空目录里跑、不存会话）：
  haiku：`claude -p --model haiku --effort low --tools ""`
  gpt  ：`codex exec -m gpt-6-luna -c model_reasoning_effort="low" -s read-only --ephemeral`
提取成功一次就存进实验记录，不再重复提取；失败了过一阵再试。发给模型前先把疑似密钥打码。
命令行不在 PATH 里时，自动去常见位置找（npm 全局目录、VS Code 的 Codex 扩展目录等），找到就把它所在目录加进用户环境变量 PATH。"""
import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile

log = logging.getLogger("majing.exp")

SYSTEM = "用一句中文（20到30个字，不换行）概括这个深度学习实验在做什么：任务、数据集、方法要点，例如“在RESIDE数据集上训练基于Transformer的单图像去雾网络”。不写路径和参数，不加引号，不要用“这是”开头，直接说做什么，只输出这一句。"
MAX_LEN = 34
GPT_MODEL = "gpt-6-luna"
PROVIDERS = {"haiku": "claude", "gpt": "codex"}

_SECRET = re.compile(r"(?i)((?:api[_-]?key|secret|token|passwd|password|authorization|access[_-]?key|private[_-]?key|bearer)\w*['\"]?\s*[:=]\s*['\"]?)([^\s'\",}]{4,})")
_LONG = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|[A-Za-z0-9+/_\-]{40,}={0,2}|[0-9a-fA-F]{32,})\b")
_AUTH_HINT = re.compile(r"(?i)not logged in|please run /?login|/login|login required|sign in|invalid api key|authentication|oauth|credentials|unauthorized|401|未登录")
_NOISE = re.compile(r"(?i)^(?:note|说明|实验说明|结论)[:：]\s*")

_tmpdir = None


def mask(text):
    text = _SECRET.sub(lambda m: m.group(1) + "***", text or "")
    return _LONG.sub("***", text)


_KEY = re.compile(r"(?i)(name|model|network|arch|task|dataset|data|type|loss|scale|aug|pretrain|backbone|dehaz|derain|denois|detect|segment|super|restor|train|epoch|iter|lr|batch|opt)")
_TS = re.compile(r"^\s*(?:\[?\d{4}[-/]\d\d[-/]\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?\]?|\d\d:\d\d:\d\d(?:[.,]\d+)?)\s*[-:|]?\s*(?:\[?(?:INFO|DEBUG|WARNING|WARN)\]?\s*[-:|]?\s*)?")
_BAD = re.compile(r"(?i)warn|deprecat|\d+%\||it/s|s/it|nvidia-smi|cuda version|^\W*$")
_PATH = re.compile(r"(?:[A-Za-z]:)?[\/][^\s'\",=:]*[\/][^\s'\",=:]+")


def _short_path(m):
    parts = [x for x in re.split(r"[\/]", m.group(0)) if x]
    return ".../" + "/".join(parts[-2:]) if len(parts) > 2 else m.group(0)


def _cmd(text, n):
    return _PATH.sub(_short_path, re.sub(r"\s+", " ", text or "")).strip()[:n]


def _cfg(text, n):
    """配置文件：去注释/空行/路径，信息量大的键（模型、数据集、任务…）排前面，凑够 n 字就停。"""
    seen, good, rest = set(), [], []
    for ln in (text or "").splitlines():
        ln = re.sub(r"\s+#.*$|^\s*#.*$", "", ln).rstrip()
        t = ln.strip()
        if not t or t in seen or t in "{}[]()-":
            continue
        seen.add(t)
        t = _PATH.sub(_short_path, t)[:120]
        (good if _KEY.search(t) else rest).append(t)
    out, used = [], 0
    for t in good + rest:
        if used + len(t) + 1 > n:
            break
        out.append(t)
        used += len(t) + 1
    return "\n".join(out)


def _head(text, n):
    """日志开头：去时间戳、警告、进度条和重复行。"""
    seen, out, used = set(), [], 0
    for ln in (text or "").splitlines():
        t = _TS.sub("", ln).strip()[:160]
        if not t or _BAD.search(t) or t in seen:
            continue
        seen.add(t)
        if used + len(t) + 1 > n:
            break
        out.append(t)
        used += len(t) + 1
    return "\n".join(out)


def build_prompt(ctx):
    """尽量省 token：路径缩短、配置只留有信息的键、日志去噪，没有「最近几行」。"""
    parts = ["命令：" + _cmd(mask(ctx.get("cmd", "")), 500)]
    if ctx.get("launcher"):
        parts.append("启动：" + _cmd(mask(ctx["launcher"]), 200))
    cwd = [x for x in re.split(r"[\/]", ctx.get("cwd") or "") if x]
    if cwd:
        parts.append("目录：" + "/".join(cwd[-2:]))
    if ctx.get("cfg"):
        parts.append("配置：\n" + _cfg(mask(ctx["cfg"]), 1000))
    if ctx.get("head"):
        parts.append("日志：\n" + _head(mask(ctx["head"]), 700))
    if ctx.get("shorten"):
        parts.append("你上次写的“%s”太长。压缩成不超过28个字的完整一句话，仍然只输出这一句。" % ctx["shorten"])
    return "\n".join(parts)


# ---------------------------------------------------------------- 找命令行 + 自动加环境变量
def _candidates(name):
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    out = []
    if sys.platform == "win32":
        out += [os.path.join(appdata, "npm", name + ".cmd"), os.path.join(appdata, "npm", name + ".exe"), os.path.join(local, "Programs", name, name + ".exe"),
                os.path.join(home, ".local", "bin", name + ".exe"), os.path.join(home, "scoop", "shims", name + ".exe")]
    else:
        out += [os.path.join(home, ".local", "bin", name), "/usr/local/bin/" + name, os.path.join(home, ".npm-global", "bin", name)]
    if name == "claude":
        out += [os.path.join(home, ".claude", "local", "claude" + (".exe" if sys.platform == "win32" else ""))]
    if name == "codex":
        # VS Code / Cursor 的 Codex 扩展自带一份
        for root in (os.path.join(home, ".vscode", "extensions"), os.path.join(home, ".cursor", "extensions"), os.path.join(home, ".vscode-insiders", "extensions")):
            out += sorted(glob.glob(os.path.join(root, "openai.chatgpt-*", "bin", "*", "codex" + (".exe" if sys.platform == "win32" else ""))), reverse=True)
        out += [os.path.join(home, ".codex", "bin", "codex" + (".exe" if sys.platform == "win32" else ""))]
    return out


def ensure_on_path(exe):
    """把可执行文件所在目录加进环境变量 PATH：当前进程立即生效；Windows 上同时写进用户环境变量（以后新开的终端和程序都能直接用）。"""
    d = os.path.dirname(os.path.abspath(exe))
    norm = lambda x: os.path.normcase(os.path.normpath(x.strip().strip('"')))
    cur = [norm(x) for x in os.environ.get("PATH", "").split(os.pathsep) if x.strip()]
    if norm(d) in cur:
        return False
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + d
    log.info("命令行不在 PATH 里，已把 %s 加进当前进程的 PATH", d)
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                val, typ = winreg.QueryValueEx(k, "Path")
            except FileNotFoundError:
                val, typ = "", winreg.REG_EXPAND_SZ
            if norm(d) not in [norm(x) for x in val.split(";") if x.strip()]:
                winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ if typ != winreg.REG_SZ else winreg.REG_SZ, (val.rstrip(";") + ";" if val else "") + d)
                log.info("已把 %s 写进用户环境变量 PATH", d)
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000, ctypes.byref(res))      # 通知已打开的程序环境变量变了
    except Exception as e:               # noqa: BLE001
        log.warning("写用户环境变量失败（当前进程里仍然可用）：%s", e)
    return True


def find_cli(name):
    env = os.environ.get("MAJING_%s_BIN" % name.upper())
    if env:
        return env
    p = shutil.which(name)
    if p:
        return p
    for c in _candidates(name):
        if os.path.isfile(c):
            ensure_on_path(c)
            return c
    return None


def clean(text):
    """模型输出 → 一句短话：取第一行，去掉引号、句号、前缀；不在中间硬截（截出半句很难看）。"""
    t = (text or "").strip().splitlines()
    t = t[0].strip() if t else ""
    t = _NOISE.sub("", t).strip(" \t\"'“”‘’「」`*。.；;")
    t = re.sub(r"^(?:这是|该实验是|本实验是)(?:一个|一项|一次)?", "", t).strip(" ，,：:")
    if "（" in t and "）" not in t:
        t = t.split("（")[0].strip() or t
    return t[:60]                        # 只防模型发疯；太长让它自己压缩（见 ask），界面一行放不下会自动省略


def _tmp():
    global _tmpdir
    if _tmpdir is None or not os.path.isdir(_tmpdir):
        _tmpdir = tempfile.mkdtemp(prefix="mj_exp_note_")
    return _tmpdir


_LEAN_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}      # 不加载记忆/CLAUDE.md，少发无关内容


def _run(cmd, prompt, timeout):
    return subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=timeout, cwd=_tmp(), env={**os.environ, **_LEAN_ENV}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ask_one(provider, ctx, timeout):
    cli = PROVIDERS[provider]
    exe = find_cli(cli)
    name = "Claude Code" if cli == "claude" else "Codex"
    if not exe:
        return False, "没找到 %s 命令行（%s），装好并登录后才能生成实验说明" % (cli, name), "missing"
    outfile = None
    if provider == "haiku":
        cmd = [exe, "-p", "--model", "haiku", "--effort", "low", "--tools", "", "--no-session-persistence", "--disable-slash-commands", "--system-prompt", SYSTEM]
        prompt = build_prompt(ctx)
    else:
        fd, outfile = tempfile.mkstemp(prefix="mj_exp_out_", suffix=".txt", dir=_tmp())
        os.close(fd)
        cmd = [exe, "exec", "-m", GPT_MODEL, "-c", 'model_reasoning_effort="low"', "--ignore-user-config", "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-o", outfile, "-"]
        prompt = SYSTEM + "\n\n" + build_prompt(ctx)
    try:
        p = _run(cmd, prompt, timeout)
    except subprocess.TimeoutExpired:
        return False, "生成实验说明超时", "error"
    except Exception as e:                       # noqa: BLE001
        return False, "调用 %s 失败：%s" % (cli, e), "error"
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    if outfile:
        try:
            with open(outfile, encoding="utf-8", errors="replace") as f:
                got = f.read().strip()
            os.remove(outfile)
        except OSError:
            got = ""
        out = got                                # codex 的标准输出里夹着很多过程信息，只认 -o 文件里的最终回答
    if p.returncode != 0 or not out:
        msg = (out or err or "退出码 %s" % p.returncode)[-200:]
        return False, msg, "auth" if _AUTH_HINT.search(out + " " + err) else "error"
    if _AUTH_HINT.search(out[:200]) and len(out) < 200:
        return False, out[:200], "auth"
    note = clean(out)
    if len(note) < 4:
        return False, "模型没有给出有效的说明", "error"
    return True, note, ""


def ask(ctx, provider="haiku", timeout=150):
    """返回 (ok, 文字或错误, kind)；kind: 'auth' 没登录 / 'missing' 没装命令行 / 'error' 其它。
    选的那个命令行没装就自动换另一个。"""
    order = [provider] + [x for x in PROVIDERS if x != provider]
    res = (False, "", "error")
    for i, pv in enumerate(order):
        res = _ask_one(pv, ctx, timeout)
        if res[0] and len(res[1]) > MAX_LEN:                 # 太长：让模型重写成完整的短句，还是长就留着（界面省略）
            r2 = _ask_one(pv, {**ctx, "shorten": res[1]}, timeout)
            if r2[0] and len(r2[1]) < len(res[1]):
                res = r2
        if res[0] or res[2] != "missing":
            return res
    return res
