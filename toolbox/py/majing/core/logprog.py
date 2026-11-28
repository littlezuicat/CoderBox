# -*- coding: utf-8 -*-
"""训练日志 → 进度（纯规则，不调用任何模型）。

每个作者的日志都不一样：有的按 iter（BasicSR、MMagic、FFA-Net、KAIR），有的按 epoch（一千个 epoch 每个一行），有的是 tqdm 进度条，
有的 epoch + 轮内 batch 都有。这里的做法是不认“某个仓库的格式”，而是：
1. 从每一行里抽出所有“像进度”的数字：`epoch 3/100`、`Iter [1000/300000]`、`step :1234/20000`、tqdm 条、`epoch: 12, iter: 1,000`、`eta: 1 day, 2:03:04` 等；
2. 总数优先取日志里的 `n/总数`，没有就从启动命令、配置文件、日志开头的参数打印里找（`--epochs 200`、`total_iter: 300000`、`max_epochs=100`）；
3. 判断计数器是“全局 iter”还是“轮内 batch”（看 epoch 变化时它是归零还是接着涨），统一换算成 0~1 的进度；
4. 预计结束时间：日志自带的 eta > 日志时间戳算出来的速度 > 从启动到现在的平均速度（粗估）。
认不出来就老实说认不出来（frac=None），界面画不确定进度条。"""
import datetime
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
N = r"(\d[\d,_]*(?:\.\d+)?)"


def _int(s):
    try:
        return int(float(str(s).replace(",", "").replace("_", "")))
    except ValueError:
        return None


def _flt(s):
    try:
        return float(str(s).replace(",", "").replace("_", ""))
    except ValueError:
        return None


# ---- 行内模式 ----
RE_EPOCH_RATIO = re.compile(r"\b(?:epochs?|ep)\b[^\d\n]{0,10}" + N + r"\s*/\s*" + N, re.I)
RE_EPOCH_MM = re.compile(r"\bepoch\b\W*(?:\(\w+\))?\W*\[\s*(\d+)\s*\]\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]", re.I)        # mmcv：Epoch [3][100/500]
RE_EPOCH_ONE = re.compile(r"\b(?:epochs?|ep)\b[^\d\n]{0,6}?" + N + r"(?!\s*/)(?![\d.]*\s*/)", re.I)
RE_ITER_RATIO = re.compile(r"\b(iters?|iterations?|steps?|updates?|global[_ ]?steps?|itr|it|batch(?:es)?)\b[^\d\n]{0,8}?(?:\(\w+\)[^\d\n]{0,6})?" + N + r"\s*/\s*" + N, re.I)
RE_ITER_ONE = re.compile(r"\b(iters?|iterations?|steps?|updates?|global[_ ]?steps?|itr)\b[^\d\n]{0,6}?" + N + r"(?!\s*/)(?![\d.]*\s*/)", re.I)
RE_TQDM = re.compile(r"(?:(\d{1,3})%\|[^|\n]*\|\s*)?(\d[\d,]*)/(\d[\d,]*)\s*\[\s*((?:\d+:)?\d+:\d+)\s*<\s*((?:\d+:)?\d+:\d+|\?)")
RE_ETA = re.compile(r"\beta\b\W{0,3}(?:(\d+)\s*days?,?\s*)?(\d+):(\d{2}):(\d{2})", re.I)
RE_ETA2 = re.compile(r"\b(?:remaining|time left|eta)\b\W{0,3}(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?)\b", re.I)
RE_PCT = re.compile(r"\((\d{1,3})\s*%\)|\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:complete|done|finished)", re.I)               # Train Epoch: 3 [1200/6000 (20%)]
RE_TS = [
    (re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})[ T](\d{2}):(\d{2}):(\d{2})"), 1),
    (re.compile(r"(?<![\d/-])(\d{2})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})"), 2),                                  # KAIR：23-11-20 10:21:33.123
    (re.compile(r"(?<![\d/-])(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})"), 3),                                          # mmengine：11/20 10:21:33
]
RE_ERR = re.compile(r"Traceback \(most recent call last\)|CUDA out of memory|OutOfMemoryError|RuntimeError:|\bKilled\b|Segmentation fault|NCCL (?:error|Error)|\bAssertionError|\bKeyError|\bValueError|\bFileNotFoundError|\bImportError|\bModuleNotFoundError|Error:")
RE_DONE = re.compile(r"training (?:finished|complete[d]?|done|ended)|finished training|train(?:ing)? (?:is )?(?:over|finish)|end of training|all (?:done|epochs? finished)|optimization finished|done training", re.I)
RE_EVAL_DONE = re.compile(r"(?:test|eval(?:uation)?|inference|testing)\s+(?:finished|complete[d]?|done)|(?:test|eval(?:uation)?|overall|final)\s+(?:averages?|results?|summary|metrics)\b|\baverages?\s*[:=]|\bsummary\b", re.I)   # 仅评测脚本用
RE_INTR = re.compile(r"KeyboardInterrupt|\bTerminated\b|\bInterrupted\b|Aborted \(core dumped\)")        # 被人中断
RE_EVAL_CMD = re.compile(r"(?:^|[\s/\\])[\w.\-]*(?:eval|evaluate|test|infer|inference|predict|benchmark|metric)[\w.\-]*\.py\b|\.py\s+(?:eval|evaluate|test|infer|predict)\b", re.I)


