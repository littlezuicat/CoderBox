# -*- coding: utf-8 -*-
"""格式转换核心：ffprobe 读信息、拼 ffmpeg 参数、带进度运行、Pillow 转图片。
规则取自网页版 converter/server.py（那边跑过 540 个用例），命令构造部分原样保留。"""
import json
import os
import subprocess
import sys
import threading

FFMPEG_THREADS = max(2, os.cpu_count() or 4)
MAX_PIXELS = 8192 * 8192
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
MAX_GIF_SECONDS = 120
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 目标格式：key -> (扩展名, MIME)。视频文件可以转成视频格式，也可以只提取声音（音频格式）。
VIDEO_OUT = {
    "mp4": ("mp4", "video/mp4"), "mp4-h265": ("mp4", "video/mp4"), "webm": ("webm", "video/webm"),
    "mkv": ("mkv", "video/x-matroska"), "mov": ("mov", "video/quicktime"), "avi": ("avi", "video/x-msvideo"),
    "flv": ("flv", "video/x-flv"), "wmv": ("wmv", "video/x-ms-wmv"), "mpg": ("mpg", "video/mpeg"),
    "ts": ("ts", "video/mp2t"), "gif": ("gif", "image/gif"),
}

AUDIO_OUT = {
    "mp3": ("mp3", "audio/mpeg"), "m4a": ("m4a", "audio/mp4"), "aac": ("aac", "audio/aac"),
    "wav": ("wav", "audio/wav"), "flac": ("flac", "audio/flac"), "ogg": ("ogg", "audio/ogg"),
    "opus": ("opus", "audio/ogg"), "wma": ("wma", "audio/x-ms-wma"), "aiff": ("aiff", "audio/aiff"),
}

IMAGE_OUT = {
    "jpg": ("jpg", "image/jpeg"), "png": ("png", "image/png"), "webp": ("webp", "image/webp"),
    "gif": ("gif", "image/gif"), "bmp": ("bmp", "image/bmp"), "tiff": ("tiff", "image/tiff"),
    "ico": ("ico", "image/x-icon"), "avif": ("avif", "image/avif"),
}

ALLOWED = {"video": [VIDEO_OUT, AUDIO_OUT], "audio": [AUDIO_OUT], "image": [IMAGE_OUT]}

QUALITY = ("balanced", "high", "small")

SCALES = {
    "video": {"orig": None, "1080": 1080, "720": 720, "480": 480},    # 短边上限
    "audio": {"orig": None},
    "image": {"orig": None, "2048": 2048, "1024": 1024, "512": 512},  # 长边上限
}

def target_spec(kind, target):
    """(类别, 扩展名, MIME)；目标不适用于这类文件时返回 None。类别：video / audio / image。"""
    for table in ALLOWED.get(kind, []):
        if target in table:
            cat = "video" if table is VIDEO_OUT else "audio" if table is AUDIO_OUT else "image"
            return (cat,) + table[target]
    return None

def video_rotation(v):
    """视频流的旋转角度（显示矩阵或旧式 rotate 标签），没有则 0。"""
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(round(float(sd["rotation"]))) % 360
            except (TypeError, ValueError):
                pass
    try:
        return int(v.get("tags", {}).get("rotate", 0)) % 360
    except (TypeError, ValueError):
        return 0

CRF_X264 = {"balanced": 22, "high": 18, "small": 24}

PRESET_X264 = {"balanced": "veryfast", "high": "medium", "small": "veryfast"}

CRF_X265 = {"balanced": 26, "high": 22, "small": 29}

CRF_VP9 = {"balanced": 33, "high": 28, "small": 38}

QV_MPEG = {"balanced": 4, "high": 2, "small": 8}        # mpeg4 / mpeg2 / wmv 的 -q:v（越小越好）

SMALL_CAP = 1.5                                         # “小体积”：H.264 码率不超过原片的 1.5 倍

GIF_FPS_W = {"balanced": (12, 480), "high": (15, 720), "small": (10, 320)}

MPEG2_FPS = (24000 / 1001, 24, 25, 30000 / 1001, 30, 50, 60000 / 1001, 60)

