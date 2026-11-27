#!/usr/bin/env python3
"""
Kiểm bộ ghi «máy nào đang chạy bước nào» + lịch sử theo máy / theo đơn (app/history.py) và chỗ nó gắn vào bộ chạy bước:
  • trạng thái trực tiếp: lượt chạy, đơn, giai đoạn, bước thứ mấy / tổng số, bước vừa xong;
  • lịch sử của máy (mỗi bước một dòng kèm kết quả + thời gian), sổ tóm tắt đơn, các bước của một đơn;
  • KHÔNG có bí mật: tài khoản / mật khẩu / OTP của khách không bao giờ nằm trong tệp lịch sử;
  • ghi lịch sử trục trặc (thư mục hỏng, bộ theo dõi ném lỗi) không làm hỏng bước đang chạy;
  • tệp lớn thì tự cắt bớt phần cũ; dòng ghi dở bị bỏ qua.

    ./.venv/bin/python app/tests/test_history.py
"""
from __future__ import annotations
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import apimode, engine, history

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


class Fake:                                   # máy giả: chỉ có bàn phím + màn hình cố định
    def __init__(self, tracker=None, text="Trang chu"):
        self.e = self; self.h = self; self.sent = []; self.text = text
        if tracker is not None:
            self.observer = tracker

    def send(self, cmd, wait=0.5): self.sent.append(cmd); return "OK"
    def key(self, name): self.sent.append("key " + name)
    def screenshot(self): return None
    def read_text(self, img=None, **k): return self.text
    def find_text(self, *a, **k): return None


def lines(path):
    return [json.loads(x) for x in open(path, encoding="utf-8").read().splitlines() if x.strip()]


