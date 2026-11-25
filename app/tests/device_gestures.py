#!/usr/bin/env python3
"""
Thử CỬ CHỈ trên iPhone THẬT — bấm vào một điểm, bấm app theo tên, lật trang, cuộn, bấm giữ:

    ./.venv/bin/python app/tests/device_gestures.py <tên máy> [nhóm thử]
    ./.venv/bin/python app/tests/device_gestures.py iPhoneFarm-01
    ./.venv/bin/python app/tests/device_gestures.py iPhoneFarm-01 tap,swipe      # chỉ vài nhóm: tap,name,swipe,scroll,hold

TẮT app iPhone Farm Manager trước khi chạy (cổng serial của board chỉ một chương trình mở được).

Dùng đúng các hàm của tool (Nav.tap_at / hold_at / flick) và chỉ làm việc vô hại: mở vài app có sẵn rồi về màn hình
chính, lật trang, cuộn trong Cài đặt, bấm giữ để hiện menu rồi thoát. Toạ độ dưới đây là của MÀN HÌNH CHÍNH MẶC ĐỊNH
trên iPhone 8 (750×1334, iOS 16, tiếng Việt): hàng 1 FaceTime·Lịch·Ảnh·Camera, hàng 2 Mail·Đồng hồ·Bản đồ·Thời tiết,
hàng 3 Lời nhắc·Ghi chú·Chứng khoán·Sách, hàng 5 có Cài đặt, Safari ở dock. Máy xếp icon khác thì sửa bảng TAPS.

Chạy lại script này sau khi đổi board, đổi firmware, đổi iOS, hoặc sửa code ở nav.py / hands.py / eyes.py.
"""
from __future__ import annotations
import os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

import cv2

import apimode, esp, store
from eyes import norm_text
from nav import Nav

TAPS = [("icon Ghi chú (288,468)", 288, 468, ()), ("icon Cài đặt (462,820)", 462, 820, ("Bluetooth", "Wi-Fi")),
        ("icon Đồng hồ (288,292) — có kim giây chạy", 288, 292, ()), ("icon Safari ở dock (282,1240)", 282, 1240, ())]
BY_NAME = ("Sách", "Podcast")
SETTINGS = (462, 820)
BOOKS = (636, 468)
EMPTY = (600, 950)


def open_nav(name: str) -> Nav:
    port = None
    for _ in range(8):                  # cổng mở độc quyền: chương trình khác đang dò thì thử lại
        port = next((b["port"] for b in esp.list_boards() if (esp.probe(b["port"]) or {}).get("name") == name), None)
        if port:
            break
        time.sleep(0.5 + random.random() * 2)
    udid = next((d.get("udid") for d in store.get_devices() if d.get("name") == name), None)
    if not port or not udid:
        raise SystemExit("Không thấy board/iPhone của «%s» (board: %s, iPhone đã gán: %s). Đã tắt app chưa?" % (name, port or "không thấy", "có" if udid else "chưa"))
    return Nav(port, udid)


