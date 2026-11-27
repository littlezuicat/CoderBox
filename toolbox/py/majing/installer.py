# -*- coding: utf-8 -*-
"""安装 / 卸载。下载下来的就是安装包：直接运行会出现安装面板，把程序装到用户自己的目录（默认 %LOCALAPPDATA%\\Programs\\ClaudeToolbox，
不需要管理员权限），建桌面和开始菜单快捷方式，在“设置 → 应用”里登记卸载项。装好之后从安装目录运行的就是正式的程序。

怎么区分“安装包”和“装好的程序”：安装目录里有一个 install.json（安装时写入）。exe 旁边有它 = 已安装的程序；没有 = 安装包。
用户的数据（设置、主机列表、加密的密码）在 %APPDATA%\\MajingToolbox，不在安装目录里：覆盖安装、更新、卸载（默认）都不动它。
卸载永远不会碰 ~/.ssh（私钥、config 是用户自己的）。"""
import json
import os
import shutil
import subprocess
import sys
import time

from majing import APP_NAME, APP_VERSION

APP_ID = "ClaudeToolbox"
EXE_NAME = "ClaudeToolbox.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudeToolbox"
LNK_NAME = APP_NAME + ".lnk"
NOWIN = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------------------------------------------ 位置
def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share"), "Programs", APP_ID)


def _known_folder(guid_parts, fallback):
    if sys.platform != "win32":
        return fallback
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]
        a, b, c, d = guid_parts
        g = GUID(a, b, c, (ctypes.c_ubyte * 8)(*d))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
            p = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            if p:
                return p
    except Exception:
        pass
    return fallback


def desktop_dir():
    return _known_folder((0xB4BFCC3A, 0xDB2C, 0x424C, (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)), os.path.join(os.path.expanduser("~"), "Desktop"))


def start_menu_dir():
    return _known_folder((0xA77F5D77, 0x2E2B, 0x44C3, (0xA6, 0xA2, 0xAB, 0xA6, 0x01, 0x05, 0x4A, 0x51)),
                         os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Microsoft", "Windows", "Start Menu", "Programs"))


def _meta(d):
    return os.path.join(d, "install.json")


def is_installed_run():
    """当前进程是不是从装好的目录里运行的（exe 旁边有 install.json）。"""
    return bool(getattr(sys, "frozen", False)) and os.path.exists(_meta(os.path.dirname(os.path.abspath(sys.executable))))


def existing_install():
    """已装的版本：{dir, version}，没有返回 None。先看注册表里登记的位置，再看默认位置。"""
    cands = []
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
                cands.append(winreg.QueryValueEx(k, "InstallLocation")[0])
        except OSError:
            pass
    cands.append(default_dir())
    for d in cands:
        try:
            with open(_meta(d), encoding="utf-8") as f:
                m = json.load(f)
            if os.path.exists(os.path.join(d, EXE_NAME)):
                return {"dir": d, "version": m.get("version", "")}
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ 快捷方式 / 注册表
def _make_shortcut(lnk, target, workdir):
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            sc = win32com.client.Dispatch("WScript.Shell").CreateShortCut(lnk)
            sc.TargetPath = target
            sc.WorkingDirectory = workdir
            sc.IconLocation = target + ",0"
            sc.Description = APP_NAME
            sc.Save()
        finally:
            pythoncom.CoUninitialize()
        return
    except Exception:
        pass
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()"
          % (lnk.replace("'", "''"), target.replace("'", "''"), workdir.replace("'", "''"), target.replace("'", "''")))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=NOWIN, timeout=30)


def _register(d, exe, size_kb):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in [("DisplayName", APP_NAME), ("DisplayVersion", APP_VERSION), ("Publisher", "zuicat"), ("InstallLocation", d),
                          ("DisplayIcon", exe + ",0"), ("UninstallString", '"%s" --uninstall' % exe), ("URLInfoAbout", "https://www.zuicat.cn/")]:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))


def _check_dir(d):
    d = (d or "").strip().strip('"')
    if not d or not os.path.isabs(d):
        raise ValueError("请填写完整的安装路径，比如 C:\\Users\\你\\AppData\\Local\\Programs\\ClaudeToolbox。")
    d = os.path.normpath(d)
    if os.path.dirname(d) == d:
        raise ValueError("不能直接装在磁盘根目录，请选一个文件夹。")
    if os.path.isfile(d):
        raise ValueError("这个路径是一个文件，请选文件夹。")
    return d