# 目标容器能直接装下（不用重编码）的编码
REMUX = {  # target -> (视频编码, 音频编码)
    "mp4": ({"h264"}, {"aac", "mp3"}),
    "mp4-h265": ({"hevc"}, {"aac", "mp3"}),
    "mov": ({"h264"}, {"aac"}),
    "mkv": ({"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}, {"aac", "mp3", "opus", "vorbis", "ac3", "flac"}),
    "ts": ({"h264"}, {"aac", "mp3", "ac3"}),
    "flv": ({"h264"}, {"aac", "mp3"}),
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
}

MULTI_AUDIO = {"mp4", "mp4-h265", "mov", "mkv", "ts", "webm"}   # 这些容器保留全部音轨，其余只取第一条

HDR_CHAIN = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
             "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")

def snap_sr(info, limit):
    sr = info.get("sample_rate") or 44100
    return ["-ar", str(48000 if limit == 48000 and sr > 48000 else sr)] if sr > limit else []

# H.264 MP4 的“最大兼容”规格：Baseline 档（CAVLC、没有 B 帧，所以没有 ctts / 负 DTS）、yuv420p、按分辨率和帧率选的 level、AAC-LC 立体声 44.1/48k、
# moov 在前（faststart）、brand mp42、恒定帧率、每 2 秒一个关键帧、不带旋转标记。
# 在线预览（微信 / 腾讯文档 / 各家网页播放器）对 High 档、单声道、mp3-in-mp4、多音轨、旋转标记等都可能不买账。
LEVELS = ((3.0, 1620, 40500), (3.1, 3600, 108000), (4.0, 8192, 245760), (4.2, 8704, 522240),
          (5.1, 36864, 983040), (5.2, 36864, 2073600))   # (level, 每帧最大宏块数, 每秒最大宏块数)

def h264_level(w, h, fps):
    mbs = ((w + 15) // 16) * ((h + 15) // 16)
    for lv, max_frame, max_rate in LEVELS:
        if mbs <= max_frame and mbs * max(fps, 1) <= max_rate:
            return "%.1f" % lv
    return "5.2"

def cfr_rate(fps):
    for std, text in ((23.976, "24000/1001"), (29.97, "30000/1001"), (59.94, "60000/1001")):
        if abs(fps - std) < 0.03:
            return text
    return "%.3f" % fps

def mp4_compat_audio(i):
    """源的第一条音轨是否已经满足：AAC-LC、立体声、44.1k/48k（没有音轨也算满足）。"""
    ac = i.get("acodecs") or []
    if not ac:
        return True
    return (ac[0] == "aac" and i.get("aprofile") in ("LC", None) and i.get("channels") == 2
            and i.get("sample_rate") in (44100, 48000))

def mp4_compat_video(i):
    """源的视频是否已经满足 H.264 MP4 最大兼容规格，可以不重编码直接换封装。"""
    try:
        level = int(i.get("vlevel") or 0)
    except (TypeError, ValueError):
        level = 0
    return (i.get("vcodec") == "h264" and i.get("pix_fmt") == "yuv420p"
            and i.get("vprofile") in ("Baseline", "Constrained Baseline")
            and 0 < level <= 42 and not i.get("rotation") and (i.get("fps") or 0) <= 60.5)

def video_cmd(job):
    i, t, q = job.info, job.target, job.quality
    short = SCALES["video"][job.scale]
    vremux, aremux = REMUX.get(t, (set(), set()))
    # H.264 输出一律是 8 位 4:2:0（几乎所有设备/浏览器都能放）：10 位或 4:4:4 的 H.264 源即使目标是 MKV 也要重编码。
    # 其他编码（HEVC/VP9/AV1…）装进 MKV / MP4(H.265) / WebM 时原样保留位深。
    pix8 = i.get("pix_fmt") in ("yuv420p", "yuvj420p")
    copy_v = (not short and i.get("vcodec") in vremux and
              (pix8 or (i.get("vcodec") != "h264" and t in ("mkv", "mp4-h265", "webm"))))
    acodecs = i.get("acodecs") or []
    multi = t in MULTI_AUDIO and t != "mp4"                 # MP4(H.264) 只取第一条音轨，多音轨会让部分预览器出问题
    if not multi:
        acodecs = acodecs[:1]
    copy_a = bool(acodecs) and all(c in aremux for c in acodecs)
    if t == "mp4":
        copy_v = not short and mp4_compat_video(i)
        copy_a = bool(acodecs) and mp4_compat_audio(i)

    cmd = ["-map", "0:v:0", "-map", "0:a?" if multi else "0:a:0?", "-sn", "-dn", "-map_metadata", "0", "-map_chapters", "-1"]
    vf = []
    if t == "gif":
        fps, width = GIF_FPS_W[q]
        if i.get("hdr"):
            vf.append(HDR_CHAIN)
        vf.append("fps=%d,scale=w='min(iw,%d)':h=-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
                  "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" % (fps, width))
        return cmd[:2] + ["-an", "-vf", ",".join(vf), "-loop", "0", "-f", "gif"], True
    if copy_v:
        cmd += ["-c:v", "copy"]
        if t in ("mp4", "mp4-h265", "mov") and i.get("vcodec") == "hevc":
            cmd += ["-tag:v", "hvc1"]
    else:
        if i.get("hdr"):
            vf.append(HDR_CHAIN)
        if short:
            vf.append("scale=w='if(gt(iw,ih),-2,min(iw,%d))':h='if(gt(iw,ih),min(ih,%d),-2)'" % (short, short))
        vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        if t == "mpg":
            fps = i.get("fps") or 30
            cmd += ["-r", "%.5f" % min(MPEG2_FPS, key=lambda f: abs(f - fps))]
        cmd += ["-vf", ",".join(vf)]
        th = str(FFMPEG_THREADS)
        if t in ("mp4", "mov", "mkv", "ts", "flv"):
            cmd += ["-c:v", "libx264", "-preset", PRESET_X264[q], "-crf", str(CRF_X264[q]),
                    "-profile:v", "baseline" if t == "mp4" else "high", "-pix_fmt", "yuv420p", "-threads", th]
            if t == "mp4":
                fps = min(i.get("fps") or 30, 60)
                cmd += ["-level:v", h264_level(i.get("width") or 1920, i.get("height") or 1080, fps),
                        "-g", str(max(12, int(round(fps * 2)))),
                        "-fps_mode", "cfr", "-r", cfr_rate(fps)]      # 手机视频常是变帧率，统一成恒定帧率
            if q == "small" and i.get("bitrate"):
                cap = max(300_000, int(i["bitrate"] * SMALL_CAP))
                cmd += ["-maxrate", str(cap), "-bufsize", str(cap * 2)]
        elif t == "mp4-h265":
            cmd += ["-c:v", "libx265", "-preset", PRESET_X264[q], "-crf", str(CRF_X265[q]), "-pix_fmt", "yuv420p",
                    "-tag:v", "hvc1", "-threads", th, "-x265-params", "log-level=error"]
        elif t == "webm":
            cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(CRF_VP9[q]), "-row-mt", "1", "-cpu-used", "4",
                    "-deadline", "good", "-pix_fmt", "yuv420p", "-threads", th]
        elif t == "avi":
            cmd += ["-c:v", "mpeg4", "-vtag", "xvid", "-q:v", str(QV_MPEG[q]), "-pix_fmt", "yuv420p", "-threads", th]
        elif t == "wmv":
            cmd += ["-c:v", "wmv2", "-q:v", str(QV_MPEG[q]), "-pix_fmt", "yuv420p", "-threads", th]
        elif t == "mpg":
            cmd += ["-c:v", "mpeg2video", "-q:v", str(QV_MPEG[q]), "-pix_fmt", "yuv420p", "-threads", th]
    # 音频
    if copy_a:
        cmd += ["-c:a", "copy"]
    elif t == "webm":
        cmd += ["-c:a", "libopus", "-b:a", "128k", "-ar", "48000"]
    elif t == "avi":
        cmd += ["-c:a", "libmp3lame", "-q:a", {"balanced": "4", "high": "2", "small": "6"}[q]] + snap_sr(i, 48000)
    elif t == "wmv":
        cmd += ["-c:a", "wmav2", "-b:a", "192k", "-ac", "2"] + snap_sr(i, 48000)
    elif t == "mpg":
        cmd += ["-c:a", "mp2", "-b:a", "192k", "-ac", "2", "-ar", "48000"]
    elif t == "mp4":
        sr = 48000 if i.get("sample_rate") == 48000 else 44100
        cmd += ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "160k", "-ac", "2", "-ar", str(sr)]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"] + snap_sr(i, 96000)
    fmt = {"mp4": "mp4", "mp4-h265": "mp4", "mov": "mov", "mkv": "matroska", "ts": "mpegts", "flv": "flv",
           "webm": "webm", "avi": "avi", "wmv": "asf", "mpg": "mpeg"}[t]
    if fmt in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    if t == "mp4":
        cmd += ["-brand", "mp42"]       # 不要加 -use_editlist 0：会把声音的启动偏移揉进视频首帧，时间戳变得不均匀
    return cmd + ["-f", fmt], copy_v

