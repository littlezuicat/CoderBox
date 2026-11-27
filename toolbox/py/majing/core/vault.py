# -*- coding: utf-8 -*-
"""密码保险库（本机版）。

设计：
  · 日常不需要主密码，也不上锁：保险库文件 vault.dat 用一把随机的 256 位密钥做 AES-256-GCM 加密，
    这把密钥再由 Windows DPAPI 保护（和浏览器保存密码是同一种机制，只有当前 Windows 用户能解开）。
    别人拿到 vault.dat 在别的电脑/别的账户下打不开。（主密码留到“同步到服务器”那一步，用来登录账户、跨设备解密。）
  · 文件是原子写入（先写临时文件再替换），并保留上一份 vault.dat.bak；主文件坏了会自动退回备份并提示。
  · 复制密码到剪贴板后默认 15 秒自动清空（只在剪贴板里还是这个密码时才清），并要求 Windows 不要把它记进剪贴板历史/云剪贴板。
  · 日志里不写任何条目内容，只写条目 id 和操作类型。
非 Windows 平台没有 DPAPI：默认拒绝创建保险库（避免把密钥明文放在磁盘上）；开发测试可设环境变量 MAJING_VAULT_DEV=1 放行。"""
import base64
import json
import logging
import os
import shutil
import sys
import threading
import time
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from majing.core import account

log = logging.getLogger("majing.vault")
AAD = b"majing-vault-v1"
CLIP_SECS = 15
FIELDS = ("type", "name", "username", "password", "url", "notes", "folder")


class VaultError(Exception):
    pass


def _dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return d


def path():
    return os.path.join(_dir(), "vault.dat")


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    return base64.b64decode(s.encode("ascii"))


def _host(url):
    from urllib.parse import urlsplit
    u = (url or "").strip()
    try:
        h = urlsplit(u if "://" in u else "https://" + u).hostname or ""
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _can_protect():
    return sys.platform == "win32" or os.environ.get("MAJING_VAULT_DEV") == "1"


