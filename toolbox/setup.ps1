# 一次性准备开发环境：Python 虚拟环境 + 依赖 + 前端依赖。用法：在 toolbox 目录里  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) { py -3.11 -m venv .venv }
$req = if (Test-Path requirements.lock) { 'requirements.lock' } else { 'requirements.txt' }
.venv\Scripts\python.exe -m pip install -r $req pyinstaller
Push-Location web
if (Get-Command npm -EA SilentlyContinue) { if (Test-Path package-lock.json) { npm ci } else { npm install } } else { Write-Warning '没找到 Node.js/npm：前端要改、要打包就先装 Node 20+ (https://nodejs.org)' }
Pop-Location
'环境就绪。跑程序：.venv\Scripts\python.exe py\main.py --portable --no-update   发布：release.ps1 -Bump -Notes "说明"'
