#!/usr/bin/env python3
"""
Kiểm luồng TOOL TỰ BÁO CHO GATEWAY (presence.py + POST /api/tool/sync) — không cần phần cứng:
  • danh mục kịch bản: mã «nhóm:kịch bản», biến {{…}}, dàn ý KHÔNG kèm chữ gõ / toạ độ / tên app; mã băm ổn định, đổi khi kịch bản đổi;
  • trạng thái máy: chỉ «idle» khi thật sự sẵn sàng — đang giữ / đang dừng / đang chạy / điều khiển tay / thiếu board, iPhone, Bluetooth thì không;
  • máy rảnh Ở KỊCH BẢN NÀO: theo các nhóm máy đang ở (một máy nhiều nhóm);
  • luồng báo: chỉ gửi khi đổi hoặc tới nhịp; danh mục chỉ gửi khi gateway chưa có; lỗi thì lùi (sai khoá lùi hẳn), không ném lỗi ra ngoài;
  • nối vào app: dữ kiện lấy từ store / runner / sổ «ai đang dùng máy»; bản web báo «không nhận đơn»;
  • chạy với Topup Gateway THẬT (php -S trên SQLite tạm) nếu máy có lệnh php.

    ./.venv/bin/python app/tests/test_presence.py
"""
from __future__ import annotations
import json, os, shutil, signal, sqlite3, subprocess, sys, tempfile, time, types, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["IPF_NO_TELEGRAM"] = "1"            # app có thể đã cấu hình Telegram thật: kiểm thử không bao giờ bắn tin
import presence
from gateway import Gateway, GatewayError

GATEWAY_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "Web-topup-gateway")
PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


SECRET_TEXT = "MatKhauGoThang#99"
STEPS = [
    {"type": "launch", "app": "ten-app-rieng", "note": "mở game"},
    {"type": "tap_text", "text": "Đăng nhập"},
    {"type": "type", "text": "{{username}}", "note": "tài khoản"},
    {"type": "key", "name": "tab"},
    {"type": "type", "text": "{{ password }}", "optional": True},
    {"type": "type", "text": SECRET_TEXT},
    {"type": "tap", "x": 123, "y": 987},
    {"type": "tap_text", "text": "{{package.ocr_text}} {{username}}"},
    {"type": "loai la"}, "rac", {"type": "wait", "seconds": 2},
]
GROUPS = [
    {"id": "g1", "name": "Nhóm 1", "mode": "once", "devices": ["M1", "M2"], "scripts": [
        {"id": "nap", "name": "Nạp gói", "mode": "loop", "loops": 3, "steps": STEPS},
        {"id": "rong", "name": "Chưa có bước", "mode": "once", "loops": 1, "steps": []}]},
    {"id": "g2", "name": "Nhóm 2", "mode": "once", "devices": ["M2", "M3"], "scripts": [
        {"id": "k1", "name": "Kịch bản 1", "mode": "once", "loops": 1, "steps": [{"type": "home"}]},
        {"id": "mã có dấu", "name": "bỏ", "steps": [{"type": "home"}]}]},
    {"id": "nhóm sai mã", "name": "bỏ", "mode": "once", "devices": ["M1"], "scripts": [{"id": "y", "name": "bỏ", "steps": []}]},
]
READY = {"board_online": True, "udid": True, "ios_connected": True, "ble": True}


def fact(name, **kw):
    return dict(READY, name=name, **kw)


