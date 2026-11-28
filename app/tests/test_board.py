#!/usr/bin/env python3
"""
Kiểm phần SỨC KHOẺ board ESP32 (app/boardhealth.py) bằng board giả — không cần phần cứng:
  • đọc dòng status của firmware v2 (và firmware cũ v1);
  • đánh giá: thiếu RAM, phân mảnh, nóng, sụt nguồn, tự reset, tràn serial, BLE rớt liên tục;
  • tự phục hồi LÚC RẢNH: board im → reset cứng; thiếu RAM → reset mềm sớm; sau reset chờ BLE nối lại;
    không được phép reset thì không reset.
Thử trên board thật: app/tests/smoke_board.py. Biên dịch firmware: app/tests/test_firmware.py.

    ./.venv/bin/python app/tests/test_board.py
"""
from __future__ import annotations
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import boardhealth as bh


class Clock:                                  # đồng hồ GIẢ riêng của module boardhealth (không đụng time.sleep toàn cục của test khác)
    t = 0.0


bh.time = types.SimpleNamespace(time=lambda: Clock.t, sleep=lambda s: setattr(Clock, "t", Clock.t + s))

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


GOOD = "OK ble=connected fw=3 up=7300 heap=152000 tot=330000 min=118000 blk=110000 rst=poweron rxerr=0 ovf=0 drop=0 cmds=412"


def line(**kw):
    d = dict(ble="connected", fw=3, up=7300, heap=152000, tot=330000, min=118000, blk=110000, rst="poweron", rxerr=0, ovf=0, drop=0, cmds=412)
    d.update(kw)
    return "OK ble=%s " % d.pop("ble") + " ".join("%s=%s" % kv for kv in d.items())


class FakeSer:
    def __init__(self): self.dtr, self.rts, self.log, self.closed = False, False, [], False
    def reset_input_buffer(self): self.log.append("flush")
    def close(self): self.closed = True


class FakeBoard:
    """Board giả. `script` = danh sách trạng thái; mỗi lần reset (cứng / mềm) chuyển sang trạng thái kế."""
    def __init__(self, states, silent_first=0, dead=False):
        self.dead = dead                      # chết hẳn: reset xong vẫn im
        self.states, self.i, self.silent, self.sent, self.ser, self._rx = states, 0, silent_first, [], FakeSer(), b""
        self.hard = 0; self.soft = 0; self.ble_waits = 0
        self.disc, self.disc_reply = [], None         # các lệnh disconnect đã nhận / câu trả lời ép sẵn (None = trả lời như firmware v3)
        outer = self
        class RtsWatch:
            def __init__(s): s._rts = False
            @property
            def rts(s): return s._rts
            @rts.setter
            def rts(s, v):
                if s._rts and not v:
                    outer.hard += 1; outer.i = min(outer.i + 1, len(outer.states) - 1); outer.silent = 10 ** 12 if outer.dead else 0
                s._rts = v
            dtr = False
            def reset_input_buffer(s): pass
            closed = False
            def close(s): s.closed = True
        self.ser = RtsWatch()
        self.ignore_reset = False                     # board «đơ»: nhận lệnh reset nhưng KHÔNG khởi động lại

    def send(self, cmd, wait=0.5):
        self.sent.append(cmd)
        if self.silent > 0:
            self.silent -= 1
            return ""
        st = self.states[self.i]
        if cmd == "ping": return "pong"
        if cmd == "status": return st
        if cmd == "reset":
            self.soft += 1
            if not self.ignore_reset:
                self.i = min(self.i + 1, len(self.states) - 1)
            return "OK reset"
        if cmd.startswith("disconnect"):
            self.disc.append(cmd)
            if self.disc_reply is not None:
                return self.disc_reply
            self.i = min(self.i + 1, len(self.states) - 1)          # sau lệnh: trạng thái kế (iPhone đã rớt)
            return "OK disconnect hold=%s" % (cmd.split()[1] if len(cmd.split()) > 1 else "30")
        return "OK " + cmd

    def status(self):                                 # như Hands.status()
        return self.send("status")

    def wait_connected(self, timeout=15.0):
        self.ble_waits += 1
        return "ble=connected" in self.states[self.i]


