#!/usr/bin/env python3
"""VS Code Server 镜像：把微软的 VS Code Server 安装包预取到本机，放进 nginx 的静态目录，供码境工具箱下载。

为什么要有：用户电脑直接从微软下载 230MB 的安装包，国内网络常常只有几百 KB/s；服务器后台慢慢拉一次（断点续传），
所有用户就都从 https://www.zuicat.cn/toolbox/vscode-server/<提交号>/vscode-server-linux-<架构>.tar.gz 下，没有就回退微软。

用法：
  vsc-mirror.py latest            拉取最新稳定版（x64 + arm64），清理旧版本（定时器每天跑一次）
  vsc-mirror.py commit <提交号>   拉取指定版本（用户的 VS Code 不是最新版时手动补）
环境变量：VSC_MIRROR_DIR 存放目录（默认 /var/www/toolbox/vscode-server）、VSC_MIRROR_KEEP 保留几个版本（默认 4）。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.environ.get("VSC_MIRROR_DIR", "/var/www/toolbox/vscode-server")
KEEP = int(os.environ.get("VSC_MIRROR_KEEP", "4"))
ARCHES = ("x64", "arm64")
UA = "Mozilla/5.0 (majing-toolbox vsc-mirror)"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def log(*a):
    print(time.strftime("%F %T"), *a, flush=True)


def latest_commit():
    req = urllib.request.Request("https://update.code.visualstudio.com/api/update/linux-x64/stable/latest", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    return j["version"], j.get("productVersion", "")


def valid(path):
    try:
        if os.path.getsize(path) < 20_000_000:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def fetch(commit, arch):
    d = os.path.join(ROOT, commit)
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "vscode-server-linux-%s.tar.gz" % arch)
    if valid(dest):
        log("已有", commit[:10], arch)
        return True
    part = dest + ".part"
    url = "https://update.code.visualstudio.com/commit:%s/server-linux-%s/stable" % (commit, arch)
    for attempt in range(1, 41):
        log("下载", commit[:10], arch, "第", attempt, "次（接着已有的部分下）")
        # -C - 断点续传；速度低于 20KB/s 持续 2 分钟就放弃这一次重来
        rc = subprocess.run(["curl", "-fL", "-A", UA, "-C", "-", "--connect-timeout", "30", "--speed-limit", "20000", "--speed-time", "120", "-o", part, url]).returncode
        if rc == 0:
            break
        if rc == 33 and valid(part):                             # 416：已经下完
            break
        if rc == 22:                                             # HTTP 4xx：这个提交号/架构微软那边没有，别重试了
            log("微软没有这个版本：", commit[:10], arch)
            return False
        time.sleep(min(10 * attempt, 60))
    else:
        log("放弃（保留已下的部分，下次接着下）", commit[:10], arch)
        return False
    if not valid(part):
        os.remove(part)
        log("下载到的文件不是有效的 gzip，已删除", commit[:10], arch)
        return False
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    os.replace(part, dest)
    with open(dest + ".sha256", "w") as f:
        f.write("%s  %s\n" % (h.hexdigest(), os.path.basename(dest)))
    os.chmod(dest, 0o644)
    log("完成", commit[:10], arch, "%.1f MB" % (os.path.getsize(dest) / 1048576))
    return True


def prune(keep_commit):
    dirs = [x for x in os.listdir(ROOT) if COMMIT_RE.match(x) and os.path.isdir(os.path.join(ROOT, x))]
    dirs.sort(key=lambda x: os.path.getmtime(os.path.join(ROOT, x)), reverse=True)
    for x in dirs[KEEP:]:
        if x != keep_commit:
            shutil.rmtree(os.path.join(ROOT, x), ignore_errors=True)
            log("清理旧版本", x[:10])


def write_index(latest=""):
    idx = {"latest": latest, "updated": int(time.time()), "commits": {}}
    for x in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, x)
        if COMMIT_RE.match(x) and os.path.isdir(p):
            idx["commits"][x] = {a: os.path.getsize(os.path.join(p, "vscode-server-linux-%s.tar.gz" % a)) for a in ARCHES if valid(os.path.join(p, "vscode-server-linux-%s.tar.gz" % a))}
    tmp = os.path.join(ROOT, "index.json.tmp")
    with open(tmp, "w") as f:
        json.dump(idx, f, indent=1)
    os.replace(tmp, os.path.join(ROOT, "index.json"))
    os.chmod(os.path.join(ROOT, "index.json"), 0o644)


def main():
    os.makedirs(ROOT, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "latest"
    if mode == "commit" and len(sys.argv) > 2:
        commits, latest = [sys.argv[2].lower()], ""
        if not COMMIT_RE.match(commits[0]):
            sys.exit("提交号应该是 40 位十六进制")
    else:
        c, ver = latest_commit()
        log("最新稳定版", ver, c)
        commits, latest = [c], c
    ok = all([fetch(c, a) for c in commits for a in ARCHES])
    if latest:
        prune(latest)
    write_index(latest)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
