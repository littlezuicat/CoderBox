# 克劳德工具箱（码境）

Windows 桌面工具箱：**PPT 定图**、**格式转换**（ffmpeg）、**SSH 管理**（主机列表、SFTP 文件树 + 编辑器、内嵌终端、GPU 总览、共享本机）、**密码库**（本机加密 + 浏览器自动填充扩展）、在线工具、设置。

界面是 React + MUI（Vite），外壳是 pywebview（系统自带的 WebView2），后端是 Python，用 PyInstaller 打成单文件 exe（兼作安装包）。界面风格参考 Clash Verge Rev。

## 开发

需要 Windows 10/11、Python 3.11、Node 20+。

```powershell
cd toolbox
powershell -ExecutionPolicy Bypass -File setup.ps1                 # 第一次：虚拟环境 + 依赖
cd web; npm run build; cd ..                                        # 构建界面
.venv\Scripts\python.exe py\main.py --portable --no-update          # 运行
cd web; npm run dev                                                 # 浏览器里调界面（mock 后端）
```

打包：`.\release.ps1 -NoUpload` → `dist\MajingToolbox.exe`。发布到自己的服务器需要把 `release.config.example.json` 复制为 `release.config.json` 并填写（该文件不会入库）。

目录结构、两层打包与增量更新、各功能的实现细节和踩过的坑见 [CLAUDE.md](CLAUDE.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `toolbox/py` | Python 后端（`main.py` 入口、`api.py` 前端接口、`majing/core` 各功能） |
| `toolbox/web` | React 前端 |
| `toolbox/extension` | Chrome/Edge 密码自动填充扩展（MV3） |
| `toolbox/deploy` | 服务器侧脚本（发布、共享中转、密码同步、VS Code Server 镜像） |
| `toolbox/tools` | 打包辅助脚本 |
| `toolbox/brand` | LOGO 素材 |

## 许可证

[GPL-3.0](LICENSE)。前端部分界面代码参考了 [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)（GPL-3.0）。
