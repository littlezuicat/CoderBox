# -*- coding: utf-8 -*-
"""一键给 SSH 主机装 VS Code Server。
VS Code 的 Remote-SSH 默认让服务器自己去微软站点下载服务端，服务器上不了外网（国内机器常见）就会卡在 “Downloading with wget”。
这里换成：本机下载（走本机网络/代理）→ 经已有的 SSH 连接上传 → 在服务器上解压到 ~/.vscode-server/bin/<提交号>/。
提交号取本机正在用的 VS Code（`code --version`），必须和本机 VS Code 一致，Remote-SSH 才认。只支持 Linux 主机。"""
import glob
import json
import logging
import os
import time
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from majing.core import sshhosts
from majing.settings import _path

log = logging.getLogger("majing.vsc")

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armhf", "armv8l": "armhf"}


def _cache_dir():
    d = os.path.join(os.path.dirname(_path()), "vscode-server")
    os.makedirs(d, exist_ok=True)
    return d


def _install_dirs():
    out = []
    la, pf = os.environ.get("LOCALAPPDATA") or "", os.environ.get("ProgramFiles") or ""
    for base in (os.path.join(la, "Programs", "Microsoft VS Code"), os.path.join(pf, "Microsoft VS Code")):
        if base and os.path.isdir(base):
            out.append(base)
    code = shutil.which("code")
    if code:
        d = os.path.dirname(os.path.dirname(code))
        if os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def local_vscode():
    """本机 VS Code 的 {commit, version, quality}；找不到返回 None。"""
    exe = shutil.which("code")
    for base in _install_dirs():
        for n in ("code.cmd", "code"):
            p = os.path.join(base, "bin", n)
            if os.path.isfile(p):
                exe = exe or p
    info = None
    if exe:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, creationflags=_NOWIN, encoding="utf-8", errors="replace")
            lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
            if len(lines) >= 2 and re.fullmatch(r"[0-9a-f]{40}", lines[1]):
                info = {"version": lines[0], "commit": lines[1]}
        except Exception as e:                                   # noqa: BLE001
            log.warning("code --version 失败：%s", e)
    quality = "stable"
    prods = []
    for base in _install_dirs():
        prods += glob.glob(os.path.join(base, "*", "resources", "app", "product.json")) + glob.glob(os.path.join(base, "resources", "app", "product.json"))
    prods.sort(key=os.path.getmtime, reverse=True)
    for p in prods:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                        # noqa: BLE001
            continue
        if info is None:
            info = {"version": d.get("version", ""), "commit": d.get("commit", "")}
            quality = d.get("quality") or "stable"
            break
        if d.get("commit") == info["commit"]:
            quality = d.get("quality") or "stable"
            break
    if not info or not re.fullmatch(r"[0-9a-f]{40}", info.get("commit", "")):
        return None
    info["quality"] = quality
    return info


MIRROR = "https://www.zuicat.cn/toolbox/vscode-server"       # 码境服务器预取的镜像（deploy/vsc-mirror）；MAJING_VSC_MIRROR 可改，设成空串就不用


def _sources(commit, arch, quality):
    """下载地址，按优先级：测试用的 MAJING_VSC_URL（只用它）／码境镜像（只有稳定版）／微软官方。同一个提交的安装包各处字节一致，所以断点续传可以跨源接着下。"""
    env = os.environ.get("MAJING_VSC_URL")
    if env:
        return [env.format(commit=commit, arch=arch, quality=quality)]
    out = []
    mirror = os.environ.get("MAJING_VSC_MIRROR", MIRROR)
    if mirror and quality == "stable":
        out.append("%s/%s/vscode-server-linux-%s.tar.gz" % (mirror.rstrip("/"), commit, arch))
    out.append("https://update.code.visualstudio.com/commit:%s/server-linux-%s/%s" % (commit, arch, quality))
    return out


def _download(urls, dest, prog):
    """下载到 dest。urls 是按优先级排的几个源（字符串也行）：前面的源没有这个文件（404）或连不上就换下一个，最后一个源重试到底。
    支持断点续传（.part 里已有的接着下）和网络中断自动重试：本机到微软的网络常常只有几百 KB/s，安装包 230MB 上下，一次下不完很正常。"""
    if isinstance(urls, str):
        urls = [urls]
    if os.path.isfile(dest) and os.path.getsize(dest) > 5_000_000:
        prog("download", 100, "本机已有下载好的安装包，直接用")
        return
    part = dest + ".part"
    last = None
    done = False
    for si, url in enumerate(urls):
        final = si == len(urls) - 1
        host = url.split("/")[2]
        for attempt in range(40 if final else 3):
            have = os.path.getsize(part) if os.path.isfile(part) else 0
            headers = {"User-Agent": "Mozilla/5.0 (ClaudeToolbox)"}
            if have:
                headers["Range"] = "bytes=%d-" % have
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60 if final else 30) as r:
                    resumed = bool(have) and r.status == 206
                    length = int(r.headers.get("Content-Length") or 0)
                    total = (have + length) if resumed else length
                    got = have if resumed else 0
                    with open(part, "ab" if resumed else "wb") as f:
                        while True:
                            b = r.read(256 * 1024)
                            if not b:
                                break
                            f.write(b)
                            got += len(b)
                            prog("download", int(got * 100 / total) if total else 0, "正在下载 %.1f MB%s（%s）" % (got / 1048576, " / %.1f MB" % (total / 1048576) if total else "", host))
                if total and got < total:
                    raise OSError("连接中断（%d/%d 字节）" % (got, total))
                done = True
                break
            except urllib.error.HTTPError as e:
                if e.code == 416 and have > 5_000_000:           # 已经下完了（.part 就是完整文件）
                    done = True
                    break
                if e.code == 416:
                    os.remove(part)
                last = e
                if e.code in (403, 404) and not final:           # 这个源没有这个版本：直接换下一个源
                    log.info("%s 没有这个版本（HTTP %s），换下一个源", host, e.code)
                    break
            except (OSError, urllib.error.URLError) as e:        # 超时、被掐断：等一会儿接着下
                last = e
            wait = min(5 * (attempt + 1), 30)
            log.info("下载中断（%s 第 %d 次）：%s，%s 秒后接着下", host, attempt + 1, last, wait)
            prog("download", 0, "网络不稳，%d 秒后接着下…" % wait)
            time.sleep(wait)
        if done:
            break
    if not done:
        raise RuntimeError("本机下载一直失败：%s（检查本机网络或代理，已下的部分会保留，下次接着下）" % last)
    with open(part, "rb") as f:
        magic = f.read(2)
    if magic != b"\x1f\x8b" or os.path.getsize(part) < 5_000_000:
        os.remove(part)
        raise RuntimeError("下载到的不是有效的安装包（可能被网络拦截了）。")
    os.replace(part, dest)
    for old in glob.glob(os.path.join(os.path.dirname(dest), "vscode-server-*")):          # 旧版本的安装包不留，每个 230MB
        if os.path.abspath(old) != os.path.abspath(dest):
            try:
                os.remove(old)
            except OSError:
                pass


