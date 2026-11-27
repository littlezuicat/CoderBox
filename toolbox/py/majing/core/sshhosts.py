# -*- coding: utf-8 -*-
"""主机与两端直连传输：和用户的 ~/.ssh/config 双向同步，密码加密保存，一把通用密钥配给所有主机，SFTP 直连收发文件。

- 主机列表 = ~/.ssh/config 里的 Host 条目（单个、不带通配符的）。本程序新增的条目前面有一行 “# 克劳德工具箱” 标记；
  改动只触及对应条目的 HostName/User/Port/IdentityFile 几行，其它内容原样保留，首次写入前备份成 config.bak-toolbox。
- 密码不写进 ssh config，单独用系统用户加密（Windows DPAPI）存放；私钥是用户自己 ~/.ssh 里的文件。
- 通用密钥：~/.ssh/claude_toolbox_ed25519 和 .pub 两个文件，所有主机共用。
- 主机指纹单独记在应用自己的 known_hosts，首次连接信任并记录，之后指纹变了就拒绝。"""
import logging
import getpass
import json
import os
import posixpath
import queue
import re
import shlex
import base64
import contextlib
import socket
import stat as statmod
import subprocess
import sys
import threading
import time

import paramiko

from majing.core import account

MARK = "# 克劳德工具箱"          # 标记保持旧名：改了就认不出之前加进 ssh config 的主机
KEY_NAME = "claude_toolbox_ed25519"
_ALIAS = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_LOCK = threading.RLock()


# ------------------------------------------------------------------ 非 UTF-8 文件名（GBK 压缩包解出来的文件名等）
# paramiko 把文件名严格按 UTF-8 解码，目录里只要有一个 GBK 名字，整个目录都读不出来。
# 这里改成：UTF-8 解不了就按 GB18030 解码给界面显示，同时记下原始字节；之后用这个显示名做路径时，发给服务器的还是原始字节，重命名/删除/下载都照常。
_RAW = {}                                # 显示名 → 原始字节（只有非 UTF-8 的名字才会进来）


def _patch_paramiko_names():
    from paramiko import message as _msg
    from paramiko import sftp_client as _sc

    def get_text(self):
        raw = self.get_string()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = raw.decode("gb18030", "replace")
            if len(_RAW) < 20000:
                _RAW[txt] = raw
            return txt

    orig_b = _sc.b

    def b(s, encoding="utf8"):
        if _RAW and isinstance(s, str):
            segs = s.split("/")
            if any(x in _RAW for x in segs):
                return b"/".join(_RAW.get(x, x.encode("utf-8")) for x in segs)
        return orig_b(s, encoding)

    _msg.Message.get_text = get_text
    _sc.b = b


try:
    _patch_paramiko_names()
except Exception:                        # noqa: BLE001  换了 paramiko 版本结构不同就算了，只是回到原来的行为
    logging.getLogger("majing.ssh").warning("没能打上非 UTF-8 文件名补丁", exc_info=True)


# ------------------------------------------------------------------ 路径
def ssh_dir():
    d = os.environ.get("CLAUDE_SSH_DIR") or os.path.join(os.path.expanduser("~"), ".ssh")
    os.makedirs(d, exist_ok=True)
    return d


def _data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "MajingToolbox")
    os.makedirs(d, exist_ok=True)
    return d


def key_path():
    return os.path.join(ssh_dir(), KEY_NAME)


def _config_path():
    return os.path.join(ssh_dir(), "config")


