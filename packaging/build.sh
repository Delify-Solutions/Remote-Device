#!/usr/bin/env bash
# packaging/build.sh <windows|macos> — dựng BỘ CÀI iPhone Farm (tải về, bấm cài, không phải cài Python / thư viện).
#
#   Windows → dist/iPhoneFarm-Setup-<bản>.exe      (Inno Setup; cài vào %LOCALAPPDATA%\iPhoneFarm, không cần quyền admin)
#   macOS   → dist/iPhoneFarm-<bản>-macos-arm64.dmg (kéo «iPhone Farm» vào Applications; lần mở đầu tự cài vào ~/Library/iPhoneFarm)
#
# Bộ cài mang theo: mã app, Python 3.12 «chạy được ở đâu cũng được» (python-build-standalone, ghim bản + mã kiểm), toàn bộ thư viện
# dạng wheel và mô hình đọc chữ → lúc cài KHÔNG cần mạng. Lúc cài chỉ tạo .venv từ Python kèm theo rồi cài wheel vào đó — đúng cách
# bố trí mà app vẫn chạy (run.bat / run.command, app/venvbin.py), nên không phải đổi dòng mã nào của app.
#
# Chạy trên đúng hệ điều hành đích (Windows: Git Bash; macOS: máy Apple Silicon). Biến môi trường:
#   IPF_VERSION              tên bản (mặc định: git describe)
#   IPF_DEFAULT_GROUPS_B64   nội dung groups.json mặc định, mã hoá base64  (nhóm + kịch bản có sẵn khi cài máy mới)
#   IPF_DEFAULT_GROUPS       hoặc đường dẫn tới file đó; không đặt gì thì dùng app/defaults/groups.json nếu có (file này không vào git)
set -euo pipefail
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8      # Python kèm theo in tiếng Việt: máy dựng Windows mặc định cp1252 → lỗi mã hoá

PLATFORM="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="${IPF_VERSION:-$(git describe --tags --always --dirty)}"

PBS_TAG=20261124
PBS_PY=3.12.16
case "$PLATFORM" in
  windows)
    PBS_ARCH=x86_64-pc-windows-msvc
    PBS_SHA=8152ff5b6c6c044ddbbaa3531dda59cb9ce5bd6cb670d4c9ac2e3ab91afa8778
    RT_PY=runtime/python.exe; VENV_BIN=Scripts; VENV_SITE=Lib/site-packages; EXE=.exe ;;
  macos)
    [ "$(uname -m)" = arm64 ] || { echo "✗ bản macOS dựng trên máy Apple Silicon (arm64)"; exit 1; }
    PBS_ARCH=aarch64-apple-darwin
    PBS_SHA=431b99a9c2cdd37ad9b06e425be0e520d2dbce0552abe454257abef592fe3634
    RT_PY=runtime/bin/python3; VENV_BIN=bin; VENV_SITE=lib/python3.12/site-packages; EXE= ;;
  *) echo "Dùng: packaging/build.sh <windows|macos>"; exit 2 ;;
esac

BUILD="$ROOT/build"; STAGE="$BUILD/stage"; DIST="$ROOT/dist"; CACHE="$BUILD/cache"
rm -rf "$STAGE" "$BUILD/smoke"
mkdir -p "$STAGE" "$DIST" "$CACHE"
echo "== iPhone Farm $VER — $PLATFORM"

# ---- 1. mã app: đúng các file đang được git theo dõi (không lẫn app/data, .venv, log…) ----
# (SETUP.md là nhật ký dựng máy của nhà phát triển — không đưa vào bộ cài)
PAYLOAD=(app farm farm.bat farm.conf devices.py requirements-windows.txt run.bat run.command setup.bat
         scan_devices.sh start_wda_farm.sh stop_wda_farm.sh .mcp.json .gitattributes)
git ls-files -z -- "${PAYLOAD[@]}" | tar --null -T - -cf - | tar -xf - -C "$STAGE"
[ -f "$STAGE/app/gui.py" ] || { echo "✗ không chép được mã app"; exit 1; }
[ ! -e "$STAGE/app/data" ] || { echo "✗ app/data lọt vào bộ cài"; exit 1; }

# ---- 2. Python kèm theo (ghim bản, kiểm mã SHA-256 trước khi dùng) ----
ASSET="cpython-${PBS_PY}+${PBS_TAG}-${PBS_ARCH}-install_only.tar.gz"
if [ ! -f "$CACHE/$ASSET" ]; then
  curl -fL --retry 3 -o "$CACHE/$ASSET.part" \
    "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${ASSET//+/%2B}"
  mv "$CACHE/$ASSET.part" "$CACHE/$ASSET"