def is_eval_cmd(cmd):
    """命令是不是评测 / 推理脚本（跑完就退出，没有“总轮数”，不能按训练那套判进度）。只看脚本名和子命令。"""
    return bool(RE_EVAL_CMD.search(cmd or ""))
RE_VAL = re.compile(r"valid|\bval\b|evaluat|\btest(?:ing)?\b|# *validation|psnr|ssim|\bmetric", re.I)
RE_SAVE = re.compile(r"sav(?:ing|ed)\b.{0,40}(?:model|ckpt|checkpoint|state|weight|net|\.pth|\.pt\b|\.safetensors)|checkpoint.{0,20}sav", re.I)
RE_INIT = re.compile(r"\bload(?:ing|ed)\b|\bbuild(?:ing)?\b|prepar|dataset|data ?loader|total params|#params|number of param|parameters|initiali[sz]", re.I)
RE_PSNR = re.compile(r"psnr\W{0,6}(\d+(?:\.\d+)?)", re.I)
RE_SSIM = re.compile(r"ssim\W{0,6}(\d?\.\d+)", re.I)
RE_LOSS = re.compile(r"\b(?:total[_ ])?loss(?:[_ ][A-Za-z]\w*)?\W{0,6}(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", re.I)

# 命令/配置里的总数：键名 → 类型
TOTAL_KEYS = [
    ("epoch", r"(?:epoches|niter|num[_-]?train[_-]?epochs?|train[_-]?epochs?|max[_-]?epochs?|total[_-]?epochs?|num[_-]?epochs?|n[_-]?epochs?|nepochs?|epochs?|epoch[_-]?num|max[_-]?epoch|n[_-]?epoch)"),
    ("iter", r"(?:total[_-]?iters?|max[_-]?iters?|num[_-]?iters?|n[_-]?iters?|train[_-]?iters?|iterations?|max[_-]?steps?|total[_-]?steps?|num[_-]?steps?|train[_-]?steps?|train[_-]?num[_-]?steps|steps|iters)"),
]
DECAY_KEYS = r"(?:n[_-]?epochs?[_-]?decay|niter[_-]?decay|epochs?[_-]?decay|decay[_-]?epochs?)"


def _clean(text):
    text = ANSI.sub("", text or "")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _secs(hms):
    """'1:02:03' / '02:03' → 秒。"""
    p = [int(x) for x in hms.split(":")]
    s = 0
    for x in p:
        s = s * 60 + x
    return s


