# 克劳德工具箱（原码境工具箱）— 开发交接

从 2026-11-22 起，**源码、打包、测试都在这台 Windows 上**，服务器（用户的 Linux 主机，域名 www.zuicat.cn）**只负责分发**。
项目在 `toolbox\`（本目录下）。你是接手的 Claude：先读完本文件，再动手。回复用中文，简洁，先说结论。

## 它是什么
Windows 桌面软件，React(Vite+MUI，Clash Verge Rev 风格，GPL-3.0) + pywebview(WebView2) 外壳，Python 后端，PyInstaller 打成单文件 exe。功能页：
- **PPT定图**：每页渲染成高清图片再装回 PPT（真 PowerPoint/WPS COM 导出），备注保留、可跳过隐藏页。
- **格式转换**：视频/音频/图片互转（ffmpeg，组件约 76MB，页面右上角一键安装，从服务器 `ffmpeg-8.1-win64.zip` 下）。
- **SSH管理**：主机列表同步 ~/.ssh/config、通用密钥、SFTP、内嵌终端(xterm.js)、IP 池、「共享本机」(内置 SSH 服务)。
- **密码**（本机加密保险库，`py\majing\core\vault.py`；密钥由 Windows DPAPI 保护，日常不上锁，复制后 15 秒清剪贴板；后续：导入 Bitwarden、同步到服务器、浏览器扩展）。
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
  extension\            Chrome/Edge 密码自动填充扩展（MV3，见其 README.md）；原生主机 py\nmhost.py，注册 py\majing\core\nmreg.py（打包版主机未做）
  deploy\vault-sync\    密码保险库同步服务（服务器侧脚本+部署说明；已部署在服务器 vaultsync.service，改它要用户授权）
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

## 两层打包与增量更新（2026-11-22 起）
- exe = **运行时**（Python + 第三方库 + 引导程序 `pyoot.py`，约 34 MB，很少变）+ 内置的**负载包**（我们自己的 py 源码 + web/dist，约 0.5 MB，每次改功能都变）。`boot.py` 是 PyInstaller 入口，**不能 import majing/api/main**（否则会被冻进 exe）。
- 负载包解压到 `%LOCALAPPDATA%\MajingToolbox\payload\<版本>\`（`py\`、`web\dist\` 和源码布局一样）；启动时 boot.py 选最新的、运行时 id 对得上的那份。上次启动没走到“界面加载完成”（有 `.launching` 没有 `.verified`）就自动退回更老的一份。
- `toolsuild_payload.py` 生成 `stage\`：`payload-<版本>.zip`、`runtime.txt`（运行时 id = requirements.lock/txt + spec + boot.py + 用到的模块清单的哈希）、`hiddenimports.json`（spec 用它补我们代码的 import，因为不再被冻进 exe）。**新增第三方依赖/标准库模块 → 运行时 id 变 → release.ps1 自动连整包一起发**；id 不变只发负载包。
- 更新器（`updater.py` + `api._update_once`）：version.json 里 `payload.runtime` 和本 exe 的运行时 id 一致 → 只下负载包（约 0.5 MB）；否则下整包。顶层 `exe/size/sha256` 永远是线上整包（老版本只认这些）。启动另一个自己要用 `updater.fresh_env()`（清 `_PYI*` 并设 `PYINSTALLER_RESET_ENVIRONMENT=1`），否则新进程共用旧进程的 _MEI 目录，旧进程一退出就报找不到 WebView2 dll。
- 本地测增量更新：`MAJING_UPDATE_BASE=http://127.0.0.1:端口/` 指到自己起的 http.server（放 version.json、payload/payload-x.y.z.zip），`LOCALAPPDATA/APPDATA` 指到临时目录，`MAJING_PORTABLE=1`。打包后 `dist\MajingToolbox.exe --selftest=文件` 会把负载包所有模块 import 一遍（release.ps1 自动跑）。
- `deploy\server-publish.sh` 是服务器脚本的源（release.ps1 每次发布先 scp 覆盖线上那份）；用 `WEBROOT=… SUDO=` 可以在本地测。release.ps1 用 `-Ffmpeg` 才会上传 `stagefmpegfmpeg-8.1-win64.tar.xz`。
- ffmpeg 组件现在是 `.tar.xz`（`tools\pack_ffmpeg.py` 重新压：x86 BCJ + LZMA2，47 MB，原 zip 79.5 MB），进入工具箱自动下载；`MAJING_FFMPEG_URL` 可指到本地服务器测试。
- 源码版（没打包）自动写详细日志 `toolbox\logs\debug.log`（`py\majing\log.py`），排查问题先看它。