fi
if command -v sha256sum >/dev/null 2>&1; then GOT="$(sha256sum "$CACHE/$ASSET" | cut -d' ' -f1)"; else GOT="$(shasum -a 256 "$CACHE/$ASSET" | cut -d' ' -f1)"; fi
[ "$GOT" = "$PBS_SHA" ] || { echo "✗ sai mã kiểm của $ASSET: $GOT"; rm -f "$CACHE/$ASSET"; exit 1; }
tar -xzf "$CACHE/$ASSET" -C "$STAGE"
mv "$STAGE/python" "$STAGE/runtime"
"$STAGE/$RT_PY" -c "import sys, venv, ensurepip; print('Python kèm theo:', sys.version.split()[0])"

# ---- 3. dữ liệu mặc định (nhóm + kịch bản): không nằm trong git, đưa vào lúc dựng ----
DEF_SRC=""
if [ -n "${IPF_DEFAULT_GROUPS_B64:-}" ]; then
  DEF_SRC="$BUILD/default-groups.json"
  printf '%s' "$IPF_DEFAULT_GROUPS_B64" | "$STAGE/$RT_PY" -c "import sys, base64; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))" > "$DEF_SRC"
elif [ -n "${IPF_DEFAULT_GROUPS:-}" ]; then
  DEF_SRC="$IPF_DEFAULT_GROUPS"
elif [ -f app/defaults/groups.json ]; then
  DEF_SRC=app/defaults/groups.json
fi
if [ -n "$DEF_SRC" ]; then
  mkdir -p "$STAGE/app/defaults"
  # chỉ nhận danh sách nhóm hợp lệ; BỎ tên máy của từng nhóm (máy là của riêng từng nơi cài)
  "$STAGE/$RT_PY" - "$DEF_SRC" "$STAGE/app/defaults/groups.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8-sig"))
if not isinstance(data, list) or not all(isinstance(g, dict) and isinstance(g.get("id"), str) and g["id"] for g in data):
    sys.exit("✗ dữ liệu mặc định không phải danh sách nhóm hợp lệ")
for g in data:
    if "devices" in g:
        g["devices"] = []
