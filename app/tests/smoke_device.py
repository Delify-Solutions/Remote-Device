#!/usr/bin/env python3
"""
Thử các thao tác của CHẾ ĐỘ API trên iPhone THẬT — bằng việc vô hại trong app Cài đặt:

    ./.venv/bin/python app/tests/smoke_device.py <tên máy> [số vòng=2]
    ./.venv/bin/python app/tests/smoke_device.py iPhoneFarm-01

TẮT app iPhone Farm Manager trước khi chạy (một cổng serial chỉ một chương trình mở được).

Chạy đúng các bước mà một đơn nạp dùng, theo đúng code lúc nhận đơn (stepexec.py + jobflow.py):
  kiểm máy sẵn sàng → kiểm bàn phím tiếng Anh → mở app qua Spotlight (gõ + Enter) → chờ chữ
  → dò chữ «Wi-Fi» + đưa con trỏ tới + bấm → dò chữ «‹ Cài đặt» + bấm (quay lại) → về màn hình chính.
Chỉ đi lại giữa hai trang của Cài đặt, không bật/tắt gì.

Máy/board mới, đổi cỡ màn hình, đổi iOS → chạy script này trước khi cho máy nhận đơn thật.
"""
from __future__ import annotations
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import jobflow, stepexec, esp, store
from eyes import norm_text
from nav import Nav


def find_port(name: str):
    for b in esp.list_boards():
        if (esp.probe(b["port"]) or {}).get("name") == name:
            return b["port"]
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name, rounds = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2
    udid = next((d.get("udid") for d in store.get_devices() if d.get("name") == name), None)
    port = find_port(name)
    if not udid or not port:
        print("Không tìm thấy máy «%s» (board: %s, iPhone đã gán: %s). Mở app → Thiết bị để kiểm tra." % (name, port or "không thấy", "có" if udid else "chưa"))
        return 2
    nav = Nav(port, udid)
    bad = []

    def screen():
        return norm_text(nav.e.read_text(nav.e.screenshot()))

    def step(label, steps):
        t = time.time()
        try:
            ok, why, _, _ = stepexec.run_steps(nav, steps, {})
        except Exception as e:                                   # lỗi cấu hình / mất chụp màn…
            ok, why = False, "%s: %s" % (type(e).__name__, e)
        print("  %s %-44s %5.1fs%s" % ("✓" if ok else "✗", label, time.time() - t, ("   → " + why) if why else ""))
        if not ok:
            bad.append(label)
        return ok

    def wait_gone(text, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if not stepexec.text_has(screen(), text):
                return True
        return False

    try:
        why = jobflow.preflight(nav)
        print("Máy %s (%s): %s" % (name, port, why or "sẵn sàng"))
        if why:
            return 1
        t = time.time()
        en, seen = nav.ensure_english()
        print("  %s %-44s %5.1fs" % ("✓" if en else "✗", "bàn phím cứng đang là tiếng Anh", time.time() - t))
        if not en:
            bad.append("bàn phím đang ở bộ gõ tiếng Việt (Telex/VNI)" if nav.kb_reason == "ime"
                       else "không đọc được chữ gõ thử để kiểm bàn phím (đọc được %r)" % seen)
        if step("mở app Cài đặt qua Spotlight", [{"type": "launch", "app": "Settings"}]) and \
           step("chờ thấy danh sách Cài đặt", [{"type": "wait_text", "text": "Bluetooth", "timeout": 12}]):
            for n in range(rounds):
                if not step("vòng %d: dò chữ «Wi-Fi» + bấm" % (n + 1), [{"type": "tap_text", "text": "Wi-Fi"}]):
                    break
                opened = wait_gone("Bluetooth")
                print("  %s %-44s" % ("✓" if opened else "✗", "         → trang Wi-Fi đã mở"))
                if not opened:
                    bad.append("bấm «Wi-Fi» nhưng trang không đổi")
                    break
                if not step("vòng %d: dò chữ «‹ Cài đặt» + bấm quay lại" % (n + 1),
                            [{"type": "tap_text", "text": "Cài đặt|Settings"}, {"type": "wait_text", "text": "Bluetooth", "timeout": 10}]):
                    break
            step("bước «bỏ qua nếu lỗi» không có trên màn", [{"type": "tap_text", "text": "KhongCoChuNay123", "optional": True}])
            jpg = jobflow.shot_jpeg(nav)
            print("  %s %-44s %s" % ("✓" if jpg else "✗", "chụp ảnh JPEG (ảnh bill gửi gateway)", ("%d KB" % (len(jpg) // 1024)) if jpg else ""))
            if not jpg:
                bad.append("chụp ảnh")
        step("về màn hình chính", [{"type": "home"}])
    finally:
        nav.close()
    print("\n" + ("✅ Máy %s chạy được đủ các thao tác của chế độ API." % name if not bad else "❌ Chưa đạt: " + "; ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
