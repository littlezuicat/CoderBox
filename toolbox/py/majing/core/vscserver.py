# -*- coding: utf-8 -*-
"""一键给 SSH 主机装 VS Code Server。
VS Code 的 Remote-SSH 默认让服务器自己去微软站点下载服务端，服务器上不了外网（国内机器常见）就会卡在 “Downloading with wget”。
这里换成：本机下载（走本机网络/代理）→ 经已有的 SSH 连接上传 → 在服务器上解压到 ~/.vscode-server/bin/<提交号>/。
提交号取本机正在用的 VS Code（`code --version`），必须和本机 VS Code 一致，Remote-SSH 才认。Linux 主机自动装；Windows 主机只在用户点“在 VSCode 打开”时装（安装包 200MB+）。"""
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


def _sources(commit, arch, quality, win=False):
    """下载地址，按优先级：测试用的 MAJING_VSC_URL（只用它）／码境镜像（只有稳定版）／微软官方。同一个提交的安装包各处字节一致，所以断点续传可以跨源接着下。"""
    env = os.environ.get("MAJING_VSC_URL")
    if env:
        return [env.format(commit=commit, arch=arch, quality=quality)]
    if win:                                                      # Windows 服务端（zip）：同样先走码境镜像（只有 x64 的稳定版），没有再回退微软
        w = []
        mirror = os.environ.get("MAJING_VSC_MIRROR", MIRROR)
        if mirror and quality == "stable" and arch == "x64":
            w.append("%s/%s/vscode-server-win32-x64.zip" % (mirror.rstrip("/"), commit))
        w.append("https://update.code.visualstudio.com/commit:%s/server-win32-%s/%s" % (commit, arch, quality))
        return w
    out = []
    mirror = os.environ.get("MAJING_VSC_MIRROR", MIRROR)
    if mirror and quality == "stable":
        out.append("%s/%s/vscode-server-linux-%s.tar.gz" % (mirror.rstrip("/"), commit, arch))
    out.append("https://update.code.visualstudio.com/commit:%s/server-linux-%s/%s" % (commit, arch, quality))
    return out


def _download(urls, dest, prog, magic=b"\x1f\x8b", keep="vscode-server-*-linux-*"):
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
        magic_read = f.read(len(magic))
    if magic_read != magic or os.path.getsize(part) < 5_000_000:
        os.remove(part)
        raise RuntimeError("下载到的不是有效的安装包（可能被网络拦截了）。")
    if magic == b"PK":                                           # zip：打开读一遍目录，坏包（被截断、混进别的内容）当场发现，不要传到主机上才失败
        import zipfile
        try:
            with zipfile.ZipFile(part) as z:
                if not z.namelist():
                    raise zipfile.BadZipFile("空包")
        except Exception as e:                                   # noqa: BLE001
            os.remove(part)
            raise RuntimeError("下载到的安装包是坏的（%s），已删除，请重试。" % e)
    for k in range(8):                                           # 杀毒软件刚好在扫描新下载的文件时会短暂占用（WinError 32），隔一会儿重试
        try:
            os.replace(part, dest)
            break
        except PermissionError:
            if k == 7:
                raise
            time.sleep(0.5 * (k + 1))
    for old in glob.glob(os.path.join(os.path.dirname(dest), keep)):          # 旧版本的安装包不留，每个 230MB
        if os.path.abspath(old) != os.path.abspath(dest):
            try:
                os.remove(old)
            except OSError:
                pass