class FakeGW:
    """Gateway giả: ghi lại mọi lời báo; trả theo kịch bản."""
    def __init__(self):
        self.calls = []
        self.rev = None             # mã băm danh mục «gateway» đang giữ
        self.fail = None            # GatewayError sẽ ném ở lần gọi kế
        self.forget = False         # True: lần gọi kế coi như gateway vừa mất danh mục

    def sync(self, body, timeout=12.0):
        self.calls.append(json.loads(json.dumps(body)))
        if self.fail is not None:
            raise self.fail
        if self.forget:
            self.forget, self.rev = False, None
        if "scripts" in body:
            self.rev = body["scripts_rev"]
        return {"ok": True, "scripts_rev": self.rev, "need_scripts": self.rev != body["scripts_rev"], "devices": len(body["devices"]), "scripts": 0}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def unit_tests():
    print("== 1. Danh mục kịch bản ==")
    rows, rev = presence.catalog(GROUPS)
    by = {r["uid"]: r for r in rows}
    ok(sorted(by) == ["g1:nap", "g1:rong", "g2:k1"], "mọi kịch bản có mã hợp lệ (bỏ nhóm / kịch bản mang mã có ký tự lạ)", sorted(by))
    r = by["g1:nap"]
    ok(r["group"] == "Nhóm 1" and r["name"] == "Nạp gói" and r["mode"] == "loop" and r["loops"] == 3 and r["step_count"] == len(STEPS), "tên, nhóm, cách chạy, số bước", r)
    ok(r["vars"] == ["username", "password", "package.ocr_text"], "biến {{…}} theo thứ tự xuất hiện, không lặp, chịu khoảng trắng", r["vars"])
    ok([s["type"] for s in r["outline"]] == ["launch", "tap_text", "type", "key", "type", "type", "tap", "tap_text", "wait"]
       and r["outline"][0] == {"type": "launch", "note": "mở game", "optional": False} and r["outline"][4]["optional"] is True,
       "dàn ý: loại bước + ghi chú + cờ bỏ qua; bước rác / loại lạ bị bỏ", r["outline"])
    ok(presence.step_vars([{"type": "tap_if", "timeout": 5, "cases": [{"text": "{{otp}}", "tap": "Hủy"}, {"text": "x", "tap": "{{package.name}}"}]}, {"type": "type", "text": "{{otp}}"}]) == ["otp", "package.name"],
       "biến nằm trong các trường hợp của bước «nếu … thì bấm» cũng được tính (không lặp)")
    blob = json.dumps(rows, ensure_ascii=False)
    ok(SECRET_TEXT not in blob and "ten-app-rieng" not in blob and "987" not in blob and "Đăng nhập" not in blob,
       "chữ gõ, tên app, toạ độ, chữ cần bấm KHÔNG nằm trong danh mục gửi đi")
    ok(by["g1:rong"]["step_count"] == 0 and by["g1:rong"]["outline"] == [], "kịch bản chưa có bước vẫn nằm trong danh mục (0 bước)")
    ok(len(rev) == 64 and presence.catalog(list(reversed(GROUPS)))[1] == rev, "mã băm không phụ thuộc thứ tự nhóm", rev)
    g2 = json.loads(json.dumps(GROUPS)); g2[0]["scripts"][0]["steps"].append({"type": "home"})
    g3 = json.loads(json.dumps(GROUPS)); g3[0]["scripts"][0]["name"] = "Tên mới"
    g4 = json.loads(json.dumps(GROUPS)); g4[0]["devices"] = ["M9"]
    g5 = json.loads(json.dumps(GROUPS)); g5[0]["scripts"][0]["steps"][5]["text"] = "ChuKhac"
    ok(presence.catalog(g2)[1] != rev and presence.catalog(g3)[1] != rev, "thêm bước / đổi tên kịch bản → mã băm đổi")
    ok(presence.catalog(g4)[1] == rev and presence.catalog(g5)[1] == rev, "đổi máy trong nhóm / đổi chữ gõ cố định → danh mục không đổi (những thứ đó không nằm trong danh mục)")
    ok(presence.catalog([])[0] == [] and presence.catalog(None)[0] == [] and presence.catalog([{"id": "g", "scripts": "rac"}, "x"])[0] == [], "dữ liệu rác không làm hỏng")
    ok(presence.script_uid("a1b2c3d4", "nap01") == "a1b2c3d4:nap01" and presence.script_uid("", "a") is None and presence.script_uid("a", "b:c") is None
       and presence.script_uid("a" * 41, "b") is None, "mã «nhóm:kịch bản» chỉ nhận ký tự gateway nhận")

    # kịch bản NHẬN ĐƠN: gateway cần biết nó phục vụ pool nào; bước của nó chia theo giai đoạn của một đơn
    go = [{"id": "g7", "name": "Theo đơn", "mode": "once", "devices": ["M1"], "scripts": [
        {"id": "nd", "name": "Nạp theo đơn", "mode": "orders", "steps": [{"type": "type", "text": "KHONG-TINH"}], "loops": 1,
         "orders": {"pool": "efootball-ios", "steps": {"login": [{"type": "launch", "app": "ten-app-rieng"}, {"type": "type", "text": "{{username}}"}],
                                                       "purchase": [{"type": "tap_text", "text": "{{package.ocr_text}}", "optional": True}], "rac": [{"type": "home"}]}}},
        {"id": "th", "name": "Thường", "mode": "once", "steps": [{"type": "home"}], "orders": {"pool": "khong-gui"}}]}]
    ro = {r["uid"]: r for r in presence.catalog(go)[0]}
    ok(ro["g7:nd"]["mode"] == "orders" and ro["g7:nd"]["pool"] == "efootball-ios" and ro["g7:nd"]["step_count"] == 3 and ro["g7:nd"]["vars"] == ["username", "package.ocr_text"]
       and ro["g7:nd"]["outline"] == [{"type": "launch", "note": "", "optional": False, "phase": "login"}, {"type": "type", "note": "", "optional": False, "phase": "login"},
                                      {"type": "tap_text", "note": "", "optional": True, "phase": "purchase"}],
       "kịch bản nhận đơn trong danh mục: cách chạy «orders», pool, số bước = tổng các giai đoạn, dàn ý kèm giai đoạn (không tính bước của cách chạy khác)", ro["g7:nd"])
    ok(ro["g7:th"]["mode"] == "once" and "pool" not in ro["g7:th"] and ro["g7:th"]["step_count"] == 1, "kịch bản thường không khai pool dù còn giữ cấu hình nhận đơn cũ")
    ok("ten-app-rieng" not in json.dumps(list(ro.values()), ensure_ascii=False) and "KHONG-TINH" not in json.dumps(list(ro.values())), "…vẫn không gửi tên app / chữ gõ")
    bo, _ = presence.build([fact("M1", running=True, run_mode="api", run_group_id="g7", run_script_id="nd", run_group="Theo đơn", run_script="Nạp theo đơn", iter=3)], go)
    do = {x["name"]: x for x in bo["devices"]}
    ok(do["M1"]["status"] == "orders" and do["M1"]["running"] == {"group": "Theo đơn", "script": "Nạp theo đơn", "uid": "g7:nd"} and do["M1"]["scripts"] == ["g7:nd", "g7:th"],
       "máy đang nhận đơn bằng một KỊCH BẢN → báo «orders» kèm kịch bản đang chạy (không kèm số vòng)", do["M1"])

    print("== 2. Trạng thái một máy ==")
    S = presence.device_status
    ok(S(dict(READY)) == ("idle", ""), "đủ board + iPhone + Bluetooth, không ai dùng → rảnh")
    ok(S(dict(READY, ble=None))[0] == "offline" and "chưa biết" in S(dict(READY, ble=None))[1], "CHƯA BIẾT trạng thái Bluetooth → không dám báo rảnh")
    ok(S(dict(READY, ble=False))[0] == "offline" and "Bluetooth" in S(dict(READY, ble=False))[1], "Bluetooth chưa nối → chưa sẵn sàng")
    ok(S(dict(READY, ios_connected=False))[0] == "offline" and S(dict(READY, udid=False))[0] == "offline" and S(dict(READY, board_online=False))[0] == "offline",
       "thiếu iPhone / chưa gán iPhone / thiếu board → chưa sẵn sàng")
    ok(S(dict(READY, running=True, run_mode="once"))[0] == "running" and S(dict(READY, running=True, run_mode="loop"))[0] == "running", "đang chạy kịch bản")
    ok(S(dict(READY, running=True, run_mode="api"))[0] == "orders", "đang ở chế độ nhận đơn")
    ok(S(dict(READY, claimed=True))[0] == "manual", "đang được điều khiển tay (thử bước / AI)")
    ok(S(dict(READY, parked=True))[0] == "paused" and S(dict(READY, parked=True, running=True, run_mode="once"))[0] == "paused", "người vận hành bấm Dừng máy (kể cả giữa lúc chạy) → đang dừng")
    ok(S(dict(READY, hold=True, parked=True, running=False))[0] == "hold", "dừng chờ kiểm tra thắng mọi trạng thái khác")
    ok("NG26" not in S(dict(READY, hold="đơn NG261124A002 cần đối soát"))[1], "lý do giữ (có thể chứa mã đơn) không gửi đi — chỉ ghi chú chung")
    ok(S({})[0] == "offline", "không có dữ kiện gì → KHÔNG báo rảnh")

    print("== 3. Máy nào rảnh ở kịch bản nào ==")
    devs = [fact("M2", label="iPhone số 2"), fact("M1", label="M1"),
            fact("M3", running=True, run_mode="loop", run_group_id="g2", run_script_id="k1", run_group="Nhóm 2", run_script="Kịch bản 1", iter=4),
            fact("M4", ios_connected=False), fact("M1", ios_connected=False), {"name": ""},
            fact("M5", running=True, run_mode="api", run_group_id="g9", run_script_id="nd", run_group="Nhóm 9", run_script="Nạp theo đơn", iter=2)]
    body, rows2 = presence.build(devs, GROUPS, {"app": "iphone-farm", "mode": "desktop", "accepting": True})
    d = {x["name"]: x for x in body["devices"]}
    ok([x["name"] for x in body["devices"]] == ["M1", "M2", "M3", "M4", "M5"], "mỗi máy một dòng, xếp theo tên (tên trùng / rỗng bị bỏ)", list(d))
    ok(d["M1"]["scripts"] == ["g1:nap", "g1:rong"] and d["M2"]["scripts"] == ["g1:nap", "g1:rong", "g2:k1"] and d["M3"]["scripts"] == ["g2:k1"] and d["M4"]["scripts"] == [],
       "kịch bản máy chạy được = kịch bản của MỌI nhóm máy đang ở", {k: v["scripts"] for k, v in d.items()})
    ok(d["M1"]["status"] == "idle" and d["M2"]["status"] == "idle" and d["M3"]["status"] == "running" and d["M4"]["status"] == "offline" and d["M5"]["status"] == "orders", "trạng thái từng máy")
    ok(d["M3"]["running"] == {"group": "Nhóm 2", "script": "Kịch bản 1", "uid": "g2:k1", "iter": 4}, "máy đang chạy: nhóm · kịch bản · vòng", d["M3"])
    ok(d["M5"]["running"] == {"group": "Nhóm 9", "script": "Nạp theo đơn", "uid": "g9:nd"} and "running" not in d["M1"],
       "máy đang nhận đơn: kèm kịch bản nhận đơn đang chạy (không kèm số vòng); máy nghỉ không có mục «đang chạy kịch bản»", d["M5"])
    ok(d["M2"]["label"] == "iPhone số 2" and "label" not in d["M1"] and d["M4"]["note"] == "iPhone chưa cắm USB" and "note" not in d["M1"], "nhãn (khi khác tên) và ghi chú (khi có)")
    ok(body["scripts_rev"] == rev and "scripts" not in body and rows2 == rows and body["tool"]["accepting"] is True, "thân lời báo: mã băm danh mục, KHÔNG kèm danh mục")
    ok("udid" not in json.dumps(body).lower() and "port" not in json.dumps(body).lower(), "không có UDID / cổng serial trong lời báo")

    print("== 4. Luồng báo ==")
    gw, clock, world = FakeGW(), Clock(), {"devs": [fact("M1"), fact("M2")], "groups": GROUPS}
    rp = presence.Reporter(lambda: gw, lambda: (world["devs"], world["groups"]), lambda: {"app": "iphone-farm", "mode": "desktop", "accepting": True}, clock=clock)
    ok(rp.state()["ok"] is None and rp.state()["sent"] == 0, "chưa báo lần nào")
    rp.once()
    ok(len(gw.calls) == 1 and "scripts" in gw.calls[0] and len(gw.calls[0]["scripts"]) == 3 and gw.calls[0]["scripts_rev"] == rev, "lần đầu: gửi máy KÈM danh mục", [list(c) for c in gw.calls])
    st = rp.state()
    ok(st["ok"] is True and st["configured"] is True and st["devices"] == 2 and st["idle"] == 2 and st["scripts"] == 3 and st["sent"] == 1 and st["at"], "trạng thái sau khi báo được", st)
    clock.t += 3; rp.once(); clock.t += 3; rp.once()
    ok(len(gw.calls) == 1, "không có gì đổi và chưa tới nhịp → không gửi lại")
    world["devs"] = [fact("M1", running=True, run_mode="once", run_group_id="g1", run_script_id="nap", run_group="Nhóm 1", run_script="Nạp gói"), fact("M2")]
    clock.t += 3; rp.once()
    ok(len(gw.calls) == 2 and "scripts" not in gw.calls[1] and gw.calls[1]["devices"][0]["status"] == "running" and rp.state()["idle"] == 1, "máy bắt đầu chạy → báo NGAY, không kèm danh mục (gateway đã có)", gw.calls[-1])
    clock.t += presence.Reporter.EVERY + 0.1; rp.once()
    ok(len(gw.calls) == 3 and "scripts" not in gw.calls[2], "tới nhịp (~20 giây) → báo lại dù không đổi (để gateway biết tool còn sống)")
    world["groups"] = g3
    clock.t += 3; rp.once()
    ok(len(gw.calls) == 4 and "scripts" in gw.calls[3] and gw.calls[3]["scripts_rev"] != rev, "sửa kịch bản → báo ngay KÈM danh mục mới")
    gw.forget = True
    clock.t += presence.Reporter.EVERY + 0.1; rp.once()
    ok(len(gw.calls) == 6 and "scripts" not in gw.calls[4] and "scripts" in gw.calls[5] and rp.state()["ok"] is True, "gateway mất danh mục (need_scripts) → gửi lại ngay kèm danh mục", [("scripts" in c) for c in gw.calls])

    gw.fail = GatewayError(0, "network", "connection refused")
    clock.t += presence.Reporter.EVERY + 0.1
    try:
        rp.once(); raised = False
    except Exception:
        raised = True
    n = len(gw.calls)
    ok(not raised and rp.state()["ok"] is False and "Không kết nối được" in rp.state()["error"], "gateway không tới được → ghi lỗi, không ném ra ngoài", rp.state())
    clock.t += 5; rp.once(); clock.t += 5; rp.once()
    ok(len(gw.calls) == n, "đang lùi sau lỗi → chưa thử lại ngay")
    gw.fail = None
    clock.t += presence.Reporter.ERROR_WAIT; rp.once()
    ok(len(gw.calls) == n + 1 and "scripts" in gw.calls[-1] and rp.state()["ok"] is True, "hết thời gian lùi → báo lại, kèm danh mục (không chắc gateway còn giữ)")
    gw.fail = GatewayError(401, "unauthorized", "sai khoá")
    clock.t += presence.Reporter.EVERY + 0.1; rp.once(); n = len(gw.calls)
    clock.t += presence.Reporter.ERROR_WAIT + 5; rp.once()
    ok(len(gw.calls) == n and "khoá" in rp.state()["error"], "sai khoá → lùi HẲN (không gõ cửa mỗi 30 giây để khỏi bị gateway chặn IP)", rp.state())
    gw.fail = None
    rp.kick(); rp.once()
    ok(len(gw.calls) == n + 1 and rp.state()["ok"] is True, "«báo ngay» (kick) bỏ qua thời gian lùi")
    n = len(gw.calls)
    for _ in range(5):
        rp.kick(); wait = rp.once()
    ok(len(gw.calls) == n and 0 < wait <= presence.Reporter.MIN_GAP, "bấm «báo ngay» dồn dập → không dội gateway (hai lần gọi cách nhau tối thiểu)", (len(gw.calls) - n, wait))
    clock.t += presence.Reporter.MIN_GAP; rp.once()
    ok(len(gw.calls) == n + 1, "…hết khoảng cách tối thiểu thì lời «báo ngay» được gửi")
    # kịch bản lặp đổi số vòng liên tục: không phải «thay đổi đáng báo ngay»
    loop = lambda it: [fact("M1", running=True, run_mode="loop", run_group_id="g1", run_script_id="nap", run_group="Nhóm 1", run_script="Nạp gói", iter=it), fact("M2")]
    world["devs"] = loop(1); clock.t += presence.Reporter.EVERY + 0.1; rp.once(); n = len(gw.calls)
    for it in range(2, 8):
        world["devs"] = loop(it); clock.t += 3; rp.once()
    ok(len(gw.calls) == n, "máy đang lặp kịch bản: số vòng đổi liên tục KHÔNG làm báo dồn", len(gw.calls) - n)
    clock.t += 3; rp.once()
    ok(len(gw.calls) == n + 1 and gw.calls[-1]["devices"][0]["running"]["iter"] == 7, "…số vòng mới nhất vẫn tới gateway theo nhịp đều (~20 giây)", gw.calls[-1]["devices"][0])
    world["devs"] = [fact("M1"), fact("M2")]; clock.t += 3; rp.once()

    # đang quét board (dữ kiện đang được dựng lại) → bỏ nhịp, không báo bừa; đọc tệp lỗi → không gửi «không còn gì»
    n = len(gw.calls); real_facts = rp._facts
    rp._facts = lambda: None
    clock.t += presence.Reporter.EVERY + 0.1; rp.once()
    ok(len(gw.calls) == n and rp.state()["ok"] is True, "đang quét board (chưa có dữ kiện ổn định) → bỏ nhịp này, giữ lời báo cũ")

    def broken():
        raise ValueError("groups.json hỏng")
    rp._facts = broken
    clock.t += 3
    try:
        rp.once(); raised = False
    except Exception:
        raised = True
    ok(not raised and len(gw.calls) == n and rp.state()["ok"] is False and "groups.json hỏng" in rp.state()["error"], "không đọc được tệp máy / nhóm → KHÔNG gửi gì (không báo «hết máy / hết kịch bản»), ghi lỗi", rp.state())
    rp._facts = real_facts
    clock.t += presence.Reporter.ERROR_WAIT + 0.1; rp.once()
    ok(len(gw.calls) == n + 1 and rp.state()["ok"] is True, "đọc lại được → báo tiếp")

    # «báo ngay» tới GIỮA lúc một lần gọi đang lỗi (vd vừa sửa khoá) không bị lần lỗi đó nuốt mất
    class KickDuring(FakeGW):
        def sync(self, body, timeout=12.0):
            self.calls.append(body)
            if len(self.calls) == 1:
                rk.kick()
                raise GatewayError(401, "unauthorized", "sai khoá")
            return {"ok": True, "scripts_rev": body["scripts_rev"], "need_scripts": False}
    kg = KickDuring()
    rk = presence.Reporter(lambda: kg, lambda: (world["devs"], world["groups"]), clock=clock)
    rk.once(); clock.t += presence.Reporter.MIN_GAP; rk.once()
    ok(len(kg.calls) == 2 and rk.state()["ok"] is True, "«báo ngay» giữa lúc đang gọi lỗi → nhịp sau thử lại luôn (không nằm im 5 phút)", (len(kg.calls), rk.state()))

    # tiến trình không được phép báo (tiến trình khác của app đang báo)
    rd = presence.Reporter(lambda: gw, lambda: (world["devs"], world["groups"]), clock=clock)
    rd.disable("tiến trình khác đang báo"); n = len(gw.calls)
    rd.start(); rd.kick(); rd.once()
    ok(len(gw.calls) == n and rd._thread is None and rd.state()["ok"] is False and "tiến trình khác" in rd.state()["error"], "disable(): không chạy luồng, không gửi gì, nói rõ lý do", rd.state())

    # trần của gateway: tool tự cắt cho vừa thay vì gửi rồi bị từ chối mãi
    big = [{"id": "g", "name": "G", "mode": "once", "devices": ["M%d" % i for i in range(260)],
            "scripts": [{"id": "s%d" % i, "name": "S", "steps": [{"type": "tap_text", "text": "x", "note": "n" * 120}] * 80} for i in range(330)]}]
    bb, brows = presence.build([fact("M%d" % i) for i in range(260)], big)
    size = len(json.dumps(dict(bb, scripts=brows), ensure_ascii=False).encode("utf-8"))
    ok(len(bb["devices"]) == presence.MAX_DEVICES and len(brows) == presence.MAX_SCRIPTS and all(r["outline"] == [] and r["step_count"] == 80 for r in brows),
       "quá trần: cắt còn 200 máy / 300 kịch bản; danh mục quá lớn thì bỏ dàn ý (vẫn còn tên, số bước, biến)", (len(bb["devices"]), len(brows), size))
    rb = presence.Reporter(lambda: gw, lambda: ([fact("M%d" % i) for i in range(260)], big), clock=clock)
    n = len(gw.calls); rb.once()
    ok((size <= presence.MAX_BODY_BYTES and len(gw.calls) == n + 1) or (size > presence.MAX_BODY_BYTES and len(gw.calls) == n and "quá lớn" in rb.state()["error"]),
       "lời báo vừa trần thì gửi; vẫn quá 1 MB thì KHÔNG gửi (và lùi hẳn) thay vì bị từ chối mỗi 30 giây", (size, rb.state()))
    ok(presence.script_uid("g1", "nap\n") is None and presence.outline([{"type": "launch\n"}]) == [] and presence.step_vars([{"text": "{{a}}"}]) == ["a"], "mã / loại bước có dấu xuống dòng thừa không được nhận")

    gw.fail = GatewayError(404, "not_found", "Không có API này.")
    clock.t += presence.Reporter.EVERY + 0.1; rp.once()
    ok("bản cũ" in rp.state()["error"], "gateway bản cũ chưa có API sync → nói rõ cần cập nhật gateway", rp.state()["error"])

    def no_gw():
        raise GatewayError(0, "not_configured", "Chưa cấu hình địa chỉ / khoá gateway")
    rp2 = presence.Reporter(no_gw, lambda: (world["devs"], world["groups"]), clock=clock)
    wait = rp2.once()
    ok(rp2.state()["configured"] is False and rp2.state()["ok"] is None and wait == presence.Reporter.IDLE_WAIT, "chưa cấu hình gateway → nằm im, không báo lỗi", rp2.state())

    class Stuck(FakeGW):
        def sync(self, body, timeout=12.0):
            super().sync(body, timeout)
            return {"ok": True, "scripts_rev": None, "need_scripts": True}
    sg = Stuck()
    rp3 = presence.Reporter(lambda: sg, lambda: (world["devs"], world["groups"]), clock=clock)
    rp3.once()
    ok(len(sg.calls) == 2 and rp3.state()["ok"] is False and rp3.state()["sent"] == 0, "gateway mãi không nhận danh mục → không tự coi là đã báo xong, không gửi dồn dập", rp3.state())

    def boom():
        raise RuntimeError("đọc tệp nhóm lỗi")
    rp4 = presence.Reporter(lambda: gw, boom, clock=clock)
    rp4.TICK = rp4.ERROR_WAIT = 0.05
    rp4.start(); time.sleep(0.3); alive = rp4._thread.is_alive(); rp4.stop(); rp4._thread.join(2)
    ok(alive and "đọc tệp nhóm lỗi" in rp4.state()["error"] and not rp4._thread.is_alive(), "lỗi bất ngờ khi gom dữ kiện → luồng vẫn sống, ghi lỗi; stop() thì dừng", rp4.state())


