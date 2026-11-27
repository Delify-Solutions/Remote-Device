#!/usr/bin/env python3
"""
fleet.py — quản & điều khiển NHIỀU iPhone song song.

- Tự quét các cổng serial, hỏi `whoami` -> map {tên board: cổng}.
- DEVICES: khai báo board nào (tên BLE) điều khiển iPhone nào (udid).
- Mỗi máy = 1 Nav(cổng, udid). Chạy song song bằng thread.

    python app/fleet.py discover     # xem board + cổng
    python app/fleet.py type HELLO   # gõ lên TẤT CẢ máy cùng lúc
    python app/fleet.py shot         # chụp tất cả -> shots/fleet_<udid>.png
"""
from __future__ import annotations
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from serial.tools import list_ports
from hands import Hands, UART_VIDPID
from nav import Nav

# Khai báo đội máy: tên board (BLE) <-> UDID iPhone nó điều khiển.
DEVICES = [
    {"name": "iPhoneFarm-01", "udid": "babfe8c8261743b1eb722aa5b0c8b599e58b8c9c"},
    {"name": "iPhoneFarm-02", "udid": "68b6f24f432ffa7c5beac3de43e0a79b4a792dd6"},
]


def list_esp_ports():
    return [p.device for p in list_ports.comports()
            if p.vid is not None and (p.vid, p.pid) in UART_VIDPID]


def discover():
    """Trả {tên board: cổng} bằng cách hỏi whoami từng cổng."""
    mapping = {}
    for port in list_esp_ports():
        try:
            h = Hands(port, reset=False)
            name = ""
            for _ in range(6):
                r = h.send("whoami")
                if r.startswith("NAME "):
                    name = r[5:].strip(); break
                time.sleep(0.3)
            h.close()
            if name:
                mapping[name] = port
        except Exception as e:
            print(f"  ! {port}: {e}")
    return mapping


def build_navs():
    """Tạo Nav cho mỗi máy trong DEVICES (bỏ qua máy không tìm thấy board)."""
    m = discover()
    navs = []
    for d in DEVICES:
        port = m.get(d["name"])
        if not port:
            print(f"  ! bỏ qua {d['name']}: không thấy board"); continue
        navs.append((d, Nav(port, d["udid"])))
    return navs


def _run_parallel(navs, fn):
    """Chạy fn(d, nav) song song trên tất cả máy."""
    threads = []
    results = {}
    def worker(d, nav):
        try:
            results[d["name"]] = fn(d, nav)
        except Exception as e:
            results[d["name"]] = f"ERR {e}"
    for d, nav in navs:
        t = threading.Thread(target=worker, args=(d, nav)); t.start(); threads.append(t)
    for t in threads: t.join()
    return results


def cmd_discover():
    m = discover()
    print("Board tìm thấy:")
    for name, port in m.items():
        print(f"  {name:<16} {port}")
    print("\nĐội máy (DEVICES):")
    for d in DEVICES:
        print(f"  {d['name']:<16} -> iPhone {d['udid'][:12]}  [{'OK' if d['name'] in m else 'THIẾU BOARD'}]")


def cmd_type(text):
    navs = build_navs()
    def do(d, nav):
        nav.h.wait_connected(15)
        return nav.h.type(text)
    res = _run_parallel(navs, do)
    for name, r in res.items(): print(f"  {name}: {r}")
    for _, nav in navs: nav.close()


def cmd_shot():
    navs = build_navs()
    def do(d, nav):
        return nav.shot(f"shots/fleet_{d['udid'][:12]}.png")
    res = _run_parallel(navs, do)
    for name, r in res.items(): print(f"  {name}: {r}")
    for _, nav in navs: nav.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "discover"
    if cmd == "discover": cmd_discover()
    elif cmd == "type":   cmd_type(" ".join(sys.argv[2:]) or "HELLO")
    elif cmd == "shot":   cmd_shot()
    else: print("Lệnh: discover | type <text> | shot")
