# -*- coding: utf-8 -*-
"""设备安全页的“一键修复”：直接改本机 Clash Verge (Rev) 的配置文件，改之前先备份（旁边生成 .bak-日期-toolbox），再让正在运行的内核热加载。
  · DNS 泄露 → DNS 增强模式改成 fake-ip（dns_config.yaml + 当前运行配置 + 打开“DNS 覆写”开关）
  · WebRTC 泄露 → 屏蔽常见 STUN 端口（UDP 3478、19302-19309），写进当前订阅的“规则增强”（订阅更新后也还在）+ 当前运行配置。需要先开 TUN 模式。
只用文本方式改，不动用户原有的格式和注释；不打印、不记录 controller 的 secret。
环境变量 MAJING_CLASH_DIR 可以指到别的目录（测试用，此时不会去热加载内核）。"""
import logging
import os
import re
import time

import requests

log = logging.getLogger("majing.clashfix")

STUN_RULES = [
    "AND,((NETWORK,UDP),(DST-PORT,3478)),REJECT",
    "AND,((NETWORK,UDP),(DST-PORT,19302-19309)),REJECT",
]


class ClashFixError(Exception):
    pass


def clash_dir():
    d = os.environ.get("MAJING_CLASH_DIR") or os.path.join(os.environ.get("APPDATA", ""), "io.github.clash-verge-rev.clash-verge-rev")
    if not d or not os.path.isdir(d) or not os.path.exists(os.path.join(d, "verge.yaml")):
        raise ClashFixError("没找到 Clash Verge 的配置（只支持 Clash Verge Rev），请手动修改。")
    return d


