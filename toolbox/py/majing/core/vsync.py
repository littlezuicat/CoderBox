# -*- coding: utf-8 -*-
"""保险库同步（到 www.zuicat.cn，用码境账号当身份）。

· 服务器只存密文：整库用一把随机的“同步密钥”K 做 AES-256-GCM 加密后上传；K 再用【主密码】（Argon2id 派生）加密成 wrap 一起放在服务器上。
  所以服务器和别人都看不到内容；忘了主密码，别的设备就解不开（本机因为有 K，还能用）。
· 这台电脑开启同步后，K 用 Windows DPAPI 存在本机（vaultsync.bin），日常同步、使用都不需要主密码；
  主密码只在“新设备第一次开启同步”时要输入一次。
· 合并：同一条取修改时间较新的；删除会留“删除记录”同步给别的设备。冲突（别的设备刚上传过）自动重拉合并再传。
· 身份：请求头带码境账号的登录凭证，服务器那边拿它去码境核对是谁。凭证只发给同步服务（HTTPS）。
内容不写日志。"""
import base64
import hashlib
import json
import logging
import os
import threading
import time

import requests
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from majing import APP_VERSION
from majing.core import account
from majing.core.vault import VaultError, vault

log = logging.getLogger("majing.vault")
WRAP_AAD = b"majing-sync-wrap-v1"
BLOB_AAD = b"majing-sync-blob-v1"
MAX_BYTES = 6 * 1024 * 1024
_lock = threading.RLock()


class SyncError(VaultError):
    pass


def base_url():
    return (os.environ.get("MAJING_SYNC_URL") or "https://www.zuicat.cn/toolbox/api/vault").rstrip("/")


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    return base64.b64decode(s.encode("ascii"))


# ---------------------------------------------------------------- 本机状态
def _state_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "vaultsync.bin")


def _load():
    try:
        with open(_state_path(), "rb") as f:
            st = json.loads(account._unprotect(f.read()).decode("utf-8"))
        st["k"] = _unb64(st["k"])
        return st
    except Exception:                                        # noqa: BLE001
        return None


def _save(st):
    s = dict(st)
    s["k"] = _b64(st["k"])
    tmp = _state_path() + ".tmp"
    with open(tmp, "wb") as f:
        f.write(account._protect(json.dumps(s).encode("utf-8")))
    os.replace(tmp, _state_path())


def _forget():
    try:
        os.remove(_state_path())
    except OSError:
        pass


def status():
    st = _load()
    return {"account": bool(account.token()), "enabled": bool(st), "user": (st or {}).get("user", ""), "last_ok": (st or {}).get("last_ok", 0), "url": base_url()}


# ---------------------------------------------------------------- 加密
def _kdf(password, salt, t=3, m=64, p=4):
    return Argon2id(salt=salt, length=32, iterations=t, lanes=p, memory_cost=m * 1024).derive(password.encode("utf-8"))