def changed(a, b, thr: int = 25) -> float:
    """Tỉ lệ điểm ảnh khác nhau giữa hai ảnh (0…1)."""
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    return float((cv2.absdiff(a, b).max(axis=2) > thr).mean())


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"tap", "name", "swipe", "scroll", "hold"}
    out = os.path.join(ROOT, "shots")
    os.makedirs(out, exist_ok=True)
    nav = open_nav(name)
    res = []

    def snap(tag=None):
        img = nav.e.screenshot()
        if tag:
            cv2.imwrite(os.path.join(out, "gestures_%s_%s.png" % (name, tag)), cv2.resize(img, (375, 667)))
        return img

    def txt(img):
        return norm_text(nav.e.read_text(img))

    def has(img, *alts):
        t = txt(img)
        return any(apimode.text_has(t, a) for a in alts)

    def page(img):
        if has(img, "FaceTime") and has(img, "App Store"):
            return 1
        return 2 if has(img, "iTunes", "Watch", "Phím tắt", "Danh bạ", "Dịch thuật", "Freeform", "Messenger") else 0

    def dots(img):
        """Chấm chỉ trang ở đáy màn hình chính: chấm nào sáng hơn = đang ở trang đó (1 | 2)."""
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(int)
        a, b = g[1114:1130, 350:366].mean(), g[1114:1130, 384:400].mean()
        return 1 if a > b + 12 else (2 if b > a + 12 else 0)

    def home():
        """Về TRANG 1 màn hình chính từ bất cứ đâu."""
        for _ in range(6):
            nav.h.do("combo gui h"); time.sleep(1.1)
            img = snap(); p = page(img)
            if p == 1:
                return img
            if p == 2:
                nav.flick("right"); time.sleep(1.3)
                continue
            for b in ("Hủy", "Không cho phép", "Để sau", "Cancel"):      # hộp thoại hệ thống chặn phím Home
                pos = nav.e.find_text(b, img)
                if pos:
                    print("     (có hộp thoại → bấm «%s»: %s)" % (b, nav.tap_at(pos[0], pos[1]))); time.sleep(1.3)
                    break
            else:
                nav.flick("left"); time.sleep(1.3)                       # trang widget → trang 1
        return snap()

    def note(label, ok, extra=""):
        res.append(bool(ok))
        print("  %s %-56s %s" % ("✓" if ok else "✗", label, extra)); sys.stdout.flush()

    try:
        why = apimode.preflight(nav)
        print("Máy %s: %s" % (name, why or "sẵn sàng"))
        if why:
            return 1
        base = home()
        if page(base) != 1:
            print("Không về được trang 1 của màn hình chính: " + txt(base)[:80])
            return 1
        if "tap" in only:
            print("— BẤM VÀO 1 ĐIỂM (toạ độ) —")
            for label, x, y, exp in TAPS:
                b = home(); t = time.time(); ok = nav.tap_at(x, y); dt = time.time() - t; time.sleep(2.3); img = snap()
                note(label, ok and changed(b, img) > 0.3 and (not exp or has(img, *exp)), "%.0fs, đổi %.0f%%" % (dt, changed(b, img) * 100))
        if "name" in only:
            print("— BẤM APP THEO TÊN (dò chữ dưới icon → bấm vào icon phía trên) —")
            for app in BY_NAME:
                b = home(); pos = nav.e.find_text(app, b)
                ok = bool(pos) and nav.tap_at(pos[0], pos[1] - 88); time.sleep(2.3); img = snap()
                note("app «%s» (chữ ở %s)" % (app, pos), ok and changed(b, img) > 0.3, "đổi %.0f%%" % (changed(b, img) * 100))
        if "swipe" in only:
            print("— VUỐT QUA TRANG —")
            p1 = home()
            ok = nav.flick("left"); time.sleep(1.3); p2 = snap("page2")
            note("vuốt TRÁI: trang 1 → trang 2", ok and page(p2) != 1 and dots(p2) == 2 and changed(p1, p2) > 0.15, "chấm trang=%s, đổi %.0f%%" % (dots(p2), changed(p1, p2) * 100))
            ok = nav.tap_at(288, 468); time.sleep(3.0); g = snap()
            note("bấm 1 app ở trang 2 (288,468)", ok and changed(p2, g) > 0.3, "đổi %.0f%%" % (changed(p2, g) * 100))
            nav.h.do("combo gui h"); time.sleep(1.2); cur = snap()
            if dots(cur) != 2:
                nav.flick("left"); time.sleep(1.3)
            ok = nav.flick("right"); time.sleep(1.3); b1 = snap()
            note("vuốt PHẢI: trang 2 → trang 1", ok and page(b1) == 1 and dots(b1) == 1, "khác trang 1 lúc đầu %.0f%%" % (changed(p1, b1) * 100))
            ok = nav.flick("right"); time.sleep(1.3); tv = snap("today")
            note("vuốt PHẢI lần nữa → trang widget", ok and page(tv) != 1 and changed(p1, tv) > 0.4, "đổi %.0f%%" % (changed(p1, tv) * 100))
            ok = nav.flick("left", at=0.2); time.sleep(1.3); b2 = snap()
            note("vuốt TRÁI: trang widget → trang 1", ok and page(b2) == 1, "khác trang 1 lúc đầu %.0f%%" % (changed(p1, b2) * 100))
        if "scroll" in only:
            print("— CUỘN TRONG APP (Cài đặt) —")
            home(); nav.tap_at(*SETTINGS); time.sleep(2.5); s0 = snap()
            row = lambda img: (nav.e.find_text("Bluetooth", img) or (None, None))[1]
            y0 = row(s0)
            if y0 is None:
                note("mở Cài đặt", False, txt(s0)[:60])
            else:
                ok = nav.flick("up"); time.sleep(1.8); s1 = snap(); y1 = row(s1)
                note("vuốt LÊN: danh sách trôi lên", ok and (y1 is None or y1 < y0 - 60), "dòng «Bluetooth»: y=%s → %s" % (y0, y1))
                ok = nav.flick("down"); time.sleep(1.8); s2 = snap(); y2 = row(s2)
                note("vuốt XUỐNG: trôi ngược lại", ok and y2 is not None and (y1 is None or y2 > y1 + 60), "y=%s → %s" % (y1, y2))
        if "hold" in only:
            print("— BẤM GIỮ —")
            b = home()
            ok = nav.hold_at(BOOKS[0], BOOKS[1], 1.3); time.sleep(1.0); m = snap("hold_icon")
            note("giữ 1.3s trên icon Sách → menu ngữ cảnh", ok and has(m, "Sửa Màn hình chính", "Xóa ứng dụng", "Xoá ứng dụng", "Chia sẻ ứng dụng", "Edit Home Screen"))
            b = home()
            ok = nav.hold_at(EMPTY[0], EMPTY[1], 1.5); time.sleep(1.0); j = snap("hold_empty")
            note("giữ 1.5s vào chỗ trống → chế độ sửa màn hình chính", ok and 0.02 < changed(b, j) < 0.5, "đổi %.0f%%" % (changed(b, j) * 100))
            back = home()
            note("thoát về màn hình chính bình thường", page(back) == 1 and changed(b, back) < 0.06, "khác %.0f%%" % (changed(b, back) * 100))
        good = sum(res)
        print("\n%s Máy %s: ĐẠT %d/%d" % ("✅" if good == len(res) else "❌", name, good, len(res)))
        return 0 if good == len(res) else 1
    finally:
        try:
            nav.h.burst(["up", "move 1 0", "move -1 0"], wait=1.0, urgent=True)
        finally:
            nav.close()


if __name__ == "__main__":
    sys.exit(main())
