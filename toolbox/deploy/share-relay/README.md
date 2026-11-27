# 共享本机 SSH 的公网中转（tb-relay）

跑在 code.zuicat.cn 背后的服务器（worker）上。别人用原生 ssh：`ssh -p 41764 <码境用户名>@code.zuicat.cn`，中转按码境用户名把连接分给对应的电脑。
一个公网端口服务所有人；同一个码境用户名同一时刻一台设备（后来的顶掉先来的）。

- 链路：访客 → SakuraFrp 节点 46 的 TCP 隧道 `tb_share_ssh`（id 29963994，code.zuicat.cn:41764）→ 服务器 `127.0.0.1:22301`（本程序）← 设备（工具箱）主动连来。
- 设备：用户名 `_device`、密码 = 码境登录凭证（中转去 `code.zuicat.cn/api/auth/me` 核对出码境用户名，防冒名），然后 `tcpip-forward` 登记。
- 访客：用户名 = 码境用户名，密码 = 设备共享窗口里的密码；中转经设备的通道连到它本机的内置 SSH，用访客的密码登录，成功才放行，再把 shell/exec/sftp 接过去。
- 限制：不支持 `ssh -L/-J`（设备端内置 SSH 不支持端口转发）；中转处会解开会话再转发，不是端到端加密；同一用户名连错 8 次锁 5 分钟。

## 部署（服务器上，已部署）
```
sudo useradd -r -m -d /var/lib/tb-relay -s /usr/sbin/nologin tbrelay
sudo install -d -m 755 /opt/tb-relay && sudo install -m 644 relay.py /opt/tb-relay/relay.py
sudo python3 -m venv /opt/tb-relay/venv && sudo /opt/tb-relay/venv/bin/pip install paramiko cryptography
# /etc/systemd/system/tb-relay.service：User=tbrelay，ExecStart=/opt/tb-relay/venv/bin/python /opt/tb-relay/relay.py，
#   Environment=LISTEN_HOST=127.0.0.1 LISTEN_PORT=22301 DATA_DIR=/var/lib/tb-relay，NoNewPrivileges/ProtectSystem=strict/ReadWritePaths=/var/lib/tb-relay
sudo systemctl enable --now tb-relay
```
更新程序：`scp relay.py` 到服务器后 `sudo install -m 644 … /opt/tb-relay/relay.py && sudo systemctl restart tb-relay`（重启会让在线设备掉线，工具箱会自动重连）。
