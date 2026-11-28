# -*- coding: utf-8 -*-
"""用本机的 PowerPoint（没有就试 WPS 演示）把每页导出成图片，再打包成图片版 PPTX。
渲染完全由用户自己的 Office 完成：字体、特效和放映时一样，文件也不出本机。
只能在 Windows 上用（COM）；其他系统用 FakeEngine 方便开发调试。
必须在工作线程里调用，且线程里先 pythoncom.CoInitialize()（engine.run_in_thread 已处理）。"""
import os
from concurrent.futures import ThreadPoolExecutor
import shutil
import sys
import tempfile
import time
import uuid

from . import pptx_writer

PPT_EXTS = (".pptx", ".ppt", ".pptm", ".ppsx", ".pps", ".potx", ".pot", ".odp", ".dps", ".dpt")
PROG_IDS = ("PowerPoint.Application", "KWPP.Application", "WPP.Application")
PPT_CLSID = "{91493441-5A91-11CF-8700-00AA0060263B}"
WIDTHS = {"1080P": 1920, "2K": 2560, "4K": 3840, "6K": 5760}


class PptOptions:
    def __init__(self, width=3840, jpeg=False, notes=True, skip_hidden=True, out_dir=""):
        self.width, self.jpeg, self.notes, self.skip_hidden, self.out_dir = width, jpeg, notes, skip_hidden, out_dir   # out_dir 空 = 放在原文件旁边


class PptResult:
    def __init__(self):
        self.output, self.pages, self.img_w, self.img_h, self.warning = None, 0, 0, 0, None


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- 探测（Windows）

def powerpoint_exe():
    """本机 POWERPNT.EXE 路径（看 App Paths 的 64/32 位两个视图），没装返回 None。"""
    if sys.platform != "win32":
        return None
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\powerpnt.exe", 0, winreg.KEY_READ | view) as k:
                    v = winreg.QueryValueEx(k, "")[0].strip('"')
                    if v and os.path.exists(v):
                        return v
            except OSError:
                pass
    return None


def _progid_server():
    """“PowerPoint.Application” 实际由谁提供（WPS 开了“兼容 Office”时会把它接管）。"""
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\LocalServer32" % PPT_CLSID) as k:
            return winreg.QueryValueEx(k, "")[0] or ""
    except OSError:
        return ""


def _has_progid(pid):
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, pid + r"\CLSID"))
        return True
    except OSError:
        return False


def detect():
    """看看装了什么（不启动）：'Microsoft PowerPoint' / 'WPS 演示' / None。"""
    if powerpoint_exe():
        return "Microsoft PowerPoint"
    if any(_has_progid(i) for i in PROG_IDS):
        return "WPS 演示"
    return None


def _is_ms_powerpoint(app):
    """WPS 也自称 “Microsoft PowerPoint”（Name 一样），只能看程序目录里有没有 POWERPNT.EXE。"""
    try:
        d = app.Path
        return bool(d) and os.path.exists(os.path.join(d, "POWERPNT.EXE"))
    except Exception:
        return False


# --------------------------------------------------------------------------- 引擎

