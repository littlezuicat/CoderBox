# -*- coding: utf-8 -*-
"""Windows 剪贴板上的“虚拟文件”（FileGroupDescriptorW + FileContents）：复制服务器上的文件时本机什么都不下载，
剪贴板上只放一份“文件清单”和按需读取的数据流；到资源管理器/桌面里 Ctrl+V 粘贴的那一刻，系统才逐个来读文件内容，
我们这时才从服务器读，资源管理器自己弹出原生的复制进度框（有取消）。

为什么不用 CF_HDROP 延迟渲染：系统里的剪贴板监听程序（微信、剪贴板历史…）一有变化就会去读 CF_HDROP，
会让“复制”立刻开始下载（实测：offer 之后 0.01 秒就被渲染了）。虚拟文件格式它们不会去读内容。

实现：用 ctypes 手写 COM 的 IDataObject / IStream（OleSetClipboard），全部跑在一条专用的 STA 线程里（要泵消息，系统的跨进程调用在这条线程上分发）。
来源（Source）是可替换的：list_entries() → [{rel, size, mtime, isdir}]（rel 用 / 分隔，文件夹要先于它里面的文件），
open(i) → 有 read(n)/seek(pos)/close() 的对象，close() 清理。"""
import ctypes
import queue
import struct
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_long, c_ubyte, c_ulong, c_ulonglong, c_longlong, c_ushort, c_void_p, wintypes

HRESULT = c_long
WINFUNCTYPE = ctypes.WINFUNCTYPE if sys.platform == "win32" else None


def _hr(v):
    return c_long(v).value


S_OK, S_FALSE = 0, 1
E_NOTIMPL, E_NOINTERFACE, E_POINTER, E_FAIL = _hr(0x80004001), _hr(0x80004002), _hr(0x80004003), _hr(0x80004005)
DV_E_FORMATETC, DV_E_TYMED, DV_E_LINDEX = _hr(0x80040064), _hr(0x80040069), _hr(0x80040068)
OLE_E_ADVISENOTSUPPORTED = _hr(0x80040003)
DATA_S_SAMEFORMATETC = _hr(0x00040130)
STG_E_ACCESSDENIED = _hr(0x80030005)

TYMED_HGLOBAL, TYMED_ISTREAM = 1, 4
DVASPECT_CONTENT = 1
FD_ATTRIBUTES, FD_WRITESTIME, FD_FILESIZE, FD_PROGRESSUI = 0x4, 0x20, 0x40, 0x4000
FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_NORMAL = 0x10, 0x80
GMEM_MOVEABLE, GMEM_ZEROINIT = 0x2, 0x40
WM_APP_JOB = 0x8000 + 7


class GUID(Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]


def _guid(s):
    import uuid
    u = uuid.UUID(s)
    g = GUID()
    g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


def _same(a, b):
    return bytes(a) == bytes(b)


IID_IUnknown = _guid("00000000-0000-0000-C000-000000000046")
IID_IDataObject = _guid("0000010E-0000-0000-C000-000000000046")
IID_IDropSource = _guid("00000121-0000-0000-C000-000000000046")
IID_IStream = _guid("0000000C-0000-0000-C000-000000000046")
IID_ISequentialStream = _guid("0C733A30-2A1C-11CE-ADE5-00AA0044773D")


class FORMATETC(Structure):
    _fields_ = [("cfFormat", c_ushort), ("ptd", c_void_p), ("dwAspect", wintypes.DWORD), ("lindex", c_long), ("tymed", wintypes.DWORD)]


class STGMEDIUM(Structure):
    _fields_ = [("tymed", wintypes.DWORD), ("u", c_void_p), ("pUnkForRelease", c_void_p)]


class FILETIME(Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class STATSTG(Structure):
    _fields_ = [("pwcsName", c_void_p), ("type", wintypes.DWORD), ("cbSize", c_ulonglong), ("mtime", FILETIME), ("ctime", FILETIME), ("atime", FILETIME),
                ("grfMode", wintypes.DWORD), ("grfLocksSupported", wintypes.DWORD), ("clsid", GUID), ("grfStateBits", wintypes.DWORD), ("reserved", wintypes.DWORD)]


def _filetime(ts):
    v = int((ts or 0) * 10000000) + 116444736000000000
    return v & 0xFFFFFFFF, (v >> 32) & 0xFFFFFFFF


def _bad(name):
    """Windows 文件名里不允许的字符换成下划线。"""
    out = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).rstrip(" .")
    return out or "_"


