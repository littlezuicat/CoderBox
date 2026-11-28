# -*- coding: utf-8 -*-
"""把一组整页图片打包成 PPTX：每页一张铺满的图片 + 演讲者备注。
结构沿用 res/base.pptx（python-pptx 生成，PowerPoint/LibreOffice 验证过），只在标记处填入页面、尺寸和标题。
图片原样存入，不重新压缩。"""
import errno
import os
import re
import struct
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CT_NOTES = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "res", "base.pptx")
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def esc(s):
    """XML 转义，并去掉 XML 1.0 不允许的控制字符。"""
    s = "".join(c for c in s if c >= " " or c == "\t")
    s = s.replace("￾", "").replace("￿", "")
    return escape(s, {'"': "&quot;"})


def image_size(path):
    """读 PNG / JPEG 文件头里的像素尺寸；失败返回 None。"""
    with open(path, "rb") as f:
        head = f.read(24)
        if head[:4] == b"\x89PNG":
            return struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(4)
                if len(b) < 4 or b[0] != 0xFF:
                    return None
                ln = (b[2] << 8) | b[3]
                if 0xC0 <= b[1] <= 0xC3:
                    d = f.read(5)
                    return ((d[3] << 8) | d[4], (d[1] << 8) | d[2])
                f.seek(ln - 2, 1)
    return None


