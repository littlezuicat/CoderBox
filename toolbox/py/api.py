# -*- coding: utf-8 -*-
"""前端（React）能调用的全部后端功能。pywebview 会把本类的公开方法暴露成 window.pywebview.api.<方法>；
以下划线开头的是内部实现，不会暴露。后端 → 前端的推送统一走 emit(type, data) → window.__emit(type, data)。"""
import json
import os
import subprocess
import sys
import threading
import time

from majing import APP_VERSION, history, installer
from majing.core import account, clashfix, devsec, ffsetup, gpumon, media, ppt_engine, sshhosts, sshserver, updater, vscserver, vsync
from majing.core import vault as vault_mod
from majing.core.vault import VaultError, vault
from majing.core.remote_agent import RemoteAgent
from majing.settings import settings

import logging
ulog = logging.getLogger("majing.update")


def _reveal(path):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


def _system_desktop():
    """系统的“桌面”文件夹（Windows 上可能被挪到别的盘或 OneDrive 里，所以问系统要，不拼路径）。"""
    d = installer.desktop_dir()
    return d if d and os.path.isdir(d) else os.path.expanduser("~")


def _system_downloads():
    """系统的“下载”文件夹（保留备用）。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
            g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7D))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def _unique_out(src, ext, used, out_dir=""):
    base = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0]) if out_dir else os.path.splitext(src)[0]
    p = "%s.%s" % (base, ext)
    k = 2
    while os.path.exists(p) or p in used or os.path.normcase(p) == os.path.normcase(src):
        p = "%s (%d).%s" % (base, k, ext)
        k += 1
    used.add(p)
    return p


_MI = None


def _monitorinfo_cls():
    """MONITORINFO 结构体只定义一次：user32 的函数对象是全局共用的，各处各定义一个同名类再给 argtypes 赋值会互相覆盖，调用就报参数类型错。"""
    global _MI
    if _MI is None:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        _MI = MONITORINFO
    return _MI


class Api:
    def __init__(self):
        self._window = None
        self._emit_hook = None            # 测试时可替换：收集事件
        self._busy = {}                   # 名称 -> 提示文字；有任务在跑就非空
        self._vsc_auto = {}               # 主机别名 -> {ok, t}：自动安装 VS Code Server 的结果（失败 30 分钟后才重试）
        self._vsc_lock = threading.Lock()  # 一次只给一台主机装
        sshhosts.on_session = self._auto_vsc
        self._ppt_stop = False
        self._cv_job = None
        self._cv_stop = False
        self.mode = "app"                  # app / installer / uninstaller，由 main.py 按启动方式决定
        self._ssh_stop = False
        self._share = sshserver.ShareServer(on_change=lambda i: self._emit("share:state", i))
        sshhosts.on_route = lambda alias, info: self._emit("ssh:route", {"alias": alias, **info})       # 长连接自动换到优先级更高的地址
        self._agent = RemoteAgent()
        self._agent.on_event = lambda ev: self._emit("remote:event", ev)
        self._update_pending = None
        self._upd_lock = threading.Lock()                 # 同一时间只允许一轮更新（检查+下载）
        self._acct_code = None
        self._made = set()                # 这个会话里转换生成的输出文件（重新转换时只允许删这些）
        self._dragging = False            # 正在把输出文件拖出窗口
        self._drag_end = 0.0

    # ------------------------------------------------------------------ 内部
    def log_js(self, level, msg):
        """前端把 JS 报错/警告交给后端写日志（源码版看 logs\debug.log）。"""
        import logging
        logging.getLogger("majing.js").log(logging.ERROR if level == "error" else logging.WARNING, "%s", str(msg)[:2000])
        return True

    def _set_window(self, w):
        self._window = w

    def _emit(self, typ, data=None):
        if self._emit_hook:
            self._emit_hook(typ, data)
            return
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js("window.__emit && window.__emit(%s, %s)" % (json.dumps(typ), json.dumps(data, ensure_ascii=False)))
        except Exception:
            pass

    def _thread(self, fn, *a):
        t = threading.Thread(target=fn, args=a, daemon=True)
        t.start()
        return t

    def _start_background(self):
        """窗口加载完成后调用：自动更新。（旧的“设备 ID 远程连接”组件不再随工具箱启动，被连功能改为 SSH 管理里的“共享本机 SSH”。）"""
        self._thread(self._update_loop)
        self._thread(self._vsync_loop)
        gpumon.monitor.start(self._emit)             # GPU 采样只在界面要求时做（gpu_sample_now），这里只记下事件推送函数

    def _vsync_loop(self):
        """开了密码同步就每 3 分钟同步一次（浏览器扩展保存的新密码、别的电脑的修改都靠它带过去/带回来）。"""
        time.sleep(20)
        while True:
            try:
                if vsync.status()["enabled"] and vsync.status()["account"]:
                    self._vsync_run()
            except Exception:                            # noqa: BLE001
                pass
            time.sleep(180)

    def _shutdown(self):
        try:
            vault_mod.clear_clipboard_if_ours()          # 退出时剪贴板里还留着复制的密码就清掉
        except Exception:                                # noqa: BLE001
            pass
        self._share.stop("工具箱已退出")
        self._agent.stop()

    # ------------------------------------------------------------------ 通用
    def app_info(self):
        return {"version": APP_VERSION, "platform": sys.platform, "settings": settings.data, "mode": self.mode,
                "installed": installer.is_installed_run(), "remote": {}}

    # ------------------------------------------------------------------ 安装 / 卸载面板
    def installer_state(self):
        return {"mode": self.mode, "version": APP_VERSION, "default_dir": installer.default_dir(), "existing": installer.existing_install()}

    def installer_pick_dir(self, cur=""):
        import webview
        dlg = getattr(webview, "FileDialog", None)
        mode = dlg.FOLDER if dlg else webview.FOLDER_DIALOG
        start = cur if cur and os.path.isdir(cur) else os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else os.path.expanduser("~")
        r = self._window.create_file_dialog(mode, directory=start)
        if not r:
            return None
        d = r if isinstance(r, str) else r[0]
        return d if os.path.basename(d).lower() == "claudetoolbox" else os.path.join(d, installer.APP_ID)     # 选了一个已有文件夹就在里面建专用子目录，别把文件散在别人的目录里

    def installer_run(self, opts):
        def run():
            r = installer.install(dict(opts), lambda p, t: self._emit("inst:progress", {"pct": p, "text": t}))
            self._emit("inst:done", r)
        self._thread(run)
        return True

    def uninstall_run(self, opts):
        def run():
            r = installer.uninstall(dict(opts), lambda p, t: self._emit("inst:progress", {"pct": p, "text": t}))
            self._emit("inst:done", r)
        self._thread(run)
        return True

    def installer_launch(self, exe):
        installer.launch(exe)
        return True

    def installer_exit(self):
        try:
            self._window.destroy()
        except Exception:
            os._exit(0)
        return True

    # ------------------------------------------------------------------ 下载位置
    def download_dir(self):
        """所有输出（PPT 定图、格式转换、SSH 下载、导出密钥）默认存到这里：设置里改过就用设置的，否则是桌面。"""
        d = settings.get("download_dir", "") or ""
        if d:
            try:
                os.makedirs(d, exist_ok=True)
                return d
            except OSError:
                pass
        return _system_desktop()

    def download_dir_info(self):
        d = self.download_dir()
        return {"path": d, "custom": bool(settings.get("download_dir", ""))}

    def download_dir_pick(self):
        import webview
        dlg = getattr(webview, "FileDialog", None)
        mode = dlg.FOLDER if dlg else webview.FOLDER_DIALOG
        r = self._window.create_file_dialog(mode, directory=self.download_dir())
        if not r:
            return self.download_dir_info()
        settings.set("download_dir", r if isinstance(r, str) else r[0])
        return self.download_dir_info()

    def download_dir_reset(self):
        settings.set("download_dir", "")
        return self.download_dir_info()

    def settings_set(self, key, value):
        settings.set(key, value)
        return True

    def pick_files(self, kind="any"):
        import webview
        types = {"ppt": ("演示文稿 (*.pptx;*.ppt;*.pptm;*.ppsx;*.pps;*.potx;*.pot;*.odp;*.dps;*.dpt)", "所有文件 (*.*)"),
                 "media": ("音视频和图片 (*.*)",), "any": ("所有文件 (*.*)",)}.get(kind, ("所有文件 (*.*)",))
        dlg = getattr(webview, "FileDialog", None)
        mode = dlg.OPEN if dlg else webview.OPEN_DIALOG
        r = self._window.create_file_dialog(mode, directory=settings.get("last_dir", ""), allow_multiple=True, file_types=types)
        files = list(r or [])
        if files:
            settings.set("last_dir", os.path.dirname(files[0]))
        return files

    def pick_folder(self):
        import webview
        dlg = getattr(webview, "FileDialog", None)
        mode = dlg.FOLDER if dlg else webview.FOLDER_DIALOG
        r = self._window.create_file_dialog(mode, directory=self.download_dir())
        return r[0] if r else None

    def open_path(self, path):
        """在资源管理器里打开一个文件夹。"""
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except OSError:
            return False

    def reveal(self, path):
        _reveal(path)
        return True

    def open_url(self, url):
        import webbrowser
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        return True

    def file_info(self, paths, kind="any"):
        """把路径变成 [{path,name,size,kind}]；文件夹展开一层（快传里递归）。kind: ppt / media / any"""
        out = []

        def add(p, recurse=False):
            if os.path.isdir(p):
                if recurse:
                    for root, _d, fs in os.walk(p):
                        for f in sorted(fs):
                            add(os.path.join(root, f))
                else:
                    for f in sorted(os.listdir(p)):
                        fp = os.path.join(p, f)
                        if os.path.isfile(fp):
                            add(fp)
                return
            if not os.path.isfile(p) or os.path.basename(p).startswith("~$"):
                return
            k = None
            if kind == "ppt":
                if os.path.splitext(p)[1].lower() not in ppt_engine.PPT_EXTS:
                    return
                k = "ppt"
            elif kind == "media":
                k = media.kind_of(p)
                if not k:
                    return
            out.append({"path": p, "name": os.path.basename(p), "size": os.path.getsize(p), "kind": k or "file"})
        for p in paths:
            add(p, recurse=(kind == "any"))
        return out

    def busy_text(self):
        t = [v for v in self._busy.values() if v]
        if self._share.sessions:
            t.append("有 %d 个人正通过 SSH 连着这台电脑" % len(self._share.sessions))
        return t

    # ------------------------------------------------------------------ 无标题栏窗口（顶部功能栏当标题栏用）
    def _hwnd(self):
        """本进程自己的主窗口句柄。不能按标题全局找（FindWindow）：电脑上同时开着别的实例（比如用户正在用的那个）时会操作到别人的窗口。"""
        import ctypes
        from ctypes import wintypes
        from majing import APP_NAME
        u = ctypes.windll.user32
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        me, found = os.getpid(), []
        CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == me and u.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(256)
                u.GetWindowTextW(h, buf, 256)
                if buf.value == APP_NAME:
                    found.append(h)
            return True
        u.EnumWindows(CB(cb), 0)
        if found:
            return found[0]
        try:                                                 # 窗口还藏着（启动时先藏着、页面画好再显示）：EnumWindows 只认可见窗口，直接用窗体自己的句柄
            return int(self._window.native.Handle.ToInt64())
        except Exception:                                    # noqa: BLE001
            return None

    def _install_nc_hook(self, hwnd):
        """子类化窗口过程，做“客户区铺满整个窗口、顶栏当标题栏”的自绘标题栏：
        - 保留 WS_CAPTION 等样式：Windows 仍把它当有标题栏的窗口（拖动、贴边、贴靠布局都是原生的）。
        - WM_NCCALCSIZE：客户区从窗口最顶端（留几个像素当上边缘缩放把手）开始，盖住标题栏；最大化时从屏幕顶开始。
        - 网页的 WebView2 子窗口盖住整个客户区，系统拿不到右上角的鼠标命中，所以给它设“挖掉右上角三个按钮”的窗口区域（SetWindowRgn），
          按钮自己用 GDI 画（Segoe Fluent Icons 字形），命中测试返回系统的 HTMINBUTTON/HTMAXBUTTON/HTCLOSE，
          于是悬停最大化按钮时 Win11 会弹出原生“贴靠布局”浮层。（DWM 不会替我们画按钮：客户区盖住标题栏后试过，没有。）"""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32

        class NCSP(ctypes.Structure):
            _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.IsZoomed.argtypes = [wintypes.HWND]
        class TME(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]
        u.TrackMouseEvent.argtypes = [ctypes.POINTER(TME)]
        u.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        old = u.GetWindowLongPtrW(hwnd, -4)

        class MMI(ctypes.Structure):
            _fields_ = [("ptReserved", wintypes.POINT), ("ptMaxSize", wintypes.POINT), ("ptMaxPosition", wintypes.POINT), ("ptMinTrackSize", wintypes.POINT), ("ptMaxTrackSize", wintypes.POINT)]

        MONITORINFO = _monitorinfo_cls()
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HANDLE
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._frame_px = 10

        def proc(h, msg, wp, lp):
            if not getattr(self, "_nc_on", False):
                return u.CallWindowProcW(old, h, msg, wp, lp)
            # 标题栏三个按钮（最小化/最大化/关闭）是我们自己画的，但命中测试按系统标题栏按钮返回（HTMINBUTTON/HTMAXBUTTON/HTCLOSE）：
            # Win11 据此在鼠标悬停最大化按钮时弹出“贴靠布局”浮层；点击/悬停/按下的状态自己管
            if msg == 0x0084:                                                              # WM_NCHITTEST
                r = u.CallWindowProcW(old, h, msg, wp, lp)
                hole = getattr(self, "_hole", None)
                if r == 1 and hole:
                    pt = wintypes.POINT(ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value)
                    u.ScreenToClient(h, ctypes.byref(pt))
                    if hole[0] <= pt.x < hole[2] and hole[1] <= pt.y < hole[3]:
                        return (8, 9, 20)[min(2, (pt.x - hole[0]) * 3 // max(1, hole[2] - hole[0]))]
                    bl = getattr(self, "_blank_hole", None)
                    if bl and bl[0] <= pt.x < bl[2] and bl[1] <= pt.y < bl[3]:
                        return 2                                                           # HTCAPTION：真正的系统标题栏拖动（贴边、顶端布局条、双击最大化、右键系统菜单）
                return r
            if msg == 0x00A0:                                                              # WM_NCMOUSEMOVE
                code = wp if wp in (8, 9, 20) else 0
                if code != getattr(self, "_cap_hover", 0):
                    self._cap_hover = code
                    self._paint_caption(h)
                    if code:
                        tme = TME(ctypes.sizeof(TME), 0x2 | 0x10, h, 0)                    # TME_LEAVE | TME_NONCLIENT：鼠标移出才会收到 WM_NCMOUSELEAVE
                        u.TrackMouseEvent(ctypes.byref(tme))
            elif msg == 0x02A2:                                                            # WM_NCMOUSELEAVE
                if getattr(self, "_cap_hover", 0) or getattr(self, "_cap_press", 0):
                    self._cap_hover = self._cap_press = 0
                    self._paint_caption(h)
            elif msg == 0x00A1 and wp in (8, 9, 20):                                       # WM_NCLBUTTONDOWN：吞掉（系统没有真的按钮），松开时才执行
                self._cap_press = wp
                self._paint_caption(h)
                return 0
            elif msg == 0x00A2 and wp in (8, 9, 20):                                       # WM_NCLBUTTONUP
                pressed, self._cap_press = getattr(self, "_cap_press", 0), 0
                self._paint_caption(h)
                if pressed == wp:
                    self._thread(lambda: self.win_cmd({8: "min", 9: "toggle", 20: "close"}[wp]))
                return 0
            elif msg == 0x000F:                                                            # WM_PAINT：系统画完后在挖开的区域上画按钮
                r = u.CallWindowProcW(old, h, msg, wp, lp)
                self._paint_caption(h)
                return r
            if msg == 0x0083 and wp:                                                        # WM_NCCALCSIZE（wParam=TRUE）
                prm = ctypes.cast(lp, ctypes.POINTER(NCSP)).contents
                top, left = prm.rgrc[0].top, prm.rgrc[0].left
                r = u.CallWindowProcW(old, h, msg, wp, lp)
                if u.IsZoomed(h):
                    prm.rgrc[0].top = top + (prm.rgrc[0].left - left)                       # 最大化：窗口比屏幕大一圈边框，客户区从屏幕顶开始（不留标题栏）
                else:
                    prm.rgrc[0].top = top + self._top_grip(h)                               # 盖住标题栏，只留几像素当上边缘缩放把手
                return r
            if msg == 0x0024:                                                              # WM_GETMINMAXINFO：系统最大化时占满“工作区”，不盖任务栏
                r = u.CallWindowProcW(old, h, msg, wp, lp)
                try:
                    mm = ctypes.cast(lp, ctypes.POINTER(MMI)).contents
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    u.GetMonitorInfoW(u.MonitorFromWindow(h, 2), ctypes.byref(mi))
                    if not u.IsZoomed(h):                                                  # 最大化前量一下系统给这扇窗留的边框宽度（随缩放变）
                        wr, pt = wintypes.RECT(), wintypes.POINT(0, 0)
                        u.GetWindowRect(h, ctypes.byref(wr))
                        u.ClientToScreen(h, ctypes.byref(pt))
                        if 0 < pt.x - wr.left < 40:
                            self._frame_px = pt.x - wr.left
                    f, w = self._frame_px, mi.rcWork
                    mm.ptMaxPosition.x, mm.ptMaxPosition.y = w.left - mi.rcMonitor.left - f, w.top - mi.rcMonitor.top - f
                    mm.ptMaxSize.x, mm.ptMaxSize.y = w.right - w.left + 2 * f, w.bottom - w.top + 2 * f
                    mm.ptMaxTrackSize.x, mm.ptMaxTrackSize.y = mm.ptMaxSize.x, mm.ptMaxSize.y
                except Exception:                                                          # noqa: BLE001
                    pass
                return r
            if msg in (0x0047, 0x0005, 0x02E0):                                            # WM_WINDOWPOSCHANGED / WM_SIZE / WM_DPICHANGED：窗口变了，重新挖按钮区
                r = u.CallWindowProcW(old, h, msg, wp, lp)
                self._apply_caption_hole(h)
                return r
            return u.CallWindowProcW(old, h, msg, wp, lp)
        cb = WNDPROC(proc)
        self._nc_hook = cb                              # 留着引用，别被回收
        u.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p).value)

    def _apply_caption_hole(self, hwnd):
        """给网页控件设窗口区域：整个控件减去右上角三个按钮的矩形（46×46 DIP 一个），露出下面的窗体，按钮由 _paint_caption 画。返回按钮区宽度（物理像素）。"""
        import ctypes
        from ctypes import wintypes
        if not getattr(self, "_nc_on", False):
            return 0
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        try:
            wv = int(self._window.native.webview.Handle.ToInt64())
        except Exception:                                  # noqa: BLE001
            return 0
        u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.restype = wintypes.UINT
        g.CreateRectRgn.restype = wintypes.HANDLE
        g.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        g.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
        g.DeleteObject.argtypes = [wintypes.HANDLE]
        cr = wintypes.RECT()
        if not u.GetClientRect(wv, ctypes.byref(cr)) or cr.right < 300:
            return 0
        bw = int(round(46 * (u.GetDpiForWindow(hwnd) or 96) / 96.0))
        hole = (cr.right - 3 * bw, 0, cr.right, bw)
        full = g.CreateRectRgn(0, 0, cr.right, cr.bottom)
        cut = g.CreateRectRgn(*hole)
        g.CombineRgn(full, full, cut, 4)                                                    # RGN_DIFF
        g.DeleteObject(cut)
        self._blank_hole = None
        bk = getattr(self, "_blank", None)                                                  # 网页报来的顶栏空白区（导航和版本号之间）：也挖掉，让系统把它当真正的标题栏
        if bk and bk[2] - bk[0] > 8 and bk[3] > bk[1]:
            bl = (max(0, bk[0]), max(0, bk[1]), min(hole[0], bk[2]), min(cr.bottom, bk[3]))
            if bl[2] - bl[0] > 8:
                cut = g.CreateRectRgn(*bl)
                g.CombineRgn(full, full, cut, 4)
                g.DeleteObject(cut)
                self._blank_hole = bl
        u.SetWindowRgn(wv, full, True)                                                      # 系统接管 full，不要再 DeleteObject
        self._hole = hole
        self._repaint_webview()
        return 3 * bw

    def _repaint_webview(self):
        """改了窗口区域或顶栏底色之后，强制网页控件整块重画。不然顶上那一截可能还是旧画面（比如弹窗的遮罩没盖上去）。"""
        try:
            import ctypes
            from ctypes import wintypes
            from System import Action
            form = self._window.native
            wv = int(form.webview.Handle.ToInt64())
            u = ctypes.windll.user32
            u.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.HANDLE, wintypes.UINT]
            u.RedrawWindow.restype = wintypes.BOOL
            # RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW；在界面线程里做（跨线程直接发消息容易卡住）
            form.Invoke(Action(lambda: u.RedrawWindow(wv, None, None, 0x0001 | 0x0080 | 0x0100)))
        except Exception:                                  # noqa: BLE001
            pass

    def _paint_caption(self, hwnd):
        """在挖开的区域里画 最小化/最大化(还原)/关闭 三个按钮（Segoe Fluent Icons 字形，和系统按钮一样的图标），悬停/按下有底色，关闭悬停红底。"""
        hole = getattr(self, "_hole", None)
        if not hole or not getattr(self, "_nc_on", False):
            return
        import ctypes
        from ctypes import wintypes
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        try:
            u.GetDC.argtypes = [wintypes.HWND]
            u.GetDC.restype = wintypes.HDC
            u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
            u.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
            u.IsZoomed.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.restype = wintypes.UINT
            g.CreateSolidBrush.restype = wintypes.HBRUSH
            g.CreateSolidBrush.argtypes = [wintypes.DWORD]
            g.CreateFontW.restype = wintypes.HFONT
            g.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
            g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
            g.SelectObject.restype = wintypes.HANDLE
            g.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
            g.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
            g.DeleteObject.argtypes = [wintypes.HANDLE]

            def rgb(r, gg, b):
                return r | (gg << 8) | (b << 16)
            dark = getattr(self, "_cap_dark", False)
            bg = rgb(*self._cap_bg())
            hov = rgb(63, 65, 77) if dark else rgb(230, 230, 230)
            prs = rgb(80, 82, 94) if dark else rgb(217, 217, 217)
            fg = rgb(255, 255, 255) if dark else rgb(0x1F, 0x1F, 0x1F)
            if getattr(self, "_cap_dim", False):             # 弹窗压暗时：悬停/按下底色和图标也压暗一半，和被遮罩盖住的网页一致
                def half(c):
                    return (c & 0xFF) // 2 | (((c >> 8) & 0xFF) // 2) << 8 | (((c >> 16) & 0xFF) // 2) << 16
                hov, prs, fg = half(hov), half(prs), half(fg)
            hover, press = getattr(self, "_cap_hover", 0), getattr(self, "_cap_press", 0)
            zoomed = bool(u.IsZoomed(hwnd))
            scale = (u.GetDpiForWindow(hwnd) or 96) / 96.0
            hdc = u.GetDC(hwnd)
            if not hdc:
                return
            font = g.CreateFontW(-int(round(10 * scale)), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe Fluent Icons" if sys.getwindowsversion().build >= 22000 else "Segoe MDL2 Assets")     # CLEARTYPE_QUALITY
            old_font = g.SelectObject(hdc, font)
            g.SetBkMode(hdc, 1)
            bw = (hole[2] - hole[0]) // 3
            for i, (code, glyph) in enumerate(((8, "\uE921"), (9, "\uE923" if zoomed else "\uE922"), (20, "\uE8BB"))):
                rc = wintypes.RECT(hole[0] + i * bw, hole[1], hole[0] + (i + 1) * bw, hole[3])
                col, color_fg = bg, fg
                if press == code and hover == code:
                    col, color_fg = (rgb(0xC4, 0x2B, 0x1C), rgb(255, 255, 255)) if code == 20 else (prs, fg)
                elif hover == code and not press:
                    col, color_fg = (rgb(0xE8, 0x11, 0x23), rgb(255, 255, 255)) if code == 20 else (hov, fg)
                if code == 20 and col != bg and getattr(self, "_cap_dim", False):
                    col, color_fg = (col & 0xFF) // 2 | (((col >> 8) & 0xFF) // 2) << 8 | (((col >> 16) & 0xFF) // 2) << 16, rgb(127, 127, 127)
                br = g.CreateSolidBrush(col)
                u.FillRect(hdc, ctypes.byref(rc), br)
                g.DeleteObject(br)
                g.SetTextColor(hdc, color_fg)
                u.DrawTextW(hdc, glyph, 1, ctypes.byref(rc), 0x1 | 0x4 | 0x20)                                          # DT_CENTER | DT_VCENTER | DT_SINGLELINE
            g.SelectObject(hdc, old_font)
            g.DeleteObject(font)
            if sys.getwindowsversion().build >= 22000:
                # Win11：DWM 会把“标题栏颜色”那 1px 以相加方式叠在客户区第一行上（实测 = 窗体底色 + 标题栏色，逐通道相加），
                # 只在没有网页盖着的原生挖洞区（空白拖动区 + 三个按钮）看得见：暗色下是一条细亮线，弹窗压暗时更扎眼。
                # 先把这一行涂黑，相加之后正好等于标题栏色（标题栏色跟着压暗，见 _apply_caption_color）。
                blk = g.CreateSolidBrush(0)
                rows = [(hole[0], hole[1], hole[2], hole[1] + 1)]
                bh = getattr(self, "_blank_hole", None)
                if bh:
                    rows.append((bh[0], bh[1], bh[2], bh[1] + 1))
                for rr in rows:
                    rc = wintypes.RECT(*rr)
                    u.FillRect(hdc, ctypes.byref(rc), blk)
                g.DeleteObject(blk)
            u.ReleaseDC(hwnd, hdc)
        except Exception:                                  # noqa: BLE001
            pass

    def _apply_caption_color(self, hwnd):
        """DWM 的标题栏色（DWMWA_CAPTION_COLOR=35）= 顶栏底色，弹窗压暗时一起压暗，不然上边缘那几像素的把手和顶栏对不上。Win11 才有。"""
        try:
            import ctypes
            if sys.getwindowsversion().build < 22000:
                return
            r, g, b = self._cap_bg()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(r | (g << 8) | (b << 16))), 4)
        except Exception:                                  # noqa: BLE001
            pass

    def _border_rgb(self):
        """窗口边框色（DWMWA_BORDER_COLOR）：暗色用黑；浅色用灰边，但弹窗压暗时也用黑——浅色灰边相加到被压暗的页面上会变成一条亮线，而且外圈也该跟着压暗。"""
        if getattr(self, "_cap_dark", False) or getattr(self, "_cap_dim", False):
            return 0
        return 0xB8 | (0xBC << 8) | (0xC4 << 16)

    def _apply_border_color(self, hwnd):
        try:
            import ctypes
            if sys.getwindowsversion().build >= 22000:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ctypes.c_int(self._border_rgb())), 4)
        except Exception:                                  # noqa: BLE001
            pass

    def allow_clipboard_read(self):      # 名字沿用，实际放行所有权限
        """VS Code 的右键菜单要读剪贴板（判断“粘贴”能不能点），WebView2 会为此弹“想要查看复制到剪贴板的文本和图像”。
        页面只加载本机自己的界面，所有权限请求（剪贴板、通知、麦克风…）一律直接放行，不弹窗。"""
        if sys.platform != "win32" or getattr(self, "_perm_hooked", False):
            return False
        try:
            from System import Action
            form = self._window.native
            wv = form.webview

            def hook():
                from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

                def on_perm(_sender, args):
                    args.State = CoreWebView2PermissionState.Allow          # 全放行：页面只加载本机自己的界面，不需要任何权限提示
                wv.CoreWebView2.PermissionRequested += on_perm
                self._perm_hooked = True
            form.Invoke(Action(hook))
            return bool(getattr(self, "_perm_hooked", False))
        except Exception as e:                               # noqa: BLE001
            import logging
            logging.getLogger("majing.api").warning("allow_clipboard_read 失败: %r", e)
            return False

    def win_native_drag(self):
        """打开 WebView2 的“非客户区区域”支持：网页里 CSS 标成 app-region: drag 的地方交给系统当标题栏。"""
        if sys.platform != "win32":
            return False
        try:
            form = self._window.native
            wv = form.webview
            from System import Action
            res = {}

            def f():
                s = wv.CoreWebView2.Settings
                s.IsNonClientRegionSupportEnabled = True
                res["ok"] = bool(s.IsNonClientRegionSupportEnabled)
            form.Invoke(Action(f))
            self._native_drag = bool(res.get("ok"))
            return self._native_drag
        except Exception as e:                               # noqa: BLE001
            import logging
            logging.getLogger("majing.api").warning("win_native_drag 失败: %r", e)
            return False

    def win_blank(self, rect):
        """网页告诉我们顶栏空白处（导航和版本号之间）在客户区里的位置（物理像素 [左,上,右,下]）。这一块从网页控件上挖掉，命中测试返回 HTCAPTION。"""
        try:
            self._blank = tuple(int(v) for v in rect) if rect else None
        except (TypeError, ValueError):
            self._blank = None
        hwnd = self._hwnd()
        if hwnd and getattr(self, "_nc_on", False):
            self._apply_caption_hole(hwnd)
            self._paint_caption(hwnd)
        return True

    def _cap_bg(self):
        """顶栏底色（RGB）：跟随深浅主题；网页弹出对话框时压暗一半，和网页的遮罩（黑色 50%）一致。"""
        base = (0x2E, 0x30, 0x3D) if getattr(self, "_cap_dark", False) else (0xF5, 0xF5, 0xF5)
        return tuple(v // 2 for v in base) if getattr(self, "_cap_dim", False) else base

    def _set_form_back(self):
        """窗体底色 = 顶栏底色：按钮区下面露出的就是它（网页的 WebView 被挖掉了这一块）。"""
        try:
            from System import Action
            from System.Drawing import Color
            form = self._window.native
            r, g, b = self._cap_bg()
            c = Color.FromArgb(r, g, b)
            form.Invoke(Action(lambda: setattr(form, "BackColor", c)))
        except Exception:                                  # noqa: BLE001
            pass

    def win_dim(self, on):
        """网页弹出对话框（遮罩打开）时，顶栏里不是网页画的那一块（原生区域）和右上角按钮也压暗，不然会是一块亮的、对不上的颜色。"""
        if sys.platform != "win32":
            return False
        self._cap_dim = bool(on)
        hwnd = self._hwnd()
        if hwnd and getattr(self, "_nc_on", False):
            self._set_form_back()
            self._apply_caption_color(hwnd)
            self._apply_border_color(hwnd)
            self._paint_caption(hwnd)
            self._repaint_webview()
        return True

    def _top_grip(self, hwnd):
        """窗口上边缘可拖着缩放的那条（物理像素，随缩放）。客户区一直铺到窗口最顶的话，网页子窗口盖住了整条边，上边缘就抓不到了。"""
        try:
            import ctypes
            from ctypes import wintypes
            ctypes.windll.user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            ctypes.windll.user32.GetDpiForWindow.restype = wintypes.UINT
            return max(3, int(round(4 * (ctypes.windll.user32.GetDpiForWindow(hwnd) or 96) / 96.0)))
        except Exception:                                    # noqa: BLE001
            return 4

    def win_borderless(self, on):
        """新布局：客户区铺满窗口、顶部功能栏当标题栏。保留系统标题栏样式（所以最小化/最大化/关闭是 Windows 原生按钮，悬停最大化弹贴靠布局浮层），
        标题栏本身被客户区盖住；按钮区靠 SetWindowRgn 从网页控件上挖开（见 _install_nc_hook）。
        返回 {w, h}（原生按钮区的宽高，CSS 像素，前端据此给右上角留位置）；关闭新布局返回 False。"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = self._hwnd()
            if not hwnd:
                return False
            GWL_STYLE = -16
            WS_CAPTION, WS_THICKFRAME, WS_SYSMENU, WS_MINBOX, WS_MAXBOX = 0x00C00000, 0x00040000, 0x00080000, 0x00020000, 0x00010000
            u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.restype = wintypes.UINT
            self._nc_on = bool(on)
            style = u.GetWindowLongPtrW(hwnd, GWL_STYLE) | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINBOX | WS_MAXBOX
            u.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
            if on and not getattr(self, "_nc_hook", None):
                self._install_nc_hook(hwnd)
            if not on:
                try:
                    u.SetWindowRgn(int(self._window.native.webview.Handle.ToInt64()), None, True)       # 还原网页控件的完整区域
                except Exception:                                                                       # noqa: BLE001
                    pass
            u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)         # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
            if not on:
                return False
            self._set_form_back()
            w = self._apply_caption_hole(hwnd)
            self._paint_caption(hwnd)
            return {"w": 138, "h": 46} if w else False
        except Exception as e:                               # noqa: BLE001
            import logging
            logging.getLogger("majing.api").warning("win_borderless 失败: %r", e)
            return False

    def _win_geom(self, hwnd):
        """返回 (窗口矩形, 所在显示器的工作区（不含任务栏）, (左,上,右,下 各自的非客户区宽度))，都是物理像素。"""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32

        MONITORINFO = _monitorinfo_cls()
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HANDLE
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        wr, cr, mi, pt = wintypes.RECT(), wintypes.RECT(), MONITORINFO(), wintypes.POINT(0, 0)
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetWindowRect(hwnd, ctypes.byref(wr))
        u.GetClientRect(hwnd, ctypes.byref(cr))
        u.ClientToScreen(hwnd, ctypes.byref(pt))
        u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        nc = (pt.x - wr.left, pt.y - wr.top, wr.right - (pt.x + cr.right), wr.bottom - (pt.y + cr.bottom))
        return (wr.left, wr.top, wr.right, wr.bottom), (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom), nc

    def _win_zoomed(self, hwnd):
        import ctypes
        from ctypes import wintypes
        ctypes.windll.user32.IsZoomed.argtypes = [wintypes.HWND]
        return bool(ctypes.windll.user32.IsZoomed(hwnd))

    def win_cmd(self, cmd):
        """min / max / restore / toggle / close。用系统自带的最大化/还原（有 Windows 的放大动画），范围由钩子里的 WM_GETMINMAXINFO 限制在工作区。
        close 发 WM_CLOSE，会照常走“有任务在跑要确认”的关闭流程。返回是否处于最大化。"""
        if sys.platform != "win32":
            return False
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = self._hwnd()
        if not hwnd:
            return False
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        if cmd == "close":
            u.PostMessageW(hwnd, 0x0010, 0, 0)
            return False
        zoomed = self._win_zoomed(hwnd)
        self._snap_rect = None
        if cmd == "toggle":
            cmd = "restore" if zoomed else "max"
        if cmd == "min":
            u.ShowWindow(hwnd, 6)
        elif cmd == "max" and not zoomed:
            self._normal_rect = self._win_geom(hwnd)[0]          # 最大化前的位置和大小
            u.ShowWindow(hwnd, 3)
        elif cmd == "restore" and zoomed:
            u.ShowWindow(hwnd, 9)
            self._fix_restored(hwnd)
        return self._win_zoomed(hwnd)

    def _fix_restored(self, hwnd, rect=None):
        """系统还原后，WinForms 会按“窗口还带着标题栏”的算法重算尺寸（每最大化/还原一轮宽 +2、高 +46），所以还原完立刻把大小设回最大化前记下的。"""
        import ctypes
        from ctypes import wintypes
        n = rect or getattr(self, "_normal_rect", None)
        if not n:
            return
        u = ctypes.windll.user32
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos(hwnd, None, n[0], n[1], n[2] - n[0], n[3] - n[1], 0x0004 | 0x0010)

    def win_front(self):
        """把窗口叫到最前面（从托盘叫回来、或第二次启动时用）：最小化着就还原。"""
        if sys.platform != "win32":
            return False
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = self._hwnd()
        if not hwnd:
            return False
        for fn, at in (("IsIconic", [wintypes.HWND]), ("ShowWindow", [wintypes.HWND, ctypes.c_int]), ("SetForegroundWindow", [wintypes.HWND]), ("BringWindowToTop", [wintypes.HWND])):
            getattr(u, fn).argtypes = at
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        return True

    def win_zoomed(self):
        if sys.platform != "win32":
            return False
        hwnd = self._hwnd()
        return bool(hwnd and self._win_zoomed(hwnd))

    def win_drag(self):
        """按住顶部栏空白处拖动窗口：后端直接读鼠标的物理坐标，不受 150% 这类缩放影响，也不用网页一直发消息。松开左键就结束。
        还原：最大化或贴边状态下，鼠标动了几个像素就还原成原来的大小，并让鼠标留在窗口里按比例对应的位置，接着往下拖（和系统标题栏一样）。
        贴边（Win11 Snap）：鼠标顶到屏幕左/右边缘停一会儿出半透明预览，松开就贴成半屏；顶到上边缘预览全屏，松开就最大化。"""
        if sys.platform != "win32":
            return False
        import ctypes
        from ctypes import wintypes
        from majing.core.snap import Overlay
        u = ctypes.windll.user32
        hwnd = self._hwnd()
        if not hwnd:
            return False

        class WP(ctypes.Structure):
            _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                        ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT), ("rcDevice", wintypes.RECT)]
        MONITORINFO = _monitorinfo_cls()
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WP)]
        u.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WP)]
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.restype = wintypes.UINT
        u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        u.MonitorFromPoint.restype = wintypes.HANDLE
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        zoomed = self._win_zoomed(hwnd)
        r = self._win_geom(hwnd)[0]
        snapped = (not zoomed) and getattr(self, "_snap_rect", None) == r          # 还停在上次贴的位置上
        if not zoomed and not snapped:
            self._normal_rect = r                                                   # 普通状态：记下大小，贴边/最大化后拖开要还原成它
        p0 = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(p0))
        scale = (u.GetDpiForWindow(hwnd) or 96) / 96.0

        def snap_target(p):
            """鼠标当前顶着哪条边：返回 (动作, 预览矩形, 贴边后的窗口矩形)，没顶着返回 None。"""
            mon = u.MonitorFromPoint(p, 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            u.GetMonitorInfoW(mon, ctypes.byref(mi))
            m, w = mi.rcMonitor, mi.rcWork
            th, gap = max(2, int(3 * scale)), int(8 * scale)
            mid = (w.left + w.right) // 2
            if p.y <= m.top + th:
                return "max", (w.left + gap, w.top + gap, w.right - gap, w.bottom - gap), None
            if p.x <= m.left + th or p.x >= m.right - 1 - th:
                left = p.x <= m.left + th
                prev = (w.left + gap, w.top + gap, mid - gap // 2, w.bottom - gap) if left else (mid + gap // 2, w.top + gap, w.right - gap, w.bottom - gap)
                nc = self._win_geom(hwnd)[2]                                        # 窗口矩形比“看得见的窗口”四边各大一圈（不可见的缩放边）
                win = (w.left - nc[0], w.top, mid + nc[2], w.bottom + nc[3]) if left else (mid - nc[0], w.top, w.right + nc[2], w.bottom + nc[3])
                return "left" if left else "right", prev, win
            return None

        def loop():
            nonlocal p0, r
            p = wintypes.POINT()
            if zoomed or snapped:
                while u.GetAsyncKeyState(0x01) & 0x8000:
                    u.GetCursorPos(ctypes.byref(p))
                    if abs(p.x - p0.x) + abs(p.y - p0.y) > 6 * scale:
                        break
                    time.sleep(0.01)
                else:
                    return                                    # 没拖就松手了（单击/双击），不还原
                wr, work, _nc = self._win_geom(hwnd)
                nr = getattr(self, "_normal_rect", None)
                if nr is None:
                    return
                nw, nh = nr[2] - nr[0], nr[3] - nr[1]                 # 用记下的大小（系统记的那份会被 WinForms 放大）
                ratio = min(1.0, max(0.0, (p.x - wr[0]) / float(max(1, wr[2] - wr[0]))))
                left = int(p.x - nw * ratio)
                top = int(p.y - 22 * scale)                   # 鼠标留在顶栏中间的高度
                if zoomed:
                    pl = WP()
                    pl.length = ctypes.sizeof(WP)
                    u.GetWindowPlacement(hwnd, ctypes.byref(pl))
                    pl.showCmd = 1                            # SW_SHOWNORMAL：直接还原到我们指定的位置，不先跳回旧位置
                    pl.rcNormalPosition = wintypes.RECT(left, top, left + nw, top + nh)
                    u.SetWindowPlacement(hwnd, ctypes.byref(pl))
                self._fix_restored(hwnd, (left, top, left + nw, top + nh))
                self._snap_rect = None
                time.sleep(0.03)
                r = self._win_geom(hwnd)[0]
                p0 = wintypes.POINT(p.x, p.y)
            ov = Overlay()
            target, since = None, 0.0
            try:
                while u.GetAsyncKeyState(0x01) & 0x8000:
                    u.GetCursorPos(ctypes.byref(p))
                    u.SetWindowPos(hwnd, None, r[0] + p.x - p0.x, r[1] + p.y - p0.y, 0, 0, 0x0001 | 0x0004 | 0x0010)     # NOSIZE|NOZORDER|NOACTIVATE
                    t = snap_target(p)
                    key = (t[0], t[1]) if t else None
                    if key != (target[0], target[1]) if target else key is not None:
                        target, since = t, time.time()
                        ov.hide()
                    elif t and time.time() - since > 0.2:
                        ov.show(t[1])                                   # 停满 0.2 秒才出预览（路过屏幕边缘/跨显示器不触发）
                    ov.pump()
                    time.sleep(0.008)
                if target and ov.shown:                                 # 松手时预览还在 = 贴边
                    ov.hide()
                    if target[0] == "max":
                        self._normal_rect = getattr(self, "_normal_rect", None) or r
                        u.ShowWindow(hwnd, 3)
                    else:
                        w = target[2]
                        u.SetWindowPos(hwnd, None, w[0], w[1], w[2] - w[0], w[3] - w[1], 0x0004 | 0x0010)
                        self._snap_rect = self._win_geom(hwnd)[0]
            finally:
                ov.close()
        self._thread(loop)
        return True

    def set_titlebar(self, mode):
        """Win11：把系统标题栏染成和页面同色（文字、按钮也跟着深浅主题），看起来和界面连成一体。Win10 上这几个属性无效，保持原样。"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            hwnd = self._hwnd()
            if not hwnd:
                return False
            dark = mode == "dark"
            self._cap_dark = dark
            if getattr(self, "_nc_on", False):
                self._set_form_back()
                self._paint_caption(hwnd)

            def put(attr, val):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(val)), 4)

            def rgb(r, g, b):
                return r | (g << 8) | (b << 16)
            bg = rgb(0x2E, 0x30, 0x3D) if dark else rgb(0xF5, 0xF5, 0xF5)
            put(20, 1 if dark else 0)                     # 深色标题栏按钮
            put(35, rgb(*self._cap_bg()) if getattr(self, "_nc_on", False) else bg)       # 标题栏底色（弹窗压暗时一起压暗）
            put(36, rgb(255, 255, 255) if dark else rgb(0, 0, 0))   # 标题文字
            # 窗口边框色：DWM 会把它以“相加”的方式再叠到客户区最外一列像素上（暗色下 #5A5E72 + 页面底色 = 一条亮白线），
            # 所以暗色用黑：外圈是一条深色细边（和桌面区分开），里面那一列相加后正好等于页面底色，看不出线。浅色相加会饱和成白，和 #F5F5F5 差别很小，保持灰边。
            put(34, self._border_rgb())
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ PPT
    def ppt_detect(self):
        if sys.platform != "win32":
            return "模拟引擎（开发）"
        return ppt_engine.detect()

    def _drop_old(self, paths):
        """重新转换前，删掉这个会话里上一次生成的输出（只删自己生成过的），免得每调一次参数桌面上就多一份“xxx (2)”。"""
        for p in paths or []:
            if p in self._made:
                self._made.discard(p)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError:
                    pass

    def start_drag(self, paths):
        """把输出文件从窗口里用鼠标拖出去（拖到资源管理器、桌面、聊天窗口都行）：在窗口线程上发起系统拖放，只允许复制。前端在鼠标按下并移动后调用。"""
        paths = [p for p in (paths or []) if isinstance(p, str) and os.path.isfile(p)]
        if sys.platform != "win32" or not paths or self._dragging or self._window is None:
            return False
        import logging
        lg = logging.getLogger("majing.drag")
        try:
            import clr  # noqa: F401
            from System import Action
            from System.Collections.Specialized import StringCollection
            from System.Windows.Forms import DataObject, DragDropEffects
            form = self._window.native
        except Exception as e:                                # noqa: BLE001
            lg.warning("没法发起拖放：%s", e)
            return False

        def go():
            self._dragging = True
            try:
                sc = StringCollection()
                for p in paths:
                    sc.Add(p)
                d = DataObject()
                d.SetFileDropList(sc)
                r = form.DoDragDrop(d, DragDropEffects.Copy)
                lg.info("拖出 %s → %s", paths, r)
            except Exception as e:                            # noqa: BLE001
                lg.warning("拖放出错：%s", e)
            finally:
                self._drag_end = time.time()
                self._dragging = False
        try:
            form.BeginInvoke(Action(go))
        except Exception as e:                                # noqa: BLE001
            lg.warning("发起拖放失败：%s", e)
            return False
        return True

    def drag_active(self):
        """正在拖出，或刚拖完不久：窗口收到的 drop 要忽略（不然拖出去又落回自己窗口，输出文件会被当成新输入）。"""
        return self._dragging or (time.time() - self._drag_end) < 1.0

    def ppt_start(self, files, opts):
        if "ppt" in self._busy:
            return False
        self._drop_old(opts.get("replace"))
        self._ppt_stop = False
        self._busy["ppt"] = "PPT 还在转换"
        self._thread(self._ppt_run, list(files), dict(opts))
        return True

    def ppt_stop(self):
        self._ppt_stop = True
        return True

    def _ppt_run(self, files, o):
        pythoncom = None
        if sys.platform == "win32":
            import pythoncom
            pythoncom.CoInitialize()
        opt = ppt_engine.PptOptions(width=int(o.get("width", 3840)), jpeg=bool(o.get("jpeg")), notes=bool(o.get("notes", True)), skip_hidden=bool(o.get("skipHidden", True)), out_dir=self.download_dir())
        eng = ppt_engine.make_engine()
        try:
            try:
                eng.start()
                self._emit("ppt:engine", eng.name or "")
            except Exception as e:
                for i in range(len(files)):
                    self._emit("ppt:file", {"idx": i, "state": "err", "error": str(e)})
                return
            for idx, path in enumerate(files):
                if self._ppt_stop:
                    self._emit("ppt:file", {"idx": idx, "state": "cancel"})
                    continue
                self._emit("ppt:file", {"idx": idx, "state": "run"})
                try:
                    r = eng.convert(path, opt, lambda i, n, idx=idx: self._emit("ppt:progress", {"idx": idx, "i": i, "n": n}), lambda: self._ppt_stop)
                    self._made.add(r.output)
                    self._emit("ppt:file", {"idx": idx, "state": "done", "output": r.output, "pages": r.pages, "w": r.img_w, "h": r.img_h, "warning": r.warning})
                    self._log("ppt", path, r.output, True, "%s 页 · %s×%s%s" % (r.pages, r.img_w, r.img_h, (" · " + r.warning) if r.warning else ""))
                except ppt_engine.Cancelled:
                    self._emit("ppt:file", {"idx": idx, "state": "cancel"})
                except Exception as e:
                    self._emit("ppt:file", {"idx": idx, "state": "err", "error": str(e)})
                    self._log("ppt", path, "", False, str(e))
        finally:
            eng.close()
            if pythoncom:
                pythoncom.CoUninitialize()
            self._busy.pop("ppt", None)
            self._emit("ppt:done", None)

    # ------------------------------------------------------------------ 转换历史（长期保存）
    def _log(self, kind, src, output, ok, detail):
        return        # 2.0.5 起关闭转换历史：不再记录（history_* 接口保留，旧数据不动）
        try:
            size = os.path.getsize(output) if output and os.path.exists(output) else 0
            detail = str(detail).split("：(")[0].split("\n")[0][:120]          # 去掉 COM 原始报错元组，历史里只留人话
            history.add(kind, os.path.basename(src), src, output, ok, detail, size)
            self._emit("history:changed", {"kind": kind})
        except Exception:
            pass

    def history_list(self, kind):
        return history.list_(kind)

    def history_remove(self, hid, kind=None):
        history.remove(hid)
        self._emit("history:changed", {"kind": kind})
        return True

    def history_clear(self, kind):
        history.clear(kind)
        self._emit("history:changed", {"kind": kind})
        return True

    # ------------------------------------------------------------------ 格式转换
    def convert_targets(self):
        def lab(k):
            return {"mp4": "MP4（H.264，兼容最好）", "mp4-h265": "MP4（H.265，体积小）", "webm": "WebM", "mkv": "MKV", "mov": "MOV", "avi": "AVI",
                    "flv": "FLV", "wmv": "WMV", "mpg": "MPG", "ts": "TS", "gif": "GIF 动图", "ico": "ICO 图标"}.get(k, k.upper())
        return {"video": [{"key": k, "label": lab(k)} for k in media.VIDEO_OUT] + [{"key": k, "label": "只要声音 · " + k.upper()} for k in media.AUDIO_OUT],
                "audio": [{"key": k, "label": lab(k)} for k in media.AUDIO_OUT],
                "image": [{"key": k, "label": lab(k)} for k in media.IMAGE_OUT]}

    def ff_status(self):
        d = ffsetup.find()
        if d:
            media.set_ffmpeg_dir(d)
        return {"ready": bool(d)}

    def ff_download(self):
        if "ff" in self._busy:
            return False
        self._busy["ff"] = "正在下载转换组件"

        def run():
            try:
                ffsetup.download(lambda g, t: self._emit("ff:progress", {"got": g, "total": t}))
                self._emit("ff:done", {"error": ""})
            except Exception as e:
                self._emit("ff:done", {"error": str(e) or e.__class__.__name__})
            finally:
                self._busy.pop("ff", None)
        self._thread(run)
        return True

    def convert_start(self, items, quality="balanced", vscale="orig", iscale="orig", replace=None):
        """items: [{path, kind, target}]；replace：上一次生成的输出路径（重新转换前删掉）"""
        if "cv" in self._busy:
            return False
        self._drop_old(replace)
        d = ffsetup.find()
        if not d:
            return False
        media.set_ffmpeg_dir(d)
        self._cv_stop = False
        self._busy["cv"] = "格式转换还在进行"
        self._thread(self._cv_run, list(items), quality, vscale, iscale)
        return True

    def convert_stop(self):
        self._cv_stop = True
        if self._cv_job:
            media.cancel(self._cv_job)
        return True

    def _cv_run(self, items, quality, vscale, iscale):
        used = set()
        try:
            for idx, it in enumerate(items):
                if self._cv_stop:
                    self._emit("cv:file", {"idx": idx, "state": "cancel"})
                    continue
                kind, target = it["kind"], it["target"]
                spec = media.target_spec(kind, target)
                if not spec:
                    self._emit("cv:file", {"idx": idx, "state": "err", "error": "不支持的目标格式"})
                    continue
                out = _unique_out(it["path"], spec[1], used, self.download_dir())
                job = media.Job(it["path"], out, kind, target, quality, {"video": vscale, "image": iscale}.get(kind, "orig"))
                self._cv_job = job
                self._emit("cv:file", {"idx": idx, "state": "run"})
                err = media.run_job(job, lambda f, eta, idx=idx: self._emit("cv:progress", {"idx": idx, "f": f, "eta": eta}))
                self._cv_job = None
                if err:
                    self._emit("cv:file", {"idx": idx, "state": "cancel" if err == "已取消" else "err", "error": err})
                    if err != "已取消":
                        self._log("convert", it["path"], "", False, str(err))
                else:
                    self._made.add(out)
                    self._emit("cv:file", {"idx": idx, "state": "done", "output": out, "size": os.path.getsize(out)})
                    self._log("convert", it["path"], out, True, "转成 " + str(target).upper())
        finally:
            self._busy.pop("cv", None)
            self._emit("cv:done", None)

    # ------------------------------------------------------------------ SSH 管理（主机 / 两端直连传输 / 内嵌命令行）
    def ssh_hosts(self):
        """主机列表（和 ~/.ssh/config 同步）+ 通用密钥状态 + “自动配置密钥”开关。"""
        try:
            return {"ok": True, "hosts": sshhosts.list_hosts(), "key": sshhosts.key_status(), "status": sshhosts.load_status(),
                    "config": os.path.join(sshhosts.ssh_dir(), "config")}
        except Exception as e:
            return {"ok": False, "error": "读取 ssh 配置失败：%s" % e}

    def ssh_test(self, h):
        """测试一组参数（可以是还没保存的）。已保存的主机编辑时不改密码，就用保存的那个。"""
        p = dict(h)
        if not p.get("password") and p.get("old_alias"):
            try:
                p["password"] = sshhosts._load_pw().get(p["old_alias"], "")
            except Exception:
                pass
        p.setdefault("port", 22)
        return sshhosts.test(p)

    def ssh_check(self, alias):
        return sshhosts.check(alias)

    def _auto_vsc(self, alias):
        """连上主机后自动在服务器上装 VS Code Server（已经装好的几秒就过）：本机没有 VS Code、不是 Linux、网络不通等都静默跳过，失败 30 分钟后才再试。
        这样服务器上总有 VS Code Remote 需要的东西（还自带 ripgrep，编辑器里的搜索也更快）。进度走 vsc:progress（auto=True），界面只在头部显示一行小字。"""
        if os.environ.get("MAJING_NO_AUTO_VSC"):
            return
        now = time.time()
        st = self._vsc_auto.get(alias)
        if st and (st["ok"] or st.get("run") or now - st["t"] < 1800):
            return
        st = self._vsc_auto[alias] = {"ok": False, "t": now, "run": True}
        log = logging.getLogger("majing.vsc")
        last = [None, -1, 0.0]                               # 限频：上传回调每 32KB 一次，界面不需要那么多；步骤/百分比变了且距上次 ≥1 秒才发

        def prog(step, pct, msg):
            now = time.time()
            if (step, pct) != (last[0], last[1]) and (step != last[0] or now - last[2] >= 1.0 or pct in (0, 100)):
                last[0], last[1], last[2] = step, pct, now
                self._emit("vsc:progress", {"alias": alias, "step": step, "pct": pct, "text": msg, "auto": True})
        with self._vsc_lock:
            try:
                text = vscserver.install(alias, prog)
                st["ok"] = True
                log.info("自动安装 %s：%s", alias, text)
                self._emit("vsc:done", {"alias": alias, "ok": True, "text": text, "auto": True})
            except Exception as e:                           # noqa: BLE001
                log.info("自动安装 %s 没成功（静默）：%s", alias, e)
                self._emit("vsc:done", {"alias": alias, "ok": False, "text": str(e), "auto": True})
            finally:
                st["run"] = False; st["t"] = time.time()

    def vsc_install(self, alias):
        """一键给主机装 VS Code Server（本机下载→上传→解压）。立刻返回，进度走 vsc:progress，结果走 vsc:done。"""
        if "vsc" in self._busy:
            return {"ok": False, "error": "正在给 %s 安装中。" % self._busy["vsc"]}
        self._busy["vsc"] = alias

        def run():
            try:
                text = vscserver.install(alias, lambda step, pct, msg: self._emit("vsc:progress", {"alias": alias, "step": step, "pct": pct, "text": msg}))
                self._emit("vsc:done", {"alias": alias, "ok": True, "text": text})
            except Exception as e:                           # noqa: BLE001
                import logging
                logging.getLogger("majing.vsc").warning("安装失败：%s", e)
                self._emit("vsc:done", {"alias": alias, "ok": False, "text": str(e)})
            finally:
                self._busy.pop("vsc", None)
        self._thread(run)
        return {"ok": True}

    # ------------------------------------------------------------------ GPU 总览（只在打开页面或点刷新时采样一次，不定时）
    def gpu_state(self):
        """拿最近一次的采样结果（各主机）。"""
        return gpumon.monitor.state()

    def gpu_sample_now(self):
        """采样一次所有已连接的主机，结果走 gpu:sample 事件推给界面。同一时间只跑一轮。"""
        if getattr(self, "_gpu_running", False):
            return {"ok": True, "busy": True}
        self._gpu_running = True

        def run():
            try:
                gpumon.monitor.sample_all()
            finally:
                self._gpu_running = False
        self._thread(run)
        return {"ok": True, "busy": False}

    def ssh_save(self, h, old_alias=None):
        try:
            saved = sshhosts.save_host(h, old_alias)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except OSError as e:
            return {"ok": False, "error": "写入 ssh 配置失败：%s" % e}
        note = ""            # 2.0.6 起不再保存时自动配密钥：要用通用密钥，点主机右边的“+密钥”图标
        return {"ok": True, "host": saved, "note": note}

    def ssh_delete(self, alias):
        sshhosts.delete_host(alias)
        return True

    def ssh_key_all(self):
        """生成通用密钥（没有的话），并配给所有已配置的主机。"""
        if "sshkey" in self._busy:
            return {"ok": False, "error": "正在配置中。"}
        self._busy["sshkey"] = "正在配置 SSH 密钥"
        try:
            r = sshhosts.setup_key_all(lambda i, n, a: self._emit("ssh:keyprogress", {"i": i, "n": n, "alias": a}))
            return {"ok": True, **r}
        except Exception as e:
            return {"ok": False, "error": "配置失败：%s" % e}
        finally:
            self._busy.pop("sshkey", None)

    def ssh_key_info(self):
        return sshhosts.key_status()

    def ssh_key_export(self):
        """把通用密钥（私钥 + 公钥两个文件）存到下载位置（设置里可改）；同名文件不覆盖，自动改名；存好后在资源管理器里选中它。"""
        st = sshhosts.key_status()
        if not st["exists"]:
            return {"ok": False, "error": "还没有通用密钥。"}
        import shutil
        dest = self.download_dir()
        base = os.path.basename(st["path"])
        k = 1
        pick = lambda n: n if k == 1 else (n[:-4] + " (%d).pub" % k if n.endswith(".pub") else n + " (%d)" % k)
        try:
            while any(os.path.exists(os.path.join(dest, pick(n))) for n in (base, base + ".pub")):      # 同名不覆盖：两个文件一起加序号
                k += 1
            shutil.copyfile(st["path"], os.path.join(dest, pick(base)))
            shutil.copyfile(st["path"] + ".pub", os.path.join(dest, pick(base + ".pub")))
        except OSError as e:
            return {"ok": False, "error": "保存失败：%s" % e}
        _reveal(os.path.join(dest, pick(base)))
        return {"ok": True, "dest": dest}

    def ssh_key_one(self, alias):
        """给这一台主机配上通用密钥（没有就先生成）并改用它登录；对方 authorized_keys 里和本机上的旧密钥都不动。"""
        if "sshkey" in self._busy:
            return {"ok": False, "error": "正在配置中。"}
        self._busy["sshkey"] = "正在配置 SSH 密钥"
        try:
            return sshhosts.setup_key_for(alias)
        except Exception as e:
            return {"ok": False, "error": "配置失败：%s" % e}
        finally:
            self._busy.pop("sshkey", None)

    def ssh_ls(self, alias, path=""):
        return sshhosts.fs_list(alias, path)

    def ssh_mkdir(self, alias, parent, name):
        return sshhosts.fs_mkdir(alias, parent, name)

    def ssh_rename(self, alias, parent, old, new):
        return sshhosts.fs_rename(alias, parent, old, new)

    def ssh_rm(self, alias, parent, names):
        return sshhosts.fs_delete(alias, parent, names)

    def ssh_trash(self, alias, parent, names):
        return sshhosts.fs_trash(alias, parent, names)

    def ssh_restore(self, alias, pairs):
        return sshhosts.fs_restore(alias, pairs)

    def ssh_mv(self, alias, parent, names, dest):
        return sshhosts.fs_move(alias, parent, names, dest)

    def ssh_cp(self, alias, parent, names, dest):
        return sshhosts.fs_copy(alias, parent, names, dest)

    def ssh_mv_paths(self, alias, pairs):
        return sshhosts.fs_move_paths(alias, pairs)

    def ssh_rm_paths(self, alias, paths):
        return sshhosts.fs_rm_paths(alias, paths)

    def ssh_sysinfo(self, alias):
        """主机的系统、CPU、内存、系统盘（型号和占用）。界面点开主机或点刷新时调用一次，不定时。"""
        return sshhosts.sysinfo(alias)

    def ssh_read_file(self, alias, path):
        """编辑器打开远程文本文件：返回 text / encoding（utf-8、utf-8-sig、gb18030…）。
        读的过程中推 ssh:readprogress {alias, path, got, total}，编辑器据此画进度条。"""
        return sshhosts.fs_read_text(
            alias, path,
            lambda got, total: self._emit("ssh:readprogress", {"alias": alias, "path": path, "got": got, "total": total}))

    def ssh_write_file(self, alias, path, text, encoding="utf-8"):
        """编辑器保存：直接覆盖远程文件。"""
        return sshhosts.fs_write_text(alias, path, text, encoding)

    # --- VS Code 工作台的文件系统（ide\workbench.ts 里的 ssh:// 提供者）
    def ssh_stat(self, alias, path):
        return sshhosts.fs_stat(alias, path)

    def ssh_read_bytes(self, alias, path):
        return sshhosts.fs_read_bytes(alias, path)

    def ssh_write_bytes(self, alias, path, b64, create=True, overwrite=True):
        return sshhosts.fs_write_bytes(alias, path, b64, bool(create), bool(overwrite))

    def ssh_rename_path(self, alias, src, dst, overwrite=False):
        return sshhosts.fs_rename_path(alias, src, dst, bool(overwrite))

    def ssh_search_files(self, alias, root):
        return sshhosts.fs_search_files(alias, root)

    def ssh_search_text(self, alias, root, pattern, regex=False, case=False, word=False, includes=None, excludes=None):
        return sshhosts.fs_search_text(alias, root, pattern, bool(regex), bool(case), bool(word), includes or [], excludes or [])

    def ssh_remove_path(self, alias, path):
        return sshhosts.fs_remove_path(alias, path)

    def ssh_fix_sftp(self, alias):
        """文件页提示“服务器没开 SFTP”时的一键修复（改 sshd 配置的 Subsystem，改前备份、改后检查）。"""
        return sshhosts.fix_sftp(alias)

    def ssh_extract(self, alias, parent, names, here=False):
        """右键“解压”：在服务器上解 zip/tar/7z/rar 等（默认解到同名新文件夹，不覆盖）。"""
        return sshhosts.fs_extract(alias, parent, names, bool(here))

    def ssh_archive(self, alias, parent, names, kind="zip"):
        """右键“压缩”：在服务器上把所选压成 zip 或 tar.gz。"""
        return sshhosts.fs_archive(alias, parent, names, kind if kind in ("zip", "tgz") else "zip")

    def ssh_rmdir(self, alias, path):
        return sshhosts.fs_rmdir(alias, path)

    def ssh_upload(self, alias, paths, remote_dir):
        return self._ssh_transfer("up", alias, lambda emit, cancelled: sshhosts.upload(alias, paths, remote_dir, emit, cancelled))

    def ssh_download(self, alias, items):
        dest = self.download_dir()
        return self._ssh_transfer("down", alias, lambda emit, cancelled: {**sshhosts.download(alias, items, dest, emit, cancelled), "dest": dest})

    def ssh_clip_copy(self, alias, items):
        """“复制”服务器上的文件到 Windows 剪贴板：只在剪贴板上放一份“虚拟文件”清单（vclip），本机什么都不下载；
        到资源管理器/桌面里 Ctrl+V 粘贴的那一刻，系统才来读文件内容，这时才从服务器读，资源管理器自己弹出复制进度框。items 同下载：[{path, name, dir}]。"""
        from majing.core import vclip
        if not items:
            return {"ok": False, "error": "没有选中文件。"}
        ok, err = vclip.offer(sshhosts.ClipSource(alias, items))
        return {"ok": True, "count": len(items)} if ok else {"ok": False, "error": err}

    def open_vscode(self, alias, path=""):
        """用本机的 VS Code（Remote-SSH 扩展）打开这台主机：`code --folder-uri vscode-remote://ssh-remote+别名/路径`。
        主机别名就是 ~/.ssh/config 里的 Host（工具箱的主机列表和它同步），所以连接方式、密钥都沿用。path 为空就打开主目录。"""
        import shutil
        import subprocess
        alias = (alias or "").strip()
        if not alias:
            return {"ok": False, "error": "没有选中主机。"}
        code = shutil.which("code") or shutil.which("code.cmd")
        if not code:
            for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
                for rel in (("Programs", "Microsoft VS Code", "bin", "code.cmd"), ("Microsoft VS Code", "bin", "code.cmd")):
                    c = os.path.join(base, *rel)
                    if base and os.path.exists(c):
                        code = c
                        break
                if code:
                    break
        if not code:
            return {"ok": False, "error": "没找到 VS Code。请先安装 VS Code（并装上 Remote - SSH 扩展），或把 code 命令加进 PATH。"}
        # 告诉 Remote-SSH 这台主机是什么系统，省得它每次问“选择远程主机的系统”（写进 VS Code 用户设置 remote.SSH.remotePlatform）
        try:
            from majing.core import vscset
            uname = sshhosts.detect_os(sshhosts.exec_client(alias))
            plat = "windows" if uname == "Windows" else "macOS" if uname == "Darwin" else "linux"
            if not vscset.set_platform(alias, plat):
                logging.getLogger("majing.vscode").info("没改 VS Code 设置（settings.json 结构看不懂）")
        except Exception as e:                                # noqa: BLE001  探测/写设置失败不影响打开，最多它自己再问一次
            logging.getLogger("majing.vscode").info("设置 remotePlatform 失败：%s", e)
        p = (path or "").strip()
        if not p:
            r = sshhosts.fs_list(alias, "")
            p = r.get("path") if r.get("ok") else ""
        uri = "vscode-remote://ssh-remote+%s%s" % (alias, p if p.startswith("/") else "/" + p if p else "")
        args = ["--folder-uri", uri] if p else ["--remote", "ssh-remote+" + alias]
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(["cmd", "/c", code, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError as e:
            return {"ok": False, "error": "启动 VS Code 失败：%s" % e}
        return {"ok": True, "uri": uri}

    def ssh_drag(self, alias, items):
        """把服务器上选中的文件从窗口里拖出去（拖到资源管理器/桌面）：虚拟文件，拖的时候不下载，放下的那一刻系统才来读，资源管理器自己出进度框。
        前端在文件树里按下并移动后调用（此时左键还按着）。"""
        from majing.core import vclip
        if not items or self._dragging:
            return {"ok": False, "error": "没有选中文件。" if not items else "正在拖放。"}
        self._dragging = True

        def done(hr, eff):
            self._drag_end = time.time()
            self._dragging = False
            import logging
            logging.getLogger("majing.drag").info("拖出服务器文件 %d 项：hr=%s effect=%s", len(items), hr, eff)
        try:
            from System import Action
            form = self._window.native

            def ui_invoke(fn):
                form.BeginInvoke(Action(fn))
        except Exception as e:                                # noqa: BLE001
            self._dragging = False
            return {"ok": False, "error": "没法发起拖放：%s" % e}
        ok, err = vclip.drag(sshhosts.ClipSource(alias, items), ui_invoke, done)
        if not ok:
            self._dragging = False
            return {"ok": False, "error": err}
        return {"ok": True}

    def _ssh_transfer(self, kind, alias, fn):
        if "ssh" in self._busy:
            return {"ok": False, "error": "已有文件在传输，请等它结束。"}
        self._busy["ssh"] = "文件还在传"
        self._ssh_stop = False
        t0 = time.time()

        def run():
            try:
                r = fn(lambda d: self._emit("ssh:progress", {**d, "kind": kind}), lambda: self._ssh_stop)
            except Exception as e:
                r = {"ok": False, "error": "传输失败：%s" % e}
            finally:
                self._busy.pop("ssh", None)
            self._emit("ssh:done", {**r, "kind": kind, "alias": alias, "secs": time.time() - t0})
        self._thread(run)
        return {"ok": True}

    # --- 共享本机 SSH（别人连这台电脑）
    def share_info(self):
        return self._share.info()

    def share_start(self, seconds=0):
        return self._share.start(int(seconds or 0))

    def share_stop(self):
        self._share.stop("已手动关闭")
        return True

    def share_reset_password(self):
        return self._share.reset_password()

    def share_kick(self, sid):
        return self._share.kick(sid)

    def ssh_cancel(self):
        self._ssh_stop = True
        return True

    def term_open(self, alias, cols, rows):
        return sshhosts.term_open(alias, cols, rows, lambda i, d: self._emit("term:data", {"id": i, "data": d}),
                                  lambda i, why: self._emit("term:close", {"id": i, "reason": why}))

    def term_input(self, tid, data):
        return sshhosts.term_input(tid, data)

    def term_resize(self, tid, cols, rows):
        return sshhosts.term_resize(tid, cols, rows)

    def term_close(self, tid):
        return sshhosts.term_close(tid)

    # ------------------------------------------------------------------ 远程连接
    def remote_send(self, cmd):
        """阻塞直到组件回结果（pywebview 在独立线程里跑接口，不会卡界面）。"""
        box, ev = {}, threading.Event()

        def done(r):
            box["r"] = r
            ev.set()
        self._agent.send(dict(cmd), done)
        if not ev.wait(180):
            return {"ok": False, "error": "远程组件没有响应"}
        return box["r"]

    def remote_busy(self):
        return None

    def ssh_exe(self):
        if sys.platform != "win32":
            return "ssh"
        w = os.environ.get("WINDIR", "C:\\Windows")
        for p in (os.path.join(w, "System32", "OpenSSH", "ssh.exe"), os.path.join(w, "Sysnative", "OpenSSH", "ssh.exe")):
            if os.path.exists(p):
                return p
        return None

    def open_terminal(self, alias):
        ssh = self.ssh_exe()
        if not ssh:
            return {"ok": False, "error": "这台电脑没有装 Windows 自带的 OpenSSH 客户端。打开 设置 → 系统 → 可选功能 → 添加功能，搜索“OpenSSH 客户端”安装后再试。"}
        try:
            if sys.platform == "win32":
                subprocess.Popen('cmd.exe /k ""%s" %s"' % (ssh, alias), creationflags=0x00000010)
            else:
                subprocess.Popen(["x-terminal-emulator", "-e", ssh, alias])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------ 自动更新
    # ------------------------------------------------------------------ 设备安全（出口 IP / IP 质量 / DNS 泄露 / 可用性）
    def _dev(self, fn, *a):
        try:
            return {"ok": True, "data": fn(*a)}
        except Exception as e:                           # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def devsec_exit_ips(self):
        return self._dev(devsec.exit_ips)

    def devsec_geoip(self, ip):
        return self._dev(devsec.geoip, ip)

    def devsec_risk(self, ip):
        return self._dev(devsec.iprisk, ip)

    def devsec_dns(self):
        return self._dev(devsec.dns_leak)

    # ------------------------------------------------------------------ 密码保险库（本机加密，日常不上锁）
    def _v(self, fn):
        try:
            return {"ok": True, **fn()}
        except VaultError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                           # noqa: BLE001
            logging.getLogger("majing.vault").exception("保险库操作出错")
            return {"ok": False, "error": "操作失败：%s" % type(e).__name__}

    def vault_list(self, query="", folder=""):
        def go():
            items = vault.list(query, folder)
            st = vault.status()
            return {"items": items, "count": st["count"], "folders": st["folders"], "exists": st["exists"], "recovered": st["recovered"]}
        return self._v(go)

    def vault_get(self, iid):
        return self._v(lambda: {"item": vault.get(iid)})

    def vault_save(self, item):
        r = self._v(lambda: {"id": vault.save(dict(item))})
        if r.get("ok"):
            self._vsync_kick()
        return r

    def vault_delete(self, iid):
        r = self._v(lambda: (vault.delete(iid), {})[1])
        if r.get("ok"):
            self._vsync_kick()
        return r

    # ---- 浏览器扩展（Chrome / Edge 自动填充；原生通信主机见 py\nmhost.py、majing\core\nmreg.py）
    def ext_status(self):
        def go():
            from majing.core import nmreg
            return nmreg.status()
        return self._v(go)

    def ext_install(self):
        def go():
            from majing.core import nmreg
            return nmreg.register()
        return self._v(go)

    def ext_uninstall(self):
        def go():
            from majing.core import nmreg
            return nmreg.unregister()
        return self._v(go)

    def ext_open_browser(self, browser="chrome", page="extensions"):
        """用对应浏览器打开它的扩展管理页 / 密码管理页（chrome:// 这类地址不能走系统默认打开，要直接启动浏览器）。"""
        scheme = "edge" if browser == "edge" else "chrome"
        target = {"extensions": scheme + "://extensions", "passwords": "chrome://password-manager/settings" if scheme == "chrome" else "edge://settings/passwords"}.get(page, scheme + "://extensions")
        cands = {"chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
                 "edge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"]}.get(browser, [])
        for c in cands:
            p = os.path.expandvars(c)
            if os.path.exists(p):
                subprocess.Popen([p, target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {"ok": True}
        return {"ok": False, "error": "没找到这个浏览器。"}

    # ---- 同步到服务器（用码境账号；细节见 majing\core\vsync.py）
    _vs_timer = None
    _vs_lock = threading.Lock()

    def _vsync_kick(self, delay=3.0):
        """开了同步才有用：本地改完过几秒（合并多次改动）后台同步一次，结果用 vault:sync 事件告诉界面。"""
        if not vsync.status()["enabled"]:
            return
        with self._vs_lock:
            if self._vs_timer:
                self._vs_timer.cancel()
            self._vs_timer = threading.Timer(delay, self._vsync_run)
            self._vs_timer.daemon = True
            self._vs_timer.start()

    def _vsync_run(self):
        self._emit("vault:sync", {"state": "busy"})
        try:
            r = vsync.sync()
            self._emit("vault:sync", {"state": "ok", "changed": r["changed"], "last_ok": r["last_ok"]})
        except VaultError as e:
            self._emit("vault:sync", {"state": "err", "error": str(e)})
        except Exception as e:                           # noqa: BLE001
            logging.getLogger("majing.vault").exception("同步出错")
            self._emit("vault:sync", {"state": "err", "error": "同步失败：%s" % type(e).__name__})

    def vault_sync_status(self):
        return {"ok": True, **vsync.status()}

    def vault_sync_kick(self):
        self._vsync_kick(0.3)
        return {"ok": True}

    def vault_sync_probe(self):
        return self._v(vsync.probe)

    def vault_sync_enable(self, password, confirm=None):
        return self._v(lambda: vsync.enable(str(password or ""), confirm))

    def vault_sync_now(self):
        return self._v(vsync.sync)

    def vault_sync_disable(self, erase=False):
        return self._v(lambda: (vsync.disable(bool(erase)), {})[1])

    def vault_pick_import(self):
        """选一个 Bitwarden 导出文件（.json / .csv），返回路径；取消返回空串。"""
        import webview
        dlg = getattr(webview, "FileDialog", None)
        mode = dlg.OPEN if dlg else webview.OPEN_DIALOG
        r = self._window.create_file_dialog(mode, directory=settings.get("last_dir", ""), allow_multiple=False,
                                            file_types=("密码导出文件 (*.json;*.csv)", "所有文件 (*.*)"))
        files = list(r or [])
        if files:
            settings.set("last_dir", os.path.dirname(files[0]))
        return files[0] if files else ""

    def vault_import(self, path, password="", delete_after=False):
        """导入 Bitwarden / Chrome / Edge / Firefox 的导出文件。需要文件密码时返回 need_password。
        delete_after：导入成功后删除这个导出文件（里面可能是明文密码；直接删除，不进回收站）。内容不写日志，只记条数。"""
        from majing.core import bwimport
        try:
            items, source = bwimport.load_ex(path, password or "")
        except bwimport.NeedPassword as e:
            return {"ok": False, "need_password": True, "error": str(e)}
        except VaultError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                           # noqa: BLE001
            logging.getLogger("majing.vault").exception("导入出错")
            return {"ok": False, "error": "导入失败：%s" % type(e).__name__}
        def go():
            added = vault.import_items(items)
            return {"added": added, "total": len(items), "skipped": len(items) - added, "source": source}
        r = self._v(go)
        logging.getLogger("majing.vault").info("导入（%s）：共 %s 条，新增 %s 条", source, r.get("total"), r.get("added"))
        if r.get("ok") and r.get("added"):
            self._vsync_kick()
        if r.get("ok") and delete_after:
            try:
                os.remove(path)
                r["deleted"] = True
            except OSError as e:
                r["deleted"] = False
                r["delete_error"] = "没能删除导出文件（%s），请手动删除。" % type(e).__name__
        return r

    def vault_copy(self, iid, field):
        """复制用户名/密码到剪贴板；密码 15 秒后自动清空。"""
        def go():
            if field not in ("username", "password", "url", "notes"):
                raise VaultError("不能复制这一项。")
            val = vault.get(iid).get(field, "")
            if not val:
                raise VaultError("这一项是空的。")
            secs = vault_mod.CLIP_SECS if field == "password" else 0
            vault_mod.copy_secret(val, secs)
            return {"secs": secs}
        return self._v(go)

    def devsec_fix(self, kind):
        """一键修复 DNS / WebRTC 泄露（改本机 Clash Verge 的配置，会先备份）。"""
        try:
            return {"ok": True, "data": clashfix.fix(kind)}
        except clashfix.ClashFixError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                           # noqa: BLE001
            logging.getLogger("majing.api").exception("一键修复失败")
            return {"ok": False, "error": "修复失败：%s" % e}

    def devsec_avail(self):
        return self._dev(devsec.avail)

    # ------------------------------------------------------------------ 码境账号
    def account_status(self):
        return account.status(APP_VERSION)

    def account_login(self):
        """发起跳转授权：打开浏览器授权页，后台轮询，结果通过 account:event 推给前端。"""
        r = account.start(APP_VERSION)
        if not r.get("ok"):
            return r
        self._acct_code = r["device_code"]
        self.open_url(r["url"])
        self._thread(self._account_poll, r["device_code"], time.time() + r["expires_in"])
        return {"ok": True, "user_code": r["user_code"], "url": r["url"]}

    def account_cancel(self):
        self._acct_code = None
        return True

    def _account_poll(self, code, deadline):
        while getattr(self, "_acct_code", None) == code and time.time() < deadline:
            time.sleep(2)
            if getattr(self, "_acct_code", None) != code:
                return
            r = account.poll(code, APP_VERSION)
            if r["state"] == "pending":
                continue
            self._acct_code = None
            self._emit("account:event", r)
            return
        if getattr(self, "_acct_code", None) == code:
            self._acct_code = None
            self._emit("account:event", {"state": "expired"})

    def account_unbind(self):
        return account.unbind(APP_VERSION)

    def update_check(self):
        self._thread(self._update_once)
        return True

    def _update_loop(self):
        time.sleep(4)
        while True:
            if not self._update_pending:
                self._update_once()
            time.sleep(6 * 3600)

    def _update_once(self):
        """检查并更新。自动检查和手动检查可能同时触发：已经有一轮在跑（检查/下载/等重启）就不再开第二轮，免得同时下载两份。"""
        if not self._upd_lock.acquire(blocking=False):
            ulog.info("已经有一轮更新在进行，这次检查忽略")
            return
        if self._update_pending:                          # 新版已经下载好、只等重启：不用再下一遍
            self._upd_lock.release()
            return
        try:
            self._update_run()
        finally:
            self._upd_lock.release()

    def _update_run(self):
        cur = os.environ.get("MAJING_FAKE_VERSION") or APP_VERSION
        try:
            info = updater.check(cur)
        except Exception:
            self._emit("update:state", {"state": "err", "text": "检查更新失败"})
            return
        if not info:
            self._emit("update:state", {"state": "ok", "text": "最新"})
            return
        if not updater.exe_path():
            self._emit("update:state", {"state": "ok", "text": "有新版 v%s" % info.version})
            return
        mode = updater.plan(info, cur)
        ulog.info("发现新版本 %s（当前 %s），更新方式：%s", info.version, cur, mode)
        if mode is None:
            self._emit("update:state", {"state": "ok", "text": "最新"})
            return
        tries = settings.get("upd_try", {})
        if tries.get("ver") == info.version and tries.get("n", 0) >= 3:       # 同一个版本连续试了几次都没换成功：别没完没了地下载
            self._emit("update:state", {"state": "err", "text": "更新没成功，稍后再试"})
            return
        try:
            last = [-1]

            def prog(g, t):
                pct = g * 100 // max(1, t)
                if pct != last[0]:
                    last[0] = pct
                    self._emit("update:state", {"state": "busy", "text": "更新中 %d%%" % pct})
            if mode == "payload":
                updater.download_payload(info, prog)
            else:
                f = updater.download(info, prog)
                updater.replace(f, updater.exe_path())
        except Exception:
            ulog.exception("更新失败")
            self._emit("update:state", {"state": "err", "text": "更新失败，稍后重试"})
            return
        settings.set("upd_try", {"ver": info.version, "n": (tries.get("n", 0) + 1) if tries.get("ver") == info.version else 1})      # 下载换好了才记一次：换了却没生效（比如运行时对不上）连续几次就停手
        self._update_pending = info
        while True:                                   # 没有任务在跑就重启，有就等做完
            busy = self.busy_text()
            if not busy:
                break
            self._emit("update:state", {"state": "busy", "text": "已更新，任务结束后重启"})
            time.sleep(2)
        self._emit("update:state", {"state": "busy", "text": "已更新，正在重启"})
        try:
            updater.relaunch(sys.argv[1:])
        except Exception:
            self._emit("update:state", {"state": "err", "text": "新版已就位，下次生效"})
            return
        self._shutdown()
        from majing import tray
        tray.remove()                                 # os._exit 不走清理，托盘图标要先摘掉，不然会残留到鼠标扫过
        os._exit(0)
