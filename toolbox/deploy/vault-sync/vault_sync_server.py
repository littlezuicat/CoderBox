#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""码境工具箱「密码保险库同步」服务（放在 www.zuicat.cn 的服务器上，只用 Python 标准库）。

它只存**密文**：工具箱在本机用随机密钥加密整个保险库再上传，服务器不知道内容，也不知道主密码。
身份用码境账号：工具箱在 Authorization 头里带码境的登录凭证，本服务拿它去 code.zuicat.cn 的 /api/auth/me 核对是谁，
每个账号一个文件。接口（nginx 把 /toolbox/api/vault 转到这里，见 README.md）：
  GET    /  → {exists:false,user} 或 {exists:true,user,rev,wrap,blob,updated}
  PUT    /  body {base_rev,wrap,blob} → {ok,user,rev}；base_rev 不是当前版本 → 409 {error,rev}
  DELETE /  → 删除这个账号在服务器上的副本
环境变量：LISTEN_HOST(127.0.0.1) LISTEN_PORT(8765) DATA_DIR(/var/lib/toolbox-vault) AUTH_ME_URL(https://code.zuicat.cn/api/auth/me)
"""
import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("LISTEN_PORT", "8765"))
DATA = os.environ.get("DATA_DIR", "/var/lib/toolbox-vault")
AUTH = os.environ.get("AUTH_ME_URL", "https://code.zuicat.cn/api/auth/me")
COOKIE = "coderland_session"
MAX_BODY = 8 * 1024 * 1024
LOCK = threading.Lock()
CACHE = {}                    # 凭证哈希 -> (过期时间, 用户标识)；只缓存 60 秒，减少对码境的请求


def who(token):
    """核对凭证，返回用户标识（字符串）；无效返回 None；码境连不上抛 RuntimeError。"""
    h = hashlib.sha256(token.encode()).hexdigest()
    hit = CACHE.get(h)
    if hit and hit[0] > time.time():
        return hit[1]
    req = urlreq.Request(AUTH, headers={"Cookie": "%s=%s" % (COOKIE, token), "Accept": "application/json",
                                        "Origin": "https://code.zuicat.cn", "User-Agent": "MajingToolbox-vault-sync"})
    try:
        with urlreq.urlopen(req, timeout=8) as r:
            u = (json.loads(r.read().decode("utf-8")).get("user") or {})
    except HTTPError as e:
        if e.code in (401, 403):
            return None
        raise RuntimeError("auth http %d" % e.code)
    except (URLError, ValueError, OSError):
        raise RuntimeError("auth unreachable")
    uid = str(u.get("id") or u.get("username") or "")
    if not uid:
        return None
    if len(CACHE) > 500:
        CACHE.clear()
    CACHE[h] = (time.time() + 60, uid)
    return uid


def path_for(uid):
    return os.path.join(DATA, hashlib.sha256(uid.encode()).hexdigest()[:40] + ".json")


def read(uid):
    try:
        with open(path_for(uid), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def write(uid, doc):
    p = path_for(uid)
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    if os.path.exists(p):
        try:
            os.replace(p, p + ".prev")                      # 上一版留一份，万一客户端传坏了能手工找回
        except OSError:
            pass
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    os.chmod(p, 0o600)


class H(BaseHTTPRequestHandler):
    server_version = "vault-sync"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                         # 不记请求内容，只记方法、状态
        print("%s %s %s" % (self.command, a[1] if len(a) > 1 else "", self.client_address[0]), flush=True)

    def send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def user(self):
        m = re.match(r"^Bearer ([A-Za-z0-9._~+/=-]{10,2048})$", self.headers.get("Authorization", ""))
        if not m:
            self.send(401, {"error": "没有登录凭证。"})
            return None
        try:
            uid = who(m.group(1))
        except RuntimeError:
            self.send(503, {"error": "暂时连不上码境账号服务，稍后再试。"})
            return None
        if not uid:
            self.send(401, {"error": "码境账号登录已失效。"})
            return None
        return uid

    def do_GET(self):
        uid = self.user()
        if uid is None:
            return
        with LOCK:
            doc = read(uid)
        if not doc:
            return self.send(200, {"exists": False, "user": uid})
        self.send(200, {"exists": True, "user": uid, "rev": doc["rev"], "wrap": doc["wrap"], "blob": doc["blob"], "updated": doc["updated"]})

    def do_PUT(self):
        uid = self.user()
        if uid is None:
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            self.rfile.read(min(n, MAX_BODY)) if n > 0 else None
            return self.send(413, {"error": "数据太大或为空。"})
        try:
            b = json.loads(self.rfile.read(n).decode("utf-8"))
            base, wrap, blob = int(b["base_rev"]), b["wrap"], b["blob"]
            assert isinstance(wrap, dict) and isinstance(blob, dict) and isinstance(blob.get("ct"), str)
        except Exception:                                   # noqa: BLE001
            return self.send(400, {"error": "请求格式不对。"})
        with LOCK:
            cur = read(uid)
            rev = cur["rev"] if cur else 0
            if base != rev:
                return self.send(409, {"error": "服务器上有更新的版本。", "rev": rev})
            write(uid, {"rev": rev + 1, "wrap": wrap, "blob": blob, "updated": int(time.time())})
        self.send(200, {"ok": True, "user": uid, "rev": rev + 1})

    def do_DELETE(self):
        uid = self.user()
        if uid is None:
            return
        with LOCK:
            try:
                os.replace(path_for(uid), path_for(uid) + ".deleted")   # 先改名留一份，不直接抹掉；确认没问题后可手工清理
            except FileNotFoundError:
                pass
        self.send(200, {"ok": True})


if __name__ == "__main__":
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    print("vault-sync 监听 %s:%d 数据目录 %s" % (HOST, PORT, DATA), flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
