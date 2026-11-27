# -*- coding: utf-8 -*-
"""给本机 VS Code 的用户设置写入 remote.SSH.remotePlatform：{主机别名: linux | windows | macOS}。
Remote-SSH 第一次连一台主机会弹“选择远程主机的系统”，写好这一项就不再问。
settings.json 是带注释的 JSONC，不能解析后重写（会丢注释），所以只做文本层面的最小改动；改之前备份一次。"""
import os
import re

KEY = "remote.SSH.remotePlatform"


def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Code", "User", "settings.json")


def _entry(alias, plat):
    return '"%s": "%s"' % (alias.replace("\\", "\\\\").replace('"', '\\"'), plat)


def set_platform(alias, plat, path=None):
    """返回 True = 已写入（或本来就是这个值）；False = 文件结构看不懂，没动它。"""
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path) or not open(path, encoding="utf-8-sig").read().strip():
        with open(path, "w", encoding="utf-8") as f:
            f.write('{\n  "%s": {\n    %s\n  }\n}\n' % (KEY, _entry(alias, plat)))
        return True
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    ent = _entry(alias, plat)
    m = re.search(r'"%s"\s*:\s*\{([^{}]*)\}' % re.escape(KEY), text)
    if m:
        body = m.group(1)
        am = re.search(r'"%s"\s*:\s*"[^"]*"' % re.escape(alias.replace("\\", "\\\\").replace('"', '\\"')), body)
        if am:
            if am.group(0) == ent:
                return True
            nb = body[:am.start()] + ent + body[am.end():]
        else:
            nb = (nl + "    " + ent + "," + body) if body.strip() else (nl + "    " + ent + nl + "  ")
        new = text[:m.start(1)] + nb + text[m.end(1):]
    else:
        end = text.rfind("}")
        if end < 0:
            return False
        head = text[:end].rstrip()
        lines = [x for x in head.splitlines() if x.strip() and not x.strip().startswith("//")]
        if not lines:
            return False
        last = lines[-1].rstrip()
        if "//" in last.replace("://", ""):                  # 末行带行尾注释：加逗号会加进注释里，不碰
            return False
        comma = "" if last.endswith(("{", ",")) else ","
        # 把逗号加在最后一个值后面（注释行之前）
        if comma:
            pos = head.rfind(last) + len(last)
            head = head[:pos] + "," + head[pos:]
        block = '%s  "%s": {%s    %s%s  }' % (nl, KEY, nl, ent, nl)
        new = head + block + nl + text[end:]
    bak = path + ".bak-toolbox"
    if not os.path.exists(bak):
        try:
            with open(bak, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return True
