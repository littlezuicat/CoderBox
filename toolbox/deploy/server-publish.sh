#!/bin/bash
# 服务器端发布脚本：由 Windows 上的 release.ps1 通过 ssh 调用（每次发布前 release.ps1 会把这份脚本传到服务器覆盖）。只做分发，不含源码。
#
#   publish.sh --version X.Y.Z --notes <说明 | b64:base64(说明)> --payload <负载包.zip> --runtime <运行时id> [--exe <整包.exe>] [--ffmpeg <ffmpeg.tar.xz>]
#
# 两种发布：
#   · 日常（只带 --payload）：只传约 0.5 MB 的负载包。运行时 id 必须和线上整包的一致，否则拒绝（要连 exe 一起传）。
#   · 整包（带 --exe）：第三方依赖变了。exe 里内置了同版本的负载包。
# version.json：{version, exe, size, sha256, exe_version, runtime, payload:{file,size,sha256,runtime}, notes}
#   顶层 exe/size/sha256 永远描述“线上那个整包”（老版本工具箱只认这几项，所以老版本也能更新上来）。
# 环境变量 WEBROOT（默认 /var/www/toolbox）、SUDO（默认 sudo；测试时设成空）。
set -euo pipefail
WEBROOT="${WEBROOT:-/var/www/toolbox}"
SUDO="${SUDO-sudo}"
VER=""; NOTES=""; PAYLOAD=""; RUNTIME=""; EXE=""; FFMPEG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VER="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --payload) PAYLOAD="$2"; shift 2 ;;
    --runtime) RUNTIME="$2"; shift 2 ;;
    --exe) EXE="$2"; shift 2 ;;
    --ffmpeg) FFMPEG="$2"; shift 2 ;;
    *) echo "不认识的参数：$1"; exit 1 ;;
  esac
done
case "$NOTES" in b64:*) NOTES=$(printf '%s' "${NOTES#b64:}" | base64 -d) ;; esac
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "版本号格式不对：$VER"; exit 1; }
[ -n "$PAYLOAD" ] && [ -f "$PAYLOAD" ] || { echo "缺少负载包：--payload"; exit 1; }
[[ "$RUNTIME" =~ ^[0-9a-f]{8,64}$ ]] || { echo "运行时 id 格式不对：$RUNTIME"; exit 1; }
OLDJSON="$WEBROOT/version.json"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
if [ -f "$OLDJSON" ]; then cp "$OLDJSON" "$WORK/old.json"; else echo '{"version":"0.0.0"}' > "$WORK/old.json"; fi
OLDJSON="$WORK/old.json"          # 后面都读这份拷贝：写新 version.json 时旧文件会被覆盖，不能边读边写

# 版本号必须比线上新
python3 - "$VER" "$OLDJSON" <<'PY' || { echo "版本号 $VER 不比线上的新"; exit 1; }
import json, sys
n = lambda v: tuple(int(x) for x in v.split("."))
sys.exit(0 if n(sys.argv[1]) > n(json.load(open(sys.argv[2]))["version"]) else 1)
PY
OLD=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$OLDJSON")

# 负载包：是 zip、payload.json 里的版本和运行时 id 对得上
python3 - "$PAYLOAD" "$VER" "$RUNTIME" <<'PY' || exit 1
import json, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
if z.testzip() is not None:
    sys.exit("负载包损坏")
m = json.loads(z.read("payload.json").decode("utf-8"))
if m.get("version") != sys.argv[2] or m.get("runtime") != sys.argv[3]:
    sys.exit("负载包里的版本/运行时 id（%s / %s）和参数对不上" % (m.get("version"), m.get("runtime")))
PY

if [ -n "$EXE" ]; then
  [ "$(head -c2 "$EXE")" = "MZ" ] || { echo "不是 Windows exe：$EXE"; exit 1; }
  [ "$(stat -c %s "$EXE")" -gt 15000000 ] || { echo "exe 太小（$(stat -c %s "$EXE") 字节），像是没打完整"; exit 1; }
else
  # 只传负载包：运行时 id 必须和线上整包的一致
  python3 - "$OLDJSON" "$RUNTIME" <<'PY' || { echo "运行时 id 和线上整包不一致：这次发布必须带 --exe（第三方依赖变了）"; exit 1; }
import json, sys
sys.exit(0 if json.load(open(sys.argv[1])).get("runtime") == sys.argv[2] else 1)
PY
fi

$SUDO install -d -m 755 "$WEBROOT/_prev" "$WEBROOT/payload"
[ -f "$WEBROOT/version.json" ] && $SUDO cp "$WEBROOT/version.json" "$WEBROOT/_prev/version-$OLD.json"
if [ -n "$EXE" ] && [ -f "$WEBROOT/MajingToolbox.exe" ]; then
  [ -f "$WEBROOT/_prev/MajingToolbox-$OLD.exe" ] || $SUDO cp "$WEBROOT/MajingToolbox.exe" "$WEBROOT/_prev/MajingToolbox-$OLD.exe"
fi
[ -n "$EXE" ] && $SUDO install -m 644 "$EXE" "$WEBROOT/MajingToolbox.exe"
$SUDO install -m 644 "$PAYLOAD" "$WEBROOT/payload/payload-$VER.zip"
[ -n "$FFMPEG" ] && $SUDO install -m 644 "$FFMPEG" "$WEBROOT/ffmpeg-8.1-win64.tar.xz"
# 负载包只留最近 6 个
(cd "$WEBROOT/payload" && ls -1 payload-*.zip | sort -V | head -n -6 | xargs -r $SUDO rm -f)

python3 - "$OLDJSON" "$VER" "$RUNTIME" "$NOTES" "$WEBROOT/MajingToolbox.exe" "$WEBROOT/payload/payload-$VER.zip" "${EXE:+1}" <<'PY' > "$WORK/new.json"
import hashlib, json, os, sys
old = json.load(open(sys.argv[1]))
ver, runtime, notes, exe_path, pl_path, new_exe = sys.argv[2:8]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
d = {"version": ver, "exe": "MajingToolbox.exe", "size": os.path.getsize(exe_path), "sha256": sha(exe_path)}
if new_exe:
    d["exe_version"], d["runtime"] = ver, runtime
else:
    d["exe_version"] = old.get("exe_version") or old.get("version")
    d["runtime"] = old.get("runtime", runtime)
d["payload"] = {"file": "payload-%s.zip" % ver, "size": os.path.getsize(pl_path), "sha256": sha(pl_path), "runtime": runtime}
d["notes"] = notes
print(json.dumps(d, ensure_ascii=False))
PY
$SUDO install -m 644 "$WORK/new.json" "$WEBROOT/version.json"
rm -f "$EXE" "$PAYLOAD" "$FFMPEG"
echo "已发布 $VER（原线上 $OLD）${EXE:+，含新整包 exe}："; cat "$WEBROOT/version.json"
