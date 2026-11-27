# -*- coding: utf-8 -*-
"""“共享本机 SSH”的公网入口：本机以“设备”身份连到公网中转（code.zuicat.cn 上的一个端口，所有人共用），中转按**码境用户名**把访客分给对应的电脑。

别人：  ssh -p 41764 <你的码境用户名>@code.zuicat.cn   → 输入共享窗口里的密码
链路：访客 → code.zuicat.cn:41764（SakuraFrp 节点 46 的 TCP 隧道 tb_share_ssh）→ 服务器上的中转程序 tb-relay（deploy\share-relay\relay.py，监听 127.0.0.1:22302）
      ← 本机主动连出去的 SSH 连接（用户名 _device、密码=码境登录凭证，中转拿凭证去 code.zuicat.cn 核对出用户名，防冒名）← 本机内置 SSH 服务。
- 本机只往外连，不需要路由器开端口；关闭共享（或关闭工具箱）连接即断，设备就从中转上下线了。
- 要先在设置里绑定码境账号（凭证存在 account.bin）；没绑定就不开公网入口，共享窗口退回显示局域网命令。
- 同一个码境用户名同一时刻只有一台设备在线（后来的顶掉先来的）。
- 经中转进来的连接在本机看到的来源都是 127.0.0.1，所以“同一 IP 连错 5 次锁 10 分钟”是全局的（中转那边另外按用户名限速）。"""
import logging
import os
import re
import socket
import threading
import time

import paramiko

log = logging.getLogger("majing.share")

CFG = {
    "host": os.environ.get("MAJING_RELAY_HOST") or "code.zuicat.cn",
    "port": int(os.environ.get("MAJING_RELAY_PORT") or 41764),     # SakuraFrp TCP 隧道 tb_share_ssh（节点 46）→ 服务器 127.0.0.1:22302 的中转程序
}


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")        # ssh 用户名只能是英文：字母、数字、下划线、点、减号（中文会让原生 ssh 命令乱码、各系统不一致）
BAD_NAME = "码境用户名“%s”不是英文，没法用作 ssh 用户名。请先把码境用户名改成英文（字母、数字、_ . -）再开启共享。"


class BadName(Exception):
    pass


def _dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "MajingToolbox")


def available():
    """有没有绑定码境账号（有登录凭证就可以尝试开公网入口）。"""
    from majing.core import account
    return bool(account.token())


def precheck():
    """开启共享前的检查：必须绑定了码境账号、码境用户名是英文。没问题返回 None，否则返回要告诉用户的话。"""
    from majing import APP_VERSION
    from majing.core import account
    if not account.token():
        return "请先绑定码境账号（设置 → 码境账号）。共享本机必须用码境账号，别人用你的码境用户名连过来。"
    st = account.status("MajingToolbox/" + APP_VERSION)
    if not st.get("bound"):
        return "码境账号登录已失效，请在设置里重新登录后再开启共享。"
    if st.get("offline") or not st.get("username"):
        return "暂时没能确认码境账号（网络不通？），请联网后再试。"
    if not NAME_RE.match(st["username"]):
        return BAD_NAME % st["username"]
    return None


def _pipe(src, dst):
    try:
        while True:
            d = src.recv(32768)
            if not d:
                break
            dst.sendall(d)
    except Exception:                                # noqa: BLE001
        pass
    finally:
        for x in (src, dst):
            try:
                x.close()
            except Exception:                        # noqa: BLE001
                pass


class ShareTunnel:
    """后台线程：连上服务器、请求反向转发、断了自动重连。public = 现在能用的公网地址（没连上就是 None）。"""

    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda: None)
        self.public = None
        self.error = ""
        self._stop = threading.Event()
        self._thread = None
        self._client = None
        self._local = 0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, local_port):
        if self.running:
            return False
        if not available():
            self._set(None, "还没有绑定码境账号（设置 → 码境账号），公网入口不可用")
            return False
        self._local = int(local_port)
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        c = self._client
        if c is not None:
            try:
                c.close()
            except Exception:                        # noqa: BLE001
                pass
        self._set(None, "")

    def _set(self, public, error):
        if public != self.public or error != self.error:
            self.public, self.error = public, error
            try:
                self.on_change()
            except Exception:                        # noqa: BLE001
                pass

    def _handler(self, chan, origin, server):
        def run():
            try:
                s = socket.create_connection(("127.0.0.1", self._local), timeout=5)
            except OSError as e:
                log.info("隧道来的连接转给本机 SSH 失败：%s", e)
                try:
                    chan.close()
                except Exception:                    # noqa: BLE001
                    pass
                return
            s.settimeout(None)
            threading.Thread(target=_pipe, args=(chan, s), daemon=True).start()
            _pipe(s, chan)
        threading.Thread(target=run, daemon=True).start()

    def _username(self):
        """本机登录的码境用户名（访客就用它当 ssh 用户名）。"""
        from majing import APP_VERSION
        from majing.core import account
        st = account.status("MajingToolbox/" + APP_VERSION)
        if st.get("username"):
            self._uname = st["username"]
        return self._uname

    def _loop(self):
        delay = 3
        self._uname = getattr(self, "_uname", "")
        while not self._stop.is_set():
            c = paramiko.SSHClient()
            kh = os.path.join(_dir(), "share_tunnel_known_hosts")
            if os.path.exists(kh):
                try:
                    c.load_host_keys(kh)
                except Exception:                    # noqa: BLE001
                    pass
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())        # 第一次见到中转的指纹记住，之后变了就拒绝
            self._client = c
            try:
                from majing.core import account
                token = account.token()
                uname = self._username()
                if not token or not uname:
                    raise PermissionError("码境账号登录已失效，请在设置里重新登录")
                if not NAME_RE.match(uname):
                    raise BadName(BAD_NAME % uname)
                c.connect(CFG["host"], port=CFG["port"], username="_device", password=token, timeout=12,
                          banner_timeout=12, auth_timeout=12, allow_agent=False, look_for_keys=False)
                try:
                    c.save_host_keys(kh)
                except Exception:                    # noqa: BLE001
                    pass
                tr = c.get_transport()
                tr.set_keepalive(20)
                tr.request_port_forward("", 0, handler=self._handler)        # 在中转上登记；访客来了由中转主动开通道
                log.info("共享设备已上线：%s@%s:%s → 本机 127.0.0.1:%s", uname, CFG["host"], CFG["port"], self._local)
                self._set({"host": CFG["host"], "port": CFG["port"], "user": uname}, "")
                delay = 3
                while not self._stop.is_set() and tr.is_active():
                    time.sleep(0.5)
            except BadName as e:
                log.warning("公网入口不开：%s", e)
                self._set(None, str(e))
                return                               # 改名之前重试没用；改完名重新开启共享就会再检查
            except Exception as e:                   # noqa: BLE001
                log.warning("公网入口没连上：%s: %s", type(e).__name__, e)
                if isinstance(e, (paramiko.AuthenticationException, PermissionError)):
                    msg = "公网入口被拒绝（码境登录失效？请在设置里重新登录码境账号）"
                else:
                    msg = "公网入口没连上（%s）" % e
                self._set(None, msg)
            finally:
                try:
                    c.close()
                except Exception:                    # noqa: BLE001
                    pass
            if self.public:
                self._set(None, "公网入口断开了，正在重连…")
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 30)
