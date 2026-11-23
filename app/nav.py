#!/usr/bin/env python3
"""
nav.py — điều hướng chuột tuyệt đối bằng cách VỀ GÓC rồi di lượng cố định.

Ý tưởng: con trỏ iOS không đọc được vị trí (mờ nhanh), nhưng:
  - "về góc" (di âm thật nhiều) luôn ghim con trỏ ở (0,0) -> gốc cố định.
  - cùng một chuỗi lệnh move -> con trỏ tới cùng một chỗ (lặp lại được).
Nên ta TÌM 1 lần vector move (ax,ay) click trúng mỗi nút, lưu lại, phát lại mãi.

    from nav import Nav
    n = Nav(port, udid)
    n.home()                 # ghim con trỏ góc trên-trái
    n.tap_move(ax, ay)       # di (ax,ay) từ góc rồi click
"""
from __future__ import annotations
import sys, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from hands import Hands
from eyes import Eyes


class Nav:
    def __init__(self, port: str, udid: str):
        self.h = Hands(port, reset=False)
        self.e = Eyes(udid)
        self.h.wait_connected(15)

    def home(self, reps: int = 2):
        """Ghim con trỏ về góc trên-trái (0,0) — dùng lệnh 'home' nhanh của firmware."""
        for _ in range(reps):
            self.h.do("home")
            time.sleep(0.1)
        time.sleep(0.15)

    def move_from_home(self, ax: int, ay: int):
        """Về góc rồi di (ax,ay)."""
        self.home()
        self.h.move(ax, ay)
        time.sleep(0.2)

    def tap_move(self, ax: int, ay: int):
        """Về góc, di (ax,ay), click."""
        self.move_from_home(ax, ay)
        return self.h.click()

    # tham số calibrate (px = home + units*scale). Mặc định thô, nên chạy calibrate().
    sx = 1.09; sy = 1.0; hx = 15; hy = 15

    def _measure(self, ax, ay):
        """Về góc, di (ax,ay) BƯỚC NHỎ rồi chụp NGAY, trả vị trí con trỏ px."""
        self.home()
        self.h.move(ax, ay)
        img = self.e.screenshot()          # chụp ngay (con trỏ còn sáng)
        return self.e.find_pointer(img)

    def calibrate(self, verbose=True):
        """Đo 3 điểm -> tính scale & gốc. Lưu vào self.sx/sy/hx/hy."""
        pts = {}
        for name, (ax, ay) in {"A": (120, 120), "X": (650, 120), "Y": (120, 900)}.items():
            for _ in range(3):             # thử lại nếu chưa bắt được con trỏ
                p = self._measure(ax, ay)
                if p:
                    pts[name] = (p[0], p[1], ax, ay); break
            if verbose:
                print(f"  {name}: move({ax},{ay}) -> {pts.get(name)}")
        if len(pts) < 3:
            print("  calibrate: chưa bắt đủ con trỏ, thử lại."); return False
        ax1 = pts["A"]; px_x = pts["X"]; px_y = pts["Y"]
        self.sx = (px_x[0] - ax1[0]) / (px_x[2] - ax1[2])
        self.sy = (px_y[1] - ax1[1]) / (px_y[3] - ax1[3])
        self.hx = ax1[0] - ax1[2] * self.sx
        self.hy = ax1[1] - ax1[3] * self.sy
        if verbose:
            print(f"  => sx={self.sx:.3f} sy={self.sy:.3f} home=({self.hx:.0f},{self.hy:.0f})")
        return True

    def tap_px(self, px, py, click=True):
        """Open-loop: về góc rồi di tới pixel (px,py) theo calibrate, click."""
        ax = int((px - self.hx) / self.sx)
        ay = int((py - self.hy) / self.sy)
        self.home()
        self.h.move(ax, ay)
        time.sleep(0.15)
        if click:
            return self.h.click()
        return "OK moved"

    INV_SCALE = 1.05      # (cũ) đơn vị move trên mỗi pixel

    def locate_pointer(self, nudge=(6, 0)):
        """Nhích nhẹ cho con trỏ sáng rồi chụp tìm vị trí. Trả (x,y) px hoặc None."""
        self.h.move(*nudge)
        img = self.e.screenshot()
        p = self.e.find_pointer(img)
        return (p[0], p[1]) if p else None

    def _detect(self):
        """Chụp + tìm con trỏ, loại nhận diện sát mép (hay nhầm). Trả (x,y) hoặc None."""
        img = self.e.screenshot()
        H, W = img.shape[:2]
        p = self.e.find_pointer(img)
        if p is None:
            return None
        x, y = p[0], p[1]
        if x > W - 10 or y > H - 10 or x < 2 or y < 2:   # sát mép -> nghi ngờ
            return None
        return (x, y)

    CAP = 110      # giới hạn đơn vị mỗi lần di -> giữ tốc độ thấp, tránh gia tốc iOS

    def tap_at(self, px: int, py: int, tol: int = 12, iters: int = 16,
               click=True, verbose=False):
        """Closed-loop đi từng bước nhỏ: về góc -> nhích cho con trỏ hiện -> lặp
        (chụp, tìm con trỏ, di <=CAP về đích) tới khi sát đích rồi click."""
        self.home()
        self.h.move(50, 50)            # rời góc để con trỏ hiện (ở góc là nửa hình, khó thấy)
        time.sleep(0.15)
        last = None
        for i in range(iters):
            p = self._detect()
            if p is None:              # chưa thấy -> nhích cho sáng
                self.h.move(25, 0); time.sleep(0.12)
                p = self._detect()
                if p is None:
                    self.h.move(-25, 25); time.sleep(0.12); continue
            cx, cy = p; last = (cx, cy)
            ex, ey = px - cx, py - cy
            if verbose:
                print(f"  [{i}] con trỏ=({cx},{cy}) lệch=({ex},{ey})")
            if abs(ex) <= tol and abs(ey) <= tol:
                if click: self.h.click()
                return True
            mx = max(-self.CAP, min(self.CAP, int(ex * 0.9)))
            my = max(-self.CAP, min(self.CAP, int(ey * 0.9)))
            self.h.move(mx, my); time.sleep(0.1)
        if click: self.h.click()
        if verbose: print(f"  (hết vòng, con trỏ cuối={last})")
        return False

    def ensure_english(self, tries: int = 5, verbose=False):
        """Đảm bảo bàn phím cứng đang là tiếng Anh (không Telex). Dùng Spotlight làm ô thử.
        Gõ 'afaf': English -> 'afaf' (có f); Telex -> 'àà' (mất f). Không có f thì Ctrl+Space
        đổi input rồi thử lại. Trả (True/False, text đọc được)."""
        self.h.do("combo gui h"); time.sleep(0.5)        # về home
        self.h.do("combo gui space"); time.sleep(1.0)    # mở Spotlight
        txt = ""
        for i in range(tries):
            self.h.do("combo cmd a"); self.h.key("back"); time.sleep(0.3)   # xoá ô
            self.h.type("afaf"); time.sleep(0.6)
            img = self.e.screenshot(); H, W = img.shape[:2]
            txt = self.e.read_text(img, region=(60, H - 115, W - 60, H - 28)).lower()
            if verbose:
                print(f"  [{i}] OCR ô search = {txt!r}")
            self.h.do("combo cmd a"); self.h.key("back")                    # xoá lại
            if "f" in txt:
                self.h.do("combo gui h")
                return True, txt
            self.h.do("combo ctrl space"); time.sleep(0.7)                 # đổi input
        self.h.do("combo gui h")
        return False, txt

    def tap_text(self, needle: str, verbose=False):
        """OCR tìm nhãn chữ rồi click vào giữa nó. Trả True nếu thấy & tap."""
        img = self.e.screenshot()
        pos = self.e.find_text(needle, img)
        if not pos:
            if verbose: print(f"  không thấy chữ '{needle}'")
            return False
        if verbose: print(f"  '{needle}' ở {pos} -> tap")
        self.tap_at(pos[0], pos[1])
        return True

    def home_screen(self):
        """Về màn hình chính (Cmd+H)."""
        self.h.do("combo gui h"); time.sleep(0.8)

    def shot(self, path: str):
        return self.e.save(path)

    def close(self):
        self.h.close()


if __name__ == "__main__":
    # Dùng: python app/nav.py <udid> <ax> <ay> [out.png]
    udid = sys.argv[1]
    ax = int(sys.argv[2]); ay = int(sys.argv[3])
    out = sys.argv[4] if len(sys.argv) > 4 else "shots/nav.png"
    n = Nav("/dev/cu.usbserial-0001", udid)
    print(f"tap_move({ax},{ay}) ->", n.tap_move(ax, ay))
    time.sleep(0.5)
    n.shot(out)
    n.close()
    print("chụp", out)