def audio_cmd(job):
    i, t, q = job.info, job.target, job.quality
    cmd = ["-map", "0:a:0"]
    bits = i.get("bits") or 16
    ch = i.get("channels") or 2
    sr = i.get("sample_rate") or 44100
    if i.get("cover_idx") is not None and t in ("mp3", "m4a", "flac"):     # 保留封面图
        cmd += ["-map", "0:%d" % i["cover_idx"], "-c:v", "copy", "-disposition:v", "attached_pic"]
    else:
        cmd += ["-vn"]
    cmd += ["-sn", "-dn", "-map_metadata", "0"]
    stereo = ["-ac", "2"] if ch > 2 else []
    if t == "mp3":
        cmd += ["-c:a", "libmp3lame"] + (["-b:a", "320k"] if q == "high" else ["-q:a", "5" if q == "small" else "2"])
        cmd += stereo + snap_sr(i, 48000) + ["-id3v2_version", "3", "-f", "mp3"]
    elif t in ("m4a", "aac"):
        cmd += ["-c:a", "aac", "-b:a", {"balanced": "192k", "high": "256k", "small": "128k"}[q]] + snap_sr(i, 96000)
        cmd += ["-f", "ipod" if t == "m4a" else "adts"]
    elif t in ("wav", "aiff"):
        end = "le" if t == "wav" else "be"
        cmd += ["-c:a", "pcm_s%d%s" % (24 if bits > 16 else 16, end), "-f", t]
    elif t == "flac":
        cmd += ["-c:a", "flac", "-compression_level", "5"]
        cmd += ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"] if bits > 16 else ["-sample_fmt", "s16"]
        cmd += ["-f", "flac"]
    elif t == "ogg":
        cmd += ["-c:a", "libvorbis", "-q:a", {"balanced": "5", "high": "8", "small": "3"}[q], "-f", "ogg"]
    elif t == "opus":
        cmd += ["-c:a", "libopus", "-b:a", {"balanced": "128k", "high": "192k", "small": "64k"}[q], "-ar", "48000", "-f", "opus"]
        cmd += stereo
    elif t == "wma":
        cmd += ["-c:a", "wmav2", "-b:a", {"balanced": "192k", "high": "320k", "small": "128k"}[q], "-ac", "2"]
        cmd += snap_sr(i, 48000) + ["-f", "asf"]
    return cmd, False


