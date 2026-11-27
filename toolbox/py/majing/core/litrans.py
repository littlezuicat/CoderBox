# -*- coding: utf-8 -*-
"""文献翻译：划词 / 输入即译，走用户自己的 OpenAI 兼容在线 API（DeepSeek、Kimi、硅基流动等）。

移植自开源项目 FlashTrans（https://github.com/chai1220/FlashTrans ，MIT，作者 chai1220）的“在线 API”这条路径，
并带上它的几项提速：复用连接、关闭 DeepSeek 的思考、预热连接、按字节缓冲 SSE（汉字不会被网络包劈开）、译文 LRU 缓存、
复制选中文字用剪贴板序列号判断（不傻等超时）。本地模型 / 截图 OCR / 对话没有移植。

密钥用 Windows DPAPI 加密后才写进设置文件（只有当前 Windows 用户能解开），界面和日志里都不显示。
"""
import base64
import ctypes
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from ctypes import wintypes
from urllib.parse import urlparse

from majing.core import account
from majing.settings import settings

log = logging.getLogger("majing.litrans")

# 总开关：暂时关闭文献翻译（不注册热键、界面里不显示入口）。要恢复就改成 True（同时改 web/src/pages/online.tsx 里的 LIT_ENABLED）。
ENABLED = False

LANGS = [  # (代码, 中文名, 英文名)——英文名喂给模型比语种代码可靠
    ("zh", "中文（简体）", "Chinese (Simplified)"), ("zh-Hant", "中文（繁体）", "Chinese (Traditional)"), ("en", "英语", "English"),
    ("ja", "日语", "Japanese"), ("ko", "韩语", "Korean"), ("fr", "法语", "French"), ("de", "德语", "German"), ("es", "西班牙语", "Spanish"),
    ("it", "意大利语", "Italian"), ("pt", "葡萄牙语", "Portuguese"), ("ru", "俄语", "Russian"), ("ar", "阿拉伯语", "Arabic"),
    ("vi", "越南语", "Vietnamese"), ("th", "泰语", "Thai"), ("id", "印尼语", "Indonesian"),
]
EN = {c: e for c, _, e in LANGS}

DEFAULTS = {
    "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
    "target": "zh",           # 目标语言
    "auto_swap": True,        # 选中的文字本来就是目标语言时，反过来译成英文（中英一键往返）
    "domain": "",             # 额外要求：领域、术语、风格
    "hotkey_on": False, "hotkey": "F1", "stay": 10,
}
KEYS = tuple(DEFAULTS)


# ---------------------------------------------------------------- 配置
def get_cfg():
    c = dict(DEFAULTS)
    for k in KEYS:
        v = settings.get("lit_" + k)
        if v is not None:
            c[k] = v
    return c


def set_cfg(d):
    for k in KEYS:
        if k in d:
            settings.set("lit_" + k, d[k])


def _api_key():
    raw = settings.get("lit_key")
    if not raw:
        return ""
    try:
        return account._unprotect(base64.b64decode(raw)).decode("utf-8")
    except Exception:                                    # noqa: BLE001
        return ""


def set_key(key):
    key = (key or "").strip()
    settings.set("lit_key", base64.b64encode(account._protect(key.encode("utf-8"))).decode() if key else "")


def has_key():
    return bool(_api_key())


# ---------------------------------------------------------------- 语种 / 提示词
def detect_lang(t):
    if re.search(r"[\u4e00-\u9fff]", t):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", t):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", t):
        return "ko"
    if re.search(r"[\u0400-\u04ff]", t):
        return "ru"
    if re.search(r"[\u0600-\u06ff]", t):
        return "ar"
    if re.search(r"[\u0e00-\u0e7f]", t):
        return "th"
    return "en"


def _same(a, b):
    n = lambda x: "zh" if x.startswith("zh") else x      # noqa: E731
    return n(a) == n(b)


def resolve_target(text, cfg):
    """真正要译成什么语言：开了“自动往返”且文字本身就是目标语言时，中文译英文、其它译中文。"""
    tgt = cfg["target"]
    if cfg["auto_swap"] and text.strip() and _same(detect_lang(text), tgt):
        return "en" if _same(tgt, "zh") else "zh"
    return tgt


