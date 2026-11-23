#!/usr/bin/env bash
# Quét iPhone đang cắm USB, kiểm tra Trust / Developer Mode / DDI, ghi danh sách máy sẵn sàng ra devices.txt.
# Chạy: ./scan_devices.sh
set -u
cd "$(dirname "$0")"
export PYTHONWARNINGS=ignore
PMD=./.venv/bin/pymobiledevice3
OUT=devices.txt

command -v idevice_id >/dev/null || { echo "Thiếu libimobiledevice: brew install libimobiledevice"; exit 1; }
[ -x "$PMD" ] || { echo "Thiếu pymobiledevice3: python3 -m venv .venv && .venv/bin/pip install pymobiledevice3"; exit 1; }

udids=$(idevice_id -l 2>/dev/null | sort -u)
if [ -z "$udids" ]; then
  echo "Không thấy iPhone nào qua USB."
  exit 1
fi

{
  echo "# Sinh bởi scan_devices.sh lúc $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# UDID<TAB>Tên máy<TAB>iOS. Thứ tự dòng = thứ tự gán port (dòng 1 -> 8101/9101)."
} > "$OUT"

ready=0; problems=0
printf "%-42s %-22s %-8s %-6s %-6s %s\n" "UDID" "TÊN" "iOS" "TRUST" "DEV" "DDI"
for udid in $udids; do
  # Chưa Trust (chưa pair) thì lockdown không trả thông tin
  if ! ver=$(ideviceinfo -u "$udid" -k ProductVersion 2>/dev/null) || [ -z "$ver" ]; then
    printf "%-42s %-22s %-8s %-6s %-6s %s\n" "$udid" "?" "?" "CHƯA" "?" "?"
    echo "#CHUA_TRUST	$udid" >> "$OUT"
    problems=$((problems+1)); continue
  fi
  name=$(ideviceinfo -u "$udid" -k DeviceName 2>/dev/null)
  dev=$("$PMD" amfi developer-mode-status --udid "$udid" 2>/dev/null | tail -1)
  if [ "$dev" != "true" ]; then
    printf "%-42s %-22s %-8s %-6s %-6s %s\n" "$udid" "$name" "$ver" "OK" "TẮT" "-"
    echo "#CHUA_BAT_DEVMODE	$udid	$name	$ver" >> "$OUT"
    problems=$((problems+1)); continue
  fi
  if "$PMD" mounter list --udid "$udid" 2>/dev/null | grep -q DiskImage; then ddi="đã mount"; else ddi="chưa (start sẽ tự mount)"; fi
  printf "%-42s %-22s %-8s %-6s %-6s %s\n" "$udid" "$name" "$ver" "OK" "BẬT" "$ddi"
  printf "%s\t%s\t%s\n" "$udid" "$name" "$ver" >> "$OUT"
  ready=$((ready+1))
done

echo
echo "Sẵn sàng: $ready máy  |  Cần thao tác tay: $problems máy  →  đã ghi $OUT"
if [ "$problems" -gt 0 ]; then
  echo
  echo "Máy cần làm tay trên iPhone:"
  grep -E '^#CHUA_TRUST' "$OUT" | cut -f2 | sed 's/^/  [Chưa Trust]  mở khoá iPhone, rút cắm lại cáp, bấm "Tin cậy": /'
  grep -E '^#CHUA_BAT_DEVMODE' "$OUT" | cut -f2,3 | sed 's/^/  [Chưa bật Developer Mode]  /'
  echo "  (Developer Mode bị ẩn thì chạy: $PMD amfi reveal-developer-mode --udid <UDID>)"
fi
