# -*- coding: utf-8 -*-
"""码境工具箱 2.x：React 界面（Clash Verge Rev 风格）+ Python 后端，用 pywebview（Windows 上是系统自带的 WebView2）显示。"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 必须赶在 pywebview 之前：它启动时会调 SetProcessDPIAware()（“系统级”DPI 感知，只认主屏缩放）。
# 一旦窗口挪到缩放不同的显示器（比如主屏 150%、外接 1080P 是 100%），系统会把整个窗口位图拉伸，文字就发糊。
# 先声明“每显示器 V2”感知，WebView2 就会按窗口所在显示器的真实缩放渲染；进程的 DPI 感知只能设一次，pywebview 之后那次调用会被忽略。
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))      # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except Exception:                                                                 # noqa: BLE001  老系统没有这个接口就保持原样
        pass

from majing import APP_NAME, APP_VERSION, installer, log
from majing.core import updater
from majing.settings import settings
from api import Api


def web_index():
    base = getattr(sys, "_MEIPASS", HERE)
    for p in (os.path.join(base, "web", "index.html"), os.path.join(HERE, "..", "web", "dist", "index.html")):
        if os.path.exists(p):
            return os.path.abspath(p)
    raise SystemExit("找不到界面文件 web/index.html")


def mark_verified():
    """界面加载成功：给当前负载包打上“启动成功”的标记（引导程序下次就敢继续用它；没有这个标记又留着 .launching 就会退回上一版）。"""
    d = os.environ.get("MAJING_PAYLOAD")
    if not d:
        return
    try:
        with open(os.path.join(d, ".verified"), "w") as f:
            f.write(str(time.time()))
        os.remove(os.path.join(d, ".launching"))
    except OSError:
        pass


def run_mode(args):
    """怎么启动的：--uninstall = 卸载面板；打包后的 exe 旁边没有 install.json（= 刚下载的安装包）= 安装面板；其余是正常运行。
    --portable / --after-update / MAJING_PORTABLE 可以跳过安装面板（绿色运行、更新后重启、开发测试）。"""
    if "--uninstall" in args:
        return "uninstaller"
    if getattr(sys, "frozen", False) and not installer.is_installed_run() and not os.environ.get("MAJING_PORTABLE") \
            and not any(a == "--portable" or a.startswith("--after-update=") for a in args):
        return "installer"
    return "app"


def _dark_theme():
    """窗口刚出来、页面还没画出来时的底色要和启动动画一致：设置里是深色，或“跟随系统”且系统是深色。"""
    t = settings.get("theme", "light")
    if t == "dark":
        return True
    if t == "system" and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return False


def main():
    import webview
    from webview.dom import DOMEventHandler
    args = sys.argv[1:]
    mode = run_mode(args)
    tray_key = None
    if mode == "app" and sys.platform == "win32":
        # 单实例：已经有一个在跑（可能正藏在托盘里）就把它叫出来，自己退出。更新后重启时旧进程马上就退，等它最多 15 秒。
        from majing import tray as tray_mod
        tray_key = tray_mod.instance_key(HERE)
        if not tray_mod.acquire(tray_key, wait=15 if any(a.startswith("--after-update") for a in args) else 0):
            # 已经有一个实例：能叫出来（它在托盘里或已经开着）就叫出来，自己退出。
            # 叫不出来说明那个实例正在退出（托盘窗口已销毁、互斥量还没放）——等它放开再自己启动，别一声不响地退出（用户会看到“点不开”）
            deadline = time.time() + 20
            while True:
                if tray_mod.signal_existing(tray_key):
                    return
                if tray_mod.acquire(tray_key, wait=0.3):
                    break
                if time.time() > deadline:
                    return
    if mode == "app":
        updater.after_start(args)
    log.setup()
    api = Api()
    api.mode = mode
    log.wrap_api(api)
    if mode == "app":
        w, h = settings.get("win_size", [1180, 780])
        window = webview.create_window(APP_NAME, web_index(), js_api=api, width=int(w), height=int(h), min_size=(840, 600),
                                       background_color="#2E303D" if _dark_theme() else "#F5F5F5", text_select=True, hidden=True)
    else:       # 安装 / 卸载面板：小窗口，不能缩放
        window = webview.create_window("安装 " + APP_NAME if mode == "installer" else "卸载 " + APP_NAME, web_index(), js_api=api, width=760, height=520,
                                       resizable=False, background_color="#FFFFFF", text_select=False)
    api._set_window(window)
    if mode == "app":
        api._cap_dark = _dark_theme()
        # 把深浅色带给页面：开屏动画不用再按系统深浅色猜（设置是深色而系统是浅色时，开屏会先亮一下再变暗）
        try:
            _orig_resolve = window._resolve_url
            _tq = "t=dark" if _dark_theme() else "t=light"

            def _resolve_with_theme(url, _o=_orig_resolve):
                r = _o(url)
                return r + ("&" if "?" in r else "?") + _tq if isinstance(r, str) and r.startswith("http") else r
            window._resolve_url = _resolve_with_theme
        except Exception:                                    # noqa: BLE001
            pass

    def on_drop(e):
        files = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer", {}).get("files") or []) if f.get("pywebviewFullPath")]
        if files and not api.drag_active():          # 自己拖出去的输出文件又落回窗口：不当成新输入
            api._emit("drop:files", files)

    shown = {"v": False}

    def reveal():
        """窗口先藏着创建；窗体一建好（句柄有了）就先去掉系统标题栏、再显示出来——用户看不到带标题栏的原生窗口，
        只会先看到一块和开屏动画同底色的空窗口，网页一加载好动画就从头开始放。（试过“全透明显示→渲染好再不透明”：
        透明期间 WebView2 把窗口当成被遮挡，暂停出画面，动画前半段全丢，所以不用。）"""
        if shown["v"]:
            return
        shown["v"] = True
        try:
            if mode == "app" and settings.get("layout_demo", True) is not False:
                api.win_borderless(True)                     # 显示之前就去掉系统标题栏，不然会闪一下
                api.set_titlebar("dark" if _dark_theme() else "light")   # 标题栏色/边框色也先设好：否则界面就绪前，顶部那几行是系统默认的白
            try:                                             # 网页控件的底色也设成和开屏动画一样，不闪白
                from System import Action
                from System.Drawing import Color
                form = window.native
                c = Color.FromArgb(0x2E, 0x30, 0x3D) if _dark_theme() else Color.FromArgb(0xF5, 0xF5, 0xF5)
                form.Invoke(Action(lambda: setattr(form.webview, "DefaultBackgroundColor", c)))
            except Exception:                                # noqa: BLE001
                pass
            window.show()
        except Exception:                                    # noqa: BLE001
            try:
                window.show()
            except Exception:                                # noqa: BLE001
                pass

    def reveal_when_ready():
        t0 = time.time()
        while time.time() - t0 < 15:
            try:
                f = window.native
                if f is not None and f.IsHandleCreated and f.webview is not None:
                    break
            except Exception:                                # noqa: BLE001
                pass
            time.sleep(0.02)
        reveal()

    def on_loaded():
        mark_verified()
        if mode == "app":
            reveal()                                         # 兜底：窗体早就绪了这里什么也不做
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        # 不要再登记 dragover：pywebview 每次 dragover 都把整个事件发给 Python，拖放时会卡死页面主线程；放行拖放改在前端 App.tsx 里做。
        api._start_background()
        if mode == "app":
            api.allow_clipboard_read()                       # VS Code 右键菜单读剪贴板：直接放行，不弹权限框
        files = [a for a in args if not a.startswith("--") and os.path.exists(a)]
        if files:
            api._emit("drop:files", files)

    # ---- 托盘：关闭窗口只是缩到托盘继续跑，托盘右键“退出”才真退出
    state = {"quit": False}
    tray_icon = None

    def show_window():
        try:
            window.show()
        except Exception:                                    # noqa: BLE001
            pass
        api.win_front()

    def really_quit():
        # 不再弹“有任务在跑，退出会中断”的确认：直接退出
        state["quit"] = True
        tray_mod.release()                                   # 先放开单实例锁和托盘：收尾要几秒，这期间重新点开也要能起来
        try:
            window.destroy()
        except Exception:                                    # noqa: BLE001
            os._exit(0)

    def on_closing():
        if state["quit"]:
            return True
        if tray_icon is None or not tray_icon._added:        # 托盘没起来就别藏了（藏了就叫不回来），直接退出
            return True
        try:
            window.hide()
        except Exception:                                    # noqa: BLE001
            return True
        return False

    def on_closed():
        if tray_key:
            tray_mod.release()
        api._shutdown()

    if mode == "app":
        if tray_key:
            tray_icon = tray_mod.Tray(tray_key, APP_NAME, os.path.join(HERE, "res", "app.ico"), show_window, really_quit)
            tray_icon.start()
        threading.Thread(target=reveal_when_ready, daemon=True).start()
        window.events.loaded += on_loaded      # 去标题栏由前端按“新布局”开关决定（调 api.win_borderless）
        window.events.closing += on_closing
        window.events.closed += on_closed
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=bool(os.environ.get("MAJING_DEBUG")))
    if mode == "app":
        # 窗口已关、清理已做完：立刻结束进程。不然后台线程（SSH 连接等）会拖住进程十来秒，期间托盘窗口还在，再点开会叫不回来
        if tray_key:
            tray_mod.release()
        os._exit(0)


if __name__ == "__main__":
    main()
