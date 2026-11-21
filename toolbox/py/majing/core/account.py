# -*- coding: utf-8 -*-
"""码境账号（code.zuicat.cn，即 CoderLand 的账号）绑定。

跳转授权：在浏览器里打开码境的授权页，登录并点“授权”，工具箱从服务器领到一条独立的登录凭证（会话 cookie），
全程不经手密码，随后用它读取昵称头像。
凭证单独存放在 %APPDATA%\\MajingToolbox\\account.bin，Windows 上用 DPAPI 加密（只有当前系统用户能解开）。
解绑时会通知服务器作废这条凭证。"""
import base64
import json
import os
import sys

import requests

BASE = "https://code.zuicat.cn"
COOKIE = "coderland_session"


def _path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "account.bin")


# ---------------------------------------------------------------- DPAPI
def _protect(data):
    if sys.platform != "win32":
        return b"P0" + data
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "majing", None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    try:
        return b"W1" + ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _unprotect(blob):
    tag, body = blob[:2], blob[2:]
    if tag == b"P0":
        return body
    if tag != b"W1" or sys.platform != "win32":
        raise ValueError("bad blob")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = Blob(len(body), ctypes.cast(ctypes.create_string_buffer(body, len(body)), ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---------------------------------------------------------------- 凭证文件
def _save(token):
    with open(_path(), "wb") as f:
        f.write(_protect(token.encode("utf-8")))


def _load():
    try:
        with open(_path(), "rb") as f:
            return _unprotect(f.read()).decode("utf-8")
    except Exception:
        return None


def _forget():
    try:
        os.remove(_path())
    except OSError:
        pass


# ---------------------------------------------------------------- 接口
def _headers(ua):
    return {"User-Agent": "MajingToolbox/" + ua, "Accept": "application/json", "Origin": BASE}


def _json(r):
    try:
        return r.json()
    except Exception:
        return {}


def _profile(token, ua):
    r = requests.get(BASE + "/api/auth/me", timeout=10, headers=_headers(ua), cookies={COOKIE: token})
    if r.status_code == 401:
        return None
    r.raise_for_status()
    u = _json(r).get("user") or {}
    if not u:
        return None
    avatar = u.get("avatar_url") or ""
    return {"name": u.get("display_name") or u.get("username") or "", "username": u.get("username") or "",
            "avatar": (BASE + avatar) if avatar.startswith("/") else avatar, "csrf": u.get("csrf_token") or ""}


def status(ua):
    """当前绑定状态。联网失败时只说“暂时无法确认”，不当成已解绑（凭证留着）。"""
    token = _load()
    if not token:
        return {"bound": False}
    try:
        p = _profile(token, ua)
    except requests.RequestException:
        return {"bound": True, "offline": True}
    if not p:
        _forget()
        return {"bound": False, "expired": True}
    p.pop("csrf", None)
    return {"bound": True, **p}


def start(ua):
    """发起“跳转授权”：{ok, device_code, user_code, url}。浏览器里打开 url，用户在码境点“授权”。"""
    import socket
    try:
        name = "克劳德工具箱 · " + socket.gethostname()
    except Exception:
        name = "克劳德工具箱"
    try:
        r = requests.post(BASE + "/api/auth/device/start", json={"name": name}, timeout=10, headers=_headers(ua))
    except requests.RequestException:
        return {"ok": False, "error": "连不上码境服务器，请检查网络。"}
    j = _json(r)
    if not r.ok or not j.get("device_code"):
        return {"ok": False, "error": j.get("error") or "服务器暂不支持授权登录（%d）。" % r.status_code}
    return {"ok": True, "device_code": j["device_code"], "user_code": j["user_code"], "url": j["verification_url"],
            "expires_in": j.get("expires_in", 600)}


def poll(device_code, ua):
    """轮询一次：pending / denied / expired / error / ok（ok 时已保存凭证并带回账号信息）。"""
    try:
        r = requests.post(BASE + "/api/auth/device/poll", json={"device_code": device_code}, timeout=10, headers=_headers(ua))
    except requests.RequestException:
        return {"state": "pending"}          # 网络抖动：继续等
    j = _json(r)
    if r.status_code == 429:
        return {"state": "pending"}
    st = j.get("status")
    if st == "ok" and j.get("token"):
        try:
            p = _profile(j["token"], ua)
        except requests.RequestException:
            p = None
        if not p:
            return {"state": "error", "error": "授权成功，但读取账号信息失败，请重试。"}
        _save(j["token"])
        p.pop("csrf", None)
        return {"state": "ok", "status": {"bound": True, **p}}
    if st in ("pending", "denied", "expired"):
        return {"state": st}
    return {"state": "error", "error": j.get("error") or "授权失败。"}


def unbind(ua):
    token = _load()
    if token:
        try:
            p = _profile(token, ua)
            if p:
                requests.post(BASE + "/api/auth/logout", timeout=10, cookies={COOKIE: token},
                              headers={**_headers(ua), "X-CSRF-Token": p["csrf"]})
        except requests.RequestException:
            pass          # 服务器没通知到也没关系，本地凭证照删；凭证两周后自动过期
    _forget()
    return {"ok": True}
