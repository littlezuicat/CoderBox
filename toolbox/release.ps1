# 一条命令发布：版本号 +1（可选）→ 前端打包 → 生成负载包 → （运行时变了才）PyInstaller 打整包 → 上传服务器发布。
#   release.ps1 -Bump -Notes "一句话更新说明"     日常发布：版本号 patch+1，只上传约 0.5 MB 的负载包
#   release.ps1 -NoUpload                         只在本地打包（负载包 + exe 都出，exe 在 dist\MajingToolbox.exe），先自己试
#   release.ps1 -Full -Notes "说明"               强制连整包 exe 一起发
#   release.ps1 -Ffmpeg                           同时把 stage\ffmpeg\ffmpeg-8.1-win64.tar.xz 传到服务器（组件换了才需要）
# 是否要重新打整包：比较“本地运行时 id”和线上 version.json 里的 runtime。id = 第三方依赖 + 打包配置 + 引导程序 + 用到的模块清单的哈希；
# 一样 = 线上整包还能跑新负载包 = 只传负载包；不一样（加了新依赖等）= 自动连整包一起发。
# 服务器只负责分发：它收到文件后检查、备份旧版、写 version.json，工具箱检测到就自动更新。
param([switch]$Bump, [string]$Notes = "", [switch]$NoUpload, [switch]$Full, [switch]$Ffmpeg)
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
"== 负载包"
$pj = .venv\Scripts\python.exe tools\build_payload.py | Select-Object -Last 1 | ConvertFrom-Json
if (-not $pj) { throw '生成负载包失败' }
"负载包 $($pj.version)  $($pj.size) 字节  运行时 id $($pj.runtime)"

# 要不要重新打整包
$needExe = $Full -or $NoUpload
if (-not $needExe) {
  try {
    $online = Invoke-RestMethod -Uri ("https://www.zuicat.cn/toolbox/version.json?t=" + [int][double]::Parse((Get-Date -UFormat %s))) -TimeoutSec 15
    if ($online.runtime -ne $pj.runtime) { $needExe = $true; "线上运行时 id 是 [$($online.runtime)]，和本地不同 → 这次要连整包一起发" }
    else { "运行时 id 和线上一致 → 只发负载包" }
  } catch { $needExe = $true; "查不到线上 version.json（$($_.Exception.Message)）→ 保险起见连整包一起发" }
}
$exe = Join-Path $PSScriptRoot 'dist\MajingToolbox.exe'
if ($needExe) {
  "== PyInstaller"
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # PyInstaller 的 INFO 走 stderr，别当成错误
  try {
    .venv\Scripts\pyinstaller.exe --noconfirm --clean MajingToolbox.spec 2>&1 | ForEach-Object { "$_" } | Out-Host
    $pyiCode = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prevEap }
  if ($pyiCode) { throw 'PyInstaller 失败' }
  $size = (Get-Item $exe).Length
  "== 整包 $exe  $size 字节  sha256 " + (Get-FileHash $exe -Algorithm SHA256).Hash
  if ($size -lt 15000000) { throw 'exe 太小，打包可能不完整' }
  "== 自检（把负载包里所有模块 import 一遍）"
  $st = Join-Path $env:TEMP 'majing-selftest.txt'; Remove-Item $st -ErrorAction SilentlyContinue
  $env:MAJING_PORTABLE = '1'
  Start-Process -FilePath $exe -ArgumentList "--selftest=$st" -Wait
  Remove-Item Env:MAJING_PORTABLE
  if (-not (Test-Path $st) -or -not ((Get-Content $st) -match 'RESULT OK')) { Get-Content $st -ErrorAction SilentlyContinue; throw '自检没通过：打进 exe 的运行时缺依赖，先别发布' }
  "自检通过"
}
if ($NoUpload) { "只在本地打包，没上传。负载包 stage\payload-$ver.zip，整包 dist\MajingToolbox.exe"; return }

$cfgPath = Join-Path $PSScriptRoot 'release.config.json'
if (-not (Test-Path $cfgPath)) { throw "没有 release.config.json：复制 release.config.example.json 改成你的服务器 ssh 信息" }
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sshArgs = @('-p', $cfg.ssh_port); if ($cfg.ssh_key) { $sshArgs += @('-i', $cfg.ssh_key) }
$scpArgs = @('-P', $cfg.ssh_port); if ($cfg.ssh_key) { $scpArgs += @('-i', $cfg.ssh_key) }
"== 上传到服务器"
$prevEap2 = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
scp @scpArgs "$PSScriptRoot\deploy\server-publish.sh" "$($cfg.ssh_target):$($cfg.remote_script)"      # 服务器脚本以仓库里这份为准
if ($LASTEXITCODE) { throw '上传服务器脚本失败' }
$rPayload = "/tmp/payload-$ver.zip"
scp @scpArgs $pj.zip "$($cfg.ssh_target):$rPayload"
if ($LASTEXITCODE) { throw '上传负载包失败' }
$args2 = "--version $ver --payload $rPayload --runtime $($pj.runtime)"
if ($needExe) {
  $rExe = "/tmp/MajingToolbox-$ver.exe"
  scp @scpArgs $exe "$($cfg.ssh_target):$rExe"
  if ($LASTEXITCODE) { throw '上传整包失败' }
  $args2 += " --exe $rExe"
}
if ($Ffmpeg) {
  $ff = Join-Path $PSScriptRoot 'stage\ffmpeg\ffmpeg-8.1-win64.tar.xz'
  if (-not (Test-Path $ff)) { throw "没有 $ff：先用 tools\pack_ffmpeg.py 打包" }
  scp @scpArgs $ff "$($cfg.ssh_target):/tmp/ffmpeg-8.1-win64.tar.xz"
  if ($LASTEXITCODE) { throw '上传 ffmpeg 失败' }
  $args2 += " --ffmpeg /tmp/ffmpeg-8.1-win64.tar.xz"
}
$b64 = 'b64:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Notes))
"== 服务器发布"
ssh @sshArgs $cfg.ssh_target "bash $($cfg.remote_script) $args2 --notes $b64"
$pubCode = $LASTEXITCODE
$ErrorActionPreference = $prevEap2
if ($pubCode) { throw '服务器发布失败（线上没有改动）' }
"完成：$ver 已发布（$(if ($needExe) { '含整包' } else { '仅负载包' })），工具箱会自动更新。"
# 发布成功后把这次的改动（含版本号）提交进 git（开源仓库：每次改动都要有提交；密钥/构建产物都在 .gitignore 里）
if (Get-Command git -ErrorAction SilentlyContinue) {
  $oldEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'      # git 的换行警告走 stderr，别让它当成错误中断
  try {
    $top = (git -C $PSScriptRoot rev-parse --show-toplevel 2>$null)
    if ($top) {
      git -C $top add -A 2>$null | Out-Null
      git -C $top diff --cached --quiet 2>$null
      if ($LASTEXITCODE) {
        $msg = "发布 ${ver}: " + $(if ($Notes) { $Notes } else { '更新' }) + "`n`nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
        git -C $top commit -q -m $msg 2>$null | Out-Null
        "已提交 git：发布 $ver"
      }
      if (git -C $top remote 2>$null) {                          # 有远程（GitHub 开源仓库）就顺手推上去；推不上去不算发布失败
        $env:GIT_TERMINAL_PROMPT = '0'
        git -C $top push -q origin HEAD 2>$null | Out-Null
        if ($LASTEXITCODE) { "（git push 没成功，之后手动推一下）" } else { "已推送到 GitHub" }
      }
    }
  } finally { $ErrorActionPreference = $oldEap }
}
