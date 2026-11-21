# -*- coding: utf-8 -*-
"""文件快传客户端：对接 www.zuicat.cn/file 的同一套接口；和服务器在同一个内网时自动走内网直连。"""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

PUBLIC_BASE = "https://www.zuicat.cn/file/"
TTLS = {"保留 1 小时": "1h", "保留 1 天": "1d", "保留 7 天": "7d"}
CODE_RE = re.compile(r"([23456789abcdefghjkmnpqrstuvwxyz]{6})\s*$")


class DropError(Exception):
    def __init__(self, status, code=None, msg=None):
        super().__init__(code or "HTTP %s" % status)
        self.status, self.code, self.msg = status, code, msg


def human(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024


def err_text(e):
    if isinstance(e, DropError):
        m = {"TOO_BIG": lambda: "一次最多传 %s。" % human(int(e.msg or 0)),
             "TOO_MANY": lambda: "你同时在传的批次太多了，等前面的传完再来。",
             "IP_QUOTA": lambda: "你存在服务器上的文件太多了，先删掉一些旧的。",
             "NO_SPACE": lambda: "服务器空间不够了，稍后再试。",
             "SLOW_DOWN": lambda: "输错次数太多，过 10 分钟再试。",
             "NOT_FOUND": lambda: "没有这个取件码，可能输错了或者已经过期。"}.get(e.code)
        return m() if m else "服务器返回错误 %s%s" % (e.status, "（%s）" % e.code if e.code else "")
    if isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return "连不上服务器，检查一下网络。"
    return str(e) or e.__class__.__name__


class Cancelled(Exception):
    pass


class DropClient:
    def __init__(self, version="2.0"):
        self.base = PUBLIC_BASE
        self.lan = False
        self.max_share = 5 << 30
        self.ua = "MajingToolbox/" + version
        self.pub = requests.Session()
        self.pub.headers["User-Agent"] = self.ua
        self.direct = requests.Session()          # 内网直连：不走系统代理
        self.direct.trust_env = False
        self.direct.headers["User-Agent"] = self.ua

    @property
    def http(self):
        return self.direct if self.lan else self.pub

    def probe(self):
        """问公网入口要内网地址，能连上就用内网（快几十倍）。"""
        r = self.pub.get(PUBLIC_BASE + "api/info", timeout=10)
        info = self._json(r)
        self.base, self.lan = PUBLIC_BASE, False
        self.max_share = int(info["max_share"])
        lan = info.get("lan_url")
        if not lan:
            return
        try:
            li = self.direct.get(lan + "api/info", timeout=2).json()
            if li.get("via") == "lan":
                self.base, self.lan, self.max_share = lan, True, int(li["max_share"])
        except Exception:
            pass

    @staticmethod
    def _json(r):
        try:
            d = r.json()
        except ValueError:
            d = {}
        if not r.ok:
            raise DropError(r.status_code, d.get("error"), d.get("message"))
        return d

    def request(self, method, path, body=None, token=None):
        h = {"X-Token": token} if token else {}
        r = self.http.request(method, self.base + path, json=body, headers=h, timeout=60)
        return self._json(r)

    def put_chunk(self, code, token, i, n, data):
        for attempt in range(7):
            try:
                r = self.http.put("%sapi/shares/%s/%d/%d" % (self.base, code, i, n), data=data, headers={"X-Token": token}, timeout=300)
                if r.ok:
                    return
                if r.status_code != 429 and r.status_code < 500:
                    raise DropError(r.status_code, "BAD_CHUNK", r.text)
            except (requests.ConnectionError, requests.Timeout):
                pass
            if attempt >= 6:
                raise RuntimeError("网络断了好几次，上传失败")
            time.sleep(0.8 * (1 << attempt))

    # ---- 发送
    def send(self, paths, ttl, progress, cancelled):
        """paths: 文件路径列表；progress(已传字节, 总字节)。返回 (取件码, 链接)。"""
        files = [(os.path.basename(p), os.path.getsize(p), p) for p in paths]
        total = sum(f[1] for f in files)
        if total > self.max_share:
            raise RuntimeError("一次最多传 %s%s。" % (human(self.max_share), "" if self.lan else "（同一内网时可以传更大的）"))
        j = self.request("POST", "api/shares", {"files": [{"name": n, "size": s} for n, s, _ in files], "ttl": ttl})
        code, token, chunk = j["code"], j["token"], int(j["chunk"])
        tasks = [(i, n) for i, f in enumerate(files) for n in range(max(1, (f[1] + chunk - 1) // chunk))]
        sent = [0]
        lock = threading.Lock()
        nxt = [0]

        def work():
            while True:
                with lock:
                    k = nxt[0]
                    nxt[0] += 1
                if k >= len(tasks) or cancelled():
                    return
                i, n = tasks[k]
                with open(files[i][2], "rb") as f:
                    f.seek(n * chunk)
                    data = f.read(chunk)
                self.put_chunk(code, token, i, n, data)
                with lock:
                    sent[0] += len(data)
                    s = sent[0]
                progress(s, total)

        with ThreadPoolExecutor(6 if self.lan else 4) as ex:
            for fut in [ex.submit(work) for _ in range(6 if self.lan else 4)]:
                fut.result()
        if cancelled():
            raise Cancelled()
        self.request("POST", "api/shares/%s/finish" % code, None, token)
        return code, PUBLIC_BASE + "#" + code

    # ---- 接收
    def lookup(self, text):
        m = CODE_RE.search(text.strip().lower())
        if not m:
            raise RuntimeError("取件码是 6 位字母和数字。")
        return self.request("GET", "api/shares/" + m.group(1))

    def download(self, code, i, size, dest, progress, cancelled):
        part = dest + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        for attempt in range(7):
            try:
                h = {"Range": "bytes=%d-" % have} if have else {}
                with self.http.get("%sapi/shares/%s/%d/f" % (self.base, code, i), headers=h, stream=True, timeout=60) as r:
                    if not r.ok:
                        raise DropError(r.status_code)
                    if r.status_code != 206:
                        have = 0
                    with open(part, "ab" if have else "wb") as f:
                        for blk in r.iter_content(1 << 20):
                            if cancelled():
                                raise Cancelled()
                            f.write(blk)
                            have += len(blk)
                            progress(have)
                if have != size:
                    raise IOError("没下完整")
                if os.path.exists(dest):
                    os.remove(dest)
                os.replace(part, dest)
                return
            except (Cancelled, DropError):
                raise
            except Exception:
                if attempt >= 6:
                    raise
                time.sleep(attempt + 1)