def wiring_tests():
    print("== 5. Nối vào app ==")
    import gui, store, history
    gui.HISTORY = gui.RUNNER.history = history.History(None)      # không ghi lịch sử vào dữ liệu THẬT
    saved = (store.get_devices_strict, store.get_groups_strict, dict(gui.MGR.board_map), dict(gui.MGR.ble_map), gui.RUNNER.status, gui.ios.list_connected,
             gui.WEBDEV, gui.RUNNER.allow_api, set(gui.RUNNER.parked), gui.RUNNER.hold_reason, dict(gui._IOS_SEEN), gui.PRESENCE,
             gui.RUNNER.journal, gui.RUNNER.conflict, store.DATA_DIR, gui._PRESENCE_LOCK, gui._start_presence, gui.webview, gui.control.AppServer,
             store.get_settings, gui.WINDOW, gui.CONTROL)
    tmp = tempfile.mkdtemp(prefix="presence-port-")
    port1, port2 = os.path.join(tmp, "cu.usbserial-1"), os.path.join(tmp, "cu.usbserial-2")
    open(port1, "w").close()                                  # cổng của M1 còn đó; cổng của M2 đã «rút»
    calls = {"usbmux": 0}

    def fake_list():
        calls["usbmux"] += 1
        return [{"udid": "00008030-AAAA", "connection": "USB"}, {"udid": "bbbb"}, {"udid": "eeee", "connection": "Network"}]

    class FakeJournal:
        state = {}

        def get(self, name):
            return self.state.get(name)
    try:
        store.get_devices_strict = lambda: [{"name": "M1", "udid": "00008030aaaa", "label": "iPhone số 1"}, {"name": "M2", "udid": "BBBB"},
                                            {"name": "M3", "udid": "cccc"}, {"name": "M4", "udid": None}, {"name": "M5", "udid": "EEEE"}]
        store.get_groups_strict = lambda: GROUPS
        gui.RUNNER.journal = FakeJournal()
        gui.MGR.board_map.clear(); gui.MGR.board_map.update({"M1": port1, "M2": port2, "M3": port1, "M4": port1, "M5": port1, "M9": port1})
        gui.MGR.ble_map.clear(); gui.MGR.ble_map.update({"M1": True})
        gui.RUNNER.status = lambda: {"M3": {"running": True, "mode": "loop", "group_id": "g2", "script_id": "k1", "group_name": "Nhóm 2", "script_name": "Kịch bản 1", "iter": 2}}
        gui.RUNNER.hold_reason = lambda name: "đơn NG1 cần đối soát" if name == "M4" else None
        gui.RUNNER.parked.clear()
        gui.ios.list_connected = fake_list
        gui._IOS_SEEN.update(at=None, udids=None)
        facts, groups = gui._presence_facts()
        f = {x["name"]: x for x in facts}
        ok(sorted(f) == ["M1", "M2", "M3", "M4", "M5", "M9"] and groups is GROUPS, "gom mọi máy đã lưu + board lạ đang cắm", sorted(f))
        ok(f["M5"]["ios_connected"] is False, "iPhone chỉ thấy qua Wi-Fi (không cắm USB) → không tính là đang cắm", f["M5"])
        ok(f["M1"]["board_online"] and f["M1"]["ios_connected"] and f["M1"]["udid"] is True and f["M1"]["ble"] is True and f["M1"]["label"] == "iPhone số 1",
           "máy đủ điều kiện: board còn cổng, iPhone đang cắm (so UDID không phân biệt gạch / hoa thường)", f["M1"])
        ok(f["M2"]["board_online"] is False and f["M2"]["ios_connected"] is True, "board đã rút dây (tệp cổng biến mất) → không còn tính là có board, dù chưa quét lại", f["M2"])
        ok(f["M3"]["ios_connected"] is False and f["M3"]["running"] and f["M3"]["run_group_id"] == "g2" and f["M3"]["run_script_id"] == "k1" and f["M3"]["iter"] == 2, "iPhone không cắm; đang chạy nhóm · kịch bản nào", f["M3"])
        ok(f["M4"]["hold"] is True and f["M4"]["udid"] is False and f["M9"]["udid"] is False, "máy đang giữ chỉ gửi cờ (không gửi lý do); máy chưa gán iPhone", f["M4"])
        ok("NG1" not in json.dumps(facts, ensure_ascii=False) and "00008030" not in json.dumps(facts) and "usbserial" not in json.dumps(facts), "dữ kiện không mang UDID / cổng / lý do giữ")
        gui._presence_facts(); gui._presence_facts()
        ok(calls["usbmux"] == 1, "hỏi usbmux được nhớ tạm (không mở tiến trình con mỗi nhịp soát)", calls)
        body, _ = presence.build(facts, groups, gui._presence_tool())
        d = {x["name"]: x for x in body["devices"]}
        ok(d["M1"]["status"] == "idle" and d["M2"]["status"] == "offline" and d["M3"]["status"] == "running" and d["M4"]["status"] == "hold" and d["M9"]["status"] == "offline", "trạng thái ghép từ dữ kiện thật của app", {k: v["status"] for k, v in d.items()})
        st = lambda name: {x["name"]: x for x in presence.build(gui._presence_facts()[0], groups)[0]["devices"]}[name]["status"]

        # tên khác của CÙNG iPhone / board với một máy của khách (bộ chạy xét theo máy thật) → tên đó cũng không rảnh
        real_conflict = gui.RUNNER.conflict
        gui.RUNNER.conflict = lambda name, udid=None, port=None: "M4" if name == "M1" else None
        ok(st("M1") == "hold", "M1 trỏ vào cùng máy thật với M4 đang DỪNG CHỜ KIỂM TRA → M1 cũng báo «hold», không báo rảnh", st("M1"))
        gui.RUNNER.conflict = lambda name, udid=None, port=None: "M3" if name == "M1" else None
        ok(st("M1") == "orders", "M1 trỏ vào cùng máy thật với một máy đang làm đơn của khách → báo «orders», không báo rảnh", st("M1"))
        gui.RUNNER.conflict = real_conflict

        # app vừa khởi động lại: «dừng chờ kiểm tra» trong bộ nhớ đã mất, nhưng SỔ còn ghi máy có đơn dở
        gui.RUNNER.journal.state = {"M1": {"job": "J1", "ref": "NG1", "phase": "purchasing", "delivered": False}}
        ok(st("M1") == "hold", "sổ còn ghi máy có ĐƠN DỞ chưa báo xong → không báo rảnh (kể cả sau khi app khởi động lại)", st("M1"))
        gui.RUNNER.journal.state = {"M1": {"job": "J1", "ref": "NG1", "phase": "finished", "delivered": True}}
        ok(st("M1") == "idle", "đơn trong sổ đã báo xong → máy lại rảnh")

        # sổ đơn THẬT (jobflow.Journal): tệp hỏng phải bị coi là «không biết» → không báo rảnh; tệp chưa có = chưa từng có đơn
        import jobflow
        jdir = tempfile.mkdtemp(prefix="presence-journal-")
        try:
            gui.RUNNER.journal = jobflow.Journal(jdir)
            ok(st("M1") == "idle", "sổ đơn chưa có tệp (chưa từng nhận đơn) → máy rảnh bình thường")
            gui.RUNNER.journal.set("M1", job="J9", ref="NG9", phase="claimed", delivered=False)
            ok(st("M1") == "hold", "sổ thật ghi máy đang giữ một đơn chưa báo xong → không rảnh")
            open(os.path.join(jdir, "api_state.json"), "w").write('{"M1": {"job": "J9", "deliv')          # tệp ghi dở / hỏng
            ok(gui.RUNNER.journal.get("M1") is None and st("M1") == "hold", "sổ đơn HỎNG: đọc thường trả «không có gì», nhưng luồng tự báo đọc chặt → không dám báo rảnh", st("M1"))
            open(os.path.join(jdir, "api_state.json"), "w").write('["khong", "phai", "so"]')
            ok(st("M1") == "hold", "sổ đơn sai dạng → cũng không báo rảnh")
        finally:
            shutil.rmtree(jdir, ignore_errors=True)
        gui.RUNNER.journal = FakeJournal(); FakeJournal.state = {}

        # Bluetooth: trạng thái vừa đọc được từ board được ghi lại ngay (không chờ lượt quét sau)
        gui._note_ble("M1", "OK ble=disconnected adv=1 heap=1000")
        ok(gui.MGR.ble_map["M1"] is False and st("M1") == "offline", "vừa đọc thấy Bluetooth rớt (vd bấm «Huỷ kết nối BT») → máy hết được báo là rảnh")
        gui._note_ble("M1", "chuỗi lạ không có thông tin")
        ok(gui.MGR.ble_map["M1"] is False, "chuỗi trạng thái không nói gì về Bluetooth → giữ nguyên điều đã biết")
        gui._note_ble("M1", "OK ble=connected heap=1000")
        ok(gui.MGR.ble_map["M1"] is True and st("M1") == "idle", "đọc thấy đã nối lại → rảnh lại")
        gui.MGR.ble_map.pop("M1")
        ok(st("M1") == "offline", "chưa đọc được Bluetooth lần nào → không báo rảnh")
        gui.MGR.ble_map["M1"] = True

        # bảo trì: đang nạp firmware lên cổng của máy / đang dò máy → không rảnh
        with gui._Maint(port1):
            ok(st("M1") == "manual", "đang nạp / xoá firmware trên cổng của máy → không báo rảnh")
        with gui._Maint("*"):
            ok(st("M1") == "manual", "đang dò máy (rung chuột + chụp mọi iPhone) → không máy nào báo rảnh")
        ok(st("M1") == "idle" and not gui.MAINT, "xong bảo trì → rảnh lại")

        # đang quét board: bảng board / Bluetooth đang được dựng lại → chưa có dữ kiện ổn định
        gui.MGR.scan_idle.clear()
        ok(gui._presence_facts() is None, "đang quét board → chưa trả dữ kiện (luồng báo bỏ nhịp này, không báo «board chưa cắm» oan)")
        gui.MGR.scan_idle.set()

        # tệp máy / nhóm đọc lỗi → NÉM LỖI, không coi là «không còn máy / kịch bản nào»
        tmpd = tempfile.mkdtemp(prefix="presence-store-")
        real_files = (store.DATA_DIR, store.DEVICES_FILE, store.GROUPS_FILE)
        try:
            store.DATA_DIR = tmpd
            store.DEVICES_FILE, store.GROUPS_FILE = (os.path.join(tmpd, n) for n in ("devices.json", "groups.json"))
            open(store.GROUPS_FILE, "w").write('[{"id": "g1", "name": "N", "scripts": [{"id": "s", "name": "S", "steps": []}], "devices": []}')   # ghi dở
            open(store.DEVICES_FILE, "w").write("[]")
            try:
                saved[1](); strict = "khong nem"
            except ValueError:
                strict = "nem"
            ok(strict == "nem" and store.get_groups() == [] and saved[0]() == [], "tệp nhóm hỏng: bản đọc thường trả [] nhưng bản đọc CHẶT ném lỗi; tệp máy rỗng thật thì trả []", strict)
            open(store.GROUPS_FILE, "w").write('{"khong": "phai danh sach"}')
            try:
                saved[1](); strict = "khong nem"
            except ValueError:
                strict = "nem"
            ok(strict == "nem", "tệp nhóm không phải một danh sách → cũng ném lỗi")
        finally:
            store.DATA_DIR, store.DEVICES_FILE, store.GROUPS_FILE = real_files
            shutil.rmtree(tmpd, ignore_errors=True)
        gui.RUNNER.parked.add("M1")
        ok(presence.build(gui._presence_facts()[0], groups)[0]["devices"][0]["status"] == "paused", "bấm «Dừng máy» → máy không còn báo rảnh")
        gui.RUNNER.parked.clear()
        gui.CLAIMS.acquire("M1", "ui")
        try:
            ok(presence.build(gui._presence_facts()[0], groups)[0]["devices"][0]["status"] == "manual", "đang thử bước trên giao diện → điều khiển tay")
        finally:
            gui.CLAIMS.release("M1", "ui")

        gui.WEBDEV, gui.RUNNER.allow_api = None, True
        ok(gui._presence_tool() == {"app": "iphone-farm", "mode": "desktop", "accepting": True}, "app cửa sổ: đang nhận đơn")
        gui.WEBDEV, gui.RUNNER.allow_api = object(), False
        ok(gui._presence_tool() == {"app": "iphone-farm", "mode": "web", "accepting": False}, "bản web dev: báo rõ KHÔNG nhận đơn của khách")
        ok("gateway_sync" in gui.WEB_SAFE_WITH_CUSTOMERS and gui._web_gate("gateway_sync") is None, "bản web xem được trạng thái tự báo")

        gw = FakeGW()
        gui.PRESENCE = presence.Reporter(lambda: gw, gui._presence_facts, gui._presence_tool)
        api = gui.Api()
        ok(api.gateway_sync()["ok"] is None, "Api.gateway_sync: chưa báo lần nào")
        gui.PRESENCE.once()
        st = api.gateway_sync()
        ok(st["ok"] is True and st["devices"] == 6 and st["idle"] == 1 and st["scripts"] == 3 and gw.calls[0]["tool"]["accepting"] is False, "Api.gateway_sync trả trạng thái lần báo gần nhất", st)
        gui.PRESENCE._not_before = gui.PRESENCE._clock() + 999
        api.gateway_sync(True)
        ok(gui.PRESENCE._not_before == 0.0 and gui.PRESENCE._wake.is_set(), "Api.gateway_sync(now=True) → báo ngay")
        # mỗi bản cài chỉ MỘT tiến trình được báo (app cửa sổ + bản web chạy cùng lúc dùng chung khoá Tool)
        import fcntl
        lockdir = tempfile.mkdtemp(prefix="presence-lock-")
        store.DATA_DIR = lockdir
        started = []
        mk = lambda: types.SimpleNamespace(start=lambda: started.append("start"), disable=lambda why: started.append("disable: " + why), kick=lambda: None, state=lambda: {})
        try:
            other = open(os.path.join(lockdir, "presence.lock"), "a+")      # «tiến trình khác» đang giữ khoá
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            gui.PRESENCE, gui._PRESENCE_LOCK = mk(), None
            r1 = gui._start_presence()
            ok(r1 is False and len(started) == 1 and started[0].startswith("disable: ") and gui._PRESENCE_LOCK is None, "tiến trình khác của app đang báo → tiến trình này KHÔNG báo, nói rõ lý do", started)
            fcntl.flock(other.fileno(), fcntl.LOCK_UN); other.close()
            started.clear()
            r2 = gui._start_presence()
            ok(r2 is True and started == ["start"] and gui._PRESENCE_LOCK is not None, "không ai giữ khoá → tiến trình này báo và giữ khoá", started)
            again = open(os.path.join(lockdir, "presence.lock"), "a+")
            try:
                fcntl.flock(again.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); held = False
            except OSError:
                held = True
            again.close()
            ok(held, "…khoá được giữ thật (tiến trình thứ hai không lấy được)")
        finally:
            if gui._PRESENCE_LOCK is not None:
                gui._PRESENCE_LOCK.close()
            gui._PRESENCE_LOCK = None

        # main() của app CỬA SỔ chạy luồng tự báo trước khi mở cửa sổ (bản web: kiểm ở test_webdev)
        order = []
        gui._start_presence = lambda: order.append("tự báo")
        gui.webview = types.SimpleNamespace(create_window=lambda *a, **k: order.append("tạo cửa sổ") or "CỬA SỔ", start=lambda: order.append("chạy cửa sổ"))
        gui.control.AppServer = lambda *a, **k: types.SimpleNamespace(start=lambda p: True, stop=lambda: None, token="")
        store.get_settings = lambda: {"ai_enabled": False}
        gui.WEBDEV, gui.RUNNER.allow_api = None, True
        gui.main([])
        ok(order == ["tự báo", "tạo cửa sổ", "chạy cửa sổ"] and gui.RUNNER.allow_api is True, "app cửa sổ: main() chạy luồng tự báo gateway, vẫn nhận đơn", order)
        src = open(os.path.join(os.path.dirname(HERE), "gui.py"), encoding="utf-8").read()
        ok("PRESENCE.kick()" in src.split("def gateway_save")[1].split("def gateway_sync")[0], "lưu cấu hình gateway xong thì báo ngay theo cấu hình mới")
    finally:
        (store.get_devices_strict, store.get_groups_strict) = saved[0], saved[1]
        gui.RUNNER.journal, gui.RUNNER.conflict, store.DATA_DIR, gui._PRESENCE_LOCK, gui._start_presence = saved[12], saved[13], saved[14], saved[15], saved[16]
        gui.webview, gui.control.AppServer, store.get_settings, gui.WINDOW, gui.CONTROL = saved[17], saved[18], saved[19], saved[20], saved[21]
        gui.MAINT.clear(); gui.MGR.scan_idle.set()
        gui.MGR.board_map.clear(); gui.MGR.board_map.update(saved[2])
        gui.MGR.ble_map.clear(); gui.MGR.ble_map.update(saved[3])
        gui.RUNNER.status, gui.ios.list_connected, gui.WEBDEV, gui.RUNNER.allow_api = saved[4], saved[5], saved[6], saved[7]
        gui.RUNNER.parked.clear(); gui.RUNNER.parked.update(saved[8])
        gui.RUNNER.hold_reason = saved[9]
        gui._IOS_SEEN.clear(); gui._IOS_SEEN.update(saved[10])
        gui.PRESENCE = saved[11]
        shutil.rmtree(tmp, ignore_errors=True)


