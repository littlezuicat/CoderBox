# -*- coding: utf-8 -*-
"""Chrome / Edge 扩展的原生通信主机（Native Messaging）。浏览器按需启动它，通过标准输入输出收发 JSON（4 字节长度 + 内容）。
它和工具箱用同一个保险库文件（vault.dat，DPAPI 保护，只有当前 Windows 用户能读）。
只服务我们自己的扩展：浏览器传来的来源（argv[1]）不是我们扩展就退出。日志只记操作名，不记内容。"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

from majing import APP_VERSION                      # noqa: E402
from majing.core import nmlogic, nmreg               # noqa: E402
from majing.core.vault import VaultError, vault      # noqa: E402

_LOG = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MajingToolbox", "nm.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        if os.path.exists(_LOG) and os.path.getsize(_LOG) > 200_000:
            os.replace(_LOG, _LOG + ".old")
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def read_msg():
    head = sys.stdin.buffer.read(4)
    if len(head) < 4:
        return None
    n = struct.unpack("<I", head)[0]
    if n > 1024 * 1024:
        return None
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))


def send(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def handle(m):
    op = m.get("op")
    if op == "ping":
        return {"version": APP_VERSION, "count": vault.status()["count"]}
    if op == "match":
        return nmlogic.match(str(m.get("url", "")))
    if op == "search":
        return nmlogic.search(str(m.get("q", "")))
    if op == "fill":
        return nmlogic.fill(str(m.get("item", "")), str(m.get("url", "")), bool(m.get("force")))
    if op == "check":
        return nmlogic.check(str(m.get("url", "")), str(m.get("username", "")), str(m.get("password", "")))
    if op == "save":
        return nmlogic.save(str(m.get("url", "")), str(m.get("username", "")), str(m.get("password", "")), str(m.get("name", "")))
    raise VaultError("不认识的请求。")


def main():
    origin = next((a for a in sys.argv[1:] if a.startswith("chrome-extension://")), "")
    if origin and origin.rstrip("/") != "chrome-extension://" + nmreg.ext_id():
        log("拒绝：来源不是码境密码扩展")
        return 1
    log("启动")
    while True:
        try:
            m = read_msg()
        except Exception:                                    # noqa: BLE001
            break
        if m is None:
            break
        rid = m.get("id")
        try:
            r = handle(m)
            send({**r, "id": rid, "ok": True})                # 请求编号放最后，结果里就算有 id 字段也不会盖掉它
            log("op=%s ok" % m.get("op"))
        except VaultError as e:
            send({"id": rid, "ok": False, "error": str(e)})
            log("op=%s 拒绝：%s" % (m.get("op"), e))
        except Exception as e:                               # noqa: BLE001
            send({"id": rid, "ok": False, "error": "出错：%s" % type(e).__name__})
            log("op=%s 异常 %s" % (m.get("op"), type(e).__name__))
    log("退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