class Vault:
    def __init__(self):
        self._lock = threading.RLock()
        self._data = None            # {"items": [...], "folders": [...], "rev": n}
        self._key = None
        self.recovered = False       # 主文件坏了、是从备份读回来的
        self._sig_loaded = None      # 上次读/写时 vault.dat 的 (修改时间, 大小)

    # ------------------------------------------------------------ 读写文件
    def _decrypt_file(self, p):
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("v") != 1:
            raise VaultError("保险库文件版本不认识")
        key = account._unprotect(_unb64(doc["key"]))
        pt = AESGCM(key).decrypt(_unb64(doc["nonce"]), _unb64(doc["ct"]), AAD)
        return key, json.loads(pt.decode("utf-8"))

    @staticmethod
    def _sig():
        try:
            st = os.stat(path())
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _load(self):
        """读到内存；文件被别的进程（浏览器扩展的原生主机）改过就重新读，避免用旧数据覆盖别人的修改。"""
        if self._data is not None and self._sig() == self._sig_loaded:
            return
        self._data = None
        self._load_now()
        self._sig_loaded = self._sig()

    def _load_now(self):
        p = path()
        if not os.path.exists(p):
            if os.path.exists(p + ".bak"):
                p_try = [p + ".bak"]
            else:
                self._data = {"items": [], "folders": [], "rev": 0}
                self._key = None
                return
        else:
            p_try = [p, p + ".bak"]
        err = None
        for i, cand in enumerate(p_try):
            if not os.path.exists(cand):
                continue
            try:
                self._key, self._data = self._decrypt_file(cand)
                if cand.endswith(".bak"):
                    self.recovered = True
                    log.warning("保险库主文件读取失败，已从备份恢复")
                return
            except Exception as e:                           # noqa: BLE001
                err = e
                log.error("读保险库失败（%s）：%s", os.path.basename(cand), type(e).__name__)
        raise VaultError("保险库打不开：文件损坏，或不是在原来的 Windows 账户下。（%s）" % (type(err).__name__ if err else "未知"))

    def _save(self):
        if not _can_protect():
            raise VaultError("这个系统暂不支持保险库（没有系统级密钥保护）。")
        if self._key is None:
            self._key = os.urandom(32)
        self._data["rev"] = int(self._data.get("rev", 0)) + 1
        nonce = os.urandom(12)
        ct = AESGCM(self._key).encrypt(nonce, json.dumps(self._data, ensure_ascii=False).encode("utf-8"), AAD)
        doc = {"v": 1, "wrap": "dpapi", "key": _b64(account._protect(self._key)), "nonce": _b64(nonce), "ct": _b64(ct)}
        p = path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(p) and not self.recovered:         # 主文件是坏的（刚从备份恢复）时，别拿它去覆盖那份好备份
            try:
                shutil.copy2(p, p + ".bak")                  # 上一份好文件留作备份
            except OSError:
                pass
        os.replace(tmp, p)
        self._sig_loaded = self._sig()
        self.recovered = False

    # ------------------------------------------------------------ 对外接口
    def status(self):
        with self._lock:
            self._load()
            return {"exists": os.path.exists(path()), "count": len(self._data["items"]), "folders": self._folders(), "recovered": self.recovered}

    def _folders(self):
        return sorted({i.get("folder", "") for i in self._data["items"] if i.get("folder")} | set(self._data.get("folders", [])))

    @staticmethod
    def _summary(i):
        return {"id": i["id"], "type": i.get("type", "login"), "name": i.get("name", ""), "username": i.get("username", ""), "url": i.get("url", ""),
                "folder": i.get("folder", ""), "updated": i.get("updated", 0), "has_password": bool(i.get("password")), "has_notes": bool(i.get("notes"))}

    def list(self, query="", folder=""):
        q = (query or "").strip().lower()
        with self._lock:
            self._load()
            out = []
            for i in self._data["items"]:
                if folder and i.get("folder", "") != folder:
                    continue
                if q and not any(q in str(i.get(k, "")).lower() for k in ("name", "username", "url", "folder", "notes")):
                    continue
                out.append(self._summary(i))
        out.sort(key=lambda x: (x["name"].lower(), x["username"].lower()))
        return out

    def get(self, iid):
        with self._lock:
            self._load()
            for i in self._data["items"]:
                if i["id"] == iid:
                    return dict(i)
        raise VaultError("没有这个条目。")

    def save(self, item):
        """新增或修改。item 里有 id 就是修改。返回条目 id。"""
        clean = {k: str(item.get(k, "") or "").strip() if k not in ("password", "notes") else str(item.get(k, "") or "") for k in FIELDS}
        if clean["type"] not in ("login", "note"):
            clean["type"] = "login"
        if not clean["name"]:
            raise VaultError("名称不能为空。")
        now = round(time.time(), 3)
        with self._lock:
            self._load()
            iid = item.get("id")
            if iid:
                for n, i in enumerate(self._data["items"]):
                    if i["id"] == iid:
                        self._data["items"][n] = {**i, **clean, "updated": now}
                        break
                else:
                    raise VaultError("要修改的条目不存在。")
                act = "修改"
            else:
                iid = uuid.uuid4().hex
                self._data["items"].append({"id": iid, **clean, "created": now, "updated": now})
                act = "新增"
            self._save()
        log.info("保险库：%s 条目 %s", act, iid)
        return iid

    def delete(self, iid):
        with self._lock:
            self._load()
            n = len(self._data["items"])
            self._data["items"] = [i for i in self._data["items"] if i["id"] != iid]
            if len(self._data["items"]) == n:
                raise VaultError("没有这个条目。")
            self._data.setdefault("deleted", {})[iid] = round(time.time(), 3)      # 删除记录：同步时告诉别的设备“这条删了”
            self._save()
        log.info("保险库：删除 条目 %s", iid)

    # ------------------------------------------------------------ 同步用
    def snapshot(self):
        """整库内容（含明文，只给同步模块加密后上传用）。"""
        with self._lock:
            self._load()
            return json.loads(json.dumps({"items": self._data["items"], "deleted": self._data.get("deleted", {})}))

    def merge(self, remote):
        """把另一台设备的内容并进来：同一条取 updated 较新的；删除记录比条目新就删，条目比删除记录新就保留。
        返回 True 表示本机内容有变化（已保存）。"""
        with self._lock:
            self._load()
            local = {i["id"]: i for i in self._data["items"]}
            before = json.dumps([self._data["items"], self._data.get("deleted", {})], sort_keys=True)
            items = dict(local)
            remote_only = set()
            for r in remote.get("items", []):
                cur = items.get(r["id"])
                if cur is None:
                    items[r["id"]] = dict(r)
                    remote_only.add(r["id"])
                elif float(r.get("updated", 0)) > float(cur.get("updated", 0)):
                    items[r["id"]] = dict(r)
            dele = dict(self._data.get("deleted", {}))
            for k, ts in remote.get("deleted", {}).items():
                dele[k] = max(float(ts), float(dele.get(k, 0)))
            for k, ts in list(dele.items()):
                it = items.get(k)
                if it is not None:
                    if float(ts) >= float(it.get("updated", 0)):
                        del items[k]
                    else:
                        del dele[k]                                  # 删除之后又改过：以修改为准，保留条目
            # 两台设备各自导入了同一份文件会产生“同内容、不同 id”的重复，按固定规则只留一条（两边算出来一样，不会来回打架）
            seen = {}
            for iid in sorted(items):
                it = items[iid]
                key = (it.get("name", ""), it.get("username", ""), it.get("url", ""))
                other = seen.get(key)
                if other is None:
                    seen[key] = iid
                    continue
                if (iid in remote_only) == (other in remote_only):
                    continue                                          # 同一边自己建的重复，不动
                a, b = items[other], it
                ua, ub = float(a.get("updated", 0)), float(b.get("updated", 0))
                keep, drop = (a, b) if (ua > ub or (ua == ub and a["id"] < b["id"])) else (b, a)      # 新的留下；一样新就留 id 小的
                dele[drop["id"]] = max(float(drop.get("updated", 0)), float(dele.get(drop["id"], 0)))
                del items[drop["id"]]
                seen[key] = keep["id"]
            cutoff = int(time.time()) - 365 * 86400
            dele = {k: v for k, v in dele.items() if float(v) > cutoff}
            self._data["items"] = list(items.values())
            self._data["deleted"] = dele
            after = json.dumps([self._data["items"], self._data.get("deleted", {})], sort_keys=True)
            if after == before:
                return False
            self._save()
        log.info("保险库：合并远端内容，现有 %d 条", len(items))
        return True

    def import_items(self, items):
        """批量导入（已经整理成 FIELDS 的字典列表）。返回新增的条数。同名+同用户名+同网址的视为重复，跳过。"""
        now = round(time.time(), 3)
        added = 0
        with self._lock:
            self._load()
            have = {(i.get("name", ""), i.get("username", ""), i.get("url", "")) for i in self._data["items"]}
            # 另一种重复：同一个网站（只比主机名）+ 同用户名 + 同密码，哪怕名称、网址路径不一样（比如 Chrome 存的是登录页地址）
            have2 = {(i.get("username", "").lower(), _host(i.get("url", "")), i.get("password", "")) for i in self._data["items"] if i.get("password")}
            for it in items:
                name = str(it.get("name", "")).strip()
                if not name:
                    continue
                clean = {k: str(it.get(k, "") or "") for k in FIELDS}
                clean["name"] = name
                if clean["type"] not in ("login", "note"):
                    clean["type"] = "login"
                key = (clean["name"], clean["username"], clean["url"])
                key2 = (clean["username"].lower(), _host(clean["url"]), clean["password"])
                if key in have or (clean["password"] and _host(clean["url"]) and key2 in have2):
                    continue
                have.add(key)
                have2.add(key2)
                self._data["items"].append({"id": uuid.uuid4().hex, **clean, "created": now, "updated": now})
                added += 1
            if added:
                self._save()
        log.info("保险库：导入 %d 条", added)
        return added


