# -*- coding: utf-8 -*-
"""自动更新：启动后台查 www.zuicat.cn/toolbox/version.json，有新版就直接下载（校验大小和 SHA-256）、重新启动，不再询问。

两种更新：
  · 增量（日常）：version.json 里的 payload 是新的“负载包”（我们自己的 py 源码 + 界面，约 0.5 MB）。运行时 id（打包时写进 exe 的）
    和负载包要求的一致，就只下载它，解压到 %LOCALAPPDATA%\\MajingToolbox\\payload\\<版本>\\，重启后引导程序（boot.py）会用它。
  · 整包（第三方依赖变了才需要）：下载新的 exe，换掉自己。version.json 顶层的 exe/size/sha256 永远描述最新的整包，
    格式和旧版（C#）一致，所以老版本也能直接更新到这个版本。
version.json：{version, exe, size, sha256, exe_version?, runtime?, payload?: {file, size, sha256, runtime}, notes}"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

import requests

from .. import APP_VERSION

BASE_URL = os.environ.get("MAJING_UPDATE_BASE") or "https://www.zuicat.cn/toolbox/"      # 以 / 结尾；测试时用环境变量 MAJING_UPDATE_BASE 指到本地服务器
EXE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}\.exe$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PAYLOAD_RE = re.compile(r"^payload-\d+\.\d+\.\d+\.zip$")


def parse_version(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4])


def update_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MajingToolbox", "update")


def exe_path():
    """正在运行的程序文件；开发模式（没打包）返回 None。"""
    return sys.executable if getattr(sys, "frozen", False) else None


def runtime_id():
    """正在运行的这个 exe 的运行时 id（boot.py 读的同一个文件）。开发模式返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    try:
        with open(os.path.join(sys._MEIPASS, "runtime.txt"), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def payload_store():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MajingToolbox", "payload")


class UpdateInfo:
    def __init__(self, version, exe, sha256, size, notes, url, exe_version=None, payload=None):
        self.version, self.exe, self.sha256, self.size, self.notes, self.url = version, exe, sha256, size, notes, url
        self.exe_version = exe_version or version         # 整包里内置的版本（没写就当和 version 一样）
        self.payload = payload                             # {file, size, sha256, runtime, url} 或 None


def check(current=APP_VERSION):
    """有更新返回 UpdateInfo，已是最新返回 None；网络或格式有问题抛异常。"""
    r = requests.get(BASE_URL + "version.json", params={"t": int(time.time())}, timeout=10,
                     headers={"User-Agent": "MajingToolbox/" + current, "Cache-Control": "no-cache"})
    r.raise_for_status()
    d = json.loads(r.content[:16384].decode("utf-8"))
    info = UpdateInfo(d["version"], str(d["exe"]), str(d["sha256"]).lower(), int(d["size"]), str(d.get("notes", ""))[:300], BASE_URL + str(d["exe"]),
                      str(d["exe_version"]) if d.get("exe_version") else None)
    if not EXE_RE.match(info.exe) or not SHA_RE.match(info.sha256) or not (100000 <= info.size <= 500 << 20):
        raise ValueError("更新信息格式不对")
    pl = d.get("payload")
    if isinstance(pl, dict):
        p = {"file": str(pl.get("file", "")), "size": int(pl.get("size", 0)), "sha256": str(pl.get("sha256", "")).lower(), "runtime": str(pl.get("runtime", ""))}
        if PAYLOAD_RE.match(p["file"]) and SHA_RE.match(p["sha256"]) and 1000 <= p["size"] <= 100 << 20 and p["runtime"]:
            p["url"] = BASE_URL + "payload/" + p["file"]
            info.payload = p
    return info if parse_version(info.version) > parse_version(current) else None


def plan(info, current=APP_VERSION):
    """怎么更新：'payload' 只下载负载包；'exe' 下载整包；None 没什么可更新的。"""
    rt = runtime_id()
    if info.payload and rt and info.payload["runtime"] == rt:
        return "payload"
    if parse_version(info.exe_version) > parse_version(current):
        return "exe"                # 整包里的版本比现在新，换整包才有意义（否则会反复下载同一个整包）
    return None


def download_payload(info, progress=lambda got, total: None, cancelled=lambda: False):
    """下载负载包、校验（大小、SHA-256、zip 完整、里面的版本和运行时 id 对得上），解压到负载包目录。返回目录。"""
    import shutil
    import zipfile
    p = info.payload
    os.makedirs(update_dir(), exist_ok=True)
    part = os.path.join(update_dir(), p["file"] + ".part")
    sha = hashlib.sha256()
    got = 0
    with requests.get(p["url"], stream=True, timeout=30, headers={"User-Agent": "MajingToolbox/" + APP_VERSION}) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for blk in r.iter_content(1 << 16):
                if cancelled():
                    raise InterruptedError("已取消")
                f.write(blk)
                sha.update(blk)
                got += len(blk)
                progress(got, p["size"])
    if got != p["size"]:
        raise IOError("下载不完整（%d / %d 字节），请重试" % (got, p["size"]))
    if sha.hexdigest() != p["sha256"]:
        raise IOError("下载的更新包校验不通过，已放弃，请重试")
    with zipfile.ZipFile(part) as z:
        if z.testzip() is not None:
            raise IOError("更新包损坏")
        meta = json.loads(z.read("payload.json").decode("utf-8"))
    if meta.get("version") != info.version or meta.get("runtime") != p["runtime"]:
        raise IOError("更新包的版本信息对不上")
    store = payload_store()
    d = os.path.join(store, info.version)
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(store, exist_ok=True)
    with zipfile.ZipFile(part) as z:
        z.extractall(tmp)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    with open(os.path.join(d, ".ok"), "w") as f:
        f.write(str(time.time()))
    os.remove(part)
    return d


def download(info, progress=lambda got, total: None, cancelled=lambda: False):
    """下载并校验，返回本地文件路径。"""
    os.makedirs(update_dir(), exist_ok=True)
    final = os.path.join(update_dir(), "MajingToolbox-%s.exe" % info.version)
    part = final + ".part"
    sha = hashlib.sha256()
    got = 0
    with requests.get(info.url, stream=True, timeout=30, headers={"User-Agent": "MajingToolbox/" + APP_VERSION}) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for blk in r.iter_content(1 << 16):
                if cancelled():
                    raise InterruptedError("已取消")
                f.write(blk)
                sha.update(blk)
                got += len(blk)
                progress(got, info.size)
    if got != info.size:
        raise IOError("下载不完整（%d / %d 字节），请重试" % (got, info.size))
    if sha.hexdigest() != info.sha256:
        raise IOError("下载的文件校验不通过（可能被网络篡改或没下完整），已放弃，请重试")
    with open(part, "rb") as f:
        if f.read(2) != b"MZ":
            raise IOError("下载的不是可执行文件")
    if os.path.exists(final):
        os.remove(final)
    os.replace(part, final)
    return final


def replace(new_file, target):
    """把 new_file 换到 target 的位置：正在运行的 exe 不能覆盖但能改名，所以先改名成 .old 再放新的。失败时原样恢复。"""
    old = target + ".old"
    try:
        if os.path.exists(old):
            os.remove(old)
    except OSError:
        pass
    os.rename(target, old)
    try:
        import shutil
        shutil.copyfile(new_file, target)
    except Exception:
        try:
            if os.path.exists(target):
                os.remove(target)
            os.rename(old, target)
        except OSError:
            pass
        raise


def fresh_env():
    """启动“另一个”本程序实例用的环境变量。PyInstaller 单文件 exe 会把解压目录（_MEI…）记在环境变量里，子进程如果继承，
    会误以为自己是父进程的分身、共用父进程的解压目录；父进程一退出就把目录删了，新进程就报找不到 WebView2 的 dll。
    清掉这些变量并设 PYINSTALLER_RESET_ENVIRONMENT=1，让新进程自己重新解压。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def relaunch(args):
    """启动（已经替换好的）新版本；新进程带 --after-update=旧进程号，等本进程退出后再开始干活
    （远程连接组件是单实例的，必须等旧的先退出）。调用者随后要退出程序。"""
    exe = exe_path()
    if not exe:
        raise RuntimeError("开发模式不能重启")
    cmd = [exe, "--after-update=%d" % os.getpid()] + [a for a in args if not a.startswith("--after-update=")]
    subprocess.Popen(cmd, cwd=os.path.dirname(exe), close_fds=True, env=fresh_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def after_start(args):
    """启动时调用：如果是更新后重启的，等旧进程退出；顺手清掉 .old 和下载缓存。"""
    for a in args:
        if a.startswith("--after-update="):
            try:
                pid = int(a.split("=", 1)[1])
            except ValueError:
                continue
            t0 = time.time()
            while time.time() - t0 < 20 and _alive(pid):
                time.sleep(0.2)

    def clean():
        exe = exe_path()
        if exe:
            for _ in range(20):
                try:
                    if os.path.exists(exe + ".old"):
                        os.remove(exe + ".old")
                    break
                except OSError:
                    time.sleep(0.5)
        try:
            d = update_dir()
            for n in os.listdir(d):
                try:
                    os.remove(os.path.join(d, n))
                except OSError:
                    pass
        except OSError:
            pass
    threading.Thread(target=clean, daemon=True).start()


def _alive(pid):
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)     # SYNCHRONIZE
        if not h:
            return False
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0x102                                                # WAIT_TIMEOUT：还活着
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
