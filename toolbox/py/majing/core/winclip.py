"""Windows 剪贴板：把本机的一组文件/文件夹放成“文件”剪贴板（CF_HDROP），之后在资源管理器、桌面里 Ctrl+V 就是粘贴出这些文件。
工具箱里“复制服务器上的文件”就是先下载到临时目录，再用这里放上剪贴板。"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes

CF_HDROP = 15
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
DROPEFFECT_COPY = 1


def set_files(paths):
    """返回 (成功?, 错误文字)。paths 要是绝对路径。"""
    if sys.platform != "win32":
        return False, "只支持 Windows。"
    paths = [p for p in paths if p]
    if not paths:
        return False, "没有文件。"
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u.RegisterClipboardFormatW.restype = wintypes.UINT
    u.CreateWindowExA.restype = wintypes.HWND
    u.CreateWindowExA.argtypes = [wintypes.DWORD, wintypes.LPCSTR, wintypes.LPCSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.DestroyWindow.argtypes = [wintypes.HWND]

    def blob(data):
        h = k.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
        if not h:
            raise OSError("申请内存失败")
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        return h

    # DROPFILES：pFiles=20、pt=(0,0)、fNC=0、fWide=1，后面是以 \0 分隔、\0\0 结尾的 UTF-16 路径
    drop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + ("\0".join(paths) + "\0\0").encode("utf-16-le")
    # 不用 NULL 窗口：NULL 属主时 EmptyClipboard 之后 SetClipboardData 会失败，所以像 pyperclip 一样建一个临时的隐形窗口
    hwnd = u.CreateWindowExA(0, b"STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        for _ in range(20):                       # 剪贴板偶尔被别的程序占着，等一下再试
            if u.OpenClipboard(hwnd):
                break
            time.sleep(0.05)
        else:
            return False, "剪贴板被别的程序占用了，请再试一次。"
        try:
            u.EmptyClipboard()
            h1 = blob(drop)
            if not u.SetClipboardData(CF_HDROP, h1):
                k.GlobalFree(h1)
                return False, "放到剪贴板失败。"
            fmt = u.RegisterClipboardFormatW("Preferred DropEffect")      # 告诉资源管理器粘贴时是“复制”，不是“移动”
            h2 = blob(struct.pack("<I", DROPEFFECT_COPY))
            if not u.SetClipboardData(fmt, h2):
                k.GlobalFree(h2)
            return True, ""
        finally:
            u.CloseClipboard()
    except Exception as e:                        # noqa: BLE001
        return False, "放到剪贴板失败：%s" % e
    finally:
        if hwnd:
            u.DestroyWindow(hwnd)

