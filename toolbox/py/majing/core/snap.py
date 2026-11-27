"""拖动窗口到屏幕边缘时的“贴边”半透明预览框（Win11 Snap 的样子）：一个点击穿透、不抢焦点的分层窗口。
必须在创建它的线程里 show/hide/pump（拖动循环线程），窗口过程直接用系统默认的，底色由窗口类的画刷画。"""
import ctypes
import sys
from ctypes import wintypes

from majing.tray import WNDCLASSW, WNDPROC, _u

_CLASS = "MajingSnapPreview"
_registered = False


class Overlay:
    def __init__(self):
        self.hwnd = None
        self.shown = None

    def _create(self):
        global _registered
        u = _u()
        gdi = ctypes.windll.gdi32
        gdi.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi.CreateSolidBrush.argtypes = [wintypes.DWORD]
        if not _registered:
            wc = WNDCLASSW()
            wc.lpfnWndProc = WNDPROC(("DefWindowProcW", ctypes.windll.user32))
            wc.lpszClassName = _CLASS
            wc.hbrBackground = gdi.CreateSolidBrush(0x00DC9650)              # BGR：偏蓝的灰蓝色 #5096DC
            u.RegisterClassW(ctypes.byref(wc))
            _registered = True
        # WS_EX_LAYERED | TOOLWINDOW | TRANSPARENT（点击穿透）| TOPMOST | NOACTIVATE；WS_POPUP
        self.hwnd = u.CreateWindowExW(0x00080000 | 0x80 | 0x20 | 0x8 | 0x08000000, _CLASS, "", 0x80000000, 0, 0, 10, 10, None, None, None, None)
        if self.hwnd:
            u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
            u.SetLayeredWindowAttributes(self.hwnd, 0, 90, 2)                  # LWA_ALPHA：约 35% 不透明
            try:                                                               # Win11：圆角
                ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception:                                                  # noqa: BLE001
                pass

    def show(self, rect):
        """rect = (左, 上, 右, 下) 物理像素。"""
        if sys.platform != "win32" or rect == self.shown:
            return
        u = _u()
        if not self.hwnd:
            self._create()
        if not self.hwnd:
            return
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], 0x0010 | 0x0040)   # HWND_TOPMOST；NOACTIVATE|SHOWWINDOW
        self.shown = rect

    def hide(self):
        if self.hwnd and self.shown is not None:
            u = _u()
            u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            u.ShowWindow(self.hwnd, 0)
        self.shown = None

    def pump(self):
        if not self.hwnd:
            return
        u = _u()
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        msg = wintypes.MSG()
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        if self.hwnd:
            u = _u()
            u.DestroyWindow.argtypes = [wintypes.HWND]
            u.DestroyWindow(self.hwnd)
            self.hwnd = None
        self.shown = None
