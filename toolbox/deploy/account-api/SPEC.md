# 码境账号：资料编辑 + 实验结束邮件通知（2026-11-28，已在服务器上线）

CoderLand（`/opt/coderland/server.py`，systemd 服务 `coderland`，监听 127.0.0.1:8787，code.zuicat.cn）**本来就有**账号资料和邮箱验证体系，
工具箱直接复用，只新增了一个接口：

| 用途 | 接口（会话 cookie `coderland_session` + `X-CSRF-Token` + `Origin: https://code.zuicat.cn`） |
|---|---|
| 读账号详情（含打码邮箱、是否已验证、签名） | `GET /api/profile/me` → `account.{username, display_name, profile_bio, contact_email_masked, has_contact_email, email_verified_at, avatar_url}` |
| 改用户名（3-32 位字母数字，30 天一次，同时改显示名） | `POST /api/auth/username {username}` |
| 改签名 | `POST /api/profile/bio {bio}` |
| 换头像（≤300KB 的 png/jpg/webp 的 data URL） | `POST /api/auth/avatar {image}` |
| 绑定/换邮箱：发 6 位验证码（5 分钟有效） | `POST /api/auth/email/send {email}` |
| 验证邮箱 | `POST /api/auth/email/verify {code}` |
| **实验结束通知（新增）** | `POST /api/notify/experiment` |

## `POST /api/notify/experiment`（新增，补丁见 `patch_server.py`）
请求体全是结构化字段，邮件正文由服务器用固定模板生成（不接受客户端 HTML/任意正文，防止被当垃圾邮件转发器）：
`{id, status: done|failed|stopped, name, note, host, gpus, start, end, label, metrics: {PSNR, SSIM, loss}, error}`（各字段有长度上限）。
- 只发给该账号**已验证**的邮箱（`users.contact_email*` + `email_verified_at`）；用现成的 `send_mail` 和 `CODERLAND_SMTP_*` 环境变量，在后台线程发送。
- 同一账号同一 `id` 只发一次（内存去重，重复请求返回 `{"ok":true,"duplicate":true}`；发送失败会清掉去重记录，允许重试；服务重启后去重清空）。
- 错误码（`code` 字段）：`no_email` / `email_unverified` / `rate_limited`（每账号每小时 40 封，`RATE_WINDOWS["exp_notify"]`）/ `smtp_unconfigured` / `bad_request`。
- 部署：`python3 patch_server.py /opt/coderland/server.py`（先备份成 `server.py.bak-expnotify`，可重复运行），再 `sudo systemctl restart coderland`。
  回滚：把 `server.py.bak-expnotify` 放回 `server.py` 后重启。
