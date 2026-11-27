# -*- coding: utf-8 -*-
"""引导程序（PyInstaller 的入口，打进 exe 里）。

打包分两层：
  · 运行时（exe）：Python、pywebview、paramiko、Pillow 等第三方库。体积大（三十多 MB），但很少变。
  · 负载包（payload zip）：我们自己的 py 源码 + 界面（web/dist），约 1 MB，每次改功能都会变。
exe 里内置一份负载包；日常更新只下载新的负载包（约 1 MB），解压到 %LOCALAPPDATA%\\MajingToolbox\\payload\\<版本>\\，
下次启动（更新后会自动重启）引导程序就选最新的那份来跑。只有第三方库变了（运行时 id 对不上）才需要换整个 exe。

这个文件不能 import 我们自己的包（majing / api / main），否则它们会被冻进 exe，负载包就失去意义了。
"""
import json
import os
import shutil
import sys
import time
import zipfile


def store_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MajingToolbox", "payload")


def ver_key(s):
    out = []
    for x in str(s).split("."):
        try:
            out.append(int(x))
        except ValueError:
            out.append(0)
    return tuple(out)


def read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def runtime_id():
    """这个 exe 的运行时 id（打包时写进去的）；开发模式没有。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return os.environ.get("MAJING_RUNTIME", "dev")
    try:
        with open(os.path.join(base, "runtime.txt"), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return ""


def installed(store, runtime):
    """已解压好的、和本运行时兼容的负载包：[(版本元组, 版本, 目录)]，新的在前。"""
    out = []
    try:
        names = os.listdir(store)
    except OSError:
        return out
    for n in names:
        d = os.path.join(store, n)
        m = read_json(os.path.join(d, "payload.json"))
        if not m or not os.path.exists(os.path.join(d, ".ok")):
            continue
        if runtime and m.get("runtime") != runtime:
            continue
        out.append((ver_key(m.get("version", "0")), m.get("version", "0"), d))
    out.sort(reverse=True)
    return out


def extract(zip_path, store, version):
    """解压到临时目录再改名，中途失败不会留下半截的目录。返回目录。"""
    d = os.path.join(store, version)
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(store, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    with open(os.path.join(d, ".ok"), "w") as f:
        f.write(str(time.time()))
    return d


def ensure_embedded(store, runtime):
    """exe 里内置的负载包：本机还没有它（或更新的）就解压出来。第一次运行、换了新 exe 之后都走这里。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    zp = os.path.join(base, "payload.zip")
    if not os.path.exists(zp):
        return
    with zipfile.ZipFile(zp) as z:
        m = json.loads(z.read("payload.json").decode("utf-8"))
    have = installed(store, runtime)
    if any(v == m["version"] for _, v, _ in have):
        return
    extract(zp, store, m["version"])


def choose(store, runtime):
    """选要跑的负载包：最新的；上一次启动它没走到“界面加载完成”（有 .launching 却没有 .verified）就跳过，退回更老的。"""
    cands = installed(store, runtime)
    good = [c for c in cands if not (os.path.exists(os.path.join(c[2], ".launching")) and not os.path.exists(os.path.join(c[2], ".verified")))]
    return (good or cands or [None])[0]


def prune(store, keep_dir, keep=3):
    """只留最新的几份，旧的删掉（正在用的那份不删）。"""
    try:
        names = [n for n in os.listdir(store) if os.path.isdir(os.path.join(store, n))]
    except OSError:
        return
    names.sort(key=ver_key, reverse=True)
    for n in names[keep:]:
        d = os.path.join(store, n)
        if os.path.abspath(d) != os.path.abspath(keep_dir):
            shutil.rmtree(d, ignore_errors=True)


def main():
    runtime = runtime_id()
    store = store_dir()
    try:
        ensure_embedded(store, runtime)
    except Exception:
        pass
    pick = choose(store, runtime)
    if pick is None:
        # 开发模式直接跑 boot.py：用源码目录
        here = os.path.dirname(os.path.abspath(__file__))
        pdir, ver = here, "dev"
        py_dir = here
    else:
        _, ver, pdir = pick
        py_dir = os.path.join(pdir, "py")
    sys.path.insert(0, py_dir)
    os.environ["MAJING_PAYLOAD"] = pdir if pick else ""
    os.environ["MAJING_PAYLOAD_VERSION"] = ver
    if pick:
        try:
            with open(os.path.join(pdir, ".launching"), "w") as f:
                f.write(str(time.time()))
            if os.path.exists(os.path.join(pdir, ".verified")):
                prune(store, pdir)
        except OSError:
            pass
    args = sys.argv[1:]
    st = [a for a in args if a.startswith("--selftest")]
    if st:
        sys.exit(selftest(st[0].split("=", 1)[1] if "=" in st[0] else ""))
    import main as app
    app.main()


def selftest(out):
    """打包后的自检：把负载包里所有模块都 import 一遍，缺依赖会在这里报出来。结果写到文件（窗口程序没有控制台）。"""
    import importlib
    import pkgutil
    lines, bad = [], 0
    for name in ("main", "api"):
        try:
            importlib.import_module(name)
            lines.append("ok " + name)
        except Exception as e:                         # noqa: BLE001
            bad += 1
            lines.append("FAIL %s: %s: %s" % (name, type(e).__name__, e))
    try:
        import majing
        for m in pkgutil.walk_packages(majing.__path__, "majing."):
            try:
                importlib.import_module(m.name)
                lines.append("ok " + m.name)
            except Exception as e:                     # noqa: BLE001
                bad += 1
                lines.append("FAIL %s: %s: %s" % (m.name, type(e).__name__, e))
        cdir = os.path.join(os.path.dirname(majing.__file__), "core")
        for fn in sorted(os.listdir(cdir)):
            if fn.endswith(".py") and not fn.startswith("_"):
                name = "majing.core." + fn[:-3]
                try:
                    importlib.import_module(name)
                    lines.append("ok " + name)
                except Exception as e:                 # noqa: BLE001
                    bad += 1
                    lines.append("FAIL %s: %s: %s" % (name, type(e).__name__, e))
        lines.append("version " + getattr(majing, "APP_VERSION", "?"))
    except Exception as e:                             # noqa: BLE001
        bad += 1
        lines.append("FAIL majing: %s" % e)
    lines.append("runtime " + runtime_id())
    lines.append("payload " + os.environ.get("MAJING_PAYLOAD", ""))
    lines.append("RESULT " + ("OK" if not bad else "FAILED %d" % bad))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