def parse_ts(line):
    now = datetime.datetime.now()
    for rx, kind in RE_TS:
        m = rx.search(line)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        try:
            if kind == 1:
                d = datetime.datetime(g[0], g[1], g[2], g[3], g[4], g[5])
            elif kind == 2:
                d = datetime.datetime(2000 + g[0], g[1], g[2], g[3], g[4], g[5])
            else:
                d = datetime.datetime(now.year, g[0], g[1], g[2], g[3], g[4])
            return d.timestamp()
        except ValueError:
            continue
    return None


def find_totals(*texts):
    """从命令行、配置文件、日志开头里找“总 epoch / 总 iter”。返回 {'epoch': n, 'iter': n}（找不到的键不给）。"""
    found = {}
    for kind, keys in TOTAL_KEYS:
        rx = re.compile(r"(?<![\w.])--?(?:" + keys + r")(?![\w-])[=\s:]+['\"]?(\d[\d,]*)", re.I)          # 命令行：--epochs 200 / --epochs=200
        rx2 = re.compile(r"(?<![\w.-])['\"]?(?:" + keys + r")['\"]?\s*[:=]\s*['\"]?(\d[\d,]*)(?![\d.])", re.I)   # 配置/参数打印：total_iter: 300000、epochs=200、'epochs': 200
        for t in texts:
            if not t:
                continue
            for r in (rx, rx2):
                ms = [_int(m.group(1)) for m in r.finditer(t)]
                ms = [x for x in ms if x and x > 0]
                if ms and kind not in found:
                    found[kind] = ms[0] if r is rx else ms[0]
            if kind in found:
                break
    # CycleGAN / pix2pix：总轮数 = n_epochs + n_epochs_decay
    if "epoch" in found:
        dec = re.compile(r"(?<![\w.])--?" + DECAY_KEYS + r"[=\s:]+(\d+)", re.I)
        for t in texts:
            m = t and dec.search(t)
            if m:
                found["epoch"] += int(m.group(1))
                break
    return found


class Rec:
    __slots__ = ("i", "ts", "epoch", "epoch_tot", "epoch_float", "batch", "it", "it_tot", "it_label", "tq", "eta", "pct", "line")

    def __init__(self, i, line):
        self.i, self.line = i, line
        self.ts = None
        self.epoch = self.epoch_tot = None
        self.epoch_float = False
        self.batch = None            # (cur, tot) 来自 mmcv 的 [3][100/500] 或 batch 标签
        self.it = self.it_tot = None
        self.it_label = ""
        self.tq = None               # (n, tot, elapsed_s, remain_s|None)
        self.eta = None
        self.pct = None


