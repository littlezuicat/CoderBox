# -*- coding: utf-8 -*-
"""ffmpeg 放在 %LOCALAPPDATA%\\MajingToolbox\\ffmpeg-8.1；进入工具箱时自动从 www.zuicat.cn 下载并校验 sha256。
下载的是 .tar.xz（x86 BCJ + LZMA2 极限压缩，tools/pack_ffmpeg.py 生成），比原来的 zip 小四成，用标准库 tarfile/lzma 解压。"""
import hashlib
import os
import shutil
import sys
import tarfile

import requests

from .. import APP_VERSION

URL = os.environ.get("MAJING_FFMPEG_URL") or "https://www.zuicat.cn/toolbox/ffmpeg-8.1-win64.tar.xz"      # 测试时可用环境变量指到本地服务器
SHA256 = "d2e5906655a89ea3b57a8ca2d64ed13f82e11e6e5b12e7caaea59065abba487a"
SIZE = 47004496


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
    part = d + ".tar.xz.part"
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
    os.makedirs(tmp, exist_ok=True)
    with tarfile.open(part, "r:xz") as t:
        for m in t.getmembers():
            if not m.isfile() or m.name != os.path.basename(m.name):          # 只收平铺的普通文件，路径里有目录的一律拒绝
                raise IOError("下载的压缩包里有不认识的内容，已放弃")
            with t.extractfile(m) as fi, open(os.path.join(tmp, m.name), "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    os.remove(part)