def _rd(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def _wr(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def _backup(p):
    stamp = time.strftime("%Y%m%d")
    dst = "%s.bak-%s-toolbox" % (p, stamp)
    if os.path.exists(dst):
        dst = "%s.bak-%s-toolbox" % (p, time.strftime("%Y%m%d-%H%M%S"))
    with open(p, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())


def _nl(s):
    return "\r\n" if "\r\n" in s else "\n"


def _section(lines, key):
    """顶层 key: 的行号 i 和这一节结束的行号 j（下一个顶层行）。没有返回 None。"""
    for i, l in enumerate(lines):
        if re.match(r"^%s:\s*(#.*)?$" % re.escape(key), l.rstrip("\r\n")):
            j = i + 1
            while j < len(lines):
                t = lines[j].rstrip("\r\n")
                if t.strip() and not t[0].isspace() and not t.startswith("#"):
                    break
                j += 1
            return i, j
    return None


def _set_in_section(text, section, key, value):
    """把 section 这一节里（第一层）的 key 设成 value；没有就插在节头后面。返回 (新文本, 旧值或 None, 是否改了)。"""
    nl = _nl(text)
    lines = text.splitlines(True)
    sp = _section(lines, section)
    if not sp:
        return text, None, False
    i, j = sp
    indent = None
    for k in range(i + 1, j):
        t = lines[k].rstrip("\r\n")
        if t.strip() and not t.lstrip().startswith("#"):
            indent = len(t) - len(t.lstrip())
            break
    indent = indent or 2
    pat = re.compile(r"^(\s{%d})%s:\s*([^#\r\n]*?)\s*(#.*)?$" % (indent, re.escape(key)))
    for k in range(i + 1, j):
        m = pat.match(lines[k].rstrip("\r\n"))
        if m:
            old = m.group(2).strip().strip("'\"")
            if old == value:
                return text, old, False
            lines[k] = "%s%s: %s%s" % (m.group(1), key, value, nl)
            return "".join(lines), old, True
    lines.insert(i + 1, "%s%s: %s%s" % (" " * indent, key, value, nl))
    return "".join(lines), None, True


def _set_top(text, key, value):
    nl = _nl(text)
    m = re.search(r"^%s:[ \t]*([^\r\n]*)$" % re.escape(key), text, re.M)
    if m:
        old = m.group(1).split("#")[0].strip()
        if old == value:
            return text, False
        return text[:m.start()] + "%s: %s" % (key, value) + text[m.end():], True
    return text.rstrip("\r\n") + nl + "%s: %s%s" % (key, value, nl), True


def _top_value(text, key):
    m = re.search(r"^%s:[ \t]*([^\r\n]*)$" % re.escape(key), text, re.M)
    return m.group(1).split("#")[0].strip().strip("'\"") if m else None


def _reload(d):
    """让正在运行的内核重新读运行配置（Clash Verge 自己也是这么做的）。返回 (成功?, 说明)。"""
    if os.environ.get("MAJING_CLASH_DIR"):
        return False, "测试目录，没有热加载"
    run = os.path.join(d, "clash-verge.yaml")
    ctrl, secret = None, ""
    for f in ("clash-verge.yaml", "config.yaml"):
        p = os.path.join(d, f)
        if not os.path.exists(p):
            continue
        t = _rd(p)
        ctrl = ctrl or _top_value(t, "external-controller")
        secret = secret or _top_value(t, "secret") or ""
    if not ctrl:
        return False, "没找到 Clash 的控制端口"
    host = ctrl.replace("0.0.0.0", "127.0.0.1").replace("[::]", "127.0.0.1")
    s = requests.Session()
    s.trust_env = False                                   # 控制端口在本机，不走代理
    hd = {"Authorization": "Bearer " + secret} if secret else {}
    try:
        r = s.put("http://%s/configs?force=true" % host, json={"path": run, "payload": ""}, headers=hd, timeout=20)
        if r.status_code >= 300:
            log.info("热加载失败：HTTP %s %s", r.status_code, r.text[:200])
            return False, "Clash 没接受热加载（HTTP %s）" % r.status_code
        try:
            s.post("http://%s/cache/fakeip/flush" % host, headers=hd, timeout=5)
        except Exception:                                 # noqa: BLE001
            pass
        return True, ""
    except Exception as e:                                # noqa: BLE001
        log.info("热加载失败：%s", e)
        return False, "连不上 Clash 的控制端口"


def fix_dns():
    d = clash_dir()
    jobs = []                                             # (路径, 新文本)
    changed_any = False
    for fname in ("dns_config.yaml", "clash-verge.yaml"):
        p = os.path.join(d, fname)
        if not os.path.exists(p):
            continue
        t = _rd(p)
        n = t
        for k, v in (("enhanced-mode", "fake-ip"), ("enable", "true")):
            n, old, ch = _set_in_section(n, "dns", k, v)
            log.info("%s: dns.%s %s -> %s%s", fname, k, old, v, "" if ch else "（不用改）")
        if n != t:
            jobs.append((p, n))
    vp = os.path.join(d, "verge.yaml")
    vt = _rd(vp)
    vn, ch = _set_top(vt, "enable_dns_settings", "true")   # 不打开的话 dns_config.yaml 不生效
    if ch:
        jobs.append((vp, vn))
    for p, n in jobs:
        _backup(p)
        _wr(p, n)
        changed_any = True
    if not changed_any:
        return {"msg": "DNS 已经是 fake-ip 模式，没有要改的。再点一次“重新检测”看看；如果还报泄露，多半是其他程序绕过了 Clash 在用本机 DNS。", "changed": False}
    ok, why = _reload(d)
    log.info("fix_dns 改了 %s；热加载：%s %s", [os.path.basename(p) for p, _ in jobs], ok, why)
    return {"msg": "已把 DNS 改成 fake-ip 模式（原文件已备份）。" + ("已立即生效。" if ok else "需要在 Clash Verge 里重新应用一下配置才生效（%s）。" % why if why else ""), "changed": True}


def _current_rules_file(d):
    """当前订阅的“规则增强”文件路径；没有返回 None。"""
    pt = _rd(os.path.join(d, "profiles.yaml"))
    cur = _top_value(pt, "current")
    if not cur:
        return None
    blocks = re.split(r"(?m)^- (?=uid:)", pt)
    by_uid = {}
    for b in blocks[1:]:
        m = re.match(r"uid:\s*(\S+)", b)
        if m:
            by_uid[m.group(1)] = b
    b = by_uid.get(cur)
    if not b:
        return None
    m = re.search(r"(?m)^\s+rules:\s*(\S+)\s*$", b)
    if not m or m.group(1) == "null":
        return None
    rb = by_uid.get(m.group(1), "")
    fm = re.search(r"(?m)^\s+file:\s*(\S+)", rb)
    p = os.path.join(d, "profiles", fm.group(1) if fm else m.group(1) + ".yaml")
    return p if os.path.exists(p) else None


def _insert_list(text, head_re, rules, default_indent, inline_empty):
    """在以 head_re 开头的列表头后面插入 rules（跳过已有的）。返回新文本；没有变化返回原文本。"""
    nl = _nl(text)
    lines = text.splitlines(True)
    for i, l in enumerate(lines):
        t = l.rstrip("\r\n")
        m = re.match(head_re, t)
        if not m:
            continue
        rest = t[m.end():].strip()
        indent = default_indent
        for k in range(i + 1, len(lines)):
            s = lines[k].rstrip("\r\n")
            if s.strip().startswith("- "):
                indent = len(s) - len(s.lstrip())
                break
            if s.strip() and not s.strip().startswith("#"):
                break
        if rest == "[]" and not inline_empty:
            lines[i] = t[:m.end()].rstrip() + nl
        elif rest and rest != "[]":
            return text                                   # 不认识的写法（比如行内列表），不动
        existing = "".join(lines)
        add = [r for r in rules if ("- " + r) not in existing]
        if not add:
            return text
        for n, r in enumerate(add):
            lines.insert(i + 1 + n, "%s- %s%s" % (" " * indent, r, nl))
        return "".join(lines)
    return text


def fix_webrtc():
    d = clash_dir()
    vt = _rd(os.path.join(d, "verge.yaml"))
    if _top_value(vt, "enable_tun_mode") != "true":
        raise ClashFixError("WebRTC 走的是 UDP，要打开 Clash Verge 的「虚拟网卡（TUN）模式」才管得到。请先在 Clash Verge 里打开它，再来修复。")
    jobs = []
    rf = _current_rules_file(d)
    if rf:
        t = _rd(rf)
        n = _insert_list(t, r"^prepend:", STUN_RULES, 2, False)
        if n != t:
            jobs.append((rf, n))
    run = os.path.join(d, "clash-verge.yaml")
    if os.path.exists(run):
        t = _rd(run)
        n = _insert_list(t, r"^rules:", STUN_RULES, 0, False)
        if n != t:
            jobs.append((run, n))
    if not jobs:
        return {"msg": "已经屏蔽过 STUN 端口了，没有要改的。再点一次“重新检测”看看。", "changed": False}
    for p, n in jobs:
        _backup(p)
        _wr(p, n)
    ok, why = _reload(d)
    log.info("fix_webrtc 改了 %s；热加载：%s %s", [os.path.basename(p) for p, _ in jobs], ok, why)
    tail = "已立即生效。" if ok else ("需要在 Clash Verge 里重新应用一下配置才生效（%s）。" % why if why else "")
    extra = "" if rf else "（没找到当前订阅的规则增强，订阅更新后可能需要再修复一次）"
    return {"msg": "已屏蔽 STUN 常用端口（UDP 3478、19302–19309），WebRTC 不再暴露本机地址（原文件已备份）。" + tail + extra, "changed": True}


def fix(kind):
    if kind == "dns":
        return fix_dns()
    if kind == "webrtc":
        return fix_webrtc()
    raise ClashFixError("不认识的修复项：%s" % kind)
