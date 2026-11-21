# 克劳德工具箱（原码境工具箱）— 开发交接

从 2026-11-22 起，**源码、打包、测试都在这台 Windows 上**，服务器（用户的 Linux 主机，域名 www.zuicat.cn）**只负责分发**。
项目在 `toolbox\`（本目录下）。你是接手的 Claude：先读完本文件，再动手。回复用中文，简洁，先说结论。

## 它是什么
Windows 桌面软件，React(Vite+MUI，Clash Verge Rev 风格，GPL-3.0) + pywebview(WebView2) 外壳，Python 后端，PyInstaller 打成单文件 exe。功能页：
- **PPT定图**：每页渲染成高清图片再装回 PPT（真 PowerPoint/WPS COM 导出），备注保留、可跳过隐藏页。
- **格式转换**：视频/音频/图片互转（ffmpeg，组件约 76MB，页面右上角一键安装，从服务器 `ffmpeg-8.1-win64.zip` 下）。
- **SSH管理**：主机列表同步 ~/.ssh/config、通用密钥、SFTP、内嵌终端(xterm.js)、IP 池、「共享本机」(内置 SSH 服务)。
- **在线工具**（外链卡片）、**设置**（主题/下载目录/关于）。PPT 和格式转换页下有**转换历史**（长期保存，%APPDATA%\MajingToolbox\history.json）。
- exe 本身就是**安装包**（旁边没有 install.json 时出安装面板，装到 %LOCALAPPDATA%\Programs\ClaudeToolbox，免管理员）。开发自测一律加 `--portable`，否则会进安装面板。

## 目录
```
toolbox\
  py\main.py            入口（窗口、拖放 drop 处理器、更新、安装/卸载模式）
  py\api.py             暴露给前端的 API（公开方法 = window.pywebview.api.*；_ 开头是内部；后端→前端用 self._emit(type,data)）
  py\majing\            __init__.py(APP_NAME/APP_VERSION) settings.py history.py installer.py core\(ppt_engine media ffsetup sshhosts sshserver updater ...)
  py\res\               app.ico、base.pptx、majing-remote.exe(已不随启动，保留)
  web\src\              pages\(ppt convert ssh online settings installer) components\ bridge.ts(api 代理，浏览器里走 mock.ts) hooks.ts
  brand\                LOGO 素材（M 标 + “码境”字标）
  deploy\server-publish.sh   服务器端发布脚本的副本（线上那份在服务器 /home/zuicat/toolbox-release/publish.sh）
  setup.ps1  release.ps1  MajingToolbox.spec  requirements.txt  release.config.example.json
```

## 日常命令（在 toolbox\ 里）
```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1                     # 第一次：venv + 依赖 + 前端依赖（需要 Python 3.11、Node 20+）
.venv\Scripts\python.exe py\main.py --portable --no-update              # 跑真窗口（先 cd web; npm run build，py 读 web\dist）
cd web; npm run dev                                                     # 浏览器里调界面（mock 后端，localhost:5190）
cd web; npx tsc --noEmit -p .                                           # 类型检查
.\release.ps1 -NoUpload                                                 # 只打包（dist\MajingToolbox.exe），先自己试
.\release.ps1 -Bump -Notes "一句话更新说明"                              # 版本号+1 → 打包 → 上传服务器发布 → 工具箱自动更新
```

## 发布规矩（用户明确要求）
- **改了功能就发布新版本**，让已装的工具箱检测到后自动更新；用户自己测试，不要等他点头再发（但先自己跑通能跑的验证）。
- 版本号在 `py\majing\__init__.py` 的 APP_VERSION，必须比线上新（release.ps1 -Bump 自动加）。**不做数字签名**（用户已决定）。
- 发布 = 把 exe 传到服务器，由服务器脚本检查（是 exe、>20MB、版本更高）→ 备份旧版到 `/var/www/toolbox/_prev/MajingToolbox-<旧版>.exe` + `version-<旧版>.json` → 写 `/var/www/toolbox/version.json`
  `{"version","exe":"MajingToolbox.exe","size","sha256","notes"}`。客户端 `majing\core\updater.py` 查 `https://www.zuicat.cn/toolbox/version.json`，校验大小和 SHA-256，替换自己重启。
