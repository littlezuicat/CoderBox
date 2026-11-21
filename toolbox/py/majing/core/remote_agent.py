# -*- coding: utf-8 -*-
"""远程连接的后台程序（majing-remote.exe，Go 写的）：工具箱开着它就开着，用 stdin/stdout 一行一个 JSON 通信。
关工具箱 = 关它 = 断开所有连接、删掉 ssh 配置。协议和 C# 版一致（cmd: set_password / set / connect / disconnect / kick / approve / quit；
事件 ev: state / sessions / log / approve / approve_done / result）。"""
import json
import os
import subprocess
import sys
import threading
import time

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "res")


def locate_exe():
    """找远程组件：环境变量（测试用）> 随程序打包的 majing-remote.exe。
    打包成单文件 exe 时资源在临时目录里，所以复制到 %LOCALAPPDATA%\\MajingToolbox\\remote（带内容哈希，旧版本自动清理）再用。"""
    env = os.environ.get("MAJING_REMOTE_EXE")
    if env and os.path.exists(env):
        return env
    import hashlib
    import shutil
    base = getattr(sys, "_MEIPASS", None)
    src = os.path.join(base, "res", "majing-remote.exe") if base else os.path.join(RES, "majing-remote.exe")
    if not os.path.exists(src):
        return None
    with open(src, "rb") as f:
        data = f.read()
    tag = hashlib.sha256(data).hexdigest()[:12]
    d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share"), "MajingToolbox", "remote")
    os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, "majing-remote-%s.exe" % tag)
    if not os.path.exists(exe) or os.path.getsize(exe) != len(data):
        tmp = exe + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, exe)
    for n in os.listdir(d):
        if n.startswith("majing-remote-") and n.endswith(".exe") and os.path.join(d, n) != exe:
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass
    return exe


class RemoteAgent:
    def __init__(self, exe_path=None):
        self.exe = exe_path
        self.proc = None
        self.start_error = None
        self.other_instance = False
        self._rid = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        self._stopping = False
        self._mutex = None
        self.on_event = lambda ev: None        # 在后台线程里调用；界面层要自己切回主线程

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _acquire_owner(self):
        """同一台电脑只让一个工具箱窗口管远程连接（Windows 命名互斥量）。"""
        if sys.platform != "win32":
            return True
        import ctypes
        k = ctypes.windll.kernel32
        h = k.CreateMutexW(None, True, "Local\\MajingToolbox-RemoteAgent")
        if k.GetLastError() == 183:            # ERROR_ALREADY_EXISTS
            return False
        self._mutex = h
        return True

    def start(self):
        if self._mutex is None and not self._acquire_owner():
            self.other_instance = True
            return
        try:
            if not self.exe or not os.path.exists(self.exe):
                self.exe = locate_exe()
            if not self.exe or not os.path.exists(self.exe):
                raise RuntimeError("这个版本没有内置远程连接组件")
            self.proc = subprocess.Popen([self.exe, "ipc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=os.path.dirname(os.path.abspath(self.exe)), creationflags=CREATE_NO_WINDOW)
            p = self.proc
            threading.Thread(target=self._read_loop, args=(p,), daemon=True).start()
            threading.Thread(target=lambda: p.stderr.read(), daemon=True).start()
            self.start_error = None
        except Exception as e:
            self.start_error = "远程连接组件启动失败：%s（可能被杀毒软件拦截了）" % e
            self.proc = None

    def _read_loop(self, p):
        try:
            for raw in p.stdout:
                try:
                    ev = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("ev") == "result":
                    with self._lock:
                        cb = self._pending.pop(str(ev.get("rid")), None)
                    if cb:
                        try:
                            cb(ev)
                        except Exception:
                            pass
                    continue
                try:
                    self.on_event(ev)
                except Exception:
                    pass
        except Exception:
            pass
        if self._stopping:
            return
        try:
            self.on_event({"ev": "agent_exit"})
        except Exception:
            pass
        time.sleep(3)                          # 意外退出：过几秒重启
        if not self._stopping and self.proc is p:
            self.start()

    def send(self, cmd, done=None):
        """发一条命令；done(result) 在后台线程上收到结果（ok / error / 其它字段）。"""
        p = self.proc
        if p is None or p.poll() is not None:
            if done:
                done({"ok": False, "error": self.start_error or "远程连接组件没有运行"})
            return
        with self._lock:
            self._rid += 1
            rid = str(self._rid)
            if done:
                self._pending[rid] = done
        cmd = dict(cmd, rid=rid)
        try:
            with self._wlock:
                p.stdin.write((json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8"))
                p.stdin.flush()
        except Exception as e:
            with self._lock:
                self._pending.pop(rid, None)
            if done:
                done({"ok": False, "error": str(e)})

    def stop(self):
        """关工具箱时调用：让它断开所有连接、清理 ssh 配置后退出。"""
        self._stopping = True
        p = self.proc
        if p is None:
            return
        try:
            with self._wlock:
                p.stdin.write(b'{"cmd":"quit"}\n')
                p.stdin.flush()
                p.stdin.close()
            p.wait(6)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
