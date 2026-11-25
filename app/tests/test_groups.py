#!/usr/bin/env python3
"""
Kiểm danh sách kịch bản của nhóm + một máy ở nhiều nhóm + một máy một kịch bản một lúc (store / runner) — không cần phần cứng:
  • nhóm CŨ (chỉ có `steps`) tự thành «Kịch bản 1» (id k1) mang cách chạy cũ; nhóm không còn `steps` / `active_script`;
  • MỖI kịch bản có cách chạy riêng (mode once/loop + loops); dữ liệu rác được chuẩn hoá;
  • khoá `scripts` có mặt (kể cả rỗng) là chuẩn — xoá hết kịch bản thì không sống lại từ `steps` cũ;
  • pick_script: theo id hoặc tên; không nêu thì chỉ khi nhóm có đúng 1 kịch bản;
  • một máy ở NHIỀU nhóm; đổi tên máy giữ đủ nhóm;
  • runner: máy chạy kịch bản theo cách chạy của kịch bản, hiện «nhóm · kịch bản»; một máy KHÔNG chạy được 2 kịch bản một lúc;
    dừng nhóm / kịch bản này không đụng việc của nhóm / kịch bản khác.

    ./.venv/bin/python app/tests/test_groups.py
"""
from __future__ import annotations
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import store

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def main():
    tmp = tempfile.mkdtemp(prefix="groups-")
    old = (store.DATA_DIR, store.GROUPS_FILE, store.DEVICES_FILE, store.FLOWS_FILE)
    store.DATA_DIR = tmp
    store.GROUPS_FILE = os.path.join(tmp, "groups.json")
    store.DEVICES_FILE = os.path.join(tmp, "devices.json")
    store.FLOWS_FILE = os.path.join(tmp, "flows.json")
    try:
        home = {"type": "home"}
        tap = {"type": "tap_text", "text": "Đăng nhập"}

        print("== 1. Nhóm cũ ==")
        json.dump([{"id": "old1", "name": "Cũ", "mode": "loop", "loops": 0, "devices": [], "steps": [home, tap]}], open(store.GROUPS_FILE, "w"))
        g = store.get_group("old1")
        sc = g["scripts"][0]
        ok([s["id"] for s in g["scripts"]] == ["k1"] and sc["name"] == "Kịch bản 1" and sc["steps"] == [home, tap], "nhóm cũ → 1 kịch bản «Kịch bản 1» chứa các bước cũ", g.get("scripts"))
        ok(sc["mode"] == "loop" and sc["loops"] == 0, "…mang theo cách chạy cũ của nhóm (lặp vô hạn)", sc)
        ok("steps" not in g and "active_script" not in g, "nhóm không còn `steps` / `active_script` (cách chạy nằm trong kịch bản)")
        json.dump([{"id": "old2", "name": "Trống", "mode": "once", "devices": [], "steps": []}], open(store.GROUPS_FILE, "w"))
        ok(store.get_group("old2")["scripts"] == [], "nhóm cũ không có bước → không có kịch bản nào")

        print("\n== 2. Lưu nhiều kịch bản, mỗi kịch bản một cách chạy ==")
        g = store.save_group({"name": "Mới", "mode": "once", "scripts": [
            {"id": "a", "name": "A", "steps": [home]},
            {"id": "b", "name": "B", "steps": [tap, home], "mode": "loop", "loops": 5}], "devices": []})
        ok([(s["id"], s["mode"], s["loops"]) for s in g["scripts"]] == [("a", "once", 1), ("b", "loop", 5)], "kịch bản không nói cách chạy → chạy 1 lần; có nói thì giữ", [(s["id"], s["mode"], s["loops"]) for s in g["scripts"]])
        back = store.get_group(g["id"])
        ok(back["scripts"][1]["steps"] == [tap, home] and back["scripts"][0]["steps"] == [home], "đọc lại từ đĩa đúng, bước của từng kịch bản giữ nguyên")
        back["scripts"][0]["mode"] = "loop"; back["scripts"][0]["loops"] = 0
        back = store.get_group(store.save_group(back)["id"])
        ok(back["scripts"][0]["mode"] == "loop" and back["scripts"][0]["loops"] == 0 and back["scripts"][1]["loops"] == 5, "đổi cách chạy một kịch bản không ảnh hưởng kịch bản kia")

        print("\n== 3. Xoá / rỗng ==")
        back["scripts"] = [s for s in back["scripts"] if s["id"] != "a"]
        back = store.save_group(back)
        ok([s["id"] for s in back["scripts"]] == ["b"], "xoá kịch bản → còn lại kịch bản kia")
        back["scripts"] = []
        back["steps"] = [home]                       # `steps` cũ còn sót trong bản gửi lên: KHÔNG được dựng lại kịch bản
        back = store.save_group(back)
        ok(back["scripts"] == [] and "steps" not in back, "xoá hết kịch bản → rỗng (không sống lại từ `steps` cũ)", back)
        ok(store.get_group(back["id"])["scripts"] == [], "…và vẫn rỗng sau khi đọc lại")

        print("\n== 4. Dữ liệu lỗi / thiếu ==")
        g = store.save_group({"name": "Rác", "mode": "once", "devices": [], "scripts": [
            {"id": "x", "name": "  ", "steps": [home], "mode": "bay-ba", "loops": "nhieu"}, {"id": "x", "name": "Trùng id", "steps": "không phải danh sách", "mode": "loop", "loops": -3},
            "chuỗi lạ", None, {"name": "Thiếu id", "steps": [tap]}]})
        ids = [s["id"] for s in g["scripts"]]
        ok(len(g["scripts"]) == 3 and len(set(ids)) == 3 and all(ids), "bỏ phần tử rác, id trùng/thiếu được cấp lại, không trùng nhau", ids)
        ok(g["scripts"][0]["name"] == "Kịch bản 1" and g["scripts"][1]["steps"] == [], "tên rỗng → «Kịch bản N»; steps không phải danh sách → []")
        ok((g["scripts"][0]["mode"], g["scripts"][0]["loops"]) == ("once", 1) and (g["scripts"][1]["mode"], g["scripts"][1]["loops"]) == ("loop", 0),
           "cách chạy sai → chạy 1 lần; số vòng âm / không phải số → mặc định", [(s["mode"], s["loops"]) for s in g["scripts"]])
        g2 = store.save_group({"name": "Hỏng", "mode": "once", "devices": [], "scripts": "không phải danh sách"})
        ok(g2["scripts"] == [], "`scripts` không phải danh sách → coi như rỗng")
        long = store.save_group({"name": "Dài", "mode": "once", "devices": [], "scripts": [{"id": "l", "name": "x" * 500, "steps": [], "mode": "loop", "loops": 10 ** 9}]})
        ok(len(long["scripts"][0]["name"]) == 80 and long["scripts"][0]["loops"] == 100000, "tên cắt ở 80 ký tự; số vòng có trần")

        print("\n== 5. pick_script ==")
        grp = {"scripts": [{"id": "s1", "name": "Đăng nhập", "steps": []}, {"id": "s2", "name": "Mua  gói", "steps": []}]}
        ok(store.pick_script(grp, "s2")["id"] == "s2" and store.pick_script(grp, "đăng NHẬP")["id"] == "s1" and store.pick_script(grp, "mua gói")["id"] == "s2",
           "theo id; theo tên không phân biệt hoa thường / khoảng trắng thừa")
        ok(store.pick_script(grp, "khong-co") is None and store.pick_script(grp) is None, "tên lạ → None; không nêu mà nhóm có 2 kịch bản → None (không đoán)")
        ok(store.pick_script({"scripts": [{"id": "only", "name": "X", "steps": []}]})["id"] == "only", "không nêu mà nhóm có đúng 1 kịch bản → lấy kịch bản đó")
        ok(store.pick_script({"scripts": [{"id": "1", "name": "Trùng", "steps": []}, {"id": "2", "name": "trùng", "steps": []}]}, "trùng") is None, "hai kịch bản trùng tên → None (mơ hồ), nêu id mới chọn được")
        ok(store.pick_script({"scripts": []}) is None, "nhóm không có kịch bản → None")

        print("\n== 6. Một máy ở NHIỀU nhóm ==")
        a = store.save_group({"name": "A", "devices": [], "scripts": [{"id": "sa", "name": "SA", "steps": [home]}]})
        b = store.save_group({"name": "B", "devices": [], "scripts": [{"id": "sb", "name": "SB", "steps": [tap]}]})
        store.add_device_to_group("M1", a["id"]); store.add_device_to_group("M1", b["id"]); store.add_device_to_group("M2", a["id"])
        ok([x["name"] for x in store.groups_of_device("M1")] == ["A", "B"], "máy M1 thêm vào A rồi B → ở CẢ HAI nhóm", [x["name"] for x in store.groups_of_device("M1")])
        ok(store.get_group(a["id"])["devices"] == ["M1", "M2"] and store.get_group(b["id"])["devices"] == ["M1"], "mỗi nhóm giữ đúng danh sách máy của nó")
        store.add_device_to_group("M1", a["id"])
        ok(store.get_group(a["id"])["devices"] == ["M1", "M2"], "thêm lần nữa không bị trùng")
        store.remove_device_from_group("M1", a["id"])
        ok(store.get_group(a["id"])["devices"] == ["M2"] and store.get_group(b["id"])["devices"] == ["M1"], "bỏ M1 khỏi A → vẫn còn ở B")
        ok(store.add_device_to_group("M1", "khong-co") is False and store.remove_device_from_group("M1", "khong-co") is False, "nhóm không tồn tại → False, không lỗi")
        store.add_device_to_group("M1", a["id"]); store.add_device_to_group("M1", b["id"])
        store.rename_in_groups("M1", "M1-moi")
        ok(store.get_group(a["id"])["devices"] == ["M2", "M1-moi"] and store.get_group(b["id"])["devices"] == ["M1-moi"], "máy đổi tên → đổi trong mọi nhóm, giữ vị trí")
        ok(store.get_group(a["id"])["scripts"][0]["steps"] == [home] and store.get_group(b["id"])["scripts"][0]["steps"] == [tap], "kịch bản của các nhóm không bị đụng")
        g = store.save_group({"name": "Không nói chế độ", "devices": []})
        ok(g["mode"] == "once" and g["loops"] == 1, "nhóm mới không nói chế độ → mặc định chạy theo kịch bản (không lặp vô hạn)", (g["mode"], g["loops"]))

        print("\n== 7. Runner: một máy MỘT kịch bản một lúc, hiện «nhóm · kịch bản» ==")
        import threading, runner
        import types as types_mod

        class Th:                                       # thread giả: sống / chết
            def __init__(self, alive): self.alive = alive
            def is_alive(self): return self.alive

        def worker(gid, sid, alive=True, hold=None):
            return {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False, "thread": Th(alive),
                    "udid": None, "port": None, "carry_hold": None, "group_id": gid, "group_name": gid, "script_id": sid,
                    "script_name": sid, "mode": "once", "iter": 0, "status": "x", "last_ok": None, "last_msg": None, "job_id": None, "job_ref": None,
                    "pool": None, "counts": {"done": 0, "failed": 0, "review": 0}, "hold": hold}
        # --- khởi động thật: kịch bản chạy đúng bước + cách chạy của NÓ ---
        ran = []

        class FakeNav: pass
        R0 = runner.Runner(lambda n: FakeNav())
        real_run_flow = runner.engine.run_flow
        runner.engine.run_flow = lambda nav, steps, stop_check=None, pause_gate=None: (ran.append([s["type"] for s in steps]) or [{"ok": True}] * len(steps))
        grp = {"id": "G", "name": "Nhóm G", "devices": ["M1", "M2"], "mode": "once"}
        scr_once = {"id": "so", "name": "Một lần", "steps": [home, tap], "mode": "once", "loops": 1}
        scr_loop3 = {"id": "sl", "name": "Ba vòng", "steps": [home], "mode": "loop", "loops": 3}
        ok(R0.start_machine("M1", grp, scr_once) is True, "máy rảnh → chạy được kịch bản")
        R0.workers["M1"]["thread"].join(10)
        snap = R0.status()["M1"]
        ok(ran == [["home", "tap_text"]] and snap["group_name"] == "Nhóm G" and snap["script_name"] == "Một lần" and snap["script_id"] == "so" and snap["status"] == "xong",
           "chạy đúng các bước của kịch bản 1 lần; trạng thái ghi tên nhóm + kịch bản", (ran, snap))
        ran.clear()
        R0.start_machine("M2", grp, scr_loop3); R0.workers["M2"]["thread"].join(15)
        ok(len(ran) == 3 and R0.status()["M2"]["iter"] == 3, "kịch bản «lặp 3 vòng» chạy đúng 3 vòng (cách chạy nằm trong kịch bản)", (len(ran), R0.status()["M2"]["iter"]))
        ok(R0.start_machine("M1", grp, None) is False, "không có kịch bản (và nhóm không phải API) → không chạy")

        # --- TẠM DỪNG / TIẾP TỤC (để người xử lý tay): chạy bằng run_flow THẬT, chỉ giả bước ---
        runner.engine.run_flow = real_run_flow
        import time as _t
        done_steps = []
        real_run_step, real_sleep = runner.engine.run_step, runner.engine.time.sleep
        runner.engine.run_step = lambda nav, step, log=None: (done_steps.append(step["type"]) or (True, "ok"))
        runner.engine.time = types_ns = __import__("types").SimpleNamespace(sleep=lambda s: real_sleep(0.02), time=_t.time)   # nghỉ giữa bước ngắn lại cho bài thử
        try:
            RP = runner.Runner(lambda n: FakeNav())
            scr_inf = {"id": "sp", "name": "Lặp mãi", "steps": [home, tap], "mode": "loop", "loops": 0}
            ok(RP.pause_machine("P1") is False and RP.resume_machine("P1") is False, "máy không chạy → tạm dừng / tiếp tục trả False")
            RP.start_machine("P1", grp, scr_inf)

            def until(cond, sec=6.0):
                t0 = _t.time()
                while _t.time() - t0 < sec:
                    if cond():
                        return True
                    _t.sleep(0.02)
                return False
            ok(until(lambda: len(done_steps) >= 2), "kịch bản lặp đang chạy (đã làm vài bước)")
            ok(RP.pause_machine("P1") is True and until(lambda: RP.status()["P1"]["paused"]), "bấm Tạm dừng → máy vào trạng thái tạm dừng")
            snap = RP.status()["P1"]
            n1 = len(done_steps)
            _t.sleep(0.8)
            ok(len(done_steps) == n1 and snap["running"] is True and snap["status"].startswith("TẠM DỪNG"),
               "đang tạm dừng: KHÔNG làm thêm bước nào (để người xử lý tay), máy vẫn tính là đang chạy việc đó", (n1, len(done_steps), snap["status"]))
            ok(RP.start_machine("P1", grp, scr_once) is False, "máy đang tạm dừng vẫn giữ chỗ: không chạy kịch bản khác chồng lên được")
            ok(RP.resume_machine("P1") is True and until(lambda: len(done_steps) > n1) and RP.status()["P1"]["paused"] is False,
               "bấm Tiếp tục → chạy tiếp các bước", (n1, len(done_steps)))
            RP.pause_machine("P1"); until(lambda: RP.status()["P1"]["paused"])
            RP.stop_machine("P1")
            RP.workers["P1"]["thread"].join(5)
            ok(not RP.workers["P1"]["thread"].is_alive() and RP.status()["P1"]["status"] == "đã dừng" and RP.status()["P1"]["paused"] is False,
               "Dừng lúc đang tạm dừng → kết thúc hẳn (không kẹt ở tạm dừng)", RP.status()["P1"])
            # dừng tất cả
            RP.start_machine("P1", grp, scr_inf); RP.start_machine("P2", grp, scr_inf)
            until(lambda: RP.is_running("P1") and RP.is_running("P2"))
            RP.pause_machine("P2"); until(lambda: RP.status()["P2"]["paused"])
            RP.stop_all()
            RP.workers["P1"]["thread"].join(5); RP.workers["P2"]["thread"].join(5)
            ok(RP.running_names() == [], "Dừng tất cả → mọi máy dừng, kể cả máy đang tạm dừng", RP.running_names())
        finally:
            runner.engine.run_step = real_run_step
            runner.engine.time = _t

        # --- một máy một kịch bản một lúc ---
        R = runner.Runner(lambda n: None)
        R.workers["M1"] = worker("B", "s1")
        ok(R.start_machine("M1", {"id": "A", "name": "A", "devices": ["M1"], "mode": "once"}, scr_once) is False, "máy đang chạy kịch bản của nhóm B → nhóm A không chạy chồng lên được")
        ok(R.start_machine("M1", {"id": "B", "name": "B", "devices": ["M1"], "mode": "once"}, scr_once) is False, "…cùng nhóm nhưng kịch bản khác cũng không được (một máy một kịch bản một lúc)")

        # --- dừng nhóm / kịch bản ---
        R = runner.Runner(lambda n: None)
        R.workers["M1"] = worker("B", "s1")             # M1: nhóm B, kịch bản s1
        R.workers["M2"] = worker("A", "s1")             # M2: nhóm A, kịch bản s1
        R.workers["M3"] = worker("B", "s1", alive=False, hold="đơn cần đối soát")   # M3 đã dừng, đang GIỮ — việc của nhóm B
        R.workers["M4"] = worker("A", "s2")             # M4: nhóm A, kịch bản s2
        groupA = {"id": "A", "name": "A", "devices": ["M1", "M2", "M3", "M4"], "mode": "once"}
        R.stop_group(groupA, force=True)
        ok(R.workers["M2"]["abort"].is_set() and R.workers["M4"]["abort"].is_set(), "dừng nhóm A → mọi máy đang chạy việc của A bị dừng")
        ok(not R.workers["M1"]["stop"].is_set() and R.workers["M3"]["hold"] == "đơn cần đối soát", "…máy đang chạy / đang giữ việc của nhóm B không bị đụng")
        R2 = runner.Runner(lambda n: None)
        R2.workers["M2"] = worker("A", "s1"); R2.workers["M4"] = worker("A", "s2")
        R2.stop_group(groupA, force=False, script_id="s1")
        ok(R2.workers["M2"]["stop"].is_set() and not R2.workers["M4"]["stop"].is_set(), "dừng kịch bản s1 của nhóm A → chỉ máy đang chạy s1 dừng, máy chạy s2 giữ nguyên")
        R.stop_all(force=True)
        ok(R.workers["M3"]["hold"] == "đơn cần đối soát", "Dừng tất cả KHÔNG gỡ trạng thái giữ chờ đối soát (việc đó là của người vận hành, từng máy)")
        R.stop_group({"id": "B", "name": "B", "devices": ["M1", "M3"]}, force=False)
        R.stop_machine("M3"); R.stop_machine("M3", force=True)
        ok(R.workers["M1"]["stop"].is_set() and R.hold_reason("M3") == "đơn cần đối soát",
           "dừng nhóm B / bấm Dừng (kể cả Dừng ngay) trên máy đang giữ → KHÔNG gỡ giữ: Dừng không phải lời xác nhận «đã đối soát»")
        ok(R.ack_hold("M1") is False and R.hold_reason("M3") == "đơn cần đối soát", "xác nhận trên máy KHÔNG đang giữ → không làm gì")
        ok(R.ack_hold("M3") is True and R.hold_reason("M3") is None and R.ack_hold("M3") is False, "«Đã kiểm tra xong» (ack_hold) là cách DUY NHẤT gỡ giữ mà không chạy lại")
        # dừng nhóm tính theo VIỆC đang chạy, không theo danh sách máy hiện tại của nhóm (máy bị bỏ khỏi nhóm giữa chừng vẫn dừng được)
        R5 = runner.Runner(lambda n: None)
        R5.workers["X1"] = worker("A", "s1")
        R5.stop_group({"id": "A", "name": "A", "devices": []})
        ok(R5.workers["X1"]["stop"].is_set(), "máy đã bị bỏ khỏi nhóm nhưng còn chạy việc của nhóm → «Dừng nhóm» vẫn dừng được")

        # --- máy thật: so theo iPhone + cổng board ghi lúc BẮT ĐẦU chạy ---
        RI = runner.Runner(lambda n: FakeNav())
        table = {"M1": ("UDID-1", "/dev/p1"), "M2": ("UDID-2", "/dev/p2")}
        RI.ident = lambda n: table.get(n, (None, None))
        RI._run_api = lambda name, group, w: w["stop"].wait(30)
        RI._ensure_heartbeat = lambda: None
        RI.start_machine("M1", {"id": "API", "name": "Nhận đơn", "devices": ["M1"], "mode": "api", "api": {"pool": "p"}})
        table["M1"] = ("da-bi-gan-lai", "/dev/khac")                 # bảng gán bị đổi SAU khi máy đã bắt đầu làm đơn
        ok(RI.conflict("ten-khac", "UDID-1", None) == "M1" and RI.conflict("ten-khac", None, "/dev/p1") == "M1" and RI.conflict("M1") == "M1",
           "máy đang làm đơn được nhận ra theo iPhone / cổng board ghi lúc bắt đầu — tên khác trỏ vào cùng máy vẫn bị coi là máy đó", RI.customers())
        ok(RI.conflict("M2", "UDID-2", "/dev/p2") is None and RI.conflict("x", None, None) is None, "máy khác hẳn (iPhone khác, board khác) thì không trùng")
        ok(RI.conflict("x", "udid-1", None) == "M1" and RI.conflict("x", "UD-ID-1", None) == "M1" and RI.canon_udid("0000-ab") == "0000AB" and RI.canon_udid(None) is None,
           "UDID so ở dạng chuẩn (bỏ dấu gạch, không phân biệt hoa-thường): viết khác đi vẫn là cùng một iPhone")
        RI.stop_machine("M1"); RI.workers["M1"]["thread"].join(5)
        ok(RI.customers() == [], "máy nhận đơn dừng hẳn (không giữ) → không còn là máy của khách")
        # danh tính lấy từ PHIÊN ĐANG DÙNG THẬT (bảng gán có thể đã bị đổi sau khi phiên được mở)
        nav_real = types_mod.SimpleNamespace(e=types_mod.SimpleNamespace(udid="that-su-99"), h=types_mod.SimpleNamespace(port="/dev/that"))
        RS = runner.Runner(lambda n: nav_real)
        RS.ident = lambda n: ("theo-bang-sai", "/dev/theo-bang")
        seen = {}
        RS._ensure_heartbeat = lambda: None

        class GwStop(Exception): pass
        RS._gateway = lambda: (_ for _ in ()).throw(RuntimeError("không cần gateway cho bài thử này"))
        real_run_api = runner.Runner._run_api

        def spy_run_api(self, name, group, w):
            self._seen_nav(w, self._session(name)); seen.update(udid=w["udid"], port=w["port"]); w["stop"].wait(30)
        RS._run_api = lambda name, group, w: spy_run_api(RS, name, group, w)
        RS.start_machine("S1", {"id": "API", "name": "Nhận đơn", "devices": ["S1"], "mode": "api", "api": {"pool": "p"}})
        import time as _t2
        for _ in range(100):
            if seen: break
            _t2.sleep(0.02)
        ok(seen == {"udid": "THATSU99", "port": "/dev/that"} and RS.conflict("khac", "That-Su-99", None) == "S1" and RS.conflict("khac", "theo-bang-sai", None) is None,
           "máy của khách được ghi theo iPhone + cổng của PHIÊN đang dùng thật, không theo bảng gán lúc đó", seen)
        RS.stop_machine("S1"); RS.workers["S1"]["thread"].join(5)
        # tên KHÁC trỏ vào cùng iPhone / board với máy của khách: không chạy gì lên nó được (kịch bản «chờ chữ» sẽ dò màn hình của khách)
        RA = runner.Runner(lambda n: FakeNav())
        map_a = {"KHACH": ("UDID-K", "/dev/k"), "alias-udid": ("udid-k", "/dev/khac"), "alias-cong": ("UDID-X", "/dev/k"), "rieng": ("UDID-R", "/dev/r")}
        RA.ident = lambda n: map_a.get(n, (None, None))
        RA._run_api = lambda name, group, w: w["stop"].wait(30)
        RA._ensure_heartbeat = lambda: None
        RA.start_machine("KHACH", {"id": "API", "name": "Nhận đơn", "devices": ["KHACH"], "mode": "api", "api": {"pool": "p"}})
        kb = {"id": "KB", "name": "Kịch bản", "devices": ["alias-udid", "alias-cong", "rieng"], "mode": "once"}
        ok(RA.start_machine("alias-udid", kb, scr_once) is False and RA.start_machine("alias-cong", kb, scr_once) is False and "alias-udid" not in RA.workers,
           "kịch bản chạy lên một tên khác trỏ vào CÙNG iPhone (kể cả UDID viết khác) hoặc CÙNG board với máy đang làm đơn → từ chối")
        ok(RA.start_machine("rieng", kb, scr_once) is True, "…máy riêng (iPhone khác, board khác) vẫn chạy bình thường")
        RA.workers["rieng"]["thread"].join(10)
        RA.stop_machine("KHACH"); RA.workers["KHACH"]["thread"].join(5)
        ok(RA.start_machine("alias-udid", kb, scr_once) is True, "máy của khách dừng hẳn (không giữ) → tên kia chạy lại được")
        RA.workers["alias-udid"]["thread"].join(10)
        # kịch bản mang «cách chạy» lạ (vd "api") không bao giờ biến thành chế độ nhận đơn
        RM = runner.Runner(lambda n: FakeNav())
        api_called = []
        RM._run_api = lambda name, group, w: api_called.append(name)
        RM.start_machine("Z1", grp, dict(scr_once, mode="api"))
        RM.workers["Z1"]["thread"].join(10)
        ok(api_called == [] and RM.status()["Z1"]["mode"] == "once", "kịch bản có cách chạy lạ («api») → vẫn chạy như kịch bản 1 lần, KHÔNG thành chế độ nhận đơn", (api_called, RM.status()["Z1"]["mode"]))

        # tiến trình không được chạy đơn của khách (chế độ web)
        RW = runner.Runner(lambda n: FakeNav())
        RW.allow_api = False
        ok(RW.start_machine("W1", {"id": "API", "name": "Nhận đơn", "devices": ["W1"], "mode": "api", "api": {"pool": "p"}}) is False and RW.workers == {},
           "allow_api = False (chế độ web) → bộ chạy từ chối nhóm nhận đơn; không có worker nào được tạo")
        ok(RW.start_machine("W1", grp, scr_once) is True, "…kịch bản thường vẫn chạy")
        RW.workers["W1"]["thread"].join(10)

        # --- máy đang GIỮ chờ đối soát: nhóm / kịch bản KHÁC không được chạy đè lên ---
        RH = runner.Runner(lambda n: FakeNav())
        RH._run_api = lambda name, group, w: None            # không cần gateway thật cho bài thử này
        RH._ensure_heartbeat = lambda: None
        api_grp = {"id": "API", "name": "Nhóm nhận đơn", "devices": ["H1"], "mode": "api", "api": {"pool": "p"}}
        other_api = {"id": "API2", "name": "Nhóm nhận đơn khác", "devices": ["H1"], "mode": "api", "api": {"pool": "q"}}
        script_grp = {"id": "KB", "name": "Nhóm kịch bản", "devices": ["H1"], "mode": "once"}
        RH.workers["H1"] = worker("API", None, alive=False, hold="đơn T-9 cần đối soát")
        RH.workers["H1"]["mode"] = "api"
        ok(RH.start_machine("H1", script_grp, scr_once) is False and RH.hold_reason("H1") == "đơn T-9 cần đối soát",
           "máy đang giữ chờ đối soát: chạy KỊCH BẢN của nhóm khác lên → từ chối, vẫn giữ (không bấm vào tài khoản khách còn đăng nhập)", RH.hold_reason("H1"))
        ok(RH.start_machine("H1", other_api, None) is False and RH.hold_reason("H1") == "đơn T-9 cần đối soát", "…nhóm nhận đơn KHÁC cũng không chạy đè được")
        ok(RH.start_machine("H1", dict(api_grp, mode="once"), scr_once) is False, "…kể cả chính nhóm đó nhưng không phải đường «Chạy lại» của chế độ nhận đơn")
        RH.workers["H0"] = worker(None, None, alive=False, hold="giữ của một việc không rõ nhóm")
        RH.workers["H0"]["mode"] = "api"
        ok(RH.start_machine("H0", {"mode": "api", "devices": ["H0"], "api": {"pool": "p"}}, None) is False and RH.hold_reason("H0"),
           "nhóm không có id không được coi là «cùng nhóm» với một việc cũng không có id nhóm (None == None không phải là cùng nhóm)")
        ok(RH.start_machine("H1", api_grp, None) is True, "chỉ «Chạy lại» của CHÍNH nhóm nhận đơn đó mới chạy tiếp được (đường này tự đăng xuất + kiểm game sạch)")
        RH.workers["H1"]["thread"].join(5)
        ok(RH.hold_reason("H1") == "đơn T-9 cần đối soát",
           "«Chạy lại» mà lần chạy mới kết thúc TRƯỚC khi kiểm xong game đã đăng xuất (không mở được máy, bị dừng…) → máy VẪN đang giữ", RH.hold_reason("H1"))
        ok(RH.start_machine("H1", script_grp, scr_once) is False, "…nên kịch bản nhóm khác vẫn không chạy đè lên được")

        def clean_run(name, group, w):
            w["carry_hold"] = None                       # như bộ chạy thật lúc đã THẤY game ở trạng thái chưa đăng nhập
        RH._run_api = clean_run
        RH.start_machine("H1", api_grp, None); RH.workers["H1"]["thread"].join(5)
        ok(RH.hold_reason("H1") is None and RH.start_machine("H1", script_grp, scr_once) is True, "lần «Chạy lại» đã kiểm xong game sạch → hết giữ, máy dùng lại bình thường")
        RH.workers["H1"]["thread"].join(5)

        print("\n== 8. Giao diện app: điều kiện chạy + thông báo «máy đang chạy …» ==")
        import types
        if "webview" not in sys.modules:
            sys.modules["webview"] = types.SimpleNamespace(create_window=lambda *a, **k: None, start=lambda *a, **k: None)
        import gui
        sc_ok = {"id": "s1", "name": "Đăng nhập", "steps": [home], "mode": "once", "loops": 1}
        sc_empty = {"id": "s2", "name": "Rỗng", "steps": [], "mode": "once", "loops": 1}
        sc_dup = {"id": "s3", "name": "Mua gói", "steps": [home], "mode": "once", "loops": 1}
        gr = lambda *scripts: {"id": "G", "name": "Nhóm G", "mode": "once", "devices": ["M1", "M2"], "scripts": list(scripts)}
        rn = lambda g, s=None: gui.Api._runnable(None, g, s)
        ok(rn(gr()) == "Nhóm chưa có kịch bản nào.", "nhóm không có kịch bản → báo rõ", rn(gr()))
        ok(rn(gr(sc_ok)) is None and rn(gr(sc_ok), "đăng nhập") is None, "nhóm 1 kịch bản có bước → chạy được (không cần nêu tên; nêu tên cũng được)")
        ok("chưa có bước" in rn(gr(sc_empty)), "kịch bản chưa có bước → báo tên kịch bản", rn(gr(sc_empty)))
        multi = rn(gr(sc_ok, sc_dup))
        ok("2 kịch bản" in multi and "Đăng nhập" in multi and "Mua gói" in multi, "nhóm 2 kịch bản mà không nêu → từ chối, liệt kê tên", multi)
        ok("không có kịch bản" in rn(gr(sc_ok, sc_dup), "lạ") and rn(gr(sc_ok, sc_dup), "mua gói") is None, "kịch bản lạ → từ chối; nêu đúng tên → chạy được")

        old_get = gui.store.get_group
        gui.store.get_group = lambda gid: gr(sc_ok, sc_dup) if gid == "G" else (dict(gr(sc_ok), id="H", name="Nhóm H") if gid == "H" else None)
        saved_workers = dict(gui.RUNNER.workers)
        try:
            gui.RUNNER.workers["M1"] = worker("H", "s1")
            gui.RUNNER.workers["M1"]["group_name"] = "Nhóm H"; gui.RUNNER.workers["M1"]["script_name"] = "Đăng nhập"
            r = gui.Api().machine_run("G", "M1", "s1")
            ok(r["ok"] is False and "Nhóm H · Đăng nhập" in r["error"] and "một kịch bản một lúc" in r["error"],
               "chạy kịch bản trên máy đang chạy «Nhóm H · Đăng nhập» → từ chối, nói rõ máy đang chạy gì", r)
            r = gui.Api().group_run("G", ["M1"], "s3")
            ok(r["ok"] is True and r["started"] == [] and r["busy"] == {"M1": "Nhóm H · Đăng nhập"}, "chạy kịch bản trên máy bận: bị bỏ qua và liệt kê trong busy (không khởi động)", r)
            r = gui.Api().group_run("G", ["M2"])
            ok(r["ok"] is False and "2 kịch bản" in r["error"], "nhóm nhiều kịch bản mà không nêu kịch bản → từ chối, không chạy gì", r)
            ok("M2" not in gui.RUNNER.workers, "…và không máy nào bị khởi động")
            # app cửa sổ (không --web): tên khác trỏ vào cùng iPhone với máy đang làm đơn của khách → bị bỏ qua, báo trong `held`
            real_udid, real_map = gui.MGR._udid, gui.MGR.board_map
            gui.MGR._udid = lambda n: {"M2": "udid-khach"}.get(n)
            gui.MGR.board_map = {"M2": "/dev/m2"}
            gui.RUNNER.workers["KHACH"] = worker("H", None)
            gui.RUNNER.workers["KHACH"].update(mode="api", udid="UDIDKHACH", port="/dev/khach")
            try:
                r = gui.Api().group_run("G", ["M2"], "s3"); r2 = gui.Api().machine_run("G", "M2", "s3")
                ok(r["ok"] is True and r["started"] == [] and "KHACH" in (r["held"].get("M2") or "") and r2["ok"] is False and "M2" not in gui.RUNNER.workers,
                   "app cửa sổ: chạy kịch bản lên tên trỏ vào iPhone của khách (qua giao diện / cầu nối AI) → bỏ qua, nói rõ trùng máy nào", (r, r2))
            finally:
                gui.MGR._udid, gui.MGR.board_map = real_udid, real_map
                gui.RUNNER.workers.pop("KHACH", None)
            r = gui.Api().group_run("G", ["M-LA"], "s1"); r2 = gui.Api().machine_run("G", "M-LA", "s1")
            ok(r["ok"] is False and "không thuộc nhóm" in r["error"] and r2["ok"] is False and "M-LA" not in gui.RUNNER.workers, "máy không thuộc nhóm → từ chối, không chạy", (r, r2))

            # máy đang GIỮ chờ đối soát (việc của nhóm nhận đơn H): chạy kịch bản nhóm G lên → bỏ qua + báo, KHÔNG khởi động, vẫn giữ
            gui.RUNNER.workers["M2"] = worker("H", None, alive=False, hold="đơn T-9 cần đối soát")
            gui.RUNNER.workers["M2"]["mode"] = "api"
            calls = []
            real_start_group = gui.RUNNER.start_group
            gui.RUNNER.start_group = lambda g, names=None, sc=None: (calls.append((list(names or []), (sc or {}).get("id"))), real_start_group(g, names, sc))[1]
            try:
                r = gui.Api().group_run("G", ["M2"], "s3")
                ok(r["ok"] is True and r["started"] == [] and r["held"] == {"M2": "đơn T-9 cần đối soát"} and calls == [([], "s3")] and gui.RUNNER.hold_reason("M2") == "đơn T-9 cần đối soát",
                   "chạy kịch bản lên máy đang giữ chờ đối soát → bỏ qua, báo trong `held`, KHÔNG khởi động, trạng thái giữ còn nguyên", (r, calls))
                r = gui.Api().machine_run("G", "M2", "s3")
                ok(r["ok"] is False and "CHỜ NGƯỜI KIỂM TRA" in r["error"] and gui.RUNNER.hold_reason("M2") == "đơn T-9 cần đối soát", "…chạy riêng máy đó cũng bị từ chối, nói rõ lý do", r)
                # đúng kịch bản được đưa xuống bộ chạy
                gui.RUNNER.workers.pop("M2")
                calls.clear()
                gui.RUNNER.start_group = lambda g, names=None, sc=None: calls.append((list(names or []), (sc or {}).get("id"), (sc or {}).get("name"))) or []
                gui.Api().group_run("G", ["M2"], "mua gói"); gui.Api().group_run("G", ["M2"], "s1")
                ok(calls == [(["M2"], "s3", "Mua gói"), (["M2"], "s1", "Đăng nhập")], "nêu kịch bản nào thì ĐÚNG kịch bản đó được chạy (theo tên hoặc id)", calls)
            finally:
                gui.RUNNER.start_group = real_start_group
            # dừng theo kịch bản / dừng cả nhóm
            stops = []
            real_stop_group = gui.RUNNER.stop_group
            gui.RUNNER.stop_group = lambda g, force=False, script_id=None: stops.append((g["id"], force, script_id))
            try:
                gui.Api().group_stop("G", False, "s3"); gui.Api().group_stop("G"); gui.Api().group_stop("H")
                bad = gui.Api().group_stop("G", False, "khong-co")
            finally:
                gui.RUNNER.stop_group = real_stop_group
            ok(stops == [("G", False, "s3"), ("G", False, None), ("H", False, None)] and bad["ok"] is False,
               "dừng theo kịch bản → chỉ kịch bản đó; không nêu → MỌI việc của nhóm (kể cả nhóm chỉ có 1 kịch bản); kịch bản lạ → báo lỗi", (stops, bad))

            # máy đang giữ: Dừng không gỡ; «Đã kiểm tra xong» (machine_ack) mới gỡ; xoá nhóm còn máy đang giữ bị từ chối
            gui.RUNNER.workers["M2"] = worker("H", None, alive=False, hold="đơn T-9 cần đối soát")
            gui.RUNNER.workers["M2"]["mode"] = "api"
            deleted = []
            real_del = gui.store.delete_group
            gui.store.delete_group = lambda gid: deleted.append(gid)
            try:
                r_stop = gui.Api().machine_stop("M2")
                r_del = gui.Api().group_delete("H")
                ok(r_stop["ok"] is False and "Đã kiểm tra xong" in r_stop["error"] and gui.RUNNER.hold_reason("M2") == "đơn T-9 cần đối soát", "bấm Dừng trên máy đang giữ → không gỡ giữ, chỉ dẫn bấm «Đã kiểm tra xong»", r_stop)
                ok(r_del["ok"] is False and deleted == [] and gui.RUNNER.hold_reason("M2") == "đơn T-9 cần đối soát", "xoá nhóm còn máy đang giữ chờ đối soát → từ chối, không gỡ giữ, không xoá", r_del)
                ok(gui.Api().machine_ack("M1")["ok"] is False, "«Đã kiểm tra xong» trên máy không đang giữ → báo không có gì để xác nhận")
                r_ack = gui.Api().machine_ack("M2")
                ok(r_ack["ok"] is True and gui.RUNNER.hold_reason("M2") is None, "«Đã kiểm tra xong» ở app cửa sổ → gỡ giữ", r_ack)
                r_del = gui.Api().group_delete("H")
                ok(r_del["ok"] is True and deleted == ["H"], "hết máy đang giữ → xoá nhóm được", (r_del, deleted))
                # board của máy đang giữ: không nạp / xoá / đổi tên (đổi tên board sẽ làm mất dấu trạng thái giữ) — kể cả ở app cửa sổ
                gui.RUNNER.workers["M2"] = worker("H", None, alive=False, hold="đơn T-9 cần đối soát")
                gui.RUNNER.workers["M2"]["mode"] = "api"; gui.RUNNER.workers["M2"]["port"] = "/dev/cu.giu"
                flashed = []
                real_flash, real_erase = gui.esp.flash, gui.esp.erase
                gui.esp.flash = lambda port, name: flashed.append(("flash", port)) or {"ok": True}
                gui.esp.erase = lambda port: flashed.append(("erase", port)) or {"ok": True}
                try:
                    g1 = gui.Api()._port_guard("/dev/cu.giu")
                    f1, e1 = gui.Api().esp_flash("/dev/cu.giu", "ten-moi"), gui.Api().esp_erase("/dev/cu.giu")
                finally:
                    gui.esp.flash, gui.esp.erase = real_flash, real_erase
                ok(g1 and "CHỜ NGƯỜI KIỂM TRA" in g1 and f1["ok"] is False and e1["ok"] is False and flashed == [] and gui.RUNNER.hold_reason("M2"),
                   "nạp / xoá board của máy đang giữ → từ chối (không đổi tên board để lách trạng thái giữ), vẫn giữ", (g1, f1, e1, flashed))
                ok(gui.Api()._port_guard("/dev/cu.khac") is None, "…board khác thì không bị chặn")
                gui.RUNNER.ack_hold("M2")
            finally:
                gui.store.delete_group = real_del
        finally:
            gui.store.get_group = old_get
            gui.RUNNER.workers.clear(); gui.RUNNER.workers.update(saved_workers)
    finally:
        store.DATA_DIR, store.GROUPS_FILE, store.DEVICES_FILE, store.FLOWS_FILE = old
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