FIXTURE = r'''<?php
require getenv("GW_DIR") . "/src/bootstrap.php";
Schema::migrate();
$tool = Keys::create("tool", "Farm test");
echo json_encode(["tool" => $tool["plain"], "id" => $tool["id"]]);
'''


def real_gateway_tests():
    print("== 6. Với Topup Gateway THẬT ==")
    if not os.path.isdir(GATEWAY_DIR) or shutil.which("php") is None:
        print("  (bỏ qua: cần thư mục Web-topup-gateway và lệnh php)")
        return
    tmp = tempfile.mkdtemp(prefix="gw-presence-")
    port = 19900 + (os.getpid() % 90)
    url = "http://127.0.0.1:%d" % port
    db = os.path.join(tmp, "gw.sqlite")
    os.makedirs(os.path.join(tmp, "files"))
    env = dict(os.environ, GW_DIR=GATEWAY_DIR, APP_KEY="test-key-0123456789abcdef", APP_URL=url, APP_DEBUG="true",
               DB_DSN="sqlite:" + db, STORAGE_DIR=os.path.join(tmp, "files"), PHP_CLI_SERVER_WORKERS="4")
    fx = os.path.join(tmp, "fixture.php")
    open(fx, "w", encoding="utf-8").write(FIXTURE)
    r = subprocess.run(["php", fx], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        ok(False, "dựng gateway tạm", r.stderr + r.stdout)
        return
    key = json.loads(r.stdout)
    log = open(os.path.join(tmp, "server.log"), "w")
    proc = subprocess.Popen(["php", "-S", "127.0.0.1:%d" % port, "-t", os.path.join(GATEWAY_DIR, "public"), os.path.join(GATEWAY_DIR, "public", "index.php")],
                            env=env, stdout=log, stderr=log, cwd=GATEWAY_DIR, start_new_session=True)

    def sql(q, args=()):
        con = sqlite3.connect(db, timeout=5)
        try:
            rows = con.execute(q, args).fetchall()
            con.commit()
            return rows
        finally:
            con.close()
    try:
        up = False
        for _ in range(100):
            try:
                with urllib.request.urlopen(url + "/healthz", timeout=1) as resp:
                    up = json.loads(resp.read()).get("ok") is True
                if up:
                    break
            except Exception:
                time.sleep(0.1)
        ok(up, "gateway tạm lên")
        if not up:
            return
        sent = []

        class Spy(Gateway):
            def sync(self, body, timeout=12.0):
                sent.append(body)
                return super().sync(body, timeout)
        clock, world = Clock(), {"devs": [fact("M1", label="iPhone số 1"), fact("M2"), fact("M3", ios_connected=False)], "groups": GROUPS}
        rp = presence.Reporter(lambda: Spy(url, key["tool"]), lambda: (world["devs"], world["groups"]),
                               lambda: {"app": "iphone-farm", "mode": "web", "accepting": False}, clock=clock)
        rp.once()
        st = rp.state()
        ok(st["ok"] is True and st["devices"] == 3 and st["idle"] == 2 and st["scripts"] == 3 and len(sent) == 1, "lời báo đầu được gateway thật nhận", st)
        rows = sql("SELECT uid, name, group_name, run_mode, loops, step_count, vars, outline FROM tool_scripts ORDER BY uid")
        ok([x[0] for x in rows] == ["g1:nap", "g1:rong", "g2:k1"] and rows[0][1:6] == ("Nạp gói", "Nhóm 1", "loop", 3, len(STEPS))
           and json.loads(rows[0][6]) == ["username", "password", "package.ocr_text"] and len(json.loads(rows[0][7])) == 9, "gateway nạp đúng danh mục kịch bản của tool", rows)
        dump = json.dumps(sql("SELECT * FROM tool_scripts") + sql("SELECT * FROM devices"), ensure_ascii=False, default=str)
        ok(SECRET_TEXT not in dump and "ten-app-rieng" not in dump, "CSDL của gateway không có chữ gõ / tên app của kịch bản")
        devs = {x[0]: x for x in sql("SELECT name, status, status_note, scripts, label FROM devices")}
        ok(devs["M1"][1] == "idle" and json.loads(devs["M1"][3]) == ["g1:nap", "g1:rong"] and devs["M1"][4] == "iPhone số 1"
           and devs["M2"][1] == "idle" and json.loads(devs["M2"][3]) == ["g1:nap", "g1:rong", "g2:k1"]
           and devs["M3"][1] == "offline" and devs["M3"][2] == "iPhone chưa cắm USB", "gateway biết máy nào rảnh ở kịch bản nào", devs)
        info = json.loads(sql("SELECT tool_info FROM api_keys WHERE id=?", (key["id"],))[0][0])
        ok(info["mode"] == "web" and info["accepting"] is False and info["scripts_rev"] == sent[0]["scripts_rev"], "gateway ghi nhận tool bản web không nhận đơn", info)

        clock.t += 3; rp.once()
        ok(len(sent) == 1, "không đổi → không gửi")
        world["devs"][0] = fact("M1", label="iPhone số 1", running=True, run_mode="once", run_group_id="g1", run_script_id="nap", run_group="Nhóm 1", run_script="Nạp gói", iter=1)
        clock.t += 3; rp.once()
        row = sql("SELECT status, running FROM devices WHERE name='M1'")[0]
        ok(len(sent) == 2 and "scripts" not in sent[1] and row[0] == "running" and json.loads(row[1])["uid"] == "g1:nap", "máy bắt đầu chạy → gateway thấy ngay đang chạy kịch bản nào", row)
        world["devs"] = world["devs"][:2]
        clock.t += 3; rp.once()
        ok(sql("SELECT COUNT(*) FROM devices WHERE name='M3'")[0][0] == 0 and sql("SELECT COUNT(*) FROM devices")[0][0] == 2, "máy bị gỡ khỏi tool → gateway bỏ máy đó")

        sql("UPDATE api_keys SET tool_info=NULL"); sql("DELETE FROM tool_scripts")          # gateway «mất» danh mục
        clock.t += presence.Reporter.EVERY + 0.1; rp.once()
        ok("scripts" not in sent[-2] and "scripts" in sent[-1] and sql("SELECT COUNT(*) FROM tool_scripts")[0][0] == 3 and rp.state()["ok"] is True,
           "gateway mất danh mục → đòi lại (need_scripts) và tool gửi ngay", [("scripts" in b) for b in sent])

        bad = presence.Reporter(lambda: Gateway(url, "gwt_khoa_sai_hoan_toan"), lambda: (world["devs"], world["groups"]), clock=clock)
        bad.once()
        ok(bad.state()["ok"] is False and "khoá" in bad.state()["error"] and bad._not_before - clock.t == presence.Reporter.AUTH_WAIT, "khoá sai → gateway từ chối, tool lùi hẳn", bad.state())
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(5)
        except Exception:
            pass
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    unit_tests()
    wiring_tests()
    real_gateway_tests()
    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
