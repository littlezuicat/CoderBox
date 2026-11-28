# -*- coding: utf-8 -*-
"""给 CoderLand 的 server.py 加「实验结束邮件通知」接口 POST /api/notify/experiment（2026-11-28）。
在服务器上运行：python3 patch_server.py /opt/coderland/server.py
会先备份成 server.py.bak-expnotify；重复运行是安全的（已打过补丁就退出）。
接口约定见同目录 SPEC.md：用会话 cookie + X-CSRF-Token 认证；只发给该账号已验证的邮箱；
邮件正文由服务器用固定模板生成（客户端只给结构化字段），同一账号同一实验 id 只发一次，限频每小时 40 封。"""
import shutil
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/opt/coderland/server.py"
s = open(path, encoding="utf-8").read()
if "send_experiment_notification" in s:
    print("已经打过补丁，不处理")
    sys.exit(0)
shutil.copy2(path, path + ".bak-expnotify")


def sub(a, b):
    global s
    assert s.count(a) == 1, ("锚点不唯一或不存在", a[:60], s.count(a))
    s = s.replace(a, b, 1)


# 1. 限频配置
sub('"auth": (60.0, 20), "device": (300.0, 20),', '"auth": (60.0, 20), "exp_notify": (3600.0, 40), "device": (300.0, 20),')

# 2. 发送函数（放在 send_email_verification 前面）
FUNC = '''EXP_NOTIFY_SEEN: dict = {}
EXP_NOTIFY_LOCK = threading.Lock()
EXP_NOTIFY_STATUS = {"done": "完成", "failed": "出错", "stopped": "中途退出"}


def _exp_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def send_experiment_notification(user_id: str, body: dict) -> tuple[dict, int]:
    """码境工具箱的实验订阅：实验结束后给账号已验证的邮箱发一封固定模板的邮件。返回 (响应, HTTP 状态码)。"""
    from datetime import datetime, timedelta, timezone

    if not isinstance(body, dict):
        return {"error": "请求内容无效。", "code": "bad_request"}, 400
    exp_id = _exp_text(body.get("id"), 64)
    status = str(body.get("status") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", exp_id) or status not in EXP_NOTIFY_STATUS:
        return {"error": "实验信息无效。", "code": "bad_request"}, 400
    name = _exp_text(body.get("name"), 120) or "未命名实验"
    note = _exp_text(body.get("note"), 120)
    host = _exp_text(body.get("host"), 64)
    gpus = _exp_text(body.get("gpus"), 64)
    label = _exp_text(body.get("label"), 120)
    error = _exp_text(body.get("error"), 300)
    metrics = body.get("metrics") if isinstance(body.get("metrics"), dict) else {}
    metric_text = " · ".join(f"{_exp_text(k, 16)} {_exp_text(v, 16)}" for k, v in list(metrics.items())[:6] if _exp_text(v, 16))

    def clock(value: object) -> str:
        try:
            ts = int(value)
            return datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return ""

    start_text, end_text = clock(body.get("start")), clock(body.get("end"))
    duration = ""
    try:
        secs = int(body.get("end")) - int(body.get("start"))
        if secs >= 0:
            days, rest = divmod(secs, 86400)
            hours, rest = divmod(rest, 3600)
            duration = (f"{days} 天 " if days else "") + (f"{hours} 小时 " if days or hours else "") + f"{rest // 60} 分钟"
    except (TypeError, ValueError):
        pass

    with connect_db() as connection:
        row = connection.execute(
            "SELECT contact_email, contact_email_ciphertext, email_verified_at FROM users WHERE id = ?", (user_id,),
        ).fetchone()
    if not row:
        return {"error": "账号不存在。", "code": "bad_request"}, 401
    email = valid_contact_email(decrypt_contact_value(row["contact_email_ciphertext"], row["contact_email"]))
    if not email:
        return {"error": "账号还没有绑定邮箱，请先在码境工具箱的设置里绑定。", "code": "no_email"}, 400
    if not row["email_verified_at"]:
        return {"error": "邮箱还没有验证。", "code": "email_unverified"}, 400
    smtp_host = os.environ.get("CODERLAND_SMTP_HOST", "")
    smtp_port = os.environ.get("CODERLAND_SMTP_PORT", "465")
    smtp_username = os.environ.get("CODERLAND_SMTP_USERNAME", "")
    smtp_password = os.environ.get("CODERLAND_SMTP_PASSWORD", "")
    smtp_sender = os.environ.get("CODERLAND_SMTP_SENDER", smtp_username)
    if not all((smtp_host, smtp_username, smtp_password, smtp_sender)):
        return {"error": "邮箱服务暂未配置。", "code": "smtp_unconfigured"}, 503

    key = (str(user_id), exp_id)
    with EXP_NOTIFY_LOCK:
        if key in EXP_NOTIFY_SEEN:
            return {"ok": True, "duplicate": True}, 200
        EXP_NOTIFY_SEEN[key] = time.time()
        while len(EXP_NOTIFY_SEEN) > 5000:
            EXP_NOTIFY_SEEN.pop(next(iter(EXP_NOTIFY_SEEN)))

    word = EXP_NOTIFY_STATUS[status]
    lines = ["CODERLAND（码境）· 实验" + word, "────────────────────────", name]
    if note:
        lines.append(note)
    lines.append("")
    if host:
        lines.append("主机：" + host + (f"    GPU：{gpus}" if gpus else ""))
    if start_text:
        lines.append("开始：" + start_text)
    if end_text:
        lines.append("结束：" + end_text + (f"（用时 {duration}）" if duration else ""))
    if label:
        lines.append("进度：" + label)
    if metric_text:
        lines.append("指标：" + metric_text)
    if error and status == "failed":
        lines.append("报错：" + error)
    lines += ["", "────────────────────────", "这封邮件由码境工具箱的「实验」订阅自动发出；该实验只通知这一次。"]
    subject = f"【码境】实验{word}：{name}"[:150]

    def deliver() -> None:
        try:
            send_mail(smtp_host, smtp_port, smtp_username, smtp_password, smtp_sender, email, subject, "\\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            with EXP_NOTIFY_LOCK:
                EXP_NOTIFY_SEEN.pop(key, None)       # 没发出去：允许工具箱重试
            print(f"[exp-notify] send failed user={user_id}: {type(exc).__name__}", file=sys.stderr, flush=True)

    threading.Thread(target=deliver, name="coderland-exp-notify", daemon=True).start()
    return {"ok": True}, 200


'''
sub("def send_email_verification(user_id: str, email: str) -> None:", FUNC + "def send_email_verification(user_id: str, email: str) -> None:")

# 3. 路由（放在 /api/profile/bio 前面，已经过 csrf_user 校验）
ROUTE = '''        if path == "/api/notify/experiment":
            if not allow_rate("exp_notify", f"ip:{self.client_ip()}", f"account:{account_for_write['id']}"):
                return self.send_json({"error": "通知发送过于频繁，请稍后再试。", "code": "rate_limited"}, HTTPStatus.TOO_MANY_REQUESTS)
            payload, code = send_experiment_notification(account_for_write["id"], body)
            return self.send_json(payload, code)
'''
sub('        if path == "/api/profile/bio":', ROUTE + '        if path == "/api/profile/bio":')
open(path, "w", encoding="utf-8").write(s)
print("补丁已写入（备份：%s.bak-expnotify）" % path)
