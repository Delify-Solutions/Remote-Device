#!/usr/bin/env bash
# packaging/smoke.sh <windows|macos> — CÀI THỬ bộ cài vừa dựng (dist/) vào một thư mục tạm rồi chạy kiểm tra từ chính bản đã cài.
# Chặn mạng của bước cài (proxy chết) để chắc là cài được khi KHÔNG có mạng.
#
#   bắt buộc đạt : cài xong, nạp được mọi thư viện, lệnh pymobiledevice3 / farm chạy được, bộ đọc chữ, dữ liệu mặc định, test_portable, test_wallets, test_mcp, test_webdev
#   chỉ báo cáo  : các bộ test còn lại — kết quả in ra để xem, không làm hỏng lần dựng. (test_ocr viết cho Apple Vision: trên Windows bộ
#                  RapidOCR đọc sai DẤU tiếng Việt nên các mục so nguyên văn có dấu không đạt; app tìm chữ theo dạng bỏ dấu.)
set -uo pipefail

PLATFORM="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORK="${RUNNER_TEMP:-$ROOT/build}"
INST="$WORK/ipf-smoke-install"
rm -rf "$INST"
bad=0
step() { echo; echo "---- $1"; }
must() { if "$@"; then echo "  ✓ $*"; else echo "  ✗ $*"; bad=$((bad + 1)); fi; }

OFFLINE=(env HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 NO_PROXY= no_proxy=)

if [ "$PLATFORM" = windows ]; then
  SETUP="$(ls dist/iPhoneFarm-Setup-*.exe | head -1)"
  step "cài im lặng (không mạng): $SETUP"
  MSYS2_ARG_CONV_EXCL='*' "${OFFLINE[@]}" "$SETUP" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART "/DIR=$(cygpath -w "$INST")" "/LOG=$(cygpath -w "$WORK/ipf-setup.log")"
  echo "  mã thoát của bộ cài: $?"
  PY="$INST/.venv/Scripts/python.exe"; PMD="$INST/.venv/Scripts/pymobiledevice3.exe"; FARM=(cmd //c "$(cygpath -w "$INST/farm.bat")")
  must test -f "$INST/.venv/ipf-ok"
  must test ! -d "$INST/wheels"
elif [ "$PLATFORM" = macos ]; then
  DMG="$(ls dist/iPhoneFarm-*-macos-arm64.dmg | head -1)"
  MNT="$WORK/ipf-smoke-mnt"
  hdiutil detach "$MNT" -quiet 2>/dev/null
  step "mở $DMG rồi cài (không mạng)"
  hdiutil attach "$DMG" -nobrowse -readonly -quiet -mountpoint "$MNT" || { echo "✗ không mở được dmg"; exit 1; }
  must test -L "$MNT/Applications"
  IPF_HOME="$INST" IPF_SETUP_ONLY=1 "${OFFLINE[@]}" "$MNT/iPhone Farm.app/Contents/MacOS/iPhoneFarm"
  echo "  mã thoát của trình mở: $?"
  # chạy lần hai: đã cài đúng bản → không cài lại (tệp đánh dấu giữ nguyên thời điểm)
  stamp1="$(stat -f %m "$INST/.ipf-installed" 2>/dev/null)"
  IPF_HOME="$INST" IPF_SETUP_ONLY=1 "$MNT/iPhone Farm.app/Contents/MacOS/iPhoneFarm"
  must test "$stamp1" = "$(stat -f %m "$INST/.ipf-installed" 2>/dev/null)"
  hdiutil detach "$MNT" -quiet
  PY="$INST/.venv/bin/python"; PMD="$INST/.venv/bin/pymobiledevice3"; FARM=("$INST/farm")
  must test -f "$INST/.ipf-installed"
else
  echo "Dùng: packaging/smoke.sh <windows|macos>"; exit 2
fi

must test ! -e "$INST/app/data"          # bộ cài không mang theo / không tự tạo dữ liệu người dùng
if [ -f "$INST/install.log" ]; then step "install.log (40 dòng cuối)"; tail -40 "$INST/install.log"; fi
[ -f "$PY" ] || { echo "✗ không có Python của bản cài — dừng"; exit 1; }

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONWARNINGS=ignore
cd "$INST"

step "thư viện + lệnh đi kèm"
must "$PY" -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
must "$PY" -c "import webview, serial, cv2, numpy, PIL, onnxruntime, rapidocr, pymobiledevice3, esptool, cryptography, anthropic, openai, pytesseract"
must "$PMD" version
must "${FARM[@]}" --help

step "bộ đọc chữ RapidOCR đọc được ảnh thật (không mạng)"
must env IPF_OCR=rapid "${OFFLINE[@]}" "$PY" -c "
import sys
sys.path.insert(0, 'app')
import ocr
assert ocr.available(), ocr.why_unavailable()
print('  bộ đọc chữ:', ocr.engine_name())"

step "dữ liệu mặc định → nhóm + kịch bản có sẵn ngay lần mở đầu"
if [ -f app/defaults/groups.json ]; then
  must "$PY" -c "
import json, sys
sys.path.insert(0, 'app')
import store
want = json.load(open('app/defaults/groups.json', encoding='utf-8'))
got = store.get_groups()                       # lần đọc đầu tiên: chưa có app/data/groups.json → nạp từ dữ liệu mặc định
assert json.load(open(store.GROUPS_FILE, encoding='utf-8')) == got, 'chưa ghi thành dữ liệu của người dùng'
assert [g['id'] for g in got] == [g['id'] for g in want] and got, 'nhóm không được nạp'
assert all(not g.get('devices') for g in want), 'dữ liệu mặc định còn tên máy'
print('  nhóm: %d, kịch bản: %d' % (len(got), sum(len(g.get('scripts') or []) for g in got)))"
else
  echo "  (bản dựng này không kèm dữ liệu mặc định)"
fi

step "bộ test bắt buộc"
for t in test_portable test_wallets test_mcp test_webdev; do
  out="$("$PY" "app/tests/$t.py" 2>&1)"; rc=$?
  echo "  $t rc=$rc :: $(printf '%s\n' "$out" | tail -1)"
  [ $rc -eq 0 ] || { printf '%s\n' "$out" | grep -E '✗|Error|Traceback' | head -20; bad=$((bad + 1)); }
done

step "bộ test còn lại (chỉ báo cáo)"
for t in test_history test_groups test_screencheck test_board test_notify test_ocr test_aiscreen test_nav; do
  out="$("$PY" "app/tests/$t.py" 2>&1)"; rc=$?
  echo "  $t rc=$rc :: $(printf '%s\n' "$out" | tail -1)"
  [ $rc -eq 0 ] || printf '%s\n' "$out" | grep -E '✗|Error|Traceback' | head -8 | sed 's/^/      /'
done

echo
if [ $bad -eq 0 ]; then echo "✅ bản cài $PLATFORM dùng được"; else echo "❌ $bad mục bắt buộc không đạt"; fi
exit $((bad > 0))
