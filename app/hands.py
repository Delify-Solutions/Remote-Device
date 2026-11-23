#!/usr/bin/env python3
"""
hands.py — điều khiển ESP32 (bàn phím+chuột BLE) qua Serial từ máy tính.

Dùng như thư viện:
    from hands import Hands
    h = Hands()                 # tự tìm cổng ESP32 (CP2102/CH340/CH9102)
    h.type("hello"); h.key("enter"); h.move(50,0); h.click()

Chạy trực tiếp để test tay:
    python app/hands.py                 # tự tìm cổng, mở REPL
    python app/hands.py /dev/cu.usbserial-0001
Trong REPL gõ thẳng lệnh firmware: ping / status / type ... / key enter / move 50 0 / click
Gõ 'q' để thoát.
"""
from __future__ import annotations
import sys, time
import serial
from serial.tools import list_ports

UART_VIDPID = {(0x10C4, 0xEA60), (0x1A86, 0x7523), (0x1A86, 0x55D4), (0x0403, 0x6001)}


def find_port() -> str | None:
    for p in list_ports.comports():
        if p.vid is not None and (p.vid, p.pid) in UART_VIDPID:
            return p.device
    return None


class Hands:
    def __init__(self, port: str | None = None, baud: int = 115200, timeout: float = 2.0,
                 reset: bool = False):
        self.port = port or find_port()
        if not self.port:
            raise RuntimeError("Không tìm thấy cổng ESP32 (CP2102/CH340). Cắm board + chạy doctor.")
        # Mở cổng KHÔNG reset board (giữ phiên BLE): đặt DTR/RTS=False TRƯỚC khi open.
        self.ser = serial.Serial()
        self.ser.port = self.port
        self.ser.baudrate = baud
        self.ser.timeout = timeout
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        if reset:
            # chủ động reset nếu cần (EN qua RTS)
            self.ser.rts = True; time.sleep(0.1); self.ser.rts = False
            time.sleep(1.8)
        else:
            time.sleep(0.3)
        self._drain()

    def _drain(self):
        """Đọc bỏ hết rác khởi động (boot log) cho tới khi im."""
        self.ser.timeout = 0.3
        for _ in range(50):
            if not self.ser.readline():
                break
        self.ser.timeout = 2.0
        self.ser.reset_input_buffer()

    def send(self, cmd: str) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd.strip() + "\n").encode("utf-8", "ignore"))
        self.ser.flush()
        time.sleep(0.2)                 # chờ ESP32 trả lời
        # đọc hết dòng đang chờ, lấy dòng không rỗng CUỐI (reply mới nhất)
        last = ""
        self.ser.timeout = 0.3
        for _ in range(20):
            raw = self.ser.readline()
            if not raw:
                break
            s = raw.decode("utf-8", "ignore").strip()
            if s:
                last = s
        self.ser.timeout = 2.0
        return last

    def wait_connected(self, timeout: float = 15.0) -> bool:
        """Chờ tới khi iPhone kết nối HID ổn định."""
        end = time.time() + timeout
        while time.time() < end:
            if "ble=connected" in self.status():
                return True
            time.sleep(1)
        return False

    def do(self, cmd: str, retries: int = 3) -> str:
        """Gửi lệnh, tự chờ kết nối + thử lại nếu rớt."""
        for _ in range(retries):
            r = self.send(cmd)
            if r.startswith("OK") or r == "pong":
                return r
            if "not-connected" in r or r == "":
                self.wait_connected(8)
                time.sleep(0.2)
                continue
            return r
        return r

    # tiện ích
    def ping(self):   return self.send("ping")
    def status(self): return self.send("status")
    def type(self, text: str): return self.do("type " + text)
    def key(self, name: str):  return self.do("key " + name)
    def move(self, dx: int, dy: int): return self.do(f"move {dx} {dy}")
    def click(self):  return self.do("click")
    def down(self):   return self.do("down")
    def up(self):     return self.do("up")

    def close(self):
        try: self.ser.close()
        except Exception: pass


def repl(port: str | None):
    try:
        h = Hands(port)
    except Exception as e:
        print("Lỗi:", e); return
    print(f"Đã nối {h.port}. Gõ lệnh firmware (q để thoát).")
    print("Thử:  status  |  type xin chao  |  key enter  |  move 50 0  |  click")
    # đọc dòng BOOT nếu có
    try:
        h.ser.timeout = 0.5
        boot = h.ser.readline().decode("utf-8", "ignore").strip()
        if boot: print("  <", boot)
        h.ser.timeout = 2.0
    except Exception:
        pass
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("q", "quit", "exit"): break
        if not cmd: continue
        print("  <", h.send(cmd))
    h.close()
    print("Thoát.")


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else None
    repl(port)