def _slide_xml(i, cx, cy):
    return (HEAD + '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="%s">' % NS_REL +
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Slide %d" descr="第 %d 页"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>' % (i, i) +
            '<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>' % (cx, cy) +
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def _notes_xml(notes):
    notes = (notes or "").replace("\r\n", "\r").replace("\n", "\r").rstrip("\r")
    if not notes:
        body = '<a:p><a:endParaRPr lang="zh-CN"/></a:p>'
    else:
        paras = []
        for para in notes.split("\r"):
            if not para:
                paras.append('<a:p><a:endParaRPr lang="zh-CN"/></a:p>')
                continue
            runs = []
            for k, line in enumerate(para.split("\v")):     # \v 是 PowerPoint 的段内换行
                if k:
                    runs.append('<a:br><a:rPr lang="zh-CN"/></a:br>')
                if line:
                    runs.append('<a:r><a:rPr lang="zh-CN"/><a:t>%s</a:t></a:r>' % esc(line))
            paras.append("<a:p>%s</a:p>" % "".join(runs))
        body = "".join(paras)
    return (HEAD + '<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="%s">' % NS_REL +
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="3" sz="quarter"/></p:nvPr></p:nvSpPr><p:spPr/>'
            '<p:txBody><a:bodyPr/><a:lstStyle/>' + body + '</p:txBody></p:sp>'
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')


def write_pptx(out_path, cx, cy, slides, title=""):
    """slides: [(图片路径, 备注或 None)]；cx/cy 是幻灯片宽高，单位 EMU（1 磅 = 12700）。"""
    if not slides:
        raise ValueError("没有页面")
    tmp = out_path + ".part"
    try:
        _write_pptx(tmp, cx, cy, slides, title)
        _check_pptx(tmp, len(slides))
        _replace(tmp, out_path)
    except BaseException:
        try:                                             # 写到一半失败：别留下半截 .part 文件
            os.remove(tmp)
        except OSError:
            pass
        raise


def _write_pptx(tmp, cx, cy, slides, title):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = "".join('<p:sldId id="%d" r:id="rIdS%d"/>' % (255 + i, i) for i in range(1, len(slides) + 1))
    rels = "".join('<Relationship Id="rIdS%d" Type="%s/slide" Target="slides/slide%d.xml"/>' % (i, NS_REL, i) for i in range(1, len(slides) + 1))
    types = "".join('<Override PartName="/ppt/slides/slide%d.xml" ContentType="%s"/><Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="%s"/>' % (i, CT_SLIDE, i, CT_NOTES)
                    for i in range(1, len(slides) + 1))
    with zipfile.ZipFile(BASE) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for e in src.infolist():
            data = src.read(e.filename)
            n = e.filename
            if n in ("[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "docProps/core.xml"):
                t = data.decode("utf-8")
                if n == "[Content_Types].xml":
                    t = t.replace("<!--SLIDES-->", types)
                elif n == "ppt/presentation.xml":
                    t = t.replace("<!--SLDIDS-->", ids).replace("{CX}", str(cx)).replace("{CY}", str(cy))
                elif n == "ppt/_rels/presentation.xml.rels":
                    t = t.replace("<!--SLIDERELS-->", rels)
                else:
                    t = t.replace("{TITLE}", esc(title)).replace("2013-01-27T09:14:16Z", now).replace("2013-01-27T09:15:58Z", now)
                data = t.encode("utf-8")
            z.writestr(n, data)
        for i, (path, notes) in enumerate(slides, 1):
            ext = "png" if path.lower().endswith(".png") else "jpeg"
            media = "image%d.%s" % (i, ext)
            with open(path, "rb") as f:                      # 图片本身已压缩，存储即可
                z.writestr(zipfile.ZipInfo("ppt/media/" + media, (2020, 1, 1, 0, 0, 0)), f.read(), zipfile.ZIP_STORED)
            z.writestr("ppt/slides/slide%d.xml" % i, _slide_xml(i, cx, cy))
            z.writestr("ppt/slides/_rels/slide%d.xml.rels" % i, HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="%s/slideLayout" Target="../slideLayouts/slideLayout7.xml"/>'
                       '<Relationship Id="rId2" Type="%s/image" Target="../media/%s"/>'
                       '<Relationship Id="rId3" Type="%s/notesSlide" Target="../notesSlides/notesSlide%d.xml"/></Relationships>' % (NS_REL, NS_REL, media, NS_REL, i))
            z.writestr("ppt/notesSlides/notesSlide%d.xml" % i, _notes_xml(notes))
            z.writestr("ppt/notesSlides/_rels/notesSlide%d.xml.rels" % i, HEAD + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="%s/notesMaster" Target="../notesMasters/notesMaster1.xml"/>'
                       '<Relationship Id="rId2" Type="%s/slide" Target="../slides/slide%d.xml"/></Relationships>' % (NS_REL, NS_REL, i))


def _replace(tmp, out_path):
    """把 .part 改成正式文件名。杀毒软件/网盘同步刚好在扫描新文件时会短暂占用（WinError 32 / 5），隔一会儿重试几次；os.replace 本身就会覆盖旧文件，不先删。"""
    last = None
    for k in range(8):
        try:
            os.replace(tmp, out_path)
            return
        except PermissionError as e:
            last = e
            time.sleep(0.25 * (k + 1))
    raise last


def _check_pptx(path, n):
    """写完马上打开检查一遍：是合法的 zip、页数对、不是空文件。有问题就当场报错，别把坏文件交给用户。"""
    if os.path.getsize(path) < 1024:
        raise OSError("生成的文件是空的")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for i in (1, n):
            if "ppt/slides/slide%d.xml" % i not in names or not any(x.startswith("ppt/media/image%d." % i) for x in names):
                raise OSError("生成的文件缺第 %d 页" % i)


def unique_path(folder, name, ext):
    p = os.path.join(folder, name + ext)
    k = 2
    while os.path.exists(p):
        p = os.path.join(folder, "%s (%d)%s" % (name, k, ext))
        k += 1
    return p


# ---------------------------------------------------------------------------- 保存的容错
MAX_PATH_SAFE = 240            # Windows 老式路径上限 260，留一点余量；超过的话标题会被截短


def friendly_error(e):
    """把保存失败的原因说成人话。"""
    n = getattr(e, "errno", None)
    w = getattr(e, "winerror", None)
    if n == errno.ENOSPC or w == 112:
        return "磁盘空间不够"
    if w in (32, 33):
        return "文件正被别的程序占用（杀毒软件或网盘同步？）"
    if isinstance(e, PermissionError) or n == errno.EACCES or w == 5:
        return "没有写入权限（只读文件夹或被安全软件拦截）"
    if isinstance(e, FileNotFoundError) or w in (3, 206):
        return "文件夹不存在或路径太长"
    if n == errno.EROFS:
        return "只读位置"
    return str(e) or e.__class__.__name__


def _fit_name(folder, name, ext):
    """文件名太长会让整条路径超过上限，写入就失败：必要时把名字截短（保留结尾的后缀部分）。"""
    bad = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
    name = bad.sub("_", name).strip()
    room = MAX_PATH_SAFE - len(os.path.join(os.path.abspath(folder), "")) - len(ext) - 6          # 6 = “ (99)”预留
    if room < 12:
        raise OSError("路径太深")
    if len(name) > room:
        keep_tail = "_图片版"
        head = name[:-len(keep_tail)] if name.endswith(keep_tail) else name
        tail = keep_tail if name.endswith(keep_tail) else ""
        head = head[:max(4, room - len(tail))].rstrip(" .")
        name = head + tail
    return name or "output"


def fallback_dirs(*first):
    """保存目录的候选：传进来的优先，然后依次是 桌面、文档、系统临时目录。去重、跳过空的。"""
    out = [d for d in first if d]
    home = os.path.expanduser("~")
    for sub in ("Desktop", "Documents"):
        out.append(os.path.join(home, sub))
    out.append(tempfile.gettempdir())
    seen, res = set(), []
    for d in out:
        k = os.path.normcase(os.path.abspath(d))
        if k not in seen:
            seen.add(k)
            res.append(d)
    return res


def save_robust(dirs, title, suffix, cx, cy, slides):
    """依次试各个目录，写得进去就用。返回 (输出文件, 说明)；说明非空表示没存到首选位置（原因和实际位置）。全失败才抛错，错误里列出每个位置的原因。"""
    fails = []
    for k, d in enumerate(dirs):
        try:
            os.makedirs(d, exist_ok=True)
            out = unique_path(d, _fit_name(d, title + suffix, ".pptx"), ".pptx")
            write_pptx(out, cx, cy, slides, title)
            note = ""
            if k > 0:
                note = "没能存到 %s（%s），已存到 %s" % (dirs[0], fails[0][1] if fails else "原因未知", os.path.dirname(out))
            return out, note
        except Exception as e:                                   # noqa: BLE001
            fails.append((d, friendly_error(e)))
    raise OSError("保存失败。" + "；".join("%s：%s" % f for f in fails[:3]))