# ------------------------------------------------------------------------------------------ COM 对象
_REG = {}                      # 对象地址 → Python 状态（引用计数、数据）
_LOCK = threading.Lock()
_KEEP = []                     # 回调函数对象要一直活着


def _mk_vtbl(protos, funcs):
    arr = (c_void_p * len(funcs))()
    for i, (p, f) in enumerate(zip(protos, funcs)):
        cb = p(f)
        _KEEP.append(cb)
        arr[i] = ctypes.cast(cb, c_void_p).value
    _KEEP.append(arr)
    return arr


class _Obj(Structure):
    _fields_ = [("vtbl", c_void_p)]


def _new(vtbl, state):
    o = _Obj()
    o.vtbl = ctypes.addressof(vtbl)
    addr = ctypes.addressof(o)
    state["obj"] = o
    state["ref"] = 1
    with _LOCK:
        _REG[addr] = state
    return addr


def _st(this):
    return _REG.get(this)


def _addref(this):
    s = _st(this)
    if not s:
        return 0
    with _LOCK:
        s["ref"] += 1
        return s["ref"]


def _release(this):
    s = _st(this)
    if not s:
        return 0
    with _LOCK:
        s["ref"] -= 1
        n = s["ref"]
        if n <= 0:
            _REG.pop(this, None)
    if n <= 0:
        try:
            s["on_free"]()
        except Exception:                                        # noqa: BLE001
            pass
    return max(n, 0)


def _qi_factory(iids):
    def qi(this, riid, ppv):
        if not ppv:
            return E_POINTER
        iid = ctypes.cast(riid, POINTER(GUID)).contents
        if any(_same(iid, g) for g in iids):
            ctypes.cast(ppv, POINTER(c_void_p))[0] = this
            _addref(this)
            return S_OK
        ctypes.cast(ppv, POINTER(c_void_p))[0] = None
        return E_NOINTERFACE
    return qi


# ---- IStream：一个文件的内容（按需从来源读）
def _stream_funcs():
    P = WINFUNCTYPE
    protos = [
        P(HRESULT, c_void_p, c_void_p, POINTER(c_void_p)), P(c_ulong, c_void_p), P(c_ulong, c_void_p),                      # IUnknown
        P(HRESULT, c_void_p, c_void_p, c_ulong, POINTER(c_ulong)),                                                          # Read
        P(HRESULT, c_void_p, c_void_p, c_ulong, POINTER(c_ulong)),                                                          # Write
        P(HRESULT, c_void_p, c_longlong, wintypes.DWORD, POINTER(c_ulonglong)),                                             # Seek
        P(HRESULT, c_void_p, c_ulonglong),                                                                                  # SetSize
        P(HRESULT, c_void_p, c_void_p, c_ulonglong, POINTER(c_ulonglong), POINTER(c_ulonglong)),                            # CopyTo
        P(HRESULT, c_void_p, wintypes.DWORD), P(HRESULT, c_void_p),                                                         # Commit, Revert
        P(HRESULT, c_void_p, c_ulonglong, c_ulonglong, wintypes.DWORD), P(HRESULT, c_void_p, c_ulonglong, c_ulonglong, wintypes.DWORD),
        P(HRESULT, c_void_p, POINTER(STATSTG), wintypes.DWORD),                                                             # Stat
        P(HRESULT, c_void_p, POINTER(c_void_p)),                                                                            # Clone
    ]

    def read(this, pv, cb, pcb):
        s = _st(this)
        try:
            data = s["fh"]().read(int(cb)) if cb else b""
            if data:
                ctypes.memmove(pv, data, len(data))
            s["pos"] += len(data)
            if pcb:
                pcb[0] = len(data)
            return S_OK if data or not cb else S_FALSE
        except Exception:                                        # noqa: BLE001
            if pcb:
                pcb[0] = 0
            return E_FAIL

    def seek(this, move, origin, pnew):
        s = _st(this)
        try:
            base = {0: 0, 1: s["pos"], 2: s["size"]}.get(int(origin), 0)
            new = max(0, base + int(move))
            s["fh"]().seek(new)
            s["pos"] = new
            if pnew:
                pnew[0] = new
            return S_OK
        except Exception:                                        # noqa: BLE001
            return E_FAIL

    def stat(this, pst, flag):
        s = _st(this)
        st = pst.contents
        ctypes.memset(ctypes.addressof(st), 0, ctypes.sizeof(STATSTG))
        st.type, st.cbSize = 2, int(s["size"])
        lo, hi = _filetime(s["mtime"])
        st.mtime.lo, st.mtime.hi = lo, hi
        return S_OK

    funcs = [_qi_factory([IID_IUnknown, IID_IStream, IID_ISequentialStream]), _addref, _release, read,
             lambda this, pv, cb, pcb: STG_E_ACCESSDENIED, seek, lambda this, n: E_NOTIMPL, lambda *a: E_NOTIMPL,
             lambda this, f: S_OK, lambda this: S_OK, lambda *a: E_NOTIMPL, lambda *a: E_NOTIMPL, stat, lambda this, pp: E_NOTIMPL]
    return _mk_vtbl(protos, funcs)


