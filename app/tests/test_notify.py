#!/usr/bin/env python3
"""
Kiểm THÔNG BÁO TELEGRAM (notify.py) + chỗ nối vào bộ chạy (runner) và luồng xem board / Bluetooth của app (gui):
  • chưa cấu hình / loại sự kiện bị tắt → không gửi; cấu hình đủ → gửi đúng nội dung (loại, máy, nhóm, kịch bản, bước, lý do);
  • cùng thông báo lặp lại trong DEDUPE giây chỉ gửi một lần; ảnh gửi bằng sendPhoto, ảnh hỏng thì vẫn báo bằng chữ;
  • lời báo lỗi không bao giờ chứa mã bot;
  • bộ chạy: bước lỗi → «Bước lỗi»; lỗi Bluetooth → «mất kết nối»; bước «bỏ qua nếu lỗi» không báo; dừng giữ máy (đơn khách) → «đối soát»;
  • gui: board / Bluetooth VỪA rớt mới báo (một lần), không báo trạng thái ban đầu.
Không gửi gì ra mạng: mọi lời gọi Telegram đi qua hàm giả.

    ./.venv/bin/python app/tests/test_notify.py
"""
from __future__ import annotations
import json, os, sys, threading, time, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import notify

PASS = FAIL = 0
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghij"


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


class Wire:
    """Telegram giả: ghi lại mọi yêu cầu; `fail` = danh sách lỗi lần lượt ném ra (None = thành công)."""
    def __init__(self):
        self.reqs, self.fail = [], []
        self.lock = threading.Lock()

    def __call__(self, req, timeout):
        with self.lock:
            self.reqs.append(req)
            err = self.fail.pop(0) if self.fail else None
        if err is not None:
            raise err
        return json.dumps({"ok": True, "result": {}}).encode()

    def wait(self, n, secs=3.0):
        end = time.time() + secs
        while time.time() < end and len(self.reqs) < n:
            time.sleep(0.02)
        return len(self.reqs) >= n


def body(req):
    return req.data.decode("utf-8", "replace") if isinstance(req.data, bytes) else ""