def install(alias, prog):
    """prog(step, pct, text)。成功返回说明文字，失败抛 RuntimeError（文字直接给用户看）。"""
    prog("check", 0, "正在检查本机 VS Code…")
    loc = local_vscode()
    if not loc:
        raise RuntimeError("本机没找到 VS Code（需要先装好并能在命令行运行 code）。")
    commit, quality = loc["commit"], loc["quality"]
    log.info("给 %s 装 VS Code Server：本机 %s 提交 %s", alias, loc.get("version"), commit[:10])
    prog("check", 30, "本机 VS Code %s，正在连接 %s…" % (loc.get("version", ""), alias))
    try:
        cli, sftp = sshhosts._session(alias)
        _, out, _ = sshhosts._run(cli, "uname -sm", 10)
    except Exception as e:                                       # noqa: BLE001
        raise RuntimeError("连不上 %s：%s" % (alias, e))
    parts = out.split()
    if len(parts) < 2 or parts[0] != "Linux":
        raise RuntimeError("这台主机不是 Linux，暂不支持（Windows 主机请让 VS Code 自己装）。")
    arch = _ARCH.get(parts[1])
    if not arch:
        raise RuntimeError("不认识的处理器架构：%s" % parts[1])
    home = sftp.normalize(".")
    bindir = "%s/.vscode-server/bin/%s" % (home, commit)
    code, _, _ = sshhosts._run(cli, "test -x %s" % shlex.quote(bindir + "/bin/code-server"), 10)
    have = code == 0
    name = "vscode-server-%s-linux-%s.tar.gz" % (commit[:10], arch)
    if not have:
        urls = _sources(commit, arch, quality)
        local = os.path.join(_cache_dir(), name)
        prog("download", 0, "正在下载（%s）…" % arch)
        try:
            _download(urls, local, prog)
        except RuntimeError:
            raise
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError("本机下载失败：%s（检查本机网络或代理）" % e)
        prog("upload", 0, "正在上传到 %s…" % alias)
        for d in (home + "/.vscode-server", home + "/.vscode-server/bin"):
            try:
                sftp.mkdir(d)
            except OSError:
                pass
        remote = "%s/.vscode-server/%s" % (home, name)
        size = os.path.getsize(local)
        with open(local, "rb") as f:
            sftp.putfo(f, remote + ".part", callback=lambda a, b: prog("upload", int(a * 100 / (b or size)), "正在上传 %.1f / %.1f MB" % (a / 1048576, (b or size) / 1048576)))
        try:
            sftp.remove(remote)
        except OSError:
            pass
        sftp.rename(remote + ".part", remote)
        prog("extract", 0, "正在服务器上解压…")
        script = ('D=%s; T=%s; rm -rf "$D"; mkdir -p "$D" && tar xzf "$T" -C "$D" --strip-components=1 && touch "$D/0"; rc=$?; rm -f "$T"; '
                  '[ $rc -eq 0 ] && [ -x "$D/bin/code-server" ] && echo OK || { rm -rf "$D"; echo FAIL; }') % (shlex.quote(bindir), shlex.quote(remote))
        _, out, err = sshhosts._run(cli, "sh -c " + shlex.quote(script), 180)
        if "OK" not in out:
            raise RuntimeError("在服务器上解压失败：%s" % ((err or out).strip()[:200] or "未知原因（磁盘满了？）"))
    # 清掉上次卡住留下的安装锁（锁文件名里带这个提交号），否则 VS Code 会一直等它
    sshhosts._run(cli, "sh -c " + shlex.quote('rm -f "$HOME"/.vscode-server/bin/vscode-remote-lock.*.%s' % commit), 10)
    prog("done", 100, "完成")
    if have:
        return "%s 上本来就装好了这个版本的 VS Code Server，只清掉了卡住的安装锁。回到 VS Code 重新连接就行。" % alias
    return "已在 %s 上装好 VS Code Server（%s）。回到 VS Code 重新连接就行。" % (alias, loc.get("version") or commit[:10])