def main():
    real_sleep = apimode._sleep
    apimode._sleep = lambda s, a=None: None
    tmp = tempfile.mkdtemp(prefix="ipf-hist-")
    try:
        print("== 1. Một đơn đi qua: trạng thái trực tiếp + lịch sử của máy + sổ đơn ==")
        H = history.History(tmp)
        tr = H.tracker("iPhoneFarm-01")
        n = Fake(tr)
        ok(H.live() == {} and H.tracker("iPhoneFarm-01") is tr, "máy chưa làm gì → không có trong «đang chạy»; mỗi máy đúng một bộ theo dõi")
        tr.run_begin("nhận đơn", "Efootball ip8", "nạp Efootball", "api")
        job = {"id": 77, "ref": "T-77", "items": [{"code": "coin_1050", "name": "1050 Coins", "qty": 2, "ocr_text": "1050"}],
               "login": {"username": "khach-bi-mat@vidu.vn", "password": "MatKhau#Bi-Mat"}, "otp": {"code": "246810"}}
        tr.order_begin(job)
        apimode.watch_phase(n, "Đăng nhập", 3)
        r1 = apimode.exec_step(n, {"type": "type", "text": "{{username}}"}, job["login"])
        mid = H.live()["iPhoneFarm-01"]
        ok(r1[0] is True and mid["kind"] == "nhận đơn" and mid["group"] == "Efootball ip8" and mid["script"] == "nạp Efootball" and mid["order"]["ref"] == "T-77"
           and mid["phase"] == "Đăng nhập" and mid["last"]["what"] == "Gõ «{{username}}»" and mid["last"]["i"] == 1 and mid["last"]["n"] == 3 and "step" not in mid,
           "giữa đơn: thấy nhóm · kịch bản, mã đơn, giai đoạn, bước vừa xong (thứ 1/3) — chữ gõ chỉ là TÊN biến", mid)
        seen = {}

        class Peek(Fake):                      # nhìn «đang chạy» đúng lúc bước đang được thực hiện
            def send(self, cmd, wait=0.5):
                seen["live"] = H.live()["iPhoneFarm-01"]
                return super().send(cmd, wait)
        p = Peek(tr)
        apimode.exec_step(p, {"type": "type", "text": "{{password}}"}, job["login"])
        st = seen["live"].get("step") or {}
        ok(st.get("what") == "Gõ «{{password}}»" and st.get("i") == 2 and st.get("n") == 3 and st.get("phase") == "Đăng nhập" and st.get("since"),
           "ĐANG chạy một bước: thấy đúng bước đó, thứ 2/3, kèm lúc bắt đầu", seen["live"])
        r3 = apimode.exec_step(n, {"type": "tap_text", "text": "Nút không có"}, {})
        apimode.watch_phase(n, "Mua một gói", 1)
        apimode.exec_step(n, {"type": "wait_text", "text": "{{package.ocr_text}}|Trang chu", "timeout": 0}, {"package.ocr_text": "1050"})
        tr.note("Đang mua 1050 Coins (1/2)")
        tr.order_end("done", "đã nạp 2 gói")
        after = H.live()["iPhoneFarm-01"]
        tr.run_end("Chờ đơn")
        ev = lines(os.path.join(tmp, "may-iPhoneFarm-01.jsonl"))
        kinds = [e["ev"] for e in ev]
        steps = [e for e in ev if e["ev"] == "step"]
        ok(kinds == ["run_begin", "order_begin", "step", "step", "step", "step", "note", "order_end", "run_end"], "lịch sử của máy: đủ các sự kiện theo đúng thứ tự", kinds)
        ok([(s["i"], s["n"], s["phase"], s["ok"]) for s in steps] == [(1, 3, "Đăng nhập", True), (2, 3, "Đăng nhập", True), (3, 3, "Đăng nhập", False), (1, 1, "Mua một gói", True)]
           and steps[2]["msg"] == "không thấy chữ «Nút không có» trên màn hình" and r3[0] is False and all(s["order"] == "77" and s["run"] == ev[0]["id"] for s in steps)
           and steps[3]["what"] == "Chờ chữ «1050|Trang chu»",
           "mỗi bước một dòng: thứ tự trong giai đoạn, kết quả, lý do khi hỏng, thuộc đơn nào / lượt chạy nào; thông tin GÓI thì hiện giá trị", steps)
        raw = "".join(open(os.path.join(tmp, f), encoding="utf-8").read() for f in os.listdir(tmp))
        ok(not any(x in raw for x in ("khach-bi-mat", "MatKhau#Bi-Mat", "246810")) and "{{username}}" in raw and "{{password}}" in raw,
           "KHÔNG có tài khoản / mật khẩu / OTP của khách trong bất kỳ tệp lịch sử nào (chỉ có tên biến)")
        orders = H.orders()
        ok(len(orders) == 1 and orders[0]["id"] == "77" and orders[0]["ref"] == "T-77" and orders[0]["machine"] == "iPhoneFarm-01" and orders[0]["result"] == "done"
           and orders[0]["steps"] == 4 and orders[0]["failed"] == 1 and orders[0]["items"] == [{"code": "coin_1050", "name": "1050 Coins", "qty": 2}]
           and orders[0]["script"] == "nạp Efootball" and orders[0]["end"] >= orders[0]["t"] and "login" not in json.dumps(orders[0]),
           "sổ đơn: mỗi đơn một dòng — mã, máy, gói, kết quả, số bước / số bước lỗi; không kèm thông tin đăng nhập", orders)
        one = H.order(77)
        ok(len(one["runs"]) == 1 and [e["ev"] for e in one["events"]] == ["order_begin", "step", "step", "step", "step", "note", "order_end"]
           and all(e["machine"] == "iPhoneFarm-01" for e in one["events"]) and H.order("khong-co")["events"] == [],
           "xem MỘT đơn: đúng các bước của đơn đó trên máy đã chạy nó; đơn lạ → rỗng", [e["ev"] for e in one["events"]])
        ok("order" not in after and after.get("kind") == "nhận đơn" and H.live().get("iPhoneFarm-01", {}).get("kind") is None,
           "xong đơn → hết «đơn đang làm»; xong lượt chạy → hết «đang chạy» (chỉ còn bước vừa xong hiện thêm ít giây)", (after, H.live()))
        tr.last["t"] -= 60
        ok(H.live() == {}, "…quá ít giây đó thì máy về «nghỉ»")

        tlit = H.tracker("may-go-tay")
        fl = Fake(tlit)
        apimode.exec_step(fl, {"type": "type", "text": "MatKhauGoTay123"}, {})
        engine.run_step(fl, {"type": "type", "text": "MatKhauGoTay456"})
        raw2 = open(H._path("may-go-tay"), encoding="utf-8").read()
        ok("MatKhauGoTay" not in raw2 and raw2.count("Gõ 15 ký tự") == 2, "chữ gõ TRỰC TIẾP (có thể là mật khẩu gõ tay) không lưu nguyên văn — chỉ ghi số ký tự", raw2[:200])
        for bad in ({"type": "type", "text": "MậtKhẩuGõTay"}, {"type": "type", "text": "MatKhauCach ", "gap": 0.1}):
            try:
                engine.run_step(fl, bad) if bad.get("gap") else apimode.exec_step(fl, bad, {})
            except apimode.InputError:
                pass
        raw3 = open(H._path("may-go-tay"), encoding="utf-8").read()
        ok("MậtKhẩu" not in raw3 and "MatKhauCach" not in raw3 and "không gõ được" in raw3,
           "chữ gõ trực tiếp mà tool KHÔNG gõ được (có dấu / khoảng trắng cuối): lời báo lỗi ghi vào lịch sử vẫn không chứa chữ đó", raw3[-400:])
        ok(apimode.observed_why({"type": "type", "text": "abc123"}, "Gõ «abc123» — lỗi") == "Gõ «(6 ký tự)» — lỗi"
           and apimode.observed_why({"type": "type", "text": "{{password}}"}, "Gõ «{{password}}»") == "Gõ «{{password}}»"
           and apimode.observed_why({"type": "tap_text", "text": "Login"}, "không thấy «Login»") == "không thấy «Login»",
           "observed_why: chỉ bỏ chữ gõ TRỰC TIẾP; tên biến và lời của bước khác giữ nguyên")

        class Err(Fake):                          # board báo lỗi → bước gõ HỎNG
            def send(self, cmd, wait=0.5): return "ERR busy"
        rs = apimode.run_steps(Err(), [{"type": "type", "text": "HandTypedPw9"}], {})
        try:
            apimode.run_steps(Fake(), [{"type": "type", "text": "MậtKhẩuGõTay"}], {}); rs2 = None
        except apimode.InputError as e:
            rs2 = str(e)
        ok(rs[0] is False and "HandTypedPw9" not in rs[1] and "12 ký tự" in rs[1] and rs2 and "MậtKhẩu" not in rs2 and "12 ký tự" in rs2,
           "lời báo HỎNG của cả giai đoạn (đi vào lời nhắn / kết quả của đơn → lịch sử) cũng không chứa chữ gõ trực tiếp", (rs, rs2))
        ok(H._path("Máy 1") != H._path("Mây 1") and H._path("iPhone 01") != H._path("iPhone_01") and H._path("iPhoneFarm-01").endswith("may-iPhoneFarm-01.jsonl"),
           "tên máy khác nhau không bao giờ dùng chung một tệp lịch sử (tên phải làm sạch thì thêm mã của tên gốc)")
        box = {"d": os.path.join(tmp, "thu-muc-1")}
        HL = history.History(lambda: box["d"])
        HL.tracker("x").note("a")
        box["d"] = os.path.join(tmp, "thu-muc-2")
        HL.tracker("x").note("b")
        ok(os.path.exists(os.path.join(tmp, "thu-muc-1", "may-x.jsonl")) and os.path.exists(os.path.join(tmp, "thu-muc-2", "may-x.jsonl")),
           "thư mục lưu tính LẠI mỗi lần ghi (bài thử đổi thư mục dữ liệu → lịch sử đi theo, không ghi vào dữ liệu thật)")

        print("== 2. Chạy thử / kịch bản thường; bước lồng nhau chỉ tính một lần ==")
        t2 = H.tracker("iPhoneFarm-002")
        m = Fake(t2, text="Game Center Hủy")
        m.find_text = lambda needle, img=None, **k: None
        t2.run_begin("chạy thử kịch bản")
        res = engine.run_flow(m, [{"type": "key", "name": "enter"}, {"type": "tap_if", "text": "Không có hộp thoại", "tap": "Hủy", "timeout": 0},
                                  {"type": "wait", "seconds": 0}], log=lambda *a: None)
        t2.run_end()
        ev2 = [e for e in H.machine("iPhoneFarm-002") if e["ev"] == "step"]
        ok(len(res) == 3 and [(e["i"], e["n"], e["type"], e["ok"]) for e in ev2] == [(1, 3, "key", True), (2, 3, "tap_if", True), (3, 3, "wait", True)]
           and ev2[1]["what"].startswith("Nếu thấy chữ «Không có hộp thoại»"),
           "kịch bản thường: bước đếm 1…N; bước chạy qua HAI lớp (engine → apimode) chỉ ghi MỘT dòng", ev2)
        t2.step_begin("Bước lẻ"); t2.step_end(True)
        lone = H.machine("iPhoneFarm-002")[-1]
        ok(lone["ev"] == "step" and lone["what"] == "Bước lẻ" and "run" not in lone and "i" not in lone, "bước lẻ ngoài lượt chạy vẫn được ghi (không thuộc lượt chạy nào, không đánh số)", lone)
        ok(H.machine("iPhoneFarm-002", limit=2) == H.machine("iPhoneFarm-002")[-2:] and H.machine("iPhoneFarm-002", before=ev2[1]["t"] + 1e-9)[-1]["ev"] in ("step", "run_begin")
           and H.machine("may-chua-co") == [] and H.orders(machine="iPhoneFarm-002") == [],
           "đọc lịch sử một máy: lấy N dòng mới nhất, xem tiếp phần cũ hơn một mốc; máy chưa có lịch sử → rỗng")

        print("== 3. Theo dõi trục trặc không được làm hỏng việc đang chạy ==")

        class Broken:                             # bộ theo dõi hỏng
            def step_begin(self, *a): raise RuntimeError("hỏng")
            def step_end(self, *a): raise RuntimeError("hỏng")
            def phase(self, *a): raise RuntimeError("hỏng")
        b = Fake(Broken())
        apimode.watch_phase(b, "x", 1)
        rb = apimode.exec_step(b, {"type": "key", "name": "enter"}, {})
        rb2 = engine.run_step(b, {"type": "wait", "seconds": 0})
        ok(rb[0] is True and b.sent == ["key enter"] and rb2[0] is True, "bộ theo dõi ném lỗi lúc bắt đầu bước → bước vẫn chạy bình thường, đúng một lần", (rb, b.sent))
        bad_root = os.path.join(tmp, "may-iPhoneFarm-01.jsonl", "khong-the-tao")        # thư mục nằm DƯỚI một tệp → không tạo được
        HB = history.History(bad_root)
        tb = HB.tracker("x")
        tb.run_begin("thử"); tb.step_begin("a"); tb.step_end(True); tb.order_begin({"id": 1}); tb.order_end("done"); tb.note("n"); tb.run_end()
        ok(HB.machine("x") == [] and HB.orders() == [] and HB.order(1)["events"] == [], "không ghi được tệp (thư mục hỏng) → không ném lỗi, chỉ là không có lịch sử")
        H0 = history.History(None)
        t0 = H0.tracker("y"); t0.run_begin("thử"); t0.step_begin("a")
        ok(H0.live()["y"]["step"]["what"] == "a" and H0.machine("y") == [], "không có thư mục lưu → vẫn có «đang chạy», chỉ không ghi tệp")
        t3 = H.tracker("iPhoneFarm-03")
        e3 = Fake(t3)
        raised = []
        for bad in ({"type": "type", "text": "{{thieu}}"}, {"type": "tap_text", "text": ""}):
            try:
                apimode.exec_step(e3, bad, {})
            except apimode.ConfigError as err:
                raised.append(str(err))
        ev3 = [e for e in H.machine("iPhoneFarm-03") if e["ev"] == "step"]
        ok(len(raised) == 2 and len(ev3) == 2 and all(e["ok"] is False and e["msg"] for e in ev3) and t3.step is None and t3.depth == 0,
           "bước ném lỗi cấu hình → vẫn được ghi là HỎNG kèm lý do, lỗi vẫn được ném tiếp, bộ đếm không bị kẹt", (raised, ev3))

        class Boom(Fake):
            def send(self, cmd, wait=0.5): raise OSError("cổng serial rớt — %s" % "du-lieu-rieng")
        e4 = Boom(t3)
        try:
            apimode.exec_step(e4, {"type": "key", "name": "enter"}, {}); crashed = False
        except OSError:
            crashed = True
        last = [e for e in H.machine("iPhoneFarm-03") if e["ev"] == "step"][-1]
        ok(crashed and last["ok"] is False and last["msg"] == "lỗi: OSError" and "du-lieu-rieng" not in json.dumps(last),
           "lỗi bất ngờ (rớt cổng…) → ghi HỎNG với TÊN loại lỗi, không chép nguyên văn lời lỗi lạ vào lịch sử", last)

        print("== 4. Tệp lịch sử: tự cắt bớt, bỏ dòng ghi dở ==")
        real_max = history.MACHINE_MAX_BYTES
        history.MACHINE_MAX_BYTES = 6000
        try:
            t5 = H.tracker("may-nhieu")
            for i in range(120):
                t5.step_begin("Bước số %d " % i + "x" * 40); t5.step_end(True)
            path5 = os.path.join(tmp, "may-may-nhieu.jsonl")
            rows5 = lines(path5)
            ok(os.path.getsize(path5) <= 6000 + 400 and 10 < len(rows5) < 120 and rows5[-1]["what"].startswith("Bước số 119") and rows5[0]["what"] != "Bước số 0",
               "tệp của một máy vượt ngưỡng → bỏ phần CŨ, giữ phần mới (không lớn mãi)", (os.path.getsize(path5), len(rows5)))
        finally:
            history.MACHINE_MAX_BYTES = real_max
        with open(os.path.join(tmp, "may-may-nhieu.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"ev":"step","t":1,"what":"ghi dở\n[1,2]\n')
        ok(H.machine("may-nhieu")[-1]["what"].startswith("Bước số 119") and all(isinstance(e, dict) for e in H.machine("may-nhieu", 2000)),
           "dòng ghi dở / không đúng dạng (mất điện giữa chừng) bị bỏ qua, phần còn lại vẫn đọc được")
        ok(history._clip("a" * 500) == "a" * 299 + "…" and history._clip(None) == "" and os.path.basename(H._path("../../etc/passwd")).startswith("may-.._.._etc_passwd-")
           and os.path.dirname(H._path("../../x")) == tmp and os.path.dirname(H._path("../../etc/passwd")) == tmp,
           "lời mô tả quá dài bị cắt; tên máy lạ không thoát được ra ngoài thư mục lịch sử", H._path("../../etc/passwd"))
        for i in range(5):
            tr.order_begin({"id": 100 + i, "ref": "R-%d" % i}); tr.order_end("failed" if i % 2 else "done", "")
        got = H.orders(3)
        ok([o["ref"] for o in got] == ["R-4", "R-3", "R-2"] and len(H.orders()) == 6, "sổ đơn trả đơn MỚI NHẤT trước, giới hạn theo yêu cầu", [o["ref"] for o in got])
    finally:
        apimode._sleep = real_sleep

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