_STREAM_VT = None


def _make_stream(source, idx, ent):
    global _STREAM_VT
    if _STREAM_VT is None:
        _STREAM_VT = _stream_funcs()
    holder = {"f": None}

    def fh():
        if holder["f"] is None:
            holder["f"] = source.open(idx)
        return holder["f"]

    def on_free():
        f = holder["f"]
        if f is not None:
            try:
                f.close()
            except Exception:                                    # noqa: BLE001
                pass
    return _new(_STREAM_VT, {"fh": fh, "pos": 0, "size": ent.get("size", 0), "mtime": ent.get("mtime", 0), "on_free": on_free})


# ---- IDataObject：整份“要复制的文件”
class _Clip:
    fmt_desc = fmt_contents = fmt_effect = 0


def _data_funcs():
    P = WINFUNCTYPE
    protos = [
        P(HRESULT, c_void_p, c_void_p, POINTER(c_void_p)), P(c_ulong, c_void_p), P(c_ulong, c_void_p),
        P(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM)),                                                       # GetData
        P(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM)),                                                       # GetDataHere
        P(HRESULT, c_void_p, POINTER(FORMATETC)),                                                                           # QueryGetData
        P(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(FORMATETC)),                                                       # GetCanonicalFormatEtc
        P(HRESULT, c_void_p, POINTER(FORMATETC), POINTER(STGMEDIUM), wintypes.BOOL),                                        # SetData
        P(HRESULT, c_void_p, wintypes.DWORD, POINTER(c_void_p)),                                                            # EnumFormatEtc
        P(HRESULT, c_void_p, POINTER(FORMATETC), wintypes.DWORD, c_void_p, POINTER(wintypes.DWORD)),                        # DAdvise
        P(HRESULT, c_void_p, wintypes.DWORD), P(HRESULT, c_void_p, POINTER(c_void_p)),                                      # DUnadvise, EnumDAdvise
    ]
    K = ctypes.WinDLL("kernel32")
    K.GlobalAlloc.restype = wintypes.HGLOBAL
    K.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    K.GlobalLock.restype = c_void_p
    K.GlobalLock.argtypes = [wintypes.HGLOBAL]
    K.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    def hglobal(data):
        h = K.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        p = K.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        K.GlobalUnlock(h)
        return h

    def descriptor(s):
        ents = s["entries"]()
        out = struct.pack("<I", len(ents))
        for e in ents:
            isdir = e.get("isdir")
            flags = FD_ATTRIBUTES | FD_PROGRESSUI | (0 if isdir else (FD_FILESIZE | FD_WRITESTIME))
            lo, hi = _filetime(e.get("mtime"))
            size = int(e.get("size") or 0)
            name = e["name"][:259]
            # FILEDESCRIPTORW：dwFlags, clsid(16), sizel(8), pointl(8), dwFileAttributes, 创建/访问/修改时间(各 8), 大小高/低, 文件名(520)
            out += struct.pack("<I16s8s8sI", flags, b"\0" * 16, b"\0" * 8, b"\0" * 8, FILE_ATTRIBUTE_DIRECTORY if isdir else FILE_ATTRIBUTE_NORMAL)
            out += struct.pack("<II", 0, 0) + struct.pack("<II", 0, 0) + struct.pack("<II", lo, hi)
            out += struct.pack("<II", size >> 32, size & 0xFFFFFFFF)
            out += name.encode("utf-16-le").ljust(520, b"\0")
        return out

    def get_data(this, pfe, pmed):
        s = _st(this)
        fe = pfe.contents
        med = pmed.contents
        ctypes.memset(ctypes.addressof(med), 0, ctypes.sizeof(STGMEDIUM))
        try:
            if fe.cfFormat == _Clip.fmt_desc and fe.tymed & TYMED_HGLOBAL:
                med.tymed, med.u = TYMED_HGLOBAL, hglobal(descriptor(s))
                return S_OK
            if fe.cfFormat == _Clip.fmt_effect and fe.tymed & TYMED_HGLOBAL:
                med.tymed, med.u = TYMED_HGLOBAL, hglobal(struct.pack("<I", 1))            # 复制
                return S_OK
            if fe.cfFormat == _Clip.fmt_contents:
                if not fe.tymed & TYMED_ISTREAM:
                    return DV_E_TYMED
                ents = s["entries"]()
                if not 0 <= fe.lindex < len(ents) or ents[fe.lindex].get("isdir"):
                    return DV_E_LINDEX
                med.tymed, med.u = TYMED_ISTREAM, _make_stream(s["source"], ents[fe.lindex]["idx"], ents[fe.lindex])
                return S_OK
        except Exception:                                                                   # noqa: BLE001
            return E_FAIL
        return DV_E_FORMATETC

    def query(this, pfe):
        fe = pfe.contents
        if fe.cfFormat in (_Clip.fmt_desc, _Clip.fmt_effect) and fe.tymed & TYMED_HGLOBAL:
            return S_OK
        if fe.cfFormat == _Clip.fmt_contents:
            return S_OK if fe.tymed & TYMED_ISTREAM else DV_E_TYMED
        return DV_E_FORMATETC

    shell32 = ctypes.WinDLL("shell32")
    shell32.SHCreateStdEnumFmtEtc.argtypes = [wintypes.UINT, POINTER(FORMATETC), POINTER(c_void_p)]
    shell32.SHCreateStdEnumFmtEtc.restype = HRESULT

    def enum_fmt(this, direction, ppenum):
        if direction != 1:
            return E_NOTIMPL
        arr = (FORMATETC * 3)(
            FORMATETC(_Clip.fmt_desc, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL),
            FORMATETC(_Clip.fmt_contents, None, DVASPECT_CONTENT, -1, TYMED_ISTREAM),
            FORMATETC(_Clip.fmt_effect, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL))
        return shell32.SHCreateStdEnumFmtEtc(3, arr, ppenum)

    funcs = [_qi_factory([IID_IUnknown, IID_IDataObject]), _addref, _release, get_data, lambda *a: E_NOTIMPL, query,
             lambda this, a, b: DATA_S_SAMEFORMATETC, lambda *a: E_NOTIMPL, enum_fmt, lambda *a: OLE_E_ADVISENOTSUPPORTED,
             lambda *a: OLE_E_ADVISENOTSUPPORTED, lambda *a: OLE_E_ADVISENOTSUPPORTED]
    return _mk_vtbl(protos, funcs)


