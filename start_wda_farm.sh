#!/usr/bin/env bash
# Khởi chạy WebDriverAgent trên tất cả iPhone trong devices.txt.
#   - máy thứ i: http://127.0.0.1:<WDA_BASE_PORT+i> (WDA), <MJPEG_BASE_PORT+i> (stream màn hình)
#   - log: logs/wda_<UDID>.log, logs/iproxy_<UDID>.log
#   - bảng port: run/ports.tsv
# Chạy: ./scan_devices.sh && ./start_wda_farm.sh
#
# Lưu ý: dùng `pymobiledevice3 developer dvt xcuitest` thay cho `xcodebuild test-without-building`,
# vì với Xcode 26.6 + iOS 16, xcodebuild báo "Logic Testing Unavailable" (đã thử, xem SETUP.md).
set -u
cd "$(dirname "$0")"
export PYTHONWARNINGS=ignore
source ./farm.conf
PMD=./.venv/bin/pymobiledevice3
mkdir -p logs run

[ -f devices.txt ] || { echo "Chưa có devices.txt, chạy ./scan_devices.sh trước."; exit 1; }
command -v iproxy >/dev/null || { echo "Thiếu iproxy: brew install libimobiledevice"; exit 1; }

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

: > run/ports.tsv
i=0
while IFS=$'\t' read -r udid name ver <&3; do
  case "$udid" in ''|\#*) continue ;; esac
  i=$((i+1))
  wport=$((WDA_BASE_PORT+i)); mport=$((MJPEG_BASE_PORT+i))
  log="logs/wda_$udid.log"
  alive "run/$udid.wda.pid" || : > "$log"   # log mới cho mỗi lần khởi chạy, tránh đọc nhầm lỗi cũ
  printf "%s\t%s\t%s\t%s\n" "$udid" "$name" "$wport" "$mport" >> run/ports.tsv
  echo "[$i] $name ($udid) → WDA :$wport  MJPEG :$mport"

  # 1. Developer Disk Image (mất sau mỗi lần iPhone khởi động lại)
  "$PMD" mounter auto-mount --udid "$udid" >> "$log" 2>&1 || echo "    ! mount DDI lỗi, xem $log"

  # 2. Cài WDA nếu máy chưa có
  if ! "$PMD" apps list --udid "$udid" 2>/dev/null | grep -q "\"$WDA_BUNDLE_ID\""; then
    echo "    cài WDA…"
    "$PMD" apps install --udid "$udid" "$WDA_APP" >> "$log" 2>&1 || { echo "    ! cài WDA lỗi, xem $log"; continue; }
  fi

  # 3. iproxy: port Mac -> port trong iPhone
  if alive "run/$udid.iproxy.pid"; then
    echo "    iproxy đang chạy"
  else
    nohup iproxy -u "$udid" "$wport:$DEVICE_WDA_PORT" "$mport:$DEVICE_MJPEG_PORT" > "logs/iproxy_$udid.log" 2>&1 &
    echo $! > "run/$udid.iproxy.pid"
  fi

  # 4. Khởi chạy WDA
  if alive "run/$udid.wda.pid"; then
    echo "    WDA đang chạy"
  else
    nohup "$PMD" developer dvt xcuitest "$WDA_BUNDLE_ID" --udid "$udid" \
      --env "USE_PORT=$DEVICE_WDA_PORT" --env "MJPEG_SERVER_PORT=$DEVICE_MJPEG_PORT" >> "$log" 2>&1 &
    echo $! > "run/$udid.wda.pid"
  fi
done 3< devices.txt

[ "$i" -eq 0 ] && { echo "devices.txt không có máy nào sẵn sàng."; exit 1; }

# 5. Health-check song song cho tất cả máy
echo
echo "Chờ WDA trả lời /status (tối đa ${HEALTH_TIMEOUT}s)…"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
ok=0; fail=0
while IFS=$'\t' read -r udid name wport mport <&3; do
  log="logs/wda_$udid.log"; status=""
  while :; do
    if curl -s -m 2 "http://127.0.0.1:$wport/status" | grep -q '"ready" *: *true'; then status="OK"; break; fi
    if ! alive "run/$udid.wda.pid"; then
      if grep -q "Failed to launch" "$log"; then
        status="LỖI: iPhone chặn chạy WDA (chữ ký / xác minh nhà phát triển)"
      else
        status="LỖI: WDA thoát, xem $log"
      fi
      break
    fi
    [ "$(date +%s)" -ge "$deadline" ] && { status="LỖI: hết giờ chờ, xem $log"; break; }
    sleep 1
  done
  if [ "$status" = "OK" ]; then ok=$((ok+1)); else fail=$((fail+1)); fi
  printf "  %-22s :%-5s %s\n" "$name" "$wport" "$status"
done 3< run/ports.tsv

echo
echo "WDA sẵn sàng: $ok  |  lỗi: $fail"
[ "$fail" -eq 0 ]
