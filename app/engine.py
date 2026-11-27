#!/usr/bin/env python3
"""
engine.py — chạy flow (danh sách bước) trên 1 thiết bị (Nav).

Mỗi bước là dict JSON, ví dụ:
  {"type":"tap","x":300,"y":400}
  {"type":"tap_text","text":"Mua"}                      # thêm "timeout":5 = chữ chưa hiện thì chờ tối đa 5 giây (không ghi = nhìn một lần)
  {"type":"type","text":"hello"}                        # thêm "gap":0.4 = gõ TỪNG ký tự, nghỉ 0,4 giây (ô mã mỗi số một ô)
  {"type":"key","name":"enter"}
  {"type":"combo","keys":"gui h"}
  {"type":"home"}
  {"type":"launch","app":"efootball"}                    # thêm "fresh":true = TẮT HẲN app rồi mở mới qua USB (luôn bắt đầu từ màn đầu)
  {"type":"wait","seconds":1.5}
  {"type":"wait_text","text":"Shop","timeout":15}
  {"type":"assert_text","text":"Success"}
  {"type":"swipe","dir":"left"}                         # left|right (lật trang) | up|down (cuộn)
  {"type":"swipe","x1":375,"y1":1000,"x2":375,"y2":400} # vuốt theo toạ độ (quãng thực tế chỉ xấp xỉ)
  {"type":"hold","x":636,"y":468,"seconds":1.2}         # bấm giữ
  {"type":"hold_text","text":"Sách","seconds":1.2}
  {"type":"tap_image","image":"<PNG base64>","timeout":5}   # tìm đúng HÌNH đã cắt từ ảnh màn hình rồi bấm vào giữa nó (thay cho toạ độ cố định)
  {"type":"tap_if","text":"Game Center","tap":"Hủy","timeout":8}   # nếu (trong 8 giây) thấy chữ «Game Center» thì bấm «Hủy»; không thấy → xong
"""
from __future__ import annotations
import time

import apimode

STEP_TYPES = ["tap", "tap_text", "tap_image", "tap_if", "type", "key", "combo", "home",
              "launch", "wait", "wait_text", "assert_text", "swipe", "hold", "hold_text"]


def run_step(nav, step, log=print):
    """Chạy 1 bước. Trả (ok: bool, message: str). Máy có bộ theo dõi (nav.observer) thì báo cho nó lúc bắt đầu / xong bước."""
    obs = getattr(nav, "observer", None)
    if obs is None:
        return _run_step(nav, step, log)
    try:
        obs.step_begin(apimode.observed_what(step, {}), step.get("type"))
    except Exception:
        return _run_step(nav, step, log)
    try:
        ok, msg = _run_step(nav, step, log)
    except BaseException:
        obs.step_end(False, "lỗi")
        raise
    obs.step_end(ok, "" if ok else apimode.observed_why(step, msg))
    return ok, msg


