#!/usr/bin/env python3
"""
Thử BẢN THÂN board ESP32 trên phần cứng thật (không cần iPhone; có iPhone thì thử thêm phần BLE):

    ./.venv/bin/python app/tests/smoke_board.py <tên board>             # vd iPhoneFarm-03
    ./.venv/bin/python app/tests/smoke_board.py iPhoneFarm-03 --no-reset  # bỏ phần reset (đang nối iPhone, không muốn rớt BLE)
    ./.venv/bin/python app/tests/smoke_board.py iPhoneFarm-03 --stress 2000

TẮT app iPhone Farm Manager trước khi chạy (cổng serial của board chỉ một chương trình mở được).

Kiểm: độ trễ lệnh (p50/p95/tối đa), giao thức (lệnh lạ, dòng quá dài, rác), gửi dồn không rớt lệnh (bộ đệm nhận),
RAM không rò rỉ sau N lệnh, số liệu sức khoẻ hợp lý (RAM, nhiệt độ, lý do reset), reset mềm (lệnh `reset`) và reset cứng
(chân EN qua RTS) đều đưa board về dùng được, BLE nối lại sau reset (nếu có iPhone). Cần firmware v2 (app → Thiết bị → Nạp);
firmware cũ chỉ kiểm được độ trễ + giao thức cơ bản.
"""
from __future__ import annotations
import os, random, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import boardhealth as bh
import esp
from hands import Hands

results = []