# ------------------------------------------------------------------ 安装
def install(opts, emit):
    """把正在运行的这个 exe 装到 opts['dir']。emit(百分比, 文字) 报告进度。返回 {ok, exe, error}。"""
    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "开发模式下不能安装，请使用打包好的安装包。"}
    try:
        d = _check_dir(opts.get("dir"))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    src = os.path.abspath(sys.executable)
    target = os.path.join(d, EXE_NAME)
    try:
        emit(3, "准备安装目录…")
        os.makedirs(d, exist_ok=True)
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError:                        # 正在运行的 exe 不能删，但可以改名
                old = target + ".old"
                try:
                    if os.path.exists(old):
                        os.remove(old)
                except OSError:
                    pass
                os.replace(target, old)
        total = os.path.getsize(src)
        done = 0
        tmp = target + ".part"
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                buf = fi.read(1024 * 1024)
                if not buf:
                    break
                fo.write(buf)
                done += len(buf)
                emit(5 + int(done * 80 / max(total, 1)), "正在复制程序文件…")
        os.replace(tmp, target)
        with open(_meta(d), "w", encoding="utf-8") as f:
            json.dump({"version": APP_VERSION, "installed_at": time.time(), "dir": d, "from": src}, f, ensure_ascii=False)
        if sys.platform == "win32":
            if opts.get("desktop", True):
                emit(88, "创建桌面快捷方式…")
                _make_shortcut(os.path.join(desktop_dir(), LNK_NAME), target, d)
            if opts.get("startmenu", True):
                emit(92, "添加到开始菜单…")
                _make_shortcut(os.path.join(start_menu_dir(), LNK_NAME), target, d)
            emit(96, "登记到“设置 → 应用”…")
            _register(d, target, total // 1024)
        emit(100, "安装完成")
        return {"ok": True, "exe": target, "dir": d}
    except PermissionError:
        return {"ok": False, "error": "没有权限写入这个位置，请换一个文件夹（比如默认位置）。"}
    except OSError as e:
        return {"ok": False, "error": "安装失败：%s" % e}


def launch(exe):
    from majing.core import updater
    subprocess.Popen([exe, "--installed"], cwd=os.path.dirname(exe), close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=NOWIN if sys.platform == "win32" else 0, env=updater.fresh_env())


def _spawn_detached(cmd):
    """起一个在本进程退出后还能继续跑的命令。无控制台的 exe 没有可继承的标准句柄，必须显式给 DEVNULL。
    优先脱离当前进程的作业对象（BREAKAWAY）；有些启动器（计划任务等）的作业不允许脱离，子进程会随作业一起被杀，
    这时改走 WMI 创建（由系统服务出面起进程，不在这个作业里）；都不行才退回普通启动。"""
    dn = subprocess.DEVNULL
    kw = dict(close_fds=True, stdin=dn, stdout=dn, stderr=dn)
    try:
        subprocess.Popen(cmd, creationflags=NOWIN | 0x01000000 | 0x00000200, **kw)   # BREAKAWAY_FROM_JOB | NEW_PROCESS_GROUP
        return
    except OSError:
        pass
    try:
        import base64
        ps = "([wmiclass]'Win32_Process').Create('%s') | Out-Null" % cmd.replace("'", "''")
        enc = base64.b64encode(ps.encode("utf-16-le")).decode()
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], creationflags=NOWIN, timeout=30,
                           stdin=dn, stdout=dn, stderr=dn)
        if r.returncode == 0:
            return
    except Exception:
        pass
    subprocess.Popen(cmd, creationflags=NOWIN, **kw)



# ------------------------------------------------------------------ 卸载
def uninstall(opts, emit):
    """卸载当前运行的这份（必须是装好的）。opts['remove_data']：同时删除设置、主机列表等本程序的数据（~/.ssh 永远不动）。"""
    exe = os.path.abspath(sys.executable)
    d = os.path.dirname(exe)
    if not os.path.exists(_meta(d)):
        return {"ok": False, "error": "这不是安装版程序，无法卸载。"}
    try:
        emit(10, "删除快捷方式…")
        for lnk in (os.path.join(desktop_dir(), LNK_NAME), os.path.join(start_menu_dir(), LNK_NAME)):
            try:
                os.remove(lnk)
            except OSError:
                pass
        emit(40, "清理卸载项…")
        if sys.platform == "win32":
            try:
                import winreg
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
            except OSError:
                pass
        if opts.get("remove_data"):
            emit(60, "删除设置和主机列表…")
            for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
                if base:
                    shutil.rmtree(os.path.join(base, "MajingToolbox"), ignore_errors=True)
        local = os.environ.get("LOCALAPPDATA")
        if local:                                         # 负载包（程序本体的一部分）总是删；ffmpeg 等下载的组件跟着“删除数据”走
            shutil.rmtree(os.path.join(local, "MajingToolbox", "payload"), ignore_errors=True)
        emit(85, "删除程序文件…")
        if sys.platform == "win32":      # 自己正在运行，删不了自己：交给一个延迟几秒的独立命令，等本进程退出后再删
            # 注意 cmd 里 if 后面的 & 属于 if 的分支：if 条件不成立时 & 后面的 ping 会被一起跳过（循环就没有等待了），所以 if 要用括号圈住
            inner = 'for /l %i in (1,1,60) do (rmdir /s /q "{d}" 2>nul & (if not exist "{d}" exit) & ping -n 2 127.0.0.1 >nul)'.format(d=d)
            # 整条命令作为一个字符串交给 cmd（/s 去掉最外层引号），别用列表：列表会把里面的引号拼坏；命令行里 for 变量只写一个 %；最多重试约 1 分钟，等本进程退出
            _spawn_detached('cmd.exe /d /s /c "%s"' % inner)
        emit(100, "已卸载")
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": "卸载失败：%s" % e}
