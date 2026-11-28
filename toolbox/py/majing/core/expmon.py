# -*- coding: utf-8 -*-
"""实验记录：自动发现各台服务器上正在用显存的训练进程，读它们的日志算出进度条和预计结束时间，跑完自动归档。不调用任何模型。

流程（每台 Linux + NVIDIA 主机，每分钟一次，只跑命令、不开 SFTP）：
1. 一次 ssh 命令：nvidia-smi 看显卡和 compute-apps，再用 /proc/*/fd 找“打开了 /dev/nvidia*”的进程（容器里 nvidia-smi 看不到进程，这条路照样行），
   取出每个进程的用户、工作目录、启动命令、已运行秒数、stdout/stderr 重定向到的文件；
2. 筛出深度学习训练进程（python 且不是 Jupyter / 编辑器后台等），同一用户+目录+命令的多卡/多进程合成一个实验，开始时间 = 最老的进程的启动时间；
3. 找日志：优先 stdout/stderr 重定向的文件，其次在工作目录、脚本目录、命令里的输出目录下找最近改过的 *.log / *.txt / nohup* 等；
4. 读日志头尾，交给 logprog 算进度/阶段/预计结束；进程消失后再读一次，判成 完成 / 出错 / 中断。
记录存在 %APPDATA%\\MajingToolbox\\experiments.json。"""
import hashlib
import json
import logging
import os
import re
import shlex
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from majing.core import expnote, logprog, sshhosts
from majing.settings import _path, settings

log = logging.getLogger("majing.exp")

INTERVAL = 60                 # 后台轮询间隔（秒）
MIN_SECS = 120                # 跑满这么久才算“实验”（避开几十秒的测试/推理脚本）；或者连续两次采样都在
NOTE_V = 2                  # 一句话说明的版本：提示词改了就加一，旧说明会重新生成一次
ABSENT_N = 2                  # 连续几次没看到进程才算结束
MAX_ITEMS = 600
TAIL_BYTES = 200000
HEAD_BYTES = 12000
RELOOK = 300                  # 没找到有进度的日志时，多久重新找一次
MEM_MIN = 300                 # 显存总占用低于这个值（MiB）就当没人在跑

_SCRIPT = r"""
export LC_ALL=C
echo '@@MJ#GPU'
nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || { echo '@@MJ#NOGPU'; exit 0; }
echo '@@MJ#APPS'
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits 2>/dev/null
pids=$( { nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null; find /proc/[0-9]*/fd -maxdepth 1 -lname '/dev/nvidia[0-9]*' 2>/dev/null | cut -d/ -f3; } | tr -d ' ' | grep -E '^[0-9]+$' | sort -un | head -80)
echo '@@MJ#PROCS'
for p in $pids; do
  [ -r /proc/$p/cmdline ] || continue
  st=$(ps -o user:24= -o ppid= -o etimes= -p $p 2>/dev/null)
  [ -n "$st" ] || continue
  set -- $st
  u=$1; pp=$2; et=$3
  cwd=$(readlink /proc/$p/cwd 2>/dev/null)
  o1=$(readlink /proc/$p/fd/1 2>/dev/null)
  o2=$(readlink /proc/$p/fd/2 2>/dev/null)
  cvd=$(tr '\0' '\n' </proc/$p/environ 2>/dev/null | grep -m1 '^CUDA_VISIBLE_DEVICES=' | cut -d= -f2)
  pc=$(tr '\0\n\t' '   ' </proc/$pp/cmdline 2>/dev/null | cut -c1-400)
  cm=$(tr '\0\n\t' '   ' </proc/$p/cmdline 2>/dev/null | cut -c1-1500)
  printf '@@MJ#P\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$p" "$u" "$pp" "$et" "$cwd" "$o1" "$o2" "$cvd" "$pc" "$cm"
done
echo '@@MJ#END'
"""