class PptEngine:
    def __init__(self):
        self.app = None
        self.name = None
        self.we_started = False

    def _get_active(self, pid):
        import win32com.client
        try:
            return win32com.client.GetActiveObject(pid)
        except Exception:
            return None

    def start(self):
        import win32com.client
        import subprocess
        ppt = powerpoint_exe()
        if ppt:
            running = self._get_active("PowerPoint.Application")
            if running is not None and _is_ms_powerpoint(running):        # 1) 已经在运行的 PowerPoint
                self.app, self.we_started, self.name = running, False, "Microsoft PowerPoint"
                return
            if "POWERPNT" in _progid_server().upper():                    # 2) 自动化入口确实指向 PowerPoint
                try:
                    a = win32com.client.Dispatch("PowerPoint.Application")
                    if _is_ms_powerpoint(a):
                        self.app, self.we_started, self.name = a, True, "Microsoft PowerPoint"
                        return
                    try:
                        a.Quit()
                    except Exception:
                        pass
                except Exception:
                    pass
            try:                                                          # 3) 入口被 WPS 接管：自己以自动化模式启动 PowerPoint，再连上
                subprocess.Popen([ppt, "-Embedding"])
                t0 = time.time()
                while time.time() - t0 < 40:
                    time.sleep(0.4)
                    a = self._get_active("PowerPoint.Application")
                    if a is not None and _is_ms_powerpoint(a):
                        self.app, self.we_started, self.name = a, True, "Microsoft PowerPoint"
                        return
            except Exception:
                pass
        for pid in ("KWPP.Application", "WPP.Application", "PowerPoint.Application"):   # 退回 WPS
            if not _has_progid(pid):
                continue
            running = self._get_active(pid)
            try:
                self.app = running or win32com.client.Dispatch(pid)
                self.we_started = running is None
                self.name = "Microsoft PowerPoint" if _is_ms_powerpoint(self.app) else "WPS 演示"
                return
            except Exception:
                self.app = None
        raise RuntimeError("没找到可用的 PowerPoint 或 WPS 演示。没装 Office 的电脑可以用网页版：www.zuicat.cn/ppt")

    def _ensure_alive(self):
        """自动化模式的 PowerPoint 关掉最后一个文件后会自己退出：每个文件开始前确认还连着，断了就重连。"""
        if self.app is not None:
            try:
                self.app.Name
                return
            except Exception:
                self.app = None
        self.start()

    def convert(self, path, opt, progress, cancelled):
        """progress(第几页, 共几页)；cancelled() 返回 True 就中止。返回 PptResult。"""
        self._ensure_alive()
        full = os.path.abspath(path)
        pres, we_opened = None, False
        try:                                                    # 文件已经在 PowerPoint 里开着：直接用（含未保存的修改），转完不关
            for i in range(1, self.app.Presentations.Count + 1):
                p = self.app.Presentations.Item(i)
                if os.path.normcase(p.FullName) == os.path.normcase(full):
                    pres = p
                    break
        except Exception:
            pass
        if pres is None:
            try:
                pres = self.app.Presentations.Open(full, -1, 0, 0)   # 只读、无标题、不开窗口
            except Exception as e:
                raise RuntimeError("打不开这个文件（可能有密码、已损坏，或者被别的程序占用）：%s" % e)
            we_opened = True
        work = os.path.join(tempfile.gettempdir(), "majing-ppt-" + uuid.uuid4().hex[:8])
        os.makedirs(work)
        res = PptResult()
        try:
            sw, sh = float(pres.PageSetup.SlideWidth), float(pres.PageSetup.SlideHeight)
            w = opt.width
            h = int(round(w * sh / sw))
            total = pres.Slides.Count
            slides = []
            jobs = []
            pool = ThreadPoolExecutor(max_workers=max(2, min(8, (os.cpu_count() or 4))))
            for i in range(1, total + 1):
                if cancelled():
                    raise Cancelled()
                s = pres.Slides.Item(i)
                if opt.skip_hidden:
                    try:
                        hidden = int(s.SlideShowTransition.Hidden)
                    except Exception:
                        hidden = 0
                    if hidden == -1:
                        progress(i, total)
                        continue
                png = os.path.join(work, "%03d.png" % i)
                s.Export(png, "PNG", w, h)                           # PowerPoint 的 COM 只能单线程导出；导完的图交给线程池并行处理，同时导下一页
                if not os.path.exists(png):
                    raise RuntimeError("第 %d 页导出失败" % i)
                notes = _notes_of(s) if opt.notes else None
                jobs.append((pool.submit(_post_image, png, opt.jpeg), notes))
                progress(i, total)
            for fut, notes in jobs:                                  # 按页序收集（并行处理完的结果）
                img, size = fut.result()
                if size:
                    if not res.img_w:
                        res.img_w, res.img_h = size
                    if size[0] < w and not res.warning:
                        res.warning = "Office 只导出了 %d×%d（要求 %d×%d），可能是版本限制" % (size[0], size[1], w, h)
                slides.append((img, notes))
            if not slides:
                raise RuntimeError("没有可转换的页面（全是隐藏页？）")
            title = os.path.splitext(os.path.basename(full))[0]
            emu = (int(round(sw * 12700)), int(round(sh * 12700)))
            # 保存：首选输出目录，写不进去（不存在/只读/路径太长/被占用/磁盘满…）就依次换：原文件旁边、桌面、文档、临时目录，并在结果里说明
            out, note = pptx_writer.save_robust(pptx_writer.fallback_dirs(opt.out_dir, os.path.dirname(full)), title, "_图片版", emu[0], emu[1], slides)
            if note:
                res.warning = (res.warning + "；" if res.warning else "") + note
            res.output, res.pages = out, len(slides)
            return res
        finally:
            try:
                locals().get('pool').shutdown(wait=True, cancel_futures=True)
            except Exception:
                pass
            if we_opened:
                try:
                    pres.Close()
                except Exception:
                    pass
            shutil.rmtree(work, ignore_errors=True)

    def close(self):
        if self.app is None:
            return
        try:                                                     # 是我们启动的、而且用户没在里面开别的文件，才退出
            if self.we_started and self.app.Presentations.Count == 0:
                self.app.Quit()
        except Exception:
            pass
        self.app = None


