# -*- coding: utf-8 -*-
"""把“原生通信主机”注册给 Chrome / Edge（只写当前用户的注册表 HKCU，不需要管理员）。
浏览器扩展（toolbox\\extension）通过它和保险库对话：
  注册表  HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\<名字>  →  清单 json  →  启动脚本 .bat  →  python nmhost.py
清单里的 allowed_origins 只放我们扩展的 ID（由 manifest.json 里固定的 key 算出），别的扩展连不上。
目前只支持源码运行（开发期）：启动脚本指向 .venv 的 python。打包后要换成独立的小 exe（工具箱本体是无控制台程序，没有标准输入输出）。"""
import base64
import hashlib
import json
import os
import sys

HOST_NAME = "cn.zuicat.majing_pw"
_BROWSERS = {"chrome": r"Software\Google\Chrome\NativeMessagingHosts", "edge": r"Software\Microsoft\Edge\NativeMessagingHosts"}


def _toolbox_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def ext_dir():
    return os.environ.get("MAJING_EXT_DIR") or os.path.join(_toolbox_root(), "extension")


def ext_id():
    """扩展 ID：manifest.json 里的 key（公钥）的 SHA-256 前 128 位，0-f 映射成 a-p。"""
    with open(os.path.join(ext_dir(), "manifest.json"), "r", encoding="utf-8") as f:
        key = json.load(f)["key"]
    h = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)


def nm_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox", "nm")
    os.makedirs(d, exist_ok=True)
    return d


def _python():
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        exe = os.path.join(os.path.dirname(exe), "python.exe")
    return exe


def write_files():
    """生成启动脚本和清单，返回清单路径。"""
    d = nm_dir()
    script = os.path.join(_toolbox_root(), "py", "nmhost.py")
    bat = os.path.join(d, "majing_nm.bat")
    with open(bat, "w", encoding="mbcs", newline="\r\n") as f:
        f.write('@echo off\n"%s" "%s" %%*\n' % (_python(), script))
    man = os.path.join(d, HOST_NAME + ".json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump({"name": HOST_NAME, "description": "码境密码（码境工具箱）", "path": bat, "type": "stdio",
                   "allowed_origins": ["chrome-extension://%s/" % ext_id()]}, f, ensure_ascii=False, indent=2)
    return man


def _reg_get(sub):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub + "\\" + HOST_NAME) as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def status():
    man = os.path.join(nm_dir(), HOST_NAME + ".json")
    out = {"ext_dir": ext_dir(), "ext_id": ext_id(), "files": os.path.exists(man)}
    for b, sub in _BROWSERS.items():
        v = _reg_get(sub)
        out[b] = bool(v) and os.path.normcase(v) == os.path.normcase(man)
    return out


def register(browsers=("chrome", "edge")):
    import winreg
    man = write_files()
    for b in browsers:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _BROWSERS[b] + "\\" + HOST_NAME) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, man)
    return status()


def unregister():
    import winreg
    for sub in _BROWSERS.values():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub + "\\" + HOST_NAME)
        except OSError:
            pass
    return status()
