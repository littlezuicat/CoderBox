# VS Code Server 镜像（deploy/vsc-mirror）

用户电脑直接从微软下 230MB 的 VS Code Server 很慢，所以由码境服务器（www.zuicat.cn，ssh worker 就是它）后台预取，
放进 nginx 已有的静态目录 `/var/www/toolbox/vscode-server/<提交号>/vscode-server-linux-<x64|arm64>.tar.gz`，
工具箱（`py/majing/core/vscserver.py`）先从 `https://www.zuicat.cn/toolbox/vscode-server/...` 下，404 就回退微软。
**nginx 不用改**：`/toolbox/` 是静态 alias，`.tar.gz` 按 octet-stream 发，支持 Range。

## 部署（在服务器上，只做一次）
```bash
sudo mkdir -p /var/www/toolbox/vscode-server && sudo chown zuicat:zuicat /var/www/toolbox/vscode-server
install -m 755 vsc-mirror.py /home/zuicat/toolbox-release/vsc-mirror.py
sudo cp tb-vsc-mirror.service tb-vsc-mirror.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now tb-vsc-mirror.timer
sudo systemctl start --no-block tb-vsc-mirror.service      # 立刻拉一次
```
## 日常
- 看进度：`journalctl -u tb-vsc-mirror -f`；已有哪些：`cat /var/www/toolbox/vscode-server/index.json`
- 补指定版本（用户的 VS Code 不是最新版）：`python3 /home/zuicat/toolbox-release/vsc-mirror.py commit <40位提交号>`
- 保留最近 4 个版本（`VSC_MIRROR_KEEP`），每个版本 x64 + arm64 约 470MB。
- 服务器到微软也慢（实测 ~0.13MB/s），所以是 curl 断点续传 + 失败重试，慢慢拉。
