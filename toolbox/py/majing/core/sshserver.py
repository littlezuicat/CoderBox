# -*- coding: utf-8 -*-
"""“共享本机 SSH”：在工具箱里开一个内置 SSH 服务，别人用 用户名 + 密码 + 端口 就能连上这台电脑（命令行、scp/sftp 都行）。

- 一键开启：随机分配端口（尽量沿用上次的）、随机生成密码、用户名是当前登录用户；可以限定开放时长，到点自动关闭。
- 关闭工具箱（进程退出）服务随之消失，不留后台程序。
- 防爆破：同一个 IP 连错 5 次锁 10 分钟；每次连接都记在“连接记录”里，可以一键踢掉。
- 权限就是当前登录用户的权限（可以运行命令、读写文件），所以密码是每次开启重新随机的 16 位。"""
import getpass
import hmac
import os
import posixpath
import re
import secrets
import select
import socket
import stat as statmod
import subprocess
import sys
import threading
import time

import paramiko

from majing.core import sharetunnel
from majing.settings import settings

NOWIN = 0x08000000 if sys.platform == "win32" else 0
_ALPHA = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return d


def _host_key():
    """固定的主机密钥（别人第一次连时记住指纹，之后不会因为重开服务而报“指纹变了”）。"""
    path = os.path.join(_data_dir(), "share_host_ed25519")
    if not os.path.exists(path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        k = ed25519.Ed25519PrivateKey.generate()
        with open(path, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
        from majing.core import sshhosts
        sshhosts._lock_down(path)
    return paramiko.PKey.from_path(path)


def local_ips():
    """这台电脑的 IPv4 地址（局域网 / VPN），主出口地址排第一。"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(ai[4][0])
    except Exception:
        pass
    out = []
    for ip in ips:
        if ip.startswith(("127.", "169.254.", "0.", "198.18.", "198.19.")) or ip in out:      # 198.18/15 是 Clash 等工具的虚拟网卡，别人连不上
            continue
        out.append(ip)

    def rank(ip):                       # 常见局域网地址排前面，docker 之类的排最后
        a = ip.split(".")
        if ip.startswith("192.168."):
            return 0
        if a[0] == "10":
            return 1
        if a[0] == "172" and 16 <= int(a[1]) <= 31:
            return 3 if a[1] in ("17", "18") else 2
        return 4
    out.sort(key=rank)
    return out


def _win_path(p):
    """SFTP 虚拟路径 ↔ Windows 路径：/C:/Users/x ↔ C:\\Users\\x；根目录 / 列出所有盘符。"""
    p = posixpath.normpath("/" + p.lstrip("/")) if p else "/"
    m = re.match(r"^/([A-Za-z]):(/.*)?$", p)
    if m:
        return m.group(1) + ":" + (m.group(2) or "/")
    return None


class _Handle(paramiko.SFTPHandle):
    def stat(self):
        try:
            return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def chattr(self, attr):
        return paramiko.SFTP_OK


class _SFTP(paramiko.SFTPServerInterface):
    """整盘可读写的 SFTP（权限=当前用户）。Windows 上路径形如 /C:/Users/…。"""
    WIN = sys.platform == "win32"

    def __init__(self, server, *a, **k):
        super().__init__(server, *a, **k)

    def _real(self, path):
        if not self.WIN:
            return posixpath.normpath("/" + path.lstrip("/")) if path else "/"
        return _win_path(path)

    def canonicalize(self, path):
        if path in ("", "."):
            home = os.path.expanduser("~")
            return ("/" + home.replace("\\", "/")) if self.WIN else home
        return posixpath.normpath(path if path.startswith("/") else "/" + path)

    def list_folder(self, path):
        try:
            r = self._real(path)
            out = []
            if r is None:
                for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    if os.path.exists(d + ":\\"):
                        a = paramiko.SFTPAttributes()
                        a.filename = d + ":"
                        a.st_mode = statmod.S_IFDIR | 0o755
                        a.st_size = 0
                        out.append(a)
                return out
            for fn in os.listdir(r):
                try:
                    a = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(r, fn)))
                except OSError:
                    continue
                a.filename = fn
                out.append(a)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            r = self._real(path)
            if r is None:
                a = paramiko.SFTPAttributes()
                a.st_mode = statmod.S_IFDIR | 0o755
                return a
            return paramiko.SFTPAttributes.from_stat(os.stat(r))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    lstat = stat

    def open(self, path, flags, attr):
        try:
            r = self._real(path)
            flags |= getattr(os, "O_BINARY", 0)
            fd = os.open(r, flags, 0o644)
        except (OSError, TypeError) as e:
            return paramiko.SFTPServer.convert_errno(getattr(e, "errno", 2) or 2)
        if flags & os.O_WRONLY:
            mode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            mode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            mode = "rb"
        f = os.fdopen(fd, mode)
        h = _Handle(flags)
        h.filename, h.readfile, h.writefile = r, f, f
        return h

    def mkdir(self, path, attr):
        return self._do(lambda r: os.mkdir(r))(path)

    def rmdir(self, path):
        return self._do(lambda r: os.rmdir(r))(path)

    def remove(self, path):
        return self._do(lambda r: os.remove(r))(path)

    def rename(self, old, new):
        try:
            os.replace(self._real(old), self._real(new))
            return paramiko.SFTP_OK
        except (OSError, TypeError) as e:
            return paramiko.SFTPServer.convert_errno(getattr(e, "errno", 1) or 1)

    def chattr(self, path, attr):
        return paramiko.SFTP_OK

    def _do(self, fn):
        def run(path):
            try:
                fn(self._real(path))
                return paramiko.SFTP_OK
            except (OSError, TypeError) as e:
                return paramiko.SFTPServer.convert_errno(getattr(e, "errno", 1) or 1)
        return run


class _Recode:
    """Windows 控制台程序按 OEM 代码页（中文系统是 GBK）输出；对外统一转成 UTF-8。已经是合法 UTF-8 的输出原样放行。"""

    def __init__(self, on):
        import codecs
        self.on, self.dec, self.oem = on, codecs.getincrementaldecoder("utf-8")("strict"), None
        self._codecs = codecs

    def conv(self, b):
        if not self.on:
            return b
        if self.oem is None:
            try:
                return self.dec.decode(b).encode("utf-8")
            except UnicodeDecodeError:
                try:
                    import ctypes
                    name = "cp%d" % ctypes.windll.kernel32.GetOEMCP()
                    self._codecs.lookup(name)
                except Exception:
                    name = "cp936"
                self.oem = self._codecs.getincrementaldecoder(name)("replace")
                self.oem_first = True
        return self.oem.decode(b).encode("utf-8")


class _Iface(paramiko.ServerInterface):
    def __init__(self, srv, ip, sid):
        self.srv, self.ip, self.sid = srv, ip, sid
        self.size = {}

    def get_allowed_auths(self, username):
        return "password"

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if self.srv._auth(self.ip, username, password, self.sid) else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pw, ph, modes):
        self.size[channel.chanid] = (width, height)
        return True

    def check_channel_window_change_request(self, channel, width, height, pw, ph):
        self.size[channel.chanid] = (width, height)
        self.srv._resize(channel, width, height)
        return True

    def check_channel_shell_request(self, channel):
        self.srv._tag(self.sid, "终端")
        threading.Thread(target=self.srv._shell, args=(channel, self.size.get(channel.chanid, (80, 24))), daemon=True).start()
        return True

    def check_channel_exec_request(self, channel, command):
        self.srv._tag(self.sid, "命令")
        threading.Thread(target=self.srv._exec, args=(channel, command.decode("utf-8", "replace")), daemon=True).start()
        return True

    def check_channel_env_request(self, channel, name, value):
        return False

    def check_channel_subsystem_request(self, channel, name):
        self.srv._tag(self.sid, "SFTP" if name == "sftp" else name)
        return super().check_channel_subsystem_request(channel, name)


class ShareServer:
    MAX_FAILS = 5
    LOCK_SECS = 600

    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda info: None)
        self._lock = threading.RLock()
        self.sock = None
        self.port = 0
        self.user = ""
        self.password = ""
        self.expires = 0            # 0 = 一直开到关闭工具箱
        self.started = 0
        self.sessions = {}          # sid -> {ip, since, transport}
        self.log = []               # 最近的连接记录
        self._fails = {}            # ip -> (次数, 解锁时间)
        self._ptys = {}
        self._stop = threading.Event()
        self._hostkey = None
        self._sid = 0
        self._pend_kinds = {}
        self._pend_who = {}
        self.tunnel = sharetunnel.ShareTunnel(lambda: self._changed())      # 公网入口（反向隧道到 code.zuicat.cn）；没有隧道密钥的电脑上不启用

    # ------------------------------------------------------------ 状态
    @property
    def on(self):
        return self.sock is not None

    def info(self):
        with self._lock:
            return {
                "on": self.on, "port": self.port, "user": self.user, "password": self.password,
                "public": self.tunnel.public if self.on else None, "tunnel_error": self.tunnel.error if self.on else "", "tunnel_running": self.tunnel.running if self.on else False,
                "expires": self.expires, "started": self.started,
                "sessions": [{"sid": k, "ip": v["ip"], "since": v["since"], "kinds": list(v.get("kinds", {})), "who": v.get("who", "")} for k, v in self.sessions.items()],
                "log": list(self.log[-8:]),
            }

    def _tag(self, sid, kind):
        """记下这条连接在干什么（终端/命令/SFTP），共享窗口里显示：一个客户端（VS Code、Termius…）会同时开好几条连接。"""
        with self._lock:
            v = self.sessions.get(sid)
            d = v.setdefault("kinds", {}) if v is not None else self._pend_kinds.setdefault(sid, {})        # 会话还没登记（认证刚过、请求就来了）先暂存
            d[kind] = d.get(kind, 0) + 1
        self._changed()

    def _changed(self):
        try:
            self.on_change(self.info())
        except Exception:
            pass

    def _note(self, text):
        self.log.append({"t": time.time(), "text": text})
        del self.log[:-30]

    # ------------------------------------------------------------ 开关
    def start(self, seconds=0):
        with self._lock:
            if self.on:
                return {"ok": False, "error": "已经开启了。"}
            bad = sharetunnel.precheck()                    # 没绑定码境账号 / 码境用户名不是英文：不允许共享
            if bad:
                return {"ok": False, "error": bad}
            try:
                self._hostkey = self._hostkey or _host_key()
            except Exception as e:
                return {"ok": False, "error": "生成主机密钥失败：%s" % e}
            sock = None
            last = int(settings.get("share_port", 0) or 0)
            for port in ([last] if last else []) + [secrets.randbelow(40000) + 20000 for _ in range(30)]:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    if sys.platform != "win32":
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", port))                # 只在本机回环上监听：别人只能经公网中转进来，局域网里不能直连
                    s.listen(20)
                    sock = s
                    break
                except OSError:
                    s.close()
            if not sock:
                return {"ok": False, "error": "找不到可用的端口，请稍后重试。"}
            self.sock, self.port = sock, sock.getsockname()[1]
            settings.set("share_port", self.port)
            self.user = getpass.getuser()
            self.password = "".join(secrets.choice(_ALPHA) for _ in range(16))
            self.started = time.time()
            self.expires = (time.time() + int(seconds)) if seconds else 0
            self._fails.clear()
            self.log.clear()
            self._stop.clear()
            self._note("已开启，端口 %d" % self.port)
            threading.Thread(target=self._accept, args=(sock,), daemon=True).start()
            threading.Thread(target=self._timer, daemon=True).start()
            self.tunnel.start(self.port)
        self._changed()
        return {"ok": True, **self.info()}

    def stop(self, why="已关闭"):
        with self._lock:
            if not self.on:
                return
            self._stop.set()
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self.tunnel.stop()
            for v in list(self.sessions.values()):
                try:
                    v["transport"].close()
                except Exception:
                    pass
            self.sessions.clear()
            self.password = ""
            self._note(why)
        self._changed()

    def reset_password(self):
        """重置密码：换一个新的随机密码，旧密码作废，所有正在连着的人立刻断开（要用新密码重新连）。"""
        with self._lock:
            if not self.on:
                return {"ok": False, "error": "还没有开启共享。"}
            self.password = "".join(secrets.choice(_ALPHA) for _ in range(16))
            self._fails.clear()
            n = len(self.sessions)
            for v in list(self.sessions.values()):
                try:
                    v["transport"].close()
                except Exception:
                    pass
            self.sessions.clear()
            self._note("已重置密码，断开了所有连接" if n else "已重置密码")
        self._changed()
        return {"ok": True, **self.info()}

    def kick(self, sid):
        v = self.sessions.get(sid)
        if v:
            try:
                v["transport"].close()
            except Exception:
                pass
        return True

    def _timer(self):
        while not self._stop.wait(1.0):
            if self.expires and time.time() >= self.expires:
                self.stop("开放时间到，已自动关闭")
                return

    # ------------------------------------------------------------ 连接
    def _accept(self, sock):
        sock.settimeout(0.3)                     # 不能无限阻塞在 accept 上：否则 Linux 上 close 之后端口还会保持监听
        while not self._stop.is_set():
            try:
                cl, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                # Windows 上对方在握手前强行断开（RST）也会让 accept 抛 OSError（ConnectionResetError），不能因此退出；只有真的关了才退
                if self._stop.is_set() or sock.fileno() == -1:
                    return
                time.sleep(0.05)
                continue
            cl.settimeout(None)
            threading.Thread(target=self._serve, args=(cl, addr[0]), daemon=True).start()

    def _serve(self, cl, ip):
        with self._lock:
            self._sid += 1
            sid = self._sid
        t = paramiko.Transport(cl)
        try:
            t.add_server_key(self._hostkey)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, _SFTP)
            t.start_server(server=_Iface(self, ip, sid))
        except Exception:
            try:
                t.close()
            except Exception:
                pass
            return
        ok = False
        # 等认证通过（最多 30 秒），之后一直挂到连接结束
        for _ in range(300):
            if t.is_authenticated():
                ok = True
                break
            if not t.is_active():
                break
            time.sleep(0.1)
        if not ok:
            t.close()
            return
        with self._lock:
            self.sessions[sid] = {"ip": ip, "since": time.time(), "transport": t, "kinds": self._pend_kinds.pop(sid, {}), "who": self._pend_who.pop(sid, "")}
            self._note("%s 已连接" % ip)
        self._changed()
        while t.is_active() and not self._stop.is_set():
            time.sleep(0.5)
        t.close()
        with self._lock:
            if self.sessions.pop(sid, None):
                self._note("%s 已断开" % ip)
        self._changed()

    def _auth(self, ip, username, password, sid):
        now = time.time()
        with self._lock:
            n, until = self._fails.get(ip, (0, 0))
            if until > now:
                return False
            good = self.on and hmac.compare_digest(password.encode(), self.password.encode()) and (username.lower() == self.user.lower() or (ip == "127.0.0.1" and (username == "relay" or username.startswith("relay+"))))        # 经公网中转来的连接，中转已经按码境用户名分好了设备，用户名固定 relay
            if good:
                self._fails.pop(ip, None)
                if username.startswith("relay+"):
                    self._pend_who[sid] = username[6:][:32]        # 访客自称的码境用户名（中转带过来的，没法核实）
                return True
            n += 1
            self._fails[ip] = (n, now + self.LOCK_SECS if n >= self.MAX_FAILS else 0)
            self._note("%s 密码错误（%d/%d）%s" % (ip, n, self.MAX_FAILS, "，已锁定 10 分钟" if n >= self.MAX_FAILS else ""))
        time.sleep(1.0)
        self._changed()
        return False

    # ------------------------------------------------------------ 会话内容
    def _resize(self, ch, w, h):
        p = self._ptys.get(ch.chanid)
        if not p:
            return
        try:
            if sys.platform == "win32":
                p["proc"].setwinsize(h, w)
            else:
                import fcntl
                import struct
                import termios
                fcntl.ioctl(p["fd"], termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        except Exception:
            pass

    def _shell(self, ch, size):
        w, h = size
        try:
            if sys.platform == "win32":
                self._shell_win(ch, w, h)
            else:
                self._shell_posix(ch, w, h)
        except Exception:
            pass
        finally:
            self._ptys.pop(ch.chanid, None)
            try:
                ch.send_exit_status(0)
                ch.close()
            except Exception:
                pass

    def _shell_win(self, ch, w, h):
        from winpty import PtyProcess          # ConPTY：和本机终端一样的完整终端（方向键、vim 等都正常）
        proc = PtyProcess.spawn("cmd.exe", dimensions=(h, w), cwd=os.path.expanduser("~"))
        self._ptys[ch.chanid] = {"proc": proc}

        def pump():
            try:
                while proc.isalive():
                    d = proc.read(4096)
                    if d:
                        ch.send(d.encode("utf-8", "replace"))
            except Exception:
                pass
            try:
                ch.close()
            except Exception:
                pass
        threading.Thread(target=pump, daemon=True).start()
        try:
            while not ch.closed and proc.isalive():
                if ch.recv_ready():
                    proc.write(ch.recv(4096).decode("utf-8", "replace"))
                else:
                    time.sleep(0.02)
        finally:
            try:
                proc.terminate(force=True)
            except Exception:
                pass

    def _shell_posix(self, ch, w, h):
        import fcntl
        import pty
        import struct
        import termios
        m, s = pty.openpty()
        fcntl.ioctl(m, termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        p = subprocess.Popen([os.environ.get("SHELL", "/bin/sh")], stdin=s, stdout=s, stderr=s, close_fds=True, start_new_session=True, cwd=os.path.expanduser("~"))
        os.close(s)
        self._ptys[ch.chanid] = {"fd": m}
        try:
            while p.poll() is None and not ch.closed:
                r, _, _ = select.select([m, ch], [], [], 0.1)
                if m in r:
                    d = os.read(m, 4096)
                    if not d:
                        break
                    ch.send(d)
                if ch.recv_ready():
                    os.write(m, ch.recv(4096))
        except OSError:
            pass
        finally:
            p.kill()

    def _exec(self, ch, cmd):
        recode = sys.platform == "win32" and not cmd.strip().lower().startswith(("scp ", "scp.exe", "rsync", "sftp-server"))   # scp/rsync 走二进制协议，不能转码
        if sys.platform == "win32":
            argv = "cmd.exe /C " + cmd          # 和 Windows 自带 OpenSSH 服务端一样：原样交给 cmd
        else:
            argv = [os.environ.get("SHELL", "/bin/sh"), "-c", cmd]
        try:
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN, cwd=os.path.expanduser("~"))
        except OSError as e:
            ch.send_stderr(("无法运行：%s\n" % e).encode())
            ch.send_exit_status(127)
            ch.close()
            return

        def feed():                              # scp / 管道需要把通道里的数据写进进程的 stdin
            try:
                while True:
                    d = ch.recv(32768)
                    if not d:
                        break
                    p.stdin.write(d)
                    p.stdin.flush()
            except Exception:
                pass
            try:
                p.stdin.close()
            except Exception:
                pass

        rc_out, rc_err = _Recode(recode), _Recode(recode)

        def errs():
            try:
                for chunk in iter(lambda: p.stderr.read1(32768), b""):
                    ch.send_stderr(rc_err.conv(chunk))
            except Exception:
                pass
        threading.Thread(target=feed, daemon=True).start()
        te = threading.Thread(target=errs, daemon=True)
        te.start()
        try:
            for chunk in iter(lambda: p.stdout.read1(32768), b""):
                ch.sendall(rc_out.conv(chunk))
        except Exception:
            pass
        p.wait()
        te.join(2)
        try:                                      # 顺序和 OpenSSH 的 sshd 一致：数据 → EOF → 退出码 → 关闭
            ch.shutdown_write()
            ch.send_exit_status(p.returncode or 0)
            ch.close()
        except Exception:
            pass
