"""系统托盘图标 + 单实例（纯 ctypes，不加依赖）。
关闭窗口只是把窗口藏起来、缩到托盘；托盘里左键/“打开”把窗口叫回来，右键“退出”才真退出。
单实例：再次启动时发现已经有一个（可能正藏在托盘里），就把它叫出来，自己退出。"""
import ctypes
import hashlib
import os
import sys
import threading
from ctypes import wintypes

WM_USER = 0x0400
WM_TRAY = WM_USER + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
WM_DESTROY, WM_NULL, WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0002, 0x0000, 0x0202, 0x0205, 0x007B
CMD_OPEN, CMD_QUIT = 1, 2
CLASS_NAME = "MajingToolboxTray"
ERROR_ALREADY_EXISTS = 183

_mutex = None                       # 互斥量句柄要一直拿着，进程结束才放
_tray = None


class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uTimeout", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", _GUID), ("hBalloonIcon", wintypes.HICON)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _u():
    u = ctypes.windll.user32
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.RegisterWindowMessageW.restype = wintypes.UINT
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    u.LoadImageW.restype = wintypes.HANDLE
    u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.LoadIconW.restype = wintypes.HICON
    u.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    return u


# ------------------------------------------------------------------ 单实例
def instance_key(app_dir):
    """同一份安装/同一份源码 + 同一个数据目录算同一个实例（测试时把 APPDATA 指到临时目录就互不干扰；安装版和源码版也互不干扰）。"""
    raw = "%s|%s" % (os.path.abspath(os.environ.get("APPDATA", "")), os.path.abspath(sys.executable if getattr(sys, "frozen", False) else app_dir))
    return hashlib.sha1(raw.lower().encode("utf-8", "replace")).hexdigest()[:12]


def acquire(key, wait=0):
    """抢单实例互斥量。wait>0：已有实例时最多等这么多秒（更新后重启，旧进程马上退出）。抢到返回 True。"""
    global _mutex
    if sys.platform != "win32":
        return True
    import time
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    deadline = time.time() + wait
    while True:
        h = k.CreateMutexW(None, False, "Local\\MajingToolbox-" + key)
        err = ctypes.get_last_error()                                       # 紧跟在调用后面读，中间不能再调别的 Win32
        if h and err != ERROR_ALREADY_EXISTS:
            _mutex = h
            return True
        if h:
            k.CloseHandle(h)
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def release():
    """退出流程一开始就调用：放开单实例互斥量、摘掉托盘图标并销毁托盘窗口。
    之后哪怕这个进程还要花几秒收尾，重新点开的新实例也能直接起来，不会被“旧实例还在”挡住。"""
    global _mutex
    if sys.platform != "win32":
        return
    remove()
    t = _tray
    if t is not None and t.hwnd:
        try:
            u = _u()
            u.PostMessageW(t.hwnd, 0x0010, 0, 0)                          # WM_CLOSE → DefWindowProc 销毁窗口 → WM_DESTROY → 托盘线程退出
        except Exception:                                                  # noqa: BLE001
            pass
    if _mutex:
        try:
            k = ctypes.WinDLL("kernel32")
            k.CloseHandle.argtypes = [wintypes.HANDLE]
            k.CloseHandle(_mutex)
        except Exception:                                                  # noqa: BLE001
            pass
        _mutex = None


def signal_existing(key):
    """叫已经在跑的那个实例把窗口显示出来（它可能正藏在托盘里）。"""
    if sys.platform != "win32":
        return False
    u = _u()
    hwnd = u.FindWindowW(CLASS_NAME, "%s-%s" % (CLASS_NAME, key))
    if not hwnd:
        return False
    ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)      # ASFW_ANY：让已有的那个实例有权把窗口提到最前
    u.PostMessageW(hwnd, u.RegisterWindowMessageW("MajingToolbox.Show"), 0, 0)
    return True