## 发布规矩（用户明确要求）
- **开源 + 每次改动都提交 git（2026-11-27 起，用户明确要求）**：代码以 GPL-3.0 开源（根目录 `LICENSE`、`README.md`）。**每做完一处改动就 `git commit`**（发布新版本时 release 的版本号改动也一起提交），提交信息用中文一句话说清改了什么；别把一堆改动攒着不提交。远程仓库是 https://github.com/littlezuicat/CoderBox（`origin/main`，2026-11-27 已推送）；`release.ps1` 发布后会自动提交并 `git push`，手动提交的也记得 `git push`。（Claude 的 PowerShell 工具里没有交互凭据，release.ps1 里的 push 会失败并提示“没成功”；这时在 Bash 工具里 `git push origin main` 就能推上去，每次发布后都要确认 `git status -sb` 不再显示 ahead。）**绝不入库**：`release.config.json`、日志、`stage/ dist/ build/`、用户的密码/令牌/私钥、SakuraFrp 令牌、服务器上的凭证；提交前 `git status` 看一眼有没有不该进的文件。
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
- 文字渲染：关 hinting 的 QSS 时代结论已不适用（现在是 WebView2 原生 ClearType）。
- **多显示器缩放不同时文字发糊（2026-11-24 修）**：pywebview 的 winforms 后端启动时调 `SetProcessDPIAware()`（系统级 DPI 感知，只认主屏缩放）。用户主屏是 2560×1600@150%、外接 1920×1080@100%，窗口放到 1080P 屏上时页面仍按 150% 渲染再被系统缩小 → 糊。`py\main.py` 最顶部在 import webview 之前先调 `SetProcessDpiAwarenessContext(-4)`（每显示器 V2；进程 DPI 感知只能设一次，pywebview 之后那次就无效）。实测：修复前窗口在 100% 屏上 `devicePixelRatio=1.5`、窗口 DPI=144；修复后 1 / 96。浏览器预览（Claude 桌面应用里的）本来就是每显示器感知，所以预览清晰、真窗口糊。注意窗口最小尺寸（840×600）是创建时按当时显示器换算成物理像素的，换到低缩放屏后最小宽度仍是那个物理值。**打包版（exe）还没验证**。
- **别用 `FindWindow(标题)` 找窗口**：电脑上可能同时开着用户自己的工具箱，同名窗口会被误操作（2026-11-24 测试时就把用户正在用的窗口关了）。`api._hwnd()` 现在用 EnumWindows 只找**本进程**的窗口；做真窗口测试脚本时，启动前先检查有没有同名窗口，有就中止，别碰。
- **新布局没有系统标题栏**（顶部功能栏当标题栏）：`api.win_borderless(on)` 去掉 `WS_CAPTION`、保留 `WS_THICKFRAME`（四边仍能拖着缩放、有 Win11 圆角阴影），前端 `App.tsx` 按“新布局”开关调它。最小化/最大化/关闭是顶栏右边的网页按钮 → `api.win_cmd('min'|'toggle'|'close')`（close 发 WM_CLOSE，走正常的关闭确认）。**最大化/还原用系统原生的**（`ShowWindow`，有 Windows 的放大/还原动画）；无标题栏窗口系统默认的最大化会盖住任务栏，所以在窗口钩子里处理 `WM_GETMINMAXINFO`，把最大位置/大小限制成所在显示器的工作区（边框宽度每次最大化前现量，随缩放变）。**WinForms 的坑**：它以为窗口还带标题栏，系统还原后会按这个算法把窗口放大（每轮宽 +2、高 +46），所以 `win_cmd` 最大化前记下 `_normal_rect`，还原后 `_fix_restored` 立刻设回去。**`user32` 函数对象是全局共用的**：别在不同地方各定义一个同名结构体（如 MONITORINFO）再给同一个函数设 argtypes，会互相覆盖、调用报错且被钩子里的 try/except 吞掉（表现为最大化盖住任务栏）——结构体统一用 `_monitorinfo_cls()`。
  - 拖动：顶栏空白处按下 → `api.win_drag()`，后端线程读鼠标物理坐标 + `SetWindowPos`，松左键结束；**最大化时按住往下拖会还原成原大小并跟着鼠标走**（和系统标题栏一样，鼠标在窗口里的横向比例不变），不受缩放影响（pywebview 自带的 drag-region 用网页像素，150% 缩放会错位，所以没用）；双击空白处最大化/还原。已在真窗口验证（样式、最大化=工作区、两轮还原不漂移、拖动距离精确、关闭）；**贴边分屏（2026-11-24 补）**：自己实现的，见下一条。
  - **顶部白边（已修）**：去掉 `WS_CAPTION` 后客户区仍比窗口矩形往下缩 10px（物理像素，150% 缩放时；这是完全可见的系统上边框，Win11 上显示成一条白边）。`api._install_nc_hook` 用 `SetWindowLongPtr(GWLP_WNDPROC)` 子类化主窗口，处理 `WM_NCCALCSIZE`（wParam=TRUE）：先让系统算，再把 `rgrc[0].top` 还原成窗口顶；被系统最大化时（IsZoomed）不处理。上边缘缩放（2026-11-24 补，新方案下同样适用）：客户区上沿比窗口顶低 `_top_grip()`（3 DIP，150% 时 6px）当缩放把手，其中最外 2px 是 DWM 灰边，剩下的是页面底色；没有这几个像素的话网页子窗口盖住整条上边，抓不到。四边的非客户区宽度现在不对称，所以 `_win_geom` 返回 (左,上,右,下) 各自的宽度，最大化矩形按它算。
  - **灰色外框（2026-11-24）**：窗口化时最外一圈灰边 = DWM 边框色（`DWMWA_BORDER_COLOR`=34，`api.set_titlebar` 里设：浅色 #B8BCC4、深色 #5A5E72），以前设成和面板同色所以看着是白边。左/右/下 8px 是系统留的不可见缩放边，不会画出来。
  - **顶栏右上角原生区的细白线 / 弹窗时先白后灰 / 开屏闪一下（2026-11-26 修）**：Win11 的 DWM 会把“标题栏色”（`DWMWA_CAPTION_COLOR`=35）那 1px **逐通道相加**叠在客户区第一行上，只在没有网页盖着的原生挖洞区（空白拖动区 + 三个按钮）看得见 → 暗色下一条亮线。对策：`_paint_caption` 把洞第一行涂黑（相加后正好 = 标题栏色），标题栏色用 `_apply_caption_color` 跟着 `_cap_bg()`（弹窗压暗时一起压暗）；`theme.ts` 里 `.MuiBackdrop-root` 关了过渡动画（网页遮罩和原生区同一帧压暗），`App.tsx` 按遮罩真实 opacity 判断是否压暗（rAF 合并）。开屏：`main.py` 给页面地址带 `?t=dark|light`（包装 `window._resolve_url`），`index.html` 优先用它决定开屏深浅色（以前按系统深浅色猜，设置是深色而系统是浅色时开屏先亮一下）；`reveal()` 在显示前就调 `api.set_titlebar`，不然界面就绪前顶部两行是系统默认白。验证方法：`PrintWindow` 抓自己窗口逐帧取像素（不用屏幕抓取，不受别的窗口遮挡）。Win10 没有这套 DWM 属性，黑行只在 build≥22000 涂。
  - **窗口右/左/下边缘的亮线（2026-11-26）**：同样是 DWM 相加——边框色（34）会再叠到客户区最外一列像素上（暗色 #5A5E72 + 页面底色 #2E303D = 一条 (136,142,175) 亮线）。暗色边框色改成黑（相加后 = 页面底色，外圈剩 2px 深色细边）；浅色相加饱和成 255 对 245，几乎看不出，保留灰边。测法：窗口前置后用 `ImageGrab` 取屏幕像素（PrintWindow 画不出 DWM 的边框，不可信）。
  - **弹窗压暗时（2026-11-26）**：原生三个按钮的悬停/按下底色、图标、关闭红也压暗一半（`_paint_caption` 里 `_cap_dim`）；边框色压暗时一律用黑（`_border_rgb`/`_apply_border_color`，在 `win_dim` 里设）——浅色的灰边相加到被压暗的页面上会变成亮线，外圈也该跟着变暗。
  - **原生拖动 / 贴边 / 贴靠布局（2026-11-24，最终方案）**：窗口保留 `WS_CAPTION` 等样式，钩子里 `WM_NCCALCSIZE` 让客户区盖住标题栏（最大化时从屏幕顶开始，上边缘留 `_top_grip()` 缩放把手）。①**顶栏空白处（导航和版本号之间，前端 `blankRef` 量出来经 `api.win_blank` 报给后端）**：和按钮一样从 WebView 控件上挖掉，钩子里 `WM_NCHITTEST` 返回 `HTCAPTION`——这是**真正的系统标题栏拖动**：贴边、**拖到屏幕顶端弹出的布局条（Win11 原生）**、双击最大化、右键系统菜单全有（只靠 WebView2 的 app-region 拖动区时顶端布局条不出来，别退回去）。其余顶栏区域（logo、版本号）仍用 `api.win_native_drag()` 打开 WebView2 `CoreWebView2Settings.IsNonClientRegionSupportEnabled`，前端顶栏 CSS `-webkit-app-region: drag`（按钮/导航 `no-drag`）→ 拖动、双击最大化、拖到屏幕边缘贴边（Win11 原生预览）、顶到上沿最大化并弹布局浮层、最大化/贴边后下拖还原，全是系统的。②**右上角三个按钮**：WebView 子窗口盖住整个客户区，系统拿不到命中，所以 `_apply_caption_hole` 给 WebView 控件 `SetWindowRgn` 挖掉右上角 3×46 DIP，露出窗体（底色=顶栏色，`_set_form_back`），`_paint_caption` 用 GDI 画 Segoe Fluent Icons 字形（Win10 退到 Segoe MDL2 Assets），钩子里 `WM_NCHITTEST` 返回 `HTMINBUTTON/HTMAXBUTTON/HTCLOSE`、`WM_NCMOUSEMOVE/LEAVE/NCLBUTTONDOWN/UP` 自己管悬停/按下/点击 → **悬停最大化按钮时 Win11 原生贴靠布局浮层会弹出**。`api.win_borderless()` 返回 `{w,h}`（按钮区 CSS 像素），前端 `cap` 状态据此右侧留位、不再渲染网页按钮。③`api.win_drag()`（自写拖动 + `majing\core\snap.py` 自绘预览）只是 `win_native_drag` 失败时的后备。**试过但不行的**：`ReleaseCapture`+`WM_NCLBUTTONDOWN(HTCAPTION)`（鼠标被 WebView 子窗口捕获，没反应）；客户区盖住标题栏后让 DWM 画原生按钮（`DwmExtendFrameIntoClientArea`、窗体涂黑当透明、`DwmDefWindowProc`）——按钮不出来，所以自己画。没做：Win+方向键（系统自带，没测）、四角 1/4 分屏浮层以外的细节。最小窗口 840×600（2560@150% 屏半屏贴得下）；窄于 940px 顶栏版本号隐藏。真窗口里已验证（2026-11-24 用户验收通过）：拖到顶端弹出布局条（截图）、拖动位移精确、拖到左边缘贴成半屏、从贴边拖开还原原大小、顶到上沿最大化、最大化下拖还原、悬停最大化弹出贴靠布局浮层（截图）、点击最大化/还原、深浅色边框、上边缘缩放。