def _run_step(nav, step, log=print):
    t = step.get("type")
    try:
        if t == "tap":
            ok = nav.tap_at(int(step["x"]), int(step["y"]))
            return ok, f"tap ({step['x']},{step['y']}) {'OK' if ok else 'con trỏ không tới nơi → KHÔNG bấm'}"
        if t == "tap_if":                           # cùng MỘT cách làm với lúc nhận đơn (dò chữ nhiều cách viết, bấm có kiểm lại)
            ok, why, _ = apimode.exec_step(nav, step, {})
            return ok, why or ("xong" if ok else "không thực hiện được")
        # Bấm vào vùng ảnh / có ghi «chờ chữ hiện ra» / «tắt hẳn rồi mở mới» / «gõ từng ký tự»: cùng MỘT cách làm với lúc nhận đơn
        if t == "tap_image" or (t in ("tap_text", "hold_text") and step.get("timeout")) or (t == "launch" and step.get("fresh")) or (t == "type" and step.get("gap")) \
                or (t in ("tap_text", "assert_text") and (step.get("near") or step.get("scroll"))):
            ok, why, _ = apimode.exec_step(nav, step, {})
            return ok, apimode.describe(step, {}) + ((" — " + why) if why else "")
        if t == "tap_text":
            ok = nav.tap_text(step["text"])
            return ok, f"tap_text '{step['text']}' {'OK' if ok else 'không thấy chữ / con trỏ không tới nơi → KHÔNG bấm'}"
        # Sau mỗi lệnh BÀN PHÍM nghỉ một nhịp (lệnh xuống board giờ trả về ngay khi board làm xong; trước đây mỗi
        # lệnh tự trễ thêm ~0,4s và các kịch bản đã quen với nhịp đó: ô nhập kịp nhận chữ, kịp chuyển ô sau Tab).
        if t == "type":
            nav.h.type(step["text"]); time.sleep(0.4)
            return True, f"gõ '{step['text']}'"
        if t == "key":
            nav.h.key(step["name"]); time.sleep(0.4)
            return True, f"phím {step['name']}"
        if t == "combo":
            keys = apimode.combo_keys(step["keys"])     # sai dạng → ném lỗi, báo ra ở dưới (không gửi thứ lạ xuống board)
            nav.h.do("combo " + keys); time.sleep(0.4)
            return True, f"combo {keys}"
        if t == "home":
            nav.home_screen()
            return True, "về home"
        if t == "launch":
            # (quãng nghỉ: Spotlight phải mở ra và CHỌN xong kết quả đầu rồi Enter mới mở được app)
            nav.h.do("combo gui h"); time.sleep(1.1)
            nav.h.do("combo gui space"); time.sleep(1.7)
            nav.h.do("combo cmd a"); time.sleep(0.5); nav.h.key("back"); time.sleep(0.8)
            nav.h.type(step["app"]); time.sleep(1.7)
            nav.h.key("enter"); time.sleep(3.0)
            return True, f"mở app '{step['app']}'"
        if t == "wait":
            time.sleep(float(step.get("seconds", 1)))
            return True, f"chờ {step.get('seconds',1)}s"
        if t == "wait_text":
            needle = step["text"]; timeout = float(step.get("timeout", 15))
            end = time.time() + timeout
            while time.time() < end:
                txt = nav.e.read_text().lower()
                if needle.lower() in txt:
                    return True, f"thấy '{needle}'"
                time.sleep(1)
            return False, f"hết giờ chờ '{needle}'"
        if t == "assert_text":
            time.sleep(0.9)                     # chờ màn hình đứng yên rồi mới nhìn (ảnh chụp giờ tức thì)
            txt = nav.e.read_text().lower()
            ok = step["text"].lower() in txt
            return ok, f"kiểm '{step['text']}' {'có' if ok else 'KHÔNG thấy'}"
        if t == "swipe":
            if step.get("dir"):
                ok = nav.flick(str(step["dir"]).lower())
                return ok, f"vuốt {step['dir']} {'OK' if ok else 'không thực hiện được'}"
            ok = nav.swipe(int(step["x1"]), int(step["y1"]), int(step["x2"]), int(step["y2"]))
            return ok, f"vuốt ({step['x1']},{step['y1']})→({step['x2']},{step['y2']}) {'OK' if ok else 'không thực hiện được'}"
        if t == "hold":
            sec = max(0.2, min(float(step.get("seconds", 1.0)), 10.0))
            ok = nav.hold_at(int(step["x"]), int(step["y"]), sec)
            return ok, f"bấm giữ ({step['x']},{step['y']}) {sec}s {'OK' if ok else 'con trỏ không tới nơi → KHÔNG bấm'}"
        if t == "hold_text":
            sec = max(0.2, min(float(step.get("seconds", 1.0)), 10.0))
            time.sleep(0.9)
            pos = nav.e.find_text(step["text"], nav.e.screenshot())
            if not pos:
                return False, f"bấm giữ '{step['text']}': không thấy chữ"
            ok = nav.hold_at(pos[0], pos[1], sec)
            return ok, f"bấm giữ '{step['text']}' {sec}s {'OK' if ok else 'con trỏ không tới nơi → KHÔNG bấm'}"
        return False, f"bước lạ: {t}"
    except Exception as e:
        return False, f"lỗi {t}: {e}"


def run_flow(nav, steps, log=print, stop_on_fail=True, stop_check=None, pause_gate=None):
    """Chạy cả flow. Trả list kết quả [{i, type, ok, msg}].
    stop_check: hàm trả True để DỪNG giữa chừng (dùng khi dừng 1 máy).
    pause_gate: hàm được gọi TRƯỚC mỗi bước; đang «tạm dừng» thì nó chặn ở đó (người xử lý tay) cho tới khi tiếp tục hoặc bị dừng."""
    results = []
    apimode.watch_phase(nav, None, len(steps))
    for i, step in enumerate(steps):
        if pause_gate:
            pause_gate()
        if stop_check and stop_check():
            log("  ⟂ đã dừng theo yêu cầu")
            break
        ok, msg = run_step(nav, step, log)
        log(f"[{i+1}/{len(steps)}] {step.get('type')}: {msg}")
        results.append({"i": i, "type": step.get("type"), "ok": ok, "msg": msg})
        if not ok and stop_on_fail and not step.get("optional"):     # bước «bỏ qua nếu lỗi» thì đi tiếp
            log(f"  ⟂ dừng vì bước {i+1} thất bại")
            break
        time.sleep(0.3)
    return results
