#!/usr/bin/env python3
"""
Kiểm firmware ESP32 KHÔNG cần board: biên dịch thật bằng arduino-cli (cùng lệnh app dùng khi «Nạp») + soi mã nguồn.

    ./.venv/bin/python app/tests/test_firmware.py

Bắt các lỗi như: dùng hàm không có trong core esp32 2.0.17, thiếu lệnh trong giao thức, bỏ mất chốt an toàn
(giới hạn dòng, watchdog, reset). Thiếu arduino-cli / core esp32 thì phần biên dịch được BỎ QUA (nói rõ), phần soi mã vẫn chạy.
Thử trên board thật: app/tests/smoke_board.py.
"""
from __future__ import annotations
import os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import esp

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def main():
    src = open(os.path.join(esp.FW_DIR, "esp32_hid.ino"), encoding="utf-8").read()

    print("== 1. Soi mã nguồn firmware ==")
    cmds = set(re.findall(r'line == "([a-z]+)"', src)) | set(re.findall(r'cmd == "([a-z]+)"', src))
    want = {"ping", "whoami", "status", "info", "reset", "home", "type", "key", "combo", "move", "click", "rclick", "down", "up"}
    ok(want <= cmds, "đủ lệnh giao thức: " + " ".join(sorted(want)), sorted(want - cmds))
    doc = src.split("#include")[0]
    ok(all(c in doc for c in ("status", "info", "reset")), "đầu tệp ghi rõ các lệnh sức khoẻ (status / info / reset)")
    ok("String buf" not in src and "lineBuf[MAX_LINE" in src and "ERR line-too-long" in src,
       "dòng lệnh đọc vào bộ đệm CỐ ĐỊNH, quá MAX_LINE → ERR (không nối String vô hạn)")
    ok("setRxBufferSize" in src and src.index("setRxBufferSize") < src.index("Serial.begin"), "bộ đệm nhận serial được nới TRƯỚC khi mở cổng")
    ok("enableLoopWDT" in src and src.count("feedLoopWDT") >= 3, "watchdog bật + được «cho ăn» trong loop và trong các vòng gõ / di chuột chạy lâu")
    ok("esp_reset_reason" in src and "brownout" in src, "báo lý do reset lần trước (brownout / task_wdt / panic…)")
    ok(src.index('line == "reset"') < src.index("if (!hid.isConnected())"), "lệnh reset chạy được cả khi BLE chưa nối")
    ok(re.search(r'#define DEVICE_NAME "[^"]*"', src) is not None, "còn dòng #define DEVICE_NAME (app thay tên mỗi board lúc nạp)")
    ok(re.search(r"^status\b.*OK ble=", src, re.M) is None and 'String s = "OK ble=";' in src, "status vẫn mở đầu bằng «OK ble=» (app đang dò theo tiền tố này)")

    print("\n== 2. Biên dịch thật (arduino-cli, core esp32 2.0.17) ==")
    cli = shutil.which("arduino-cli")
    core = os.path.join(esp.ARDUINO_DATA, "packages", "esp32")
    if not cli or not os.path.isdir(core):
        print("  (bỏ qua: không có arduino-cli hoặc chưa cài core esp32 trong .arduino)")
    else:
        sketch, tmp = esp._make_named_sketch("iPhoneFarm-test")
        try:
            r = subprocess.run([cli, "compile", "--fqbn", esp.FQBN, "--config-file", esp.ARDUINO_CFG, sketch],
                               capture_output=True, text=True, env=esp._env(), timeout=900)
            tail = (r.stderr or r.stdout)[-700:]
            ok(r.returncode == 0, "biên dịch thành công", tail)
            m = re.search(r"Sketch uses (\d+) bytes \((\d+)%\)", r.stdout)
            m2 = re.search(r"Global variables use (\d+) bytes \((\d+)%\)", r.stdout)
            if m and m2:
                print("    (flash %s%%, RAM tĩnh %s%%)" % (m.group(2), m2.group(2)))
                ok(int(m.group(2)) < 90 and int(m2.group(2)) < 60, "còn chỗ: flash < 90%, RAM tĩnh < 60% (BLE cần nhiều RAM lúc chạy)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