vault = Vault()


# ---------------------------------------------------------------- 剪贴板（复制后自动清空）
_clip_lock = threading.Lock()
_clip_timer = None
_clip_value = None


def _with_clipboard(fn):
    import win32clipboard
    last = None
    for _ in range(10):                                      # 剪贴板偶尔被别的程序占着，等一下再试
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception as e:                               # noqa: BLE001
            last = e
            time.sleep(0.05)
    else:
        raise VaultError("剪贴板被占用，稍后再试。（%s）" % last)
    try:
        return fn(win32clipboard)
    finally:
        win32clipboard.CloseClipboard()


def _clip_get():
    import win32con

    def go(c):
        try:
            return c.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception:                                    # noqa: BLE001
            return None
    return _with_clipboard(go)


def copy_secret(text, secs=CLIP_SECS):
    """把 text 放进剪贴板，secs 秒后（剪贴板里还是它时）清空。并要求系统不要记进剪贴板历史/云剪贴板。"""
    global _clip_timer, _clip_value
    if sys.platform != "win32":
        raise VaultError("这个系统暂不支持复制到剪贴板。")
    import win32con

    def go(c):
        c.EmptyClipboard()
        c.SetClipboardData(win32con.CF_UNICODETEXT, text)
        for name, data in (("ExcludeClipboardContentFromMonitorProcessing", b"\x01\x00\x00\x00"),
                           ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"), ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00")):
            try:
                c.SetClipboardData(c.RegisterClipboardFormat(name), data)
            except Exception:                                # noqa: BLE001
                pass
    _with_clipboard(go)
    with _clip_lock:
        if _clip_timer:
            _clip_timer.cancel()
        _clip_value = text
        if secs and secs > 0:
            _clip_timer = threading.Timer(secs, clear_clipboard_if_ours)
            _clip_timer.daemon = True
            _clip_timer.start()


def clear_clipboard_if_ours():
    """剪贴板里还是我们放进去的那段文字才清空（用户中途复制了别的就不动）。"""
    global _clip_timer, _clip_value
    with _clip_lock:
        mine, _clip_value, _clip_timer = _clip_value, None, None
    if mine is None or sys.platform != "win32":
        return
    try:
        if _clip_get() == mine:
            _with_clipboard(lambda c: c.EmptyClipboard())
            log.info("剪贴板已自动清空")
    except Exception as e:                                   # noqa: BLE001
        log.info("清剪贴板失败：%s", type(e).__name__)