# ------------------------------------------------------------------ 托盘
class Tray:
    def __init__(self, key, tip, icon_path, on_open, on_quit):
        self.key, self.tip, self.icon_path = key, tip, icon_path
        self.on_open, self.on_quit = on_open, on_quit
        self.hwnd = None
        self._nid = None
        self._proc = WNDPROC(self._wndproc)          # 留着引用别被回收
        self._ready = threading.Event()
        self._added = False

    def start(self):
        global _tray
        _tray = self
        threading.Thread(target=self._run, daemon=True, name="tray").start()
        self._ready.wait(5)

    def _icon(self, u):
        h = None
        if self.icon_path and os.path.exists(self.icon_path):
            cx = ctypes.windll.user32.GetSystemMetrics(49)               # SM_CXSMICON：托盘图标的尺寸（随缩放）
            h = u.LoadImageW(None, self.icon_path, 1, cx, cx, 0x10)       # IMAGE_ICON | LR_LOADFROMFILE
        return h or u.LoadIconW(None, ctypes.c_void_p(32512))             # 没有就用系统默认图标

    def _data(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID = self.hwnd, 1
        return nid

    def _add(self):
        u = _u()
        nid = self._data()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon(u)
        nid.szTip = self.tip[:127]
        self._nid = nid
        self._added = bool(ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

    def _run(self):
        u = _u()
        self._show_msg = u.RegisterWindowMessageW("MajingToolbox.Show")
        self._created_msg = u.RegisterWindowMessageW("TaskbarCreated")      # 资源管理器重启后图标会丢，收到这个消息要重新加
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.lpszClassName = CLASS_NAME
        u.RegisterClassW(ctypes.byref(wc))
        # 不用 HWND_MESSAGE 窗口：它收不到 TaskbarCreated 这种广播
        self.hwnd = u.CreateWindowExW(0, CLASS_NAME, "%s-%s" % (CLASS_NAME, self.key), 0, 0, 0, 0, 0, None, None, None, None)
        self._add()
        self._ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wp, lp):
        u = ctypes.windll.user32
        try:
            if msg == WM_TRAY:
                ev = lp & 0xFFFF
                if ev == WM_LBUTTONUP:
                    threading.Thread(target=self.on_open, daemon=True).start()
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu(hwnd)
                return 0
            if msg == getattr(self, "_show_msg", -1):                      # 第二次启动让我们把窗口叫出来
                threading.Thread(target=self.on_open, daemon=True).start()
                return 0
            if msg == getattr(self, "_created_msg", -1):
                self._add()
                return 0
            if msg == WM_DESTROY:
                u.PostQuitMessage(0)
                return 0
        except Exception:                                                  # noqa: BLE001  回调里别抛异常
            pass
        return u.DefWindowProcW(hwnd, msg, wp, lp)

    def _menu(self, hwnd):
        u = _u()
        pt = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        m = u.CreatePopupMenu()
        u.AppendMenuW(m, 0, CMD_OPEN, "打开码境工具箱")
        u.AppendMenuW(m, 0x800, 0, None)                                   # 分隔线
        u.AppendMenuW(m, 0, CMD_QUIT, "退出")
        u.SetMenuDefaultItem(m, CMD_OPEN, 0)
        u.SetForegroundWindow(hwnd)                                        # 不先置前台的话，点菜单外面菜单不会自己收起来
        cmd = u.TrackPopupMenu(m, 0x0100 | 0x0002 | 0x0020, pt.x, pt.y, 0, hwnd, None)   # RETURNCMD | RIGHTBUTTON | BOTTOMALIGN
        u.PostMessageW(hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(m)
        if cmd == CMD_OPEN:
            threading.Thread(target=self.on_open, daemon=True).start()
        elif cmd == CMD_QUIT:
            threading.Thread(target=self.on_quit, daemon=True).start()     # 退出可能要弹确认框，别堵住托盘的消息循环

    def balloon(self, title, text):
        """托盘气泡提示。"""
        if not self._added or self._nid is None:
            return
        nid = self._data()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self):
        """摘掉托盘图标（从任何线程调用都行；os._exit 之前也要调，不然图标会残留到鼠标扫过）。"""
        if self._added and self._nid is not None:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._added = False


def remove():
    """没有启动托盘时调用也安全。"""
    if _tray is not None:
        try:
            _tray.remove()
        except Exception:                                                  # noqa: BLE001
            pass
