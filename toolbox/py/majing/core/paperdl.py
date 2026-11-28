# -*- coding: utf-8 -*-
"""paperdl —— 码境工具箱的论文检索/下载客户端。

服务端：worker 服务器上的 paperdl-service（FastAPI）
        https://code.zuicat.cn/paperdl/  → 反代 127.0.0.1:8800
流程：   输入文章名 → 服务端 S2 检索并判定出版商 → 建下载任务 →
        服务器侧 fetcher 领任务抓 PDF 并回传 → 客户端按 job_id 拉文件
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = os.environ.get("PAPERDL_BASE", "https://code.zuicat.cn/paperdl")
DEFAULT_TIMEOUT = 60


class PaperDLError(RuntimeError):
    pass


def _req(path, base=DEFAULT_BASE, method="GET", payload=None, timeout=DEFAULT_TIMEOUT, raw=False):
    url = base.rstrip("/") + path
    data = None
    headers = {"User-Agent": "MajingToolbox/paperdl"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if raw:
                return body
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise PaperDLError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise PaperDLError(f"网络错误: {e.reason}") from None


def health(base=DEFAULT_BASE):
    """服务存活 + 队列概况"""
    return _req("/health", base)


def search(title, limit=12, base=DEFAULT_BASE):
    """按文章名检索，返回带出版商分类的候选列表"""
    data = _req("/api/search", base, "POST", {"title": title, "limit": limit})
    return data.get("items") or []


def submit(doi=None, title=None, base=DEFAULT_BASE):
    """建下载任务，返回 job_id"""
    payload = {}
    if doi:
        payload["doi"] = doi
    if title:
        payload["title"] = title
    if not payload:
        raise PaperDLError("doi 或 title 至少给一个")
    return _req("/api/jobs", base, "POST", payload)


def status(job_id, base=DEFAULT_BASE):
    """查任务状态：pending / running / done / failed"""
    return _req(f"/api/jobs/{job_id}", base)


def wait(job_id, timeout=300, interval=3, base=DEFAULT_BASE, on_tick=None):
    """轮询直到完成，返回最终状态 dict"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = status(job_id, base)
        if on_tick:
            on_tick(st)
        if st.get("status") in ("done", "failed"):
            return st
        time.sleep(interval)
    raise PaperDLError(f"等待超时（{timeout}s），任务仍在队列")


def download(job_id, save_dir=".", base=DEFAULT_BASE, filename=None):
    """拉取 PDF 落盘，返回本地路径"""
    st = status(job_id, base)
    if st.get("status") != "done":
        raise PaperDLError(f"任务未完成：{st.get('status')}")
    body = _req(f"/files/{job_id}.pdf", base, raw=True, timeout=180)
    if body[:4] != b"%PDF":
        raise PaperDLError("返回内容不是 PDF")
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, filename or f"{job_id}.pdf")
    with open(path, "wb") as f:
        f.write(body)
    return path


def fetch_by_title(title, save_dir=".", timeout=300, base=DEFAULT_BASE, on_tick=None):
    """一步到位：标题 → 检索 → 取最佳候选 → 建任务 → 等待 → 落盘"""
    items = search(title, base=base)
    if not items:
        raise PaperDLError("未检索到结果")
    best = items[0]
    if not best.get("doi"):
        raise PaperDLError("首选结果没有 DOI")
    job = submit(doi=best["doi"], title=best.get("title"), base=base)
    st = wait(job["job_id"], timeout=timeout, base=base, on_tick=on_tick)
    if st.get("status") != "done":
        raise PaperDLError(f"下载失败：{st.get('reason')}")
    path = download(job["job_id"], save_dir, base)
    return {"path": path, "doi": best["doi"], "provider": best.get("provider"), "job": st}


if __name__ == "__main__":
    import sys
    print("health:", health())
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        for it in search(q, limit=5):
            print(f"  [{it['provider']:8s}] {it['year']} {it['doi']:32s} {it['title'][:56]}")