def messages(text, target, domain=""):
    sysmsg = ("You are a professional translator. Translate the user's text into %s. "
              "Preserve meaning, tone and formatting. Output ONLY the translation, nothing else." % EN.get(target, target))
    if domain.strip():
        sysmsg += " Follow these additional requirements from the user (domain, terminology, style): " + domain.strip()
    sysmsg += " /no_think"
    return [{"role": "system", "content": sysmsg}, {"role": "user", "content": text}]


def _strip_think(t):
    return re.sub(r"<think>[\s\S]*?</think>", "", t, flags=re.I).strip()


# ---------------------------------------------------------------- 翻译
class Translator:
    CACHE_MAX = 200

    def __init__(self):
        self._s = None
        self._lock = threading.Lock()
        self._cache = OrderedDict()
        self._gen = {}                                   # 请求 id → 是否已被取消
        self._warm_at = 0.0

    def _session(self):
        import requests
        from requests.adapters import HTTPAdapter
        with self._lock:
            if self._s is None:
                s = requests.Session()
                s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=8))
                s.headers["User-Agent"] = "MajingToolbox-LitTrans"
                self._s = s
            return self._s

    @staticmethod
    def _url(base):
        base = (base or "").strip().rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def warmup(self):
        """提前和 API 建好连接（TLS 握手），第一句翻译就不用再等。"""
        cfg = get_cfg()
        if not cfg["base_url"].strip() or time.time() - self._warm_at < 20:
            return
        self._warm_at = time.time()

        def go():
            try:
                u = urlparse(self._url(cfg["base_url"]))
                self._session().head("%s://%s/" % (u.scheme, u.netloc), timeout=5)
            except Exception:                            # noqa: BLE001
                pass
        threading.Thread(target=go, daemon=True).start()

    def cancel(self, rid):
        self._gen[rid] = True

    def cancel_all(self):
        for k in list(self._gen):
            self._gen[k] = True

    def run(self, rid, text, emit, cfg=None, use_cache=True):
        """同步翻译（调用方放线程里）。emit(type, data)：delta / done / error。"""
        cfg = cfg or get_cfg()
        self._gen[rid] = False
        text = (text or "").strip()
        if not text:
            emit("done", {"id": rid, "full": "", "cached": False})
            return
        base = cfg["base_url"].strip()
        key = _api_key()
        if not base or not key:
            emit("error", {"id": rid, "message": "还没填接口地址和密钥，先到“文献”页的设置里填一下。"})
            return
        target = resolve_target(text, cfg)
        msgs = messages(text, target, cfg["domain"])
        ck = "\x01".join([base, cfg["model"], json.dumps(msgs, ensure_ascii=False)])
        if use_cache and ck in self._cache:
            self._cache.move_to_end(ck)
            full = self._cache[ck]
            emit("delta", {"id": rid, "text": full})
            emit("done", {"id": rid, "full": full, "cached": True})
            return
        url = self._url(base)
        body = {"model": cfg["model"], "messages": msgs, "stream": True, "temperature": 0.2}
        if "deepseek.com" in (urlparse(url).hostname or ""):
            body["thinking"] = {"type": "disabled"}     # DeepSeek 默认先思考再作答，翻译用不上，白等 0.3~1 秒
        s = self._session()
        resp = None
        for attempt in (0, 1):                           # 连接池里的空闲连接可能已被服务器关掉：失败（非超时）自动重试一次
            try:
                resp = s.post(url, json=body, headers={"Authorization": "Bearer " + key}, stream=True, timeout=(8, 120))
                break
            except Exception as e:                       # noqa: BLE001
                import requests
                if attempt == 0 and not isinstance(e, requests.Timeout):
                    continue
                emit("error", {"id": rid, "message": "请求失败：%s" % e})
                return
        try:
            if resp.status_code != 200:
                emit("error", {"id": rid, "message": "接口错误 %s：%s" % (resp.status_code, resp.text[:300])})
                return
            full = []
            for raw in resp.iter_lines():                # 按字节切行再整行转 UTF-8：汉字不会被网络包劈成乱码
                if self._gen.get(rid):
                    return
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = json.loads(payload)["choices"][0]["delta"].get("content")
                except Exception:                        # noqa: BLE001
                    continue
                if delta:
                    full.append(delta)
                    emit("delta", {"id": rid, "text": delta})
            out = _strip_think("".join(full))
            if use_cache and out:
                self._cache[ck] = out
                while len(self._cache) > self.CACHE_MAX:
                    self._cache.popitem(last=False)
            emit("done", {"id": rid, "full": out, "cached": False})
        except Exception as e:                           # noqa: BLE001
            emit("error", {"id": rid, "message": "流中断：%s" % e})
        finally:
            try:
                resp.close()
            except Exception:                            # noqa: BLE001
                pass
            self._gen.pop(rid, None)

    def test(self, cfg=None):
        """连通性测试：发一句最短的翻译（不走缓存），返回 {ok, ms, text/error}。"""
        out = {"ok": False}
        done = threading.Event()
        t0 = time.time()

        def emit(typ, d):
            if typ == "done":
                out.update(ok=True, ms=int((time.time() - t0) * 1000), text=d.get("full", ""))
                done.set()
            elif typ == "error":
                out.update(ok=False, error=d.get("message", ""))
                done.set()
        self.run(-1, "Hello", emit, cfg=dict(get_cfg(), **(cfg or {}), target="zh", auto_swap=False), use_cache=False)
        done.wait(1)
        return out