_DATA_VT = None


def _make_dataobject(source, on_lost):
    """把来源整理成条目表（惰性：第一次有人要文件清单时才列目录），返回 IDataObject 的地址。"""
    global _DATA_VT
    if _DATA_VT is None:
        _DATA_VT = _data_funcs()
    cache = {}

    def entries():
        if "e" not in cache:
            ents = []
            for i, e in enumerate(source.list_entries()):
                name = "\\".join(_bad(x) for x in e["rel"].split("/") if x)
                ents.append({"name": name, "size": e.get("size", 0), "mtime": e.get("mtime", 0), "isdir": e.get("isdir", False), "idx": i})
            cache["e"] = ents
        return cache["e"]

    def on_free():
        try:
            source.close()
        finally:
            if on_lost:
                on_lost()
    return _new(_DATA_VT, {"entries": entries, "source": source, "on_free": on_free})


# ------------------------------------------------------------------------------------------ STA 线程
class _Worker:
    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._tid = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def _ensure(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._ready.clear()
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            self._ready.wait(5)

    def _run(self):
        U = ctypes.WinDLL("user32")
        K = ctypes.WinDLL("kernel32")
        O = ctypes.WinDLL("ole32")
        U.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        U.RegisterClipboardFormatW.restype = wintypes.UINT
        U.GetMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        U.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
        U.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
        U.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        O.OleInitialize.argtypes = [c_void_p]
        O.OleSetClipboard.argtypes = [c_void_p]
        O.OleSetClipboard.restype = HRESULT
        O.CoMarshalInterThreadInterfaceInStream.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
        O.CoMarshalInterThreadInterfaceInStream.restype = HRESULT
        self.U, self.O = U, O
        O.OleInitialize(None)
        _Clip.fmt_desc = U.RegisterClipboardFormatW("FileGroupDescriptorW")
        _Clip.fmt_contents = U.RegisterClipboardFormatW("FileContents")
        _Clip.fmt_effect = U.RegisterClipboardFormatW("Preferred DropEffect")
        self._tid = K.GetCurrentThreadId()
        self._ready.set()
        msg = wintypes.MSG()
        while U.GetMessageW(byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_JOB:
                try:
                    self._q.get_nowait()()
                except Exception:                                # noqa: BLE001
                    pass
                continue
            U.TranslateMessage(byref(msg))
            U.DispatchMessageW(byref(msg))

    def post(self, fn):
        """在 STA 线程里执行 fn()，不等结果（拖放会一直占着这条线程直到松开鼠标）。"""
        self._ensure()
        self._q.put(fn)
        for _ in range(20):
            if self.U.PostThreadMessageW(self._tid, WM_APP_JOB, 0, 0):
                return True
            time.sleep(0.05)
        return False

    def run(self, fn, timeout=15):
        """在 STA 线程里执行 fn()，返回它的结果。"""
        self._ensure()
        box, ev = {}, threading.Event()

        def job():
            try:
                box["r"] = fn()
            except Exception as e:                               # noqa: BLE001
                box["e"] = e
            ev.set()
        self._q.put(job)
        for _ in range(20):                                      # 线程消息队列刚建好时可能还收不到，重发几次
            if self.U.PostThreadMessageW(self._tid, WM_APP_JOB, 0, 0):
                break
            time.sleep(0.05)
        if not ev.wait(timeout):
            raise TimeoutError("剪贴板线程没有响应")
        if "e" in box:
            raise box["e"]
        return box["r"]


_worker = _Worker()


def offer(source, on_lost=None):
    """把 source 里的文件放到剪贴板（虚拟文件）。返回 (成功?, 错误文字)。剪贴板被别的内容顶掉时会调 source.close() 和 on_lost。"""
    if sys.platform != "win32":
        return False, "只支持 Windows。"

    def do():
        addr = _make_dataobject(source, on_lost)
        hr = None
        for _ in range(20):                                      # 剪贴板偶尔被别的程序占着
            hr = _worker.O.OleSetClipboard(addr)
            if hr == S_OK:
                break
            time.sleep(0.05)
        _release(addr)                                           # 我们自己那一份引用放掉：之后由剪贴板持有，被顶掉时才释放
        return hr
    try:
        hr = _worker.run(do)
    except Exception as e:                                       # noqa: BLE001
        return False, "放到剪贴板失败：%s" % e
    return (True, "") if hr == S_OK else (False, "剪贴板被别的程序占用了，请再试一次。")


# ------------------------------------------------------------------------------------------ 拖出去（拖放到资源管理器 / 桌面）
_DROP_VT = None


def _drop_source_vtbl():
    P = WINFUNCTYPE
    protos = [P(HRESULT, c_void_p, c_void_p, POINTER(c_void_p)), P(c_ulong, c_void_p), P(c_ulong, c_void_p),
              P(HRESULT, c_void_p, wintypes.BOOL, wintypes.DWORD),                                  # QueryContinueDrag
              P(HRESULT, c_void_p, wintypes.DWORD)]                                                 # GiveFeedback

    def qcd(this, esc, keys):
        if esc:
            return 0x40101                                      # DRAGDROP_S_CANCEL
        if not keys & 1:                                        # 左键松开了
            return 0x40100                                      # DRAGDROP_S_DROP
        return S_OK
    return _mk_vtbl(protos, [_qi_factory([IID_IUnknown, IID_IDropSource]), _addref, _release, qcd, lambda this, eff: 0x40102])      # 0x40102 = 用系统默认光标


def _com_release(ptr):
    """对一个 COM 指针调 IUnknown::Release（它的 vtbl 第 3 项）。"""
    if not ptr:
        return
    vt = ctypes.cast(ptr, POINTER(c_void_p))[0]
    fn = WINFUNCTYPE(c_ulong, c_void_p)(ctypes.cast(vt, POINTER(c_void_p))[2])
    fn(ptr)


def drag(source, ui_invoke, on_done=None):
    """从窗口里把 source 的文件拖出去（左键必须正按着）：放到资源管理器/桌面的那一刻，系统才来读文件内容（和粘贴同一套虚拟文件），
    这时才从服务器读，资源管理器自己弹出复制进度。
    线程安排：DoDragDrop 必须在按下鼠标的那条界面线程上跑（否则抓不到鼠标，拖放卡死——试过在专用线程里直接跑），
    但数据对象放在专用 STA 线程里（先用 CoMarshalInterThreadInterfaceInStream 导出，界面线程再导入成代理），
    这样放下后系统读文件内容的调用落在专用线程，不会拖慢界面。ui_invoke(fn)：把 fn 交给界面线程执行。
    on_done(hr, effect) 在拖放结束时调用（effect: 1=复制，0=没放下）。"""
    if sys.platform != "win32":
        return False, "只支持 Windows。"

    def make():                                                  # 专用线程：建数据对象并导出
        if hasattr(source, "prefetch"):
            source.prefetch()                                    # 同时开始在后台列文件清单
        pstm = c_void_p()
        data = None
        try:
            data = _make_dataobject(source, None)
            hr = _worker.O.CoMarshalInterThreadInterfaceInStream(byref(IID_IDataObject), data, byref(pstm))
            if hr != S_OK:
                raise OSError("导出数据对象失败 0x%08X" % (hr & 0xFFFFFFFF))
        except Exception as e:                                   # noqa: BLE001
            if on_done:
                on_done(e, 0)
            return
        finally:
            if data:
                _release(data)                                   # 我们自己那份引用放掉，导出的流里有一份

        def ui():                                                # 界面线程：导入成代理，开始拖放
            global _DROP_VT
            if _DROP_VT is None:
                _DROP_VT = _drop_source_vtbl()
            O = ctypes.WinDLL("ole32")
            O.CoGetInterfaceAndReleaseStream.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
            O.CoGetInterfaceAndReleaseStream.restype = HRESULT
            O.DoDragDrop.argtypes = [c_void_p, c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD)]
            O.DoDragDrop.restype = HRESULT
            pdata = c_void_p()
            ds = None
            eff = wintypes.DWORD(0)
            hr = None
            try:
                hr = O.CoGetInterfaceAndReleaseStream(pstm, byref(IID_IDataObject), byref(pdata))
                if hr == S_OK:
                    ds = _new(_DROP_VT, {"on_free": lambda: None})
                    hr = O.DoDragDrop(pdata, ds, 1, byref(eff))
            finally:
                if ds:
                    _release(ds)
                _com_release(pdata.value)
                if on_done:
                    try:
                        on_done(hr, eff.value)
                    except Exception:                            # noqa: BLE001
                        pass
        try:
            ui_invoke(ui)
        except Exception as e:                                   # noqa: BLE001
            if on_done:
                on_done(e, 0)
    try:
        return (True, "") if _worker.post(make) else (False, "拖放线程没有响应。")
    except Exception as e:                                       # noqa: BLE001
        return False, "发起拖放失败：%s" % e
