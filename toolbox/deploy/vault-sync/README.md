# 保险库同步服务 — 服务器端

**已部署（2026-11-24）** 在 ssh.zuicat.cn 这台机器上，工具箱“密码”页 → 同步可直接用。本目录是线上那份的源。

## 它做什么
- 只存密文（工具箱本机加密后上传），服务器看不到保险库内容，也不知道主密码。
- 身份用 CoderLand 账号：请求头 `Authorization: Bearer <登录凭证>`，本服务拿它向**本机** CoderLand（`http://127.0.0.1:8787/api/auth/me`，带 `Cookie: coderland_session=…` 和 `Origin: https://code.zuicat.cn`）核对用户，每个用户一个文件；核对结果缓存 60 秒。
- 只用 Python 3 标准库。

## 线上布局（和这台机器上其它服务的约定一致）
| 东西 | 位置 |
|---|---|
| 脚本 | `/opt/vaultsync/vault_sync_server.py`（= 本目录 `vault_sync_server.py`） |
| systemd | `/etc/systemd/system/vaultsync.service`（= 本目录 `vaultsync.service`）：DynamicUser、只读系统、只允许回环网络，监听 127.0.0.1:8795 |
| 数据 | `/var/lib/vaultsync/`（StateDirectory，0700；实际在 `/var/lib/private/vaultsync/`）。每个账号 `<哈希>.json`（全是密文），上传时留 `.prev`，工具箱里“删除服务器副本”只会改名 `.deleted` |
| nginx 限流 | `/etc/nginx/conf.d/vaultsync-limits.conf`（`vaultsync` 区，60 次/分钟/IP） |
| nginx 路由 | `/etc/nginx/snippets/toolbox.conf` 里，在 `location ^~ /toolbox/` 之前加了 `location = /toolbox/api/vault`（内容见 `vaultsync-nginx.txt`；精确匹配优先于前缀匹配）。改动前的备份：`toolbox.conf.bak-vaultsync-20261124015735` |

## 运维
```bash
systemctl status vaultsync            # 状态
sudo journalctl -u vaultsync -f       # 日志（只记方法和状态，不含内容和凭证）
curl -s https://www.zuicat.cn/toolbox/api/vault   # 应返回 {"error": "没有登录凭证。"}（JSON），不是 404/502
```
- 回滚：`sudo systemctl disable --now vaultsync`，再把 `toolbox.conf.bak-vaultsync-*` 拷回 `snippets/toolbox.conf` 并 `nginx -t && systemctl reload nginx`。数据文件不要删，那是用户的密文。
- 这个 location 里 `access_log off`：请求头里有登录凭证，别开日志。
- 账号标识取 `/api/auth/me` 返回的 `user.id`，没有才用 `username`。

## 重新部署（改了脚本以后）
`scp vault_sync_server.py` 到服务器 → `sudo install -m 644 … /opt/vaultsync/` → `sudo systemctl restart vaultsync`。
