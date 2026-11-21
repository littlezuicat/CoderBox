# -*- coding: utf-8 -*-
"""转换历史：PPT定图 / 格式转换各自的长期记录，存在 %APPDATA%\\MajingToolbox\\history.json，重启、更新都不丢。"""
import json
import os
import threading
import time
import uuid

from .settings import _path

MAX = 2000          # 总条数上限，超出丢最旧的
_lock = threading.Lock()


def _file():
    return os.path.join(os.path.dirname(_path()), "history.json")


def _load():
    try:
        with open(_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _save(items):
    try:
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, _file())
    except Exception:
        pass


def add(kind, name, src, output, ok, detail="", size=0):
    e = {"id": uuid.uuid4().hex[:12], "kind": kind, "name": name, "src": src, "output": output or "", "ok": bool(ok),
         "detail": detail or "", "size": int(size or 0), "time": int(time.time())}
    with _lock:
        items = _load()
        items.append(e)
        _save(items[-MAX:])
    return e


def list_(kind):
    with _lock:
        items = [e for e in _load() if e.get("kind") == kind]
    items.reverse()          # 新的在前
    for e in items:
        e["exists"] = bool(e.get("output")) and os.path.exists(e["output"])
    return items


def remove(hid):
    with _lock:
        items = _load()
        _save([e for e in items if e.get("id") != hid])
    return True


def clear(kind):
    with _lock:
        items = _load()
        _save([e for e in items if e.get("kind") != kind])
    return True