def make_wrap(password, k):
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(password, salt)).encrypt(nonce, k, WRAP_AAD)
    return {"kdf": "argon2id", "t": 3, "m": 64, "p": 4, "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct)}


def open_wrap(password, wrap):
    try:
        key = _kdf(password, _unb64(wrap["salt"]), int(wrap["t"]), int(wrap["m"]), int(wrap["p"]))
        return AESGCM(key).decrypt(_unb64(wrap["nonce"]), _unb64(wrap["ct"]), WRAP_AAD)
    except InvalidTag:
        raise SyncError("主密码不对。")
    except Exception:                                        # noqa: BLE001
        raise SyncError("服务器上的同步数据格式不对。")


def seal(k, snap):
    nonce = os.urandom(12)
    raw = json.dumps(snap, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"v": 1, "nonce": _b64(nonce), "ct": _b64(AESGCM(k).encrypt(nonce, raw, BLOB_AAD))}


def unseal(k, blob):
    try:
        return json.loads(AESGCM(k).decrypt(_unb64(blob["nonce"]), _unb64(blob["ct"]), BLOB_AAD).decode("utf-8"))
    except Exception:                                        # noqa: BLE001
        raise SyncError("服务器上的保险库解不开（可能是在别的设备重新开启过同步）。请关闭同步后用主密码重新开启。")


def _canon(snap):
    return hashlib.sha256(json.dumps({"items": snap.get("items", []), "deleted": snap.get("deleted", {})}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 网络
def _req(method, body=None):
    tok = account.token()
    if not tok:
        raise SyncError("还没有登录码境账号。请先到“设置”里登录。")
    try:
        r = requests.request(method, base_url(), json=body, timeout=20,
                             headers={"Authorization": "Bearer " + tok, "User-Agent": "MajingToolbox/" + APP_VERSION, "Accept": "application/json"})
    except requests.RequestException:
        raise SyncError("连不上服务器，请检查网络。")
    try:
        j = r.json()
    except ValueError:
        j = None
    if r.status_code == 401:
        raise SyncError("码境账号登录已失效，请到“设置”里重新登录。")
    if not isinstance(j, dict):
        raise SyncError("服务器上还没有部署保险库同步服务（%d）。" % r.status_code)
    if r.status_code == 409:
        return 409, j
    if r.status_code >= 400:
        raise SyncError(j.get("error") or "服务器出错（%d）。" % r.status_code)
    return r.status_code, j


def probe():
    """服务器上是不是已经有这个账号的保险库。"""
    _, j = _req("GET")
    return {"exists": bool(j.get("exists")), "user": j.get("user", "")}


# ---------------------------------------------------------------- 开启 / 同步 / 关闭
def enable(password, confirm=None):
    """第一台设备：设主密码（要两次）并上传；新设备：输入已有的主密码。"""
    with _lock:
        _, j = _req("GET")
        user = j.get("user", "")
        if j.get("exists"):
            k = open_wrap(password, j["wrap"])
            wrap, rev = j["wrap"], int(j.get("rev", 0))
            mode = "joined"
        else:
            if len(password) < 8:
                raise SyncError("主密码至少 8 位。")
            if confirm is not None and confirm != password:
                raise SyncError("两次输入的主密码不一样。")
            k, wrap, rev, mode = os.urandom(32), None, 0, "created"
            wrap = make_wrap(password, k)
        _save({"user": user, "k": k, "wrap": wrap, "rev": rev, "last_ok": 0})
        log.info("保险库同步：开启（%s）", mode)
        r = sync()
        return {**r, "mode": mode}


def sync():
    """拉 → 合并 → 需要时上传。返回 {changed(本机内容有更新), pushed}。"""
    with _lock:
        st = _load()
        if not st:
            raise SyncError("还没有开启同步。")
        changed = pushed = False
        for _ in range(4):
            _, j = _req("GET")
            if j.get("user") and st.get("user") and j["user"] != st["user"]:
                raise SyncError("码境账号和开启同步时不是同一个。请关闭同步后重新开启。")
            rev = int(j.get("rev", 0)) if j.get("exists") else 0
            remote = None
            if j.get("exists"):
                remote = unseal(st["k"], j["blob"])
                if vault.merge(remote):
                    changed = True
            snap = vault.snapshot()
            if remote is not None and _canon(remote) == _canon(snap):
                break
            blob = seal(st["k"], snap)
            if len(json.dumps(blob)) > MAX_BYTES:
                raise SyncError("保险库太大，超出同步上限。")
            code, r = _req("PUT", {"base_rev": rev, "wrap": st["wrap"], "blob": blob})
            if code == 409:
                continue                                      # 别的设备刚传过：重新拉、合并、再传
            rev = int(r.get("rev", rev + 1))
            pushed = True
            break
        else:
            raise SyncError("同步冲突太多次，请稍后再试。")
        st.update({"rev": rev, "last_ok": int(time.time())})
        _save(st)
        log.info("保险库同步：完成（本机更新=%s，已上传=%s）", changed, pushed)
        return {"changed": changed, "pushed": pushed, "last_ok": st["last_ok"]}


def disable(erase_server=False):
    with _lock:
        if erase_server:
            _req("DELETE")
        _forget()
        log.info("保险库同步：已关闭（删除服务器副本=%s）", erase_server)
