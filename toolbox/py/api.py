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
from majing.core import account, ffsetup, media, ppt_engine, sshhosts, sshserver, updater
from majing.core.remote_agent import RemoteAgent
from majing.settings import settings


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


class Api:
    def __init__(self):
        self._window = None
        self._emit_hook = None            # 测试时可替换：收集事件
        self._busy = {}                   # 名称 -> 提示文字；有任务在跑就非空
        self._ppt_stop = False
        self._cv_job = None
        self._cv_stop = False
        self.mode = "app"                  # app / installer / uninstaller，由 main.py 按启动方式决定
        self._ssh_stop = False
        self._share = sshserver.ShareServer(on_change=lambda i: self._emit("share:state", i))
        self._agent = RemoteAgent()
        self._agent.on_event = lambda ev: self._emit("remote:event", ev)
        self._update_pending = None
        self._acct_code = None

    # ------------------------------------------------------------------ 内部
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

    def _shutdown(self):
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

    def set_titlebar(self, mode):
        """Win11：把系统标题栏染成和页面同色（文字、按钮也跟着深浅主题），看起来和界面连成一体。Win10 上这几个属性无效，保持原样。"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from majing import APP_NAME
            hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
            if not hwnd:
                return False
            dark = mode == "dark"

            def put(attr, val):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(val)), 4)

            def rgb(r, g, b):
                return r | (g << 8) | (b << 16)
            bg = rgb(0x2E, 0x30, 0x3D) if dark else rgb(0xF5, 0xF5, 0xF5)
            put(20, 1 if dark else 0)                     # 深色标题栏按钮
            put(35, bg)                                    # 标题栏底色
            put(36, rgb(255, 255, 255) if dark else rgb(0, 0, 0))   # 标题文字
            put(34, bg)                                    # 窗口边框
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ PPT
    def ppt_detect(self):
        if sys.platform != "win32":
            return "模拟引擎（开发）"
        return ppt_engine.detect()

    def ppt_start(self, files, opts):
        if "ppt" in self._busy:
            return False
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

    def convert_start(self, items, quality="balanced", vscale="orig", iscale="orig"):
        """items: [{path, kind, target}]"""
        if "cv" in self._busy:
            return False
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
                    self._emit("cv:file", {"idx": idx, "state": "done", "output": out, "size": os.path.getsize(out)})
                    self._log("convert", it["path"], out, True, "转成 " + str(target).upper())
        finally:
            self._busy.pop("cv", None)
            self._emit("cv:done", None)

    # ------------------------------------------------------------------ SSH 管理（主机 / 两端直连传输 / 内嵌命令行）
    def ssh_hosts(self):
        """主机列表（和 ~/.ssh/config 同步）+ 通用密钥状态 + “自动配置密钥”开关。"""
        if not settings.get("auto_key_default_on", False):         # 这一版起“新增主机自动配置密钥”默认打开（只迁移一次，之后用户怎么设就怎么算）
            settings.set("auto_key", True)
            settings.set("auto_key_default_on", True)
        try:
            return {"ok": True, "hosts": sshhosts.list_hosts(), "key": sshhosts.key_status(), "auto_key": bool(settings.get("auto_key", True)), "status": sshhosts.load_status(),
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

    def ssh_save(self, h, old_alias=None):
        try:
            saved = sshhosts.save_host(h, old_alias)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except OSError as e:
            return {"ok": False, "error": "写入 ssh 配置失败：%s" % e}
        note = ""
        if settings.get("auto_key", True) and (h.get("password") or saved.get("has_password")):
            r = sshhosts.setup_key_for(saved["alias"])
            note = "已自动配置密钥。" if r["ok"] else "保存成功，但自动配置密钥没成功：%s" % r["error"]
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

    def ssh_auto_key(self, on):
        settings.set("auto_key", bool(on))
        return True

    def ssh_ls(self, alias, path=""):
        return sshhosts.fs_list(alias, path)

    def ssh_mkdir(self, alias, parent, name):
        return sshhosts.fs_mkdir(alias, parent, name)

    def ssh_upload(self, alias, paths, remote_dir):
        return self._ssh_transfer("up", alias, lambda emit, cancelled: sshhosts.upload(alias, paths, remote_dir, emit, cancelled))

    def ssh_download(self, alias, items):
        dest = self.download_dir()
        return self._ssh_transfer("down", alias, lambda emit, cancelled: {**sshhosts.download(alias, items, dest, emit, cancelled), "dest": dest})

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
        try:
            last = [-1]

            def prog(g, t):
                pct = g * 100 // max(1, t)
                if pct != last[0]:
                    last[0] = pct
                    self._emit("update:state", {"state": "busy", "text": "更新中 %d%%" % pct})
            f = updater.download(info, prog)
            updater.replace(f, updater.exe_path())
        except Exception:
            self._emit("update:state", {"state": "err", "text": "更新失败，稍后重试"})
            return
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
        os._exit(0)
