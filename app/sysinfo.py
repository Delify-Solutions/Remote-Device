#!/usr/bin/env python3
"""
sysinfo.py — Thông tin hệ thống + kiểm tra/cài thư viện & công cụ cho app.

Dùng cho trang "Tổng quan": phát hiện OS (Mac/Linux/Win), kiểm tra Python,
các gói pip cần thiết, và công cụ ngoài (arduino-cli / tesseract / iproxy);
kèm hành động cài đặt (pip install, hoặc brew/apt tuỳ OS).
"""
from __future__ import annotations
import importlib.util, importlib.metadata as md
import platform, shutil, subprocess, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VENV_PY = sys.executable

# (import_name, pip_name, mô tả)
PACKAGES = [
    ("pymobiledevice3", "pymobiledevice3", "Chụp màn hình + đọc thông tin iPhone"),
    ("serial",          "pyserial",        "Điều khiển board ESP32 qua cổng serial"),
    ("cv2",             "opencv-python-headless",   "Nhận diện nút/con trỏ trên ảnh"),
    ("numpy",           "numpy",           "Xử lý ảnh"),
    ("PIL",             "pillow",          "Đọc/ghi ảnh"),
    ("pytesseract",     "pytesseract",     "OCR dự phòng (cần cả tesseract) — tuỳ chọn"),
    ("webview",         "pywebview",       "Giao diện app desktop (cửa sổ native)"),
    ("esptool",         "esptool",         "Nạp/xoá firmware ESP32"),
]
# Bộ đọc chữ: macOS dùng Apple Vision CÓ SẴN; Windows / Linux cần RapidOCR (xem ocr.py) — trên macOS không bắt buộc nên không liệt kê.
if platform.system() != "Darwin":
    PACKAGES.append(("rapidocr", "rapidocr", "Đọc chữ trên màn hình (Windows / Linux — macOS dùng Apple Vision có sẵn)"))
    PACKAGES.append(("onnxruntime", "onnxruntime", "Chạy mô hình đọc chữ của RapidOCR (rapidocr KHÔNG tự cài gói này)"))

# (tên lệnh, mô tả, {os: câu lệnh cài})
TOOLS = [
    ("arduino-cli", "Biên dịch + nạp firmware ESP32", {
        "Darwin":  "brew install arduino-cli",
        "Linux":   "curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh",
        "Windows": "winget install ArduinoSA.CLI",
    }),
    ("tesseract", "Bộ đọc chữ dự phòng (tuỳ chọn — chính là Apple Vision / RapidOCR)", {
        "Darwin":  "brew install tesseract tesseract-lang",
        "Linux":   "sudo apt install -y tesseract-ocr tesseract-ocr-vie",
        "Windows": "winget install UB-Mannheim.TesseractOCR",
    }),
    ("iproxy", "Chuyển cổng USB iPhone (tuỳ chọn)", {
        "Darwin":  "brew install libimobiledevice",
        "Linux":   "sudo apt install -y libimobiledevice-utils",
        "Windows": "Cài ứng dụng «Apple Devices» (Microsoft Store) hoặc iTunes — driver USB cho iPhone",
    }),
]

OS_NAME = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}


def system_info():
    sysname = platform.system()
    v = sys.version_info
    return {
        "os": OS_NAME.get(sysname, sysname),
        "os_raw": sysname,
        "os_version": platform.release(),
        "arch": platform.machine(),
        "python": f"{v.major}.{v.minor}.{v.micro}",
        "python_ok": v >= (3, 9),
        "venv": os.path.dirname(os.path.dirname(VENV_PY)),
        "has_brew": shutil.which("brew") is not None,
        "has_apt": shutil.which("apt") is not None or shutil.which("apt-get") is not None,
        "has_winget": shutil.which("winget") is not None,
        "ocr": _ocr_engine(),
    }