- PowerPoint 导出：COM 引擎在 `majing\core\ppt_engine.py`；“打不开文件”的 COM 原始报错元组在历史里会被截掉（api._log）。
- **PPT 定图保存的容错（2026-11-28，有用户反馈处理完保存失败）**：`pptx_writer.save_robust` 依次试 设置的输出目录 → 原文件旁边 → 桌面 → 文档 → 系统临时目录，哪个写得进去就用，并把“没存到首选位置+原因+实际位置”写进结果的 `warning`（界面卡片的小字里显示）；全失败才报错，列出每个位置的原因（`friendly_error` 翻成人话：磁盘满/被占用/没权限/路径太长）。写入本身：`.part` 失败必清理、写完用 `_check_pptx` 打开校验（合法 zip、首尾页都在）、`os.replace` 被杀毒/网盘短暂占用时重试 8 次、不再先删旧文件、文件名里的非法字符替换并在整条路径超过 240 时截短标题。测试脚本不在库里（假目录/超长路径/占用重试/磁盘满/坏文件/同名编号 7 项都通过）。用户那次的真实报错原文没拿到，原因是推测的。
- 无控制台 exe 里 `subprocess.Popen` 必须给 `stdin/stdout/stderr=DEVNULL`；cmd 里 `if ... & x` 的 `&` 属于 if 分支要加括号；for 变量命令行写 `%i`。
- Windows 用户名=电脑名(zuicat)时 icacls 按名字授权会授给电脑账户 → 必须用 SID。
- 自动更新测试：`--fake-version=1.0.0` 在副本上测（会下载线上最新版）。
- 不要用 HTML5 拖放做应用内排序（IP 池已改成 mousedown/mousemove 自写）。
- 用正则批量改 tsx 的 `info=` 属性会吃掉后面的 `header=`，这类批量改动要看 diff。
- 依赖：pywebview 6.2.1；pywinpty 打包要 `collect_all('winpty')`（见 spec）；PyQt5 版已弃用。