def parse_line(i, line):
    r = Rec(i, line)
    r.ts = parse_ts(line)
    m = RE_EPOCH_MM.search(line)
    if m:
        r.epoch = _int(m.group(1))
        r.batch = (_int(m.group(2)), _int(m.group(3)))
    else:
        m = RE_EPOCH_RATIO.search(line)
        if m and _int(m.group(2)) and _int(m.group(1)) is not None and _int(m.group(1)) <= _int(m.group(2)) + 1:
            r.epoch, r.epoch_tot = _int(m.group(1)), _int(m.group(2))
        else:
            m = RE_EPOCH_ONE.search(line)
            if m:
                v = _flt(m.group(1))
                if v is not None:
                    r.epoch_float = abs(v - round(v)) > 1e-9 or "." in m.group(1)
                    r.epoch = v if r.epoch_float else int(v)
    m = RE_ITER_RATIO.search(line)
    if m and _int(m.group(3)) and _int(m.group(2)) is not None and _int(m.group(2)) <= _int(m.group(3)) + 1:
        lab = m.group(1).lower()
        if lab.startswith("batch"):
            r.batch = (_int(m.group(2)), _int(m.group(3)))
        else:
            r.it, r.it_tot, r.it_label = _int(m.group(2)), _int(m.group(3)), lab
    else:
        m = RE_ITER_ONE.search(line)
        if m and _int(m.group(2)) is not None:
            r.it, r.it_label = _int(m.group(2)), m.group(1).lower()
    m = RE_TQDM.search(line)
    if m and re.search(r"\b(?:val|valid|validation|validating|test|testing|eval|evaluating|evaluation|infer|inference)\b", line[:m.start()] + line[m.end():m.end() + 40], re.I):
        m = None                   # 验证/测试用的进度条不是训练进度
    if m:
        n, tot = _int(m.group(2)), _int(m.group(3))
        if tot and n is not None and n <= tot:
            rem = None if m.group(5) == "?" else _secs(m.group(5))
            r.tq = (n, tot, _secs(m.group(4)), rem)
    if r.it is None and r.batch is None:
        # 形如 “Train Epoch: 3 [1200/6000 (20%)]”：方括号里的 n/总数 当作轮内 batch
        m = re.search(r"\[\s*(\d[\d,]*)\s*/\s*(\d[\d,]*)\s*(?:\(\s*\d+%\s*\))?\s*\]", line)
        if m and _int(m.group(2)) and _int(m.group(1)) is not None and _int(m.group(1)) <= _int(m.group(2)):
            r.batch = (_int(m.group(1)), _int(m.group(2)))
    m = RE_ETA.search(line)
    if m:
        r.eta = int(m.group(1) or 0) * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
    else:
        m = RE_ETA2.search(line)
        if m:
            v = float(m.group(1))
            r.eta = int(v * (3600 if m.group(2).lower().startswith("h") else 60))
    return r


def _has_progress(r):
    return r.epoch is not None or r.it is not None or r.batch is not None or r.tq is not None


def _inner_is_per_epoch(recs):
    """轮内计数器（iter / tqdm）是不是每个 epoch 归零。None = 看不出来。"""
    last_e, last_v = None, None
    votes_reset = votes_grow = 0
    for r in recs:
        v = r.it if r.it is not None else (r.tq[0] if r.tq else None)
        if r.epoch is not None:
            if last_e is not None and r.epoch != last_e and v is not None and last_v is not None:
                if v < last_v:
                    votes_reset += 1
                elif v > last_v:
                    votes_grow += 1
            last_e = r.epoch
        if v is not None:
            last_v = v
    if votes_reset or votes_grow:
        return votes_reset >= votes_grow
    return None


