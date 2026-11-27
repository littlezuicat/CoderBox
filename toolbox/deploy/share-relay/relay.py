#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""码境工具箱「共享本机 SSH」的公网中转（跑在 code.zuicat.cn 背后的服务器上，只监听 127.0.0.1，由 SakuraFrp 的 TCP 隧道对外）。

别人用原生 ssh 连：  ssh -p 公网端口 <码境用户名>@code.zuicat.cn   → 密码是对方共享窗口里的那串
SSH 的用户名在加密之后才发送，TCP 转发看不到，所以这里自己充当 SSH 服务端：
  · 设备（工具箱）以用户名 _device、密码=码境登录凭证连进来，中转用凭证去 code.zuicat.cn/api/auth/me 核对是谁（防冒名），
    再让它 tcpip-forward 一条通道；之后这台设备就以它的码境用户名登记在册（同一用户名只留最新的一台）。
  · 访客用户名=码境用户名：中转经那台设备的通道连到它本机的内置 SSH 服务，用访客给的密码去登录；登录成功才放行，
    之后把访客的 shell / exec / sftp / 端口转发原样接到设备上。
中转能看到访客输入的共享密码（一次性随机密码，且这是自己的服务器），看不到会话里的内容之外的东西——会话内容在中转处是解开再转发的，所以别把它当端到端加密。
环境变量：LISTEN_HOST(127.0.0.1) LISTEN_PORT(22302) DATA_DIR(/var/lib/tb-relay) AUTH_ME_URL(https://code.zuicat.cn/api/auth/me)
"""
import hashlib
import json
import logging
import os
import re
import socket
import threading
import time
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

import paramiko

HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("LISTEN_PORT", "22302"))
DATA = os.environ.get("DATA_DIR", "/var/lib/tb-relay")
AUTH = os.environ.get("AUTH_ME_URL", "https://code.zuicat.cn/api/auth/me")
COOKIE = "coderland_session"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
log = logging.getLogger("tb-relay")

DEVICES = {}                  # 码境用户名(小写) -> {"t": Transport, "since": 时间, "uid": 用户标识}
DLOCK = threading.Lock()
CACHE = {}                    # 凭证哈希 -> (过期时间, uid, username)
FAILS = {}                    # 用户名 -> (次数, 解锁时间)：同一个用户名连错 8 次锁 5 分钟（来源 IP 经隧道都是 127.0.0.1，只能按用户名限）


def who(token):
    """核对码境凭证，返回 (uid, username)；无效返回 None；码境连不上抛 RuntimeError。"""
    h = hashlib.sha256(token.encode()).hexdigest()
    hit = CACHE.get(h)
    if hit and hit[0] > time.time():
        return hit[1], hit[2]
    req = urlreq.Request(AUTH, headers={"Cookie": "%s=%s" % (COOKIE, token), "Accept": "application/json",
                                        "Origin": "https://code.zuicat.cn", "User-Agent": "MajingToolbox-share-relay"})
    try:
        with urlreq.urlopen(req, timeout=8) as r:
            u = (json.loads(r.read().decode("utf-8")).get("user") or {})
    except HTTPError as e:
        if e.code in (401, 403):
            return None
        raise RuntimeError("auth http %d" % e.code)
    except (URLError, ValueError, OSError):
        raise RuntimeError("auth unreachable")
    uname = str(u.get("username") or "").strip()
    uid = str(u.get("id") or uname)
    if not uname:
        return None
    if len(CACHE) > 500:
        CACHE.clear()
    CACHE[h] = (time.time() + 60, uid, uname)
    return uid, uname


def _host_key():
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "host_ed25519")
    if not os.path.exists(path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        k = ed25519.Ed25519PrivateKey.generate()
        with open(path, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
        os.chmod(path, 0o600)
    return paramiko.PKey.from_path(path)


def _pipe(src_recv, dst_send, on_eof=None):
    try:
        while True:
            d = src_recv(32768)
            if not d:
                break
            dst_send(d)
    except Exception:                                   # noqa: BLE001
        pass
    finally:
        if on_eof:
            try:
                on_eof()
            except Exception:                           # noqa: BLE001
                pass


class Session:
    """一个访客 session 通道 ↔ 设备上对应的 session 通道。"""

    def __init__(self, chan, up_tr):
        self.chan, self.up_tr = chan, up_tr
        self.pty = None
        self.up = None
        self.started = False

    def open_up(self):
        self.up = self.up_tr.open_session(timeout=15)
        if self.pty:
            term, w, h, pw, ph = self.pty
            self.up.get_pty(term, w, h, pw, ph)

    def start(self, how):
        """how: 对上游通道做的启动动作（invoke_shell / exec_command / invoke_subsystem），然后开始双向搬运。"""
        how(self.up)
        self.started = True
        up, chan = self.up, self.chan
        threading.Thread(target=_pipe, args=(chan.recv, up.sendall, lambda: up.shutdown_write()), daemon=True).start()
        threading.Thread(target=_pipe, args=(up.recv_stderr, chan.sendall_stderr), daemon=True).start()

        def out():
            _pipe(up.recv, chan.sendall)
            try:
                code = up.recv_exit_status()
                chan.send_exit_status(code if code >= 0 else 0)
            except Exception:                           # noqa: BLE001
                pass
            for c in (chan, up):
                try:
                    c.close()
                except Exception:                       # noqa: BLE001
                    pass
        threading.Thread(target=out, daemon=True).start()


class Iface(paramiko.ServerInterface):
    def __init__(self, addr):
        self.addr = addr
        self.transport = None
        self.role = None                                # "device" / "visitor"
        self.cuser = ""                                 # 设备：它的码境用户名
        self.up_tr = None                               # 访客：连到设备的上游 Transport
        self.sessions = {}                              # chanid -> Session
        self.direct = {}                                # chanid -> (目标主机, 端口)

    # ---- 认证
    def get_allowed_auths(self, username):
        return "password"

    def check_auth_password(self, username, password):
        username = (username or "").strip()
        try:
            if username == "_device":
                return self._auth_device(password)
            return self._auth_visitor(username.lower(), password)
        except Exception as e:                          # noqa: BLE001
            log.warning("认证出错：%s: %s", type(e).__name__, e)
            return paramiko.AUTH_FAILED

    def _auth_device(self, token):
        r = who(token)
        if not r:
            time.sleep(1)
            return paramiko.AUTH_FAILED
        if not NAME_RE.match(r[1]):
            log.info("拒绝设备：用户名不是英文 %r", r[1])
            return paramiko.AUTH_FAILED               # 用户名必须是英文（字母数字 _ . -），工具箱那边会先提示用户改名
        self.role, self.cuser = "device", r[1].lower()
        self.uid = r[0]
        return paramiko.AUTH_SUCCESSFUL

    def _auth_visitor(self, user, password):
        user, _, who = user.partition("+")              # ssh 用户名可以写成 目标码境用户名+自己的码境用户名，被控端会看到后者（自称，没法核实）
        who = who if NAME_RE.match(who) else ""
        n, until = FAILS.get(user, (0, 0))
        if n >= 8 and until > time.time():
            time.sleep(1)
            return paramiko.AUTH_FAILED
        with DLOCK:
            dev = DEVICES.get(user)
        tr = dev["t"] if dev else None
        ok = False
        up = None
        if tr is not None and tr.is_active():
            try:
                ch = tr.open_forwarded_tcpip_channel(("127.0.0.1", 0), ("127.0.0.1", 0))
                up = paramiko.Transport(ch)
                up.start_client(timeout=12)
                up.auth_password("relay+" + who if who else "relay", password)     # 设备那边的内置 SSH 对经隧道来的连接不看用户名，只看密码
                self.up_tr = up
                ok = True
            except paramiko.AuthenticationException:
                pass
            except Exception as e:                      # noqa: BLE001
                log.info("访客 %s 连设备失败：%s: %s", user, type(e).__name__, e)
        if not ok and up is not None:
            try:
                up.close()                              # 密码不对时别留着到设备的连接
            except Exception:                           # noqa: BLE001
                pass
        if ok:
            FAILS.pop(user, None)
            self.role = "visitor"
            log.info("访客登录 %s 来自 %s", user, who or "（没写名字）")
            return paramiko.AUTH_SUCCESSFUL
        FAILS[user] = (n + 1 if until > time.time() or n < 8 else 1, time.time() + 300)
        time.sleep(1)                                   # 拖慢猜密码
        return paramiko.AUTH_FAILED

    # ---- 设备：tcpip-forward（只当登记用，通道由中转主动开）
    def check_port_forward_request(self, address, port):
        if self.role != "device":
            return False
        t = self.transport
        with DLOCK:
            old = DEVICES.get(self.cuser)
            DEVICES[self.cuser] = {"t": t, "since": time.time(), "uid": self.uid}
        log.info("设备上线：%s（共 %d 台）", self.cuser, len(DEVICES))
        if old and old["t"] is not t:
            try:
                old["t"].close()                        # 同一个用户名只留最新的一台
            except Exception:                           # noqa: BLE001
                pass
        return port or 22301

    def cancel_port_forward_request(self, address, port):
        pass

    # ---- 访客：通道
    def check_channel_request(self, kind, chanid):
        if self.role == "visitor" and kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        if self.role != "visitor":
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        self.direct[chanid] = destination
        return paramiko.OPEN_SUCCEEDED

    def _sess(self, channel):
        s = self.sessions.get(channel.get_id())
        if s is None:
            s = self.sessions[channel.get_id()] = Session(channel, self.up_tr)
        return s

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self._sess(channel).pty = (term.decode() if isinstance(term, bytes) else term, width, height, pixelwidth, pixelheight)
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        s = self.sessions.get(channel.get_id())
        if s and s.up:
            try:
                s.up.resize_pty(width, height, pixelwidth, pixelheight)
            except Exception:                           # noqa: BLE001
                pass
        return True

    def check_channel_env_request(self, channel, name, value):
        return False

    def _go(self, channel, how):
        s = self._sess(channel)
        try:
            s.open_up()
            s.start(how)
            return True
        except Exception as e:                          # noqa: BLE001
            log.info("开会话失败：%s: %s", type(e).__name__, e)
            return False

    def check_channel_shell_request(self, channel):
        return self._go(channel, lambda up: up.invoke_shell())

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode("utf-8", "replace") if isinstance(command, bytes) else command
        return self._go(channel, lambda up: up.exec_command(cmd))

    def check_channel_subsystem_request(self, channel, name):
        return self._go(channel, lambda up: up.invoke_subsystem(name))


def _direct_loop(iface, t):
    """访客开的 direct-tcpip 通道（ssh -L / -J）：经设备原样转发。"""
    while t.is_active() and iface.up_tr is not None and iface.up_tr.is_active():        # 设备那头断了（被踢、重置密码），访客这条也一起断
        chan = t.accept(1)
        if chan is None:
            continue
        dest = iface.direct.pop(chan.get_id(), None)
        if dest is None:
            continue                                    # session 通道在 check_channel_*_request 里自己处理

        def run(chan=chan, dest=dest):
            try:
                up = iface.up_tr.open_channel("direct-tcpip", dest, ("127.0.0.1", 0))
            except Exception:                           # noqa: BLE001
                chan.close()
                return
            threading.Thread(target=_pipe, args=(chan.recv, up.sendall, lambda: up.shutdown_write()), daemon=True).start()
            _pipe(up.recv, chan.sendall, lambda: (chan.close(), up.close()))
        threading.Thread(target=run, daemon=True).start()


def serve(cl, addr, hostkey):
    t = paramiko.Transport(cl)
    t.add_server_key(hostkey)
    t.set_keepalive(20)
    iface = Iface(addr)
    iface.transport = t
    try:
        t.start_server(server=iface)
        for _ in range(300):                            # 等认证通过（最多 30 秒）
            if iface.role or not t.is_active():
                break
            time.sleep(0.1)
        if not iface.role:                              # 没认证成功（注意不能用 t.is_authenticated()：认证后马上断开它也返回 False，会漏掉上游连接不关）
            return
        if iface.role == "device":
            while t.is_active():
                time.sleep(1)
            with DLOCK:
                if DEVICES.get(iface.cuser, {}).get("t") is t:
                    DEVICES.pop(iface.cuser, None)
            log.info("设备下线：%s", iface.cuser)
        else:
            _direct_loop(iface, t)
    except Exception as e:                              # noqa: BLE001
        log.info("连接处理出错：%s: %s", type(e).__name__, e)
    finally:
        for x in (iface.up_tr, t):                      # 无论怎么结束，通往设备的那条上游连接和访客这条都要关掉
            try:
                if x is not None:
                    x.close()
            except Exception:                           # noqa: BLE001
                pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    hostkey = _host_key()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(100)
    log.info("中转已启动 %s:%d", HOST, PORT)
    while True:
        cl, addr = s.accept()
        threading.Thread(target=serve, args=(cl, addr, hostkey), daemon=True).start()


if __name__ == "__main__":
    main()
