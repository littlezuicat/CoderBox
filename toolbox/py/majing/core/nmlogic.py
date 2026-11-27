# -*- coding: utf-8 -*-
"""浏览器扩展 ↔ 保险库 的逻辑：按网址匹配条目、取出要填的账号密码、保存新登录。
被原生通信主机（py\\nmhost.py）调用。**密码只在“网址匹配”或用户明确选择时才交给扩展**；内容不写日志。

匹配规则（防钓鱼，宁可少匹配也不多匹配）：
  · 只比主机名，忽略端口和路径；开头的 www. 忽略；
  · 条目里存的网址是 example.com → 页面是 example.com 或它的子域名（a.example.com）才算，
    evil-example.com、example.com.evil.com 都不算；
  · localhost / IP 地址 只接受完全相同；
  · http（非加密）页面默认不填，除非是本机地址或用户在弹窗里明确选择。"""
import ipaddress
from urllib.parse import urlsplit

from majing.core.vault import VaultError, vault


def _parse(url):
    url = (url or "").strip()
    if not url:
        return "", ""
    if "://" not in url:
        url = "https://" + url
    try:
        u = urlsplit(url)
        return (u.scheme or "").lower(), (u.hostname or "").lower().rstrip(".")
    except ValueError:
        return "", ""


def _norm(host):
    return host[4:] if host.startswith("www.") else host


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_local(host):
    return host == "localhost" or host.endswith(".localhost") or host in ("127.0.0.1", "::1")


def url_match(item_url, page_url):
    isch, ih = _parse(item_url)
    psch, ph = _parse(page_url)
    if isch not in ("http", "https") or psch not in ("http", "https") or not ih or not ph:
        return False
    ih, ph = _norm(ih), _norm(ph)
    if ph == ih:
        return True
    if _is_ip(ih) or is_local(ih) or "." not in ih:
        return False
    return ph.endswith("." + ih)


def insecure(page_url):
    sch, host = _parse(page_url)
    return sch == "http" and not is_local(host)


def _summary(i):
    # i 是 vault.list() 的摘要（不含密码）；密码长度要回保险库里取，只把“长度”带给扩展（让菜单里的圆点和真实长度一致），不给密码本身
    try:
        n = len(vault.get(i["id"]).get("password", ""))
    except VaultError:
        n = 0
    return {"id": i["id"], "name": i.get("name", ""), "username": i.get("username", ""), "url": i.get("url", ""), "has_password": n > 0, "plen": n}


def _logins():
    for s in vault.list():
        if s["type"] == "login" and s.get("url"):
            yield s


def match(page_url):
    """当前页面能用的登录。http 页面（非本机）不返回，避免明文网页上被截获。"""
    if insecure(page_url):
        return {"items": [], "insecure": True}
    out = [_summary(s) for s in _logins() if url_match(s["url"], page_url)]
    out.sort(key=lambda x: (x["name"].lower(), x["username"].lower()))
    return {"items": out, "insecure": False}


def search(q, limit=30):
    q = (q or "").strip()
    return {"items": [_summary(s) for s in vault.list(q)[:limit] if s["type"] == "login"]}


def fill(iid, page_url, force=False):
    """取出账号密码。网址不匹配、或页面是 http：只有 force（用户在弹窗里明确点了“仍然填充”）才给。"""
    it = vault.get(iid)
    if it.get("type") != "login":
        raise VaultError("这条不是登录条目。")
    sch, _ = _parse(page_url)
    if sch not in ("http", "https"):
        raise VaultError("这个页面不能填充。")
    if not force and (not url_match(it.get("url", ""), page_url) or insecure(page_url)):
        raise VaultError("这个条目和当前网站对不上，已拒绝填充。")
    return {"username": it.get("username", ""), "password": it.get("password", "")}


def _same_login(page_url, username):
    for s in _logins():
        if url_match(s["url"], page_url) and s.get("username", "").lower() == (username or "").lower():
            return s["id"]
    return None


def check(page_url, username, password):
    """这次提交的登录要不要提示保存：new（新）/ update（密码变了）/ same（已有且一样）。"""
    if not password or _parse(page_url)[0] not in ("http", "https"):
        return {"status": "skip"}
    iid = _same_login(page_url, username)
    if iid is None:
        return {"status": "new"}
    return {"status": "same" if vault.get(iid).get("password", "") == password else "update", "item": iid}


def save(page_url, username, password, name=""):
    st = check(page_url, username, password)
    if st["status"] in ("skip", "same"):
        return {"status": "same" if st["status"] == "same" else "skip"}
    if st["status"] == "update":
        it = vault.get(st["item"])
        it["password"] = password
        vault.save(it)
        return {"status": "updated", "item": st["item"]}
    sch, host = _parse(page_url)
    h = _norm(host)
    iid = vault.save({"type": "login", "name": (name or h)[:80], "username": username or "", "password": password,
                      "url": "%s://%s" % (sch, host), "notes": "", "folder": ""})
    return {"status": "added", "item": iid}
