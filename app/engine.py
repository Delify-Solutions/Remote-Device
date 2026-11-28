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

def run_step(nav, step):
    """Chạy 1 bước của kịch bản. Trả (ok: bool, message: str) — lời mô tả bước, kèm lý do khi có.
    MỘT bộ chạy cho mọi nơi: đây chính là apimode.exec_step — cùng cách làm với lúc nhận đơn (dò chữ nhiều cách viết, bấm có kiểm lại,
    nhịp bàn phím, báo «máy đang ở bước nào» cho bộ theo dõi). Kịch bản thường không có dữ liệu của đơn nên bước dùng {{biến}} sẽ báo lỗi
    thay vì gõ nguyên chữ {{…}}. Lỗi cấu hình / lỗi bất ngờ → (False, lời báo), không ném ra ngoài."""
    try:
        ok, why, _ = apimode.exec_step(nav, step, {})
    except Exception as e:
        return False, "lỗi %s: %s" % (step.get("type"), e)
    return ok, apimode.describe(step, {}) + ((" — " + why) if why else "")


def capture_ref(nav, step):
    """Ảnh mẫu cho `step` lúc chạy thử: chỉ bước thao tác CHƯA có ảnh mẫu (bước đã có thì giữ nguyên — muốn thay thì bấm «Chụp lại»).
    Chụp hỏng → None (không làm hỏng lượt chạy thử)."""
    import screencheck
    if not isinstance(step, dict) or step.get("type") not in screencheck.CHECK_TYPES or screencheck.valid(step.get("screen")):
        return None
    try:
        return apimode.capture_screen(nav)
    except Exception:
        return None


def _tell(on_step, i, ok=None, msg=""):
    """Báo tiến độ cho người gọi (bộ chạy hiện «máy đang ở bước nào») — trục trặc ở đó không bao giờ làm hỏng lượt chạy."""
    if on_step is not None:
        try:
            on_step(i, ok, msg)
        except Exception:
            pass


def run_flow(nav, steps, log=print, stop_on_fail=True, stop_check=None, pause_gate=None, capture=False, start=0, on_step=None):
    """Chạy cả flow. Trả list kết quả [{i, type, ok, msg}] (`i` = vị trí của bước trong `steps`, kể cả khi chạy từ giữa).
    stop_check: hàm trả True để DỪNG giữa chừng (dùng khi dừng 1 máy).
    pause_gate: hàm được gọi TRƯỚC mỗi bước; đang «tạm dừng» thì nó chặn ở đó (người xử lý tay) cho tới khi tiếp tục hoặc bị dừng.
    capture: CHẠY THỬ trong trình sửa — không kiểm màn hình; bước thao tác CHƯA có ảnh mẫu thì chụp màn hình ngay trước bước, bước làm được
    thì kết quả mang theo ảnh mẫu (`screen`) để giao diện gắn vào bước.
    start: bắt đầu từ bước thứ `start` (0 = đầu) — «chạy tiếp từ bước N» sau khi máy dừng vì lỗi; các bước trước đó KHÔNG làm.
    on_step(i, ok, msg): báo tiến độ — ok=None lúc BẮT ĐẦU bước i (trước cả lúc kiểm màn hình), True / False lúc bước xong."""
    results = []
    start = max(0, min(int(start or 0), len(steps)))
    apimode.watch_phase(nav, None, len(steps), start)
    for i, step in enumerate(steps):
        if i < start:
            continue
        if pause_gate:
            pause_gate()
        if stop_check and stop_check():
            log("  ⟂ đã dừng theo yêu cầu")
            break
        _tell(on_step, i)
        ref = None
        if capture:                                     # chạy thử trong trình sửa: không kiểm màn hình, chụp ảnh mẫu cho bước chưa có
            ref = capture_ref(nav, step)
            seen = True
        else:
            try:
                seen, why = apimode.screen_gate(nav, step, stop_check)
            except apimode.Aborted:
                log("  ⟂ đã dừng theo yêu cầu")
                break
        if not seen:                                    # màn hình không phải màn hình của bước này → KHÔNG làm bước
            log(f"[{i+1}/{len(steps)}] {step.get('type')}: {why}")
            results.append({"i": i, "type": step.get("type"), "ok": False, "msg": why})
            _tell(on_step, i, False, why)
            if step.get("optional"):
                continue
            log(f"  ⟂ dừng vì bước {i+1}: màn hình khác ảnh mẫu")
            break
        ok, msg = run_step(nav, step)
        log(f"[{i+1}/{len(steps)}] {step.get('type')}: {msg}")
        results.append(dict({"i": i, "type": step.get("type"), "ok": ok, "msg": msg}, **({"screen": ref} if ok and ref else {})))
        _tell(on_step, i, bool(ok), msg)
        if not ok and stop_on_fail and not step.get("optional"):     # bước «bỏ qua nếu lỗi» thì đi tiếp
            log(f"  ⟂ dừng vì bước {i+1} thất bại")
            break
        time.sleep(0.3)
    return results
