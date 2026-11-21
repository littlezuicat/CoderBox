# -*- coding: utf-8 -*-
"""ffmpeg 放在 %LOCALAPPDATA%\\MajingToolbox\\ffmpeg-8.1；第一次用时从 www.zuicat.cn 下载并校验 sha256。"""
import hashlib
import os
import shutil
import sys
import zipfile

import requests

from .. import APP_VERSION

URL = "https://www.zuicat.cn/toolbox/ffmpeg-8.1-win64.zip"
SHA256 = "567fe0c9f8bae55b6a6678e8c196d9938bcb7af71e821367f5222399a8ff1a32"
SIZE = 79496402


def install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MajingToolbox", "ffmpeg-8.1")


def find():
    """返回 ffmpeg 所在目录；找不到返回 None。顺序：程序旁边 > 已下载的 > 系统 PATH（开发用）。"""
    exe = ".exe" if sys.platform == "win32" else ""
    here = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(sys.argv[0]))
    for d in (here, os.path.join(here, "ffmpeg"), install_dir()):
        if os.path.exists(os.path.join(d, "ffmpeg" + exe)) and os.path.exists(os.path.join(d, "ffprobe" + exe)):
            return d
    f, p = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if f and p:
        return os.path.dirname(f)
    return None


def download(progress=lambda got, total: None, cancelled=lambda: False):
    d = install_dir()
    os.makedirs(os.path.dirname(d), exist_ok=True)
    part = d + ".zip.part"
    sha = hashlib.sha256()
    got = 0
    with requests.get(URL, stream=True, timeout=30, headers={"User-Agent": "MajingToolbox/" + APP_VERSION}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or SIZE)
        with open(part, "wb") as f:
            for blk in r.iter_content(1 << 16):
                if cancelled():
                    raise InterruptedError("已取消")
                f.write(blk)
                sha.update(blk)
                got += len(blk)
                progress(got, total)
    if sha.hexdigest() != SHA256:
        os.remove(part)
        raise IOError("下载的文件校验不通过（可能被网络篡改或没下完整），请重试")
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(part) as z:
        z.extractall(tmp)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    os.remove(part)