# --------------------------------------------------------------------------- 图片（Pillow）
from PIL import Image, ImageOps, ImageSequence  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:      # 没装 HEIF 插件时 HEIC 读不了，其余照常
    pass

IMG_MAX_PIXELS = 100_000_000
MAX_FRAMES = 400
Image.init()      # 把所有插件注册进来，否则 formats 里的名字（如 MPO）可能还不存在
IN_FORMATS = [f for f in ("JPEG", "MPO", "PNG", "GIF", "BMP", "TIFF", "WEBP", "ICO", "HEIF", "AVIF") if f in Image.OPEN]
Image.MAX_IMAGE_PIXELS = IMG_MAX_PIXELS * 2


class ConvError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(msg)
        self.code = code


def die(code, msg):
    raise ConvError(code, msg)


def has_alpha(im):
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info) or "transparency" in im.info


def flatten(im):
    """去掉透明度：铺在白底上，转 RGB。"""
    if has_alpha(im):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return im.convert("RGB")


def to_rgb_or_rgba(im):
    return im.convert("RGBA" if has_alpha(im) else "RGB")


def convert_image(src, dst, target, quality, maxedge):
    """图片转换。失败抛 ConvError（code 2 不是图片 / 3 像素太多 / 5 其他）。"""
    try:
        im = Image.open(src, formats=IN_FORMATS)
        src_fmt = im.format
        w, h = im.size
    except Exception as e:
        die(2, "open: %s" % e)
    if w * h > IMG_MAX_PIXELS:
        die(3, "pixels")

    animated_ok = target in ("gif", "webp")
    n = min(getattr(im, "n_frames", 1), MAX_FRAMES)
    frames, durations = [], []
    try:
        if animated_ok and n > 1:
            for fr in ImageSequence.Iterator(im):
                durations.append(fr.info.get("duration", 100))
                frames.append(fr.convert("RGBA"))
                if len(frames) >= n:
                    break
            loop = im.info.get("loop", 0)
        else:
            first = ImageOps.exif_transpose(im)      # 按 EXIF 方向摆正，iPhone 照片不会躺着
            frames.append(first if first is not None else im)
            loop = 0
    except Exception as e:
        die(2, "decode: %s" % e)

    icc = im.info.get("icc_profile")
    exif = None
    try:
        exif = frames[0].getexif() if len(frames) == 1 else None
        if exif is not None and not len(exif):
            exif = None
    except Exception:
        exif = None

    def resize(fr):
        if maxedge and max(fr.size) > maxedge:
            fr = fr.copy()
            fr.thumbnail((maxedge, maxedge), Image.LANCZOS)
        return fr

    frames = [resize(f) for f in frames]
    out = frames[0]
    extra = {}
    if icc and target in ("jpg", "png", "webp", "tiff", "avif"):
        extra["icc_profile"] = icc
    if exif is not None and target in ("jpg", "png", "webp", "tiff", "avif"):
        extra["exif"] = exif

    try:
        if target == "jpg":
            flatten(out).save(dst, "JPEG", quality=quality, optimize=True, progressive=True, **extra)
        elif target == "png":
            m = out if out.mode in ("RGB", "RGBA", "L", "LA", "P", "I;16") else to_rgb_or_rgba(out)
            m.save(dst, "PNG", optimize=True, **extra)
        elif target == "webp":
            seq = [to_rgb_or_rgba(f) for f in frames]
            kw = dict(quality=quality, method=4, **extra)
            if len(seq) > 1:
                seq[0].save(dst, "WEBP", save_all=True, append_images=seq[1:], duration=durations, loop=loop, **kw)
            else:
                seq[0].save(dst, "WEBP", **kw)
        elif target == "gif":
            if len(frames) > 1:
                frames[0].save(dst, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                               loop=loop, disposal=2, optimize=False)
            else:
                to_rgb_or_rgba(out).save(dst, "GIF")
        elif target == "bmp":
            flatten(out).save(dst, "BMP")
        elif target == "tiff":
            m = out if out.mode in ("RGB", "RGBA", "L", "LA", "CMYK", "I;16") else to_rgb_or_rgba(out)
            m.save(dst, "TIFF", compression="tiff_lzw", **extra)
        elif target == "ico":
            rgba = out.convert("RGBA")
            side = max(rgba.size)
            if side > 256:
                rgba.thumbnail((256, 256), Image.LANCZOS)
                side = max(rgba.size)
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))     # 图标必须是正方形：居中补透明
            sq.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side] or [(side, side)]
            sq.save(dst, "ICO", sizes=sizes)
        elif target == "avif":
            to_rgb_or_rgba(out).save(dst, "AVIF", quality=quality, speed=6, **extra)
        else:
            die(5, "bad target")
    except ConvError:
        raise
    except MemoryError:
        die(3, "memory")
    except Exception as e:
        die(5, "save: %s" % e)
    return {"w": out.width, "h": out.height, "frames": len(frames), "src": src_fmt}