## GPU 总览 + 实验记录（2026-11-24，未发布）
- SSH管理第三个标签「GPU 总览」（`web\src\components\gpu-board.tsx`）：每台主机一张卡片（每张卡利用率/显存/温度 + 谁在跑什么），选中该标签时左侧主机列表变成双条。独立页「实验记录」（`pages\experiments.tsx`）。
- 后端 `py\majing\core\gpumon.py`（采样、任务识别、现场资料、Haiku）+ `py\majing\experiments.py`（%APPDATA%\MajingToolbox\experiments.json）。复用 `sshhosts._session` 的长连接跑 `nvidia-smi` + `ps`；页面可见 5 秒一次，后台监控 60 秒一次（设置 `gpu_monitor`），AI 备注开关 `gpu_ai`。Windows 主机只显示显卡，看不到进程。
- 任务 = 同用户+同目录+同命令（去掉 --local_rank）；连续两次采样都在或已跑 90 秒才建记录；连续 3 次没看到才算结束；结束后同命令再跑=新记录。新记录排队让 `claude -p --model haiku --tools ""`（prompt 走 stdin，临时空目录当 cwd）写 JSON 备注；采集的资料（脚本/配置/日志/目录/git）只读，疑似密钥打码后才发给 claude。
- AI 备注已精简成一句话（≤40 字，只存 `note`；`title/kind` 留空，旧记录有标题的照旧显示）。卡片里显存列在前、更醒目，不再显示“显存余量”。
- **claude 命令要先 `claude auth login`**（桌面应用的登录和命令行是两套，开发机上命令行没登录；界面有“登录 Claude”按钮 → `gpumon.open_login()`）。没登录时记录标“备注没写成”，登录后自动重试失败的。
- 测试方法：`MAJING_CLAUDE_BIN` 指到桩脚本即可不用真 claude；真 Linux 验证用 WSL(Ubuntu-24.04) + 假 nvidia-smi（测完 `wsl --terminate`）。测试脚本在会话 scratchpad，没入库。**真 Haiku 调用、真 GPU 服务器都还没验证过。**