translator = Translator()


# ---------------------------------------------------------------- Windows：全局热键 / 取词 / 弹窗位置
_u = _k = None


def _dlls():
    """自己单独的 user32/kernel32 句柄：函数对象是各自的，设 argtypes 不会和别处互相覆盖。"""
    global _u, _k
    if _u is None:
        _u = ctypes.WinDLL("user32", use_last_error=True)
        _k = ctypes.WinDLL("kernel32", use_last_error=True)
        _u.OpenClipboard.argtypes = [wintypes.HWND]
        _u.GetClipboardData.restype = ctypes.c_void_p
        _u.GetClipboardData.argtypes = [wintypes.UINT]
        _k.GlobalLock.restype = ctypes.c_void_p
        _k.GlobalLock.argtypes = [ctypes.c_void_p]
        _k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        _u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        _u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        _u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    return _u, _k


def clipboard_text():
    u, k = _dlls()
    for _ in range(10):
        if u.OpenClipboard(None):
            try:
                h = u.GetClipboardData(13)               # CF_UNICODETEXT
                if not h:
                    return ""
                p = k.GlobalLock(h)
                try:
                    return ctypes.wstring_at(p) if p else ""
                finally:
                    k.GlobalUnlock(h)
            finally:
                u.CloseClipboard()
        time.sleep(0.01)
    return ""


_MODS = {"ctrl": (2, 0x11), "control": (2, 0x11), "alt": (1, 0x12), "shift": (4, 0x10), "win": (8, 0x5B)}
_NAMED = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "`": 0xC0}


def parse_combo(s):
    """'F1' / 'Alt+Q' / 'Ctrl+Shift+T' → (修饰键位, 虚拟键码, [修饰键的虚拟键码])。不认识就 None。"""
    parts = [p.strip() for p in (s or "").split("+") if p.strip()]
    if not parts:
        return None
    mods, mvk = 0, []
    for p in parts[:-1]:
        m = _MODS.get(p.lower())
        if not m:
            return None
        mods |= m[0]
        mvk.append(m[1])
    key = parts[-1].upper()
    if re.fullmatch(r"F([1-9]|1\d|2[0-4])", key):
        vk = 0x70 + int(key[1:]) - 1
    elif len(key) == 1 and key.isalnum():
        vk = ord(key)
    elif key.lower() in _NAMED:
        vk = _NAMED[key.lower()]
    else:
        return None
    return mods, vk, mvk


def grab_selection(mod_vks=()):
    """模拟 Ctrl+C 取当前选中的文字。用剪贴板序列号判断复制是否完成（序列号一变就是目标程序写了剪贴板），不傻等超时。"""
    u, _ = _dlls()
    before = u.GetClipboardSequenceNumber()
    for vk in mod_vks:                                   # 热键里带的 Alt/Shift 还按着，会把 Ctrl+C 变成别的组合
        u.keybd_event(vk, 0, 2, 0)
    for vk, up in ((0x11, 0), (0x43, 0), (0x43, 2), (0x11, 2)):
        u.keybd_event(vk, 0, up, 0)
        time.sleep(0.004)
    t0 = time.time()
    while True:
        time.sleep(0.006)
        if u.GetClipboardSequenceNumber() != before:
            t = clipboard_text()
            if t.strip():
                return t
        if time.time() - t0 > 0.9:
            return clipboard_text()