# ------------------------------------------------------------------ ssh config 读写
def _read_lines():
    try:
        with open(_config_path(), "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return [], "\n"
    text = raw.decode("utf-8", errors="surrogateescape")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(True), nl


def _write_lines(lines):
    p = _config_path()
    bak = p + ".bak-toolbox"
    if os.path.exists(p) and not os.path.exists(bak):
        try:
            with open(p, "rb") as f, open(bak, "wb") as g:
                g.write(f.read())
        except OSError:
            pass
    tmp = p + ".tmp-toolbox"
    with open(tmp, "wb") as f:
        f.write("".join(lines).encode("utf-8", errors="surrogateescape"))
    os.replace(tmp, p)


_HOST_RE = re.compile(r"^\s*Host\s+(.+?)\s*$", re.I)
_MATCH_RE = re.compile(r"^\s*Match\s", re.I)
_KV_RE = re.compile(r"^\s*([A-Za-z]+)\s*(?:=|\s)\s*(.*?)\s*$")


def _blocks(lines):
    """[(start, end, patterns)]：每个 Host 条目占 lines[start:end]（end 不含）。"""
    out, cur = [], None
    for i, ln in enumerate(lines):
        m = _HOST_RE.match(ln)
        if m or _MATCH_RE.match(ln):
            if cur:
                out.append((cur[0], i, cur[1]))
            cur = (i, m.group(1).split() if m else None)
    if cur:
        out.append((cur[0], len(lines), cur[1]))
    return [b for b in out if b[2]]


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return v


def _fields(block):
    f = {}
    for ln in block[1:]:
        if ln.lstrip().startswith("#"):
            continue
        m = _KV_RE.match(ln)
        if m:
            f.setdefault(m.group(1).lower(), _unquote(m.group(2)))
    return f


def _hidden(alias):
    return alias.startswith("coderland-")      # “远程连接”临时建的别名，不算用户的主机


# ------------------------------------------------------------------ 地址池（IP 池）
# 一个主机可以有多个地址（内网 / 公网 / 备用）。ssh config 里只写第一个（系统的 ssh 命令用它），完整顺序存在应用自己的 hosts_pool.json。
def _pool_path():
    return os.path.join(_data_dir(), "hosts_pool.json")


def _load_pool():
    try:
        with open(_pool_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _store_pool(d):
    try:
        with open(_pool_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def is_internal(host):
    """是不是内网地址（RFC1918：10.x、172.16–31.x、192.168.x）。只看字面 IP；域名返回 None（连上以后再按实际对端 IP 判断）。"""
    import ipaddress
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    return any(ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _norm_addrs(addrs):
    out = []
    for a in addrs or []:
        host = str(a.get("host") or "").strip()
        if not host:
            continue
        if re.search(r"[\s'\"#]", host):
            raise ValueError("地址“%s”里不能有空格或引号。" % host)
        try:
            port = int(a.get("port") or 22)
            assert 1 <= port <= 65535
        except Exception:
            raise ValueError("地址“%s”的端口应是 1–65535 的数字。" % host)
        if not any(x["host"] == host and x["port"] == port for x in out):
            out.append({"host": host, "port": port})
    return out


def _addrs_for(alias, host, port):
    """这个主机的完整地址顺序：以 ssh config 里的为第一个（config 被外部改过就以 config 为准），其余按存下来的顺序跟在后面。"""
    primary = {"host": host, "port": port}
    rest = [a for a in _load_pool().get(alias, []) if not (a["host"] == host and a["port"] == port)]
    return [primary] + rest


def list_hosts():
    lines, _ = _read_lines()
    pw = _load_pw()
    hosts = []
    for s, e, pats in _blocks(lines):
        if len(pats) != 1 or any(c in pats[0] for c in "*?!") or _hidden(pats[0]):
            continue
        f = _fields(lines[s:e])
        alias = pats[0]
        host, port = f.get("hostname", alias), int(f["port"]) if f.get("port", "").isdigit() else 22
        addrs = _addrs_for(alias, host, port)
        ident = f.get("identityfile", "")
        common = bool(ident) and os.path.normcase(os.path.normpath(_expand(ident))) == os.path.normcase(os.path.normpath(key_path()))      # 这台主机的 IdentityFile 是不是通用密钥
        hosts.append({
            "alias": alias, "host": host, "user": f.get("user", ""), "port": port,
            "addrs": [{**a, "internal": is_internal(a["host"])} for a in addrs],
            "identity": ident, "has_password": alias in pw, "common_key": common,
            "managed": s > 0 and lines[s - 1].strip() == MARK,
        })
    return hosts


def _fmt(v):
    return '"%s"' % v if re.search(r"\s", v) else v


def _check(h):
    alias = (h.get("alias") or "").strip()
    if not _ALIAS.match(alias):
        raise ValueError("别名只能用字母、数字、点、横线和下划线（最长 64 位）。")
    addrs = _norm_addrs(h["addrs"]) if h.get("addrs") else _norm_addrs([{"host": h.get("host"), "port": h.get("port")}])
    if not addrs:
        raise ValueError("请填写主机的 IP 或域名。")
    host, port = addrs[0]["host"], addrs[0]["port"]
    user = (h.get("user") or "").strip()
    if re.search(r"[\s'\"#]", user):
        raise ValueError("用户名里不能有空格或引号。")
    ident = (h.get("identity") or "").strip()
    if re.search(r"['\"#]", ident):
        raise ValueError("私钥路径里不能有引号。")
    return alias, host, user, port, ident, addrs


def _find_key(blk, key):
    for i in range(1, len(blk)):
        if blk[i].lstrip().startswith("#"):
            continue
        m = _KV_RE.match(blk[i])
        if m and m.group(1).lower() == key.lower():
            return i
    return None


def _set_key(blk, key, val, nl, only_if_missing=False):
    """在一个 Host 条目（行列表）里设置/删除一项，其余行不动。"""
    idx = _find_key(blk, key)
    if val:
        if idx is not None:
            if not only_if_missing:
                blk[idx] = re.match(r"\s*", blk[idx]).group(0) + "%s %s%s" % (key, _fmt(val), nl)
        else:
            last = max(i for i, ln in enumerate(blk) if ln.strip())
            if not blk[last].endswith("\n"):
                blk[last] += nl
            blk.insert(last + 1, "    %s %s%s" % (key, _fmt(val), nl))
    elif idx is not None and key.lower() != "hostname":
        del blk[idx]


def save_host(h, old_alias=None):
    """新增或更新一个主机（同步到 ssh config），密码若给了就加密保存。返回 list_hosts() 里这一项。"""
    alias, host, user, port, ident, addrs = _check(h)
    old = (old_alias or alias).strip()
    with _LOCK:
        lines, nl = _read_lines()
        blocks = _blocks(lines)
        if alias != old and any(b[2] == [alias] for b in blocks):
            raise ValueError("别名“%s”已经有了。" % alias)
        target = next((b for b in blocks if b[2] == [old]), None)
        if not target and any(b[2] == [alias] for b in blocks):
            target = next(b for b in blocks if b[2] == [alias])
            old = alias
        want = [("HostName", host), ("User", user), ("Port", str(port) if port != 22 else ""), ("IdentityFile", ident)]
        if target:
            s, e, _ = target
            blk = lines[s:e]
            blk[0] = re.match(r"\s*Host\s+", blk[0], re.I).group(0) + alias + (nl if blk[0].endswith("\n") else "")
            for key, val in want:
                _set_key(blk, key, val, nl)
            if ident:
                _set_key(blk, "IdentitiesOnly", "yes", nl, only_if_missing=True)
            lines[s:e] = blk
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += nl
            if lines and lines[-1].strip():
                lines.append(nl)
            lines.append(MARK + nl)
            lines.append("Host %s%s" % (alias, nl))
            for key, val in want:
                if val:
                    lines.append("    %s %s%s" % (key, _fmt(val), nl))
            if ident:
                lines.append("    IdentitiesOnly yes" + nl)
        _write_lines(lines)
        pool_d = _load_pool()
        pool_d.pop(old, None)
        pool_d[alias] = addrs
        _store_pool(pool_d)
        _put_status(old, None)
        _put_status(alias, None)
        pw = h.get("password")
        data = _load_pw()
        if old != alias and old in data:
            data[alias] = data.pop(old)
        if pw:
            data[alias] = pw
        _store_pw(data)
    return next(x for x in list_hosts() if x["alias"] == alias)


def delete_host(alias):
    with _LOCK:
        lines, _ = _read_lines()
        for s, e, pats in _blocks(lines):
            if pats == [alias]:
                if s > 0 and lines[s - 1].strip() == MARK:
                    s -= 1
                    if s > 0 and not lines[s - 1].strip():
                        s -= 1
                del lines[s:e]
                _write_lines(lines)
                break
        data = _load_pw()
        if data.pop(alias, None) is not None:
            _store_pw(data)
        pool_d = _load_pool()
        if pool_d.pop(alias, None) is not None:
            _store_pool(pool_d)
        _put_status(alias, None)
    _drop(alias)
    return True


def set_identity(alias, ident):
    h = next((x for x in list_hosts() if x["alias"] == alias), None)
    if not h:
        raise ValueError("没有这个主机。")
    save_host({**h, "identity": ident}, alias)


# ------------------------------------------------------------------ 密码（加密保存）
def _pw_path():
    return os.path.join(_data_dir(), "hosts.bin")


def _load_pw():
    try:
        with open(_pw_path(), "rb") as f:
            return json.loads(account._unprotect(f.read()).decode("utf-8"))
    except Exception:
        return {}


def _store_pw(d):
    with open(_pw_path(), "wb") as f:
        f.write(account._protect(json.dumps(d, ensure_ascii=False).encode("utf-8")))


# ------------------------------------------------------------------ 连接
log = logging.getLogger("majing.ssh")


class _TOFU(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        client.get_host_keys().add(hostname, key.get_name(), key)


def _known_hosts():
    return os.path.join(_data_dir(), "known_hosts")


def _expand(p):
    return os.path.expanduser(p) if p else p


def _load_key(path):
    try:
        return paramiko.PKey.from_path(path)
    except paramiko.PasswordRequiredException:
        raise ValueError("私钥 %s 有密码短语，暂时不支持，请用没有密码短语的私钥，或点“一键创建密钥”。" % os.path.basename(path))


def _key_candidates(p):
    """按顺序尝试的私钥文件：主机自己写的 IdentityFile，其次通用密钥。"""
    out = []
    for c in (_expand(p.get("identity")), key_path()):
        if c and os.path.isfile(c) and c not in out:
            out.append(c)
    return out


def _winerr(e):
    """从各种包装过的异常里取 Windows 套接字错误码（没有就 None）。"""
    seen = 0
    while e is not None and seen < 5:
        w = getattr(e, "winerror", None)
        if w:
            return w
        if isinstance(e, paramiko.ssh_exception.NoValidConnectionsError):
            for sub in (getattr(e, "errors", None) or {}).values():
                w = getattr(sub, "winerror", None)
                if w:
                    return w
        e = e.__cause__ or e.__context__
        seen += 1
    return None


def _explain(e, host, port):
    if _winerr(e) == 10013:
        return ("本机的网络访问被拦截了（WinError 10013）：Windows 防火墙、杀毒/VPN（如 aTrust）或 Clash 虚拟网卡不让工具箱连 %s:%d。"
                "请把“码境工具箱”加进防火墙/代理软件的放行名单，或退出冲突的 VPN 后重试。") % (host, port)
    if isinstance(e, paramiko.SSHException) and "banner" in str(e).lower():
        return "%s:%d 的 SSH 握手被中途断开了（中转或网络不稳，已自动重试仍失败），请稍后再试。" % (host, port)
    if isinstance(e, paramiko.BadHostKeyException):
        return "主机“%s”的身份和上次记录的不一致（可能被冒充，也可能重装过系统）。如果确认是重装，请删掉应用数据目录里 known_hosts 对应的行。" % host
    if isinstance(e, paramiko.AuthenticationException):
        return "认证失败：密码或密钥不对。"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "连接 %s:%d 超时，请检查 IP、端口和网络。" % (host, port)
    if isinstance(e, socket.gaierror):
        return "找不到主机“%s”，请检查 IP 或域名。" % host
    if isinstance(e, (ConnectionRefusedError, paramiko.ssh_exception.NoValidConnectionsError)):
        return "%s:%d 拒绝了连接，对方可能没开 SSH 服务或端口不对。" % (host, port)
    if isinstance(e, ValueError):
        return str(e)
    return "连接失败：%s" % (e,)


class AuthError(ConnectionError):
    """认证失败（密码/密钥不对）或没有凭据：换地址也没用，不再往下试。"""


def _tag(c, a, via, prio):
    c.tb_addr = a
    c.tb_via = via
    c.tb_prio = prio                    # 在地址池里的序号，越小优先级越高
    try:
        c.tb_ip = c.get_transport().getpeername()[0]
        c.tb_internal = is_internal(c.tb_ip) is True
    except Exception:
        c.tb_ip, c.tb_internal = a["host"], bool(is_internal(a["host"]))


def connect(p, timeout=10, use_password=True, use_key=True, on_better=None):
    """p: {host,port,user,identity,password,addrs?}。地址池里的每个地址同时去连，谁先连上先用谁（内网不通时不用干等它超时再轮到公网）。
    先连上的不是优先级最高的话，后面优先级更高的那个连上了，就调 on_better(client, via)（没给回调就直接关掉）。认证失败（密码/密钥不对）换地址也没用，直接报错。
    返回 (client, via)；via 是 'key' 或 'password'。client.tb_addr / tb_ip / tb_internal / tb_prio 记录实际用的是哪个地址、对端 IP、是不是内网、优先级序号。"""
    addrs = _norm_addrs(p["addrs"]) if p.get("addrs") else _norm_addrs([{"host": p.get("host"), "port": p.get("port")}])
    if not addrs:
        raise ConnectionError("没有可用的地址。")
    n = len(addrs)
    q = queue.Queue()

    def one(i, a):
        t = timeout if i == n - 1 else min(timeout, 4)          # 前面的地址（多半是内网）连不上要快点放弃
        t0 = time.time()
        try:
            c, via = _connect_one({**p, "host": a["host"], "port": a["port"]}, t, use_password, use_key)
        except AuthError as e:
            log.warning("连接 %s:%s 认证失败（%.1fs）：%s", a["host"], a["port"], time.time() - t0, e)
            q.put((i, None, None, e))
            return
        except Exception as e:                                   # noqa: BLE001
            log.info("连接 %s:%s 没连上（%.1fs，超时设 %ss）：%s", a["host"], a["port"], time.time() - t0, t, e)
            q.put((i, None, None, e))
            return
        log.info("连接 %s:%s 成功（%.1fs，%s 登录）", a["host"], a["port"], time.time() - t0, via)
        _tag(c, a, via, i)
        q.put((i, c, via, None))

    for i, a in enumerate(addrs):
        threading.Thread(target=one, args=(i, a), daemon=True).start()
    pending = set(range(n))
    last = None
    got = None                                                   # (i, c, via)
    while pending:
        i, c, via, err = q.get()
        pending.discard(i)
        if c is not None:
            got = (i, c, via)
            break
        if isinstance(err, AuthError):
            if pending:
                threading.Thread(target=_drain, args=(q, pending, n, None, None), daemon=True).start()
            raise err
        last = err
    if got is None:
        if n > 1:
            raise ConnectionError("所有地址都连不上（共 %d 个）。最后一个：%s" % (n, last))
        raise last
    # 剩下还在连的：优先级更高的连上了就换过去，其余关掉
    if pending:
        threading.Thread(target=_drain, args=(q, pending, n, got[0], on_better), daemon=True).start()
    return got[1], got[2]


def _drain(q, pending, n, cur, on_better):
    """收尾：把还没出结果的连接处理掉。cur 是已经在用的那个连接的序号（None=没有）。"""
    best = cur
    while pending:
        i, c, via, err = q.get()
        pending.discard(i)
        if c is None:
            continue
        if on_better is not None and (best is None or i < best) and cur is not None:
            best = i
            try:
                on_better(c, via)
                continue
            except Exception as e:                               # noqa: BLE001
                log.info("换到优先级更高的地址失败：%s", e)
        try:
            c.close()
        except Exception:                                        # noqa: BLE001
            pass


_MYNAME = {"v": None}


def _relay_user(user, host, port):
    """连 code.zuicat.cn 的共享中转（41764）时，把自己的码境用户名接在后面（目标+我），让被控端的共享窗口看到是谁在连。没绑定/不是英文/离线就原样。"""
    if host != "code.zuicat.cn" or port != 41764 or "+" in user:
        return user
    if _MYNAME["v"] is None:
        try:
            from majing import APP_VERSION
            from majing.core import account, sharetunnel
            st = account.status("MajingToolbox/" + APP_VERSION) if account.token() else {}
            n = st.get("username") or ""
            _MYNAME["v"] = n if sharetunnel.NAME_RE.match(n) else ""
        except Exception:                                        # noqa: BLE001
            return user
    return "%s+%s" % (user, _MYNAME["v"]) if _MYNAME["v"] else user


def _connect_one(p, timeout=10, use_password=True, use_key=True):
    host, port = p["host"], int(p.get("port") or 22)
    user = _relay_user(p.get("user") or getpass.getuser(), host, port)
    attempts = []
    if use_key:
        for kp in _key_candidates(p):
            attempts.append(("key", kp))
    if use_password and p.get("password"):
        attempts.append(("password", None))
    if not attempts:
        raise AuthError("这个主机还没有密码，也没有可用的私钥。")
    last = None
    for via, kp in attempts:
        for tries in range(3):
            c = paramiko.SSHClient()
            kh = _known_hosts()
            if os.path.exists(kh):
                try:
                    c.load_host_keys(kh)
                except Exception:
                    pass
            c.set_missing_host_key_policy(_TOFU())
            try:
                kw = dict(hostname=host, port=port, username=user, timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
                          allow_agent=False, look_for_keys=False)
                if via == "key":
                    kw["pkey"] = _load_key(kp)
                else:
                    kw["password"] = p["password"]
                c.connect(**kw)
                try:
                    c.save_host_keys(kh)
                except Exception:
                    pass
                tr = c.get_transport()
                tr.set_keepalive(20)
                try:
                    # Windows 默认的 TCP 发送缓冲很小，上传（本机→服务器）只能到 ~28MB/s（CPU 不忙、在等对端）；
                    # 放大到 8MB 后内网可达 ~95MB/s（实测 622：28 → 94）。只影响发送，几乎不占内存
                    tr.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
                except Exception:                                    # noqa: BLE001
                    pass
                return c, via
            except Exception as e:
                c.close()
                last = e
                log.debug("  %s:%s %s登录%s失败：%s: %s", host, port, via, ("(%s)" % os.path.basename(kp)) if kp else "", type(e).__name__, e)
                msg = str(e).lower()
                transient = (isinstance(e, paramiko.SSHException) and ("banner" in msg or "negotiation" in msg)) or _winerr(e) in (10013, 10048, 10053, 10054)
                if tries < 2 and transient:
                    # 中转（frp 等）偶尔在握手时掐掉连接；Windows 的 10013/10048 多半是防火墙/代理软件（TUN、aTrust…）或临时端口一时被占，隔一会儿再来
                    time.sleep(0.8 * (tries + 1))
                    continue
                break
        e = last
        if isinstance(e, paramiko.AuthenticationException) or (isinstance(e, ValueError) and via == "key"):
            continue            # 换下一种方式
        raise ConnectionError(_explain(e, host, port))
    raise AuthError(_explain(last, host, port))


def _params(alias):
    h = next((x for x in list_hosts() if x["alias"] == alias), None)
    if not h:
        raise ConnectionError("没有这个主机。")
    return {**h, "password": _load_pw().get(alias, "")}


def _run(c, cmd, timeout=20):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    return o.channel.recv_exit_status(), out, err


def detect_os(c):
    try:
        code, out, _ = _run(c, "uname -s", 8)
        if code == 0 and out.strip():
            return out.strip()
    except Exception:
        pass
    return "Windows"


_SYS_LINUX = r"""
. /etc/os-release 2>/dev/null
echo "NAME=${PRETTY_NAME:-$(uname -s)}"
echo "ARCH=$(uname -m)"
echo "CPU=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//')"
# ---- 容器的额度：cgroup 的 CPU 配额、内存上限（cgroup v2 或 v1）；没设上限就是整机
if [ -r /sys/fs/cgroup/cpu.max ]; then
  V2=1; read q p < /sys/fs/cgroup/cpu.max
  MEMMAX=/sys/fs/cgroup/memory.max; MEMUSE=/sys/fs/cgroup/memory.current; MEMSTAT=/sys/fs/cgroup/memory.stat; INACT=inactive_file
else
  V2=0; q=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null); p=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null)
  ACCT=/sys/fs/cgroup/cpuacct/cpuacct.usage; [ -r "$ACCT" ] || ACCT=/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage
  MEMMAX=/sys/fs/cgroup/memory/memory.limit_in_bytes; MEMUSE=/sys/fs/cgroup/memory/memory.usage_in_bytes; MEMSTAT=/sys/fs/cgroup/memory/memory.stat; INACT=total_inactive_file
fi
acct() { if [ "$V2" = 1 ]; then awk '/^usage_usec/{print $2*1000}' /sys/fs/cgroup/cpu.stat; else cat "$ACCT"; fi; }
NCPU=$(nproc 2>/dev/null)
if [ -n "$q" ] && [ "$q" != max ] && [ "$q" -gt 0 ] 2>/dev/null; then QCPU=$(awk -v q="$q" -v p="$p" 'BEGIN{printf "%.2f", q/p}'); else QCPU=$NCPU; fi
echo "CORES=$(awk -v c="$QCPU" 'BEGIN{printf "%d", c+0.5}')"
a1=$(acct); t1=$(date +%s%N); sleep 0.5; a2=$(acct); t2=$(date +%s%N)
echo "CPUUSE=$(awk -v a="$a1" -v b="$a2" -v t1="$t1" -v t2="$t2" -v c="$QCPU" 'BEGIN{d=t2-t1; if(d>0 && c>0){v=(b-a)/d/c*100; if(v<0)v=0; if(v>100)v=100; printf "%.1f", v}}')"
TOT=$(awk '/^MemTotal:/{print $2*1024}' /proc/meminfo)
LIM=$(cat $MEMMAX 2>/dev/null)
case "$LIM" in ''|max|*[!0-9]*) LIM=$TOT;; esac
[ "$LIM" -gt "$TOT" ] 2>/dev/null && LIM=$TOT
USE=$(cat $MEMUSE 2>/dev/null); INA=$(awk -v k=$INACT '$1==k{print $2}' $MEMSTAT 2>/dev/null)
echo "MEM=$LIM $(awk -v u="${USE:-0}" -v i="${INA:-0}" 'BEGIN{x=u-i; if(x<0)x=0; printf "%.0f", x}')"
CONT=0; { [ "$(stat -f -c %T / 2>/dev/null)" = overlayfs ] || [ -e /.dockerenv ] || [ -e /run/.containerenv ]; } && CONT=1
echo "CONT=$CONT"
# 只有容器才要自己量根目录用了多少（df 报的是宿主机整块盘）；真机直接用 df，遍历整个根目录要二十多秒
[ "$CONT" = 1 ] && echo "DU=$(timeout 25 du -sxB1 --exclude=/proc --exclude=/sys --exclude=/dev / 2>/dev/null | tail -1 | awk '{print $1}')"
echo "GPUS=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU')"
echo "RO=$(awk '$4 ~ /^ro(,|$)/ {print $2}' /proc/mounts 2>/dev/null | paste -sd, -)"
echo "VOLS=$(df -PB1 -T 2>/dev/null | awk 'NR>1 && $2 ~ /^(ext[234]|xfs|btrfs|zfs|ceph|nfs|nfs4|cifs|smbfs|fuse)/ && $7 !~ /^\/(etc|usr|proc|sys|dev|run|boot|snap)(\/|$)/ {print $1, $7, $3, $4, $2}' | while read src mnt tot used typ; do printf '%s|%s|%s|%s|%s;' "$mnt" "$tot" "$used" "$typ" "$src"; done)"
"""

_SYS_WIN = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$o = Get-CimInstance Win32_OperatingSystem
$c = Get-CimInstance Win32_Processor | Select-Object -First 1
$d = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$dm = (Get-Partition -DriveLetter C -ErrorAction SilentlyContinue | Get-Disk -ErrorAction SilentlyContinue).FriendlyName
[pscustomobject]@{ os = $o.Caption; cpu = $c.Name; cores = $c.NumberOfLogicalProcessors; cpuUse = $c.LoadPercentage;
  memTotal = [int64]$o.TotalVisibleMemorySize * 1024; memFree = [int64]$o.FreePhysicalMemory * 1024;
  diskTotal = [int64]$d.Size; diskFree = [int64]$d.FreeSpace; disk = $dm;
  sysDrive = $env:SystemDrive;
  drives = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object { [pscustomobject]@{ id = $_.DeviceID; size = [int64]$_.Size; free = [int64]$_.FreeSpace } }) } | ConvertTo-Json -Compress -Depth 4
"""


def _num_or(s, default=0):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


CONTAINER_DISK_BYTES = 200 * 1024 ** 3      # 容器没有显卡时的实例盘规格
CONTAINER_GPU_DISK_BYTES = 100 * 1024 ** 3  # 容器每张显卡配的实例盘（读不到真实额度时按这个算）


def _fnum(s, default=0.0):
    try:
        return round(float(s), 1)
    except (TypeError, ValueError):
        return default


def sysinfo(alias):
    """主机的系统信息：系统名、CPU 型号/核数/占用、内存和系统盘的总量/已用、硬盘型号。Linux 用 shell，Windows 用 PowerShell。"""
    try:
        c = exec_client(alias)
        if detect_os(c) == "Windows":
            import base64
            enc = base64.b64encode(_SYS_WIN.encode("utf-16-le")).decode()
            code, out, err = _run(c, "powershell -NoProfile -NonInteractive -EncodedCommand " + enc, 25)
            import json
            j = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
            if not j:
                return {"ok": False, "error": (err or "没读到系统信息").strip()[:200]}
            mt, mf = int(j.get("memTotal") or 0), int(j.get("memFree") or 0)
            dt, df_ = int(j.get("diskTotal") or 0), int(j.get("diskFree") or 0)
            sysd = (j.get("sysDrive") or "C:").upper()
            drives = j.get("drives") or []
            if isinstance(drives, dict):
                drives = [drives]
            disks = [{"kind": "system" if str(d.get("id", "")).upper() == sysd else "mount", "mount": d.get("id", ""), "total": int(d.get("size") or 0),
                      "used": max(0, int(d.get("size") or 0) - int(d.get("free") or 0))} for d in drives if int(d.get("size") or 0) > 0]
            if not disks:
                disks = [{"kind": "system", "mount": sysd, "total": dt, "used": max(0, dt - df_)}]
            disks.sort(key=lambda x: (x["kind"] != "system", x["mount"]))
            return {"ok": True, "family": "windows", "name": j.get("os") or "Windows", "container": False, "gpus": 0,
                    "cpu": {"model": j.get("cpu") or "", "cores": int(j.get("cores") or 0), "usage": int(j.get("cpuUse") or 0)},
                    "mem": {"total": mt, "used": max(0, mt - mf)},
                    "disks": disks}
        code, out, err = _run(c, "sh -c " + shlex.quote(_SYS_LINUX), 25)
        kv = {}
        for ln in out.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                kv[k.strip()] = v.strip()
        if not kv:
            return {"ok": False, "error": (err or "没读到系统信息").strip()[:200]}
        mem_t, mem_u = (kv.get("MEM") or "0 0").split()[:2] if kv.get("MEM") else ("0", "0")
        in_container = kv.get("CONT") == "1"
        gpus = _num_or(kv.get("GPUS"))
        ro = set(filter(None, (kv.get("RO") or "").split(",")))
        disks, seen = [], set()
        for item in (kv.get("VOLS") or "").split(";"):
            p = item.split("|")
            if len(p) < 5 or not p[0] or p[0] in ro:                # 只读的（比如 /public 公共盘）不算
                continue
            mnt, tot, used, typ, src = p[0], _num_or(p[1]), _num_or(p[2]), p[3], p[4]
            if tot <= 0 or (src, tot) in seen:                      # 同一个设备被挂了多次（bind mount）只算一次
                continue
            seen.add((src, tot))
            if typ.startswith("ceph") or mnt.rstrip("/") == "/cloud":
                kind = "cloud"
            elif mnt == "/":
                kind = "system"
            else:
                kind = "mount"
            disks.append({"kind": kind, "mount": mnt, "total": tot, "used": min(used, tot)})
        if in_container:
            # 容器的系统盘：平台给的额度在容器里读不到（df 报的是宿主机整块盘），按每张显卡 100 GB 算，没有显卡就按 200 GB
            nominal = CONTAINER_GPU_DISK_BYTES * gpus if gpus > 0 else CONTAINER_DISK_BYTES
            disks = [d for d in disks if d["kind"] != "system"]
            disks.insert(0, {"kind": "system", "mount": "/", "total": nominal, "used": min(_num_or(kv.get("DU")), nominal), "nominal": True})
        elif not any(d["kind"] == "system" for d in disks):
            r = _num_or(kv.get("DU"))
            disks.insert(0, {"kind": "system", "mount": "/", "total": max(r, 0), "used": max(r, 0)})
        order = {"system": 0, "mount": 1, "cloud": 2}
        disks.sort(key=lambda d: (order[d["kind"]], d["mount"]))
        cloud = next((d["mount"] for d in disks if d["kind"] == "cloud"), "")
        return {"ok": True, "family": "linux", "name": kv.get("NAME") or "Linux", "arch": kv.get("ARCH", ""), "container": in_container, "gpus": gpus,
                "cpu": {"model": kv.get("CPU", ""), "cores": _num_or(kv.get("CORES")), "usage": _fnum(kv.get("CPUUSE"))},
                "mem": {"total": _num_or(mem_t), "used": _num_or(mem_u)},
                "disks": disks, "cloudPath": cloud}
    except Exception as e:                                # noqa: BLE001
        drop_exec(alias)
        return {"ok": False, "error": str(e)[:200]}


def probe_all(p, timeout=6):
    """IP 池里的每个地址同时测一遍（互不等待）。返回 (总体结果, 每个地址的结果列表)。
    总体 ok = 任意一个地址连得上；via/addr/internal 取地址池里排最前的那个连得上的。"""
    addrs = _norm_addrs(p["addrs"]) if p.get("addrs") else _norm_addrs([{"host": p.get("host"), "port": p.get("port")}])
    if not addrs:
        return {"ok": False, "error": "请先填主机的 IP 或域名。"}, []
    rows = [None] * len(addrs)
    clients = [None] * len(addrs)

    def one(i, a):
        t0 = time.time()
        try:
            c, via = _connect_one({**p, "host": a["host"], "port": a["port"]}, timeout)
        except AuthError as e:
            rows[i] = {**a, "ok": False, "reachable": True, "error": str(e)}
            return
        except ConnectionError as e:
            rows[i] = {**a, "ok": False, "reachable": False, "error": str(e)}
            return
        except Exception as e:
            rows[i] = {**a, "ok": False, "reachable": False, "error": str(e)}
            return
        try:
            ip = c.get_transport().getpeername()[0]
            internal = is_internal(ip) is True
        except Exception:
            internal = bool(is_internal(a["host"]))
        c.tb_internal, c.tb_addr = internal, a
        clients[i] = c
        rows[i] = {**a, "ok": True, "via": via, "ms": int((time.time() - t0) * 1000), "internal": internal}

    ths = [threading.Thread(target=one, args=(i, a), daemon=True) for i, a in enumerate(addrs)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    first = next((i for i, r in enumerate(rows) if r and r["ok"]), None)
    if first is None:
        errs = [r["error"] for r in rows if r]
        # 认证失败比连不上更有信息量：地址通了，只是密码/密钥不对
        auth = next((r["error"] for r in rows if r and r.get("reachable")), None)
        msg = auth or (errs[0] if len(errs) == 1 else "所有地址都连不上（共 %d 个）。" % len(errs))
        return {"ok": False, "error": msg}, rows
    res = {"ok": True, "via": rows[first]["via"], "ms": rows[first]["ms"], "internal": rows[first]["internal"], "addr": addrs[first], "_client": clients[first]}
    for i, c in enumerate(clients):
        if c is not None and i != first:
            try:
                c.close()
            except Exception:
                pass
    return res, rows


def test(p):
    """测试一组参数（还没保存的也行）。每个地址同时测。返回 {ok, via, os, error, addr, internal, rows}。"""
    try:
        res, rows = probe_all(p, timeout=8)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    c = res.pop("_client", None)
    res["rows"] = [{k: v for k, v in r.items()} for r in rows if r]
    if c is not None:
        try:
            res["os"] = detect_os(c)
        finally:
            c.close()
    return res


# ------------------------------------------------------------------ 连通性状态（存成文件，下次打开直接显示上次的结果）
def _status_path():
    return os.path.join(_data_dir(), "hosts_status.json")


def load_status():
    try:
        with open(_status_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _put_status(alias, res):
    with _LOCK:
        d = load_status()
        if res is None:
            if d.pop(alias, None) is None:
                return
        else:
            d[alias] = {**res, "t": time.time()}
        try:
            with open(_status_path(), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError:
            pass


def check(alias):
    """快速测一台已保存主机的连通性（IP 池里的地址同时测）：{ok, via, ms, error, internal, addr, rows}。via=key 说明用密钥就能登录。"""
    try:
        p = _params(alias)
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    res, rows = probe_all(p, timeout=6)
    c = res.pop("_client", None)
    if c is not None:
        c.close()
    res["rows"] = [r for r in rows if r]
    _put_status(alias, {k: v for k, v in res.items() if k != "rows"})
    return res


# ------------------------------------------------------------------ 通用密钥
def key_status():
    kp = key_path()
    if not (os.path.isfile(kp) and os.path.isfile(kp + ".pub")):
        return {"exists": False, "path": kp}
    try:
        pk = paramiko.PKey.from_path(kp)
        fp = "SHA256:" + __import__("base64").b64encode(__import__("hashlib").sha256(pk.asbytes()).digest()).decode().rstrip("=")
    except Exception:
        fp = ""
    return {"exists": True, "path": kp, "fingerprint": fp}


def _my_sid():
    """当前用户的 SID。用 SID 授权最稳：用户名和电脑名相同（比如都叫 zuicat）时，按名字授权会授给电脑账户。"""
    r = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, creationflags=0x08000000, timeout=15)
    m = re.search(r'S-1-[0-9-]+', r.stdout)
    return m.group(0) if m else None


def _lock_down(path):
    """私钥只让当前用户读写（OpenSSH 要求；Windows 上去掉继承、只授权给自己，POSIX 上 chmod 600）。"""
    try:
        if sys.platform == "win32":
            sid = _my_sid()
            if not sid:
                return
            flags = 0x08000000
            subprocess.run(["icacls", path, "/grant:r", "*%s:F" % sid], capture_output=True, creationflags=flags, timeout=15)
            subprocess.run(["icacls", path, "/inheritance:r"], capture_output=True, creationflags=flags, timeout=15)
            try:
                with open(path, "rb") as f:
                    f.read(1)
            except OSError:                        # 收紧后自己都读不了：恢复默认权限，宁可宽一点也别把密钥锁死
                subprocess.run(["icacls", path, "/reset"], capture_output=True, creationflags=flags, timeout=15)
        else:
            os.chmod(path, 0o600)
    except Exception:
        pass


def ensure_key():
    """没有通用密钥就生成一对（私钥 + .pub 两个文件）；已有就原样返回。"""
    st = key_status()
    if st["exists"]:
        return st
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    k = ed25519.Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    comment = re.sub(r"[^A-Za-z0-9._-]", "", "claude-toolbox@" + socket.gethostname())
    kp = key_path()
    with open(kp, "wb") as f:
        f.write(priv)
    _lock_down(kp)
    with open(kp + ".pub", "w", encoding="ascii", newline="\n") as f:
        f.write("%s %s\n" % (pub, comment))
    return key_status()


def _pub_line():
    with open(key_path() + ".pub", encoding="ascii") as f:
        return f.read().strip()


_SH = ("umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; "
       "if [ -s ~/.ssh/authorized_keys ] && [ -n \"$(tail -c1 ~/.ssh/authorized_keys)\" ]; then echo >> ~/.ssh/authorized_keys; fi; "
       "grep -qxF '{k}' ~/.ssh/authorized_keys || echo '{k}' >> ~/.ssh/authorized_keys")
_PS = ("$k='{k}'; $d=Join-Path $env:USERPROFILE '.ssh'; New-Item -ItemType Directory -Force $d | Out-Null; "
       "$f=Join-Path $d 'authorized_keys'; if(-not (Test-Path $f) -or -not (Select-String -Path $f -SimpleMatch -Pattern $k -Quiet)) {{ Add-Content -Path $f -Value $k -Encoding ascii }}")
_PS_ADMIN = ("$k='{k}'; $f='C:\\ProgramData\\ssh\\administrators_authorized_keys'; "
             "if(-not (Test-Path $f) -or -not (Select-String -Path $f -SimpleMatch -Pattern $k -Quiet)) {{ Add-Content -Path $f -Value $k -Encoding ascii }}; "
             "icacls $f /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null")


def _ps_cmd(script):
    """把 PowerShell 脚本做成 -EncodedCommand：不管对方默认 shell 是 cmd 还是 PowerShell，都不会被引号/变量展开搞坏
    （以前直接拼 -Command "..."，对方默认 shell 是 PowerShell 时 $k 等变量先被外层展开，脚本变成乱码并卡住等输入）。"""
    import base64
    return "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + base64.b64encode(("$ErrorActionPreference='Stop'; " + script).encode("utf-16-le")).decode("ascii")


def _install_pub(c, pub, os_name):
    if os_name != "Windows":
        code, _, err = _run(c, _SH.format(k=pub))
        if code != 0:
            raise ConnectionError("写入对方 authorized_keys 失败：%s" % (err.strip() or code))
        return
    code, out, err = _run(c, _ps_cmd(_PS.format(k=pub)), 40)
    log.info("  Windows 写 authorized_keys：code=%s out=%r err=%r", code, out.strip()[:200], err.strip()[:300])
    if code != 0:
        raise ConnectionError("写入对方 authorized_keys 失败：%s" % (err.strip() or code))


def _verify_key(p):
    q = {**p, "password": ""}
    q["identity"] = key_path()
    try:
        c, via = connect(q, timeout=8, use_password=False)
        c.close()
        return via == "key"
    except ConnectionError as e:
        log.info("  验证通用密钥登录：不行（%s）", e)
        return False


def setup_key_for(alias):
    """给一个主机配上通用密钥：写公钥、验证能用密钥登录、把 ssh config 里的 IdentityFile 指向它。返回 {ok, error, note}。"""
    log.info("配置通用密钥 [%s] 开始", alias)
    p = _params(alias)
    st = ensure_key()
    log.info("  通用密钥：%s 指纹 %s；该主机地址池 %s，当前 identity=%r", st.get("path"), st.get("fingerprint"), [(x["host"], x["port"]) for x in p.get("addrs", [])], p.get("identity"))
    try:
        c, via = connect(p, timeout=10)
    except ConnectionError as e:
        log.warning("  第1步 用现有凭据登录失败：%s", e)
        return {"ok": False, "error": "先要能登录这台主机才能配密钥：%s" % e}
    log.info("  第1步 已用 %s 登录（走 %s:%s）", via, c.tb_addr["host"], c.tb_addr["port"])
    p = {**p, "addrs": [c.tb_addr]}            # 后面的验证只走刚才连上的这个地址，不再重复等内网超时
    try:
        os_name = detect_os(c)
        log.info("  第2步 对方系统：%s", os_name)
        pub = _pub_line()
        if via == "key" and _verify_key(p):
            log.info("  通用密钥本来就能登录，跳过写入")
        else:
            _install_pub(c, pub, os_name)
            log.info("  第3步 公钥已写入 authorized_keys")
            ok = _verify_key(p)
            if not ok and os_name == "Windows":
                code, out, err = _run(c, _ps_cmd(_PS_ADMIN.format(k=pub)), 40)
                log.info("  第3b步 Windows 管理员组：写 administrators_authorized_keys code=%s out=%r err=%r", code, out.strip()[:200], err.strip()[:300])
                ok = _verify_key(p)
            if not ok:
                log.warning("  第4步 写入后用通用密钥仍然登录不上")
                return {"ok": False, "error": "公钥已写入，但用密钥登录没成功。对方 sshd 可能不允许公钥登录，或目录权限不对。"}
            log.info("  第4步 用通用密钥登录验证通过")
    except ConnectionError as e:
        log.warning("  配置过程出错：%s", e)
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log.exception("  配置过程异常")
        return {"ok": False, "error": "配置出错：%s" % e}
    finally:
        c.close()
    ident = "~/.ssh/" + KEY_NAME
    if p.get("identity") != ident:
        set_identity(alias, ident)
        log.info("  第5步 ssh config 里的 IdentityFile 改为 %s", ident)
    log.info("配置通用密钥 [%s] 完成", alias)
    return {"ok": True}


def setup_key_all(progress=None):
    """给所有已配置的主机配同一把密钥。主机没密码又连不上的会跳过。返回 [{alias, ok, error}]。"""
    st = ensure_key()
    out = []
    hosts = list_hosts()
    for i, h in enumerate(hosts):
        if progress:
            progress(i, len(hosts), h["alias"])
        r = setup_key_for(h["alias"])
        out.append({"alias": h["alias"], "ok": r["ok"], "error": r.get("error", "")})
    return {"key": st, "results": out}


# ------------------------------------------------------------------ SFTP
_POOL = {}
_ALOCKS = {}                              # alias -> RLock：同一台主机同一时刻只建一条连接（文件页/GPU 采样/终端同时要连时，后来的等着复用，别一起去敲中转的门）


def _alias_lock(alias):
    with _LOCK:
        return _ALOCKS.setdefault(alias, threading.RLock())


def _drop(alias):
    with _LOCK:
        ent = _POOL.pop(alias, None)
    if ent:
        try:
            ent[0].close()
        except Exception:
            pass


_EXEC = {}                                # 只跑命令的长连接（不开 SFTP）：有的服务器（容器里的 sshd）没装 sftp 子系统，open_sftp 会报 “EOF during negotiation”，但命令照样能跑


def exec_client(alias):
    """只用来跑命令的连接（GPU 采样等）。优先复用文件页的长连接，没有就自己连一条，不开 SFTP。"""
    with _LOCK:
        ent = _POOL.get(alias)
        if ent and ent[0].get_transport() and ent[0].get_transport().is_active():
            return ent[0]
        c = _EXEC.get(alias)
        if c and c.get_transport() and c.get_transport().is_active():
            return c
    with _alias_lock(alias):
        with _LOCK:
            ent = _POOL.get(alias)
            if ent and ent[0].get_transport() and ent[0].get_transport().is_active():
                return ent[0]
            c = _EXEC.get(alias)
            if c and c.get_transport() and c.get_transport().is_active():
                return c
        c, _ = connect(_params(alias))
        with _LOCK:
            _EXEC[alias] = c
        return c


def drop_exec(alias):
    with _LOCK:
        c = _EXEC.pop(alias, None)
    if c:
        try:
            c.close()
        except Exception:                 # noqa: BLE001
            pass


_AUTOFIX = {}                             # alias -> {t, running, ok, error}：自动修复 SFTP 的记录


def _auto_fix_sftp(alias, client=None):
    """发现服务器没有 SFTP 就自动修（不弹提示、不用点按钮）。同一台 10 分钟内只自动试一次，免得反复改配置。返回 True=刚修好。
    client：手上已经连好的那条连接，修复直接用它，不再另起一条（再连一次容易撞上同一个偶发的断连）。"""
    now = time.time()
    with _LOCK:
        st = _AUTOFIX.get(alias)
        if st and (st["running"] or now - st["t"] < 600):
            return False
        st = _AUTOFIX[alias] = {"t": now, "running": True, "ok": None, "error": ""}
    log.info("%s 没有 SFTP，自动修复", alias)
    try:
        r = fix_sftp(alias, client)
    except Exception as e:                                       # noqa: BLE001
        r = {"ok": False, "error": str(e)}
    with _LOCK:
        st.update(running=False, ok=bool(r.get("ok")), error=r.get("error", ""), conn=bool(r.get("conn")), t=time.time())
        if r.get("conn"):                                        # 是连接出的问题，不是服务器没 SFTP：别占掉 10 分钟的“只试一次”额度
            _AUTOFIX.pop(alias, None)
    if not r.get("ok"):
        log.warning("%s 自动修复 SFTP 没成功：%s", alias, r.get("error"))
    return bool(r.get("ok"))


def _alive(c):
    """连接是不是真的还能用（transport 显示活着不算数：中转掐掉后还要等一会儿才发现）：跑一条最简单的命令。"""
    try:
        t = c.get_transport()
        if t is None or not t.is_active():
            return False
        code, _, _ = _run(c, "echo 1", 8)
        return code == 0
    except Exception:                                            # noqa: BLE001
        return False


def _session(alias):
    """浏览用的长连接（断了自动重连）。返回 (client, sftp)。"""
    with _LOCK:
        ent = _POOL.get(alias)
        if ent and ent[0].get_transport() and ent[0].get_transport().is_active():
            return ent
    with _alias_lock(alias):
        with _LOCK:
            ent = _POOL.get(alias)
            if ent and ent[0].get_transport() and ent[0].get_transport().is_active():
                return ent                                       # 排队期间别的线程已经连好了
        return _open_session(alias)


_CHAN_MAX = 2                                                    # 每条连接最多缓存多少条空闲的 SFTP 通道
_CHAN_LIVE = 4                                                   # 每条连接同时最多借出多少条（sshd 默认 MaxSessions=10，终端/监控/共享也要占会话，别占满）


@contextlib.contextmanager
def _lease(alias):
    """借一条独立的 SFTP 通道来做一件事（返回 (client, sftp)），做完放回池子。
    paramiko 的 SFTPClient 不能被多个线程同时用（各线程抢读应答包，抢不到的永远等），而 VS Code 工作台一次会并发很多请求；
    所以同一条 SSH 连接上开多条通道，每个操作独占一条。"""
    c, _base = _session(alias)
    with _LOCK:
        sem = c.__dict__.setdefault("_tb_sem", threading.BoundedSemaphore(_CHAN_LIVE))
    if not sem.acquire(timeout=120):
        raise TimeoutError("文件操作排队太久，请稍后再试。")
    try:
        with _LOCK:
            free = c.__dict__.setdefault("_tb_free", [])
            s = free.pop() if free else None
        if s is None:
            s = c.open_sftp()
        try:
            yield c, s
        except BaseException:
            ch = getattr(s, "sock", None)
            tr = c.get_transport()
            if ch is None or getattr(ch, "closed", True) or tr is None or not tr.is_active():
                _close_quiet(s)                                  # 通道已经坏了，别放回池子
            else:
                _give_back(c, s)
            raise
        else:
            _give_back(c, s)
    finally:
        sem.release()


def _give_back(c, s):
    with _LOCK:
        free = c.__dict__.setdefault("_tb_free", [])
        if len(free) < _CHAN_MAX:
            free.append(s)
            return
    _close_quiet(s)


def _open_session(alias):
    """建连接并开 SFTP。开 SFTP 失败要分清三种情况：连接中途被掐断（重连再试）／偶发失败（同一条连接再试一次）／命令能跑但真的没有 SFTP 服务（自动修）。"""
    last = None
    for attempt in range(2):
        c, _ = connect(_params(alias), on_better=lambda nc, via: _upgrade(alias, nc))
        try:
            sftp = c.open_sftp()
        except (paramiko.SSHException, EOFError, OSError) as e:
            last = e
            log.info("%s 开 SFTP 失败（第 %d 次）：%s: %s", alias, attempt + 1, type(e).__name__, e)
            if not _alive(c):                                    # 连接本身已经被掐断（中转/代理/防火墙）：不是没有 SFTP，重连再来
                _close_quiet(c)
                time.sleep(1.0)
                continue
            time.sleep(0.6)
            try:
                sftp = c.open_sftp()                             # 连接好好的，可能只是这一次握手偶发失败
            except (paramiko.SSHException, EOFError, OSError):
                fixed = _auto_fix_sftp(alias, c)                 # 命令能跑、SFTP 连开两次都不行：才当作服务器没有 SFTP，自动修
                _close_quiet(c)
                if fixed:
                    return _session(alias)                       # 修好后 fix_sftp 已经连上并放进池子了
                st = _AUTOFIX.get(alias) or {}
                if st.get("conn"):
                    raise ConnectionError("连接不稳定：%s" % st.get("error"))
                raise NoSftp("这台服务器没有开启 SFTP，自动修复也没成功：%s" % (st.get("error") or last))
        with _LOCK:
            _POOL[alias] = (c, sftp)
        cb = on_session
        if cb:                                                   # 长连接第一次建好：通知上层（自动给这台主机装 VS Code Server 等），不阻塞当前操作
            threading.Thread(target=lambda: cb(alias), daemon=True).start()
        return c, sftp
    raise ConnectionError("连接在握手中途被断开了（中转、代理或防火墙掐掉了连接），请稍后再试：%s" % last)


def _close_quiet(c):
    try:
        c.close()
    except Exception:                                            # noqa: BLE001
        pass


on_session = None          # 回调 alias：某台主机的长连接新建好了（api 里设置）
on_route = None            # 回调 (alias, {addr, internal, via})：长连接自动换到了优先级更高的地址时通知界面（api 里设置）


def _upgrade(alias, nc):
    """先用公网连上了，内网随后也连通：把浏览用的长连接换成内网这条。旧的等一会儿再关，让正在进行的操作做完。"""
    for _ in range(40):                                      # 等 _session 把先连上的那条放进池子
        with _LOCK:
            ent = _POOL.get(alias)
        if ent:
            break
        time.sleep(0.05)
    else:
        raise ConnectionError("连接已经被丢弃")
    if getattr(ent[0], "tb_prio", 99) <= getattr(nc, "tb_prio", 99):
        raise ConnectionError("没有更优")
    sftp = nc.open_sftp()
    with _LOCK:
        if _POOL.get(alias) is not ent:
            sftp.close()
            raise ConnectionError("连接已经变了")
        _POOL[alias] = (nc, sftp)
    old = ent[0]
    threading.Timer(30, lambda: old.close()).start()
    log.info("已换到优先级更高的地址 %s:%s（%s）", nc.tb_addr["host"], nc.tb_addr["port"], "内网" if nc.tb_internal else "公网")
    info = {"addr": {"host": nc.tb_addr["host"], "port": nc.tb_addr["port"]}, "internal": bool(nc.tb_internal), "via": nc.tb_via}
    _put_status(alias, {**load_status().get(alias, {}), "ok": True, **info})
    cb = on_route
    if cb:
        try:
            cb(alias, info)
        except Exception:                                    # noqa: BLE001
            pass


def fs_list(alias, path=""):
    try:
        try:
            with _lease(alias) as (cli, sftp):
                cwd = sftp.normalize(path or ".")
                items = sftp.listdir_attr(cwd)
        except (OSError, EOFError, paramiko.SSHException):
            _drop(alias)
            with _lease(alias) as (cli, sftp):
                cwd = sftp.normalize(path or ".")
                items = sftp.listdir_attr(cwd)
    except NoSftp as e:
        return {"ok": False, "error": str(e), "nosftp": True}
    except ConnectionError as e:
        _put_status(alias, {"ok": False, "error": str(e)})       # 连不上就把这台主机的状态点同步成失败
        return {"ok": False, "error": str(e), "conn": True}
    except PermissionError:
        return {"ok": False, "error": "没有权限打开这个目录。"}
    except FileNotFoundError:
        return {"ok": False, "error": "目录不存在。"}
    except Exception as e:
        return {"ok": False, "error": "读取目录失败：%s" % e}
    ents = [{"name": a.filename, "dir": statmod.S_ISDIR(a.st_mode or 0), "size": a.st_size or 0, "mtime": a.st_mtime or 0} for a in items]
    ents.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    ta = getattr(cli, "tb_addr", None)
    return {"ok": True, "path": cwd, "entries": ents, "addr": {"host": ta["host"], "port": ta["port"]} if ta else None, "internal": bool(getattr(cli, "tb_internal", False)), "via": getattr(cli, "tb_via", None)}      # addr：实际连上的地址（内网超时会自动换公网）


def fs_mkdir(alias, parent, name):
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return {"ok": False, "error": "文件夹名不合法。"}
    try:
        with _lease(alias) as (_c, sftp):
            sftp.mkdir(posixpath.join(parent, name))
    except Exception as e:
        return {"ok": False, "error": "新建失败：%s" % e}
    return {"ok": True}


# ------------------------------------------------------------------ 远程文件操作（重命名 / 删除 / 复制 / 移动）
def _fs_op(alias, fn):
    """跑一个文件操作；连不上就把主机状态点同步成失败。fn(sftp, client) 返回要带回前端的字段。每次借用独立的 SFTP 通道（可并发）。"""
    try:
        for attempt in (0, 1):
            try:
                with _lease(alias) as (c, sftp):
                    extra = fn(sftp, c)
                break
            except (EOFError, paramiko.SSHException):            # 长连接断了：重连再试一次
                if attempt:
                    raise
                _drop(alias)
        return {"ok": True, **(extra or {})}
    except NoSftp as e:
        return {"ok": False, "error": str(e), "nosftp": True}
    except ConnectionError as e:
        _put_status(alias, {"ok": False, "error": str(e)})
        return {"ok": False, "error": str(e), "conn": True}
    except PermissionError:
        return {"ok": False, "error": "没有权限。"}
    except FileNotFoundError:
        return {"ok": False, "error": "文件不存在（可能已被改动，刷新看看）。"}
    except Exception as e:
        return {"ok": False, "error": "操作失败：%s" % e}


def _bad_name(n):
    return not n or "/" in n or "\\" in n or n in (".", "..")


def _rm_rf(sftp, p):
    st = sftp.lstat(p)
    if statmod.S_ISDIR(st.st_mode or 0):
        for a in sftp.listdir_attr(p):
            _rm_rf(sftp, posixpath.join(p, a.filename))
        sftp.rmdir(p)
    else:
        sftp.remove(p)


def _cp_sftp(sftp, src, dst):
    """经过本机中转的复制（对方是 Windows 等没有 cp 命令时用）。"""
    st = sftp.stat(src)
    if statmod.S_ISDIR(st.st_mode or 0):
        sftp.mkdir(dst)
        for a in sftp.listdir_attr(src):
            _cp_sftp(sftp, posixpath.join(src, a.filename), posixpath.join(dst, a.filename))
    else:
        with sftp.open(src, "rb") as fi, sftp.open(dst, "wb") as fo:
            fo.set_pipelined(True)
            while True:
                b = fi.read(262144)
                if not b:
                    break
                fo.write(b)


def fs_rename(alias, parent, old, new):
    new = (new or "").strip()
    if _bad_name(new) or _bad_name(old):
        return {"ok": False, "error": "名字不合法。"}

    def go(sftp, c):
        dst = posixpath.join(parent, new)
        if new != old and _remote_exists(sftp, dst):
            raise ValueError("已经有同名的文件或文件夹了。")
        sftp.rename(posixpath.join(parent, old), dst)
    r = _fs_op(alias, go)
    if not r["ok"] and r["error"].startswith("操作失败：已经有同名"):
        r["error"] = "已经有同名的文件或文件夹了。"
    return r


def fs_delete(alias, parent, names):
    def go(sftp, c):
        for n in names:
            if _bad_name(n):
                raise ValueError("名字不合法：%s" % n)
            _rm_rf(sftp, posixpath.join(parent, n))
        return {"count": len(names)}
    return _fs_op(alias, go)


TRASH_LIMIT = 100 * 1024 * 1024          # 100MB 以内进垃圾目录（可撤销），超过的要用户确认后永久删除
_TRASH_WALK_MAX = 20000                  # 量大小时最多看这么多个条目，再多就当“大”处理


def _tree_size(sftp, p, acc):
    """递归量 p 的总大小，累计到 acc[0]（条目数 acc[1]）；超过上限就提前返回。不跟随符号链接。"""
    st = sftp.lstat(p)
    acc[1] += 1
    if statmod.S_ISDIR(st.st_mode or 0):
        for a in sftp.listdir_attr(p):
            if acc[0] > TRASH_LIMIT or acc[1] > _TRASH_WALK_MAX:
                return
            _tree_size(sftp, posixpath.join(p, a.filename), acc)
    elif not statmod.S_ISLNK(st.st_mode or 0):
        acc[0] += st.st_size or 0


def _mkdirs(sftp, p):
    """mkdir -p（sftp 没有自带的）。"""
    if p in ("", "/"):
        return
    try:
        sftp.stat(p)
        return
    except IOError:
        pass
    _mkdirs(sftp, posixpath.dirname(p.rstrip("/")))
    try:
        sftp.mkdir(p)
    except IOError:
        sftp.stat(p)                    # 并发创建了也算成功；真失败这里会抛


def _trash_dirs(sftp):
    """对方机器上的垃圾目录（~/.local/share/Trash 的 files / info，和桌面系统的回收站同一套格式）。没有就建出来。"""
    home = sftp.normalize(".")
    base = posixpath.join(home, ".local", "share", "Trash")
    files, info = posixpath.join(base, "files"), posixpath.join(base, "info")
    _mkdirs(sftp, files)
    _mkdirs(sftp, info)
    return files, info


def _quote_path(p):
    from urllib.parse import quote
    return quote(p, safe="/")


def fs_trash(alias, parent, names):
    """删除：100MB 以内的移进对方机器的垃圾目录（可用 fs_restore 恢复），超过的什么都不做、返回 big=True 让前端确认后走 fs_delete。"""
    import shlex

    def go(sftp, c):
        for n in names:
            if _bad_name(n):
                raise ValueError("名字不合法：%s" % n)
        acc = [0, 0]
        for n in names:
            _tree_size(sftp, posixpath.join(parent, n), acc)
            if acc[0] > TRASH_LIMIT or acc[1] > _TRASH_WALK_MAX:
                log.info("删除 %s：超过 100MB（或条目太多），需要确认后永久删除", names)
                return {"big": True, "count": 0}
        files, info = _trash_dirs(sftp)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        pairs = []
        for n in names:
            src = posixpath.join(parent, n)
            dst = _unique_remote(sftp, posixpath.join(files, n))
            try:
                sftp.rename(src, dst)
            except IOError:                                 # 跨磁盘/分区 rename 不了：用对方的 mv
                code, _, err = _run(c, "mv -- %s %s" % (shlex.quote(src), shlex.quote(dst)), 600)
                if code != 0:
                    raise IOError("无法移到垃圾目录：%s" % (err or "").strip()[:120])
            try:
                with sftp.open(posixpath.join(info, posixpath.basename(dst) + ".trashinfo"), "w") as f:
                    f.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (_quote_path(src), stamp))
            except Exception as e:                          # noqa: BLE001  信息文件写不了不影响恢复
                log.info("写 trashinfo 失败：%s", e)
            pairs.append([src, dst])
        return {"count": len(pairs), "pairs": pairs, "big": False}
    return _fs_op(alias, go)


def fs_restore(alias, pairs):
    """把 fs_trash 移走的东西放回原处（原位置被占了就自动加序号）。pairs 是 fs_trash 返回的 [原路径, 垃圾目录里的路径]。"""
    def go(sftp, c):
        out = []
        for orig, trashed in pairs:
            dst = _unique_remote(sftp, orig)
            sftp.rename(trashed, dst)
            try:
                sftp.remove(posixpath.join(posixpath.dirname(posixpath.dirname(trashed)), "info", posixpath.basename(trashed) + ".trashinfo"))
            except Exception:                               # noqa: BLE001
                pass
            out.append(dst)
        return {"count": len(out)}
    return _fs_op(alias, go)


def fs_move(alias, parent, names, dest):
    """把 parent 里的 names 移到 dest 目录里（同名自动加序号，不覆盖）。"""
    def go(sftp, c):
        d = sftp.normalize(dest)
        pairs = []
        for n in names:
            src = posixpath.join(parent, n)
            if _bad_name(n) or src == d or d.startswith(src.rstrip("/") + "/"):
                raise ValueError("不能把文件夹移到它自己里面。")
            if posixpath.dirname(src) == d:
                continue
            dst = _unique_remote(sftp, posixpath.join(d, n))
            sftp.rename(src, dst)
            pairs.append([src, dst])
        return {"count": len(pairs), "pairs": pairs}            # pairs：实际的 原路径→新路径，撤销时按它们原路退回
    return _fs_op(alias, go)


def fs_copy(alias, src_dir, names, dest):
    """把 src_dir 里的 names 复制到 dest 目录里（同名自动加序号）。优先用对方的 cp（不占本机网速），不行再经本机中转。"""
    import shlex

    def go(sftp, c):
        d = sftp.normalize(dest)
        created = []
        for n in names:
            if _bad_name(n):
                raise ValueError("名字不合法：%s" % n)
            src = posixpath.join(src_dir, n)
            if d.startswith(src.rstrip("/") + "/"):
                raise ValueError("不能把文件夹复制到它自己里面。")
            dst = _unique_remote(sftp, posixpath.join(d, n))
            ok = False
            try:
                code, _, _ = _run(c, "cp -a -- %s %s" % (shlex.quote(src), shlex.quote(dst)), 600)
                ok = code == 0
            except Exception:
                ok = False
            if not ok:
                if _remote_exists(sftp, dst):
                    try:
                        _rm_rf(sftp, dst)           # 清掉 cp 失败时留下的半成品
                    except Exception:
                        pass
                _cp_sftp(sftp, src, dst)
            created.append(dst)
        return {"count": len(names), "created": created}        # created：新生成的副本路径，撤销就是删掉它们
    return _fs_op(alias, go)


def fs_move_paths(alias, pairs):
    """按完整路径移动：[[from, to], ...]。目标已存在就自动加序号，不覆盖。撤销移动/重命名用。返回实际落点 pairs。"""
    def go(sftp, c):
        out = []
        for a, b in pairs:
            dst = _unique_remote(sftp, b)
            sftp.rename(a, dst)
            out.append([a, dst])
        return {"count": len(out), "pairs": out}
    return _fs_op(alias, go)


def fs_rm_paths(alias, paths):
    """按完整路径递归删除。撤销“复制”用（删掉当时生成的副本）。"""
    def go(sftp, c):
        for p in paths:
            _rm_rf(sftp, p)
        return {"count": len(paths)}
    return _fs_op(alias, go)


# ------------------------------------------------------------------ 压缩 / 解压（在对方机器上做，不经过本机）
_PY_UNZIP = r'''
import os, shutil, sys, time, zipfile
arc, dest, skip = sys.argv[1], sys.argv[2], sys.argv[3] == "1"

def fix(info):
    n = info.filename
    if info.flag_bits & 0x800:
        return n
    try:
        raw = n.encode("cp437")
    except UnicodeEncodeError:
        return n
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return n

root = os.path.realpath(dest)
with zipfile.ZipFile(arc) as z:
    for info in z.infolist():
        name = fix(info).replace("\\", "/").lstrip("/")
        target = os.path.realpath(os.path.join(dest, name))
        if target != root and not target.startswith(root + os.sep):
            continue
        if name.endswith("/"):
            os.makedirs(target, exist_ok=True)
            continue
        if skip and os.path.lexists(target):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with z.open(info) as s, open(target, "wb") as o:
            shutil.copyfileobj(s, o)
        mode = (info.external_attr >> 16) & 0o777
        if mode:
            os.chmod(target, mode)
        try:
            t = time.mktime(info.date_time + (0, 0, -1))
            os.utime(target, (t, t))
        except Exception:
            pass
'''

_PY_ZIP = r'''
import os, sys, zipfile
out, names = sys.argv[1], sys.argv[2:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
    for n in names:
        if os.path.isdir(n) and not os.path.islink(n):
            z.write(n, n.rstrip("/") + "/")
            for d, ds, fs in os.walk(n):
                for x in ds:
                    p = os.path.join(d, x)
                    if not os.path.islink(p):
                        z.write(p, p + "/")
                for x in fs:
                    z.write(os.path.join(d, x))
        else:
            z.write(n)
'''

_ARC_EXT = [(".tar.gz", "tar"), (".tgz", "tar"), (".tar.bz2", "tar"), (".tbz2", "tar"), (".tar.xz", "tar"), (".txz", "tar"), (".tar.zst", "tar"), (".tar.lz", "tar"),
            (".tar", "tar"), (".zip", "zip"), (".jar", "zip"), (".7z", "7z"), (".rar", "rar"), (".gz", "gz"), (".bz2", "bz2"), (".xz", "xz")]


def _arc_kind(name):
    low = name.lower()
    for ext, kind in _ARC_EXT:
        if low.endswith(ext):
            return kind, name[:-len(ext)] or name
    return None, name


def _run_long(c, cmd, timeout=3600, cap=0):
    """跑一条可能很久的命令（压缩/解压大文件）：边跑边把输出读走，免得缓冲区塞满卡住。返回 (退出码, 标准输出, 错误输出)。
    输出太长时默认只留最后 30KB（给提示用）；cap>0 表示要完整输出（搜索），最多收 cap 字节，超出就停。"""
    chan = c.get_transport().open_session()
    chan.exec_command(cmd)
    out, err = bytearray(), bytearray()
    t0 = time.time()
    while True:
        got = False
        while chan.recv_ready():
            out += chan.recv(65536)
            got = True
        while chan.recv_stderr_ready():
            err += chan.recv_stderr(65536)
            got = True
        if cap:
            if len(out) > cap:
                chan.close()
                break
        elif len(out) > 60000:
            del out[:-30000]
        if len(err) > 60000:
            del err[:-30000]
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        if time.time() - t0 > timeout:
            chan.close()
            raise TimeoutError("操作超时（%d 分钟）。" % (timeout // 60))
        if not got:
            time.sleep(0.1)
    return chan.recv_exit_status(), out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _extract_script(kind, arc, dest, here):
    import shlex
    q = shlex.quote
    A, D = q(arc), q(dest)
    stem = q(posixpath.join(dest, _arc_kind(posixpath.basename(arc))[1]))
    if kind == "zip":
        return ("if command -v python3 >/dev/null 2>&1; then python3 -c %s %s %s %s; "
                "elif command -v unzip >/dev/null 2>&1; then unzip -q -n %s -d %s; "
                "elif command -v bsdtar >/dev/null 2>&1; then bsdtar -xf %s -C %s; "
                "elif command -v 7z >/dev/null 2>&1; then 7z x -y -aos -o%s %s >/dev/null; "
                "else echo '服务器上没有可用的解压工具（python3 / unzip / 7z）' >&2; exit 127; fi"
                % (q(_PY_UNZIP), A, D, "1" if here else "0", A, D, A, D, D, A))
    if kind == "tar":
        if here:
            return "tar --skip-old-files -xf %s -C %s 2>/dev/null || tar -xkf %s -C %s" % (A, D, A, D)
        return "tar -xf %s -C %s" % (A, D)
    if kind == "7z":
        return ("if command -v 7z >/dev/null 2>&1; then 7z x -y -aos -o%s %s >/dev/null; elif command -v 7za >/dev/null 2>&1; then 7za x -y -aos -o%s %s >/dev/null; "
                "elif command -v 7zr >/dev/null 2>&1; then 7zr x -y -aos -o%s %s >/dev/null; elif command -v bsdtar >/dev/null 2>&1; then bsdtar -xf %s -C %s; "
                "else echo '服务器上没有 7z（可以先 apt install p7zip-full）' >&2; exit 127; fi" % (D, A, D, A, D, A, A, D))
    if kind == "rar":
        return ("if command -v unrar >/dev/null 2>&1; then unrar x -y -o- %s %s/; elif command -v 7z >/dev/null 2>&1; then 7z x -y -aos -o%s %s >/dev/null; "
                "elif command -v bsdtar >/dev/null 2>&1; then bsdtar -xf %s -C %s; else echo '服务器上没有 unrar 或 7z' >&2; exit 127; fi" % (A, D, D, A, A, D))
    tool = {"gz": "gzip", "bz2": "bzip2", "xz": "xz"}[kind]
    return "%s -dc %s > %s" % (tool, A, stem) if not here else "[ -e %s ] && echo '同名文件已存在，没有覆盖' >&2 && exit 1; %s -dc %s > %s" % (stem, tool, A, stem)


def fs_extract(alias, parent, names, here=False):
    """解压 parent 里的 names。默认解到和压缩包同名的新文件夹里（重名自动加序号，不会覆盖任何东西）；here=True 解到当前文件夹，已有同名文件跳过不覆盖。
    zip 优先用对方的 python3 解（国内常见的 GBK 文件名压缩包也能解对），没有 python3 再用 unzip/bsdtar/7z。返回 created（新生成的文件夹，撤销就是删掉它们）。"""
    def go(sftp, c):
        created = []
        for n in names:
            if _bad_name(n):
                raise ValueError("名字不合法：%s" % n)
            kind, stem = _arc_kind(n)
            if not kind:
                raise ValueError("不支持解压这种文件：%s（支持 zip / tar / tar.gz / tar.bz2 / tar.xz / 7z / rar / gz / bz2 / xz）" % n)
            arc = posixpath.join(parent, n)
            dest = parent if here else _unique_remote(sftp, posixpath.join(parent, stem))
            if not here:
                sftp.mkdir(dest)
            code, out, err = _run_long(c, "sh -c " + _q(_extract_script(kind, arc, dest, here)))
            if code != 0:
                if not here:
                    try:
                        sftp.rmdir(dest)                      # 没解出东西就别留一个空文件夹
                    except Exception:                         # noqa: BLE001
                        pass
                raise ValueError("解压“%s”失败：%s" % (n, (err or out).strip()[-300:] or "退出码 %s" % code))
            if not here:
                created.append(dest)
        return {"count": len(names), "created": created}
    return _fs_op(alias, go)


def _q(s):
    import shlex
    return shlex.quote(s)


def fs_archive(alias, parent, names, kind="zip"):
    """把 parent 里的 names 压缩成一个包放在同一个文件夹里（重名自动加序号）。kind: zip | tgz。返回 created=[包路径]。"""
    def go(sftp, c):
        for n in names:
            if _bad_name(n):
                raise ValueError("名字不合法：%s" % n)
        if len(names) == 1:
            stem = names[0]
            base, ext = posixpath.splitext(stem)
            if base and not stem.startswith(".") and 1 < len(ext) <= 6:
                stem = base
        else:
            stem = posixpath.basename(parent.rstrip("/")) or "压缩包"
        ext = ".zip" if kind == "zip" else ".tar.gz"
        out = _unique_remote(sftp, posixpath.join(parent, stem + ext))
        rel = posixpath.basename(out)
        args = " ".join(_q(n) for n in names)
        if kind == "zip":
            # 优先 python3：它给非 ASCII 文件名打 UTF-8 标志，Windows/macOS 打开中文名才不乱码；Info-ZIP 的 zip 在 POSIX 语言环境下不打标志（要加 -UN=UTF8）
            cmd = ("cd %s && if command -v python3 >/dev/null 2>&1; then python3 -c %s %s %s; "
                   "elif command -v zip >/dev/null 2>&1; then zip -UN=UTF8 -rq %s -- %s 2>/dev/null || zip -rq %s -- %s; "
                   "else echo '服务器上没有 python3 或 zip，可以改选“压缩为 tar.gz”' >&2; exit 127; fi") % (_q(parent), _q(_PY_ZIP), _q(rel), args, _q(rel), args, _q(rel), args)
        else:
            cmd = "cd %s && tar -czf %s -- %s" % (_q(parent), _q(rel), args)
        code, o, e = _run_long(c, "sh -c " + _q(cmd))
        if code != 0:
            try:
                sftp.remove(out)                              # 清掉压到一半的半成品
            except Exception:                                 # noqa: BLE001
                pass
            raise ValueError("压缩失败：%s" % ((e or o).strip()[-300:] or "退出码 %s" % code))
        return {"count": len(names), "created": [out]}
    return _fs_op(alias, go)


# ------------------------------------------------------------------ 服务器没开 SFTP：一键修复
# 常见情况：自己编译的 sshd（装在 /usr/local/openssh），配置里 Subsystem 还指着 /usr/lib/openssh/sftp-server，但这个文件根本不存在。
# 命令行、GPU 采样都不受影响（走的是命令通道），只有文件页（SFTP）打不开，报 “EOF during negotiation”。
_FIX_SFTP = r'''
set -u
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo -n"
  $SUDO true 2>/dev/null || { echo "ERR 需要 root 权限：当前用户不是 root，也不能免密 sudo"; exit 2; }
else
  SUDO=""
fi
PID=$(pgrep -o -x sshd 2>/dev/null)
[ -n "$PID" ] || { echo "ERR 没找到正在运行的 sshd 进程"; exit 2; }
EXE=$(readlink /proc/$PID/exe 2>/dev/null)
case "$(basename "$EXE")" in sshd) ;; *) EXE=$(command -v sshd 2>/dev/null || ls /usr/sbin/sshd /usr/local/sbin/sshd /usr/local/openssh/sbin/sshd 2>/dev/null | head -1);; esac
[ -n "$EXE" ] && [ -x "$EXE" ] || { echo "ERR 找不到 sshd 程序"; exit 2; }
CFG=$(tr '\0' ' ' < /proc/$PID/cmdline 2>/dev/null | sed -n 's/.* -f \([^ ]*\).*/\1/p')
[ -n "$CFG" ] || CFG=/etc/ssh/sshd_config
[ -f "$CFG" ] || { echo "ERR 找不到 sshd 配置文件 $CFG"; exit 2; }
BIN=""
for p in "$(dirname "$(dirname "$EXE")")/libexec/sftp-server" "$(dirname "$(dirname "$EXE")")/libexec/openssh/sftp-server" /usr/lib/openssh/sftp-server /usr/lib/ssh/sftp-server /usr/libexec/openssh/sftp-server /usr/libexec/sftp-server /usr/local/libexec/sftp-server /usr/local/openssh/libexec/sftp-server; do
  if [ -x "$p" ]; then BIN="$p"; break; fi
done
TARGET=${BIN:-internal-sftp}
CUR=$($SUDO "$EXE" -T -f "$CFG" 2>/dev/null | grep -i '^subsystem' | head -1)
CURCMD=$(echo "$CUR" | awk '{print $3}')
if [ -n "$CURCMD" ] && { [ "$CURCMD" = "internal-sftp" ] || [ -x "$CURCMD" ]; }; then
  echo "ERR 服务器的 SFTP 配置没问题（$CUR），问题不在这里，可能是登录 shell 的启动脚本（.bashrc 等）往外输出了内容"; exit 3
fi
TS=$(date +%Y%m%d%H%M%S)
$SUDO cp -p "$CFG" "$CFG.bak-toolbox-$TS" || { echo "ERR 备份配置失败"; exit 2; }
TMP=$(mktemp)
sed -E '/^[[:space:]]*Subsystem[[:space:]]+sftp([[:space:]]|$)/d' "$CFG" | awk -v line="Subsystem\tsftp\t$TARGET" '/^[ \t]*Match[ \t]/ && !done {print line; done=1} {print} END{if(!done) print line}' > "$TMP"
$SUDO sh -c 'cat "$1" > "$2"' _ "$TMP" "$CFG"
rm -f "$TMP"
restore() { $SUDO sh -c 'cat "$1" > "$2"' _ "$CFG.bak-toolbox-$TS" "$CFG"; }
if ! $SUDO "$EXE" -t -f "$CFG" 2>/tmp/.mj_sshd_t; then restore; echo "ERR 改完的配置没通过 sshd -t 检查，已还原：$(head -c 200 /tmp/.mj_sshd_t)"; rm -f /tmp/.mj_sshd_t; exit 4; fi
rm -f /tmp/.mj_sshd_t
if ! $SUDO "$EXE" -T -f "$CFG" 2>/dev/null | grep -i '^subsystem' | grep -q -F "$TARGET"; then restore; echo "ERR 配置里别处（Include 的文件）还有 Subsystem 设置盖住了这一行，已还原，需要手动处理"; exit 4; fi
$SUDO kill -HUP "$PID" 2>/dev/null || { restore; echo "ERR 通知 sshd 重新读取配置失败，已还原"; exit 4; }
sleep 1
kill -0 "$PID" 2>/dev/null || pgrep -x sshd >/dev/null 2>&1 || { echo "ERR sshd 重新读取配置后没起来！请马上去服务器上检查（备份在 $CFG.bak-toolbox-$TS）"; exit 5; }
echo "OK $TARGET $CFG.bak-toolbox-$TS"
'''


class NoSftp(Exception):
    """能连上、能跑命令，但服务器没有可用的 SFTP 服务。"""


def fix_sftp(alias, client=None):
    """诊断并修复服务器的 SFTP：找得到 sftp-server 就指过去，找不到就用 sshd 自带的 internal-sftp（不用装任何包）；
    改之前备份配置，改完用 sshd -t 检查、没通过就还原，然后给 sshd 发 HUP 重新读取配置（已连上的会话不受影响）。需要 root。
    返回里 conn=True 表示是连不上/连接断了，不是服务器的问题。"""
    import shlex
    try:
        try:
            c = client or exec_client(alias)
        except ConnectionError as e:
            return {"ok": False, "conn": True, "error": str(e)}
        if not _alive(c):
            return {"ok": False, "conn": True, "error": "连接中途断开了"}
        sysname = detect_os(c)
        if sysname == "Windows":
            return {"ok": False, "error": "Windows 主机的 SFTP 要在系统设置里装“OpenSSH 服务器”，这里没法自动修。"}
        code, out, err = _run_long(c, "sh -c " + shlex.quote(_FIX_SFTP), 120)
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": "修复失败：%s" % e}
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    last = lines[-1] if lines else ""
    if not last.startswith("OK "):
        return {"ok": False, "error": (last[4:] if last.startswith("ERR ") else (err or out).strip()[-300:] or "没有成功（退出码 %s）" % code)}
    _, target, backup = last.split(None, 2)
    _drop(alias)
    try:
        _session(alias)                                          # 再试一次真的开 SFTP
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": "已经改好配置（%s），但再连一次 SFTP 还是没成功：%s" % (target, e), "backup": backup}
    log.info("%s 的 SFTP 已修复：%s（备份 %s）", alias, target, backup)
    how = "指到了已有的 sftp-server（%s）" % target if target != "internal-sftp" else "改用 sshd 自带的 internal-sftp（不需要安装任何东西）"
    return {"ok": True, "text": "已修复：SFTP 服务%s。原配置备份在服务器的 %s。" % (how, backup), "target": target, "backup": backup}


# ------------------------------------------------------------------ 在编辑器里打开/保存远程文本文件
EDIT_LIMIT = 5 * 1024 * 1024            # 超过这个大小不在编辑器里打开（大日志请下载或用命令行 less/tail）


def _decode_text(data):
    """返回 (文本, 编码名)。UTF-8（含 BOM）优先；不是 UTF-8 就按 GB18030（国内常见的 GBK 文件）；再不行用 latin-1 保证能显示。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gb18030"), "gb18030"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


READ_CHUNK = 64 * 1024


def fs_read_text(alias, path, progress=None):
    """读远程文本文件。progress(已读字节, 总字节)：分块读取，每块回调一次，给编辑器画进度条。"""
    def go(sftp, c):
        st = sftp.stat(path)
        size = st.st_size or 0
        if statmod.S_ISDIR(st.st_mode or 0):
            raise ValueError("这是文件夹。")
        if size > EDIT_LIMIT:
            raise ValueError("文件太大（%.1f MB），超过 %d MB 不在编辑器里打开。" % (size / 1048576, EDIT_LIMIT // 1048576))
        parts, got = [], 0
        if progress:
            progress(0, size)
        with sftp.open(path, "rb") as f:
            f.prefetch(size)                                 # 让 SFTP 请求在后台并发拉取，分块读也不慢
            while True:
                chunk = f.read(READ_CHUNK)
                if not chunk:
                    break
                parts.append(chunk)
                got += len(chunk)
                if progress:
                    progress(got, size)
        data = b"".join(parts)
        if b"\x00" in data[:8192]:
            raise ValueError("看起来是二进制文件，不能当文本打开。")
        text, enc = _decode_text(data)
        return {"text": text, "encoding": enc, "size": len(data), "mtime": st.st_mtime or 0}
    r = _fs_op(alias, go)
    if not r["ok"] and r["error"].startswith("操作失败："):
        r["error"] = r["error"][len("操作失败："):]
    return r


def fs_write_text(alias, path, text, encoding="utf-8"):
    """直接覆盖写（保留文件原来的权限和所有者）。编码沿用打开时识别的那个。"""
    def go(sftp, c):
        enc = encoding if encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1") else "utf-8"
        data = text.encode(enc, "replace")
        with sftp.open(path, "wb") as f:
            f.set_pipelined(True)
            f.write(data)
        st = sftp.stat(path)
        return {"size": len(data), "mtime": st.st_mtime or 0}
    r = _fs_op(alias, go)
    if not r["ok"] and r["error"].startswith("操作失败："):
        r["error"] = "保存失败：" + r["error"][len("操作失败："):]
    return r


BYTES_LIMIT = 200 * 1024 * 1024         # 工作台（VS Code）按字节读文件的上限；更大的请下载或用命令行


def fs_stat(alias, path):
    """给 VS Code 工作台的文件系统用：是文件还是文件夹、大小、修改时间。"""
    def go(sftp, c):
        st = sftp.stat(path)
        return {"dir": statmod.S_ISDIR(st.st_mode or 0), "size": st.st_size or 0, "mtime": st.st_mtime or 0, "mode": st.st_mode or 0}
    return _fs_op(alias, go)


def fs_read_bytes(alias, path):
    """按原始字节读整个文件（base64），不做任何解码，编码交给编辑器去猜。并发预取，千兆内网能跑满。"""
    def go(sftp, c):
        st = sftp.stat(path)
        size = st.st_size or 0
        if statmod.S_ISDIR(st.st_mode or 0):
            raise ValueError("这是文件夹。")
        if size > BYTES_LIMIT:
            raise ValueError("文件太大（%.1f MB），超过 %d MB 不在编辑器里打开。" % (size / 1048576, BYTES_LIMIT // 1048576))
        parts = []
        with sftp.open(path, "rb") as f:
            if size:
                f.prefetch(size, max_concurrent_requests=400)
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                parts.append(chunk)
        data = b"".join(parts)
        return {"b64": base64.b64encode(data).decode("ascii"), "size": len(data), "mtime": st.st_mtime or 0}
    return _fs_op(alias, go)


def fs_write_bytes(alias, path, b64, create=True, overwrite=True):
    """按原始字节写文件（覆盖时保留原来的权限和所有者）。"""
    def go(sftp, c):
        data = base64.b64decode(b64 or "")
        exists = _remote_exists(sftp, path)
        if exists and not overwrite:
            raise FileExistsError("已经有同名文件了。")
        if not exists and not create:
            raise FileNotFoundError(path)
        with sftp.open(path, "wb") as f:
            f.set_pipelined(True)
            f.write(data)
        st = sftp.stat(path)
        return {"size": len(data), "mtime": st.st_mtime or 0}
    r = _fs_op(alias, go)
    if not r["ok"] and r["error"].startswith("操作失败："):
        r["error"] = "保存失败：" + r["error"][len("操作失败："):]
    return r


def fs_rename_path(alias, src, dst, overwrite=False):
    """按完整路径重命名/移动（同一台主机内）。overwrite 为假且目标已存在就报错。"""
    def go(sftp, c):
        if _remote_exists(sftp, dst):
            if not overwrite:
                raise FileExistsError("目标已存在。")
            try:
                sftp.posix_rename(src, dst)
                return {}
            except (IOError, OSError):
                _rm_rf(sftp, dst)
        sftp.rename(src, dst)
    r = _fs_op(alias, go)
    if not r["ok"] and r["error"].startswith("操作失败："):
        r["error"] = r["error"][len("操作失败："):]
    return r


def fs_remove_path(alias, path):
    """删一个文件/文件夹：100MB 以内悄悄移进服务器的回收目录，超过的才永久删除（VS Code 删除前已经问过用户了）。"""
    parent, name = posixpath.split(path.rstrip("/"))
    parent = parent or "/"
    r = fs_trash(alias, parent, [name])
    if r.get("conn") or r.get("nosftp"):
        return r
    if not r.get("ok") or r.get("big"):          # 太大，或者这台主机没法进回收目录（Windows 没有 mv）：直接删
        r = fs_delete(alias, parent, [name])
    return r


_SKIP_DIRS = (".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".idea", ".mypy_cache", ".pytest_cache", ".tox", "site-packages")


def _search_prep(alias, root):
    """搜索用：返回 (连接, 去掉前导 / 的根目录)；Windows 主机没有 find/grep，直接报错。"""
    c = exec_client(alias)
    if detect_os(c) == "Windows":
        raise ValueError("这台是 Windows 主机，暂不支持在编辑器里搜索（Linux/macOS 主机可以）。")
    return c


def fs_search_files(alias, root, limit=30000):
    """列出 root 下的文件（相对路径），给 Ctrl+P 找文件用；跳过 .git、node_modules 等。"""
    import shlex
    try:
        c = _search_prep(alias, root)
        prune = " -o ".join("-name %s" % shlex.quote(d) for d in _SKIP_DIRS)
        cmd = "cd %s && find . \( %s \) -prune -o -type f -print 2>/dev/null | head -n %d" % (shlex.quote(root), prune, int(limit) + 1)
        code, out, err = _run_long(c, cmd, 120, cap=24 * 1024 * 1024)
        files = [l[2:] if l.startswith("./") else l for l in out.split("\n") if l.strip()]
        return {"ok": True, "files": files[:limit], "limitHit": len(files) > limit}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": str(e) if isinstance(e, ValueError) else "搜索失败：%s" % e}


def fs_search_text(alias, root, pattern, regex=False, case=False, word=False, includes=None, excludes=None, limit=3000):
    """在 root 下按内容搜索（grep -rIn）。返回 [{path(相对), line(从 1 起), text}]；每个文件最多 200 处，总共 limit 处。"""
    import shlex
    q = shlex.quote
    try:
        c = _search_prep(alias, root)
        # 先用 find 挑出要搜的文件（跳过 .git/node_modules 等目录和超过 2MB 的文件，按 include/exclude 通配符过滤），再 4 路并行 grep
        prune = " -o ".join("-name %s" % q(x) for x in _SKIP_DIRS)
        flt = ""
        if includes:
            flt += " \( " + " -o ".join("-name %s" % q(g) for g in includes) + " \)"
        for g in (excludes or []):
            flt += " ! -name %s" % q(g)
        gp = ["grep", "-InH", "--color=never", "-m", "200", "--binary-files=without-match", "-E" if regex else "-F"]
        rg = ["\"$RG\"", "--hidden", "-n", "--no-heading", "--with-filename", "--color", "never", "--max-filesize", "2M", "--max-count", "200", "--no-messages"]
        if regex:
            pass
        else:
            rg.append("-F")
        rg.append("-i" if not case else "-s")
        if not case:
            gp.append("-i")
        if word:
            gp.append("-w"); rg.append("-w")
        for dname in _SKIP_DIRS:
            rg += ["-g", q("!" + dname)]
        for g in (includes or []):
            rg += ["-g", q(g)]
        for g in (excludes or []):
            rg += ["-g", q("!" + g)]
        gp += ["-e", q(pattern)]
        rg += ["-e", q(pattern), "."]
        grep_cmd = "find . \( %s \) -prune -o -type f -size -2M%s -print0 2>/dev/null | LC_ALL=C xargs -0 -r -P 4 %s" % (prune, flt, " ".join(gp))
        # 优先用 ripgrep：PATH 里的 rg，或者装过 VS Code Remote 的服务器上自带的那份；都没有就用 find + 并行 grep
        pick = 'RG=$(command -v rg 2>/dev/null || ls -d "$HOME"/.vscode-server/bin/*/node_modules/@vscode/ripgrep*/bin/rg "$HOME"/.vscode-server/bin/*/node_modules/@vscode/ripgrep*/bin/linux-*/rg 2>/dev/null | head -n 1)'
        cmd = "cd %s && %s; if [ -n \"$RG\" ]; then %s; else %s; fi 2>/dev/null | head -n %d" % (q(root), pick, " ".join(rg), grep_cmd, int(limit) + 1)
        code, out, err = _run_long(c, cmd, 120, cap=24 * 1024 * 1024)
        res = []
        for ln in out.split("\n"):
            if not ln:
                continue
            a = ln.split(":", 2)
            if len(a) < 3 or not a[1].isdigit():
                continue
            res.append({"path": a[0][2:] if a[0].startswith("./") else a[0], "line": int(a[1]), "text": a[2][:2000]})
        return {"ok": True, "matches": res[:limit], "limitHit": len(res) > limit}
    except Exception as e:                                       # noqa: BLE001
        return {"ok": False, "error": str(e) if isinstance(e, ValueError) else "搜索失败：%s" % e}


def fs_rmdir(alias, path):
    """只删空文件夹。撤销“新建文件夹”用：里面已经放了东西就不删。"""
    def go(sftp, c):
        sftp.rmdir(path)
    r = _fs_op(alias, go)
    if not r["ok"] and not r.get("conn"):
        r["error"] = "这个文件夹里已经有东西了，没有删除。"
    return r


class Cancelled(Exception):
    pass


def _remote_exists(sftp, p):
    try:
        sftp.stat(p)
        return True
    except IOError:
        return False


def _unique_remote(sftp, p):
    if not _remote_exists(sftp, p):
        return p
    base, ext = posixpath.splitext(p)
    k = 2
    while _remote_exists(sftp, "%s (%d)%s" % (base, k, ext)):
        k += 1
    return "%s (%d)%s" % (base, k, ext)


def _unique_local(p):
    if not os.path.exists(p):
        return p
    base, ext = os.path.splitext(p)
    k = 2
    while os.path.exists("%s (%d)%s" % (base, k, ext)):
        k += 1
    return "%s (%d)%s" % (base, k, ext)


class _Meter:
    def __init__(self, total, emit, cancelled):
        self.total, self.done, self.emit, self.cancelled = total, 0, emit, cancelled
        self.t0 = self.last = time.time()
        self.file = ""

    def step(self, n):
        self.done += n
        if self.cancelled():
            raise Cancelled()
        now = time.time()
        if now - self.last >= 0.25:
            self.last = now
            self.emit({"sent": self.done, "total": self.total, "speed": self.done / max(now - self.t0, 0.001), "file": self.file})


def upload(alias, locals_, remote_dir, emit, cancelled):
    """把本地文件/文件夹传到对方的 remote_dir。已有同名就自动改名，不覆盖。返回 {ok, count, error}。"""
    try:
        c, _ = connect(_params(alias))
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    count = 0
    try:
        sftp = c.open_sftp()
        plan = []          # (本地路径, 远端路径)；目录项远端路径末尾带 /
        for p in locals_:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                top = _unique_remote(sftp, posixpath.join(remote_dir, os.path.basename(p)))
                plan.append((None, top))
                for root, dirs, files in os.walk(p):
                    rel = os.path.relpath(root, p).replace(os.sep, "/")
                    rdir = top if rel == "." else posixpath.join(top, rel)
                    for d in dirs:
                        plan.append((None, posixpath.join(rdir, d)))
                    for fn in files:
                        plan.append((os.path.join(root, fn), posixpath.join(rdir, fn)))
            elif os.path.isfile(p):
                plan.append((p, _unique_remote(sftp, posixpath.join(remote_dir, os.path.basename(p)))))
        total = sum(os.path.getsize(a) for a, _ in plan if a)
        m = _Meter(total, emit, cancelled)
        for src, dst in plan:
            if src is None:
                try:
                    sftp.mkdir(dst)
                except IOError:
                    pass
                continue
            m.file = os.path.basename(src)
            last = [0]

            def cb(done, _t, last=last):
                m.step(done - last[0]); last[0] = done
            sftp.put(src, dst, callback=cb)
            count += 1
        emit({"sent": total, "total": total, "speed": 0, "file": ""})
        return {"ok": True, "count": count}
    except Cancelled:
        return {"ok": False, "error": "已取消。", "cancelled": True}
    except Exception as e:
        return {"ok": False, "error": "上传失败：%s" % e}
    finally:
        c.close()


class ClipSource:
    """“复制服务器上的文件”的数据来源（给 vclip 用）：复制时什么都不读；粘贴时系统才来要文件清单和内容，这时才连服务器读。
    用一条独立的连接（不占文件页那条长连接），断了会在下次读的时候自动重连；剪贴板被顶掉时 close()。"""

    def __init__(self, alias, items):
        self.alias, self.items = alias, items
        self._c = self._sftp = None
        self._ents = []
        self._listed = False
        self._list_lock = threading.RLock()

    def _conn(self):
        t = self._c.get_transport() if self._c else None
        if self._sftp is None or t is None or not t.is_active():
            self.close()
            self._c, _ = connect(_params(self.alias))
            self._sftp = self._c.open_sftp()
        return self._sftp

    def prefetch(self):
        """后台先把文件清单列好（拖出去时用：用户一松手系统就要清单，现列大目录会让界面等很久）。"""
        threading.Thread(target=lambda: self._safe_list(), daemon=True).start()

    def _safe_list(self):
        try:
            self.list_entries()
        except Exception:                                            # noqa: BLE001
            pass

    def list_entries(self):
        with self._list_lock:
            if self._listed:
                return self._ents
            self._ents = self._do_list()
            self._listed = True
            return self._ents

    def _find_dir(self, it):
        """一条 find 命令列完整棵目录（Linux/macOS）：比逐层 SFTP listdir 快几十倍；出错返回 None 让调用方退回逐层列。"""
        import shlex
        cmd = "find %s -printf '%%y\\t%%Y\\t%%s\\t%%T@\\t%%P\\0' 2>/dev/null" % shlex.quote(it["path"])
        try:
            _i, so, _e = self._c.exec_command(cmd, timeout=600)
            raw = so.read()
            if so.channel.recv_exit_status() not in (0, 1) or not raw:
                return None
        except Exception:                                            # noqa: BLE001
            return None
        out = []
        for rec in raw.split(b"\x00"):
            if not rec:
                continue
            try:
                y, yy, size, mt, rel = rec.decode("utf-8", "replace").split("\t", 4)
            except ValueError:
                continue
            if not rel:                                              # 起点本身
                out.append({"rel": it["name"], "isdir": True, "size": 0, "mtime": float(mt or 0), "path": it["path"]})
                continue
            full = posixpath.join(it["path"], rel)
            if y == "d" or (y == "l" and yy == "d"):
                if y == "l":
                    continue                                         # 指向文件夹的符号链接不展开（避免绕圈）
                out.append({"rel": it["name"] + "/" + rel, "isdir": True, "size": 0, "mtime": float(mt or 0), "path": full})
            else:
                sz = int(size or 0)
                if y == "l":                                         # 符号链接：读的是它指向的文件，大小要取目标的
                    try:
                        sz = self._sftp.stat(full).st_size or 0
                    except Exception:                                # noqa: BLE001
                        continue
                out.append({"rel": it["name"] + "/" + rel, "isdir": False, "size": sz, "mtime": float(mt or 0), "path": full})
        return out

    def _do_list(self):
        sftp = self._conn()
        out = []

        def walk(rpath, rel):
            for a in sorted(sftp.listdir_attr(rpath), key=lambda x: x.filename):
                p, r = posixpath.join(rpath, a.filename), rel + "/" + a.filename
                if statmod.S_ISDIR(a.st_mode or 0):
                    out.append({"rel": r, "isdir": True, "size": 0, "mtime": a.st_mtime or 0, "path": p})
                    walk(p, r)
                else:
                    out.append({"rel": r, "isdir": False, "size": a.st_size or 0, "mtime": a.st_mtime or 0, "path": p})
        for it in self.items:
            if it["dir"]:
                got = self._find_dir(it)
                if got is not None:
                    out.extend(got)
                    continue
                out.append({"rel": it["name"], "isdir": True, "size": 0, "mtime": 0, "path": it["path"]})
                walk(it["path"], it["name"])
            else:
                st = sftp.stat(it["path"])
                out.append({"rel": it["name"], "isdir": False, "size": st.st_size or 0, "mtime": st.st_mtime or 0, "path": it["path"]})
        return out

    def open(self, i):
        e = self._ents[i]
        f = self._conn().open(e["path"], "rb")
        try:
            # 顺序读：并发预取。在途请求数要给够：paramiko 满了就 sleep(0.01) 轮询，48 个时实测只有 ~12 MB/s，
            # 200 以上 ~95 MB/s（1Gbps 内网跑满）；每个请求 32KB，400 个 ≈ 12.8MB，内存有界
            f.prefetch(e["size"], max_concurrent_requests=400)
        except Exception:                                            # noqa: BLE001
            pass
        return f

    def close(self):
        c, self._c, self._sftp = self._c, None, None
        if c is not None:
            try:
                c.close()
            except Exception:                                        # noqa: BLE001
                pass


def download(alias, items, local_dir, emit, cancelled):
    """items: [{path, name, dir}]。保存到 local_dir，同名自动改名。"""
    try:
        c, _ = connect(_params(alias))
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    count = 0
    try:
        sftp = c.open_sftp()
        plan = []
        stack = []
        for it in items:
            if it["dir"]:
                top = _unique_local(os.path.join(local_dir, it["name"]))
                stack.append((it["path"], top))
            else:
                plan.append((it["path"], _unique_local(os.path.join(local_dir, it["name"])), sftp.stat(it["path"]).st_size or 0))
        while stack:
            rdir, ldir = stack.pop()
            os.makedirs(ldir, exist_ok=True)
            for a in sftp.listdir_attr(rdir):
                rp = posixpath.join(rdir, a.filename)
                lp = os.path.join(ldir, a.filename)
                if statmod.S_ISDIR(a.st_mode or 0):
                    stack.append((rp, lp))
                else:
                    plan.append((rp, lp, a.st_size or 0))
        total = sum(x[2] for x in plan)
        m = _Meter(total, emit, cancelled)
        for rp, lp, _sz in plan:
            m.file = posixpath.basename(rp)
            last = [0]

            def cb(done, _t, last=last):
                m.step(done - last[0]); last[0] = done
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            tmp = lp + ".part"
            try:
                sftp.get(rp, tmp, callback=cb)
                os.replace(tmp, lp)
            except BaseException:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            count += 1
        emit({"sent": total, "total": total, "speed": 0, "file": ""})
        return {"ok": True, "count": count}
    except Cancelled:
        return {"ok": False, "error": "已取消。", "cancelled": True}
    except Exception as e:
        return {"ok": False, "error": "下载失败：%s" % e}
    finally:
        c.close()


# ------------------------------------------------------------------ 内嵌命令行（交互式 shell）
_TERMS = {}


class _TermCodec:
    """交互 shell 的编解码。Windows 上 exec 通道里 chcp 报的代码页（常是 936/GBK）和交互 shell 实际输出的编码可能不一样
    （新版 Windows 的 ConPTY 常直接输出 UTF-8，按 GBK 解就成了“鍏”这种乱码）。所以第一次出现非 ASCII 字节时判断一次：
    是合法 UTF-8 就按 UTF-8，否则按代码页，之后固定。Linux 不猜，按 locale 声明的编码。"""

    def __init__(self, enc, auto):
        import codecs
        self._codecs = codecs
        self.enc, self.auto = enc, auto
        self.mode = None if auto else enc
        self.dec = None if auto else codecs.getincrementaldecoder(enc)("replace")

    def decode(self, data):
        if self.mode is None:
            if all(b < 0x80 for b in data):
                return data.decode("ascii")
            probe = self._codecs.getincrementaldecoder("utf-8")("strict")
            try:
                txt = probe.decode(data, False)                    # 允许末尾被切在多字节字符中间
                self.mode, self.dec = "utf-8", self._codecs.getincrementaldecoder("utf-8")("replace")
                return self.dec.decode(data, False) if txt is not None else ""
            except UnicodeDecodeError:
                self.mode, self.dec = self.enc, self._codecs.getincrementaldecoder(self.enc)("replace")
        return self.dec.decode(data)

    def encode(self, text):
        return text.encode(self.mode or self.enc, "replace")


def _remote_encoding(c):
    """交互 shell 的字符编码，返回 (编码名, 是否需要强制 UTF-8)。
    Windows 的 OpenSSH 按控制台代码页输出（中文系统是 GBK/cp936）；Linux 看登录 shell 的 locale：
    UTF-8 → 不动；GBK/GB2312/GB18030 → 按 gb18030 解码；POSIX/ASCII（没设语言，中文会显示成问号/转义）→ 开 shell 时要求用 UTF-8。"""
    import codecs
    try:
        if detect_os(c) != "Windows":
            _, out, _ = _run(c, '"${SHELL:-sh}" -lc "locale charmap" 2>/dev/null', 8)
            cm = out.strip().upper()
            if not cm or cm.startswith("UTF"):
                return "utf-8", False
            if cm.startswith("ANSI_X3.4") or cm in ("ASCII", "POSIX", "C"):
                return "utf-8", True
            if cm in ("GBK", "GB2312", "GB18030", "CP936"):
                return "gb18030", False
            try:
                codecs.lookup(cm)
                return cm.lower(), False
            except LookupError:
                return "utf-8", False
        _, out, _ = _run(c, "chcp", 8)
        m = re.search(r"(\d{3,5})", out)
        if m:
            name = "cp" + m.group(1)
            codecs.lookup(name)
            return ("utf-8" if m.group(1) == "65001" else name), False
    except Exception:
        pass
    return "utf-8", False


def term_open(alias, cols, rows, on_data, on_close):
    """在应用里开一个到主机的交互 shell。on_data(id, 文本) / on_close(id, 原因) 在后台线程里回调。返回 {ok, id, error}。"""
    import codecs
    import uuid
    try:
        c, via = connect(_params(alias))
        enc, force_utf8 = _remote_encoding(c)
        chan = c.get_transport().open_session()
        env_ok = True
        if force_utf8:
            try:
                chan.set_environment_variable("LANG", "C.UTF-8")          # 服务器没开放 AcceptEnv 的话会被拒，下面再用命令补
            except Exception:
                env_ok = False
        chan.get_pty(term="xterm-256color", width=max(int(cols), 20), height=max(int(rows), 5))
        chan.invoke_shell()
        if force_utf8 and not env_ok:
            chan.send(b" export LANG=C.UTF-8 2>/dev/null; clear\r")
    except ConnectionError as e:
        _put_status(alias, {"ok": False, "error": str(e)})
        return {"ok": False, "error": str(e), "conn": True}
    except Exception as e:
        return {"ok": False, "error": "打开命令行失败：%s" % e}
    tid = uuid.uuid4().hex[:8]
    codec = _TermCodec(enc, enc.startswith("cp") and enc != "cp65001")
    with _LOCK:
        _TERMS[tid] = (c, chan, codec)

    def pump():
        reason = ""
        try:
            while True:
                data = chan.recv(32768)
                if not data:
                    break
                txt = codec.decode(data)
                if txt:
                    on_data(tid, txt)
        except Exception as e:
            reason = str(e)
        finally:
            with _LOCK:
                _TERMS.pop(tid, None)
            try:
                c.close()
            except Exception:
                pass
            on_close(tid, reason)

    threading.Thread(target=pump, daemon=True).start()
    return {"ok": True, "id": tid, "via": via}


def term_input(tid, data):
    ent = _TERMS.get(tid)
    if not ent:
        return False
    try:
        ent[1].send(ent[2].encode(data))
        return True
    except Exception:
        return False


def term_resize(tid, cols, rows):
    ent = _TERMS.get(tid)
    if ent:
        try:
            ent[1].resize_pty(width=max(int(cols), 20), height=max(int(rows), 5))
        except Exception:
            pass
    return True


def term_close(tid):
    ent = _TERMS.get(tid)
    if ent:
        try:
            ent[1].close()
            ent[0].close()
        except Exception:
            pass
    return True
