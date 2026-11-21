# 一条命令发布：版本号 +1（可选）→ 前端打包 → PyInstaller 打 exe → 上传服务器并发布。
#   release.ps1 -Bump -Notes "一句话更新说明"     正常发布（版本号 patch+1）
#   release.ps1 -NoUpload                         只打包不上传（先自己试 dist\MajingToolbox.exe）
#   release.ps1 -Notes "说明"                     不改版本号直接发（版本号必须已经比线上新）
# 服务器只负责分发：它收到 exe 后检查、备份旧版、写 version.json，工具箱检测到就自动更新。
param([switch]$Bump, [string]$Notes = "", [switch]$NoUpload)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$init = 'py\majing\__init__.py'
$txt = [IO.File]::ReadAllText("$PSScriptRoot\$init", [Text.Encoding]::UTF8)
if ($txt -notmatch 'APP_VERSION = "(\d+)\.(\d+)\.(\d+)"') { throw "$init 里找不到 APP_VERSION" }
$ver = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
if ($Bump) {
  $new = "$($Matches[1]).$($Matches[2]).$([int]$Matches[3] + 1)"
  $txt = $txt -replace 'APP_VERSION = "\d+\.\d+\.\d+"', "APP_VERSION = `"$new`""
  [IO.File]::WriteAllText("$PSScriptRoot\$init", $txt, (New-Object Text.UTF8Encoding($false)))
  "版本号 $ver -> $new"; $ver = $new
}
"== 前端打包"
Push-Location web
if (-not (Test-Path node_modules)) { npm ci }
npm run build
if ($LASTEXITCODE) { throw '前端打包失败' }
Pop-Location
"== PyInstaller"
.venv\Scripts\pyinstaller.exe --noconfirm --clean MajingToolbox.spec
if ($LASTEXITCODE) { throw 'PyInstaller 失败' }
$exe = Join-Path $PSScriptRoot 'dist\MajingToolbox.exe'
$size = (Get-Item $exe).Length
"== 产物 $exe  $size 字节  sha256 " + (Get-FileHash $exe -Algorithm SHA256).Hash
if ($size -lt 20000000) { throw 'exe 太小，打包可能不完整' }
if ($NoUpload) { "只打包，没上传。"; return }
$cfgPath = Join-Path $PSScriptRoot 'release.config.json'
if (-not (Test-Path $cfgPath)) { throw "没有 release.config.json：复制 release.config.example.json 改成你的服务器 ssh 信息" }
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sshArgs = @('-p', $cfg.ssh_port); if ($cfg.ssh_key) { $sshArgs += @('-i', $cfg.ssh_key) }
$scpArgs = @('-P', $cfg.ssh_port); if ($cfg.ssh_key) { $scpArgs += @('-i', $cfg.ssh_key) }
$remoteTmp = "/tmp/MajingToolbox-$ver.exe"
"== 上传到服务器"
scp @scpArgs $exe "$($cfg.ssh_target):$remoteTmp"
if ($LASTEXITCODE) { throw '上传失败' }
$b64 = 'b64:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Notes))
"== 服务器发布"
ssh @sshArgs $cfg.ssh_target "bash $($cfg.remote_script) $remoteTmp $ver $b64"
if ($LASTEXITCODE) { throw '服务器发布失败（线上没有改动）' }
"完成：$ver 已发布，工具箱会自动更新。"