def note(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s %-62s %s" % ("✓" if ok else "✗", name, detail))
    sys.stdout.flush()


def open_board(name: str) -> Hands:
    port = None
    for _ in range(8):                  # cổng mở độc quyền: chương trình khác đang dò thì thử lại
        port = next((b["port"] for b in esp.list_boards() if (esp.probe(b["port"]) or {}).get("name") == name), None)
        if port:
            break
        time.sleep(0.5 + random.random() * 2)
    if not port:
        raise SystemExit("Không thấy board «%s». Đã cắm chưa? Đã tắt app chưa?" % name)
    return Hands(port)


def raw_line(h: Hands, text: str, wait: float = 1.5) -> str:
    """Gửi MỘT dòng thô (không qua _clean: có thể rất dài / có byte lạ) rồi đọc dòng trả lời đầu tiên."""
    h.ser.reset_input_buffer(); h._rx = b""
    h.ser.write(text.encode("latin-1") + b"\n"); h.ser.flush()
    return next(h._lines(time.time() + wait), "") or ""


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__); return 2
    name = sys.argv[1]
    do_reset = "--no-reset" not in sys.argv
    stress = int(sys.argv[sys.argv.index("--stress") + 1]) if "--stress" in sys.argv else 500
    h = open_board(name)
    print("Board %s (%s)" % (name, h.port))
    try:
        print("— CƠ BẢN —")
        first = h.send("ping", wait=1.5)             # cú đầu sau khi mở cổng: cho board thời gian (không tính điểm)
        if first != "pong":
            print("    (lưu ý: ping đầu tiên sau khi mở cổng không có trả lời — bình thường nếu board vừa reset)")
        note("ping → pong", h.send("ping", wait=1.0) == "pong")
        note("whoami → đúng tên", h.send("whoami") == "NAME " + name, h.send("whoami"))
        st = bh.read(h)
        note("status đọc được", st is not None, str(h.send("status"))[:80])
        v2 = bool(st and st.get("fw", 1) >= 2)
        if not v2:
            print("  (firmware CŨ: chưa có số liệu sức khoẻ / reset / chống tràn — nạp lại firmware để kiểm đủ)")
        else:
            info = bh.parse_info(str(h.send("info")))
            note("info: chip, lõi, xung nhịp, flash", bool(info and info.get("chip") and info.get("mhz")), (info or {}))
            print("    sức khoẻ: " + st["summary"])
            note("RAM trống hợp lý (> 40 KB)", st["heap"] > 40_000, "%d KB" % (st["heap"] // 1024))
            tv = bh.temp_of(st)
            note("nhiệt độ thô hợp lý (0–100 °C), hoặc chip không có cảm biến thật", tv is None or 0 < tv < 100,
                 ("%.1f °C" % tv) if tv is not None else "luôn 53.3 °C = không có cảm biến thật (chỉ RAM / nguồn / reset là đáng tin)")
            note("không có phát hiện NẶNG", st["level"] != "bad", "; ".join(f["text"] for f in st["findings"]) or "—")

        if v2:
            print("— MỞ CỔNG KHÔNG RESET —")
            up_a = st["up"]
            h.ser.close()
            time.sleep(3)
            h = Hands(h.port)                         # mở lại cổng: QuietSerial không được làm board khởi động lại
            st_b = bh.read(h)
            note("mở lại cổng KHÔNG làm board reset (uptime tăng, không về 0)", bool(st_b) and st_b["up"] >= up_a + 2,
                 "up %s → %s s" % (up_a, (st_b or {}).get("up")))
            st = st_b or st

        print("— ĐỘ TRỄ —")
        lat = []
        fail = 0
        for _ in range(200):
            t = time.time()
            r = h.send("ping", wait=1.0)
            lat.append((time.time() - t) * 1000)
            fail += r != "pong"
        lat.sort()
        p50, p95, mx = lat[len(lat) // 2], lat[int(len(lat) * 0.95)], lat[-1]
        note("200 lệnh ping: không rớt cái nào", fail == 0, "rớt %d" % fail)
        note("độ trễ ping: trung vị < 120 ms, p95 < 250 ms", p50 < 120 and p95 < 250, "p50 %.0f · p95 %.0f · max %.0f ms" % (p50, p95, mx))

        print("— GIAO THỨC —")
        note("lệnh lạ → ERR cmd?", raw_line(h, "khonglenhnay").startswith("ERR"), raw_line(h, "khonglenhnay"))
        r = raw_line(h, "x" * 700, 2.0)
        if v2:
            note("dòng dài 700 ký tự → ERR line-too-long (không ăn RAM)", r.startswith("ERR") and "long" in r, r)
        else:
            note("dòng dài 700 ký tự → board không đơ", True, "(firmware cũ: %s)" % (r or "không trả lời"))
        note("…và board vẫn trả lời ngay sau đó", h.send("ping") == "pong")
        rr = raw_line(h, "".join(chr(random.randint(1, 31)) for _ in range(40)).replace("\n", " "), 1.5)
        note("byte rác điều khiển → không đơ", h.send("ping") == "pong", rr[:30])
        r = h.send("move 1", wait=1.0)
        note("lệnh thiếu tham số (move 1) → ERR, và board không đơ", r.startswith("ERR") and h.send("ping") == "pong", r)

        print("— GỬI DỒN —")
        got = h.burst(["ping"] * 300, wait=3.0)
        note("300 ping trong MỘT lần ghi → đủ 300 pong, không rớt", len(got) == 300 and all(x == "pong" for x in got), "nhận %d" % len(got))
        got = h.burst(["status"] * 60, wait=3.0)
        note("60 status trong một lần ghi → đủ 60 câu trả lời", len(got) == 60 and all(x.startswith("OK ble=") for x in got), "nhận %d" % len(got))
        if v2:
            st2 = bh.read(h)
            note("sau gửi dồn: không có lỗi tràn serial", st2 and st2.get("rxerr", 0) == 0, "rxerr=%s" % (st2 or {}).get("rxerr"))

        print("— RÒ RỈ RAM —")
        if v2:
            a = bh.read(h)
            for i in range(stress):
                h.send("ping", wait=1.0) if i % 2 else h.send("status", wait=1.0)
            b = bh.read(h)
            leak = a["heap"] - b["heap"]
            note("%d lệnh ping/status: RAM trống mất < 4 KB" % stress, leak < 4096, "trước %d → sau %d (mất %d byte)" % (a["heap"], b["heap"], leak))
            note("cmds tăng đúng số lệnh đã gửi (không bỏ sót)", b["cmds"] - a["cmds"] >= stress, "+%d" % (b["cmds"] - a["cmds"]))
        else:
            print("  (bỏ qua: cần firmware v2)")

        print("— BLE (nếu có iPhone) —")
        connected = "ble=connected" in str(h.send("status"))
        if connected:
            bad = sum(not (h.send("move 1 0", wait=1.0) == "OK move" and h.send("move -1 0", wait=1.0) == "OK move") for _ in range(30))
            note("30 cặp move +1/−1: đều OK", bad == 0, "lỗi %d" % bad)
            note("nhả nút (up) OK", h.send("up") == "OK up")
        else:
            print("  (chưa có iPhone nối BLE → bỏ qua; lệnh HID phải trả ERR not-connected)")
            note("chưa nối BLE → lệnh HID trả ERR not-connected (không treo)", h.send("move 1 0", wait=1.0) == "ERR not-connected", h.send("move 1 0", wait=1.0))

        if do_reset and v2:
            print("— RESET —")
            up0 = bh.read(h)["up"]
            t = time.time()
            ok = bh.soft_reset(h)
            s = bh.read(h)
            note("reset MỀM (lệnh reset): board khởi động lại và dùng được", ok and s is not None, "%.1f s" % (time.time() - t))
            note("…lý do reset = sw, up nhỏ lại, cmds về ~0", s and s["rst"] == "sw" and s["up"] < max(up0, 30) and s["cmds"] < 20, str({k: (s or {}).get(k) for k in ("rst", "up", "cmds")}))
            if connected:
                t = time.time()
                back = h.wait_connected(30)
                note("BLE nối lại sau reset mềm", back, "%.0f s" % (time.time() - t))
            t = time.time()
            ok = bh.hard_reset(h)
            s = bh.read(h)
            note("reset CỨNG (chân EN qua RTS): board dùng lại được", ok and s is not None, "%.1f s" % (time.time() - t))
            note("…lý do reset = poweron/ext, up nhỏ", s and s["rst"] in ("poweron", "ext") and s["up"] < 30, str({k: (s or {}).get(k) for k in ("rst", "up")}))
            if connected:
                t = time.time()
                back = h.wait_connected(30)
                note("BLE nối lại sau reset cứng", back, "%.0f s" % (time.time() - t))
            r = bh.recover(h)
            note("recover() trên board khoẻ → không làm gì thêm", r["ok"] and r["actions"] == [], r["actions"])
        elif do_reset:
            print("— RESET — (bỏ qua: cần firmware v2 cho lệnh reset mềm)")
    finally:
        h.ser.close()

    n_ok = sum(results)
    print("\n%s Board %s: %d/%d" % ("✅" if n_ok == len(results) else "❌", name, n_ok, len(results)))
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
