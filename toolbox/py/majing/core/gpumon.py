# -*- coding: utf-8 -*-
"""GPU 采样：每台能连上的服务器跑一次 nvidia-smi，得到每张卡的利用率/显存/温度。
只在用户打开 GPU 总览（或主机列表的迷你条）时采样，页面开着期间由界面每 60 秒要求采一次；页面关了就不再采样。后端不自己跑定时器。
Windows 主机同样只读显卡占用（Windows 的 nvidia-smi 看不到进程）。"""
import logging
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from majing.core import sshhosts

log = logging.getLogger("majing.gpu")

NOGPU_TTL = 600        # 判定“没有 NVIDIA 显卡”之后多久再试一次

_LINUX_SCRIPT = r"""
nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits || exit 3
"""
_WIN_CMD = "nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits"


def _num(s, default=0.0):
    try:
        return float(str(s).strip())
    except ValueError:
        return default


def _parse_gpus(text):
    gpus = []
    for ln in text.splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) < 7 or not p[0].isdigit():
            continue
        gpus.append({"index": int(p[0]), "uuid": p[1], "name": ", ".join(p[2:-4]) if len(p) > 7 else p[2],
                     "util": int(_num(p[-4])), "mem_used": int(_num(p[-3])), "mem_total": int(_num(p[-2])), "temp": int(_num(p[-1]))})
    return gpus


class Monitor:
    def __init__(self):
        self.emit = lambda t, d=None: None
        self.samples = {}                  # alias -> 最近一次采样
        self.os = {}                       # alias -> "linux"/"windows"
        self.nogpu = {}                    # alias -> 到期时间
        self._lock = threading.RLock()
        self._busy = False

    def start(self, emit):
        self.emit = emit

    def state(self):
        with self._lock:
            return {"samples": dict(self.samples)}

    def sample_all(self):
        """采样一次所有已连接的主机（界面要求时调用：打开页面、手动刷新、每 60 秒）。同一时间只跑一轮。"""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        try:
            st = sshhosts.load_status()
            hosts = [h["alias"] for h in sshhosts.list_hosts() if (st.get(h["alias"]) or {}).get("ok")]
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(self.poll_one, hosts))
        finally:
            with self._lock:
                self._busy = False
        return True

    def poll_one(self, alias):
        now = time.time()
        if self.nogpu.get(alias, 0) > now:
            return
        try:
            try:
                c = sshhosts.exec_client(alias)
            except Exception as e:                           # noqa: BLE001  偶发的连接失败，等一下再试一次
                log.info("采样 %s 第一次连接失败（%s），重试一次", alias, e)
                time.sleep(1.5)
                c = sshhosts.exec_client(alias)
            sysname = self.os.get(alias)
            if sysname is None:
                sysname = "windows" if sshhosts.detect_os(c) == "Windows" else "linux"
                self.os[alias] = sysname
            if sysname == "linux":
                code, out, err = sshhosts._run(c, "sh -c " + shlex.quote(_LINUX_SCRIPT), 20)
                if code == 3 or "not found" in err or "command not found" in err:
                    return self._no_gpu(alias)
            else:
                code, out, err = sshhosts._run(c, _WIN_CMD, 20)
                if code != 0:
                    return self._no_gpu(alias)
            gpus = _parse_gpus(out)
            if not gpus:
                return self._no_gpu(alias)
        except Exception as e:                               # noqa: BLE001
            log.warning("采样 %s 失败：%s", alias, e)
            sshhosts.drop_exec(alias)
            with self._lock:
                self.samples[alias] = {"t": int(time.time()), "state": "error", "error": str(e)[:200], "gpus": []}
            self.emit("gpu:sample", {"alias": alias, "sample": self.samples[alias]})
            return
        sample = {"t": int(time.time()), "state": "ok", "os": sysname, "gpus": gpus}
        with self._lock:
            self.samples[alias] = sample
        self.emit("gpu:sample", {"alias": alias, "sample": sample})

    def _no_gpu(self, alias):
        self.nogpu[alias] = time.time() + NOGPU_TTL
        with self._lock:
            self.samples[alias] = {"t": int(time.time()), "state": "nogpu", "gpus": []}
        self.emit("gpu:sample", {"alias": alias, "sample": self.samples[alias]})


monitor = Monitor()
