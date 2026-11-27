#!/usr/bin/env python3
"""
Kiểm ẢNH MẪU + KIỂM MÀN HÌNH TRƯỚC MỖI BƯỚC (screencheck.py, apimode.screen_gate, engine.run_flow, runner._admin_pause):
  • ảnh mẫu: chữ chuẩn hoá (bỏ dấu, số → 9), bỏ dòng quá ngắn / toàn số / email / mã người chơi; hai lần đọc chỉ giữ chữ chung;
  • so khớp: theo chữ (đủ dòng) hoặc theo hình (ít chữ); khác chiều ảnh → khác;
  • trước bước thao tác có ảnh mẫu: khớp → làm; khác (sau khi chờ) → KHÔNG làm bước; có bộ xử lý (lúc chạy thật) → giao cho nó;
  • chạy thử trong trình sửa: không kiểm, chụp ảnh mẫu cho bước chưa có;
  • bộ chạy: màn hình lạ → TẠM DỪNG máy, báo Telegram (ảnh, trừ lúc làm đơn khách), Tiếp tục → làm bước; Dừng → không làm; Dừng ngay → Aborted.

    ./.venv/bin/python app/tests/test_screencheck.py
"""
from __future__ import annotations
import os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["IPF_NO_TELEGRAM"] = "1"
import cv2
import numpy as np
import screencheck as sc
import apimode, engine

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def screen(color=(40, 80, 160), w=1334, h=750, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), color, np.uint8)
    for _ in range(12):
        x, y = int(rng.integers(0, w - 200)), int(rng.integers(0, h - 100))
        cv2.rectangle(img, (x, y), (x + 180, y + 80), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


MAIN = ["Home", "Shop", "Academy", "Extras", "Match", "My Team", "Contracts", "Daily Game"]
SHOP = ["Shop", "eFootball Coins", "You can purchase", "Product Details", "Back"]


class Eyes:
    """Mắt giả: lần lượt trả các (ảnh, dòng chữ) trong `frames` (giữ khung cuối)."""
    def __init__(self, frames):
        self.frames = list(frames)
        self.shots = 0

    def _cur(self):
        return self.frames[min(self.shots, len(self.frames) - 1)]

    def screenshot(self):
        f = self._cur()
        self.shots += 1
        return f[0]

    def text_lines(self, img=None):
        f = self.frames[min(max(0, self.shots - 1), len(self.frames) - 1)]
        return [{"text": t, "x": 0, "y": 0, "w": 10, "h": 10} for t in f[1]]


class Hands:
    def __init__(self):
        self.sent = []

    def send(self, cmd, wait=0.5):
        self.sent.append(cmd)
        return "OK " + cmd.split(" ")[0]


class Nav:
    def __init__(self, frames):
        self.e, self.h = Eyes(frames), Hands()


def main():
    print("== 1. Ảnh mẫu ==")
    ok(sc.ref_texts(["Shop", "Shop", "OK", "12,500", "nkha@example.org", "User ID: ABCD-123-456", "Mã 123456", "Đăng nhập", "Coins 1,050"])
       == ["shop", "dang nhap", "coins 9,999"], "chữ chuẩn hoá (bỏ dấu, số → 9), bỏ trùng / ngắn / toàn số / email / mã người chơi / số dài",
       sc.ref_texts(["Shop", "Shop", "OK", "12,500", "nkha@example.org", "User ID: ABCD-123-456", "Mã 123456", "Đăng nhập", "Coins 1,050"]))
    img = screen()
    ref = sc.capture(img, MAIN + ["fotbal"], MAIN + ["apotb-l"])
    ok(ref["texts"] == [sc.text_key(t) for t in MAIN] and ref["w"] == 1334 and ref["h"] == 750 and sc.ref_image(ref) is not None
       and max(sc.ref_image(ref).shape[:2]) == sc.SHOT_SIDE, "hai lần đọc: chỉ giữ chữ chung (chữ rác của logo bị bỏ); ảnh thu nhỏ đọc lại được")
    ok(len(ref["img"]) < 60000, "ảnh mẫu nhỏ (lưu được trong kịch bản)", len(ref["img"]))

    print("== 2. So khớp ==")
    s1 = sc.score(ref, screen(seed=5), MAIN[:6] + ["Coins 2,100"])
    ok(s1["ok"] and s1["how"] == "chữ", "cùng màn (thiếu vài chữ, hình động khác) → khớp theo chữ", s1)
    s2 = sc.score(ref, img, SHOP)
    ok(not s2["ok"] and s2["how"] == "chữ", "màn khác (Shop) → khác", s2)
    s3 = sc.score(ref, img, ["Special Offer", "Buy now", "Close"])
    ok(not s3["ok"], "quảng cáo che hết màn chính → khác", s3)
    few = sc.capture(img, ["Sign Players"])
    s4 = sc.score(few, img, ["Sign Players"])
    s5 = sc.score(few, screen((200, 30, 30), seed=9), ["Sign Players"])
    ok(s4["ok"] and s4["how"] == "hình" and not s5["ok"], "ít chữ → so bằng hình: cùng ảnh khớp, ảnh khác hẳn thì khác", (s4, s5))
    ok(sc.image_score(few, screen(w=750, h=1334)) == 0.0, "khác chiều (dọc / ngang) → không giống")
    ok(sc.wants_check({"type": "tap_text", "text": "Shop", "screen": ref}) and not sc.wants_check({"type": "tap_text", "screen": ref, "screen_check": False})
       and not sc.wants_check({"type": "tap_if", "screen": ref}) and not sc.wants_check({"type": "tap_text"}),
       "chỉ kiểm bước thao tác có ảnh mẫu, không bị tắt")

    ad = sc.capture(img, ["Coins 1,050", "Price 1,050 GP", "Buy 120 Coins", "Shop"])
    ok(not sc.score(ad, img, ["Ad", "Install", "120"])["ok"], "con số lẻ trên màn quảng cáo («120») không «khớp» mọi dòng mẫu có số")
    ok(sc.ref_texts(["Name: Hoang Anh", "Ten: Duong", "090 123 4567", "Gift Box"]) == ["gift box"], "bỏ dòng tên / số điện thoại viết cách")

    print("== 3. Kiểm trước bước (apimode.screen_gate / run_steps) ==")
    apimode.SCREEN_WAIT = 0.6
    real_sleep = apimode._sleep
    apimode._sleep = lambda sec, abort=None: (abort and abort() and (_ for _ in ()).throw(apimode.Aborted())) or time.sleep(min(sec, 0.05))
    step = {"type": "key", "name": "enter", "screen": ref}
    nav = Nav([(img, MAIN)])
    ok(apimode.screen_gate(nav, step) == (True, ""), "khớp ngay → làm bước")
    nav = Nav([(img, SHOP), (img, SHOP), (img, MAIN)])
    ok(apimode.screen_gate(nav, step) == (True, ""), "lúc đầu khác (đang chuyển màn), khớp trong lúc chờ → làm bước")
    nav = Nav([(img, SHOP)])
    r = apimode.screen_gate(nav, step)
    ok(r[0] is False and "khác ảnh mẫu" in r[1], "khác mãi, không có bộ xử lý (chạy thử / AI điều khiển) → không làm, nêu lý do", r)
    got = []
    nav = Nav([(img, SHOP)])
    nav.screen_helper = lambda st, why, im: got.append((st, why, im)) or (True, "")
    ok(apimode.screen_gate(nav, step) == (True, "") and got and got[0][0] is step and got[0][2] is not None, "khác mãi, có bộ xử lý (chạy thật) → giao cho nó")
    got.clear()
    nav = Nav([(img, SHOP)])
    nav.screen_helper = lambda st, why, im: got.append(st) or (True, "")
    r = apimode.screen_gate(nav, dict(step, optional=True))
    ok(r[0] is False and not got, "bước «bỏ qua nếu lỗi» màn hình khác (lúc chạy thật) → bỏ qua, KHÔNG tạm dừng máy", (r, got))

    class Flaky(Eyes):
        def __init__(self, frames, fails):
            super().__init__(frames)
            self.fails = fails

        def screenshot(self):
            if self.fails > 0:
                self.fails -= 1
                raise RuntimeError("usbmux lỗi")
            return super().screenshot()
    nav = Nav([(img, MAIN)]); nav.e = Flaky([(img, MAIN)], 2)
    ok(apimode.screen_gate(nav, step) == (True, ""), "chụp màn hình lỗi tạm thời → nhìn lại, khớp thì làm bước (không hỏng cả lượt)")
    nav = Nav([(img, MAIN)]); nav.e = Flaky([(img, MAIN)], 999)
    r = apimode.screen_gate(nav, step)
    ok(r[0] is False and "không đọc được màn hình" in r[1], "chụp lỗi mãi → không làm bước, nêu lý do (không ném lỗi)", r)
    got.clear()
    nav = Nav([(img, MAIN)]); nav.e = Flaky([(img, MAIN)], 999)
    nav.screen_helper = lambda st, why, im: got.append(im) or (True, "")
    ok(apimode.screen_gate(nav, step) == (True, "") and got == [None], "chụp lỗi mãi lúc chạy thật → giao cho bộ xử lý (tạm dừng chờ admin), không có ảnh")
    nav = Nav([(img, SHOP)])
    ok(apimode.screen_gate(nav, step)[0] is False and any(c == "home" for c in nav.h.sent), "màn hình khác ở lần nhìn đầu → cất con trỏ ra góc rồi mới nhìn lại")
    nav = Nav([(img, SHOP)])
    try:
        apimode.screen_gate(nav, step, abort=lambda: True)
        ok(False, "bị «Dừng ngay» trong lúc chờ → Aborted")
    except apimode.Aborted:
        ok(True, "bị «Dừng ngay» trong lúc chờ → Aborted")
    real_exec = apimode.exec_step
    done = []
    apimode.exec_step = lambda nav, st, vars, abort=None: done.append(st) or (True, "", True)
    try:
        nav = Nav([(img, SHOP)])
        r = apimode.run_steps(nav, [{"type": "home"}, step, {"type": "key", "name": "tab"}], {})
        ok(r[0] is False and r[2] == 1 and done == [{"type": "home"}] and "khác ảnh mẫu" in r[1], "run_steps: màn hình khác → dừng TRƯỚC bước đó, không làm nó", r)
        done.clear()
        nav = Nav([(img, SHOP)])
        r = apimode.run_steps(nav, [dict(step, optional=True), {"type": "key", "name": "tab"}], {})
        ok(r[0] is True and done == [{"type": "key", "name": "tab"}], "bước «bỏ qua nếu lỗi» màn hình khác → bỏ qua bước đó, làm tiếp", done)
    finally:
        apimode.exec_step = real_exec

    print("== 4. engine.run_flow: chạy thật kiểm, chạy thử chụp ảnh mẫu ==")
    real_run = engine.run_step
    done = []
    engine.run_step = lambda nav, st, log=print: done.append(st) or (True, "ok")
    real_cap = apimode.capture_screen
    try:
        nav = Nav([(img, SHOP)])
        res = engine.run_flow(nav, [step, {"type": "key", "name": "tab"}], log=lambda *a: None)
        ok(len(res) == 1 and res[0]["ok"] is False and not done, "chạy thật: màn hình khác → bước không làm, kịch bản dừng", res)
        apimode.capture_screen = lambda nav: {"v": 1, "img": "x", "texts": ["shop"], "w": 1, "h": 1}
        done.clear()
        nav = Nav([(img, SHOP)])
        res = engine.run_flow(nav, [step, {"type": "tap_text", "text": "Shop"}, {"type": "wait", "seconds": 0}], log=lambda *a: None, capture=True)
        ok(len(done) == 3 and "screen" not in res[0] and res[1].get("screen", {}).get("texts") == ["shop"] and "screen" not in res[2],
           "chạy thử: không kiểm; chụp ảnh mẫu cho bước thao tác CHƯA có (bước đã có / bước chờ thì không)", res)
        apimode.capture_screen = lambda nav: (_ for _ in ()).throw(RuntimeError("chụp hỏng"))
        res = engine.run_flow(Nav([(img, SHOP)]), [{"type": "tap_text", "text": "Shop"}], log=lambda *a: None, capture=True)
        ok(res[0]["ok"] and "screen" not in res[0], "chụp ảnh mẫu hỏng → lượt chạy thử vẫn chạy bình thường")
    finally:
        engine.run_step = real_run
        apimode.capture_screen = real_cap
    apimode._sleep = real_sleep

    print("== 4b. Giai đoạn MUA cũng được kiểm ==")
    apimode._sleep = lambda sec, abort=None: (abort and abort() and (_ for _ in ()).throw(apimode.Aborted())) or time.sleep(min(sec, 0.02))

    class BuyEyes(Eyes):
        def read_text(self, img=None, *a, **k):
            return " ".join(self._cur()[1])
    sent = []
    real_exec = apimode.exec_step
    apimode.exec_step = lambda nav, st, vars, abort=None: sent.append(st) or (True, "", True)
    try:
        for plist, label in (([dict(step)], "màn hình khác ở bước mua ĐẦU TIÊN → không bấm gì, «lỗi tool» (chưa chạm vào máy)"),
                             ([{"type": "key", "name": "tab"}, dict(step)], "đã chạm một bước rồi mới gặp màn hình khác → không làm bước đó, «không chắc» (không báo «chưa mua»)")):
            sent.clear()
            nav = Nav([(img, SHOP)]); nav.e = BuyEyes([(img, SHOP)])
            steps = {"login": [], "finish": [], "otp": [], "nav": [], "after": [], "purchase": plist}
            jf = apimode.JobFlow(nav, None, {"id": "J", "items": [{"code": "c", "name": "1050 Coins", "qty": 1}]}, {"rules": []}, steps,
                                 opts={"purchase_wait": 0.3, "clear_wait": 0.1}, log=lambda *a, **k: None)
            jf.PRE_LOOKS = 1
            v, why = jf._buy_one({"code": "c", "name": "1050 Coins", "qty": 1}, {})
            if len(plist) == 1:
                ok(v == "failed_tool" and not sent and "khác ảnh mẫu" in why, label, (v, why, sent))
            else:
                ok(v != "failed" and v != "ok" and jf.risky and sent == [{"type": "key", "name": "tab"}], label, (v, why, sent, jf.risky))
    finally:
        apimode.exec_step = real_exec
        apimode._sleep = real_sleep

    print("== 5. Bộ chạy: tạm dừng chờ admin ==")
    import runner as runmod
    R = runmod.Runner(lambda n: None)
    alerts = []
    R.alert = lambda ev, name, lines, photo=None: alerts.append((ev, name, lines, photo))

    def worker(job=None):
        return {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False, "name": "M1",
                "group_name": "Efootball", "script_name": "nạp", "job_id": job}
    for how, expect in (("resume", (True, "")), ("stop", False), ("abort", "Aborted")):
        w = worker()
        R.workers["M1"] = dict(w, thread=threading.current_thread())
        out = {}

        def go():
            try:
                out["r"] = R._admin_pause("M1", w, step, "màn hình khác ảnh mẫu của bước", img)
            except apimode.Aborted:
                out["r"] = "Aborted"
        alerts.clear()
        th = threading.Thread(target=go); th.start(); time.sleep(0.3)
        paused = R.is_parked("M1") and w["paused"] and "TẠM DỪNG" in w["status"]
        if how == "resume":
            R.resume_machine("M1")
        elif how == "stop":
            w["stop"].set()
        else:
            w["abort"].set()
        th.join(3)
        r = out.get("r")
        good = r == expect if how != "stop" else (isinstance(r, tuple) and r[0] is False)
        ok(paused and good and not th.is_alive(), "màn hình lạ → máy TẠM DỪNG; %s → %s" % (
            {"resume": "admin bấm Tiếp tục", "stop": "bấm Dừng", "abort": "Dừng ngay"}[how], expect), (paused, r))
        R.parked.discard("M1")
    ev = alerts[0] if alerts else None
    ok(ev and ev[0] == "paused" and ev[1] == "M1" and ev[3] and ev[3][:2] == b"\xff\xd8" and any("Bước:" in x for x in ev[2])
       and any("Tiếp tục" in x for x in ev[2]), "báo Telegram «Máy dừng chờ admin» kèm ảnh màn hình (JPEG), bước, cách xử lý", ev and ev[:3])
    for wk, label in ((worker(job="J1"), "đang làm đơn của khách"), (dict(worker(), mode="api"), "máy nhận đơn (vd bước đăng xuất sau đơn, «Chạy lại» máy đang giữ)")):
        R.workers["M1"] = dict(wk, thread=threading.current_thread())
        alerts.clear()
        th = threading.Thread(target=lambda: R._admin_pause("M1", wk, step, "khác", img)); th.start(); time.sleep(0.2)
        R.resume_machine("M1"); th.join(3)
        ok(alerts and alerts[0][3] is None, label + " → báo KHÔNG kèm ảnh màn hình", alerts and alerts[0][3])
        R.parked.discard("M1")
    w = worker(); w["stop"].set(); alerts.clear()
    r = R._admin_pause("M1", w, step, "khác", img)
    ok(r[0] is False and not alerts and not R.is_parked("M1") and not w["pause"].is_set(), "đã bấm Dừng từ trước → không tạm dừng, không báo «chờ admin»", (r, alerts))
    w = dict(worker(), mode="api", status="Đang làm đơn DH-1")
    w["pause"].set(); R.parked.add("M1")                        # người vận hành đã bấm «Tạm dừng» (không nhận đơn mới) từ trước
    R.workers["M1"] = dict(w, thread=threading.current_thread())
    th = threading.Thread(target=lambda: R._admin_pause("M1", w, step, "khác", img)); th.start(); time.sleep(0.2)
    R.resume_machine("M1"); th.join(3)
    ok(not th.is_alive() and w["pause"].is_set() and R.is_parked("M1") and w["status"] == "Đang làm đơn DH-1",
       "máy nhận đơn đã được bấm «Tạm dừng» từ trước: Tiếp tục làm tiếp bước nhưng VẪN giữ yêu cầu không nhận đơn mới; trạng thái cũ được trả lại",
       (w["pause"].is_set(), R.is_parked("M1"), w["status"]))
    R.parked.discard("M1")

    class N:
        pass
    n = N()
    w = worker()
    R._seen_nav(w, n)
    ok(callable(getattr(n, "screen_helper", None)) and w.get("nav") is n, "bắt đầu chạy thật → máy có bộ xử lý màn hình lạ")
    w["thread"] = threading.current_thread()
    R._guard(lambda *a: None, "M1", {}, w)
    ok(n.screen_helper is None, "lần chạy kết thúc → gỡ bộ xử lý (chạy thử / AI sau đó không bị tạm dừng)")

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