class Hotkey:
    """全局热键：独立线程里 RegisterHotKey + 消息循环。工具箱缩到托盘时也有效。"""

    def __init__(self, on_press):
        self.on_press = on_press
        self.tid = 0
        self.thread = None
        self.error = ""
        self.combo = ""

    def start(self, combo):
        self.stop()
        self.error, self.combo = "", combo
        p = parse_combo(combo)
        if not p:
            self.error = "热键写法不对：%s（例：F1、Alt+Q、Ctrl+Shift+T）" % combo
            return False
        ready = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(p, ready), daemon=True)
        self.thread.start()
        ready.wait(2)
        return not self.error

    def _loop(self, p, ready):
        u, k = _dlls()
        mods, vk, mvk = p
        self.tid = k.GetCurrentThreadId()
        if not u.RegisterHotKey(None, 1, mods | 0x4000, vk):         # 0x4000 = 按住不重复触发
            self.error = "热键 %s 被别的程序占用了，换一个试试。" % self.combo
            self.tid = 0
            ready.set()
            return
        log.info("热键已注册：%s", self.combo)
        ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:                                # WM_HOTKEY
                log.info("热键触发：%s", self.combo)
                threading.Thread(target=self._fire, args=(mvk,), daemon=True).start()
        u.UnregisterHotKey(None, 1)

    def _fire(self, mvk):
        try:
            self.on_press(mvk)
        except Exception:                                            # noqa: BLE001
            log.exception("热键处理失败")

    def stop(self):
        if self.tid:
            u, _ = _dlls()
            u.PostThreadMessageW(self.tid, 0x0012, 0, 0)             # WM_QUIT
            if self.thread:
                self.thread.join(1)
            self.tid = 0
        self.thread = None


class _RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


class _MI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


def cursor_and_work():
    """(鼠标 x, y, 所在显示器工作区 (l, t, r, b))，物理像素。"""
    u, _ = _dlls()
    pt = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(pt))
    mi = _MI()
    mi.cbSize = ctypes.sizeof(_MI)
    hm = u.MonitorFromPoint(pt, 2)
    u.GetMonitorInfoW(ctypes.c_void_p(hm), ctypes.byref(mi))
    w = mi.rcWork
    return pt.x, pt.y, (w.l, w.t, w.r, w.b)


def place(hwnd, w, h, x=None, y=None, activate=False):
    """把弹窗放到 (x, y)（不给就保持原位置只改大小），置顶，不抢焦点。"""
    u, _ = _dlls()
    flags = 0x10 | (0x0 if x is not None else 0x2)       # SWP_NOACTIVATE；没给位置就加 SWP_NOMOVE
    if x is not None:
        flags |= 0x40                                    # SWP_SHOWWINDOW
    u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), int(x or 0), int(y or 0), int(w), int(h), flags)


def hide(hwnd):
    u, _ = _dlls()
    u.ShowWindow(ctypes.c_void_p(hwnd), 0)


def round_corners(hwnd):
    try:
        v = ctypes.c_int(2)                              # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(v), 4)
    except Exception:                                    # noqa: BLE001
        pass


def set_clipboard_text(text):
    u, k = _dlls()
    data = (text or "").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le") + b"\x00\x00"
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    for _ in range(10):
        if u.OpenClipboard(None):
            try:
                u.EmptyClipboard()
                h = k.GlobalAlloc(0x2, len(data))        # GMEM_MOVEABLE
                p = k.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                k.GlobalUnlock(h)
                u.SetClipboardData(13, h)
                return True
            finally:
                u.CloseClipboard()
        time.sleep(0.01)
    return False


def window_rect(hwnd):
    u, _ = _dlls()
    r = _RECT()
    u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    return r.l, r.t, r.r, r.b


def window_scale(hwnd):
    u, _ = _dlls()
    try:
        return max(1.0, u.GetDpiForWindow(ctypes.c_void_p(hwnd)) / 96.0)
    except Exception:                                    # noqa: BLE001
        return 1.0


def style_popup(hwnd):
    """弹窗：不抢焦点（WS_EX_NOACTIVATE）、不出现在任务栏和 Alt+Tab（WS_EX_TOOLWINDOW）。"""
    u, _ = _dlls()
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    ex = u.GetWindowLongW(ctypes.c_void_p(hwnd), -20)
    u.SetWindowLongW(ctypes.c_void_p(hwnd), -20, ex | 0x08000000 | 0x80)