def probe(job):
    """ffprobe 校验并收集信息。返回 (info, 错误码)。"""
    cmd = [FFPROBE, "-v", "error", "-protocol_whitelist", "file",
           "-show_format", "-show_streams", "-of", "json", job.src]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        data = json.loads(r.stdout or b"{}")
    except (subprocess.TimeoutExpired, ValueError):
        return None, "PROBE_FAILED"
    if r.returncode != 0 or not data.get("streams"):
        return None, "PROBE_FAILED"
    streams = data["streams"]
    covers = [s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic")]
    vs = [s for s in streams if s.get("codec_type") == "video" and s not in covers]
    aud = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        dur = float(data.get("format", {}).get("duration") or (vs or aud or [{}])[0].get("duration") or 0)
    except ValueError:
        dur = 0.0
    info = {"duration": round(dur, 2), "has_video": bool(vs), "has_audio": bool(aud),
            "acodecs": [a.get("codec_name") for a in aud],
            "cover_idx": covers[0]["index"] if covers and covers[0].get("codec_name") in ("mjpeg", "png") else None}
    if aud:
        a = aud[0]
        try:
            info["aprofile"] = a.get("profile")
            info["sample_rate"] = int(a.get("sample_rate") or 0)
            info["channels"] = int(a.get("channels") or 0)
            info["bits"] = int(a.get("bits_per_raw_sample") or 0) or (16 if a.get("sample_fmt") in ("u8", "u8p", "s16", "s16p") else 24 if a.get("sample_fmt") in ("s32", "s32p", "s64", "s64p") else 16)
        except ValueError:
            info["sample_rate"], info["channels"], info["bits"] = 44100, 2, 16
    if vs:
        v = vs[0]
        try:
            vbr = int(v.get("bit_rate") or 0) or int(float(data.get("format", {}).get("bit_rate") or 0))
        except ValueError:
            vbr = 0
        fps = 0.0
        try:
            x, y = (v.get("avg_frame_rate") or "0/1").split("/")
            fps = float(x) / float(y) if float(y) else 0.0
        except ValueError:
            pass
        info.update({"bitrate": vbr, "vcodec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"),
                     "pix_fmt": v.get("pix_fmt"), "fps": round(fps, 3), "hdr": v.get("color_transfer") in HDR_TRANSFERS,
                     "vprofile": v.get("profile"), "vlevel": v.get("level"), "rotation": video_rotation(v)})
        if not info["width"] or not info["height"] or info["width"] * info["height"] > MAX_PIXELS:
            return info, "TOO_LARGE_RES"
    if job.cat == "video" and not vs:
        return info, "NO_VIDEO"
    if job.cat == "audio" and not aud:
        return info, "NO_AUDIO"
    if dur <= 0:
        return info, "PROBE_FAILED"
    if job.target == "gif" and job.cat == "video" and dur > MAX_GIF_SECONDS:
        return info, "TOO_LONG_GIF"
    return info, None


