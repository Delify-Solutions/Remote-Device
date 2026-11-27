#!/usr/bin/env python3
"""
esp.py — quản lý board ESP32: dò chip, kiểm tra đã nạp firmware chưa,
nạp (với tên tuỳ chọn), xoá sạch, đổi tên.

Dùng arduino-cli (đã cấu hình trong ./.arduino) + esptool (trong .venv).
"""
from __future__ import annotations
import os, re, shutil, subprocess, sys, time, tempfile
import serial
from serial.tools import list_ports

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quietserial import QuietSerial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # thư mục Remote-Device
import venvbin
VENV_PY = venvbin.python()                      # .venv/bin/python (macOS) hoặc .venv\\Scripts\\python.exe (Windows)
ARDUINO_DATA = os.path.join(ROOT, ".arduino")
ARDUINO_CFG = os.path.join(ARDUINO_DATA, "arduino-cli.yaml")
FW_DIR = os.path.join(ROOT, "app", "firmware", "esp32_hid")
FQBN = "esp32:esp32:esp32:PartitionScheme=huge_app"

UART_VIDPID = {
    (0x10C4, 0xEA60): "CP2102 (Silicon Labs)",
    (0x1A86, 0x7523): "CH340",
    (0x1A86, 0x55D4): "CH9102",
    (0x0403, 0x6001): "FTDI FT232",
}


def _arduino_cli():
    return shutil.which("arduino-cli") or "arduino-cli"


def list_boards():
    """Trả [{port, chip_desc, vid, pid, serial}] cho các cổng USB-UART."""
    out = []
    for p in list_ports.comports():
        if p.vid is not None and (p.vid, p.pid) in UART_VIDPID:
            out.append({
                "port": p.device,
                "chip_desc": UART_VIDPID[(p.vid, p.pid)],
                "vid": p.vid, "pid": p.pid,
                "serial": getattr(p, "serial_number", None),
            })
    return out


def probe(port, timeout=3.0):
    """Mở cổng KHÔNG reset, hỏi whoami. Trả {flashed, name}.
    Nếu đã nạp firmware của ta -> flashed True + name; nếu không -> flashed False."""
    try:
        ser = QuietSerial()                 # mở KHÔNG làm board reset (xem quietserial.py)
        ser.port = port; ser.baudrate = 115200; ser.timeout = 0.4
        ser.dtr = False; ser.rts = False
        if os.name == "posix":
            ser.exclusive = True      # cổng đang được điều khiển (app / farm / AI) thì KHÔNG chen lệnh dò vào
        ser.open()
        time.sleep(0.3)
        ser.reset_input_buffer()
        name = None
        for _ in range(8):
            ser.write(b"whoami\n"); ser.flush()
            time.sleep(0.2)
            line = ser.readline().decode("utf-8", "ignore").strip()
            if line.startswith("NAME "):
                name = line[5:].strip(); break
        ble = None
        if name:
            # Hỏi trạng thái Bluetooth nhiều lần rồi BỎ PHIẾU ĐA SỐ.
            # Vì firmware isConnected() lúc đầu còn lag + Serial có thể trả dòng
            # rỗng/cũ khi BLE đang bận → đọc 1 lần dễ trượt thành "?" hoặc sai.
            ser.reset_input_buffer()
            conn = disc = 0
            last_status = None
            for _ in range(8):
                ser.write(b"status\n"); ser.flush()
                time.sleep(0.15)
                got = None
                # vét hết các dòng đang có trong buffer, lấy dòng 'ble=' mới nhất
                for _2 in range(4):
                    line = ser.readline().decode("utf-8", "ignore").strip()
                    if not line:
                        break
                    if "ble=" in line:
                        got = line
                        last_status = line
                if got is not None:
                    # LƯU Ý: "disconnected" chứa chuỗi con "connected" → khớp đúng.
                    if "ble=connected" in got: conn += 1
                    else: disc += 1
            if conn or disc:
                ble = conn > disc
        ser.close()
        return {"flashed": name is not None, "name": name, "ble": ble, "status": last_status if name else None}
    except Exception as e:
        # cổng đang bị một chương trình khác giữ độc quyền (lệnh `farm` / máy chủ MCP chạy ngoài app):
        # KHÔNG phải «chưa nạp firmware» — chỉ là lúc này không hỏi được.
        locked = "lock" in str(e).lower() or "busy" in str(e).lower()
        return {"flashed": False, "name": None, "ble": None, "error": str(e), "busy": locked}