def _ps(cli, script, timeout=180):
    """在 Windows 主机上跑一段 PowerShell。用 -EncodedCommand（UTF-16LE 的 base64）传，免得路径、引号、默认 shell 是 cmd 还是 PowerShell 带来的转义问题。"""
    import base64
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return sshhosts._run(cli, "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + enc, timeout)


def _install_windows(alias, cli, sftp, loc, prog):
    """Windows 主机：本机下载 server-win32 的 zip → SFTP 上传 → 在主机上用 tar（没有就 Expand-Archive）解压到用户目录下的 .vscode-server/bin/<提交号>，再跑一下 node.exe 确认能用。"""
    commit, quality = loc["commit"], loc["quality"]
    _, out, _ = _ps(cli, "[Console]::Out.Write($env:PROCESSOR_ARCHITECTURE)", 30)
    pa = "".join(ch for ch in (out or "") if ch.isalnum()).upper()          # 只留字母数字：默认 shell 是 cmd 时输出里可能夹着引号
    arch = {"AMD64": "x64", "X64": "x64", "ARM64": "arm64"}.get(pa)
    if not arch:
        raise RuntimeError("这台 Windows 主机的处理器架构（%s）VS Code 服务端不支持。" % (pa or "未知"))
    home = sftp.normalize(".")                                   # 形如 /C:/Users/name
    bindir = "%s/.vscode-server/bin/%s" % (home, commit)
    try:
        sftp.stat(bindir + "/node.exe")
        sftp.stat(bindir + "/bin/code-server.cmd")
        have = True
    except OSError:
        have = False
    name = "vscode-server-%s-win32-%s.zip" % (commit[:10], arch)
    if not have:
        local = os.path.join(_cache_dir(), name)
        prog("download", 0, "正在下载 Windows 服务端（%s）…" % arch)
        for attempt in (1, 2):                                   # 缓存里留着的半截包是坏的（或两处同时在写）时，校验会删掉它；再来一次就是从头下
            try:
                _download(_sources(commit, arch, quality, win=True), local, prog, magic=b"PK", keep="vscode-server-*-win32-*")
                break
            except RuntimeError as e:
                if attempt == 2 or "是坏的" not in str(e):
                    raise
                prog("download", 0, "缓存的安装包有问题，重新下载…")
            except Exception as e:                               # noqa: BLE001
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
        prog("extract", 0, "正在主机上解压…")
        script = r"""
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:USERPROFILE '.vscode-server'
$d = Join-Path $base 'bin\COMMIT'
$z = Join-Path $base 'ZIPNAME'
if (Test-Path $d) { Remove-Item $d -Recurse -Force }
New-Item -ItemType Directory -Force -Path $d | Out-Null
$ok = $false
if (Get-Command tar -ErrorAction SilentlyContinue) { tar -xf $z -C $d --strip-components=1; if ($LASTEXITCODE -eq 0) { $ok = $true } }
if (-not $ok) {
  $t = Join-Path $base 'unzip-tmp'
  if (Test-Path $t) { Remove-Item $t -Recurse -Force }
  Expand-Archive -LiteralPath $z -DestinationPath $t -Force
  Get-ChildItem (Join-Path $t 'vscode-server-win32-ARCH') | Move-Item -Destination $d -Force
  Remove-Item $t -Recurse -Force
}
if (-not (Test-Path (Join-Path $d 'node.exe'))) { Remove-Item $d -Recurse -Force; throw 'node.exe missing after extract' }
New-Item -ItemType File -Force -Path (Join-Path $d '0') | Out-Null
Remove-Item $z -Force -ErrorAction SilentlyContinue
Write-Output OK
""".replace("COMMIT", commit).replace("ZIPNAME", name).replace("ARCH", arch)
        _, o, e = _ps(cli, script, 600)
        if "OK" not in o:
            raise RuntimeError("在主机上解压失败：%s" % ((e or o).strip()[:200] or "未知原因（磁盘满了？）"))
    # 清掉上次卡住的安装锁；再跑一下 node.exe，确认服务端在这台主机上真的能启动
    check = r"""
Get-ChildItem (Join-Path $env:USERPROFILE '.vscode-server\bin') -Filter 'vscode-remote-lock.*.COMMIT' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
& (Join-Path $env:USERPROFILE '.vscode-server\bin\COMMIT\node.exe') --version
""".replace("COMMIT", commit)
    prog("verify", 90, "正在确认服务端能运行…")
    rc, o, e = _ps(cli, check, 60)
    if rc != 0 or not (o or "").strip().startswith("v"):
        raise RuntimeError("服务端装上了但在主机上跑不起来：%s" % ((e or o).strip()[:200] or "node.exe 没有输出"))
    prog("done", 100, "完成")
    return have, "Windows"


def install(alias, prog, allow_windows=True):
    """prog(step, pct, text)。成功返回说明文字，失败抛 RuntimeError（文字直接给用户看）。装完会在主机上跑一下服务端的 node 确认能运行。
    Linux 主机自动装；Windows 主机要 allow_windows（用户点“在 VSCode 打开”时才传），因为安装包 200MB+。"""
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
        if len(parts) >= 2 and parts[0] == "Darwin":
            raise RuntimeError("这台主机是 macOS，暂不支持自动准备（让 VS Code 自己装）。")
        if not allow_windows:
            raise RuntimeError("这台主机不是 Linux，跳过。")
        have, _os = _install_windows(alias, cli, sftp, loc, prog)
        if have:
            return "%s 上本来就装好了这个版本的 VS Code Server，已确认能运行。" % alias
        return "已在 %s 上装好 VS Code Server（%s），已确认能运行。" % (alias, loc.get("version") or commit[:10])
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
    # 跑一下服务端自带的 node，确认真的能启动（系统太旧、缺库时会在这里暴露，而不是等 VS Code 连上去才报“无法建立连接”）
    prog("verify", 90, "正在确认服务端能运行…")
    rc, o, e = sshhosts._run(cli, "sh -c " + shlex.quote('"$HOME"/.vscode-server/bin/%s/node --version' % commit), 30)
    if rc != 0 or not o.strip().startswith("v"):
        raise RuntimeError("服务端装上了但在这台服务器上跑不起来：%s（系统版本太旧或缺系统库？）" % ((e or o).strip()[:200] or "没有输出"))
    prog("done", 100, "完成")
    if have:
        return "%s 上本来就装好了这个版本的 VS Code Server，已确认能运行。回到 VS Code 重新连接就行。" % alias
    return "已在 %s 上装好 VS Code Server（%s），已确认能运行。回到 VS Code 重新连接就行。" % (alias, loc.get("version") or commit[:10])