# --------------------------------------------------------------------------- 类别 / ffmpeg 路径
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".wmv", ".asf", ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".3gp", ".3g2", ".ogv", ".rmvb", ".rm", ".f4v", ".dav"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif", ".mka", ".amr", ".ape", ".ac3", ".m4b", ".caf", ".silk"}
IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".heic", ".heif", ".avif"}
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def set_ffmpeg_dir(d):
    """指定 ffmpeg / ffprobe 所在目录（程序自带或下载到本机的那份）。"""
    global FFMPEG, FFPROBE
    exe = ".exe" if sys.platform == "win32" else ""
    FFMPEG, FFPROBE = os.path.join(d, "ffmpeg" + exe), os.path.join(d, "ffprobe" + exe)


def kind_of(path):
    """按扩展名猜类别：video / audio / image；不认识返回 None。"""
    e = os.path.splitext(path)[1].lower()
    return "video" if e in VIDEO_EXT else "audio" if e in AUDIO_EXT else "image" if e in IMAGE_EXT else None


def targets_for(kind):
    """这类文件能转成什么：[(key, 显示名, 扩展名)]。"""
    out = []
    for table in ALLOWED.get(kind, []):
        for k, (ext, _mime) in table.items():
            out.append((k, k.upper().replace("-H265", "（H.265）") if k != "mp4-h265" else "MP4（H.265）", ext))
    return out


