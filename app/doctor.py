#!/usr/bin/env python3
"""
Doctor — kiểm tra môi trường cho iPhone-farm (chạy cả Windows & macOS).

Chạy:
    python app/doctor.py          # chỉ kiểm tra, báo thiếu gì
    python app/doctor.py --fix    # tự cài các gói Python còn thiếu (pip)

Kiểm tra: OS/Python, các gói Python cần thiết, driver USB-serial,
iPhone đang cắm, và board ESP32 (CP2102/CH340/CH9102) đang cắm.
"""
from __future__ import annotations
import importlib.util
import platform
import shutil
import subprocess
import sys

# ----- màu cho terminal (tự tắt nếu không hỗ trợ) -----
_C = sys.stdout.isatty()
def ok(s):   return (f"\033[32m{s}\033[0m" if _C else s)
def bad(s):  return (f"\033[31m{s}\033[0m" if _C else s)
def warn(s): return (f"\033[33m{s}\033[0m" if _C else s)
def head(s): return (f"\033[1m{s}\033[0m" if _C else s)

OKV, MISS, WARNV = ok("[ OK ]"), bad("[THIẾU]"), warn("[ ! ]")

# gói Python cần: (tên import, tên pip, mô tả)
REQUIRED = [
    ("pymobiledevice3", "pymobiledevice3", "chụp màn hình + đọc AX của iPhone"),
    ("serial",          "pyserial",        "điều khiển board ESP32 qua cổng serial"),
    ("cv2",             "opencv-python",   "nhận diện nút trên ảnh (template match)"),
    ("numpy",           "numpy",           "xử lý ảnh"),
    ("PIL",             "pillow",          "đọc/ghi ảnh"),
    ("pytesseract",     "pytesseract",     "OCR đọc chữ trên màn (cần cả brew tesseract + tesseract-lang)"),
    ("webview",         "pywebview",       "giao diện app desktop (cửa sổ native)"),
    ("esptool",         "esptool",         "nạp/xoá firmware ESP32"),
]

# VID:PID của các chip USB-serial hay gặp trên board ESP32
KNOWN_UART = {
    (0x10C4, 0xEA60): "CP2102 (Silicon Labs) — khuyên dùng (có serial riêng)",
    (0x1A86, 0x7523): "CH340 — ok, cần driver trên Mac, thường không có serial riêng",
    (0x1A86, 0x55D4): "CH9102 (CH343) — ok, có serial riêng",
    (0x0403, 0x6001): "FTDI FT232",
}


def check_python():
    print(head("\n1) Hệ điều hành & Python"))
    print(f"   OS      : {platform.system()} {platform.release()} ({platform.machine()})")
    v = sys.version_info
    status = OKV if v >= (3, 9) else MISS
    print(f"   {status} Python {v.major}.{v.minor}.{v.micro}  (cần >= 3.9)")
    return v >= (3, 9)


def check_packages(fix: bool):
    print(head("\n2) Thư viện Python"))
    missing = []
    for imp, pip_name, desc in REQUIRED:
        if importlib.util.find_spec(imp) is not None:
            print(f"   {OKV} {pip_name:<16} — {desc}")
        else:
            print(f"   {MISS} {pip_name:<16} — {desc}")
            missing.append(pip_name)
    if missing and fix:
        print(warn(f"\n   → Đang cài: {' '.join(missing)}"))
        subprocess.run([sys.executable, "-m", "pip", "install", *missing])
        print(warn("   → Cài xong. Chạy lại doctor để kiểm tra."))
    elif missing:
        print(warn(f"\n   → Cài bằng: {sys.executable} -m pip install {' '.join(missing)}"))
        print(warn("     (hoặc chạy: python app/doctor.py --fix)"))
    return not missing


def check_serial_boards():
    print(head("\n3) Board ESP32 (cổng USB-serial)"))
    try:
        from serial.tools import list_ports
    except ImportError:
        print(f"   {WARNV} chưa có pyserial — không quét được (cài ở bước 2)")
        return False
    ports = list(list_ports.comports())
    found = 0
    for p in ports:
        vid, pid = p.vid, p.pid
        label = KNOWN_UART.get((vid, pid)) if vid is not None else None
        if label:
            found += 1
            sn = getattr(p, "serial_number", None) or "(không có serial#)"
            print(f"   {OKV} {p.device}  — {label}")
            print(f"        serial#: {sn}")
    if not found:
        print(f"   {WARNV} chưa thấy board ESP32 nào cắm vào (bình thường nếu chưa mua/chưa cắm)")
    return found > 0


def check_iphones():
    print(head("\n4) iPhone đang cắm"))
    try:
        from pymobiledevice3.usbmux import list_devices
    except Exception:
        print(f"   {WARNV} chưa có pymobiledevice3 — bỏ qua (cài ở bước 2)")
        return False
    try:
        devs = list_devices()
        if hasattr(devs, "__await__"):
            import asyncio
            devs = asyncio.run(devs)
    except Exception as e:
        print(f"   {WARNV} không đọc được usbmux: {e}")
        if platform.system() == "Windows":
            print(warn("        → Windows cần cài 'Apple Mobile Device Support' (đi kèm iTunes)."))
        return False
    if not devs:
        print(f"   {WARNV} không thấy iPhone nào (cắm máy + bấm Tin cậy)")
        return False
    for d in devs:
        print(f"   {OKV} {getattr(d, 'serial', d)}  (conn: {getattr(d, 'connection_type', '?')})")
    return True


def check_external_tools():
    print(head("\n5) Công cụ hệ thống (ngoài pip)"))
    import shutil
    tools = [
        ("arduino-cli", "biên dịch + nạp firmware ESP32 (brew install arduino-cli)"),
        ("tesseract",   "máy OCR (brew install tesseract tesseract-lang)"),
        ("iproxy",      "chuyển cổng USB (brew install libimobiledevice) — tuỳ chọn"),
    ]
    for name, desc in tools:
        path = shutil.which(name)
        print(f"   {OKV if path else WARNV} {name:<12} — {desc}")


def check_platform_drivers():
    print(head("\n6) Driver hệ thống"))
    sysname = platform.system()
    if sysname == "Darwin":
        print(f"   {OKV} macOS: usbmux có sẵn trong hệ thống.")
        print(f"   {WARNV} CP2102/CH340: macOS mới thường tự nhận; nếu không thấy cổng, cài driver của hãng.")
    elif sysname == "Windows":
        print(f"   {WARNV} Windows cần: 'Apple Mobile Device Support' (iTunes) để chụp màn iPhone.")
        print(f"   {WARNV} Driver CP2102/CH340: thường Windows tự nhận; nếu không, cài VCP driver.")
    else:
        print(f"   {WARNV} {sysname}: chưa kiểm tra riêng.")


def main():
    fix = "--fix" in sys.argv
    print(head("=== DOCTOR — kiểm tra môi trường iPhone-farm ==="))
    results = {
        "python":  check_python(),
        "packages": check_packages(fix),
        "boards":  check_serial_boards(),
        "iphones": check_iphones(),
    }
    check_external_tools()
    check_platform_drivers()

    print(head("\n=== TÓM TẮT ==="))
    print(f"   Python      : {OKV if results['python'] else MISS}")
    print(f"   Thư viện    : {OKV if results['packages'] else MISS}")
    print(f"   iPhone cắm  : {OKV if results['iphones'] else WARNV}")
    print(f"   Board ESP32 : {OKV if results['boards'] else WARNV}")
    if not results["packages"]:
        print(warn("\n   Thiếu thư viện → chạy: python app/doctor.py --fix"))
    print()


if __name__ == "__main__":
    main()