_SKIP_CMD = re.compile(r"ipykernel|jupyter|spyder|code-server|vscode|pylance|pyright|streamlit|gradio|tensorboard|-m\s+http\.server|\bpython[\d.]*\s+-c\b|gpustat|nvitop|nvidia-smi|ray::|wandb-service|\bpip\b", re.I)
_PY_CMD = re.compile(r"python|torchrun|deepspeed|accelerate|colossalai|horovodrun", re.I)
_DIR_ARGS = re.compile(r"--?(?:save[_-]?dir|log[_-]?dir|logdir|output[_-]?dir|outdir|out[_-]?dir|exp[_-]?dir|work[_-]?dir|result[_-]?dir|results[_-]?dir|ckpt[_-]?dir|checkpoints?[_-]?dir|model[_-]?dir|save[_-]?path|log[_-]?path|exp[_-]?path|save[_-]?folder)[=\s]+(\S+)", re.I)
_CFG_ARGS = re.compile(r"(?:(?:^|\s)-(?:opt|c)|--?(?:config|cfg|cfg[_-]?file|yaml|opt|option|conf|config[_-]?file))[=\s]+(\S+\.(?:ya?ml|json|py|cfg|toml))", re.I)
_BAD_DIRS = re.compile(r"^/(?:|root|home/[^/]+|usr(?:/.*)?|opt|var(?:/.*)?|etc|proc|sys|dev|lib(?:64)?|bin|sbin|tmp)/?$")


def _store_file():
    return os.path.join(os.path.dirname(_path()), "experiments.json")


def _norm_cmd(cmd):
    c = re.sub(r"--?local[_-]rank[=\s]+\d+", "", cmd or "")
    return re.sub(r"\s+", " ", c).strip()


def _abs(p, cwd):
    p = (p or "").strip("'\"")
    if not p or p.startswith("-"):
        return ""
    if p.startswith("~"):
        return ""
    if not p.startswith("/"):
        p = (cwd.rstrip("/") + "/" + p) if cwd else ""
    # 规整 ./ 和 ../
    parts = []
    for x in p.split("/"):
        if x in ("", "."):
            continue
        if x == "..":
            if parts:
                parts.pop()
            continue
        parts.append(x)
    return "/" + "/".join(parts) if parts else ""


def _dirs_of(cmd, cwd):
    """可能放日志的目录：工作目录、脚本所在目录、命令里指定的输出目录（及其上一级）。"""
    ds = []
    if cwd and not _BAD_DIRS.match(cwd):
        ds.append(cwd)
    m = re.search(r"(\S+\.py)\b", cmd or "")
    if m:
        sp = _abs(m.group(1), cwd)
        if sp:
            d = os.path.dirname(sp)
            if d and not _BAD_DIRS.match(d) and d not in ds:
                ds.append(d)
    for m in _DIR_ARGS.finditer(cmd or ""):
        d = _abs(m.group(1), cwd)
        if d and not _BAD_DIRS.match(d) and d not in ds:
            ds.append(d)
    return ds[:5]


def _cfg_paths(cmd, cwd):
    out = []
    for m in _CFG_ARGS.finditer(cmd or ""):
        p = _abs(m.group(1), cwd)
        if p and p not in out:
            out.append(p)
    return out[:2]


_INC = re.compile(r"(?:__include__|_base_)\s*[:=]\s*(\[[^\]]*\]|['\"][^'\"]+['\"])")


def _includes(text, cfg_path):
    """配置里的 __include__ / _base_（RT-DETR、mmdet 一类把总轮数放在被引用的文件里）→ 绝对路径列表。"""
    base = os.path.dirname(cfg_path)
    out = []
    for m in _INC.finditer(text or ""):
        for q in re.findall(r"['\"]([^'\"]+\.(?:ya?ml|py|json|toml))['\"]", m.group(1)):
            p = _abs(q, base)
            if p and p not in out:
                out.append(p)
    return out[:6]


def _is_file_target(t):
    return bool(t) and t.startswith("/") and not t.startswith(("/dev/", "/proc/")) and not t.endswith(" (deleted)")