class Job:
    """一个转换任务：src 输入，out 输出，其余是选项；info 由 probe 填。"""

    def __init__(self, src, out, kind, target, quality="balanced", scale="orig"):
        self.src, self.out, self.kind, self.target = src, out, kind, target
        self.quality, self.scale = quality, scale
        cat = target_spec(kind, target)
        if not cat:
            raise ValueError("不支持的目标格式")
        self.cat = cat[0]
        self.info = {}
        self.cancel = False
        self.proc = None


def build_cmd(job):
    body, _copy = video_cmd(job) if job.cat == "video" else audio_cmd(job)
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-protocol_whitelist", "file", "-i", job.src] + body
    return cmd + ["-progress", "pipe:1", "-nostats", job.out]


def run_ffmpeg(job, progress=lambda f, eta: None):
    """跑 ffmpeg；progress(0~1, 剩余秒)。成功返回 None，失败返回错误文字。"""
    dur = job.info.get("duration") or 0
    tmp = job.out + ".part"
    real_out = job.out
    job.out = tmp
    try:
        cmd = build_cmd(job)
    finally:
        job.out = real_out
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         creationflags=CREATE_NO_WINDOW)
    job.proc = p
    err = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t.start()
    prog, speed = 0.0, 0.0
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("out_time_us="):
            try:
                tm = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                continue
            if dur:
                prog = max(0.0, min(0.999, tm / dur))
                progress(prog, int(max(0.0, dur * (1 - prog)) / speed) if speed else -1)
        elif line.startswith("speed="):
            try:
                speed = float(line.split("=", 1)[1].rstrip("x ").strip())
            except ValueError:
                pass
    rc = p.wait()
    t.join(2)
    job.proc = None
    if job.cancel:
        _rm(tmp)
        return "已取消"
    if rc != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        _rm(tmp)
        tail = (err[0] if err else b"")[-300:].decode("utf-8", "replace")
        return "转换失败：" + (tail.strip() or "ffmpeg 退出码 %s" % rc)
    os.replace(tmp, real_out)
    progress(1.0, 0)
    return None


def _rm(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def cancel(job):
    job.cancel = True
    p = job.proc
    if p:
        try:
            p.kill()
        except OSError:
            pass


IMG_ERR = {2: "不是受支持的图片", 3: "图片像素太多", 5: "转换失败"}


def run_job(job, progress=lambda f, eta: None):
    """完整流程：校验 → 转换。成功返回 None，失败返回中文错误。"""
    try:
        if job.cat == "image":
            q = {"balanced": 85, "high": 95, "small": 70}[job.quality]
            edge = SCALES["image"][job.scale] or 0
            tmp = job.out + ".part"
            try:
                convert_image(job.src, tmp, job.target, q, edge)
            except ConvError as e:
                _rm(tmp)
                return IMG_ERR.get(e.code, "转换失败") + ("（%s）" % e if str(e) else "")
            os.replace(tmp, job.out)
            progress(1.0, 0)
            return None
        info, bad = probe(job)
        job.info = info or {}
        if bad:
            return {"PROBE_FAILED": "读不出这个文件（不是音视频，或者已损坏）", "NO_VIDEO": "文件里没有视频画面",
                    "NO_AUDIO": "文件里没有音频", "TOO_LARGE_RES": "分辨率太大", "TOO_LONG_GIF": "做 GIF 的视频不能超过 %d 秒" % MAX_GIF_SECONDS}.get(bad, bad)
        return run_ffmpeg(job, progress)
    except OSError as e:
        return "找不到 ffmpeg 或无法运行：%s" % e