def _post_image(png, jpeg):
    """导出后的图片处理（在线程池里并行跑）：读尺寸；要 JPG 的话转成高质量 JPG。返回 (最终文件, 尺寸)。"""
    size = pptx_writer.image_size(png)
    img = png
    if jpeg:
        from PIL import Image
        img = png[:-4] + ".jpg"
        with Image.open(png) as im:
            im.convert("RGB").save(img, "JPEG", quality=95, subsampling=0)
        os.remove(png)
    return img, size


def _notes_of(slide):
    try:
        shapes = slide.NotesPage.Shapes
        for k in range(1, shapes.Count + 1):
            sh = shapes.Item(k)
            try:
                if sh.Type == 14 and sh.PlaceholderFormat.Type == 2 and sh.HasTextFrame == -1:   # 占位符 / 备注正文
                    return sh.TextFrame.TextRange.Text
            except Exception:
                pass
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- 开发用

class FakeEngine:
    """非 Windows 上开发调试用：每页画一张纯色图，备注取自占位文字。流程和 PptEngine 一致。"""
    name = "模拟引擎（仅开发）"

    def start(self):
        pass

    def close(self):
        pass

    def convert(self, path, opt, progress, cancelled):
        from PIL import Image
        full = os.path.abspath(path)
        work = tempfile.mkdtemp(prefix="majing-fake-")
        try:
            total = 5
            slides = []
            w, h = opt.width, int(opt.width * 9 / 16)
            for i in range(1, total + 1):
                if cancelled():
                    raise Cancelled()
                time.sleep(0.15)
                p = os.path.join(work, "%03d.png" % i)
                Image.new("RGB", (w // 8, h // 8), (40 * i, 120, 255 - 40 * i)).save(p)
                slides.append((p, "第 %d 页备注" % i if opt.notes else None))
                progress(i, total)
            res = PptResult()
            title = os.path.splitext(os.path.basename(full))[0]
            res.output, note = pptx_writer.save_robust(pptx_writer.fallback_dirs(opt.out_dir, os.path.dirname(full)), title, "_图片版", 12192000, 6858000, slides)
            res.warning = note or None
            res.pages, res.img_w, res.img_h = total, w // 8, h // 8
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)


def make_engine():
    return PptEngine() if sys.platform == "win32" else FakeEngine()
