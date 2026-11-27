# -*- coding: utf-8 -*-
"""生成打包需要的几样东西（输出到 stage/）：
  payload-<版本>.zip   负载包：py 源码 + 界面（web/dist），约 1 MB；exe 里内置一份，日常更新只下载它
  runtime.txt          运行时 id：由“第三方依赖 + 打包配置 + 引导程序 + 被用到的模块清单”算出的哈希。
                       id 没变 = 现有的 exe 还能跑新负载包 = 这次发布只需要传负载包；变了 = 要重新打整个 exe
  hiddenimports.json   负载包里用到的所有模块名（含标准库）：我们自己的代码不再被冻进 exe，PyInstaller 看不到它们的 import，要在 spec 里补上
用法：python tools/build_payload.py            （在 toolbox 目录下跑）"""
import ast
import hashlib
import json
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PY = os.path.join(ROOT, "py")
WEB = os.path.join(ROOT, "web", "dist")
OUT = os.path.join(ROOT, "stage")
OWN = {"majing", "api", "main", "boot"}
SKIP_DIRS = {"__pycache__", "tests"}
SKIP_FILES = {"boot.py", "majing-remote.exe"}        # 引导程序在 exe 里；远程组件已不随程序启动，不打包


def app_version():
    with open(os.path.join(PY, "majing", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'APP_VERSION = "(\d+\.\d+\.\d+)"', f.read()).group(1)


def payload_files():
    for base, rel_root in ((PY, "py"), (WEB, os.path.join("web", "dist"))):
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                if fn in SKIP_FILES or fn.endswith((".pyc", ".log")):
                    continue
                full = os.path.join(dp, fn)
                yield full, os.path.join(rel_root, os.path.relpath(full, base)).replace("\\", "/")


def scan_imports():
    names = set()
    for full, arc in payload_files():
        if not arc.startswith("py/") or not full.endswith(".py"):
            continue
        try:
            tree = ast.parse(open(full, encoding="utf-8").read(), full)
        except SyntaxError as e:
            sys.exit("语法错误 %s: %s" % (full, e))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
                for a in node.names:
                    names.add(node.module + "." + a.name)
    return sorted(n for n in names if n.split(".")[0] not in OWN)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if not os.path.isdir(WEB):
        sys.exit("先构建界面：cd web; npm run build")
    os.makedirs(OUT, exist_ok=True)
    ver = app_version()
    mods = scan_imports()
    h = hashlib.sha256()
    for name in ("requirements.lock", "requirements.txt", "MajingToolbox.spec"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            h.update(open(p, "rb").read().replace(b"\r\n", b"\n"))
    h.update(open(os.path.join(PY, "boot.py"), "rb").read().replace(b"\r\n", b"\n"))
    h.update("\n".join(mods).encode("utf-8"))
    h.update(("py%d.%d" % sys.version_info[:2]).encode())
    runtime = h.hexdigest()[:16]
    with open(os.path.join(OUT, "runtime.txt"), "w", encoding="ascii") as f:
        f.write(runtime)
    with open(os.path.join(OUT, "hiddenimports.json"), "w", encoding="utf-8") as f:
        json.dump(mods, f, ensure_ascii=False, indent=0)
    zpath = os.path.join(OUT, "payload-%s.zip" % ver)
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("payload.json", json.dumps({"version": ver, "runtime": runtime}))
        for full, arc in sorted(payload_files(), key=lambda x: x[1]):
            z.write(full, arc)
            n += 1
    # 固定名字的副本：PyInstaller 打包时内置这一份
    with open(zpath, "rb") as f, open(os.path.join(OUT, "payload.zip"), "wb") as g:
        data = f.read()
        g.write(data)
    print(json.dumps({"version": ver, "runtime": runtime, "zip": zpath, "size": len(data), "sha256": sha(data), "files": n, "modules": len(mods)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
