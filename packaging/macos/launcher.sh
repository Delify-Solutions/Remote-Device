#!/bin/bash
# Trình mở iPhone Farm trên macOS (file chạy của «iPhone Farm.app»).
#
# Lần mở đầu, hoặc sau khi cài bản mới: chép mã app + Python kèm theo vào ~/Library/iPhoneFarm, tạo .venv ở đó rồi cài thư viện từ
# các wheel nằm sẵn trong app (không cần mạng). Những lần sau mở thẳng. Dữ liệu của người dùng (app/data: nhóm, kịch bản, ví, cài đặt)
# nằm trong ~/Library/iPhoneFarm và KHÔNG bị ghi đè khi cập nhật.
#
#   IPF_HOME=<thư mục>   cài vào chỗ khác (dùng khi thử)
#   IPF_SETUP_ONLY=1     chỉ cài, không mở cửa sổ app, không hiện hộp thoại

SRC="$(cd "$(dirname "$0")/../Resources/payload" 2>/dev/null && pwd)"
DST="${IPF_HOME:-$HOME/Library/iPhoneFarm}"
VER="$(cat "$SRC/VERSION" 2>/dev/null)"
LOG="$DST/install.log"

notify() {
  [ -n "$IPF_SETUP_ONLY" ] && return 0
  /usr/bin/osascript -e "display notification \"$1\" with title \"iPhone Farm\"" >/dev/null 2>&1
}

fail() {
  echo "✗ $1" >&2
  [ -n "$IPF_SETUP_ONLY" ] || /usr/bin/osascript -e "display alert \"iPhone Farm\" message \"$1\" as critical" >/dev/null 2>&1
  exit 1
}

setup() {
  echo "== iPhone Farm $VER → $DST ($(date))"
  # mã app: chép đè bản mới; GIỮ NGUYÊN app/data (dữ liệu người dùng). runtime / wheels / models xử lý riêng bên dưới.
  # farm.conf là tệp cấu hình người dùng có thể đã sửa → chỉ chép khi chưa có
  local keep_conf=""
  [ -f "$DST/farm.conf" ] && keep_conf="/farm.conf"
  /usr/bin/rsync -a --exclude '/runtime' --exclude '/wheels' --exclude '/models' --exclude '/app/data' ${keep_conf:+--exclude "$keep_conf"} "$SRC/" "$DST/" || return 1
  rm -rf "$DST/runtime" "$DST/.venv" "$DST/.ipf-installed" || return 1
  /usr/bin/rsync -a "$SRC/runtime/" "$DST/runtime/" || return 1
  # app tải từ mạng bị gắn nhãn «cách ly»; bản chép ra đây phải gỡ nhãn thì Python kèm theo mới chạy được
  /usr/bin/xattr -dr com.apple.quarantine "$DST/runtime" 2>/dev/null
  "$DST/runtime/bin/python3" -m venv "$DST/.venv" || return 1
  "$DST/.venv/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$SRC/wheels" \
      -r "$DST/requirements-windows.txt" -c "$DST/constraints.txt" || return 1
  local models
  models="$("$DST/.venv/bin/python" -c 'import os, rapidocr; print(os.path.join(os.path.dirname(rapidocr.__file__), "models"))')" || return 1
  mkdir -p "$models" || return 1
  cp "$SRC"/models/*.onnx "$models/" || return 1
  /usr/bin/xattr -dr com.apple.quarantine "$DST/.venv" 2>/dev/null
  "$DST/.venv/bin/python" -c 'import webview, serial, cv2, numpy, pymobiledevice3, cryptography, esptool' || return 1
  printf '%s\n' "$VER" > "$DST/.ipf-installed" || return 1
  echo "== xong"
}

[ -n "$SRC" ] && [ -n "$VER" ] || fail "Gói app bị thiếu tệp — tải lại bộ cài."

if [ ! -x "$DST/.venv/bin/python" ] || [ "$(cat "$DST/.ipf-installed" 2>/dev/null)" != "$VER" ]; then
  mkdir -p "$DST" || fail "Không tạo được thư mục $DST"
  notify "Đang cài đặt (1–3 phút) — cửa sổ app sẽ tự mở khi xong."
  setup > "$LOG" 2>&1 || fail "Cài đặt không thành công. Xem chi tiết trong tệp: $LOG"
fi

[ -n "$IPF_SETUP_ONLY" ] && exit 0
cd "$DST" || fail "Không vào được thư mục $DST"
exec ./.venv/bin/python app/gui.py