def main():
    os.environ.pop("IPF_NO_TELEGRAM", None)
    print("== 1. Cấu hình, nội dung, lọc loại sự kiện ==")
    cfg = {}
    w = Wire()
    clock = [1000.0]
    t = notify.Telegram(lambda: cfg, opener=w, clock=lambda: clock[0])
    ok(t.notify("failed", "M1", ["Lý do: x"]) is False and not w.reqs, "chưa cấu hình → không gửi")
    cfg.update(telegram_token=TOKEN, telegram_chat="-1001234567")
    ok(t.notify("la-gi", "M1", ["x"]) is False, "loại sự kiện lạ → không gửi")
    ok(t.notify("failed", "iPhoneFarm-01", ["Nhóm: Efootball · Kịch bản: nạp", "Bước: 5/8 · Bấm «OK»", "Lý do: con trỏ không tới được"]) is True
       and w.wait(1), "cấu hình đủ → gửi")
    b = body(w.reqs[0]) if w.reqs else ""
    import urllib.parse
    q = urllib.parse.parse_qs(b)
    txt = (q.get("text") or [""])[0]
    ok(w.reqs and w.reqs[0].full_url.endswith("/sendMessage") and q.get("chat_id") == ["-1001234567"]
       and "Bước lỗi / kịch bản dừng" in txt and "iPhoneFarm-01" in txt and "Bước: 5/8" in txt and "con trỏ không tới được" in txt and "Lúc:" in txt,
       "tin gửi đi có loại sự kiện, tên máy, nhóm / kịch bản, bước, lý do, giờ", txt)
    cfg["telegram_events"] = ["review"]
    ok(t.notify("failed", "M1", ["khác"]) is False and t.notify("review", "M1", ["Lý do: đơn cần đối soát"]) is True,
       "chỉ bắn các loại sự kiện được bật")
    cfg.pop("telegram_events")
    w.wait(2)

    old = notify.Telegram(lambda: {"telegram_token": TOKEN, "telegram_chat": "1", "telegram_events": ["paused", "review"]}).config()["events"]
    new = notify.Telegram(lambda: {"telegram_token": TOKEN, "telegram_chat": "1", "telegram_events": ["paused"], "telegram_events_known": list(notify.EVENTS)}).config()["events"]
    ok("wallet" in old and "failed" not in old and new == ["paused"],
       "đã lưu danh sách cũ (trước khi có «Ví không đủ tiền») → loại mới tự BẬT; loại người dùng đã tắt vẫn tắt", (old, new))

    print("== 2. Gộp thông báo trùng ==")
    n0 = len(w.reqs)
    ok(t.notify("paused", "M2", ["Lý do: màn hình lạ"]) is True and t.notify("paused", "M2", ["Lý do: màn hình lạ"]) is False
       and t.notify("paused", "M3", ["Lý do: màn hình lạ"]) is True, "cùng tin của cùng máy trong DEDUPE giây → chỉ một lần; máy khác vẫn gửi")
    clock[0] += notify.DEDUPE + 1
    ok(t.notify("paused", "M2", ["Lý do: màn hình lạ"]) is True and w.wait(n0 + 3), "quá DEDUPE giây → gửi lại")

    print("== 3. Ảnh, lỗi mạng, che mã bot ==")
    n0 = len(w.reqs)
    jpg = b"\xff\xd8\xff\xe0fakejpeg\xff\xd9"
    t.notify("paused", "M4", ["Lý do: quảng cáo lạ"], photo=jpg)
    w.wait(n0 + 1)
    r = w.reqs[n0] if len(w.reqs) > n0 else None
    ok(r is not None and r.full_url.endswith("/sendPhoto") and jpg in r.data and b"caption" in r.data, "có ảnh → sendPhoto kèm chú thích")
    n0 = len(w.reqs)
    w.fail = [urllib.error.URLError("https://api.telegram.org/bot%s/sendPhoto timed out" % TOKEN), None]
    t.notify("paused", "M5", ["Lý do: y"], photo=jpg)
    ok(w.wait(n0 + 2) and w.reqs[n0 + 1].full_url.endswith("/sendMessage"), "gửi ảnh hỏng → vẫn báo bằng chữ")
    w.fail = [urllib.error.URLError("https://api.telegram.org/bot%s/sendMessage down" % TOKEN)]
    good, err = t.send_now("thử")
    ok(good is False and TOKEN not in err and "<mã bot>" in err, "lời báo lỗi không chứa mã bot", err)
    w2 = Wire()
    t2 = notify.Telegram(lambda: cfg, opener=lambda req, timeout: (_ for _ in ()).throw(
        urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, __import__("io").BytesIO(b'{"ok":false,"description":"Unauthorized"}'))))
    good, err = t2.send_now("thử")
    ok(good is False and "401" in err and "Unauthorized" in err and TOKEN not in err, "mã bot sai → báo rõ lỗi của Telegram", err)
    n0 = len(w.reqs)
    w.fail = [urllib.error.URLError("mạng chết"), urllib.error.URLError("mạng chết")]
    t.notify("failed", "M6", ["Lý do: q"])
    w.wait(n0 + 1); time.sleep(0.1)
    ok(t.notify("failed", "M6", ["Lý do: q"]) is True and w.wait(n0 + 2), "gửi KHÔNG được → lần báo sau của cùng tin không bị coi là «trùng»")
    time.sleep(0.2)
    n0 = len(w.reqs)
    worker = t._thread
    ok(worker is not None and worker.is_alive(), "luồng gửi sống suốt (không tự thoát khi rảnh → không có tin nào nằm chờ mãi)")
    os.environ["IPF_NO_TELEGRAM"] = "1"
    n0 = len(w.reqs)
    ok(t.notify("failed", "M9", ["z"]) is False and t.send_now("z")[0] is False and len(w.reqs) == n0, "IPF_NO_TELEGRAM (khi kiểm thử) → không bao giờ gửi")
    os.environ.pop("IPF_NO_TELEGRAM", None)
    ok(notify.link_trouble("Bluetooth chưa nối với iPhone") and notify.link_trouble("board không phản hồi (không rõ…)")
       and not notify.link_trouble("không thấy chữ «Shop»"), "phân loại lỗi board / Bluetooth")

    print("== 3b. Tìm chat id (getUpdates) ==")
    import io
    upd = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 111, "type": "private", "first_name": "Hoàng", "last_name": "Anh"}, "text": "hi"}},
        {"update_id": 2, "my_chat_member": {"chat": {"id": -1001234567890, "type": "supergroup", "title": "Farm admin"}}},
        {"update_id": 3, "message": {"chat": {"id": 111, "type": "private", "first_name": "Hoàng"}, "text": "lần 2"}},
        {"update_id": 4, "channel_post": {"chat": {"id": -1009876543210, "type": "channel", "title": "Kênh báo"}}},
        {"update_id": 5, "callback_query": {"id": "x"}}]}
    reqs = []

    def up_open(req, timeout):
        reqs.append(req.full_url)
        return json.dumps(upd).encode()
    tc = notify.Telegram(lambda: {"telegram_token": TOKEN}, opener=up_open)
    chats, err = tc.chats()
    ids = [c["id"] for c in chats]
    ok(not err and sorted(ids) == sorted(["111", "-1001234567890", "-1009876543210"]) and reqs and "/getUpdates" in reqs[0]
       and "my_chat_member" in urllib.parse.unquote(reqs[0]) and any(c["title"] == "Farm admin" and c["type"] == "supergroup" for c in chats),
       "liệt kê chat đã nói chuyện với bot (người nhắn, nhóm VỪA KÉO bot vào, kênh), không trùng", chats)

    def err_open(code, body):
        def f(req, timeout):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(json.dumps(body).encode()))
        return f
    ok("offset=-100" in reqs[0], "lấy 100 tin MỚI NHẤT (offset=-100), không phải 100 tin cũ nhất", reqs[0][:120])
    ok(chats[0]["id"] == "-1009876543210" and chats[-1]["id"] in ("111", "-1001234567890"), "chat mới thấy gần nhất lên đầu", [c["id"] for c in chats])
    for code, bd, want in ((409, {"description": "Conflict: can't use getUpdates method while webhook is active"}, "webhook"),
                             (409, {"description": "Conflict: terminated by other getUpdates request"}, "chương trình khác"),
                             (401, {"description": "x"}, "mã bot không đúng"), (404, {"description": "x"}, "mã bot không đúng")):
        tc = notify.Telegram(lambda: {"telegram_token": TOKEN}, opener=err_open(code, dict(bd, ok=False)))
        chats, err = tc.chats()
        ok(not chats and want in err and TOKEN not in err, "Telegram lỗi %d → báo rõ «%s», không lộ mã bot" % (code, want), err)
    os.environ["IPF_NO_TELEGRAM"] = "1"
    reqs.clear()
    ok(notify.Telegram(lambda: {"telegram_token": TOKEN}, opener=up_open).chats()[0] == [] and not reqs, "IPF_NO_TELEGRAM → «Tìm chat» không gọi Telegram thật")
    os.environ.pop("IPF_NO_TELEGRAM", None)
    ok(notify.Telegram(lambda: {}).chats() == ([], "chưa nhập mã bot"), "chưa có mã bot → báo")
    tc = notify.Telegram(lambda: {"telegram_token": "999:saved"}, opener=up_open)
    reqs.clear(); tc.chats(TOKEN)
    ok(reqs and TOKEN in reqs[0], "dùng mã bot vừa nhập (chưa lưu) nếu có")

    print("== 4. Bộ chạy (runner) bắn đúng loại sự kiện ==")
    import runner as runmod, engine
    got = []
    R = runmod.Runner(lambda n: object())
    R.alert = lambda ev, name, lines, photo=None: got.append((ev, name, lines))
    real = engine.run_flow
    steps = [{"type": "tap_text", "text": "Shop"}, {"type": "tap", "x": 1, "y": 2}, {"type": "key", "name": "enter", "optional": True}]
    try:
        for res, expect, label in (
                ([{"i": 0, "ok": True, "msg": ""}, {"i": 1, "ok": False, "msg": "con trỏ không tới được vị trí cần bấm"}], "failed", "bước lỗi → «Bước lỗi»"),
                ([{"i": 0, "ok": False, "msg": "Bluetooth chưa nối với iPhone"}], "link", "lỗi Bluetooth → «mất kết nối»"),
                ([{"i": 0, "ok": True}, {"i": 1, "ok": True}, {"i": 2, "ok": False, "msg": "x"}], None, "chỉ bước «bỏ qua nếu lỗi» hỏng → không báo"),
                ([{"i": 0, "ok": True}, {"i": 1, "ok": True}, {"i": 2, "ok": True}], None, "chạy xong → không báo")):
            got.clear()
            engine.run_flow = lambda nav, st, **kw: res
            w_ = {"stop": threading.Event(), "pause": threading.Event(), "group_name": "Efootball", "script_name": "nạp"}
            R._run("iPhoneFarm-01", {"mode": "once", "steps": steps}, w_)
            if expect is None:
                ok(not got, label, got)
            else:
                lines = got[0][2] if got else []
                ok(len(got) == 1 and got[0][0] == expect and got[0][1] == "iPhoneFarm-01" and any("Efootball" in x and "nạp" in x for x in lines)
                   and any(x.startswith("Bước: %d/3" % (res[-1]["i"] + 1)) for x in lines), label, got)
        got.clear()
        engine.run_flow = lambda nav, st, **kw: [{"i": 0, "ok": False, "msg": "x"}]
        w_ = {"stop": threading.Event(), "pause": threading.Event()}
        w_["stop"].set()
        R._run("M", {"mode": "once", "steps": steps}, w_)
        ok(not got, "người vận hành bấm Dừng (bước dở bị ngắt) → không báo lỗi")
    finally:
        engine.run_flow = real
    try:
        got.clear()
        engine.run_flow = lambda nav, st, **kw: [{"i": 0, "ok": False, "msg": "x"}]
        w_ = {"stop": threading.Event(), "pause": threading.Event()}
        R._run("L", {"mode": "loop", "loops": 2, "steps": steps}, w_)
        texts = [g[2][-1] for g in got]
        ok(len(got) == 2 and "vòng 1" in texts[0] and "chạy tiếp vòng sau" in texts[0] and "kịch bản dừng ở bước này" in texts[1],
           "chế độ lặp: vòng lỗi chưa phải vòng cuối → báo «chạy tiếp vòng sau», vòng cuối → «kịch bản dừng»", texts)
        got.clear()
        R._run("E", {"mode": "once", "steps": []}, {"stop": threading.Event(), "pause": threading.Event()})
        ok(got and got[0][0] == "failed" and "chưa có bước" in got[0][2][-1], "kịch bản không có bước nào → báo", got)
        got.clear()
        Rb = runmod.Runner(lambda n: (_ for _ in ()).throw(RuntimeError("Không thấy board 'X' (bấm Quét board)")))
        Rb.alert = R.alert
        Rb._run("X", {"mode": "once", "steps": steps}, {"stop": threading.Event(), "pause": threading.Event()})
        ok(got and got[0][0] == "link" and "không mở được máy" in got[0][2][-1], "không mở được máy vì board → «mất kết nối»", got)
        got.clear()
        engine.run_flow = lambda nav, st, **kw: (_ for _ in ()).throw(RuntimeError("hỏng bất ngờ"))
        R._run("Y", {"mode": "once", "steps": steps}, {"stop": threading.Event(), "pause": threading.Event()})
        ok(got and got[0][0] == "failed" and "hỏng bất ngờ" in got[0][2][-1], "kịch bản ném lỗi bất ngờ → báo", got)
    finally:
        engine.run_flow = real
    got.clear()
    Rg = runmod.Runner(lambda n: object())
    Rg.alert = R.alert
    wg = {"stop": threading.Event(), "pause": threading.Event(), "mode": "api", "group_name": "Nạp"}
    Rg._guard(lambda *a: (_ for _ in ()).throw(RuntimeError("chết giữa chừng")), "G", {}, wg)
    ok(got and got[0][0] == "review" and "chết giữa chừng" in got[0][2][-1], "máy nhận đơn chết vì lỗi bất ngờ → giữ máy + «đối soát»", got)

    class Jr:
        def get(self, name):
            return {"phase": "purchasing", "job": "J1", "ref": "DH-1"}

        def set(self, *a, **k):
            pass

        def record(self, *a, **k):
            pass
    got.clear()
    Rh = runmod.Runner(lambda n: object(), gateway_factory=lambda: object(), journal=Jr())
    Rh.alert = R.alert
    Rh._deliver = lambda *a, **k: True
    wh = {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False, "group_name": "Nạp", "script_name": "đơn"}
    Rh._run_api("H", {"mode": "api", "api": {"pool": "efootball-ios"}}, wh)
    ok(got and got[0][0] == "review" and "DH-1" in got[0][2][-1] and wh.get("hold"),
       "nhận đơn dừng GIỮ máy (đơn bị gián đoạn giữa lúc mua) → «Đơn cần đối soát» qua đúng đường halt(hold=True)", got)
    # Máy nhận đơn đang CHỜ ĐƠN (không chạy bước nào) mất Bluetooth / board → vẫn phải báo (một lần), sẵn sàng lại rồi mất lại → báo lại
    import apimode, boardhealth

    class Hh:
        ser = object()

        def __init__(self, seq):
            self.seq = seq

        def send(self, cmd, wait=0.5):
            m = self.seq[0] if len(self.seq) == 1 else self.seq.pop(0)
            if m == "unplugged":
                raise OSError("[Errno 6] Device not configured")
            return "OK status ble=connected" if m == "ok" else "OK status ble=advertising"

        def wait_connected(self, t):
            return False
        status = lambda self: self.send("status")

    class Ee:
        def screenshot(self):
            return None

    class Nn:
        def __init__(self, seq):
            self.h, self.e = Hh(seq), Ee()

    class GWp:
        def pool(self, code):
            return {"code": code, "rules": []}

        def claim(self, *a, **k):
            return {}
    saved = apimode.effective_steps, apimode.validate, boardhealth.recover, runmod.Runner._ensure_logged_out
    try:
        apimode.effective_steps = lambda pool, st: {"login": [1], "finish": [1]}
        apimode.validate = lambda pool, st: []
        boardhealth.recover = lambda h, log=None: {"ok": True, "actions": [], "health": None}
        for seq, expect, label in ((["bt"], "link", "Bluetooth rớt lúc chờ đơn"), (["unplugged"], "link", "board rút / cổng hỏng lúc chờ đơn")):
            got.clear()
            Ri = runmod.Runner(lambda n, sq=list(seq): Nn(sq), gateway_factory=lambda: GWp())
            Ri.NOT_READY_WAIT = 0.02
            Ri._ensure_logged_out = lambda *a, **k: "stop"                  # sẵn sàng thì dừng vòng ở bước kiểm đăng xuất (không đi tiếp)
            Ri.alert = R.alert
            wi = {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False,
                  "counts": {}, "iter": 0, "group_name": "Nạp", "script_name": "đơn"}
            th = threading.Thread(target=Ri._run_api, args=("W1", {"mode": "api", "api": {"pool": "p", "check_keyboard": False}}, wi), daemon=True)
            th.start(); time.sleep(4.0); wi["stop"].set(); th.join(8)      # mỗi lần kiểm Bluetooth hỏi board 3 lần, nghỉ 0,4 s
            ok(len(got) == 1 and got[0][0] == expect and "chưa sẵn sàng" in got[0][2][-1], label + " → báo «mất kết nối» đúng một lần (dù vẫn chưa sẵn sàng)", got)
        # Ví của máy không đủ tiền (gateway trả wallet_short thay vì đơn) → báo «Ví không đủ tiền» MỘT lần cho mỗi tình trạng
        short = {"reason": "insufficient", "account": "a***@example.com", "currency": "JPY", "available": 1000000, "need": 4800000,
                 "package_codes": ["efb-coin-1050"]}
        seq = [dict(ok=True, job=None, wallet_short=short)] * 3 + [dict(ok=True, job=None)] + [dict(ok=True, job=None, wallet_short=short)] * 2

        class GWw(GWp):
            def claim(self, device, pool, wallet=None):
                return seq.pop(0) if seq else {"ok": True, "job": None}
        got.clear()
        Rw = runmod.Runner(lambda n: Nn(["ok"]), gateway_factory=lambda: GWw())
        Rw.NOT_READY_WAIT = Rw.POLL_IDLE = 0.02
        Rw._ensure_logged_out = lambda *a, **k: "out"
        Rw.alert = R.alert
        ww = {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False,
              "counts": {}, "iter": 0, "group_name": "Nạp", "script_name": "đơn"}
        th = threading.Thread(target=Rw._run_api, args=("W2", {"mode": "api", "api": {"pool": "p", "check_keyboard": False}}, ww), daemon=True)
        th.start(); time.sleep(1.5); st_mid = ww.get("status"); ww["stop"].set(); th.join(8)
        wal = [g for g in got if g[0] == "wallet"]
        ok(len(wal) == 2 and "400.000 JPY" not in wal[0][2][-1] and "10.000 JPY" in wal[0][2][-1] and "48.000 JPY" in wal[0][2][-1]
           and "a***@example.com" in wal[0][2][-1] and "efb-coin-1050" in wal[0][2][-1],
           "ví không đủ tiền → báo «Ví không đủ tiền» một lần (không báo lại mỗi lần xin đơn); hết rồi lại thiếu → báo lại", [g[2][-1] for g in wal])
        ok("Chờ đơn" in (st_mid or ""), "trạng thái máy lúc đó: chờ đơn", st_mid)
        short2 = dict(short, reason="no_price", package_codes=["efb-coin-100"])
        ok("chưa có giá" in runmod.Runner._wallet_why(short2) and "JPY" in runmod.Runner._wallet_why(short2), "gói chưa có giá theo loại tiền của ví → nói rõ")
        ok(notify.money(40000000, "JPY") == "400.000 JPY" and notify.money(80, "CHF") == "0,80 CHF" and notify.money("x", "JPY") == "?",
           "hiển thị tiền (đơn vị ×100): yên không có phần lẻ, CHF có 2 số lẻ")
    finally:
        apimode.effective_steps, apimode.validate, boardhealth.recover, runmod.Runner._ensure_logged_out = saved
    got.clear()
    w_ = {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "group_name": "Nạp", "script_name": "đơn"}
    R2 = runmod.Runner(lambda n: object(), gateway_factory=lambda: None)
    R2.alert = R.alert
    R2._run_api("M7", {"mode": "api", "api": {"pool": ""}}, w_)
    ok(got and got[0][0] == "failed" and "pool" in got[0][2][-1], "nhận đơn dừng vì lỗi cấu hình → «Bước lỗi / kịch bản dừng»", got)
    got.clear()
    R2.workers["M8"] = {"group_name": "Nạp", "script_name": "đơn"}
    R2._alert("M8", "review", "đơn ABC cần đối soát — kiểm tra máy rồi bấm Chạy lại", R2.workers["M8"])
    ok(got and got[0][0] == "review" and any("đối soát" in x for x in got[0][2]), "đơn cần đối soát → «Đơn cần đối soát»", got)
    R2.alert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("telegram hỏng"))
    try:
        R2._alert("M8", "failed", "x")
        ok(True, "bộ gửi thông báo lỗi → không làm hỏng máy đang chạy")
    except Exception as e:
        ok(False, "bộ gửi thông báo lỗi → không làm hỏng máy đang chạy", e)

    print("== 5. gui: hỏi board của máy đang mở; chỉ báo khi XẤU ĐI và giữ đủ số nhịp ==")
    os.environ["IPF_NO_TELEGRAM"] = "1"
    import tempfile, store
    store.DATA_DIR = tempfile.mkdtemp(prefix="notify-data-")     # import gui không được đụng dữ liệu thật
    import gui
    seen = []
    al = lambda n, ev, text, *a, **k: seen.append((n, ev, text))
    seq = {}
    probe = lambda n: seq[n].pop(0) if seq.get(n) else None
    gui._LINK.clear()
    T0 = 1000.0

    def tick(k, **st):
        seq.update({n: [v] for n, v in st.items()})
        gui._link_watch(probe, al, names=list(st), now=T0 + k)
    tick(0, A=(True, True), B=(True, False))
    ok(not seen, "nhịp đầu (trạng thái lúc mở) → không báo, kể cả máy đang chưa nối Bluetooth")
    tick(1, A=(True, False), B=(True, False))
    ok(not seen, "Bluetooth rớt mới 1 nhịp (có thể đang nối lại) → chưa báo", seen)
    tick(2, A=(True, False), B=(True, False))
    ok(seen == [("A", "link", "Bluetooth giữa board ESP32 và iPhone bị rớt")], "rớt 2 nhịp liền → báo đúng một lần", seen)
    seen.clear()
    tick(3, A=(True, False)); tick(4, A=(True, False))
    ok(not seen, "vẫn rớt ở các nhịp sau → không báo lại", seen)
    tick(5, A=(True, True)); tick(6, A=(True, True)); tick(7, A=(False, None)); tick(8, A=(True, True)); tick(9, A=(True, True))
    ok(not seen, "nối lại thì không báo; board im đúng 1 nhịp rồi trả lời lại (chập chờn) → không báo", seen)
    tick(10, A=(False, None)); tick(11, A=(False, None))
    ok(seen and seen[0][:2] == ("A", "link") and "không còn trả lời" in seen[0][2], "board không trả lời 2 nhịp liền (rút cáp / treo) → báo", seen)
    seen.clear()
    gui._LINK.clear()
    tick(20, C=(True, True))
    real_time = gui.time.time
    gui.time.time = lambda: T0 + 20
    try:
        gui._link_quiet(["C"], 60)
    finally:
        gui.time.time = real_time
    tick(21, C=(True, True)); tick(22, C=(True, False)); tick(23, C=(True, False))
    ok(not seen, "người vận hành vừa huỷ Bluetooth / khởi động lại board (_link_quiet) → không báo «mất kết nối»", seen)
    tick(90, C=(True, True)); tick(91, C=(True, True)); tick(92, C=(True, False)); tick(93, C=(True, False))
    ok(seen and seen[0][0] == "C", "hết khoảng im lặng, iPhone đã nối lại rồi rớt thật → vẫn được báo", seen)
    seen.clear()
    seq.clear()
    tick(100, D=None)
    ok(not seen and "D" not in gui._LINK, "máy đang chạy / đang được điều khiển / đang nạp (không hỏi được) → bỏ qua, không đoán")
    gui._LINK.clear()
    gui._LINK["Z"] = {"base": (True, True), "cand": None, "n": 0, "quiet": 0.0}
    saved_sessions = dict(gui.MGR.sessions)
    try:
        gui.MGR.sessions.clear()
        gui._link_watch(probe, al, now=T0)
        ok("Z" not in gui._LINK, "phiên của máy đã đóng (quét lại / nạp firmware) → quên trạng thái cũ, mở lại thì học lại từ đầu")
    finally:
        gui.MGR.sessions.update(saved_sessions)

    class FakeH:
        def __init__(self, reply=None, boom=False):
            self.reply, self.boom, self.port = reply, boom, "COM7"

        def status(self):
            if self.boom:
                raise OSError("could not open port COM7")
            return self.reply

    class FakeNav:
        def __init__(self, h):
            self.h = h
    try:
        for h, expect, label in ((FakeH("OK status ble=connected heap=1"), (True, True), "board trả lời, Bluetooth đã nối"),
                                 (FakeH("OK status ble=advertising"), (True, False), "board trả lời, Bluetooth chưa nối"),
                                 (FakeH(""), (False, None), "board im (không trả lời)"),
                                 (FakeH(boom=True), (False, None), "cổng COM hỏng / đã rút (Windows cũng nhận ra)")):
            gui.MGR.sessions["P"] = FakeNav(h)
            ok(gui._link_probe("P") == expect, "hỏi board: " + label, gui._link_probe("P"))
        gui.MGR.sessions["P"] = FakeNav(FakeH("OK status ble=connected"))
        gui.MAINT.add("COM7")
        ok(gui._link_probe("P") is None, "board đang nạp / quét (MAINT) → không hỏi")
        gui.MAINT.discard("COM7")
        ok(gui._link_probe("NOPE") is None, "máy chưa mở phiên trong tiến trình này → không hỏi (không tranh cổng serial)")
    finally:
        gui.MGR.sessions.pop("P", None)
        gui.MAINT.discard("COM7")
        gui._LINK.clear()
    ok(callable(getattr(gui.Api, "telegram_get", None)) and callable(getattr(gui.Api, "telegram_save", None))
       and gui.RUNNER.alert == gui.TELEGRAM.notify, "app nối bộ chạy với Telegram, có lệnh cài đặt cho giao diện")
    api = gui.Api()
    saved_settings = gui.store.get_settings, gui.store.save_settings
    mem = {}
    try:
        gui.store.get_settings = lambda: dict(mem)
        gui.store.save_settings = lambda patch: mem.update(patch) or dict(mem)
        gui.TELEGRAM._settings = gui.store.get_settings
        r = api.telegram_save("không-phải-mã", "-100123", [])
        ok(r.get("ok") is False and "telegram_token" not in mem, "mã bot sai dạng → không lưu", r)
        r = api.telegram_save(TOKEN, "-100123456", ["paused", "la"])
        ok(r.get("ok") and mem.get("telegram_token") == TOKEN and mem.get("telegram_events") == ["paused"] and TOKEN not in json.dumps(r)
           and mem.get("telegram_events_known") == list(notify.EVENTS),
           "lưu mã bot + chat id + loại sự kiện; lệnh trả về KHÔNG chứa mã bot", r)
        r = api.telegram_save("", "@kenh_admin", None)
        ok(r.get("ok") and mem.get("telegram_token") == TOKEN and mem.get("telegram_chat") == "@kenh_admin", "để trống mã bot = giữ mã cũ", r)
        ok(api.telegram_save(None, "abc", None).get("ok") is False, "chat id sai dạng → không lưu")
        r = api.telegram_chats("khong-phai-ma")
        ok(r["ok"] is False and r["chats"] == [] , "«Tìm chat» với mã bot sai dạng → báo, không gọi Telegram", r)
    finally:
        gui.store.get_settings, gui.store.save_settings = saved_settings
        gui.TELEGRAM._settings = gui.store.get_settings

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
