# -*- coding: utf-8 -*-
"""生成 web/src/ide/seti/lang-map.json：文件名/扩展名 → VS Code 语言 id。

VS Code 的文件图标（Seti 主题）是三级查找：完整文件名 → 扩展名 → 文件所属“语言”（languageIds）。
语言归属不是写在主题里的，而是各个扩展在 package.json 的 contributes.languages 里声明的（extensions / filenames / filenamePatterns）。
这里把本机 VS Code 的内置扩展 + 已安装扩展声明的语言全部收集起来，前端 file-icon.tsx 用它做第三级查找，和 VS Code 保持一致。

用法：python tools/gen_lang_map.py [VS Code 安装目录]    （默认自动找 %LOCALAPPDATA%\\Programs\\Microsoft VS Code）
VS Code 升级、或装了新语言扩展后重跑一遍即可。主题文件 vs-seti-icon-theme.json / seti.woff 也要从同一份 VS Code 里拷（theme-seti/icons/）。
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "web", "src", "ide", "seti", "lang-map.json")


def find_code():
    if len(sys.argv) > 1:
        return sys.argv[1]
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code")
    hits = glob.glob(os.path.join(base, "*", "resources", "app", "extensions")) + glob.glob(os.path.join(base, "resources", "app", "extensions"))
    if not hits:
        raise SystemExit("找不到 VS Code 的 extensions 目录，请把安装目录作为参数传进来")
    return sorted(hits)[-1]


def langs_of(pkg_path):
    try:
        with open(pkg_path, encoding="utf-8") as f:
            pkg = json.load(f)
        return (pkg.get("contributes") or {}).get("languages") or []
    except Exception:                                    # noqa: BLE001
        return []


def main():
    ext_dir = find_code()
    dirs = sorted(glob.glob(os.path.join(ext_dir, "*", "package.json")))                  # 内置扩展
    user = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".vscode", "extensions", "*", "package.json")))   # 已安装扩展
    ext_map, name_map, patterns = {}, {}, []
    for src, plist in (("内置", dirs), ("已安装", user)):
        for p in plist:
            for lang in langs_of(p):
                lid = lang.get("id")
                if not lid:
                    continue
                for e in lang.get("extensions") or []:
                    e = e.lower().lstrip(".")
                    if e and e not in ext_map:                   # 先到先得：内置的优先于后装的，免得别的扩展抢走 .h 这类共用后缀
                        ext_map[e] = lid
                for n in lang.get("filenames") or []:
                    n = n.lower()
                    if n not in name_map:
                        name_map[n] = lid
                for g in lang.get("filenamePatterns") or []:
                    g = g.lower()
                    if "/" in g.replace("**/", ""):
                        continue                                 # 带目录的模式（如 **/.vscode/*.json）在文件树里没法判断，跳过
                    patterns.append([g.replace("**/", ""), lid])
    out = {"_source": "VS Code %s 的内置扩展 + ~/.vscode/extensions 里声明的语言（contributes.languages）" % os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(ext_dir)))),
           "ext": dict(sorted(ext_map.items())), "names": dict(sorted(name_map.items())), "patterns": patterns}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("扩展名 %d 条，文件名 %d 条，模式 %d 条 → %s" % (len(ext_map), len(name_map), len(patterns), os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