def parse_round1(out):
    """解析 _SCRIPT 的输出。返回 None = 没有 NVIDIA 显卡；否则 {"gpus": [...], "apps": {...}, "procs": [...]}。"""
    if "@@MJ#NOGPU" in out or "@@MJ#GPU" not in out:
        return None
    sec = None
    gpus, apps, procs = [], {}, []
    for ln in out.splitlines():
        if ln.startswith("@@MJ#"):
            tag = ln[5:].split("\t")[0].strip()
            if tag == "P":
                p = ln.split("\t")
                if len(p) >= 11:
                    try:
                        procs.append({"pid": int(p[1]), "user": p[2], "ppid": int(p[3] or 0), "etimes": int(p[4] or 0), "cwd": p[5], "out1": p[6], "out2": p[7],
                                      "cvd": p[8], "pcmd": p[9], "cmd": "\t".join(p[10:]).strip()})
                    except ValueError:
                        pass
                continue
            sec = tag
            continue
        if sec == "GPU":
            q = [x.strip() for x in ln.split(",")]
            if len(q) >= 6 and q[0].isdigit():
                def _n(x):
                    try:
                        return int(float(x))
                    except ValueError:
                        return 0
                gpus.append({"index": int(q[0]), "uuid": q[1], "name": ", ".join(q[2:-3]), "mem_used": _n(q[-3]), "mem_total": _n(q[-2]), "util": _n(q[-1])})
        elif sec == "APPS":
            q = [x.strip() for x in ln.split(",")]
            if len(q) >= 3 and q[0].isdigit():
                apps.setdefault(int(q[0]), []).append((q[1], int(float(q[2] or 0))))
    return {"gpus": gpus, "apps": apps, "procs": procs}


def build_groups(info, now):
    """把进程合成实验：同一用户 + 目录 + 命令（去掉 local_rank）= 一个实验。只留深度学习训练进程。"""
    uuid2idx = {g["uuid"]: g["index"] for g in info["gpus"]}
    groups = {}
    for p in info["procs"]:
        cmd = p["cmd"]
        if not cmd or not _PY_CMD.search(cmd) or _SKIP_CMD.search(cmd):
            continue
        key = (p["user"], p["cwd"], _norm_cmd(cmd))
        g = groups.get(key)
        if not g:
            g = groups[key] = {"user": p["user"], "cwd": p["cwd"], "cmd": _norm_cmd(cmd), "pids": [], "etimes": 0, "gpus": set(), "mem": 0, "pcmd": p["pcmd"], "outs": []}
        g["pids"].append(p["pid"])
        if p["etimes"] >= g["etimes"]:
            g["etimes"] = p["etimes"]
            g["pcmd"] = p["pcmd"]
        for o in (p["out1"], p["out2"]):
            if _is_file_target(o) and o not in g["outs"]:
                g["outs"].append(o)
        for uu, mem in info["apps"].get(p["pid"], []):
            if uu in uuid2idx:
                g["gpus"].add(uuid2idx[uu])
            g["mem"] += mem
        if p["cvd"] and not info["apps"].get(p["pid"]):
            for x in p["cvd"].split(","):
                x = x.strip()
                if x.isdigit():
                    g["gpus"].add(int(x))
    out = []
    for g in groups.values():
        g["gpus"] = sorted(g["gpus"])
        g["start"] = now - g["etimes"]
        g["pid"] = min(g["pids"])
        # 命令展示：如果是 torchrun / accelerate 之类拉起来的，带上启动器的整条命令更完整
        if re.search(r"torchrun|torch\.distributed|accelerate|deepspeed|horovodrun|mpirun", g["pcmd"] or "") and "train" in (g["pcmd"] or "").lower() + g["cmd"].lower():
            g["launcher"] = g["pcmd"].strip()
        out.append(g)
    if len(out) == 1 and not out[0]["gpus"]:
        out[0]["gpus"] = [x["index"] for x in info["gpus"] if x["mem_used"] >= MEM_MIN]
    return out