- 回滚：服务器上把 `_prev` 里的旧 exe 放回 `/var/www/toolbox/MajingToolbox.exe`，并把 version.json 改回旧版本号/大小/sha256（让用户在服务器那边的 Claude 做，或手动）。
- 上传通道：`release.config.json`（从 example 复制，已被 .gitignore）里填服务器 ssh 信息；用户说他的 Windows 能 ssh 到服务器。**服务器没有别的东西要你动**：别改服务器的 nginx/防火墙/服务，需要时告诉用户。
- 下载页 www.zuicat.cn/toolbox/ 的文案在服务器上，不在本项目里。

## 测试方法与踩过的坑（都是真机踩出来的）
- **拖放**：不要给 pywebview 登记 `dragover` DOM 处理器（`events.dragover +=`）——它每次都把整个事件序列化发给 Python，真实拖放时把页面主线程占满（定时器停摆、框不变色、入队慢数秒）。现在 main.py 只登记 `drop`（要靠它拿 `pywebviewFullPath`），放行拖放由 `web\src\App.tsx` 的 window dragover preventDefault 做。
- 真窗口调试：启动前设 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`（再配独立的 `WEBVIEW2_USER_DATA_FOLDER`），然后用 CDP（Python websocket-client / puppeteer-core）读 DOM、调 `pywebview.api.*`、截图。隐藏页也在 DOM 里，点按钮要限定可见页。用户锁屏时 captureScreenshot 会超时。测试时把 APPDATA 指到临时目录，别污染用户的设置/历史。
- 布局：`pageGrid` 必须 `minmax(0,1fr)`、左列 `minWidth:0`，否则长文字把右侧“输出设置”挤出窗口。
- 文字渲染：关 hinting 的 QSS 时代结论已不适用（现在是 WebView2 原生 ClearType）；DPI 用系统缩放，无需额外处理。
- PowerPoint 导出：COM 引擎在 `majing\core\ppt_engine.py`；“打不开文件”的 COM 原始报错元组在历史里会被截掉（api._log）。
- 无控制台 exe 里 `subprocess.Popen` 必须给 `stdin/stdout/stderr=DEVNULL`；cmd 里 `if ... & x` 的 `&` 属于 if 分支要加括号；for 变量命令行写 `%i`。
- Windows 用户名=电脑名(zuicat)时 icacls 按名字授权会授给电脑账户 → 必须用 SID。
- 自动更新测试：`--fake-version=1.0.0` 在副本上测（会下载线上最新版）。
- 不要用 HTML5 拖放做应用内排序（IP 池已改成 mousedown/mousemove 自写）。
- 用正则批量改 tsx 的 `info=` 属性会吃掉后面的 `header=`，这类批量改动要看 diff。
- 依赖：pywebview 6.2.1；pywinpty 打包要 `collect_all('winpty')`（见 spec）；PyQt5 版已弃用。

## 状态（2.0.4，2026-11-22 已发布）
已验证：PPT 真 PowerPoint 导出、格式转换、SSH 管理、安装→运行→卸载、自动更新替换重启、真实资源管理器拖放（框变色、入队正常）、转换历史写入/重启保留、长文件名下布局无横向滚动。
**没验证**：WPS 引擎、共享本机时有人来连的审批弹窗、SmartScreen 行为、公网访问共享本机（需网关开端口，用户未决定）、码境账号完整授权链路（设置页里默认隐藏）。

## 用户偏好
- 追求界面好看、操作少；文案简短，中文。小功能先做出来给他看。
- 他自己做真人测试；你要做真机验证时别抢他的鼠标/键盘太久，别留后台进程（测完 kill 自己起的测试实例，别动他正在用的那个）。
- 不要把他在聊天里贴的密码/密钥写进文件。