def main():
    print("== 1. Đọc dòng status ==")
    h = bh.parse_status(GOOD)
    ok(h and h["connected"] and h["fw"] == 3 and h["heap"] == 152000 and h["tot"] == 330000 and h["min"] == 118000 and h["rst"] == "poweron" and h["cmds"] == 412,
       "firmware v3: đọc đủ RAM trống, TỔNG RAM, đáy RAM, lý do reset, số lệnh", h)
    old = bh.parse_status("OK ble=disconnected")
    ok(old and old["connected"] is False and old["fw"] == 1, "firmware cũ (chỉ có ble=…) vẫn đọc được, coi là fw=1", old)
    ok(bh.parse_status("pong") is None and bh.parse_status("") is None and bh.parse_status("ERR cmd?") is None and bh.parse_status("OK click") is None, "dòng khác không bị nhận nhầm là status")
    ok(bh.parse_status("OK ble=connected fw=3 up=abc heap=1 tot=zz")["heap"] == 1, "giá trị hỏng chỉ bị bỏ qua, không làm đổ cả dòng")
    inf = bh.parse_info("OK info chip=ESP32-D0WD-V3 rev=3 cores=2 mhz=240 flash=4096k sdk=v4.4.7")
    ok(inf and inf["chip"] == "ESP32-D0WD-V3" and inf["cores"] == 2 and inf["mhz"] == 240 and inf["flash"] == "4096k", "dòng info: chip, số lõi, xung nhịp, flash", inf)

    print("\n== 2. Đánh giá ==")
    codes = lambda s: {f["code"]: f for f in bh.assess(bh.parse_status(s))}
    ok(bh.level_of(bh.assess(bh.parse_status(GOOD))) == "ok" and bh.assess(bh.parse_status(GOOD)) == [], "board khoẻ → không phát hiện gì")
    c = codes(line(heap=30000))
    ok(c["heap_low"]["level"] == "warn" and c["heap_low"]["reset"] is True, "RAM trống 30 KB → cảnh báo, và khởi động lại thì khá hơn")
    c = codes(line(heap=20000, min=9000))
    ok(c["heap_low"]["level"] == "bad" and "heap_floor" not in c, "RAM trống 20 KB → NẶNG (không báo thêm «đáy» cho cùng một chuyện)")
    c = codes(line(min=15000))
    ok(c["heap_floor"]["level"] == "warn" and c["heap_floor"]["reset"] is False, "RAM trống bình thường nhưng từng chạm đáy 15 KB → chỉ ghi nhận, không cần reset")
    c = codes(line(blk=8000))
    ok(c["heap_frag"]["reset"] is True, "mảng RAM liền lớn nhất nhỏ → phân mảnh, reset giúp được")
    ok(not hasattr(bh, "temp_of") and "°C" not in bh.summary(bh.parse_status(GOOD)),
       "nhiệt độ ĐÃ BỎ (ESP32 gốc luôn báo 53,3 °C = không có cảm biến thật): không còn trong tóm tắt / dữ liệu giao diện")
    c = codes(line(up=120, rst="brownout"))
    ok(c["brownout"]["level"] == "bad" and c["brownout"]["reset"] is False and "USB" in c["brownout"]["text"], "vừa tự reset vì SỤT NGUỒN → nặng, chỉ dẫn đổi cáp/hub (reset không giúp)")
    ok("brownout" not in codes(line(up=50000, rst="brownout")), "…nhưng đã chạy ổn từ lâu thì lý do reset cũ không còn đáng báo")
    ok(codes(line(up=60, rst="task_wdt"))["crash"]["level"] == "warn" and codes(line(up=60, rst="panic"))["crash"]["level"] == "warn" and "crash" not in codes(line(up=60, rst="sw")), "vừa reset vì watchdog / lỗi chương trình → cảnh báo; reset do lệnh `reset` thì không")
    ok(codes(line(rxerr=3))["rxerr"]["level"] == "warn", "serial từng tràn / lỗi khung → cảnh báo")
    ok(codes(line(up=1800, drop=5))["ble_drops"]["level"] == "warn" and "ble_drops" not in codes(line(up=36000, drop=5)) and "ble_drops" not in codes(line(up=600, drop=2)),
       "BLE rớt liên tục (≥3 lần và >6 lần/giờ) → cảnh báo; thỉnh thoảng thì không")
    f = bh.assess(bh.parse_status(line(heap=20000, rxerr=1)))
    ok([x["level"] for x in f] == sorted([x["level"] for x in f], key=lambda l: -bh._ORDER[l]) and bh.level_of(f) == "bad", "nhiều phát hiện: nặng nhất đứng đầu, mức chung = nặng nhất")
    ok(bh.assess(None)[0]["code"] == "silent" and bh.level_of(bh.assess(None)) == "bad", "board im → nặng")
    ok(bh.assess(bh.parse_status("OK ble=connected"))[0]["code"] == "old_fw", "firmware cũ → chỉ gợi ý nạp lại (không bắt lỗi)")
    s = bh.summary(bh.parse_status(GOOD))
    ok("RAM dùng 173 / 322 KB (54%)" in s and "2 giờ" in s and "poweron" in s and "BLE rớt 0" in s, "tóm tắt một dòng: RAM ĐÃ DÙNG / TỔNG, thời gian chạy, lý do reset", s)
    ok(bh.ram_of(bh.parse_status(GOOD)) == (178000, 330000, 54) and bh.ram_of(bh.parse_status("OK ble=connected fw=2 up=5 heap=100000")) == (None, None, None)
       and "RAM trống 97 KB" in bh.summary(bh.parse_status("OK ble=connected fw=2 up=5 heap=100000 min=90000 blk=80000 rst=poweron drop=0")),
       "RAM dùng/tổng tính đúng từ heap & tot; firmware v2 (chưa báo tổng) → chỉ nói «RAM trống», không bịa số tổng")
    v = bh.view(GOOD)
    ok(v["ram_used"] == 178000 and v["ram_total"] == 330000 and v["ram_pct"] == 54 and v["connected"] is True and v["level"] == "ok", "dữ liệu cho giao diện có ram_used / ram_total / ram_pct / connected", v)

    print("\n== 2b. Huỷ kết nối Bluetooth (lệnh disconnect) ==")
    b = FakeBoard([GOOD, line(ble="disconnected")])
    r = bh.disconnect_bt(b, 30)
    ok(r["ok"] is True and not r.get("none") and r["hold"] == 30 and b.disc == ["disconnect 30"], "iPhone đang nối → gửi «disconnect 30», chờ thấy ble=disconnected rồi báo xong", (r, b.disc))
    b = FakeBoard([line(ble="disconnected")]); b.disc_reply = "OK disconnect none"
    r = bh.disconnect_bt(b)
    ok(r["ok"] is True and r["none"] is True, "không có iPhone nào đang nối → báo «không có gì để huỷ», không lỗi", r)
    for rep in ("ERR cmd?", "ERR not-connected"):
        b = FakeBoard([GOOD]); b.disc_reply = rep
        r = bh.disconnect_bt(b)
        ok(r["ok"] is False and "firmware cũ" in r["error"], "firmware v2 (không có lệnh) trả «%s» → báo rõ cần nạp lại firmware" % rep, r)
    b = FakeBoard([GOOD]); b.disc_reply = ""
    r = bh.disconnect_bt(b)
    ok(r["ok"] is False and "không trả lời" in r["error"] and "firmware cũ" not in r["error"], "board IM (không phải firmware cũ) → nói «không trả lời», đừng bảo nạp lại firmware oan", r)
    b = FakeBoard([GOOD]); b.disc_reply = "ERR no-peer"
    r = bh.disconnect_bt(b)
    ok(r["ok"] is False and "không tìm thấy kết nối" in r["error"], "ERR no-peer → câu tiếng Việt dễ hiểu, không hiện mã thô", r)
    ok("đang giữ huỷ BT (còn 12 s)" in bh.summary(bh.parse_status(line(bthold=12))) and "đang giữ" not in bh.summary(bh.parse_status(GOOD)),
       "đang trong thời gian giữ huỷ BT thì tóm tắt nói rõ còn bao nhiêu giây (người vận hành / AI không tưởng BT hỏng)")
    b = FakeBoard([GOOD]); b.disc_reply = "OK disconnect hold=30"
    r = bh.disconnect_bt(b, 30, wait=2.0)
    ok(r["ok"] is False and "chưa rớt" in r["error"], "lệnh nhận rồi mà iPhone vẫn nối → báo thất bại (không giả vờ thành công)", r)

    print("\n== 2c. Khởi động lại có KIỂM CHỨNG (nút «Khởi động lại») ==")
    b = FakeBoard([line(up=5000), line(up=2)])
    r = bh.restart(b)
    ok(r == {"ok": True, "how": "mềm"} and b.soft == 1 and b.hard == 0, "board nhận lệnh reset và uptime về nhỏ → xong bằng reset mềm", (r, b.soft, b.hard))
    b = FakeBoard([line(up=5000), line(up=2)]); b.ignore_reset = True
    r = bh.restart(b)
    ok(r == {"ok": True, "how": "cứng"} and b.soft == 1 and b.hard == 1, "board «đơ»: trả OK reset mà KHÔNG khởi động lại (uptime vẫn lớn) → tự chuyển sang reset CỨNG (chân EN)", (r, b.soft, b.hard))
    b = FakeBoard([line(up=5000)], silent_first=10 ** 12, dead=True)
    r = bh.restart(b)
    ok(r["ok"] is False and r["how"] == "cứng" and b.hard == 1, "board chết hẳn → thử reset cứng MỘT lần rồi báo hỏng (không lặp vô hạn)", (r, b.hard))
    b = FakeBoard(["OK ble=connected"])
    r = bh.restart(b)
    ok(r["how"] == "cứng" and b.hard == 1, "firmware v1 (không có `up`, không có lệnh reset) → không kiểm chứng được → reset cứng", (r, b.hard))

    print("\n== 3. Tự phục hồi (lúc rảnh) ==")
    b = FakeBoard([GOOD])
    r = bh.recover(b)
    ok(r["ok"] and r["actions"] == [] and b.hard == 0 and b.soft == 0 and "reset" not in b.sent, "board khoẻ → không làm gì, KHÔNG reset", (r, b.sent))
    b = FakeBoard([line(up=40000), GOOD], silent_first=6)       # im lặng (đơ hẳn) cho tới khi reset cứng
    r = bh.recover(b)
    ok(r["ok"] and b.hard == 1 and r["actions"] and "cứng" in r["actions"][0], "board đơ (không trả lời) → reset cứng bằng chân EN, rồi dùng lại được", (r, b.hard))
    b = FakeBoard([line(up=40000)], silent_first=10 ** 12, dead=True)
    r = bh.recover(b)
    ok(r["ok"] is False and r["alive"] is False and b.hard == 1, "reset cứng xong vẫn im → báo hỏng (không lặp vô hạn)", r)
    b = FakeBoard([line(up=40000)], silent_first=10 ** 12)
    r = bh.recover(b, allow_reset=False)
    ok(r["ok"] is False and b.hard == 0 and b.soft == 0, "không được phép reset (đang có đơn) → không reset, chỉ báo", (r, b.hard))
    b = FakeBoard([line(heap=18000, min=9000), GOOD])
    r = bh.recover(b)
    ok(r["ok"] and b.soft == 1 and b.hard == 0 and "reset mềm" in r["actions"][0] and r["health"]["heap"] == 152000, "thiếu RAM nặng → reset mềm SỚM (lúc rảnh), đọc lại thấy khoẻ", (r, b.sent))
    b = FakeBoard([line(heap=18000, min=9000), GOOD])
    r = bh.recover(b, allow_reset=False)
    ok(b.soft == 0 and r["level"] == "bad" and r["ok"] is False, "thiếu RAM nhưng không được phép reset → chỉ báo nặng, không reset", r)
    b = FakeBoard([line(up=60, rst="brownout")])
    r = bh.recover(b)
    ok(b.soft == 0 and b.hard == 0 and r["level"] == "bad", "sụt nguồn: reset không giúp gì → không reset vô ích, chỉ báo", (r, b.sent))
    b = FakeBoard([line(heap=18000), line(ble="disconnected")])
    r = bh.recover(b)
    ok(b.ble_waits == 1 and any("BLE" in a for a in r["actions"]) and r["ok"] is False,
       "sau reset iPhone chưa nối lại BLE → có chờ, nói rõ, và KHÔNG coi là ổn (nhận đơn lúc này = không bấm được gì → đơn hỏng oan)", (r, b.ble_waits))
    b = FakeBoard([line(heap=18000), GOOD])
    ok(bh.recover(b)["health"]["connected"] and b.ble_waits == 0, "sau reset BLE nối ngay → không chờ thừa")

    print("\n== 4. Mở cổng serial KHÔNG làm board reset (QuietSerial) ==")
    import inspect
    from quietserial import QuietSerial
    import esp, hands as handsmod
    ok("QuietSerial()" in inspect.getsource(handsmod.Hands.__init__) and "QuietSerial()" in inspect.getsource(esp.probe),
       "Hands (điều khiển) và esp.probe (quét board) đều mở cổng bằng QuietSerial")
    if os.name == "nt":
        # phép đo thứ tự hạ DTR / RTS dùng cổng giả pty + ioctl — chỉ có trên macOS / Linux
        print("  (Windows: bỏ phép đo thứ tự DTR / RTS trên cổng giả pty — không có pty / fcntl)")
        print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
        return 1 if FAIL else 0
    import fcntl, pty
    import serial, serial.serialposix as sp

    def open_order(cls):
        """Mở một cổng pty bằng `cls(dtr=False, rts=False)`, trả thứ tự các lệnh bật/tắt DTR/RTS lúc mở."""
        master, slave = pty.openpty()
        calls, real = [], fcntl.ioctl

        def rec(fd, req, arg=0, *a):
            if req in (sp.TIOCMBIS, sp.TIOCMBIC):
                calls.append(("bật" if req == sp.TIOCMBIS else "hạ", "DTR" if arg == sp.TIOCM_DTR_str else "RTS"))
                return 0                      # cổng pty không có đường điều khiển modem → chỉ GHI NHẬN thứ tự lệnh, không gọi thật
            return real(fd, req, arg, *a)
        fcntl.ioctl = rec
        try:
            ser = cls(); ser.port = os.ttyname(slave); ser.dtr = False; ser.rts = False
            ser.open(); ser.close()
        finally:
            fcntl.ioctl = real
            os.close(master); os.close(slave)
        return calls

    plain, quiet = open_order(serial.Serial), open_order(QuietSerial)
    first = lambda calls, what: next(i for i, c in enumerate(calls) if c == what)
    ok(first(plain, ("hạ", "DTR")) < first(plain, ("hạ", "RTS")),
       "(ghi nhận lỗi gốc) pyserial thường hạ DTR TRƯỚC RTS → có lúc (DTR=0, RTS=1) = mạch tự reset kéo EN xuống → board khởi động lại mỗi lần mở cổng", plain)
    ok(first(quiet, ("hạ", "RTS")) < first(quiet, ("hạ", "DTR")),
       "QuietSerial hạ RTS TRƯỚC DTR → không bao giờ có trạng thái (DTR=0, RTS=1) → mở cổng không reset board", quiet)

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