def _round2_script(reqs):
    """reqs: [{key, files:[路径], dirs:[目录], cfg:[配置文件], head:bool}] → 一条 sh 脚本，输出带标记的头尾片段。"""
    s = ["export LC_ALL=C",
         "dump(){ f=$1; hb=$2; tb=$3; [ -f \"$f\" ] || return; echo \"@@MJ#F $f\"; echo \"@@MJ#S $(stat -c '%s %Y' \"$f\" 2>/dev/null)\"; echo '@@MJ#H'; [ \"$hb\" -gt 0 ] && head -c $hb \"$f\" 2>/dev/null; echo; echo '@@MJ#T'; tail -c $tb \"$f\" 2>/dev/null; echo; echo '@@MJ#E'; }",
         "cfgdump(){ f=$1; [ -f \"$f\" ] || return; echo \"@@MJ#C $f\"; head -c 40000 \"$f\" 2>/dev/null; echo; echo '@@MJ#E'; }",
         "disc(){ for d in \"$@\"; do [ -d \"$d\" ] && timeout 6 find \"$d\" -maxdepth 4 \\( -name '.*' -o -name node_modules -o -name __pycache__ -o -name datasets -o -name site-packages \\) -prune -o -type f \\( -name '*.log' -o -name '*.out' -o -name '*.err' -o -name '*.txt' -o -name 'nohup*' -o -name 'log*' \\) -mmin -240 -size +0 -printf '%T@ %p\\n' 2>/dev/null; done | sort -rn | head -4 | cut -d' ' -f2-; }"]
    for r in reqs:
        s.append("echo '@@MJ#X %s'" % r["key"])
        hb = HEAD_BYTES if r.get("head") else 0
        for f in r.get("files") or []:
            s.append("dump %s %d %d" % (shlex.quote(f), hb, TAIL_BYTES))
        if r.get("dirs"):
            s.append("disc %s | while IFS= read -r f; do dump \"$f\" %d %d; done" % (" ".join(shlex.quote(d) for d in r["dirs"]), HEAD_BYTES, 80000))
        for f in r.get("cfg") or []:
            s.append("cfgdump %s" % shlex.quote(f))
    s.append("echo '@@MJ#END'")
    return "\n".join(s)


def parse_round2(out):
    """→ {key: {"files": [{path,size,mtime,head,tail}], "cfg": "配置文本"}}。"""
    res = {}
    cur = None
    mode = None
    buf = []
    f = None
    cfgpath = None
    for ln in out.split("\n"):
        if ln.startswith("@@MJ#"):
            tag = ln[5:]
            if tag.startswith("X "):
                cur = res.setdefault(tag[2:].strip(), {"files": [], "cfg": ""})
                mode = None
                continue
            if cur is None:
                continue
            if tag.startswith("F "):
                f = {"path": tag[2:], "size": 0, "mtime": 0, "head": "", "tail": ""}
                cur["files"].append(f)
                mode = None
            elif tag.startswith("S ") and f is not None:
                q = tag[2:].split()
                if len(q) >= 2 and q[0].isdigit() and q[1].isdigit():
                    f["size"], f["mtime"] = int(q[0]), int(q[1])
            elif tag == "H":
                mode, buf = "H", []
            elif tag == "T":
                if mode == "H" and f is not None:
                    f["head"] = "\n".join(buf)
                mode, buf = "T", []
            elif tag.startswith("C "):
                mode, buf, cfgpath = "C", [], tag[2:]
            elif tag == "E":
                if mode == "T" and f is not None:
                    f["tail"] = "\n".join(buf)
                elif mode == "C":
                    cur["cfg"] += "\n".join(buf) + "\n"
                    cur.setdefault("cfgs", {})[cfgpath] = "\n".join(buf)
                mode, buf = None, []
            continue
        if mode:
            buf.append(ln)
    return res


