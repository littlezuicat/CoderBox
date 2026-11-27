# -*- coding: utf-8 -*-
"""把 ffmpeg 目录（ffmpeg.exe、ffprobe.exe 和它们的 dll）重新打成 .tar.xz：x86 BCJ 过滤 + LZMA2 极限压缩，
比原来的 zip（deflate）小一大截；客户端用标准库 tarfile/lzma 解压，不需要额外依赖。
用法：python tools/pack_ffmpeg.py <ffmpeg 目录> <输出.tar.xz>      输出 sha256 和大小，填进 py/majing/core/ffsetup.py"""
import hashlib
import lzma
import os
import sys
import tarfile
import time

src, out = sys.argv[1], sys.argv[2]
KEEP = ("ffmpeg.exe", "ffprobe.exe", "LICENSE.txt", "README.txt")
names = sorted(n for n in os.listdir(src) if n in KEEP or n.lower().endswith(".dll"))
t0 = time.time()
filters = [{"id": lzma.FILTER_X86}, {"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": 128 << 20}]
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with lzma.open(out, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, filters=filters) as xz:
    with tarfile.open(fileobj=xz, mode="w") as tar:
        for n in names:
            ti = tar.gettarinfo(os.path.join(src, n), arcname=n)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            with open(os.path.join(src, n), "rb") as f:
                tar.addfile(ti, f)
            print("  +", n, ti.size, flush=True)
h = hashlib.sha256()
with open(out, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
        h.update(b)
print("文件 %s\n大小 %d 字节（%.1f MB）\nsha256 %s\n用时 %.0f 秒" % (out, os.path.getsize(out), os.path.getsize(out) / 1e6, h.hexdigest(), time.time() - t0))
