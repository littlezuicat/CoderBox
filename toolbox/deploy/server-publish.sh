#!/bin/bash
# 服务器端发布脚本：由 Windows 上的 release.ps1 通过 ssh 调用。只做分发，不含源码。
#   publish.sh <已上传的 exe> <版本号> <更新说明 | b64:base64(更新说明)>
# 检查：是 Windows exe、体积正常、版本号比线上新；旧版备份到 /var/www/toolbox/_prev/，再写 version.json。
set -euo pipefail
EXE="${1:?exe}"; VER="${2:?version}"; NOTES="${3:-}"
case "$NOTES" in b64:*) NOTES=$(printf '%s' "${NOTES#b64:}" | base64 -d) ;; esac
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "版本号格式不对：$VER"; exit 1; }
OLD=$(python3 -c "import json;print(json.load(open('/var/www/toolbox/version.json'))['version'])")
SIZE=$(stat -c %s "$EXE")
[ "$(head -c2 "$EXE")" = "MZ" ] || { echo "不是 Windows exe：$EXE"; exit 1; }
[ "$SIZE" -gt 20000000 ] || { echo "exe 太小（$SIZE 字节），像是没打完整"; exit 1; }
python3 - "$VER" "$OLD" <<'PY' || { echo "版本号 $VER 不比线上的 $OLD 新"; exit 1; }
import sys
n = lambda v: tuple(int(x) for x in v.split("."))
sys.exit(0 if n(sys.argv[1]) > n(sys.argv[2]) else 1)
PY
sudo install -d -m 755 /var/www/toolbox/_prev
[ -f "/var/www/toolbox/_prev/MajingToolbox-$OLD.exe" ] || sudo cp /var/www/toolbox/MajingToolbox.exe "/var/www/toolbox/_prev/MajingToolbox-$OLD.exe"
sudo cp /var/www/toolbox/version.json "/var/www/toolbox/_prev/version-$OLD.json"
sudo install -m 644 "$EXE" /var/www/toolbox/MajingToolbox.exe
python3 - "$VER" "$SIZE" "$(sha256sum "$EXE" | cut -d' ' -f1)" "$NOTES" <<'PY' | sudo tee /var/www/toolbox/version.json >/dev/null
import json, sys
v, size, sha, notes = sys.argv[1:5]
print(json.dumps({"version": v, "exe": "MajingToolbox.exe", "size": int(size), "sha256": sha, "notes": notes}, ensure_ascii=False))
PY
rm -f "$EXE"
echo "已发布 $VER（原线上 $OLD，已备份到 _prev）："; cat /var/www/toolbox/version.json