class Monitor:
    def __init__(self):
        self.emit = lambda t, d=None: None
        self.items = []                  # 全部记录（运行中 + 已结束）
        self._lock = threading.RLock()
        self._busy = False
        self._skip = {}                  # alias -> 到期时间（没 GPU / Windows 主机，一阵子不再试）
        self.hosts = {}                  # alias -> {gpus: [...], t}：最近一次看到的显卡情况
        self._pending = {}               # (alias, key) -> 首次看到的时间
        self._mem = {}                   # rec id -> 内存里的运行时数据（head 文本、上次找日志的时间…）
        self.last_poll = 0
        self.enabled = True
        self._loaded = False
        self._started = False
        self._nq = queue.Queue()         # 等着生成一句话说明的实验（一个个来，别同时开好几个 claude）
        self.ai = {"ok": None, "error": "", "kind": ""}

    # ---------------------------------------------------------------- 存取
    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(_store_file(), encoding="utf-8") as f:
                d = json.load(f)
            self.items = d.get("items", []) if isinstance(d, dict) else []
        except Exception:               # noqa: BLE001
            self.items = []

    def _save(self):
        try:
            tmp = _store_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": self.items[-MAX_ITEMS:]}, f, ensure_ascii=False)
            os.replace(tmp, _store_file())
        except Exception as e:          # noqa: BLE001
            log.warning("保存实验记录失败：%s", e)

    def start(self, emit):
        self.emit = emit
        with self._lock:
            self._load()
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._note_loop, daemon=True).start()

    def state(self):
        with self._lock:
            self._load()
            return {"items": [self._pub(r) for r in self.items], "hosts": dict(self.hosts), "last_poll": self.last_poll, "busy": self._busy, "enabled": self.enabled,
                    "ai": {"mode": self._mode(), **self.ai}}

    @staticmethod
    def _pub(r):
        d = dict(r)
        d.pop("hist", None)
        return d

    def _loop(self):
        time.sleep(15)
        while True:
            try:
                if self.enabled:
                    self.poll_all()
            except Exception as e:      # noqa: BLE001
                log.warning("实验轮询出错：%s", e)
            time.sleep(INTERVAL)

    # ---------------------------------------------------------------- 轮询
    def poll_all(self, force=False):
        with self._lock:
            if self._busy:
                return False
            if not force and time.time() - self.last_poll < 10:
                return False
            self._busy = True
        try:
            st = sshhosts.load_status()
            hosts = [h["alias"] for h in sshhosts.list_hosts() if (st.get(h["alias"]) or {}).get("ok")]
            now = time.time()
            hosts = [a for a in hosts if self._skip.get(a, 0) <= now]
            with ThreadPoolExecutor(max_workers=5) as ex:
                list(ex.map(self._poll_safe, hosts))
        finally:
            with self._lock:
                self._busy = False
                self.last_poll = int(time.time())
                self._save()
        self.emit("exp:update", self.state())
        return True

    def _poll_safe(self, alias):
        try:
            self.poll_host(alias)
        except Exception as e:           # noqa: BLE001
            log.warning("实验采样 %s 失败：%s", alias, e)
            sshhosts.drop_exec(alias)

    def poll_host(self, alias):
        now = time.time()
        try:
            c = sshhosts.exec_client(alias)
        except Exception as e:           # noqa: BLE001
            log.info("实验采样 %s 第一次连接失败（%s），重试一次", alias, e)
            time.sleep(1.5)
            c = sshhosts.exec_client(alias)
        if sshhosts.detect_os(c) == "Windows":
            self._skip[alias] = now + 3600
            return
        code, out, err = sshhosts._run(c, "sh -c " + shlex.quote(_SCRIPT), 40)
        info = parse_round1(out)
        if info is None:
            self._skip[alias] = now + 600
            return
        with self._lock:
            self.hosts[alias] = {"t": int(now), "gpus": [{"index": g["index"], "name": g["name"], "mem_used": g["mem_used"], "mem_total": g["mem_total"], "util": g["util"]} for g in info["gpus"]]}
        groups = build_groups(info, now) if sum(g["mem_used"] for g in info["gpus"]) >= MEM_MIN or info["procs"] else []
        self._merge(alias, c, groups, now)

    # ---------------------------------------------------------------- 合并
    @staticmethod
    def _same(rec, g):
        return rec["user"] == g["user"] and rec["cwd"] == g["cwd"] and _norm_cmd(rec["cmd"]) == g["cmd"] and abs(rec["start"] - g["start"]) < 600

    def _merge(self, alias, c, groups, now):
        with self._lock:
            self._load()
            running = [r for r in self.items if r["alias"] == alias and r["status"] == "running"]
        matched = []
        reqs = []
        todo = {}                        # key -> (rec|None, group)
        for g in groups:
            rec = next((r for r in running if self._same(r, g)), None)
            if rec is None:
                pk = (alias, g["user"], g["cwd"], g["cmd"])
                first = self._pending.setdefault(pk, now)
                if g["etimes"] < MIN_SECS and now - first < 30:
                    continue                                     # 刚出现，先观察一轮（跑满 2 分钟，或连续两次采样都在才记）
                rec = self._new_rec(alias, g, now)
                with self._lock:
                    self.items.append(rec)
                self._pending.pop(pk, None)
            matched.append(rec["id"])
            todo[rec["id"]] = (rec, g)
            reqs.append(self._req_for(rec, g, now))
        lost = []
        for r in running:
            if r["id"] in matched:
                r["absent"] = 0
                continue
            r["absent"] = r.get("absent", 0) + 1
            if r["absent"] >= ABSENT_N:
                lost.append(r)
                reqs.append(self._req_for(r, None, now))
        # 清掉已经不在的 pending
        keys_now = {(alias, g["user"], g["cwd"], g["cmd"]) for g in groups}
        for pk in [k for k in self._pending if k[0] == alias and k not in keys_now]:
            self._pending.pop(pk, None)
        data = {}
        if reqs:
            try:
                code, out, err = sshhosts._run(c, "sh -c " + shlex.quote(_round2_script(reqs)), 60)
                data = parse_round2(out)
            except Exception as e:       # noqa: BLE001
                log.warning("读 %s 的日志失败：%s", alias, e)
        for rid, (rec, g) in todo.items():
            self._update_running(rec, g, data.get(rid) or {}, now)
        for r in lost:
            self._finish(r, data.get(r["id"]) or {}, now)

    def _new_rec(self, alias, g, now):
        rid = hashlib.sha1(("%s|%s|%s|%s|%d" % (alias, g["user"], g["cwd"], g["cmd"], int(g["start"]))).encode("utf-8")).hexdigest()[:12]
        return {"id": rid, "alias": alias, "user": g["user"], "cwd": g["cwd"], "cmd": g["cmd"], "launcher": g.get("launcher", ""), "name": logprog.guess_name(g["cmd"], g["cwd"]),
                "gpus": g["gpus"], "mem": g["mem"], "pid": g["pid"], "start": int(g["start"]), "end": None, "status": "running", "frac": None, "label": "", "stage": "启动中",
                "eta_ts": None, "eta_src": None, "last_line": "", "metrics": {}, "log": "", "log_ok": False, "error": "", "updated": int(now), "seen": int(now), "absent": 0, "hist": []}

    def _req_for(self, rec, g, now):
        mem = self._mem.setdefault(rec["id"], {})
        r = {"key": rec["id"], "files": [], "dirs": [], "cfg": [], "head": False}
        if g and g["outs"]:
            r["files"] = list(g["outs"])[:2]
        elif rec.get("log") and rec.get("log_ok"):
            r["files"] = [rec["log"]]
        else:
            if not r["files"] and rec.get("log"):
                r["files"] = [rec["log"]]
            if now - mem.get("looked", 0) > RELOOK:
                r["dirs"] = _dirs_of(rec["cmd"], rec["cwd"])
                mem["looked"] = now
        if mem.get("cfg_more"):
            r["cfg"] = mem["cfg_more"][:4]
            mem["cfg_more"] = mem["cfg_more"][4:]
        if "total" not in mem:
            r["cfg"] = _cfg_paths(rec["cmd"], rec["cwd"])
            r["head"] = True
        elif not mem.get("head"):
            r["head"] = True
        return r

    def _update_running(self, rec, g, d, now):
        mem = self._mem.setdefault(rec["id"], {})
        files = d.get("files") or []
        for cp, ct in (d.get("cfgs") or {}).items():
            seen = mem.setdefault("cfg_seen", set())
            seen.add(cp)
            if len(seen) < 14:
                more = [x for x in _includes(ct, cp) if x not in seen]
                mem["cfg_more"] = (mem.get("cfg_more") or []) + [x for x in more if x not in (mem.get("cfg_more") or [])]
        if d.get("cfg"):
            mem["cfg_extra"] = mem.get("cfg_extra", "") + d["cfg"]
            mem["cfg"] = mem["cfg_extra"]
            m = re.search(r"(?m)^name:\s*['\"]?([\w.\-]{2,60})", d["cfg"])           # BasicSR 一类的 yml 里有 name:，比文件名更像实验名
            if m:
                rec["name"] = m.group(1)
        cfg = mem.get("cfg", "")
        best = None
        for f in files:
            if f.get("head"):
                mem.setdefault("heads", {})[f["path"]] = f["head"]
            head = mem.get("heads", {}).get(f["path"], "")
            a = logprog.analyze(head, f["tail"], rec["cmd"], cfg, now=now, mtime=f["mtime"] or None, started=rec["start"])
            score = (1 if f["path"].startswith(rec["cwd"].rstrip("/") + "/") else 0, 1 if a["frac"] is not None else 0, 1 if a["label"] else 0, f["mtime"])
            if best is None or score > best[0]:
                best = (score, f, a)
        mem["total"] = True
        self._want_note(rec, mem)
        if g:
            rec["gpus"], rec["mem"], rec["pid"] = g["gpus"] or rec["gpus"], g["mem"] or rec["mem"], g["pid"]
            if g.get("launcher"):
                rec["launcher"] = g["launcher"]
        rec["seen"] = rec["updated"] = int(now)
        with self._lock:
            hg = (self.hosts.get(rec["alias"]) or {}).get("gpus") or []
        if hg:
            rec["gpu_model"] = hg[0]["name"]
        if best:
            _, f, a = best
            rec["log"] = f["path"]
            if a["frac"] is not None or a["label"]:
                rec["log_ok"] = True
            mem["head"] = bool(mem.get("heads", {}).get(f["path"]))
            self._apply(rec, a, now)
        else:
            rec["stage"] = "启动中（还没找到日志）" if (now - rec["start"]) < 300 else "运行中（没找到日志，无法判断进度）"

    def _apply(self, rec, a, now):
        rec["frac"], rec["label"], rec["stage"] = a["frac"], a["label"], a["stage"]
        rec["last_line"], rec["metrics"] = a["last_line"], a["metrics"]
        rec["error"] = a["error"] if rec["status"] != "running" else rec.get("error", "")
        # 预计结束：日志 eta > 日志时间戳速度 > 采样历史里的速度 > 启动以来的平均速度
        eta_s, src = a["eta_s"], a["eta_src"]
        hist = rec.setdefault("hist", [])
        if a["frac"] is not None and rec["status"] == "running":
            if not hist or abs(hist[-1][1] - a["frac"]) > 1e-6 or now - hist[-1][0] > 600:
                hist.append([int(now), round(a["frac"], 6)])
                del hist[:-80]
            if src in (None, "elapsed", "epoch-eta") and len(hist) >= 3:
                w = [x for x in hist if now - x[0] <= 7200] or hist
                dt, df = w[-1][0] - w[0][0], w[-1][1] - w[0][1]
                if dt >= 180 and df > 0:
                    eta_s, src = (1 - a["frac"]) * dt / df, "rate"
        rec["eta_ts"] = int(now + eta_s) if eta_s is not None else None
        rec["eta_src"] = src

    def _finish(self, rec, d, now):
        files = d.get("files") or []
        mem = self._mem.get(rec["id"], {})
        a = None
        mtime = None
        for f in files:
            head = mem.get("heads", {}).get(f["path"], "")
            a = logprog.analyze(head, f["tail"], rec["cmd"], mem.get("cfg", ""), now=now, mtime=f["mtime"] or None, started=rec["start"])
            mtime = f["mtime"]
            break
        self._want_note(rec, mem)
        rec["status"] = "stopped"
        if a:
            self._apply(rec, a, now)
            rec["error"] = a["error"]
            fr = a["frac"]
            if a["finished"] or (fr is not None and fr >= 0.985):
                rec["status"] = "done"
                rec["frac"] = 1.0 if (fr is None or fr >= 0.985) else fr
            elif a["error"]:
                rec["status"] = "failed"
            else:
                rec["status"] = "stopped"
        end = rec.get("seen") or int(now)
        if mtime and rec["start"] <= mtime <= now:
            end = max(end, mtime) if mtime - end < 3600 else end
        rec["end"] = int(min(end, now))
        rec["eta_ts"] = None
        rec["stage"] = {"done": "已完成", "failed": "出错退出", "stopped": "已结束（中途退出）"}[rec["status"]]
        rec["updated"] = int(now)
        self._mem.pop(rec["id"], None)
        rec.pop("hist", None)

    # ---------------------------------------------------------------- 一句话实验说明（Haiku，提取成功一次就不再提取）
    def _want_note(self, rec, mem):
        if rec.get("note_v") == NOTE_V or self._mode() == "off":
            return
        now = time.time()
        if mem.get("note_q") or now < mem.get("note_next", 0) or mem.get("note_tries", 0) >= 8:
            return
        heads = mem.get("heads") or {}
        ctx = {"cmd": rec["cmd"], "launcher": rec.get("launcher", ""), "cwd": rec["cwd"], "cfg": mem.get("cfg", ""),
               "head": next(iter(heads.values()), ""), "tail": rec.get("last_line", "")}
        mem["note_q"] = True
        self._nq.put((rec["id"], ctx))

    def _note_loop(self):
        while True:
            rid, ctx = self._nq.get()
            try:
                self._note_one(rid, ctx)
            except Exception as e:      # noqa: BLE001
                log.warning("生成实验说明出错：%s", e)

    def _note_one(self, rid, ctx):
        with self._lock:
            rec = next((r for r in self.items if r["id"] == rid), None)
        mem = self._mem.setdefault(rid, {})
        mode = self._mode()
        if not rec or rec.get("note_v") == NOTE_V or mode == "off":
            mem["note_q"] = False
            return
        ok, text, kind = expnote.ask(ctx, mode)
        mem["note_q"] = False
        if ok:
            with self._lock:
                rec["note"], rec["note_v"] = text, NOTE_V
                self.ai = {"ok": True, "error": "", "kind": ""}
                self._save()
            log.info("实验说明 %s：%s", rec["name"], text)
        else:
            mem["note_tries"] = mem.get("note_tries", 0) + 1
            mem["note_next"] = time.time() + min(900 * mem["note_tries"], 7200)
            self.ai = {"ok": False, "error": text, "kind": kind}
            log.info("实验说明失败（%s）：%s", kind, text)
        self.emit("exp:update", self.state())

    @staticmethod
    def _mode():
        v = settings.get("exp_ai", "haiku")
        return "haiku" if v is True else "off" if v is False else (v if v in ("off", "haiku", "gpt") else "haiku")

    def set_ai(self, mode):
        mode = mode if mode in ("off", "haiku", "gpt") else "off"
        settings.set("exp_ai", mode)
        if mode != "off":                # 重新打开：之前失败攒下的退避清掉，马上试
            for m in self._mem.values():
                m.pop("note_next", None)
                m["note_tries"] = 0
        self.emit("exp:update", self.state())

    # ---------------------------------------------------------------- 给界面的操作
    def remove(self, rid):
        with self._lock:
            self.items = [r for r in self.items if r["id"] != rid]
            self._save()
        self.emit("exp:update", self.state())

    def clear_finished(self):
        with self._lock:
            self.items = [r for r in self.items if r["status"] == "running"]
            self._save()
        self.emit("exp:update", self.state())

    def tail_log(self, rid, lines=300):
        with self._lock:
            rec = next((r for r in self.items if r["id"] == rid), None)
        if not rec or not rec.get("log"):
            return {"ok": False, "error": "这个实验没有找到日志文件。"}
        try:
            c = sshhosts.exec_client(rec["alias"])
            code, out, err = sshhosts._run(c, "tail -c 60000 %s | tr '\\r' '\\n' | tail -n %d" % (shlex.quote(rec["log"]), int(lines)), 30)
        except Exception as e:           # noqa: BLE001
            return {"ok": False, "error": "连不上 %s：%s" % (rec["alias"], e)}
        return {"ok": True, "path": rec["log"], "text": logprog._clean(out)}


monitor = Monitor()
