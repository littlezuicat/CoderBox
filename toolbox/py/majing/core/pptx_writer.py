# -*- coding: utf-8 -*-
"""把一组整页图片打包成 PPTX：每页一张铺满的图片 + 演讲者备注。
结构沿用 res/base.pptx（python-pptx 生成，PowerPoint/LibreOffice 验证过），只在标记处填入页面、尺寸和标题。
图片原样存入，不重新压缩。"""
import os
import struct
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
    if os.path.exists(out_path):
        os.remove(out_path)
    os.replace(tmp, out_path)


def unique_path(folder, name, ext):
    p = os.path.join(folder, name + ext)
    k = 2
    while os.path.exists(p):
        p = os.path.join(folder, "%s (%d)%s" % (name, k, ext))
        k += 1
    return p