## SSH 编辑器的文件预览（2026-11-28）
- 点开文件时按扩展名分流（`web\src\ide\preview.tsx`，接在 `editor-panel.tsx` 的标签页里）：图片（png/jpg/gif/webp/bmp/svg/ico/avif，滚轮缩放、双击切换适应/原始大小）、PDF（blob 地址塞进 iframe，用 WebView2 自带的 PDF 查看器，真窗口里验证过）、Excel（xlsx/xlsm/xlsb/xls/ods，SheetJS，只渲染前 2000 行 × 80 列，多工作表底部切换；库在打开表格时才动态加载）、Markdown（仍是文本文件，默认看渲染，标签栏右侧「源码/预览」切换；marked + DOMPurify，只放行 http(s) 链接，相对路径图片不加载）。图片/PDF/表格没有 Monaco 模型（`F.model` 为空），读字节走 `api.ssh_read_bytes(alias, path, limit)`（图片 60MB、PDF 150MB、表格 40MB 上限）。
- **Pylance 没法嵌**：它是微软闭源组件，许可只允许在微软自家的 VS Code 里用，不能放进别的程序；要 Pylance 就用头部的「VS Code」按钮。要的话以后可以考虑接开源的 Pyright（MIT）做轻量的 Python 提示。
- 浏览器 mock（`mock.ts`）里有示例文件：projects/llm-train 下的 report.xlsx、paper.pdf、pics/*.png|jpg、README.md。**没验证**：真服务器上的大文件预览、打包版 exe。

## 一键装 VS Code Server（2026-11-24，未发布）
SSH管理右上角 `</>` 按钮 → `py\majing\corescserver.py`：读本机 `code --version` 的提交号 → 本机下载 `update.code.visualstudio.com/commit:<提交>/server-linux-<架构>/stable`（缓存在 %APPDATA%\MajingToolboxscode-server）→ SFTP 上传 → 服务器解压到 `~/.vscode-server/bin/<提交>/` 并清掉卡住的安装锁。只支持 Linux 主机。事件 `vsc:progress` / `vsc:done`。测试用 `MAJING_VSC_URL` 指到本地 http 服务 + WSL。真微软下载、真服务器未验证。本机 VS Code 更新后提交号会变，要再点一次。

## SSH 文件页压缩/解压、命令行多会话、中文乱码（2026-11-24，未发布）
- 文件页右键：压缩为 ZIP / TAR.GZ、解压到“同名文件夹”/当前文件夹（`sshhosts.fs_archive/fs_extract`，在服务器上做）。zip 优先用服务器的 python3 解/压：解时按 cp437→UTF-8/GB18030 还原没有 UTF-8 标志的 GBK 文件名并防 zip-slip，压时给中文名打 UTF-8 标志（Info-ZIP 在 POSIX 语言环境下不打，Windows 里会乱码）。解压不覆盖已有内容，可 Ctrl+Z 撤销。
- 命令行：一台主机可开多个会话（`TermPane` 管标签、`TermSession` 各自一个 xterm + 一条 SSH 通道，最多 8 个）。
- 中文乱码三处：① 终端按登录 shell 的 `locale charmap` 选解码（GBK→gb18030；POSIX 无语言→开 shell 时要求 LANG=C.UTF-8，服务器拒绝环境变量就补发 export）；② paramiko 严格按 UTF-8 解文件名，GBK 名字会让整个目录读不出来 → `_patch_paramiko_names` 改成 GB18030 兜底显示 + `_RAW` 记原始字节，路径还原成原字节，重命名/删除/下载照常；③ 上面的 zip 处理。
- Windows 主机终端乱码（“鍏”“鎴”那种）：exec 通道里 `chcp` 报的代码页（常 936）≠ 交互 shell 实际输出（ConPTY 常是 UTF-8）。`_TermCodec` 在第一次出现非 ASCII 字节时判一次：合法 UTF-8 就按 UTF-8，否则按代码页，之后固定；输入也用同一个编码。Linux 不猜。
- 测试：WSL Ubuntu 真 Linux 跑通（含 GBK 命名的 zip、zip-slip、重名序号、坏包）。真服务器、真终端里 locale 为 GBK/POSIX 的场景没验证。

## 服务器没有 SFTP 的一键修复（2026-11-24，未发布）
- 现象：命令行/GPU 采样正常，文件页报 “EOF during negotiation”。msh2/msh3 是 Ubuntu 20.04 容器 + 自编译 sshd（/usr/local/openssh），`Subsystem sftp /usr/lib/openssh/sftp-server` 指向的文件不存在。
- `sshhosts._session` 开 SFTP 失败但连接还活着 → **自动**静默修复（`_auto_fix_sftp`，用户要求不要按钮不要提示；同一台 10 分钟内只自动试一次）→ 修好就重连；修不好抛 `NoSftp`，文件页只显示一条带原因的普通错误。（`ssh_fix_sftp` 接口还在，界面没用。）脚本：从 sshd 主进程找 sshd 程序和配置文件 → 找得到 sftp-server 就指过去，找不到就用 `internal-sftp`（不装任何包）→ 备份配置 → 在第一个 Match 之前写入 → `sshd -t` 与 `sshd -T` 校验（不过就还原）→ `kill -HUP` 主进程 → 再试一次真开 SFTP。要 root（或免密 sudo）。
- GPU 采样等只跑命令的地方用 `sshhosts.exec_client`（不开 SFTP），所以没 SFTP 的主机也能采样。
- 测试：WSL + 假 sshd 跑通 4 个分支；真服务器上的修复**没跑过**（要用户在文件页点按钮）。

## 新布局 demo：顶部功能栏 + VS Code 式工作区（2026-11-24，未发布，试用）
- 设置 → 外观 →「新布局（试用）」切「顶部栏」（设置项 `layout_demo`；浏览器里调试用 `?layout=ide` / `?layout=side`）。现在**默认就是顶部栏**（`layout_demo` 没设或为 true），设置里可切回侧边栏；顶部栏里每项只显示两个字（`App.tsx` 的 `SHORT`，悬停显示全名）。`App.tsx` 里 `top` 为真时渲染顶部一行导航 + 整块内容区，SSH 页收到 `ide` 属性。
- **SSH 页新布局（2026-11-27 定型）**：试过把整块 VS Code 工作台（monaco-vscode-api）嵌进来，bug 太多（搜索服务把远程目录整棵索引拖慢展开、状态栏/标题栏布局、拖出下载等），**已整体撤掉**，回到自己的轻量方案：`web/src/ide/`（`ide-pane.tsx` 一台主机一份：左资源管理器 `explorer.tsx`、右上 Monaco 编辑器标签页 `editor-panel.tsx`、右下停靠终端；`monaco.ts` 是 monaco-editor 0.52 的装配，`file-icon.tsx`+`seti/` 是文件图标）。要用完整 VS Code 就点主机头部蓝色「VS Code」按钮 → `api.open_vscode(alias)` 调本机 `code --folder-uri vscode-remote://ssh-remote+<别名>`（走本机 Remote-SSH，别名来自 ~/.ssh/config，所以要先同步过）。主机头部：别名、`SysInfoBadge`、说明、`SysInfoBar`（CPU/内存/硬盘/数据卷）、VS Code 按钮、系统终端按钮。左边主机列表宽 244。
- **这几个文件是从 Claude 会话记录里重放 Write/Edit 恢复的**（撤销嵌入时本地没有旧版副本），可能和撤销前最后一版有细微出入。**没验证**：VS Code 按钮真点击、上传按钮/拖入上传、Monaco 打开-编辑-Ctrl+S、打包版 exe。拖出下载的后端（`api.ssh_drag` / `vclip.drag`：`DoDragDrop` 必须在界面线程、数据对象建在专用 STA 线程用 `CoMarshalInterThreadInterfaceInStream` 带过去、`ClipSource.prefetch` 用一条 `find -printf` 提前列清单）还在，**前端没接**，单文件验证过，文件夹没查清。
- **教训（嵌入 VS Code 时踩的）**：`monaco-vscode-search-service-override` 的默认搜索服务启动时递归索引整个工作区，在远程主机上瞬间几千次 `ssh_ls` 占满 SFTP 通道；定位方法：CDP `Debugger.enable` + `setAsyncCallStackDepth(128)` + 在 `pywebview.api.ssh_ls` 包装里写 `debugger;`，看 `Debugger.paused` 的 `asyncStackTrace`。**并发坑仍适用**：paramiko 的 `SFTPClient` 不能被多线程同时用，`sshhosts._lease(alias)` 每次借一条独立的 SFTP 通道（最多借 4、缓存 2，因为 sshd 默认 `MaxSessions=10`）。WebView2 的权限请求全部放行（`api.allow_clipboard_read` 里的 `PermissionRequested` 处理器，不弹任何权限框）。
- **VS Code Server 自动安装 + 镜像（2026-11-26）**：连上主机后（`sshhosts.on_session` 回调，长连接第一次建好）后台自动装（`api._auto_vsc` → `vscserver.install`，已装好的几秒就过；非 Linux/本机没有 VS Code/失败都静默，失败 30 分钟后重试，一次只装一台；测试用 `MAJING_NO_AUTO_VSC=1` 关掉），主机头部有一行小字显示进度，手动安装按钮已删。服务器装好后自带 ripgrep，搜索更快（路径随版本变：旧版 `node_modules/@vscode/ripgrep/bin/rg`，1.148 起是 `@vscode/ripgrep-universal/bin/linux-x64/rg`，`fs_search_text` 的探测两种都认）。2026-11-26 在 msh4 上完整跑通过：镜像下载→上传→解压→校验，128 秒，占 692MB。下载：先 `https://www.zuicat.cn/toolbox/vscode-server/<提交>/vscode-server-linux-<架构>.tar.gz`（码境服务器预取的镜像），404 就回退微软；支持断点续传和自动重试（`.part`，跨源通用），装完清掉旧版本缓存。**镜像在码境服务器（`ssh worker` 主机名就是 zuicat，与发布通道是同一台）**：`deploy/vsc-mirror/`（vsc-mirror.py + systemd timer `tb-vsc-mirror`，每天 04:30 预取最新稳定版 x64+arm64，保留 4 个版本，**是服务器主动预取不是按请求触发**；用户的 VS Code 版本不在里面就回退微软，可手动 `vsc-mirror.py commit <40位提交号>` 补）。nginx 没改（`/toolbox/` 本来就是静态 alias）。**该服务器的 Clash（Clash Verge Rev，mihomo+TUN）此前把 4 个 VS Code 下载域名指到代理，2026-11-26 已改直连**：改的是 Clash Verge Rev 的 profile 覆写（rules 覆写，持久）和运行时 `clash-verge.yaml`，经 `PUT /configs?force=true`（unix socket `/tmp/verge/verge-mihomo.sock`）热加载；备份是同目录 `*.bak-20261126-msdirect`；服务器到微软从 ~0.13 提到 ~0.4MB/s（校园网出口上限）。国内没有 VS Code Server 的镜像（阿里/清华/腾讯/npmmirror 探测都是 404；Azure 中国 CDN 在这台电脑上连不上）。
- **上传速度（2026-11-26）**：`sshhosts._connect_one` 连上后把 TCP 发送缓冲 `SO_SNDBUF` 设成 8MB。Windows 默认缓冲下 paramiko 上传（本机→服务器）只有 ~28MB/s（CPU 只用三成、在等对端；`sftp.put`/pipelined/NODELAY 都没用），放大后 622 实测 2GB 用 23 秒≈89MB/s（和原生 scp 一致）。上传在 SSH 页资源管理器里（`ide/explorer.tsx` 的上传按钮 + 拖文件进窗口的 `files:ssh` 事件）。测上传用 622 的 `/D:/Desktop/_uptest`，测完要删。
- 主机列表：连得通的在上，其中按总显存从大到小排（`ssh.tsx` 的 `vram`）；**不显示地址**（用户明确不要），每项只有名字/徽章、显卡型号、GPU 和显存两条（字号比最初大约 +1px）。

## 托盘 + 单实例 + 启动动画（2026-11-24，未发布）
- **关闭窗口 = 缩到托盘继续运行，托盘右键“退出”才真退出**（`py\majing\tray.py` + `main.py`）。托盘是 ctypes 自写的：独立线程里一个隐藏的顶层窗口（类名 `MajingToolboxTray`，不能用 HWND_MESSAGE，它收不到 `TaskbarCreated`，资源管理器重启后要重新加图标）；左键=打开，右键=原生菜单（打开/退出）。`main.py` 的 `closing` 处理器：`window.hide()` 并返回 False；第一次会弹气泡提示（设置项 `tray_tip_shown`）。托盘没起来（`tray_icon._added` 为假）就退回老行为（有任务在跑才确认）。退出（`really_quit`）：有任务在跑先把窗口叫出来确认 → `tray.remove()` → `window.destroy()`；`webview.start` 返回后 **`os._exit(0)`**（不然后台线程会拖住进程约 10 秒，期间托盘窗口还在，再点开会叫不回来）。更新重启路径 `api._update_once` 在 `os._exit` 前也调 `tray.remove()`。
- **单实例**：命名互斥量 `Local\MajingToolbox-<key>`，key = sha1(APPDATA + 程序目录)，所以测试时把 APPDATA 指到临时目录就不会和用户正在用的那个冲突。第二次启动 → `signal_existing` 给托盘窗口发注册消息 `MajingToolbox.Show` → 旧窗口 show + `api.win_front()`，自己退出；`--after-update` 启动最多等旧进程 15 秒释放互斥量。
- **启动动画**：`web\index.html` 里 `#splash`（内联 SVG + CSS，页面 JS 加载前就显示）。图形来自 `brand\SVG-02.svg`（前 4 个 path 是 LOGO 四块，飞入拼合；后 7 个是“码境”，从左往右擦出）；SVG-05 的字是 CODERLAND，别用。生成脚本不在库里：改动画直接改 index.html 里的 CSS。`App.tsx` 在界面就绪后、且动画已放满 1.1 秒（从 `window.__splashT0` 算）再淡出并 `remove()`，同时按真实主题校正深浅色（先按系统深浅色猜）；`?nosplash=1` 可跳过（浏览器调试）。只在启动时出现，从托盘叫回不会重放。**启动时不闪系统标题栏（2026-11-24）**：`create_window(hidden=True)` 先藏着创建；`main.py` 的 `reveal_when_ready` 线程等窗体句柄和 WebView 控件建好，先 `api.win_borderless(True)`（`_hwnd()` 在窗口还藏着时退到 `window.native.Handle`）、把 WebView 的 `DefaultBackgroundColor` 设成开屏底色，再 `window.show()`。试过“全透明（Opacity=0）显示→渲染好再不透明”：不行，WebView2 把透明窗口当被遮挡、不出画面；也别让动画等后端触发（`__splashGo` 在页面里立刻调；曾因 `location.protocol` 判断写错，动画在窗口还藏着时就放完，用户只看到后半段）。**测开屏动画别拿窗口左上角抓屏**：LOGO 在窗口正中（约 y=585 物理像素），抓错区域会误以为动画没出来；用 CDP 读 `#splash` 状态 + `performance.timeOrigin` 对齐屏幕帧最可靠。`main.py` 的 `_dark_theme()` 让窗口初始底色与动画一致，避免深色主题启动时先闪一下白。
- 测试：真窗口里验证了——关闭→窗口隐藏进程还在；第二次启动→退出码 0 且叫回窗口；托盘右键菜单出现（3 项）、选“退出”→进程约 2 秒内结束、托盘窗口消失；动画帧截图（拼合→码境擦出→副标题）。**没验证**：托盘图标在任务栏里的真实样子、气泡提示、鼠标真点菜单（测试里是给菜单窗口发消息选的）、有任务在跑时退出的确认框、打包版 exe、资源管理器重启后图标恢复。注意别用键盘事件测托盘菜单（会发给前台的别的窗口），向菜单窗口 `#32768` 发消息即可。

## 共享本机：原生 ssh 命令 + 公网中转（按码境用户名分流，2026-11-25）
- 共享窗口只有两行：**命令**和**密码**。只有公网这一条命令 `ssh -p 41764 <码境用户名>@code.zuicat.cn`（**没有局域网命令**，内置 SSH 只监听 127.0.0.1，局域网里不能直连）；公网入口没连上时命令行显示状态、下面一行小字说明原因并自动重试。别人用原生 ssh/scp/sftp 连，不需要装工具箱。**不绑定码境账号不让用**：`ShareServer.start` 先调 `sharetunnel.precheck()`，没绑定/凭证失效/离线确认不了/用户名不是英文都直接报错、不开启。
- **一个公网端口服务所有人**：服务器上的 `tb-relay`（`toolbox\deploy\share-relay
elay.py`，README 里有部署步骤，systemd 服务 tb-relay，监听 127.0.0.1:22301，paramiko 写的）自己当 SSH 服务端——SSH 用户名在加密之后才发，纯 TCP 转发看不到，所以必须终结 SSH。设备（工具箱 `py\majing\core\sharetunnel.py`）以用户名 `_device`、密码=码境登录凭证连进来，中转拿凭证去 `code.zuicat.cn/api/auth/me` 核对出码境用户名（防冒名），再 `tcpip-forward` 登记；访客用户名=码境用户名，中转经该设备的通道连到它本机内置 SSH，用访客输入的密码登录，成功才放行，再接 shell/exec/sftp。同一用户名同一时刻一台设备（后来的顶掉）。
- 公网入口：SakuraFrp 节点 46 的 TCP 隧道 `tb_share_ssh`（code.zuicat.cn:41764 → 服务器 127.0.0.1:22301，systemd 服务 `natfrp-share`，启动脚本 `/root/frpc/natfrp-share-start.sh` 复制 natfrp-ssh 的写法）。SakuraFrp 账号令牌在服务器的 ini/进程参数里，**别打印、别写进仓库**（API `https://api.natfrp.com/v4/*`，Bearer 令牌）。
- **码境用户名必须是英文**（`^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$`）：中文等会让原生 ssh 命令乱码，工具箱（`sharetunnel.NAME_RE`）会提示“请先把码境用户名改成英文”并且不开公网入口，中转（relay.py）也拒绝这类设备。设备端内置 SSH 对来源 127.0.0.1（经中转）的连接，用户名固定 `relay`，只看密码；“连错 5 次锁 10 分钟”变成全局锁（来源都是 127.0.0.1），中转另外按用户名限速（8 次/5 分钟）。
- 限制：不支持 `ssh -L/-J`（设备端内置 SSH 不支持端口转发）；中转处会解开会话再转发，不是端到端加密（中转是自己的服务器，访客密码是一次性随机的）。
- **别拿真实码境用户名去测公网中转**：同一用户名只留最新一台设备，测试的设备会顶掉用户正在用的那台，测试的访客连接还会落到用户电脑上、出现在他的共享窗口里（2026-11-25 就这样让用户看到了 7 条“莫名其妙的连接”）。本地测试用回环直连（`username="relay"` 连 `127.0.0.1:本机端口`，并把 `sharetunnel.precheck` 打桩、`ShareTunnel.start` 置空）；真要测中转，先让用户关掉自己的共享，或用别的码境账号。
- **访客身份（自称，没法核实）**：ssh 用户名写成 `目标码境用户名+我的码境用户名`（如 `ssh -p 41764 mcm+zuicat@code.zuicat.cn`），中转拆开后用 `relay+我的名字` 去登录被控端，被控端共享窗口显示“码境用户 xxx（自称）”。工具箱当访客连 `code.zuicat.cn:41764` 时 `sshhosts._relay_user` 自动接上自己的码境用户名。想做成可核实的，得让访客用码境凭证向中转证明身份（原生 ssh 做不到，凭证也不能放进明文的版本串里）。
- **中转泄漏教训（2026-11-25）**：`relay.serve` 里认证后马上断开的访客（如连通性复测）走了提前返回、没关通往设备的上游连接，被控端的会话越积越多（每分钟一条）。现在 `serve` 用 try/finally 保证无论怎样结束都关 `up_tr`，判断“认证成功”用 `iface.role` 而不是 `t.is_authenticated()`（认证后立刻断开它也返回 False）。回归测试：本地起 relay（`LISTEN_PORT=22400`，打桩 `who`）+ 本地设备，反复正常关闭/连上即关/直接断 TCP/错密码，设备 `sessions` 都应回到 0；测试要用临时 APPDATA，否则本地中转的随机主机密钥会写进 `share_tunnel_known_hosts` 造成下次 BadHostKey。
- 共享图标（SSH 页主机列表头部的分享图标 / 旧布局的“共享本机”按钮）右下角有人数角标（`PeopleBadge`，按人数不是连接数）；有新的人连上，`App.tsx` 里全局的 `ShareToast`（`components/share-people.tsx`，同文件里是 `groupSessions`）在右上角弹提示“码境用户 xxx 连上了你的电脑”，不管当前在哪个页面。同一个人的多条连接只算一个人，不会重复弹。
- 共享窗口的连接列表按访客合并成一行（公网按码境用户名，其它按来源 IP），“踢掉”会断开这个人的所有连接；不显示每条连接的用途，也没有小字日志（设备端仍记录 kinds，界面不用）：VS Code Remote-SSH、Termius 这类客户端一个人就会同时开好几条。
- 测试：本机没法直接连服务器回环端口时，`ssh -L 22302:127.0.0.1:22301 …` 转出来，设 `MAJING_RELAY_HOST/PORT` 指过去；原生 ssh 测试要 `-o UserKnownHostsFile=/dev/null`（Windows 的 `NUL` 在 git-bash 下会生成名叫 NUL 的文件）。换了中转主机密钥后，已连过的人会看到主机密钥变更警告。
- 添加主机对话框顶部有「使用命令添加」：粘贴 `ssh -p 端口 用户@主机`（认 -p/-l/-i/-o Port=…、`-p2222` 连写、IPv6 方括号），自动填好别名/地址/端口/用户名/私钥；密码另填。解析函数 `parseSshCmd`（ssh.tsx）。
- 旧的“设备 ID 中转”（`/opt/claude-gate`、`majing-remote.exe`）原生 ssh 连不上它的端口，已不用；组件仍保留在 `py
es`，不随程序启动、不进负载包。
- 本机经 Clash 虚拟网卡时，对任何远端端口 `connect` 都会先成功，“端口开着”的探测结果不可信，要读到真实 banner 才算数。

## 文献翻译（工具页「文献」卡片，2026-11-27）
- **2026-11-27 用户要求暂时关闭、不接入发布**：2.0.71/2.0.72 曾发布过，之后用总开关关掉了——`litrans.ENABLED = False`（不注册热键、已开过的也会撤掉）+ `online.tsx` 的 `LIT_ENABLED = false`（卡片不显示）。代码和文档都留着；恢复就把这两个开关改成 True。以下是功能本身的说明。
- 移植自开源项目 FlashTrans（chai1220，MIT，许可证放在 `web\LICENSE-FlashTrans-MIT`）的**在线 API 路径**：输入即译工作台 + 全局划词热键 + 鼠标旁弹窗。**没移植**本地模型（NLLB/GGUF）、截图 OCR、对话、F2 打字弹窗。用户自己填接口地址/模型/密钥（默认 `api.deepseek.com` / `deepseek-flash`）。
- 后端 `py\majing\core\litrans.py`：`Translator`（requests.Session 复用连接、DeepSeek 域名带 `thinking:disabled`、SSE 按字节切行再转 UTF-8、LRU 缓存 200 条、失败重试一次、warmup 预热 TLS）；`Hotkey`（独立线程 RegisterHotKey + 消息循环）；`grab_selection`（keybd_event 模拟 Ctrl+C，用 `GetClipboardSequenceNumber` 判断复制完成）；弹窗定位/置顶/不抢焦点的 ctypes 辅助（**用自己的 `ctypes.WinDLL` 句柄**，不和别处的 user32 函数对象互相覆盖 argtypes）。
- **密钥**：用 `account._protect`（DPAPI）加密后存在设置文件的 `lit_key`，`app_info` 不把它发给前端；前端只知道 `has_key`。别把用户在聊天里贴的密钥写进任何文件。
- 弹窗是 `api._lit_popup_win` 懒创建的第二个 pywebview 窗口（无边框、置顶、`focus=False`，再补 WS_EX_NOACTIVATE|TOOLWINDOW 和 Win11 圆角），藏着备用；地址 = 主窗口 `real_url` 去掉查询再加 `?lit=popup`，`main.tsx` 看到它只渲染 `pages\lit-popup.tsx`。**不能先建窗再改地址**：`create_window` 在非主线程一调用就开始加载了。退出时 `_shutdown` 要销毁弹窗窗口，不然 `webview.start` 不返回。`_hwnd()` 按标题 `码境工具箱` 找主窗口，弹窗标题叫“文献翻译”，互不干扰。
- 前端 `pages\literature.tsx`（工作台+设置），`online.tsx` 里第一张卡片切换到它；`mock.ts` 有 `lit_*` 的模拟。
- 测试：假 SSE 服务（流式、汉字被劈开、缓存、401、密钥不明文落盘）已跑通；真窗口里（临时 APPDATA + CDP + `win_front` 把自己的窗口放前台，再用 keybd_event 发 Ctrl+Alt+F9）验证了：热键触发→弹窗在鼠标旁出现（置顶、不抢焦点、不进任务栏）→流式译文→`lit_popup_hide`。**测热键前必须先让自己的窗口在前台**，否则 Ctrl+C 会落到别的程序。**没验证**：真 DeepSeek 接口、真划词（在浏览器/PDF 阅读器里）、停留秒数自动收起、热键被别的程序占用时的提示、打包版 exe。

## 状态（2.0.4，2026-11-22 已发布）
已验证：PPT 真 PowerPoint 导出、格式转换、SSH 管理、安装→运行→卸载、自动更新替换重启、真实资源管理器拖放（框变色、入队正常）、转换历史写入/重启保留、长文件名下布局无横向滚动。
**没验证**：WPS 引擎、共享本机时有人来连的审批弹窗、SmartScreen 行为、公网访问共享本机（需网关开端口，用户未决定）、码境账号完整授权链路（2026-11-24 起设置页已显示，`SHOW_ACCOUNT`；服务器 device/start 实测可用，网页授权点“授权”这一步还没走过）。

## 用户偏好
- 追求界面好看、操作少；文案简短，中文。小功能先做出来给他看。
- 他自己做真人测试；你要做真机验证时别抢他的鼠标/键盘太久，别留后台进程（测完 kill 自己起的测试实例，别动他正在用的那个）。
- 不要把他在聊天里贴的密码/密钥写进文件。