def _ocr_engine() -> str:
    """Bộ đọc chữ app đang dùng (Apple Vision / RapidOCR / không có — kèm lý do)."""
    try:
        import ocr
        return ocr.engine_name() if ocr.available() else "không có — " + ocr.why_unavailable()
    except Exception as e:
        return "lỗi: %s" % e


def _pkg_version(pip_name):
    try: return md.version(pip_name)
    except Exception: return None


def check_packages():
    out = []
    for imp, pip_name, desc in PACKAGES:
        ok = importlib.util.find_spec(imp) is not None
        out.append({"name": pip_name, "import": imp, "desc": desc,
                    "ok": ok, "version": _pkg_version(pip_name) if ok else None})
    return out


def check_tools():
    sysname = platform.system()
    out = []
    for name, desc, cmds in TOOLS:
        path = shutil.which(name)
        out.append({"name": name, "desc": desc, "ok": path is not None,
                    "path": path, "cmd": cmds.get(sysname, "")})
    return out


def overview():
    pkgs = check_packages()
    tools = check_tools()
    return {
        "system": system_info(),
        "packages": pkgs,
        "tools": tools,
        "pkgs_ok": sum(1 for p in pkgs if p["ok"]),
        "pkgs_total": len(pkgs),
        "tools_ok": sum(1 for t in tools if t["ok"]),
        "tools_total": len(tools),
    }


# ------------------------- CÀI ĐẶT -------------------------
def _run(cmd_list, timeout=600):
    try:
        p = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + "\n" + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "Hết thời gian chờ."
    except Exception as e:
        return 1, str(e)


def pip_install(names):
    """Cài 1 hoặc nhiều gói pip vào venv. names = list hoặc 'all' (cài hết gói thiếu)."""
    if names == "all" or not names:
        names = [p["name"] for p in check_packages() if not p["ok"]]
    if isinstance(names, str):
        names = [names]
    if not names:
        return {"ok": True, "log": "Không có gói nào thiếu."}
    # Chỉ cài các gói app CẦN (danh sách PACKAGES): tên khác — kể cả tuỳ chọn của pip như «--index-url …» hay địa chỉ git — bị từ chối,
    # vì `pip install <thứ bất kỳ>` là chạy mã bất kỳ trên máy này.
    known = {p[1] for p in PACKAGES}
    bad = [n for n in names if not isinstance(n, str) or n not in known]
    if bad:
        return {"ok": False, "log": "Chỉ cài được các gói app cần: %s. Bị từ chối: %s" % (", ".join(sorted(known)), ", ".join(map(str, bad)))}
    rc, log = _run([VENV_PY, "-m", "pip", "install", "--upgrade", *names], timeout=900)
    return {"ok": rc == 0, "log": log[-4000:]}


def tool_install(name):
    """Thử cài công cụ ngoài theo OS. Nếu không tự cài được -> trả câu lệnh để tự chạy."""
    sysname = platform.system()
    entry = next((t for t in TOOLS if t[0] == name), None)
    if not entry:
        return {"ok": False, "log": "Không rõ công cụ."}
    cmd = entry[2].get(sysname, "")
    # Tự cài được khi: macOS + brew, hoặc Linux + apt (apt cần sudo → thường phải tự chạy).
    if sysname == "Darwin" and shutil.which("brew"):
        parts = cmd.split()                       # brew install X [Y]
        rc, log = _run(parts, timeout=900)
        return {"ok": rc == 0, "log": log[-4000:], "cmd": cmd}
    if sysname == "Windows" and shutil.which("winget") and cmd.startswith("winget"):
        rc, log = _run(cmd.split(), timeout=900)
        return {"ok": rc == 0, "log": log[-4000:], "cmd": cmd}
    # còn lại: cần chạy tay (apt cần sudo, hoặc chưa có brew/winget)
    return {"ok": False, "manual": True, "cmd": cmd,
            "log": "Không tự cài được từ app (thường do cần quyền sudo hoặc chưa có trình quản lý gói).\n"
                   "Hãy mở Terminal và chạy lệnh:\n  " + cmd}