def _eta_scope(pts):
    """日志里的 eta 是整个训练剩余的（mmcv / BasicSR），还是当前这一轮剩余的（RT-DETR / DETR 一类的 MetricLogger）？
    看同一轮里 eta 随轮内进度怎么降：每轮的 eta ≈ 轮长×(1-进度)，整个训练的 eta 还要再加上后面所有轮。返回 (范围, 估计的每轮耗时秒)。"""
    pts = pts[-60:]
    lens = []
    for a, b in zip(pts, pts[1:]):
        if a[0] == b[0] and b[1] - a[1] >= 0.02 and a[2] > b[2]:
            lens.append((a[2] - b[2]) / (b[1] - a[1]))
    if not lens:
        return None, None
    lens.sort()
    ln = lens[len(lens) // 2]
    last = pts[-1]
    pred = ln * (1 - last[1])
    if abs(last[2] - pred) <= 0.35 * max(pred, 60) + 30:
        return "epoch", ln
    if last[2] > pred + 0.5 * ln:
        return "total", ln
    return None, ln


def analyze(head, tail, cmd="", cfg_text="", now=None, mtime=None, started=None):
    """分析一个实验的日志。head 是日志开头一段，tail 是结尾一大段（可含 \\r 刷新的进度条）。
    返回字典：frac(0~1/None)、label(界面显示的进度说明)、eta_s、eta_src、stage、last_line、metrics、error、finished。"""
    import time as _t
    now = now or _t.time()
    lines = [x for x in _clean(tail).split("\n") if x.strip()]
    lines = lines[-4000:]
    out = {"frac": None, "label": "", "eta_s": None, "eta_src": None, "stage": "", "last_line": "", "metrics": {}, "error": "", "finished": False, "rate": None, "kind": None}
    if not lines:
        out["stage"] = "启动中（还没有日志输出）"
        return out
    out["last_line"] = lines[-1].strip()[-220:]
    recs = [parse_line(i, ln) for i, ln in enumerate(lines)]
    prog = [r for r in recs if _has_progress(r)]
    head_recs = [parse_line(i, ln) for i, ln in enumerate([x for x in _clean(head).split("\n") if x.strip()][:400])]
    totals = find_totals(cmd, cfg_text, _clean(head)[:20000])

    # ---- 指标
    for key, rx in (("psnr", RE_PSNR), ("ssim", RE_SSIM), ("loss", RE_LOSS)):
        for ln in reversed(lines[-200:]):
            m = rx.search(ln)
            if m:
                out["metrics"][key] = m.group(1)
                break

    # ---- 阶段 / 错误 / 结束
    tail_text = "\n".join(lines[-60:])
    em = None
    for ln in reversed(lines[-80:]):
        if RE_ERR.search(ln):
            em = ln.strip()[:200]
            break
    out["error"] = em or ""
    out["finished"] = bool(RE_DONE.search("\n".join(lines[-40:])))
    if not out["finished"] and is_eval_cmd(cmd):
        out["finished"] = bool(RE_EVAL_DONE.search("\n".join(lines[-8:])))
    out["interrupted"] = bool(RE_INTR.search("\n".join(lines[-40:])))
    if out["interrupted"] and is_eval_cmd(cmd):
        out["finished"] = False                   # 评测被人中断，不算跑完
    last_prog_i = prog[-1].i if prog else -1
    stage = ""
    for ln_i in range(len(lines) - 1, max(-1, len(lines) - 25), -1):
        if ln_i <= last_prog_i:
            break
        ln = lines[ln_i]
        if RE_SAVE.search(ln):
            stage = "保存模型"
            break
        if RE_VAL.search(ln):
            stage = "验证 / 测试中"
            break
    if not stage:
        stage = "训练中" if prog else ("加载数据 / 构建模型" if any(RE_INIT.search(x) for x in lines[-15:]) else "运行中（没认出进度）")
    out["stage"] = stage

    if not prog:
        return out

    # ---- 总数与模式
    epoch_tot = None
    for r in reversed(prog):
        if r.epoch_tot:
            epoch_tot = r.epoch_tot
            break
    if epoch_tot is None:
        epoch_tot = totals.get("epoch")
    it_tot = None
    for r in reversed(prog):
        if r.it_tot:
            it_tot = r.it_tot
            break
    it_declared = totals.get("iter")
    has_epoch = any(r.epoch is not None for r in prog)
    per_epoch = _inner_is_per_epoch(prog)
    # 轮内计数器：batch（mmcv 样式）一定是轮内；iter / tqdm 要看归零情况
    iter_global = False
    if any(r.it is not None for r in prog):
        if per_epoch is True:
            iter_global = False
        elif per_epoch is False:
            iter_global = True
        else:
            iter_global = (not has_epoch) or (it_declared is not None and it_tot == it_declared) or (it_tot is not None and not any(r.epoch_tot for r in prog) and it_tot > 5000) or (it_tot is None and it_declared is not None)
    # 0 起还是 1 起
    firsts = [r.epoch for r in head_recs if r.epoch is not None and not r.epoch_float][:3] or [r.epoch for r in prog if r.epoch is not None and not r.epoch_float][:3]
    base = 0 if (firsts and min(firsts) == 0) else 1
    seen_zero = any(r.epoch == 0 for r in prog if not r.epoch_float)
    if seen_zero:
        base = 0

    mode = None
    I_total = it_tot or it_declared
    if iter_global and I_total:
        mode = "iter"
    elif has_epoch and epoch_tot:
        mode = "epoch"
    elif iter_global is False and any(r.it is not None for r in prog) and not has_epoch and I_total:
        mode = "iter"
    elif any(r.tq for r in prog):
        mode = "bar"
    elif any(r.batch for r in prog):
        mode = "bar"

    # ---- 逐行换算进度（带“向前沿用”：epoch 和 batch 分在不同行时也能拼起来）
    series = []
    eta_pts = []
    cur_e = cur_it = cur_inner = None
    cur_e_float = False
    last_label = ""
    for r in prog:
        if r.epoch is not None:
            cur_e, cur_e_float = r.epoch, r.epoch_float
            if r.tq is None and r.batch is None and r.it is None:
                cur_inner = None
        if r.it is not None:
            cur_it = r.it
        inner = None
        if r.batch:
            inner = r.batch[0] / r.batch[1]
        elif r.tq and (has_epoch or not iter_global) and not (mode == "iter"):
            inner = r.tq[0] / r.tq[1]
        elif r.it is not None and r.it_tot and not iter_global:
            inner = r.it / r.it_tot
        if inner is not None:
            cur_inner = inner
        f = None
        if mode == "iter" and cur_it is not None:
            f = cur_it / I_total
        elif mode == "epoch" and cur_e is not None:
            if cur_e_float:
                f = cur_e / epoch_tot
            elif cur_inner is not None and (r.batch or r.tq or r.it is not None):
                f = (cur_e - base + cur_inner) / epoch_tot
            else:
                f = (cur_e - base + 1) / epoch_tot
        elif mode == "bar":
            if r.tq:
                f = r.tq[0] / r.tq[1]
            elif r.batch:
                f = r.batch[0] / r.batch[1]
        if f is not None:
            series.append((r, max(0.0, min(1.0, f))))
        if r.eta is not None and cur_inner is not None and cur_e is not None and (r.batch or r.tq or r.it_tot):
            eta_pts.append((cur_e, cur_inner, r.eta))
    if not series:
        # 认出了数字但算不出进度（缺总数）：给个说明
        lastr = prog[-1]
        bits = []
        if lastr.epoch is not None:
            bits.append("epoch %s" % (int(lastr.epoch) if not lastr.epoch_float else lastr.epoch))
        if lastr.it is not None:
            bits.append("iter %s" % format(lastr.it, ","))
        out["label"] = " · ".join(bits) + "（总数没识别到）" if bits else ""
        return out
    lastr, frac = series[-1]
    out["frac"] = frac
    out["kind"] = mode

    # ---- 说明文字
    if mode == "iter":
        cur = lastr.it if lastr.it is not None else cur_it
        out["label"] = "iter %s / %s" % (format(cur, ","), format(I_total, ","))
        if has_epoch and cur_e is not None:
            out["label"] += "（epoch %s）" % (int(cur_e) if not cur_e_float else cur_e)
    elif mode == "epoch":
        out["label"] = "epoch %s / %s" % (int(cur_e) if not cur_e_float else cur_e, epoch_tot)
    else:
        n, t = (lastr.tq[0], lastr.tq[1]) if lastr.tq else (lastr.batch[0], lastr.batch[1])
        if totals.get("epoch") and t in (totals["epoch"], totals["epoch"] + 1):          # 进度条的总数正好等于总 epoch：这是整个训练的进度条（DehazeFormer 一类）
            out["label"] = "epoch %s / %s" % (format(n, ","), format(t, ","))
        elif totals.get("iter") and t == totals["iter"]:
            out["label"] = "iter %s / %s" % (format(n, ","), format(t, ","))
        else:
            out["label"] = "进度条 %s / %s" % (format(n, ","), format(t, ","))

    # ---- 预计结束
    eta = None
    src = None
    # a) 日志自带 eta（BasicSR / mmcv / MMagic 都有）
    for r in reversed(prog[-30:]):
        if r.eta is not None:
            eta = r.eta
            if mtime and r.i >= len(lines) - 12:
                eta = max(0, eta - max(0, now - mtime))
            src = "log"
            break
    if src == "log" and mode == "epoch" and epoch_tot and eta_pts and not cur_e_float:
        scope, ln = _eta_scope(eta_pts)
        if scope == "epoch":
            inner_now = eta_pts[-1][1]
            if ln is None or ln <= 0:
                ln = eta / max(0.03, 1 - inner_now)
            left_epochs = max(0, epoch_tot - (cur_e - base) - 1)
            eta = eta + left_epochs * ln
            src = "epoch-eta"
    # b) 日志时间戳算速度
    pts = [(r.ts, f) for r, f in series if r.ts is not None]
    rate = None
    if len(pts) >= 3:
        pts = pts[-400:]
        half = pts[len(pts) // 2:] if len(pts) >= 8 else pts
        dt = half[-1][0] - half[0][0]
        df = half[-1][1] - half[0][1]
        if dt >= 60 and df > 0:
            rate = df / dt
    if rate and src in (None, "epoch-eta"):
        eta, src = (1 - frac) / rate, "rate"
    if rate:
        out["rate"] = rate
    if eta is None and mode == "epoch" and epoch_tot and not cur_e_float and lastr.tq and lastr.tq[3] is not None and lastr.tq[0] < lastr.tq[1]:
        el, rem = lastr.tq[2], lastr.tq[3]
        ln = el + rem
        left_epochs = max(0, epoch_tot - (cur_e - base) - 1)
        eta, src = rem + left_epochs * ln, "epoch-eta"
    # c) tqdm 自带剩余时间（只在“只有进度条”时可靠）
    if eta is None and mode == "bar" and lastr.tq and lastr.tq[3] is not None:
        eta, src = lastr.tq[3], "log"
    # d) 从启动到现在的平均速度（粗估：中途续训、验证耗时都会让它不准）
    if eta is None and started and frac > 0.02:
        el = max(0, now - started)
        if el > 120:
            eta, src = el * (1 - frac) / frac, "elapsed"
    if frac >= 0.995:
        eta, src = 0, src or "log"
    out["eta_s"] = None if eta is None else int(eta)
    out["eta_src"] = src
    return out


def guess_name(cmd, cwd=""):
    """从命令里猜一个实验名：优先 -opt xxx.yml / --config xxx.yaml / --exp_name，其次脚本名 + 目录名。"""
    import os
    c = cmd or ""
    for rx in (r"(?:^|\s)-opt[=\s]+(\S+)", r"--(?:exp[_-]?name|name|exp|experiment|run[_-]?name|tag)[=\s]+(\S+)", r"--(?:config|cfg|cfg[_-]?file|yaml|opt|option|conf)[=\s]+(\S+)", r"(?:^|\s)-c[=\s]+(\S+\.(?:ya?ml|json))"):
        m = re.search(rx, c)
        if m:
            v = m.group(1).strip("'\"")
            stem = os.path.splitext(os.path.basename(v.rstrip("/")))[0] if re.search(r"\.(?:ya?ml|json|py|cfg|toml)$", v) else os.path.basename(v.rstrip("/"))
            if stem and not stem.startswith("-"):
                return stem[:60]
    m = re.search(r"(\S+\.py)\b", c)
    script = os.path.splitext(os.path.basename(m.group(1)))[0] if m else "train"
    proj = os.path.basename((cwd or "").rstrip("/")) or ""
    return ("%s · %s" % (proj, script) if proj and proj != script else script)[:60]


def fmt_dur(sec):
    sec = int(max(0, sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return "%d天%d小时" % (d, h)
    if h:
        return "%d小时%d分" % (h, m)
    return "%d分钟" % max(1, m)
