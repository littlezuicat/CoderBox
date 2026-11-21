# -*- coding: utf-8 -*-
"""主机与两端直连传输：和用户的 ~/.ssh/config 双向同步，密码加密保存，一把通用密钥配给所有主机，SFTP 直连收发文件。

- 主机列表 = ~/.ssh/config 里的 Host 条目（单个、不带通配符的）。本程序新增的条目前面有一行 “# 克劳德工具箱” 标记；
  改动只触及对应条目的 HostName/User/Port/IdentityFile 几行，其它内容原样保留，首次写入前备份成 config.bak-toolbox。
- 密码不写进 ssh config，单独用系统用户加密（Windows DPAPI）存放；私钥是用户自己 ~/.ssh 里的文件。
- 通用密钥：~/.ssh/claude_toolbox_ed25519 和 .pub 两个文件，所有主机共用。
- 主机指纹单独记在应用自己的 known_hosts，首次连接信任并记录，之后指纹变了就拒绝。"""
import getpass
import json
import os
import posixpath
import re
import socket
import stat as statmod
import subprocess
import sys
import threading
import time

import paramiko

from majing.core import account

MARK = "# 克劳德工具箱"
KEY_NAME = "claude_toolbox_ed25519"
_ALIAS = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_LOCK = threading.RLock()


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
        hosts.append({
            "alias": alias, "host": host, "user": f.get("user", ""), "port": port,
            "addrs": [{**a, "internal": is_internal(a["host"])} for a in addrs],
            "identity": f.get("identityfile", ""), "has_password": alias in pw,
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


def _explain(e, host, port):
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


def connect(p, timeout=10, use_password=True, use_key=True):
    """p: {host,port,user,identity,password,addrs?}。按地址池从上到下试：连不上（超时/拒绝/解析不了）才换下一个；认证失败不换。
    返回 (client, via)；via 是 'key' 或 'password'。client.tb_addr / tb_ip / tb_internal 记录实际用的是哪个地址、对端 IP、是不是内网。"""
    addrs = _norm_addrs(p["addrs"]) if p.get("addrs") else _norm_addrs([{"host": p.get("host"), "port": p.get("port")}])
    if not addrs:
        raise ConnectionError("没有可用的地址。")
    last = None
    for i, a in enumerate(addrs):
        t = timeout if i == len(addrs) - 1 else min(timeout, 4)          # 前面的地址（多半是内网）连不上要快点放弃
        try:
            c, via = _connect_one({**p, "host": a["host"], "port": a["port"]}, t, use_password, use_key)
        except AuthError:
            raise
        except ConnectionError as e:
            last = e
            continue
        c.tb_addr = a
        try:
            c.tb_ip = c.get_transport().getpeername()[0]
            c.tb_internal = is_internal(c.tb_ip) is True
        except Exception:
            c.tb_ip, c.tb_internal = a["host"], bool(is_internal(a["host"]))
        return c, via
    if len(addrs) > 1:
        raise ConnectionError("所有地址都连不上（共 %d 个）。最后一个：%s" % (len(addrs), last))
    raise last


def _connect_one(p, timeout=10, use_password=True, use_key=True):
    host, port = p["host"], int(p.get("port") or 22)
    user = p.get("user") or getpass.getuser()
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
            c.get_transport().set_keepalive(20)
            return c, via
        except Exception as e:
            c.close()
            last = e
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


def _install_pub(c, pub, os_name):
    if os_name != "Windows":
        code, _, err = _run(c, _SH.format(k=pub))
        if code != 0:
            raise ConnectionError("写入对方 authorized_keys 失败：%s" % (err.strip() or code))
        return
    code, _, err = _run(c, 'powershell -NoProfile -Command "%s"' % _PS.format(k=pub).replace('"', '\\"'))
    if code != 0:
        raise ConnectionError("写入对方 authorized_keys 失败：%s" % (err.strip() or code))


def _verify_key(p):
    q = {**p, "password": ""}
    q["identity"] = key_path()
    try:
        c, via = connect(q, timeout=8, use_password=False)
        c.close()
        return via == "key"
    except ConnectionError:
        return False


def setup_key_for(alias):
    """给一个主机配上通用密钥：写公钥、验证能用密钥登录、把 ssh config 里的 IdentityFile 指向它。返回 {ok, error, note}。"""
    p = _params(alias)
    ensure_key()
    try:
        c, via = connect(p, timeout=10)
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    try:
        os_name = detect_os(c)
        pub = _pub_line()
        if via == "key" and _verify_key(p):
            pass
        else:
            _install_pub(c, pub, os_name)
            if not _verify_key(p) and os_name == "Windows":
                code, _, err = _run(c, 'powershell -NoProfile -Command "%s"' % _PS_ADMIN.format(k=pub).replace('"', '\\"'))
            if not _verify_key(p):
                return {"ok": False, "error": "公钥已写入，但用密钥登录没成功。对方 sshd 可能不允许公钥登录，或目录权限不对。"}
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    finally:
        c.close()
    ident = "~/.ssh/" + KEY_NAME
    if p.get("identity") != ident:
        set_identity(alias, ident)
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


def _drop(alias):
    with _LOCK:
        ent = _POOL.pop(alias, None)
    if ent:
        try:
            ent[0].close()
        except Exception:
            pass


def _session(alias):
    """浏览用的长连接（断了自动重连）。返回 (client, sftp)。"""
    with _LOCK:
        ent = _POOL.get(alias)
        if ent and ent[0].get_transport() and ent[0].get_transport().is_active():
            return ent
    c, _ = connect(_params(alias))
    sftp = c.open_sftp()
    with _LOCK:
        _POOL[alias] = (c, sftp)
    return c, sftp


def fs_list(alias, path=""):
    try:
        _, sftp = _session(alias)
        try:
            cwd = sftp.normalize(path or ".")
            items = sftp.listdir_attr(cwd)
        except (OSError, EOFError, paramiko.SSHException):
            _drop(alias)
            _, sftp = _session(alias)
            cwd = sftp.normalize(path or ".")
            items = sftp.listdir_attr(cwd)
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    except PermissionError:
        return {"ok": False, "error": "没有权限打开这个目录。"}
    except FileNotFoundError:
        return {"ok": False, "error": "目录不存在。"}
    except Exception as e:
        return {"ok": False, "error": "读取目录失败：%s" % e}
    ents = [{"name": a.filename, "dir": statmod.S_ISDIR(a.st_mode or 0), "size": a.st_size or 0, "mtime": a.st_mtime or 0} for a in items]
    ents.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return {"ok": True, "path": cwd, "entries": ents}


def fs_mkdir(alias, parent, name):
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return {"ok": False, "error": "文件夹名不合法。"}
    try:
        _, sftp = _session(alias)
        sftp.mkdir(posixpath.join(parent, name))
    except Exception as e:
        return {"ok": False, "error": "新建失败：%s" % e}
    return {"ok": True}


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


def _remote_encoding(c):
    """交互 shell 的字符编码。Linux/macOS 是 UTF-8；Windows 的 OpenSSH 按控制台代码页输出（中文系统是 GBK/cp936），要照这个解码。"""
    import codecs
    try:
        if detect_os(c) != "Windows":
            return "utf-8"
        _, out, _ = _run(c, "chcp", 8)
        m = re.search(r"(\d{3,5})", out)
        if m:
            name = "cp" + m.group(1)
            codecs.lookup(name)
            return "utf-8" if m.group(1) == "65001" else name
    except Exception:
        pass
    return "utf-8"


def term_open(alias, cols, rows, on_data, on_close):
    """在应用里开一个到主机的交互 shell。on_data(id, 文本) / on_close(id, 原因) 在后台线程里回调。返回 {ok, id, error}。"""
    import codecs
    import uuid
    try:
        c, via = connect(_params(alias))
        chan = c.invoke_shell(term="xterm-256color", width=max(int(cols), 20), height=max(int(rows), 5))
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": "打开命令行失败：%s" % e}
    tid = uuid.uuid4().hex[:8]
    enc = _remote_encoding(c)
    with _LOCK:
        _TERMS[tid] = (c, chan, enc)

    def pump():
        dec = codecs.getincrementaldecoder(enc)("replace")
        reason = ""
        try:
            while True:
                data = chan.recv(32768)
                if not data:
                    break
                txt = dec.decode(data)
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
        ent[1].send(data.encode(ent[2], "replace"))
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
