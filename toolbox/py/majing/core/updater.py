# -*- coding: utf-8 -*-
"""自动更新：启动后台查 www.zuicat.cn/toolbox/version.json，有新版就直接下载（校验大小和 SHA-256）、
替换自己、重新启动，不再询问。version.json 格式和旧版（C#）一致，所以旧版也能直接更新到这个版本。"""
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

BASE_URL = "https://www.zuicat.cn/toolbox/"      # 以 / 结尾；测试时可改成本地服务器
EXE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}\.exe$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_version(s):
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4])


def update_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MajingToolbox", "update")


def exe_path():
    """正在运行的程序文件；开发模式（没打包）返回 None。"""
    return sys.executable if getattr(sys, "frozen", False) else None


class UpdateInfo:
    def __init__(self, version, exe, sha256, size, notes, url):
        self.version, self.exe, self.sha256, self.size, self.notes, self.url = version, exe, sha256, size, notes, url


def check(current=APP_VERSION):
    """有更新返回 UpdateInfo，已是最新返回 None；网络或格式有问题抛异常。"""
    r = requests.get(BASE_URL + "version.json", params={"t": int(time.time())}, timeout=10,
                     headers={"User-Agent": "MajingToolbox/" + current, "Cache-Control": "no-cache"})
    r.raise_for_status()
    d = json.loads(r.content[:16384].decode("utf-8"))
    info = UpdateInfo(d["version"], str(d["exe"]), str(d["sha256"]).lower(), int(d["size"]), str(d.get("notes", ""))[:300], BASE_URL + str(d["exe"]))
    if not EXE_RE.match(info.exe) or not SHA_RE.match(info.sha256) or not (100000 <= info.size <= 500 << 20):
        raise ValueError("更新信息格式不对")
    return info if parse_version(info.version) > parse_version(current) else None


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


def relaunch(args):
    """启动（已经替换好的）新版本；新进程带 --after-update=旧进程号，等本进程退出后再开始干活
    （远程连接组件是单实例的，必须等旧的先退出）。调用者随后要退出程序。"""
    exe = exe_path()
    if not exe:
        raise RuntimeError("开发模式不能重启")
    cmd = [exe, "--after-update=%d" % os.getpid()] + [a for a in args if not a.startswith("--after-update=")]
    subprocess.Popen(cmd, cwd=os.path.dirname(exe), close_fds=True)


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
