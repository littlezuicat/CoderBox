# -*- coding: utf-8 -*-
"""克劳德工具箱 2.x：React 界面（Clash Verge Rev 风格）+ Python 后端，用 pywebview（Windows 上是系统自带的 WebView2）显示。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from majing import APP_NAME, APP_VERSION, installer
from majing.core import updater
from majing.settings import settings
from api import Api


def web_index():
    base = getattr(sys, "_MEIPASS", HERE)
    for p in (os.path.join(base, "web", "index.html"), os.path.join(HERE, "..", "web", "dist", "index.html")):
        if os.path.exists(p):
            return os.path.abspath(p)
    raise SystemExit("找不到界面文件 web/index.html")


def run_mode(args):
    """怎么启动的：--uninstall = 卸载面板；打包后的 exe 旁边没有 install.json（= 刚下载的安装包）= 安装面板；其余是正常运行。
    --portable / --after-update / MAJING_PORTABLE 可以跳过安装面板（绿色运行、更新后重启、开发测试）。"""
    if "--uninstall" in args:
        return "uninstaller"
    if getattr(sys, "frozen", False) and not installer.is_installed_run() and not os.environ.get("MAJING_PORTABLE") \
            and not any(a == "--portable" or a.startswith("--after-update=") for a in args):
        return "installer"
    return "app"


def main():
    import webview
    from webview.dom import DOMEventHandler
    args = sys.argv[1:]
    mode = run_mode(args)
    if mode == "app":
        updater.after_start(args)
    api = Api()
    api.mode = mode
    if mode == "app":
        w, h = settings.get("win_size", [1180, 780])
        window = webview.create_window(APP_NAME, web_index(), js_api=api, width=int(w), height=int(h), min_size=(980, 640),
                                       background_color="#F5F5F5", text_select=True)
    else:       # 安装 / 卸载面板：小窗口，不能缩放
        window = webview.create_window("安装 " + APP_NAME if mode == "installer" else "卸载 " + APP_NAME, web_index(), js_api=api, width=760, height=520,
                                       resizable=False, background_color="#FFFFFF", text_select=False)
    api._set_window(window)

    def on_drop(e):
        files = [f.get("pywebviewFullPath") for f in (e.get("dataTransfer", {}).get("files") or []) if f.get("pywebviewFullPath")]
        if files:
            api._emit("drop:files", files)

    def on_loaded():
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        # 不要再登记 dragover：pywebview 每次 dragover 都把整个事件发给 Python，拖放时会卡死页面主线程；放行拖放改在前端 App.tsx 里做。
        api._start_background()
        files = [a for a in args if not a.startswith("--") and os.path.exists(a)]
        if files:
            api._emit("drop:files", files)

    def on_closing():
        if api.busy_text():
            return window.create_confirmation_dialog(APP_NAME, "；".join(api.busy_text()) + "，现在退出会中断。确定退出吗？")
        return True

    def on_closed():
        api._shutdown()

    if mode == "app":
        window.events.loaded += on_loaded
        window.events.closing += on_closing
        window.events.closed += on_closed
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=bool(os.environ.get("MAJING_DEBUG")))


if __name__ == "__main__":
    main()