def chip_info(port):
    """esptool chip_id -> {chip, mac}. (Sẽ reset board.)"""
    try:
        r = subprocess.run([VENV_PY, "-m", "esptool", "--port", port, "chip_id"],
                           capture_output=True, text=True, timeout=40)
        txt = r.stdout + r.stderr
        chip = None; mac = None
        m = re.search(r"Chip is (.+)", txt)
        if m: chip = m.group(1).strip()
        m = re.search(r"MAC:\s*([0-9a-fA-F:]+)", txt)
        if m: mac = m.group(1).strip()
        return {"ok": chip is not None, "chip": chip, "mac": mac}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _env():
    return dict(os.environ, ARDUINO_DIRECTORIES_DATA=ARDUINO_DATA, PYTHONWARNINGS="ignore")


def _make_named_sketch(name):
    """Tạo bản sao firmware với DEVICE_NAME = name trong thư mục tạm. Trả đường sketch dir."""
    tmp = tempfile.mkdtemp(prefix="wda_fw_")
    dst = os.path.join(tmp, "esp32_hid")
    shutil.copytree(FW_DIR, dst)
    ino = os.path.join(dst, "esp32_hid.ino")
    with open(ino, "r", encoding="utf-8") as f:
        src = f.read()
    safe = re.sub(r'[^A-Za-z0-9_\-]', '', name) or "iPhoneFarm"
    src = re.sub(r'#define DEVICE_NAME "[^"]*"', f'#define DEVICE_NAME "{safe}"', src)
    with open(ino, "w", encoding="utf-8") as f:
        f.write(src)
    return dst, tmp


def flash(port, name, log=print):
    """Compile firmware (tên = name) rồi nạp vào port. Trả {ok, log}."""
    lines = []
    def out(s): lines.append(s); log(s)
    sketch, tmp = _make_named_sketch(name)
    try:
        out(f"Biên dịch firmware (tên: {name})…")
        r = subprocess.run(
            [_arduino_cli(), "compile", "--fqbn", FQBN, "--config-file", ARDUINO_CFG, sketch],
            capture_output=True, text=True, env=_env(), timeout=300)
        if r.returncode != 0:
            out("Lỗi biên dịch:\n" + (r.stderr or r.stdout)[-800:])
            return {"ok": False, "log": "\n".join(lines)}
        out("Nạp vào " + port + "…")
        r = subprocess.run(
            [_arduino_cli(), "upload", "-p", port, "--fqbn", FQBN,
             "--config-file", ARDUINO_CFG, sketch],
            capture_output=True, text=True, env=_env(), timeout=180)
        if r.returncode != 0:
            out("Lỗi nạp:\n" + (r.stderr or r.stdout)[-800:])
            return {"ok": False, "log": "\n".join(lines)}
        out("✓ Nạp xong. Chờ board khởi động…")
        time.sleep(2)
        p = probe(port)
        for _ in range(3):                           # board vừa nạp có lúc chưa kịp trả lời whoami (BLE đang khởi tạo) → hỏi lại, đừng báo lỗi oan
            if p["flashed"]:
                break
            time.sleep(2)
            p = probe(port)
        out(f"Kiểm tra: {'OK, tên=' + p['name'] if p['flashed'] else 'chưa thấy phản hồi'}")
        return {"ok": p["flashed"], "name": p.get("name"), "log": "\n".join(lines)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def erase(port, log=print):
    """Xoá sạch flash (esptool erase_flash)."""
    try:
        log("Xoá sạch flash " + port + "…")
        r = subprocess.run([VENV_PY, "-m", "esptool", "--port", port, "erase_flash"],
                           capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0
        return {"ok": ok, "log": (r.stdout + r.stderr)[-800:]}
    except Exception as e:
        return {"ok": False, "log": str(e)}


if __name__ == "__main__":
    for b in list_boards():
        p = probe(b["port"])
        print(b["port"], b["chip_desc"], "| flashed:", p["flashed"], "| name:", p.get("name"))
