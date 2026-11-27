# -*- coding: utf-8 -*-
"""设备安全：取各出口 IP、IP 质量、DNS 泄露、服务可用性的原始数据（判断“通过/不通过”在前端做）。
思路取自 https://ip.net.coffee/claude/ 页面：
  · 出口 IP：1.1.1.1/cdn-cgi/trace（Cloudflare 出口）、claude.ai/cdn-cgi/trace（Claude 出口）、ip138 / ip.cn（国内出口）
  · IP 信息：ip.net.coffee/api/geoip/<ip>（归属地）、/api/iprisk/<ip>（信任评分、住宅/机房、VPN/代理/Tor/爬虫/滥用…）
  · DNS 泄露：解析 <随机令牌>-N.d.ip.net.coffee（它家的权威 DNS 会记下是哪个递归 DNS 来问的），再查 /api/dns/result/<令牌>
  · 可用性：claude.ai、anthropic.com 的 trace 延迟，/claude/status.json 的服务状态
网络请求都从本机发出，走系统代理/TUN，和浏览器看到的一致。会把本机的出口 IP、随机令牌发给 ip.net.coffee（第三方站点）。"""
import ipaddress
import logging
import re
import socket
import threading
import time
import uuid

import requests

log = logging.getLogger("majing.devsec")
API = "https://ip.net.coffee"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_HEAD = {"User-Agent": UA, "Cache-Control": "no-cache"}


def _get(url, timeout):
    r = requests.get(url, timeout=timeout, headers=_HEAD)
    r.raise_for_status()
    return r


def _trace(url, timeout):
    """Cloudflare 的 /cdn-cgi/trace：每行 key=value。返回 {ip, loc, ms}。"""
    t0 = time.time()
    r = _get(url, timeout)
    d = dict(l.split("=", 1) for l in r.text.strip().split("\n") if "=" in l)
    return {"ip": d.get("ip"), "loc": (d.get("loc") or "").lower() or None, "ms": int((time.time() - t0) * 1000)}


def _ip(s):
    return str(ipaddress.ip_address(str(s).strip()))


def exit_ips():
    """三个出口 IP：{cf, claude, cn}，取不到的是 None。并行取。"""
    out = {"cf": None, "claude": None, "cn": None}

    def cf():
        out["cf"] = _trace("https://1.1.1.1/cdn-cgi/trace", 6)

    def claude():
        out["claude"] = _trace("https://claude.ai/cdn-cgi/trace", 8)

    def cn():
        for url, src in (("https://2026.ip138.com/", "ip138"), ("https://my.ip.cn/", "ip.cn")):
            try:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", _get(url, 6).text)
                if m:
                    out["cn"] = {"ip": m.group(1), "source": src}
                    return
            except Exception as e:                       # noqa: BLE001
                log.info("国内出口 %s 失败：%s", src, e)

    ths = []
    for fn in (cf, claude, cn):
        def run(f=fn):
            try:
                f()
            except Exception as e:                       # noqa: BLE001
                log.info("取出口 IP 失败 %s：%s", f.__name__, e)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        ths.append(t)
    for t in ths:
        t.join(15)
    log.info("出口 IP：%s", out)
    return out


def geoip(ip):
    return _get("%s/api/geoip/%s" % (API, _ip(ip)), 6).json()


def iprisk(ip):
    return _get("%s/api/iprisk/%s" % (API, _ip(ip)), 12).json()


def dns_leak():
    """触发两次解析，等一会儿，再取“哪些 DNS 服务器来问过”。返回 {servers: [{ip, country_code, isp}], resolved: [解析到的地址]}。
    servers 为空 = 没暴露出口（比如 DNS 走了加密/代理的 fake-ip）。"""
    token = uuid.uuid4().hex
    resolved = []
    for i in (1, 2):
        try:
            ai = socket.getaddrinfo("%s-%d.d.ip.net.coffee" % (token, i), 443, proto=socket.IPPROTO_TCP)
            resolved.append(ai[0][4][0])
        except OSError as e:
            log.info("DNS 解析失败：%s", e)
    time.sleep(1.5)
    servers = []
    for attempt in range(3):
        try:
            servers = _get("%s/api/dns/result/%s" % (API, token), 5).json().get("dns_servers") or []
        except Exception as e:                           # noqa: BLE001
            log.info("取 DNS 结果失败：%s", e)
        if servers:
            break
        time.sleep(1.5)
    out = []
    for ip in servers[:6]:
        try:
            g = geoip(ip)
            out.append({"ip": ip, "country_code": (g.get("country_code") or "").lower(), "isp": g.get("isp") or ""})
        except Exception:                                # noqa: BLE001
            out.append({"ip": ip, "country_code": "", "isp": ""})
    log.info("DNS 泄露检测：解析到 %s，服务器 %s", resolved, out)
    return {"servers": out, "resolved": resolved}


def avail():
    """claude.ai / anthropic.com 能不能连上、延迟多少，以及 Claude 服务状态（来自 ip.net.coffee 的 status.json）。"""
    res = {"sites": [], "status": None}
    for name, url in (("claude.ai", "https://claude.ai/cdn-cgi/trace"), ("anthropic.com", "https://www.anthropic.com/cdn-cgi/trace")):
        try:
            res["sites"].append({"name": name, "ok": True, "ms": _trace(url, 6)["ms"]})
        except Exception as e:                           # noqa: BLE001
            log.info("%s 不可访问：%s", name, e)
            res["sites"].append({"name": name, "ok": False, "ms": -1})
    try:
        res["status"] = _get(API + "/claude/status.json", 5).json().get("overall_indicator") or "none"
    except Exception:                                    # noqa: BLE001
        res["status"] = None
    return res
