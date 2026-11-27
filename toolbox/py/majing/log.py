# -*- coding: utf-8 -*-
"""日志。源码版（不是打包的 exe）默认记详细调试日志到 toolbox\\logs\\debug.log：每个前端→后端的接口调用（参数、耗时、结果、异常堆栈）、
SSH 连接/配密钥的每一步、前端的 JS 报错都在里面。打包版只记 WARNING 以上，放在 %APPDATA%\\MajingToolbox\\app.log。
密码、令牌之类的字段一律写成 ***，不会进日志。"""
import functools
import inspect
import json
import logging
import logging.handlers
import os
import sys
import time

_SECRET = ("password", "passwd", "token", "secret", "pw")
_SKIP = {"term_input", "term_resize", "log_js", "busy_text"}            # 太吵的接口不记
_started = False


def is_source():
    return not getattr(sys, "frozen", False)


def log_path():
    if is_source():
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.abspath(os.path.join(here, "..", "..", "logs"))
        name = "debug.log"
    else:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MajingToolbox")
        name = "app.log"
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def setup():
    global _started
    if _started:
        return
    _started = True
    root = logging.getLogger("majing")
    root.setLevel(logging.DEBUG if is_source() else logging.WARNING)
    try:
        h = logging.handlers.RotatingFileHandler(log_path(), maxBytes=5_000_000, backupCount=4, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(name)s: %(message)s", "%H:%M:%S"))
    root.addHandler(h)
    root.propagate = False
    logging.getLogger("majing").info("==== 启动 pid=%s %s python=%s ====", os.getpid(), "源码版" if is_source() else "打包版", sys.version.split()[0])
    for noisy in ("paramiko",):
        logging.getLogger(noisy).setLevel(logging.INFO if is_source() else logging.ERROR)
        if is_source():
            logging.getLogger(noisy).addHandler(h)


def clean(v, depth=0):
    """把参数/结果变成适合写日志的样子：藏掉密码，截断长字符串和长列表。"""
    if depth > 4:
        return "…"
    if isinstance(v, dict):
        return {k: ("***" if any(s in str(k).lower() for s in _SECRET) and isinstance(v[k], str) and v[k] else clean(v[k], depth + 1)) for k in list(v)[:40]}
    if isinstance(v, (list, tuple)):
        out = [clean(x, depth + 1) for x in list(v)[:12]]
        if len(v) > 12:
            out.append("…共%d项" % len(v))
        return out
    if isinstance(v, str):
        return v if len(v) <= 300 else v[:300] + "…(%d字)" % len(v)
    return v


def _fmt(v):
    try:
        return json.dumps(clean(v), ensure_ascii=False, default=str)
    except Exception:
        return repr(v)[:300]


def wrap_api(api):
    """给 Api 实例的所有公开方法套上日志（只有源码版或设了 MAJING_LOG 才套）。"""
    if not (is_source() or os.environ.get("MAJING_LOG")):
        return
    lg = logging.getLogger("majing.api")
    for name, fn in inspect.getmembers(api, inspect.ismethod):
        if name.startswith("_") or name in _SKIP:
            continue

        def make(name, fn):
            @functools.wraps(fn)
            def w(*a, **k):
                t0 = time.time()
                lg.debug("→ %s(%s)", name, ", ".join([_fmt(x) for x in a] + ["%s=%s" % (kk, _fmt(vv)) for kk, vv in k.items()]))
                try:
                    r = fn(*a, **k)
                except Exception:
                    lg.exception("✗ %s 抛出异常（%.0f ms）", name, (time.time() - t0) * 1000)
                    raise
                bad = isinstance(r, dict) and r.get("ok") is False
                lg.log(logging.WARNING if bad else logging.DEBUG, "← %s %.0f ms %s", name, (time.time() - t0) * 1000, _fmt(r) if bad else _fmt(r)[:400])
                return r
            return w
        setattr(api, name, make(name, fn))