json.dump(data, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Dữ liệu mặc định: %d nhóm, %d kịch bản" % (len(data), sum(len(g.get("scripts") or []) for g in data)))
PY
else
  echo "Dữ liệu mặc định: KHÔNG có (bản cài sẽ trống nhóm / kịch bản)"
fi

# ---- 4. thư viện: gom thành wheel bằng CHÍNH Python kèm theo (đúng bản, đúng hệ máy) ----
# packaging/constraints.txt ghim ĐÚNG bản của từng thư viện (kể cả thư viện kéo theo) đã qua cài thử — bản phát hành dựng lại vẫn ra cùng bộ.
cp packaging/constraints.txt "$STAGE/constraints.txt"
"$STAGE/$RT_PY" -m pip wheel --disable-pip-version-check -q -r requirements-windows.txt -c packaging/constraints.txt -w "$STAGE/wheels"
echo "Wheel: $(ls "$STAGE/wheels" | wc -l | tr -d ' ') gói"

# ---- 5. cài thử từ wheel (không mạng) + lấy mô hình đọc chữ để bộ cài không phải tải ----
"$STAGE/$RT_PY" -m venv "$BUILD/smoke"
SPY="$BUILD/smoke/$VENV_BIN/python$EXE"
"$SPY" -m pip install --disable-pip-version-check -q --no-index --find-links "$STAGE/wheels" -r requirements-windows.txt -c packaging/constraints.txt
"$SPY" -m pip freeze --disable-pip-version-check > "$BUILD/freeze-$PLATFORM.txt"      # để cập nhật packaging/constraints.txt
IPF_OCR=rapid PYTHONUTF8=1 "$SPY" -c "
import sys
sys.path.insert(0, 'app')
import ocr
ok = ocr.available()
print('Bộ đọc chữ:', ocr.engine_name() if ok else 'LỖI - ' + ocr.why_unavailable())
sys.exit(0 if ok else 1)"
mkdir -p "$STAGE/models"
cp "$BUILD/smoke/$VENV_SITE/rapidocr/models/"*.onnx "$STAGE/models/"
echo "Mô hình đọc chữ: $(ls "$STAGE/models" | wc -l | tr -d ' ') tệp"

printf '%s\n' "$VER" > "$STAGE/VERSION"
{
  echo "iPhone Farm $VER ($PLATFORM)"
  echo "commit: $(git rev-parse HEAD)$(git diff --quiet HEAD -- "${PAYLOAD[@]}" || echo ' + thay đổi chưa commit')"
  echo "python: $PBS_PY ($PBS_TAG, $PBS_ARCH)"
  echo "wheels:"; ls "$STAGE/wheels" | sed 's/^/  /'
} > "$STAGE/BUILD-INFO.txt"

# ---- 6. đóng gói theo hệ điều hành ----
if [ "$PLATFORM" = windows ]; then
  cp packaging/windows/install-env.bat "$STAGE/install-env.bat"
  # thư viện C++ của Microsoft mà onnxruntime / opencv cần: đặt cạnh python.exe để máy chưa cài «VC++ Redistributable» vẫn chạy
  for f in msvcp140.dll msvcp140_1.dll msvcp140_2.dll vcruntime140_1.dll concrt140.dll; do
    if [ ! -f "$STAGE/runtime/$f" ] && [ -f "/c/Windows/System32/$f" ]; then cp "/c/Windows/System32/$f" "$STAGE/runtime/$f"; fi
  done
  ISCC="$(command -v iscc 2>/dev/null || true)"
  [ -n "$ISCC" ] || ISCC="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
  [ -f "$ISCC" ] || { echo "✗ chưa có Inno Setup 6 (choco install innosetup)"; exit 1; }
  OUT="iPhoneFarm-Setup-$VER"
  rm -f "$DIST/$OUT.exe"
  MSYS2_ARG_CONV_EXCL='*' "$ISCC" "/Qp" "/DIpfVer=$VER" "/DIpfStage=$(cygpath -w "$STAGE")" "/DIpfOutDir=$(cygpath -w "$DIST")" "/DIpfOutName=$OUT" \
    "$(cygpath -w "$ROOT/packaging/windows/installer.iss")"
  ls -la "$DIST/$OUT.exe"
else
  APP="$BUILD/iPhone Farm.app"
  rm -rf "$APP" "$BUILD/dmg"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$BUILD/dmg"
  mv "$STAGE" "$APP/Contents/Resources/payload"
  cp packaging/macos/launcher.sh "$APP/Contents/MacOS/iPhoneFarm"
  chmod +x "$APP/Contents/MacOS/iPhoneFarm"
  NUMVER="$(printf '%s' "$VER" | sed -E 's/^v//')"
  printf '%s' "$NUMVER" | grep -Eq '^[0-9]+(\.[0-9]+){1,3}$' || NUMVER=0.0.0
  # macOS tối thiểu = bản cao nhất mà một wheel kèm theo đòi (vd opencv 5 cho Apple Silicon cần macOS 15) — ghi thật vào app + hướng dẫn
  MINOS="$(ls "$APP/Contents/Resources/payload/wheels" | sed -nE 's/.*-macosx_([0-9]+)_([0-9]+)_[a-z0-9_]+\.whl$/\1 \2/p' \
           | awk 'BEGIN { M = 11; m = 0 } { if ($1 > M || ($1 == M && $2 > m)) { M = $1; m = $2 } } END { print M "." m }')"
  echo "macOS tối thiểu: $MINOS"
  sed -e "s/@NUMVER@/$NUMVER/g" -e "s/@VER@/$VER/g" -e "s/@MINOS@/$MINOS/g" packaging/macos/Info.plist > "$APP/Contents/Info.plist"
  codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "(không ký ad-hoc được — bỏ qua)"
  mv "$APP" "$BUILD/dmg/"
  ln -s /Applications "$BUILD/dmg/Applications"
  sed -e "s/@MINOS@/$MINOS/g" packaging/macos/README.txt > "$BUILD/dmg/DOC TRUOC KHI MO.txt"
  printf '%s\n' "$MINOS" > "$BUILD/macos-min-version.txt"
  OUT="$DIST/iPhoneFarm-$VER-macos-arm64.dmg"
  rm -f "$OUT"
  hdiutil create -quiet -volname "iPhone Farm" -srcfolder "$BUILD/dmg" -ov -format UDZO "$OUT"
  ls -la "$OUT"
fi
echo "✓ xong: $DIST"
