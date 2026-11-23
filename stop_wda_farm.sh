#!/usr/bin/env bash
# Dừng toàn bộ WDA và iproxy do start_wda_farm.sh khởi chạy (theo file pid trong run/).
# Chạy: ./stop_wda_farm.sh
set -u
cd "$(dirname "$0")"

n=0
for pidfile in run/*.pid; do
  [ -f "$pidfile" ] || continue
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null && n=$((n+1))
  fi
  rm -f "$pidfile"
done

# Dọn tiến trình mồ côi của chính farm này (mất file pid)
pkill -f "pymobiledevice3 developer dvt xcuitest" 2>/dev/null && n=$((n+1))
pkill -f "iproxy -u " 2>/dev/null && n=$((n+1))

echo "Đã dừng $n tiến trình."
