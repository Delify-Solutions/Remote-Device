#!/usr/bin/env python3
"""
Test ĐỊNH VỊ CON TRỎ + bấm vòng kín + kiểm bàn phím (không cần iPhone):   ./.venv/bin/python app/tests/test_nav.py

Dựng một màn hình giả (chữ đen, icon màu, chấm xám đứng yên, đồng hồ đổi phút) và một con trỏ
AssistiveTouch giả (đĩa xám bán trong suốt, di chuyển với gia tốc KHÔNG đều như iOS), rồi chạy
code thật: Eyes.pointer_blobs() và Nav.tap_at().

Lỗi từng gặp trên máy thật (và test này giữ cho không tái diễn):
  * con trỏ nằm cạnh icon tròn / đè lên chữ → cách tìm «chấm xám» không thấy → không bao giờ tới đích;
  * tới không được mà vẫn bấm → bấm nhầm chỗ;
  * con trỏ không hiện, đúng lúc đó một nút cỡ con trỏ hiện ra ngay tại đích → tưởng là con trỏ đã tới → bấm
    trong khi con trỏ thật ở chỗ khác;
  * đưa con trỏ tới nơi mất hơn chục giây, màn hình đã đổi mà vẫn bấm vào toạ độ cũ;
  * iPhone bật bộ gõ Telex: «afaf» gõ ra «âf» — vẫn còn chữ f nên cách kiểm cũ («có chữ f là tiếng Anh») lọt lưới.
"""
from __future__ import annotations
import math, os, random, sys, tempfile, time

REAL_SLEEP = time.sleep                     # (các quãng nghỉ của code bị tắt bên dưới; cổng giả cần nghỉ thật vài ms)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["IPF_NO_TELEGRAM"] = "1"            # app có thể đã cấu hình Telegram thật: kiểm thử không bao giờ bắn tin

import cv2
import numpy as np

import hands as handsmod
import nav as navmod
import stepexec
from eyes import Eyes
from hands import Hands
from nav import Nav

navmod.time.sleep = lambda s: None          # bỏ các quãng nghỉ dành cho máy thật
stepexec.time.sleep = lambda s: None

PASS = FAIL = 0
def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ " + name)
    else:
        FAIL += 1
        print("  ✗ " + name + ("" if ctx is None else "   → %s" % (ctx,)))


W, H, R = 750, 1334, 19


def make_screen(seed=7):
    """Màn hình kiểu «Cài đặt»: nền sáng, tiêu đề đen, các dòng có icon màu bo tròn + chữ."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 242, np.uint8)
    cv2.putText(img, "Cai dat", (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 6)
    y = 300
    while y < H - 120:
        cv2.rectangle(img, (30, y), (W - 30, y + 84), (255, 255, 255), -1)
        color = tuple(int(c) for c in rng.integers(40, 230, 3))
        cv2.circle(img, (92, y + 42), 27, color, -1)                      # icon tròn màu, r=27 (giống icon dòng)
        cv2.putText(img, "Dong chu %d" % y, (150, y + 54), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2)
        y += 110
    cv2.circle(img, (600, 250), 20, (150, 150, 150), -1)                 # chấm XÁM đứng yên, cỡ đúng bằng con trỏ
    cv2.rectangle(img, (W - 170, H - 330, 130, 130), (190, 190, 190), -1)   # nút AssistiveTouch
    return img


def draw_pointer(img, x, y):
    """Con trỏ thật: đĩa xám bán trong suốt (trên nền trắng ra ~147, đè lên chữ đen ra rất tối)."""
    out = img.copy()
    mask = np.zeros((H, W), np.uint8)
    cv2.circle(mask, (int(x), int(y)), R, 255, -1)
    blend = (img.astype(np.float32) * 0.45 + 70 * 0.55).astype(np.uint8)
    out[mask > 0] = blend[mask > 0]
    return out


class World:
    """iPhone giả: vị trí con trỏ + gia tốc không đều + có thể «tàng hình»."""
    def __init__(self, visible=True, clock=True, popup=None, popup_from=2, first_scale=None, label_until=None, button=None, blinker=None, blink=1):
        self.base = make_screen()
        self.x = self.y = 300.0
        self.visible = visible
        self.clock = clock
        self.popup = popup              # (x, y): một nút tròn cỡ con trỏ HIỆN RA tại đây từ ảnh thứ `popup_from`
        self.popup_from = popup_from
        self.first_scale = first_scale  # nhịp di đầu tiên bị iOS «tăng tốc» gấp mấy lần
        self.label_until = label_until  # chữ cần bấm chỉ còn trên màn tới ảnh thứ mấy (None = luôn còn)
        self.button = button            # (x0,y0,x1,y1): nút hộp thoại — con trỏ đi vào thì iOS tô sẫm CẢ nút (chấm tròn vẫn vẽ bên trong)
        self.gestures = []              # cử chỉ đã nhận: ("hold", x, y, giây) / ("swipe", x, y, dx, dy)
        self.swap_from = None           # từ ảnh thứ mấy thì màn hình ĐỔI sang trang khác (hiệu ứng chuyển trang xong muộn)
        self.gain = 1.0                 # máy này đi mấy pixel cho mỗi đơn vị lệnh di (iPhone thật: 1,0–1,4 tuỳ máy)
        self.homes = 0                  # số lần con trỏ bị ghim về góc
        self.shots = 0
        self.clicks = []
        self.moves = 0
        self.seen_by_verify = []
        self.blinker = blinker          # (x, y): vật cỡ con trỏ NHẤP NHÁY tại chỗ, hiện `blink` ảnh rồi ẩn `blink` ảnh — như mũi tên cam cạnh
        self.blink = blink              # «Step 2» của hộp «Sign Players» (đo thật: một ảnh có, một ảnh không — blink=1)
        self.decoy = None               # (x, y, xác suất): vật cỡ con trỏ LOÉ lên ngẫu nhiên tại (x, y) — vd ngay ở đích (kiểm «không bấm sai»)
        self.partial = 0.0              # xác suất một lệnh di chỉ tới được 15–40% (board rớt gói)
        self.blinkers = []              # thêm nhiều vật nhấp nháy (một ảnh có, một ảnh không, nhích 0–3px)
        self.rnd = random.Random(1)

    def render(self):
        self.shots += 1
        if self.swap_from and self.shots >= self.swap_from:
            self.base, self.swap_from = make_screen(seed=99)[::-1].copy(), None     # trang khác hẳn (lật ngược cho chắc là khác)
        img = self.base.copy()
        if self.clock:              # đồng hồ trên thanh trạng thái đổi theo thời gian (vệt thay đổi KHÔNG phải con trỏ)
            cv2.putText(img, "12:%02d" % (self.shots % 60), (330, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
        if self.popup and self.shots >= self.popup_from:
            cv2.circle(img, self.popup, R, (120, 120, 120), -1)
        if self.blinker and (self.shots // self.blink) % 2 == 0:
            cv2.circle(img, (self.blinker[0] + self.shots % 2 * 2, self.blinker[1]), R, (40, 140, 240), -1)
        if self.shots % 2 == 0:
            for bx, by in self.blinkers:
                cv2.circle(img, (bx + self.shots % 4, by), R, (40, 140, 240), -1)
        if self.decoy and self.rnd.random() < self.decoy[2]:
            cv2.circle(img, (self.decoy[0], self.decoy[1]), R, (60, 200, 60), -1)
        b = self.button
        if b:
            cv2.putText(img, "De sau", (b[0] + 70, b[3] - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 122, 0), 3)      # chữ trên nút
            if b[0] <= self.x <= b[2] and b[1] <= self.y <= b[3]:
                # đo trên iPhone 8: cả nút sẫm đi ~19 mức xám, CHỮ giữ nguyên màu, chấm tròn vẫn vẽ đè lên trên
                box = img[b[1]:b[3], b[0]:b[2]]
                keep = (box == (255, 122, 0)).all(axis=2)
                dark = np.clip(box.astype(np.int16) - 19, 0, 255).astype(np.uint8)
                dark[keep] = box[keep]
                img[b[1]:b[3], b[0]:b[2]] = dark
        return draw_pointer(img, self.x, self.y) if self.visible else img


def tap_text(n, needle):
    """Bấm vào chữ bằng ĐÚNG bộ chạy bước của app (stepexec.exec_step): nhìn một lần, đưa con trỏ tới, kiểm chữ còn đó rồi mới bấm."""
    return stepexec.exec_step(n, {"type": "tap_text", "text": needle}, {})[0]


class FakeHands:
    def __init__(self, world):
        self.w = world

    def do(self, cmd, retries=3, wait=0.5):
        if cmd == "home":
            self.w.x = self.w.y = 0.0
            self.w.homes += 1
        return "OK"

    def move(self, dx, dy):
        self.w.moves += 1
        if self.w.partial and self.w.rnd.random() < self.w.partial:      # lệnh di bị rớt một phần
            s = self.w.rnd.uniform(0.15, 0.4)
            dx, dy = int(dx * s), int(dy * s)
        if self.w.moves == 1 and self.w.first_scale:
            self.w.x = min(W - 1.0, self.w.x + dx * self.w.first_scale)
            self.w.y = min(H - 1.0, self.w.y + dy * self.w.first_scale)
            return "OK move"
        k = 0.9 + 0.2 * min(1.0, max(abs(dx), abs(dy)) / 110.0)       # 0.9 … 1.1 tuỳ độ lớn (gia tốc iOS)
        if abs(dx) < 60:
            kx = 1.12
        else:
            kx = k
        self.w.x = min(W - 1.0, max(0.0, self.w.x + dx * kx * self.w.gain))
        self.w.y = min(H - 1.0, max(0.0, self.w.y + dy * k * self.w.gain))
        return "OK move"

    def click(self):
        self.w.clicks.append((round(self.w.x), round(self.w.y)))
        return "OK click"

    def send(self, cmd, wait=0.5):
        """Lệnh thô xuống board (bộ chạy bước gửi «click» qua đường này) → trả đúng câu board trả lời."""
        return self.click() if cmd == "click" else self.do(cmd)

    def hold(self, seconds=1.0):
        self.w.gestures.append(("hold", round(self.w.x), round(self.w.y), seconds))
        return True

    def swipe(self, dx, dy):
        self.w.gestures.append(("swipe", round(self.w.x), round(self.w.y), dx, dy))
        return True


class FakeEyes(Eyes):
    LABEL_AT = (186, 831)           # chỗ «chữ cần bấm» của màn hình giả

    def __init__(self, world):
        self.w = world

    def screenshot(self):
        return self.w.render()

    def find_text(self, needle, img=None, scale=2):
        if needle != "Wi-Fi" or (self.w.label_until is not None and self.w.shots > self.w.label_until):
            return None
        return self.LABEL_AT


# ---------- bàn phím giả: bộ gõ tiếng Việt gộp cặp phím thành chữ có dấu ----------
TELEX = {"dd": "đ", "aa": "â", "ee": "ê", "oo": "ô"}
VNI = {"a6": "â", "e6": "ê", "o6": "ô", "o7": "ơ", "u7": "ư", "a8": "ă", "d9": "đ"}


def telex(text):
    return " ".join(TELEX.get(w, w) for w in text.split(" "))


def vni(text):
    return " ".join(VNI.get(w, w) for w in text.split(" "))


class Keyboard:
    """Vừa là «tay» (nhận phím) vừa là «mắt» (đọc lại ô Spotlight) của một iPhone giả."""
    def __init__(self, mode="en", switchable=True, blind=0):
        self.mode, self.switchable = mode, switchable
        self.field = ""
        self.switches = 0
        self.blind = blind          # số ảnh chụp đầu mà OCR không đọc ra chữ nào
        self.shots = 0

    # --- tay ---
    def do(self, cmd, retries=3, wait=0.5):
        if cmd == "combo cmd a":
            self._sel = True
        elif cmd == "combo ctrl space":
            self.switches += 1
            if self.switchable:
                self.mode = {"telex": "vni", "vni": "en", "en": "telex"}[self.mode]
        return "OK"

    def key(self, name):
        if name == "back" and getattr(self, "_sel", False):
            self.field, self._sel = "", False
        return "OK"

    def type(self, text):
        self.field += {"en": lambda t: t, "telex": telex, "vni": vni}[self.mode](text)
        return "OK type %d" % len(text)

    # --- mắt ---
    def screenshot(self):
        self.shots += 1
        return np.zeros((H, W, 3), np.uint8)

    def read_text(self, img=None, region=None, scale=2, lang=None, psm=None):
        if self.shots <= self.blind:
            return ""
        if region is None:                      # cả màn hình: có thêm chữ khác quanh ô tìm kiếm
            return "Không có SIM 22:27 Gợi ý của Siri " + self.field + " Trang web được Siri gợi ý Lỗi gõ aa, dd, ee, oo thành dđ, aâ, eê, oô"
        return self.field


def rig(**kw):
    w = World(**kw)
    n = Nav.__new__(Nav)
    n.h, n.e = FakeHands(w), FakeEyes(w)
    return n, w


def main():
    Nav.MISS_DIR = tempfile.mkdtemp(prefix="ipf-tap-miss-")     # lần bấm hỏng trong test không ghi vào app/data/ thật
    Nav.rng = random.Random(20261125)           # hướng nhích thử chọn ngẫu nhiên: cố định hạt giống để test lặp lại được (bài quét tự đổi nhiều ca)
    DEFAULT_RELOOK = Nav.RELOOK                 # giá trị mặc định của app (các bài decoy tắt tạm, bài «lướt dở» dùng lại đúng giá trị này)
    print("\n== 1. So ảnh nền: thấy con trỏ ở MỌI nền ==")
    e = Eyes.__new__(Eyes)
    base = make_screen()
    ok(Eyes.pointer_size(base) == 38 and Eyes.pointer_size(np.zeros((2436, 1125, 3), np.uint8)) == 57, "cỡ con trỏ theo loại màn hình (×2 → 38px, ×3 → 57px)")
    cases = {"nền trắng trống": (400, 660), "đè lên tiêu đề đen": (150, 178), "đè lên chữ của một dòng": (230, 344),
             "sát icon tròn màu": (140, 342), "ngay trên chấm xám đứng yên": (606, 252), "gần mép phải": (725, 700)}
    for name, (x, y) in cases.items():
        blobs = e.pointer_blobs(base, draw_pointer(base, x, y))
        hit = [b for b in blobs if abs(b[0] - x) <= 4 and abs(b[1] - y) <= 4]
        ok(len(blobs) == 1 and len(hit) == 1, "%s (%d,%d)" % (name, x, y), blobs)
    old = e.find_pointer(draw_pointer(base, 140, 342))
    ok(old is None or abs(old[0] - 140) > 6 or abs(old[1] - 342) > 6, "(cách cũ «tìm chấm xám» KHÔNG thấy con trỏ nằm sát icon — lý do phải so ảnh)", old)
    ok(e.pointer_blobs(base, base) == [], "không có con trỏ → không báo gì")
    clock = base.copy()
    cv2.putText(clock, "12:59", (330, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    ok(e.pointer_blobs(base, clock) == [], "đồng hồ đổi phút không bị nhận nhầm là con trỏ")
    ok(e.pointer_blobs(base, draw_pointer(clock, 300, 900)) and len(e.pointer_blobs(base, draw_pointer(clock, 300, 900))) == 1, "đồng hồ đổi + con trỏ → vẫn chỉ thấy con trỏ")
    ok(e.pointer_blobs(base, draw_pointer(base, 8, 8), ignore=[(0, 0, 26, 26)]) == [], "phần tư con trỏ ghim ở góc bị bỏ qua")
    ok(e.pointer_blobs(base, np.zeros((100, 100, 3), np.uint8)) == [], "ảnh nền khác cỡ → bỏ, không lỗi")

    print("\n== 1a. Con trỏ trên một DÒNG CHỮ LINK đổi màu khi rê tới (:hover của trang web) ==")
    # Đo thật (my.konami.net, iPhone 8 xoay ngang): con trỏ vào link «Log In with Another KONAMI ID» thì cả dòng chữ đổi xanh → xám,
    # con trỏ vẫn vẽ ở giữa. Trước đây vệt «chữ đổi màu + con trỏ» không tách được (bấm hỏng hết 34 lần nhìn) và mẩu chữ «Log» ở đầu
    # link còn bị nhận nhầm là một con trỏ đứng yên.
    lk = np.full((1334, 750, 3), 255, np.uint8)
    txt = np.full((60, 760, 3), 255, np.uint8)
    cv2.putText(txt, "Log In with Another KONAMI ID", (5, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (243, 150, 66), 1, cv2.LINE_AA)  # xanh (BGR), nét ~2–3px như chữ thật
    lk[300:1060, 230:290] = cv2.rotate(txt, cv2.ROTATE_90_CLOCKWISE)
    hov = lk.copy()
    blue = (np.abs(hov.astype(int) - (243, 150, 66)).sum(axis=2) < 120)
    hov[blue] = (110, 110, 110)                                                                   # chữ đổi sang xám khi :hover
    for (px, py) in ((262, 668), (262, 420), (262, 900)):
        blobs = e.pointer_blobs(lk, draw_pointer(hov, px, py))
        ok(len(blobs) == 1 and abs(blobs[0][0] - px) <= 6 and abs(blobs[0][1] - py) <= 6,
           "link :hover đổi màu cả dòng, con trỏ ở (%d,%d) → tách được đúng MỘT con trỏ (nét chữ bị bỏ)" % (px, py), blobs)
    ok(e.pointer_blobs(lk, hov) == [], "chỉ có chữ đổi màu (không có con trỏ) → không thấy con trỏ nào (mẩu chữ không bị nhận nhầm)",
       e.pointer_blobs(lk, hov))
    bold = np.full((60, 760, 3), 255, np.uint8)
    cv2.putText(bold, "Log In with Another KONAMI ID", (5, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (243, 150, 66), 2, cv2.LINE_AA)
    lb = np.full((1334, 750, 3), 255, np.uint8); lb[300:1060, 230:290] = cv2.rotate(bold, cv2.ROTATE_90_CLOCKWISE)
    hb = lb.copy(); hb[(np.abs(hb.astype(int) - (243, 150, 66)).sum(axis=2) < 120)] = (110, 110, 110)
    got_b = e.pointer_blobs(lb, draw_pointer(hb, 262, 668))
    ok(len(got_b) <= 1 and all(abs(b[0] - 262) <= 6 and abs(b[1] - 668) <= 6 for b in got_b),
       "chữ đậm hơn: không bao giờ báo SAI chỗ (tách được thì đúng chỗ, không chắc thì không báo)", got_b)

    found_bar, wrong_bar = [], []
    for th in (3, 6, 9, 11, 14):                     # con trỏ chạm một THANH đổi màu (nét dày / mảnh)
        bb = np.full((1334, 750, 3), 255, np.uint8)
        cb = bb.copy(); cv2.rectangle(cb, (300, 600), (300 + 55, 600 + th), (200, 120, 40), -1)
        got = e.pointer_blobs(bb, draw_pointer(cb, 330, 600 + th + 14))
        near = [b for b in got if abs(b[0] - 330) <= 6 and abs(b[1] - (600 + th + 14)) <= 6]
        if len(got) == 1 and near: found_bar.append(th)
        if len(got) == 1 and not near: wrong_bar.append((th, got))
    # trước bản sửa: tách được ở 3/6/9px, 11/14px thì không báo (không sai chỗ) — bản mới không được lùi
    ok({3, 6, 9} <= set(found_bar), "con trỏ chạm một thanh đổi màu dày 3/6/9px → vẫn tách được như trước", found_bar)
    ok(not wrong_bar, "thanh đổi màu dày 3–14px: không bao giờ báo con trỏ SAI chỗ", wrong_bar)

    print("\n== 1b. Con trỏ nằm LẪN trong một vệt thay đổi to hơn nó (ảnh chụp từ iPhone thật + dựng lại) ==")
    fx = lambda n: cv2.imread(os.path.join(HERE, "fixtures", n + ".png"))
    aref = fx("alert_ref")                          # hàng nút «Để sau | Cài đặt» của hộp thoại hệ thống, iPhone 8 / iOS 16
    ok(aref is not None and e.pointer_blobs(aref, aref) == [], "ảnh thật: hàng nút hộp thoại, chưa có con trỏ → không báo gì")
    for fn, want, what in (("alert_in", (145, 65), "con trỏ nằm GIỮA nút đang bị iOS tô sẫm"),
                           ("alert_edge", (149, 37), "con trỏ vừa chạm mép trên của nút (nút đã sẫm)")):
        got = e.pointer_blobs(aref, fx(fn))
        ok(len(got) == 1 and abs(got[0][0] - want[0]) <= 5 and abs(got[0][1] - want[1]) <= 5, "ảnh thật: %s → vẫn ĐO được vị trí con trỏ" % what, got)
    # Trang WEB: nút đổi màu khi con trỏ rê tới (:hover). Ảnh thật — nút «Login» 932×92px của trang đăng nhập my.konami.net trên iPhone 8
    # đang xoay NGANG (cắt riêng vùng nút): nút đổi từ đỏ sang trắng, chữ trên nút đổi từ trắng sang xám.
    wref = fx("web_hover_ref")
    ok(wref is not None and Eyes.pointer_size(wref) == 38 and Eyes.pointer_size(np.zeros((750, 1334, 3), np.uint8)) == 38
       and Eyes.pointer_size(np.zeros((1125, 2436, 3), np.uint8)) == 57,
       "cỡ con trỏ không đổi khi ảnh chụp nằm NGANG (iPhone 8: 1334×750 vẫn là máy ×2; máy ×3 nằm ngang vẫn là ×3)")
    for fn, want, what in (("web_hover_in", (403, 55), "con trỏ nằm trong nút vừa đổi từ đỏ sang trắng"),
                           ("web_hover_text", (550, 55), "con trỏ đè lên CHỮ của nút (chữ cũng đổi màu)")):
        got = e.pointer_blobs(wref, fx(fn))
        ok(len(got) == 1 and abs(got[0][0] - want[0]) <= 6 and abs(got[0][1] - want[1]) <= 6, "ảnh thật (web): %s → vẫn ĐO được vị trí con trỏ" % what, got)
    ok(e.pointer_blobs(wref, fx("web_hover_none")) == [], "ảnh thật (web): nút đang đổi màu mà KHÔNG có con trỏ → không báo gì (chữ đổi màu không bị nhận nhầm là con trỏ)",
       e.pointer_blobs(wref, fx("web_hover_none")))
    # Bước «bấm vào chữ» đưa con trỏ tới ĐÚNG GIỮA CHỮ của nút → con trỏ đè lên chữ đang đổi màu vẫn phải đo được ở mọi vị trí
    # (vẽ con trỏ lên ảnh thật của nút đang đổi màu; chữ «Login» nằm quanh x=519, y=59 của ảnh cắt).
    whover = fx("web_hover_none")

    def dot(img, x, y):
        out, mask = img.copy(), np.zeros(img.shape[:2], np.uint8)
        cv2.circle(mask, (x, y), R, 255, -1)
        out[mask > 0] = (img.astype(np.float32) * 0.45 + 70 * 0.55).astype(np.uint8)[mask > 0]
        return out
    missed = []
    for y in (40, 50, 58, 66, 76):
        for x in range(430, 610, 5):
            got = e.pointer_blobs(wref, dot(whover, x, y))
            if not (len(got) == 1 and abs(got[0][0] - x) <= 6 and abs(got[0][1] - y) <= 6):
                missed.append((x, y, got))
    ok(not missed, "ảnh thật (web): con trỏ đè lên chữ «Login» đang đổi màu — đo đúng ở cả 180 vị trí quét quanh chữ", missed[:6])

    def tinted(img, box, by=-19):
        out = img.copy()
        x0, y0, x1, y1 = box
        out[y0:y1, x0:x1] = np.clip(out[y0:y1, x0:x1].astype(np.int16) + by, 0, 255).astype(np.uint8)
        return out
    btn = (380, 720, 660, 840)
    ok(e.pointer_blobs(base, tinted(base, btn)) == [], "nút bị tô sẫm mà KHÔNG có con trỏ bên trong → không báo gì")
    got = e.pointer_blobs(base, draw_pointer(tinted(base, btn), 520, 780))
    ok(len(got) == 1 and abs(got[0][0] - 520) <= 4 and abs(got[0][1] - 780) <= 4, "dựng lại: con trỏ trong nút bị tô sẫm → đo được", got)
    got = e.pointer_blobs(base, draw_pointer(tinted(base, btn, by=22), 430, 800))
    ok(len(got) == 1 and abs(got[0][0] - 430) <= 4 and abs(got[0][1] - 800) <= 4, "nút được tô SÁNG lên (giao diện tối) cũng vậy", got)
    hand = draw_pointer(base, 400, 660)
    cv2.line(hand, (400, 660), (470, 628), (0, 140, 255), 3)                   # kim giây (mảnh) chạy ngang qua con trỏ
    cv2.line(hand, (400, 660), (368, 700), (30, 30, 30), 5)
    plain = e.pointer_blobs(base, hand)
    ok(len(plain) == 1 and abs(plain[0][0] - 400) <= 6 and abs(plain[0][1] - 660) <= 6, "con trỏ dính vào NÉT MẢNH đang chuyển động (kim đồng hồ) → vẫn tách ra được", plain)
    # nút NHỎ bị tô (60×60): riêng con trỏ đã chiếm 1/3 nút — vẫn phải đo được
    small = (300, 600, 360, 660)
    hits = 0
    for (x, y) in ((318, 618), (330, 630), (342, 640), (320, 642), (345, 620)):
        got = e.pointer_blobs(base, draw_pointer(tinted(base, small), x, y))
        hits += int(len(got) == 1 and abs(got[0][0] - x) <= 5 and abs(got[0][1] - y) <= 5)
    ok(hits == 5 and e.pointer_blobs(base, tinted(base, small)) == [], "nút NHỎ (60×60) bị tô sẫm: đo được con trỏ ở 5/5 vị trí; không có con trỏ thì không báo gì", hits)
    frame = base.copy()                             # vùng tô KHÔNG đặc (một cái khung rỗng) + một mảnh tròn sẫm dính vào khung
    ring = np.zeros(base.shape[:2], np.uint8)
    cv2.rectangle(ring, (180, 215), (480, 295), 255, 14)
    frame[ring > 0] = np.clip(frame[ring > 0].astype(np.int16) - 19, 0, 255).astype(np.uint8)
    cv2.circle(frame, (330, 222), 19, (70, 70, 70), -1)
    ok(e.pointer_blobs(base, frame) == [], "vùng đổi đều nhưng RỖNG ruột (không phải một cái nút đặc) → không soi tìm con trỏ trong đó", e.pointer_blobs(base, frame))
    badge = tinted(base, btn)                       # trong nút bị tô có một mảnh đổi KHÁC nhưng không đúng cỡ con trỏ (nhãn dài)
    cv2.rectangle(badge, (430, 760), (560, 800), (60, 60, 200), -1)
    ok(e.pointer_blobs(base, badge) == [], "mảnh đổi khác trong nút mà KHÔNG đúng cỡ con trỏ (một cái nhãn dài) → không nhận", e.pointer_blobs(base, badge))

    # nút LỚN của trang web (dài gần hết màn hình) đổi màu nền VÀ màu chữ khi con trỏ rê tới
    def web_button(img, box, hover, text="Log In with Another KONAMI ID", lines=1):
        out = img.copy()
        x0, y0, x1, y1 = box
        cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 255) if hover else (40, 30, 170), -1)
        for k in range(lines):
            cv2.putText(out, text, (x0 + 24, y0 + 44 + 34 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (90, 90, 90) if hover else (255, 255, 255), 3)
        return out
    wide = (25, 1000, 725, 1100)                    # 700×100 = 70.000px ≈ 62 lần diện tích con trỏ (trên giới hạn cũ 60 lần)
    wbase = web_button(base, wide, False)
    got = e.pointer_blobs(wbase, draw_pointer(web_button(base, wide, True), 600, 1052))
    ok(len(got) == 1 and abs(got[0][0] - 600) <= 4 and abs(got[0][1] - 1052) <= 4, "nút web LỚN đổi cả màu nền lẫn màu chữ: con trỏ ở chỗ trống của nút → đo được", got)
    got = e.pointer_blobs(wbase, draw_pointer(web_button(base, wide, True), 200, 1040))
    ok(len(got) == 1 and abs(got[0][0] - 200) <= 6 and abs(got[0][1] - 1040) <= 6, "…con trỏ đè lên dòng chữ dài của nút → vẫn đo được (nét chữ mảnh bị bào bỏ)", got)
    ok(e.pointer_blobs(wbase, web_button(base, wide, True)) == [], "…nút đổi màu mà không có con trỏ → không báo gì", e.pointer_blobs(wbase, web_button(base, wide, True)))
    huge = (20, 300, 730, 560)                      # 710×260 ≈ 163 lần diện tích con trỏ: lớn hơn một cái nút → không soi
    hbase = web_button(base, huge, False)
    ok(e.pointer_blobs(hbase, draw_pointer(web_button(base, huge, True), 400, 500)) == [],
       "khối đổi màu LỚN hơn một cái nút (quá %d lần diện tích con trỏ) → không đoán con trỏ trong đó" % Eyes.BLOCK_MAX)
    wordy = (25, 960, 725, 1140)                    # cùng cỡ nút nhưng kín chữ đổi màu (một đoạn văn, không phải nhãn của nút)
    wb2 = web_button(base, wordy, False, text="Noi dung moi hien ra kin ca khoi nay", lines=5)
    ok(e.pointer_blobs(wb2, draw_pointer(web_button(base, wordy, True, text="Noi dung moi hien ra kin ca khoi nay", lines=5), 640, 1120)) == [],
       "khối đổi màu mà phần «đổi khác» quá nhiều (kín chữ) → không coi là nút được phủ sáng, không đoán")

    card = base.copy()                              # một khối NỘI DUNG mới hiện ra (hai mảng màu + một icon tròn cỡ con trỏ), không phải «tô đều»
    cv2.rectangle(card, (150, 215), (370, 295), (215, 215, 215), -1)
    cv2.rectangle(card, (370, 215), (470, 295), (90, 60, 200), -1)
    cv2.circle(card, (230, 255), 19, (60, 60, 60), -1)
    ok(e.pointer_blobs(base, card) == [], "vùng đổi KHÔNG đều (nội dung mới hiện ra, có icon tròn cỡ con trỏ) → không đoán bừa trong đó", e.pointer_blobs(base, card))
    dim = np.clip(base.astype(np.int16) - 40, 0, 255).astype(np.uint8)        # cả màn hình tối đi (hộp thoại bật lên) + một nút tròn mới
    cv2.circle(dim, (500, 900), 19, (40, 40, 200), -1)
    ok(e.pointer_blobs(base, dim) == [], "CẢ màn hình tối đi đều + một nút tròn mới hiện ra → không nhận nút đó là con trỏ", e.pointer_blobs(base, dim))
    other = np.full_like(base, 30)
    cv2.putText(other, "Trang khac", (60, 400), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 5)
    ok(e.pointer_blobs(base, draw_pointer(other, 300, 700)) == [], "CẢ màn hình đổi (chuyển trang) → không đoán con trỏ ở đâu")

    print("\n== 2. Bấm vòng kín: tới đúng đích rồi mới bấm ==")
    targets = {"chữ ở dòng giữa màn": (186, 831), "đè lên tiêu đề đen": (150, 178), "xa: gần đáy màn": (400, 1150),
               "sát mép phải": (700, 600), "ngay cạnh icon": (140, 452), "trên chấm xám đứng yên": (602, 250)}
    for name, (x, y) in targets.items():
        n, w = rig()
        got = n.tap_at(x, y)
        c = w.clicks[0] if w.clicks else None
        ok(got is True and len(w.clicks) == 1 and abs(c[0] - x) <= 14 and abs(c[1] - y) <= 14,
           "%s (%d,%d): bấm đúng 1 lần, lệch ≤14px (đo ±12 + sai số đo), %d ảnh chụp" % (name, x, y, w.shots), {"ok": got, "clicks": w.clicks})
    n, w = rig()
    ok(n.tap_at(186, 831, click=False) is True and w.clicks == [] and abs(w.x - 186) <= 14 and abs(w.y - 831) <= 14,
       "click=False: đưa con trỏ tới nơi nhưng KHÔNG bấm (chế độ API tự bấm sau)", (w.x, w.y, w.clicks))
    n, w = rig()
    n.tap_at(400, 1150)
    ok(w.shots <= 10, "đích xa vẫn chỉ cần ≤ 10 ảnh chụp (di nhiều nhịp, rồi phép thử đi–về trước khi bấm)", w.shots)

    print("\n== 3. Không tới được thì KHÔNG bấm ==")
    n, w = rig(visible=False)
    ok(n.tap_at(186, 831) is False and w.clicks == [], "không thấy con trỏ (AssistiveTouch tắt) → trả False, không bấm lần nào", w.clicks)
    n, w = rig(visible=False)
    ok(tap_text(n, "khong co chu nay") is False and w.clicks == [], "tap_text không thấy chữ → False, không bấm")

    class Blind(FakeEyes):          # chụp được ảnh nền rồi thì hỏng
        def screenshot(self):
            if self.w.shots >= 1:
                raise RuntimeError("Chụp màn thất bại")
            return super().screenshot()
    n, w = rig()
    n.e = Blind(w)
    try:
        r = n.tap_at(186, 831)
    except RuntimeError:
        r = "raise"
    ok(r == "raise" and w.clicks == [], "mất chụp màn giữa chừng → báo lỗi ra ngoài, không bấm mò", (r, w.clicks))

    print("\n== 3b. Không bấm nhầm: vệt lạ không phải con trỏ, màn hình đổi giữa chừng ==")
    n, w = rig(visible=False, popup=(186, 831))
    ok(n.tap_at(186, 831) is False and w.clicks == [],
       "con trỏ không hiện + một nút cỡ con trỏ hiện ra ĐÚNG ĐÍCH → không nhận nhầm là con trỏ, không bấm", {"clicks": w.clicks, "shots": w.shots})
    n, w = rig(popup=(500, 400), popup_from=4)
    got = n.tap_at(186, 831)
    c = w.clicks[0] if w.clicks else None
    ok(got is True and c and abs(c[0] - 186) <= 14 and abs(c[1] - 831) <= 14,
       "có thêm một nút lạ hiện ra giữa chừng → vẫn bám đúng con trỏ thật và bấm đúng đích", {"ok": got, "clicks": w.clicks})
    n, w = rig(first_scale=4.0)
    got = n.tap_at(400, 1150)
    c = w.clicks[0] if w.clicks else None
    ok(got is True and c and abs(c[0] - 400) <= 14 and abs(c[1] - 1150) <= 14,
       "con trỏ văng xa khỏi chỗ dự đoán (iOS tăng tốc) → nhích thử thấy nó ĐI THEO chuột → vẫn tới đích", {"ok": got, "clicks": w.clicks})

    def far_from_target(world, base, target):
        def check(img):
            blobs = Eyes.__new__(Eyes).pointer_blobs(base, img)
            world.seen_by_verify.append([b[:2] for b in blobs])
            return True
        return check
    n, w = rig(clock=False)
    got = n.tap_at(186, 831, verify=far_from_target(w, make_screen(), (186, 831)))
    seen = w.seen_by_verify
    ok(got is True and len(seen) == 1 and all(abs(b[0] - 186) > 28 or abs(b[1] - 831) > 28 for b in seen[0]),
       "hàm kiểm được gọi ĐÚNG MỘT lần, trên ảnh mà con trỏ chưa che thứ cần bấm", seen)
    n, w = rig()
    before = set(os.listdir(Nav.MISS_DIR)) if os.path.isdir(Nav.MISS_DIR) else set()
    ok(n.tap_at(186, 831, verify=lambda img: False) is False and w.clicks == [] and abs(w.x - 186) <= 14 and abs(w.y - 831) <= 14,
       "tới nơi nhưng hàm kiểm báo thứ cần bấm không còn → KHÔNG bấm", (round(w.x), round(w.y), w.clicks))
    kept = sorted(set(os.listdir(Nav.MISS_DIR)) - before) if os.path.isdir(Nav.MISS_DIR) else []
    files = sorted(os.listdir(os.path.join(Nav.MISS_DIR, kept[0]))) if len(kept) == 1 else []
    log = open(os.path.join(Nav.MISS_DIR, kept[0], "trace.txt"), encoding="utf-8").read() if "trace.txt" in files else ""
    ok("không còn ở đó" in (n.miss or "") and files == ["img.png", "ref.png", "trace.txt"] and "(186, 831)" in log and "phép thử đi–về" in log,
       "lần KHÔNG bấm: có lý do (nav.miss) + lưu nhật ký từng nhịp, ảnh nền, ảnh chụp cuối để tìm nguyên nhân", (n.miss, kept, files))
    msg = stepexec._tap(n, 186, 831, verify=lambda img: False)
    ok(msg[0] is False and msg[1].endswith("— " + n.miss), "thông báo lỗi của bước nêu lý do cụ thể", msg)
    ok(n.tap_at(186, 831) is True and n.miss is None, "lần bấm sau được → không còn lý do cũ", n.miss)
    real_keep = Nav.MISS_KEEP
    try:
        Nav.MISS_KEEP = 2
        for _ in range(3):
            n, w = rig()
            n.tap_at(186, 831, verify=lambda img: False)
        ok(len(os.listdir(Nav.MISS_DIR)) == 2, "chỉ giữ MISS_KEEP lần hỏng gần nhất", os.listdir(Nav.MISS_DIR))
        open(os.path.join(Nav.MISS_DIR, ".DS_Store"), "w").close()          # file lạ (Finder / Windows) trong thư mục lưu
        for _ in range(2):
            n, w = rig()
            n.tap_at(186, 831, verify=lambda img: False)
        left = sorted(os.listdir(Nav.MISS_DIR))
        ok(len(left) == 3 and ".DS_Store" in left, "có file lạ trong thư mục lưu → vẫn dọn đúng (chỉ xoá thư mục do tool tạo, không đụng file lạ)", left)
    finally:
        Nav.MISS_KEEP = real_keep
    for blink, how in ((1, "một ảnh có, một ảnh không — không bao giờ hiện hai ảnh liền"), (2, "hiện hai ảnh liền rồi ẩn hai ảnh")):
        hits = 0
        for seed in range(6):
            Nav.rng, Nav.gain, Nav.gain_sure = random.Random(seed), None, None
            n, w = rig(clock=False, blinker=(600, 1000), blink=blink)
            got = n.tap_at(186, 831)
            hits += bool(got and len(w.clicks) == 1 and abs(w.clicks[0][0] - 186) <= 14 and abs(w.clicks[0][1] - 831) <= 14)
        ok(hits == 6, "màn có vật NHẤP NHÁY tại chỗ ở xa đích (%s; hộp «Sign Players» máy 01 hỏng 4/10 lần thật) → vẫn tới đúng nút và bấm" % how, hits)
    # KHÔNG BAO GIỜ BẤM SAI vì gạt vật nhấp nháy (verify): con trỏ thật đi sát vật nhấp nháy + lệnh di rớt một phần + một vật cỡ con trỏ
    # loé lên ngay ở đích. Gạt nhầm chính con trỏ thì vệt «còn lại» là vật ở đích → bấm lệch ~60px (đã xảy ra trước khi có GUARD).
    T = (186, 831)
    ring = [(T[0] + dx, T[1] + dy) for dx, dy in ((61, 61), (61, -61), (-61, 61), (-61, -61), (88, 0), (-88, 0), (0, 88), (0, -88))]
    for name, setup in (("8 vật nhấp nháy quanh đích + vật loé ở đích + lệnh di rớt một phần",
                         lambda w: (w.blinkers.extend(ring), setattr(w, "decoy", (T[0] + 3, T[1], 0.3)), setattr(w, "partial", 0.15))),
                        ("vật nhấp nháy ở xa + lệnh di rớt một phần", lambda w: (setattr(w, "blinker", (600, 1000)), setattr(w, "partial", 0.25)))):
        wrong, good = [], 0
        for seed in range(30):
            Nav.rng, Nav.gain, Nav.gain_sure = random.Random(seed), None, None
            n, w = rig(clock=False)
            w.rnd = random.Random(seed * 13 + 5)
            setup(w)
            n.tap_at(*T)
            for c in w.clicks:
                if abs(c[0] - T[0]) <= 14 and abs(c[1] - T[1]) <= 14:
                    good += 1
                else:
                    wrong.append((seed, c))
        ok(not wrong and good >= 5, "%s → không lần nào bấm sai chỗ (%d/30 bấm đúng, còn lại không bấm)" % (name, good), wrong)
    ok(n._match([(400, 660)], [(462, 660), (470, 700)], [(400, 660)], (62, 0), [(470, 700)]) is None
       and n._match([(400, 660)], [(462, 660), (614, 575)], [(400, 660)], (62, 0), [(614, 575)]) == ((400, 660), (462, 660)),
       "vệt bị gạt (vật nhấp nháy) nằm SÁT chỗ mới / chỗ cũ của con trỏ → không gạt (có thể chính nó là con trỏ); ở xa → gạt được")
    ok(n._match([(186, 624)], [(186, 732), (190, 832)], [(186, 624)], (0, 190), [(186, 744)], 76) is None,
       "vệt bị gạt nằm GIỮA đường con trỏ đi (xa cả hai đầu: lệnh di dài bị rớt giữa chừng, con trỏ thật dừng sát vật nhấp nháy) → không gạt")
    Nav.rng, Nav.gain, Nav.gain_sure = random.Random(20261125), None, None
    n, w = rig()
    ok(tap_text(n, "Wi-Fi") is True and len(w.clicks) == 1, "tap_text: chữ vẫn còn đó tới lúc bấm → bấm", w.clicks)
    n, w = rig(label_until=2)
    ok(tap_text(n, "Wi-Fi") is False and w.clicks == [],
       "tap_text: chữ biến mất trong lúc đưa con trỏ tới (màn hình đổi) → không bấm vào toạ độ cũ", {"clicks": w.clicks, "shots": w.shots})

    n, w = rig(visible=False)
    cv2.circle(w.base, (600, 250), 24, (242, 242, 242), -1)       # (bỏ chấm xám mẫu ở xa để cách «tìm chấm xám» chỉ còn thấy nút dưới đây)
    cv2.circle(w.base, (300, 110), 20, (150, 150, 150), -1)       # một nút tròn xám CÓ SẴN trên màn hình (kiểu nút AssistiveTouch)
    ok(n.tap_at(300, 110) is False and w.clicks == [],
       "mất dấu con trỏ → KHÔNG vớ lấy một nút tròn xám có sẵn gần đó làm con trỏ (gặp thật: nút AssistiveTouch)", {"clicks": w.clicks, "shots": w.shots})
    n, w = rig(visible=False, popup=(100, 100))
    ok(n.tap_at(100, 100) is False and w.clicks == [],
       "con trỏ không hiện + một nút hiện ra ngay GẦN GÓC (chỗ con trỏ hay đứng lúc đầu) → vẫn không nhận nhầm", {"clicks": w.clicks})
    n, w = rig(button=(380, 720, 660, 840))                 # nút hộp thoại: con trỏ đi vào thì iOS tô sẫm CẢ nút
    got = n.tap_at(520, 780)
    c = w.clicks[0] if w.clicks else None
    ok(got is True and c and abs(c[0] - 520) <= 14 and abs(c[1] - 780) <= 14,
       "con trỏ đi vào nút hộp thoại (iOS tô sẫm cả nút) → vẫn ĐO được vị trí con trỏ trong nút, bấm đúng điểm", {"ok": got, "clicks": w.clicks, "shots": w.shots})
    n, w = rig(visible=False, button=(380, 720, 660, 840))
    ok(n.tap_at(520, 780) is False and w.clicks == [], "nút đổi màu nhưng KHÔNG thấy con trỏ trong đó → không bấm", w.clicks)
    n, w = rig(visible=False, popup=(520, 780), popup_from=2)
    ok(n.tap_at(520, 780) is False and w.clicks == [], "vùng đích đổi màu nhưng CHƯA từng thấy con trỏ → không bấm", w.clicks)

    # --- con trỏ ĐANG hiện, đúng lúc đó một thứ cỡ con trỏ hiện ra ngay tại đích (icon tải muộn, số đếm, nút tròn) ---
    off = []
    for target, frm in (((560, 500), 3), ((300, 420), 3), ((186, 831), 4), ((640, 980), 3), ((400, 1150), 4), ((560, 500), 2), ((120, 640), 5), ((660, 300), 3)):
        for clock in (True, False):
            n, w = rig(popup=target, popup_from=frm, clock=clock)
            n.tap_at(*target)
            off += [(target, frm, c) for c in w.clicks if max(abs(c[0] - target[0]), abs(c[1] - target[1])) > 20]
    ok(off == [], "con trỏ đang hiện + một vật cỡ con trỏ hiện ra tại đích → có bấm thì cú bấm nằm TRÊN đích (16 lượt, trước đây lệch tới ~300px)", off)
    wrong = []
    for target in ((420, 640), (560, 500), (300, 110), (200, 900)):
        n, w = rig(clock=False)
        cv2.circle(w.base, (600, 250), 24, (242, 242, 242), -1)
        cv2.circle(w.base, target, 20, (150, 150, 150), -1)   # đích là một nút tròn xám CÓ SẴN trên màn hình
        orig_r = w.render
        def seen_then_lost(w=w, orig_r=orig_r):
            w.visible = (w.shots + 1) < 3                     # thấy con trỏ ở 2 ảnh đầu, sau đó không dò ra nữa
            return orig_r()
        w.render = seen_then_lost
        got = n.tap_at(*target)
        wrong += [(target, got, w.clicks)] if (got or w.clicks) else []
    ok(wrong == [], "đích là nút tròn xám có sẵn, con trỏ thấy lúc đầu rồi mất dấu → KHÔNG nhận cái nút làm con trỏ, không bấm", wrong)
    far = []
    for seed in range(6):                                     # quét: nhiều đích × nhiều thời điểm vật lạ hiện ra, con trỏ luôn hiện
        rng = np.random.default_rng(seed)
        for _ in range(5):
            target = (int(rng.integers(80, 670)), int(rng.integers(140, 1200)))
            other = (int(rng.integers(80, 670)), int(rng.integers(140, 1200)))
            n, w = rig(popup=other, popup_from=int(rng.integers(2, 6)))
            n.tap_at(*target)
            far += [(target, other, c) for c in w.clicks if max(abs(c[0] - target[0]), abs(c[1] - target[1])) > 20]
    ok(far == [], "quét 30 lượt (vật lạ cỡ con trỏ hiện ra ở chỗ bất kỳ, lúc bất kỳ) → không cú bấm nào lệch đích quá 20px", far)

    # --- luật nhận con trỏ: CHỈ bằng chứng chuyển động (Nav._match) ---
    n, w = rig()
    m = (60, 0)
    ok(n._match([(400, 660)], [(462, 660)], [(400, 660)], m) == ((400, 660), (462, 660)), "vệt cũ rời đi + vệt mới hiện đúng chỗ «cũ + quãng di» → là con trỏ (trả cả chỗ cũ lẫn chỗ mới)")
    ok(n._match([(400, 660)], [(400, 660), (462, 660)], [(400, 660)], m) is None, "chỗ cũ VẪN còn vệt (thứ ở đó đứng yên) → không nhận")
    ok(n._match([(400, 660)], [(462, 660)], [(400, 660), (460, 661)], m) is None, "chỗ mới ĐÃ có vệt từ ảnh trước (thứ đứng sẵn) → không nhận")
    ok(n._match([(400, 660)], [(462, 660), (455, 672)], [(400, 660)], m) is None, "hai vệt cùng hợp lý → chưa phân định, không nhận cái nào")
    ok(n._match([(400, 660)], [(462, 660), (120, 1100)], [(400, 660)], m) is None, "có thêm MỘT VỆT MỚI KHÁC ở tận đâu đó → cũng chưa phân định (con trỏ có thể chính là nó)")
    ok(n._match([(400, 650), (400, 672)], [(462, 661)], [(400, 650), (400, 672)], m) is None, "hai vị trí cũ cùng biến mất và cùng hợp với một vệt mới → không nhận")
    ok(n._match([(400, 660)], [(590, 660)], [(400, 660)], m) is None and n._match([(400, 660)], [(462, 700)], [(400, 660)], m) is None,
       "vệt mới ở sai chỗ (quá xa so với quãng đã ra lệnh, hoặc lệch hướng) → không nhận")
    n.gain, n.gain_sure = 1.0, None
    ok(n._match([(400, 660)], [(520, 660)], [(400, 660)], m) is not None,
       "tỉ lệ mới đo MỘT lần (chưa chắc) → KHÔNG dùng để siết phép kiểm (một vật lạ cũng dạy sai được tỉ lệ)")
    n.gain, n.gain_sure = 1.0, 1.0
    ok(n._match([(400, 660)], [(520, 660)], [(400, 660)], m) is None and n._match([(400, 660)], [(462, 660)], [(400, 660)], m) is not None,
       "tỉ lệ ĐÃ CHẮC (hai lần đo khớp nhau) của máy (1,0) → vệt mới ở xa GẤP ĐÔI quãng dự kiến không nhận")
    n.gain = n.gain_sure = None
    ok(n._match([(400, 660), (200, 300)], [(462, 660), (200, 300)], [(400, 660), (200, 300)], m) == ((400, 660), (462, 660)), "nhiều ứng viên cũ: chỉ cái thật sự dời đi mới được ghép")
    ok(n._match([], [(462, 660)], [], m) is None and n._match([(400, 660)], [], [(400, 660)], m) is None, "không có vị trí cũ / không có vệt mới → không nhận")
    st = [(612, 575)]                                   # vật ĐÃ BIẾT là cựa quậy tại chỗ (mũi tên cam nhích qua lại của hộp «Sign Players»)
    ok(n._match([(400, 660)], [(462, 660), (614, 575)], [(400, 660)], m, st) == ((400, 660), (462, 660)),
       "vệt mới thứ hai nằm đúng chỗ một vật ĐÃ BIẾT là cựa quậy tại chỗ → không cản, vẫn nhận con trỏ")
    ok(n._match([(400, 660)], [(462, 660), (120, 1100)], [(400, 660)], m, st) is None,
       "vệt mới thứ hai ở chỗ KHÔNG phải vật đã biết → vẫn chưa phân định (như cũ)")
    ok(n._match([(560, 575)], [(622, 575)], [(560, 575)], m, st) == ((560, 575), (622, 575)),
       "con trỏ đi ngang qua đúng chỗ vật đã biết, không có vệt mới nào khác → vẫn ghép được")
    ok(n._match([(400, 660)], [(462, 660), (614, 575), (130, 1100)], [(400, 660)], m, st + [(120, 1100)]) == ((400, 660), (462, 660))
       and n._match([(560, 575)], [(622, 575), (130, 1100)], [(560, 575)], m, [(612, 575), (120, 1100)]) is None,
       "gạt vật đã biết chỉ khi nhờ đó còn ĐÚNG MỘT vệt mới; mọi vệt mới đều ở chỗ vật đã biết → chưa phân định")
    ok(n._gliding([(400, 660)], [(430, 660), (614, 575)], [(400, 660)], (62, 0), st) is True
       and n._gliding([(400, 660)], [(430, 660), (614, 575)], [(400, 660)], (62, 0)) is False,
       "«đang lướt dở» cũng không bị vật cựa quậy đã biết cản")
    went = Nav._went
    ok(went((100, 100), (160, 100), (60, 0)) and went((100, 100), (184, 100), (60, 0)) and went((100, 100), (145, 104), (60, 0)),
       "«đi theo lệnh di»: đúng hướng, quãng đi 0,6–1,7 lần lệnh (máy thật mỗi máy một tỉ lệ: 1,0 … 1,4 px/đơn vị)")
    ok(not went((100, 100), (160, 140), (60, 0)) and not went((100, 100), (40, 100), (60, 0)) and not went((100, 100), (100, 160), (60, 0)),
       "lệch hướng quá ~25° / đi ngược / đi ngang trong khi lệnh là đi dọc → không phải «đi theo lệnh»")
    ok(not went((100, 100), (125, 100), (110, 0)) and not went((100, 100), (420, 100), (110, 0)) and not went((100, 100), (103, 100), (60, 0)),
       "quãng đi quá ngắn / quá dài so với lệnh, hoặc gần như không nhúc nhích → không nhận")
    ok(went((100, 100), (330, 100), (110, 0)) and not went((100, 100), (330, 100), (110, 0), 1.0) and went((100, 100), (254, 100), (110, 0), 1.4) and not went((100, 100), (170, 100), (110, 0), 1.4),
       "chưa biết tỉ lệ của máy → nhận dải rộng; đã đo được (vd 1,4 px/đơn vị) → chỉ nhận quãng đi sát với dự kiến")
    ok(went((300, 300), (311, 300), (8, 0)) and not went((300, 300), (311, 300), (5, 0)), "nhịp sửa cuối rất ngắn (≥ 8 đơn vị) vẫn kiểm được; ngắn hơn nữa thì không dùng làm bằng chứng")
    # iPhone thật mỗi máy một tốc độ con trỏ: 0,8 … 1,4 … 1,7 pixel cho mỗi đơn vị lệnh
    for gain in (0.6, 0.8, 1.2, 1.4, 1.7, 2.2):
        hits, shots = 0, []
        for target in ((635, 468), (462, 820), (282, 1240), (120, 300), (697, 693)):
            n, w = rig(clock=False); w.gain = gain
            got = n.tap_at(*target)
            # con trỏ được ĐO trong ±12px quanh đích; phép đo lệch tối đa ~2px so với vị trí thật
            good = bool(got) and len(w.clicks) == 1 and abs(w.clicks[0][0] - target[0]) <= 14 and abs(w.clicks[0][1] - target[1]) <= 14
            hits += int(bool(good)); shots.append(w.shots)
        ok(hits == 5 and max(shots) <= 12, "máy đi %.1f px/đơn vị → vẫn bấm đúng cả 5 đích (lệch ≤ 14px), mỗi lần ≤ 12 ảnh chụp" % gain, (hits, shots))
    n, w = rig(clock=False); w.gain = 1.4
    n.tap_at(635, 468); first = w.shots
    w2 = World(clock=False); w2.gain = 1.4; n.h, n.e = FakeHands(w2), FakeEyes(w2)
    n.tap_at(462, 820)
    ok(1.25 <= n.gain <= 1.6 and w2.shots <= first + 1, "tool tự HỌC tỉ lệ của máy (%.2f) → lần bấm sau không tốn thêm ảnh (±1: hướng nhích thử chọn ngẫu nhiên)" % n.gain, (n.gain, first, w2.shots))
    # tỉ lệ đã học KHÔNG còn đúng (người dùng đổi «tốc độ con trỏ» trong Cài đặt, hoặc lần học rơi vào nhịp bị rớt lệnh) → phải tự quên rồi học lại
    for learned, real in ((2.4, 1.0), (0.45, 1.3), (1.0, 2.2)):
        n, w = rig(clock=False); w.gain = real; n.gain = n.gain_sure = learned     # «đã chắc» mà sai (người dùng đổi tốc độ con trỏ)
        got = n.tap_at(462, 820)
        c = w.clicks[0] if w.clicks else None
        ok(got is True and c and abs(c[0] - 462) <= 14 and abs(c[1] - 820) <= 14 and abs(n.gain - real) <= 0.25 * real and w.shots <= 14,
           "đang nhớ tỉ lệ %.2f nhưng máy thật đi %.1f → tự quên, đo lại (%.2f) và vẫn bấm đúng đích" % (learned, real, n.gain or 0), {"ok": got, "clicks": w.clicks, "gain": n.gain, "shots": w.shots})

    # (các bài fuzz decoy dưới đây tắt «nhìn lại khi con trỏ chưa hiện» cho nhanh: tính an toàn không phụ thuộc vào nó)
    saved_relook, Nav.RELOOK = Nav.RELOOK, 0
    # --- verify vòng 6 (N-1): một chấm tròn cỡ con trỏ TỰ CHẠY dọc hàng của đích (hoạt ảnh, băng chuyền) ---
    # Nó «đi đúng hướng, đúng quãng» ngẫu nhiên đúng lúc ta ra lệnh di → qua được phép ghép chuyển động.
    # Chỉ một lần nhìn nữa KHÔNG ra lệnh (con trỏ thật đứng yên, vật tự chạy thì không) mới loại được nó.
    def slide(world, y, step, x0, direction, rng=None):
        orig = world.render
        def render():
            x = x0 + direction * step * world.shots if rng is None else int(rng.integers(40, W - 40))
            x = 40 + (x - 40) % (W - 80)
            world.popup, world.popup_from = (int(x), y), 0
            return orig()
        world.render = render
    off, runs = [], 0
    for vis in (False, True):
        for step in (20, 60, 90):
            for x0 in (60, 300):
                for direction in (1, -1):
                    n, w = rig(visible=vis, clock=False)
                    slide(w, 785, step, x0, direction)
                    n.tap_at(339, 785)
                    runs += 1
                    off += [(vis, step, x0, direction, c) for c in w.clicks if max(abs(c[0] - 339), abs(c[1] - 785)) > 20]
    ok(off == [], "một chấm tròn TỰ CHẠY dọc hàng của đích (%d lượt: con trỏ thật lúc ẩn lúc hiện, 4 tốc độ, 2 chiều) → không cú bấm nào lệch đích" % runs, off[:4])
    off = []
    for seed in range(40):
        n, w = rig(visible=bool(seed % 2), clock=False)
        slide(w, 785, 0, 0, 1, rng=np.random.default_rng(seed))
        n.tap_at(339, 785)
        off += [(seed, c) for c in w.clicks if max(abs(c[0] - 339), abs(c[1] - 785)) > 20]
    ok(off == [], "băng chuyền: một chấm tròn nhảy ngẫu nhiên khắp hàng của đích (40 lượt) → không cú bấm nào lệch đích", off[:4])
    n, w = rig(clock=False)
    got = n.tap_at(339, 785)
    ok(got is True and len(w.clicks) == 1 and abs(w.clicks[0][0] - 339) <= 14 and abs(w.clicks[0][1] - 785) <= 14,
       "(đối chứng) không có vật tự chạy → vẫn bấm đúng đích", w.clicks)

    # --- verify vòng 7 (N-2): vật tự chuyển động nhưng có lúc ĐỨNG YÊN đúng khoảnh khắc ta nhìn thêm ---
    # (dừng-đi, giữ-rồi-nhảy, lướt chậm dần rồi đỗ đúng đích). Cách bắt: xác nhận cần ít nhất một nhịp CHÉO được ghép
    # đúng (vật chạy dọc một hàng không đi theo được lệnh chéo) + lần nhìn không ra lệnh với dung sai chặt.
    def decoy_row(world, kind, y, rng):
        orig = world.render
        wrap = lambda x: 40 + (int(x) - 40) % (W - 80)
        if kind == "dwell":                             # đi s px mỗi khung trong m khung rồi đứng q khung
            s, m, q = int(rng.choice([30, 50, 70, 100])), int(rng.integers(2, 6)), int(rng.integers(1, 4))
            ph, x0, d = int(rng.integers(0, m + q)), int(rng.integers(40, W - 40)), int(rng.choice([-1, 1]))
            def pos(k):
                c, cyc = (k + ph) % (m + q), (k + ph) // (m + q)
                return wrap(x0 + d * s * (cyc * m + min(c, m)))
        elif kind == "hold":                            # đứng yên h khung ở một chỗ ngẫu nhiên rồi nhảy sang chỗ khác
            h, sub, xs = int(rng.integers(1, 4)), np.random.default_rng(int(rng.integers(1 << 30))), {}
            def pos(k):
                if k // h not in xs:
                    xs[k // h] = int(sub.integers(40, W - 40))
                return xs[k // h]
        else:                                           # «ease»: lướt chậm dần rồi ĐỖ ở đích (huy hiệu bay vào nút)
            s0, r_, d = float(rng.choice([60, 100, 120])), float(rng.choice([0.5, 0.7, 0.8])), int(rng.choice([-1, 1]))
            ph, land = int(rng.integers(2, 20)), 339 + int(rng.integers(-5, 6))
            steps, sz = [], s0
            while sz >= 1.0:
                steps.append(sz); sz *= r_
            total = sum(steps)
            def pos(k):
                return int(land - d * (total - sum(steps[:max(0, min(len(steps), k - ph))])))
        def render():
            x = pos(world.shots)
            world.popup, world.popup_from = ((x, y), 0) if 40 <= x <= W - 40 else (None, 0)
            return orig()
        world.render = render
    for kind in ("dwell", "hold", "ease"):
        off, arrived = [], 0
        for seed in range(24):
            rng = np.random.default_rng(1000 + seed)
            n, w = rig(visible=(kind != "ease" and seed % 3 == 0), clock=bool(seed % 2))
            decoy_row(w, kind, 785 + int(rng.integers(-3, 4)), rng)
            arrived += bool(n.tap_at(339, 785))
            off += [(seed, c) for c in w.clicks if max(abs(c[0] - 339), abs(c[1] - 785)) > 20]
        ok(off == [], "vật tròn «%s» chạy dọc hàng của đích, con trỏ thật phần lớn ẩn (24 lượt) → không cú bấm nào lệch đích" % {"dwell": "dừng-đi", "hold": "giữ-rồi-nhảy", "ease": "lướt chậm dần rồi đỗ đúng đích"}[kind], off[:3])
    # --- con trỏ LƯỚT: ảnh chụp ngay sau lệnh di thấy nó mới đi được 40% quãng (hoặc chưa hiện) — đo thật trên iPhone (~0,4 s) ---
    # Phải CHỜ nhìn lại; trước đây coi là «mất dấu» và ra thêm lệnh di thử → con trỏ bị kéo khỏi đích, lặp lại, bấm chậm 10–25 s.
    n, w = rig()
    m_ = (60, 0)
    ok(n._gliding([(400, 660)], [(430, 660)], [(400, 660)], m_) is True
       and n._gliding([(400, 660)], [(462, 660)], [(400, 660)], m_) is False
       and n._gliding([(400, 660)], [(430, 700)], [(400, 660)], m_) is False
       and n._gliding([(400, 660)], [(430, 660), (200, 300)], [(400, 660)], m_) is False
       and n._gliding([(400, 660)], [(400, 660), (430, 660)], [(400, 660)], m_) is False
       and n._gliding([(400, 660)], [], [(400, 660)], m_) is False,
       "nhận biết «đang lướt dở»: đúng hướng nhưng mới đi được nửa quãng → chờ nhìn lại; đã đủ quãng / lệch hướng / có vệt lạ / chỗ cũ chưa trống → không")
    relook_before, Nav.RELOOK = Nav.RELOOK, DEFAULT_RELOOK     # (bài decoy ở phía trên tắt «nhìn lại»; bài này cần đúng giá trị mặc định)
    for mode in ("mid", "gone"):
        shots_l, hits_l, moves_l, off_l = [], 0, [], []
        for i, tgt in enumerate(((635, 468), (462, 820), (282, 1240), (120, 300), (697, 693), (400, 700), (186, 831), (560, 500))):
            n, w = rig(clock=False); w.gain = (0.9, 1.2, 1.4)[i % 3]
            st_ = {"fin": None, "n": 0}
            orig_mv, orig_rd = n.h.move, w.render
            def gmove(dx, dy, w=w, st_=st_, orig_mv=orig_mv, mode=mode):
                x0, y0 = w.x, w.y
                r = orig_mv(dx, dy)
                st_["n"] += 1
                if st_["n"] >= 2 and max(abs(dx), abs(dy)) >= 20 and st_["n"] % 3 == 0:   # thỉnh thoảng (1/3 số nhịp dài) ảnh chụp trúng lúc đang lướt
                    st_["fin"] = (w.x, w.y, mode)
                    if mode == "mid":
                        w.x, w.y = x0 + 0.4 * (w.x - x0), y0 + 0.4 * (w.y - y0)
                return r
            def grender(w=w, st_=st_, orig_rd=orig_rd):
                if st_["fin"] and st_["fin"][2] == "gone":
                    vis, w.visible = w.visible, False
                    img = orig_rd(); w.visible = vis
                else:
                    img = orig_rd()
                if st_["fin"]:
                    w.x, w.y = st_["fin"][0], st_["fin"][1]; st_["fin"] = None
                return img
            n.h.move, w.render = gmove, grender
            got = n.tap_at(*tgt)
            hits_l += int(bool(got) and len(w.clicks) == 1 and abs(w.clicks[0][0] - tgt[0]) <= 14 and abs(w.clicks[0][1] - tgt[1]) <= 14)
            off_l += [(tgt, c) for c in w.clicks if max(abs(c[0] - tgt[0]), abs(c[1] - tgt[1])) > 20]
            shots_l.append(w.shots); moves_l.append(st_["n"])
        ok(hits_l == 8 and off_l == [] and max(shots_l) <= 30,
           "con trỏ %s sau mỗi lệnh di dài → vẫn bấm đúng cả 8 đích, ≤ 30 ảnh/lần (không ra lệnh thừa)" % ("lướt dở (mới đi 40%)" if mode == "mid" else "chưa hiện ở ảnh đầu"),
           (hits_l, shots_l, moves_l, off_l[:2]))
    Nav.RELOOK = relook_before

    # --- verify vòng 8: vật tròn BAY (thẳng hoặc chéo) vào đích rồi ĐỖ ở đó, con trỏ thật ẩn ---
    # Mọi lệnh di của ta đều chỉ về phía đích nên vật đang hội tụ về đích «đi đúng hướng, đúng quãng» miễn phí, rồi đứng yên:
    # qua được phép ghép chuyển động lẫn lần nhìn tĩnh. Chỉ phép thử «đi ra rồi quay về» bắt được: vật đỗ ở đích không làm theo.
    def fly_in(world, target, start, steps_per_frame, appear=0, hold_from=0):
        orig = world.render
        L = math.hypot(target[0] - start[0], target[1] - start[1])
        def render():
            k = world.shots
            if k < appear:
                world.popup, world.popup_from = None, 0
            else:
                t_ = min(L, steps_per_frame * max(0, k - appear - hold_from))
                f = t_ / L if L else 1.0
                world.popup, world.popup_from = ((int(start[0] + (target[0] - start[0]) * f), int(start[1] + (target[1] - start[1]) * f)), 0)
            return orig()
        world.render = render
    tgt = (150, 300)
    bad = []
    for gain in (0.8, 1.0, 1.3):
        for clock in (True, False):
            n, w = rig(visible=False, clock=clock); w.gain = gain
            path = {2: (90, 352), 3: (120, 326)}
            orig_r = w.render
            def r2(w=w, orig_r=orig_r, path=path):
                k = w.shots
                w.popup, w.popup_from = (None, 0) if k < 2 else (path.get(k, tgt), 0)
                return orig_r()
            w.render = r2
            n.tap_at(*tgt)
            bad += [(gain, clock, c) for c in w.clicks if max(abs(c[0] - tgt[0]), abs(c[1] - tgt[1])) > 20]
    ok(bad == [], "(bản gốc của người kiểm) vật tròn bay chéo vào đích trong 3 khung rồi đỗ, con trỏ thật ẩn → không cú bấm nào lệch", bad[:3])
    bad, arrived = [], 0
    for i in range(60):
        rng = np.random.default_rng(777 + i)
        t_ = ((339, 785), (400, 700), (300, 420), (560, 500), (250, 640), (460, 1000), (186, 831))[int(rng.integers(7))]
        ang = float(rng.uniform(0, 2 * math.pi)); d_ = float(rng.choice([80, 120, 200, 300]))
        st = (min(max(t_[0] - d_ * math.cos(ang), 40), W - 40), min(max(t_[1] - d_ * math.sin(ang), 140), H - 40))
        n, w = rig(visible=bool(i % 5 == 0), clock=bool(i % 2)); w.gain = float(rng.choice([0.8, 1.0, 1.3]))
        fly_in(w, t_, st, float(rng.choice([40, 60, 100, 160])), appear=int(rng.integers(0, 4)), hold_from=int(rng.integers(0, 6)))
        arrived += bool(n.tap_at(*t_))
        bad += [(i, t_, c) for c in w.clicks if max(abs(c[0] - t_[0]), abs(c[1] - t_[1])) > 20]
    ok(bad == [], "vật tròn bay vào đích theo mọi hướng / tốc độ rồi đỗ (60 lượt, con trỏ thật thường ẩn) → không cú bấm nào lệch đích", bad[:3])

    # --- độ rộng lần nhìn «đứng yên» (STILL) được GHIM: rung ±1px (hai khung lệch 2px) vẫn qua; rung ±4px (lệch 8px) thì không ---
    def jitter(world, amp):
        orig_j = world.render
        def render():
            x0 = world.x
            world.x = x0 + (amp if world.shots % 2 else -amp)
            out = orig_j()
            world.x = x0
            return out
        world.render = render
    for amp, want in ((1, True), (4, False)):
        hit_j, clicks_j = 0, 0
        for i, tgt in enumerate(((635, 468), (462, 820), (282, 1240), (186, 831), (400, 700), (560, 500))):
            n, w = rig(clock=False); w.gain = (0.9, 1.2, 1.4)[i % 3]
            jitter(w, amp)
            hit_j += bool(n.tap_at(*tgt))
            clicks_j += len(w.clicks)
        ok((hit_j == 6) if want else (hit_j == 0 and clicks_j == 0),
           "con trỏ rung ±%d px giữa các khung (lệch %d px) → %s" % (amp, 2 * amp, "vẫn bấm được cả 6 đích (dung sai STILL=%d)" % Nav.STILL if want else "KHÔNG bấm (đứng yên là bằng chứng; vật trôi/rung mạnh thì không phải con trỏ)"), (hit_j, clicks_j))

    # vật tròn NHẢY ngẫu nhiên 2D quanh đích (huy hiệu nảy gần nút): có thể vô tình khớp cả nhịp chéo → chỉ lần nhìn
    # «không ra lệnh» (vật nhảy thì đã đi chỗ khác) mới loại được. Bỏ lần nhìn đó: 5/300 lượt bấm lệch.
    off, jumps = [], 0
    for i in range(150):
        rng = np.random.default_rng(1 * 9973 + i)
        tgt = ((339, 785), (400, 700), (300, 420), (560, 500), (250, 640), (460, 1000), (186, 831))[int(rng.integers(7))]
        n, w = rig(visible=False, clock=bool(i % 2)); w.gain = float(rng.choice([0.8, 1.0, 1.3]))
        hold_, sub_, cache_ = int(rng.integers(1, 3)), np.random.default_rng(int(rng.integers(1 << 30))), {}
        def jpos(k, hold_=hold_, sub_=sub_, cache_=cache_, tgt=tgt):
            if k // hold_ not in cache_:
                cache_[k // hold_] = (int(np.clip(tgt[0] + sub_.integers(-160, 161), 40, W - 40)), int(np.clip(tgt[1] + sub_.integers(-160, 161), 140, H - 40)))
            return cache_[k // hold_]
        orig_r = w.render
        def jrender(orig_r=orig_r, w=w, jpos=jpos):
            w.popup, w.popup_from = jpos(w.shots), 0
            return orig_r()
        w.render = jrender
        jumps += bool(n.tap_at(*tgt))
        off += [(i, tgt, c) for c in w.clicks if max(abs(c[0] - tgt[0]), abs(c[1] - tgt[1])) > 20]
    # vật «BẮT CHƯỚC»: bám theo mọi lệnh di của con trỏ thật (ẩn) như một cái bóng NHƯNG liên tục trôi lệch 12–48 px mỗi khung
    # (không bao giờ đứng yên) → qua được phép ghép chuyển động và vòng đi–về, chỉ lần nhìn «không ra lệnh» (đứng yên ≤ 3px) loại được nó.
    off, mim = [], 0
    for i in range(40):
        n, w = rig(visible=False, clock=bool(i % 2)); w.gain = (0.9, 1.2, 1.4)[i % 3]
        orig_m = w.render
        def mrender(w=w, orig_m=orig_m, i=i):
            k = w.shots
            w.popup, w.popup_from = (int(min(max(w.x + 12 * (1 + (k * 7 + i) % 4), 40), W - 40)), int(w.y)), 0
            return orig_m()
        w.render = mrender
        tgt = ((339, 785), (400, 700), (300, 420), (560, 500))[i % 4]
        mim += bool(n.tap_at(*tgt))
        off += [(i, tgt, c) for c in w.clicks if max(abs(c[0] - tgt[0]), abs(c[1] - tgt[1])) > 20]
    ok(off == [], "vật «bắt chước» lệnh di nhưng liên tục trôi 12–48 px/khung, con trỏ thật ẩn (40 lượt) → không cú bấm nào lệch đích (lần nhìn «đứng yên» là chốt cuối)", off[:3])
    ok(off == [], "vật tròn NHẢY ngẫu nhiên 2D quanh đích, con trỏ thật ẩn (150 lượt) → không cú bấm nào lệch đích (lần nhìn «không ra lệnh» là lớp chặn cuối)", off[:3])
    Nav.RELOOK = saved_relook

    # --- verify vòng 5: nhịp di ĐẦU bị iOS tăng tốc, đúng lúc đó một vật cỡ con trỏ hiện ra ở chỗ con trỏ «đáng lẽ» đứng ---
    bad = []
    for target, scale, frm in (((60, 60), 4.0, 2), ((54, 54), 2.0, 2), ((70, 50), 3.0, 2), ((60, 60), 4.0, 1), ((60, 60), 4.0, 3)):
        n, w = rig(first_scale=scale, popup=target, popup_from=frm, clock=False)
        n.tap_at(*target)
        bad += [(target, scale, frm, c) for c in w.clicks if max(abs(c[0] - target[0]), abs(c[1] - target[1])) > 20]
    ok(bad == [], "nhịp đầu bị tăng tốc + vật lạ hiện ngay chỗ xuất phát (cũng là đích) → không bấm lệch (trước đây bấm tại (200,200))", bad)

    def late(world, discs, frm, color=(120, 120, 120)):
        """Từ ảnh thứ `frm`, thêm các đĩa cỡ con trỏ ĐỨNG YÊN tại `discs` (icon tải muộn, huy hiệu…)."""
        orig = world.render
        def render():
            img = orig()
            if world.shots >= frm:
                for d in discs:
                    cv2.circle(img, d, R, color, -1)
                if world.visible:
                    img = draw_pointer(img, world.x, world.y)      # con trỏ luôn được vẽ TRÊN mọi thứ
            return img
        world.render = render
        return world

    # hai / ba vật lạ hiện muộn (một cái tại đích, cái kia ngay cạnh) — con trỏ đang hiện bình thường
    off, runs, hit = [], 0, 0
    for target in ((400, 700), (300, 420), (560, 500), (186, 831), (640, 980), (250, 640)):
        for dxo, dyo in ((-60, 0), (60, 0), (-76, 10), (52, -10), (120, 40), (-180, -50)):
            for frm in (2, 3, 4, 5):
                others = [target, (target[0] + dxo, target[1] + dyo)] + ([(target[0] - dxo // 2, target[1] + 90)] if frm % 2 else [])
                n, w = rig(clock=bool(frm % 2))
                late(w, others, frm)
                runs += 1
                hit += int(bool(n.tap_at(*target)))
                off += [(target, (dxo, dyo), frm, c) for c in w.clicks if max(abs(c[0] - target[0]), abs(c[1] - target[1])) > 20]
    ok(off == [] and hit >= runs * 0.6, "2–3 vật lạ hiện muộn quanh đích (%d lượt): KHÔNG cú bấm nào lệch đích; vẫn bấm được ở %d lượt" % (runs, hit), off[:4])
    # verify vòng 5 (kịch bản E): vài lệnh di bị RỚT (con trỏ dừng ở chỗ không ngờ) + vật lạ hiện ra đúng đích
    class DropHands(FakeHands):
        def __init__(self, world, drop):
            super().__init__(world); self.drop, self.k = set(drop), 0
        def move(self, dx, dy):
            self.k += 1
            if self.k in self.drop:
                return "OK move"                           # board báo OK nhưng con trỏ không nhúc nhích
            return super().move(dx, dy)
    off, runs = [], 0
    rng = np.random.default_rng(5)
    for target in ((400, 700), (300, 420), (560, 500), (186, 831), (640, 980), (250, 640)):
        for frm in (2, 3, 4, 5, 6):
            for _ in range(3):
                drop = set(int(v) for v in rng.integers(2, 14, size=int(rng.integers(1, 5))))
                n, w = rig(clock=False)
                n.h = DropHands(w, drop)
                late(w, [target], frm)
                runs += 1
                n.tap_at(*target)
                off += [(target, frm, sorted(drop), c) for c in w.clicks if max(abs(c[0] - target[0]), abs(c[1] - target[1])) > 20]
    ok(off == [], "lệnh di bị rớt + vật lạ hiện đúng đích (%d lượt) → không cú bấm nào lệch (trước đây lệch tới ~400px)" % runs, off[:3])
    # Nhịp di DÀI bị rớt một phần → con trỏ dừng giữa đường và đúng lúc đó KHÔNG dò ra được nữa, đồng thời một vật lạ
    # hiện ra ngay tại đích (chỗ con trỏ «đáng lẽ» phải tới). Vệt mới duy nhất + chỗ cũ đã trống → ghép được, nhưng
    # đó là sau một nhịp dài (kiểm lỏng) → KHÔNG được bấm ngay; nhịp kiểm ngắn kế tiếp sẽ lộ ra nó đứng yên.
    n, w = rig(clock=False)
    n.h = DropHands(w, {3})
    late(w, [(300, 420)], 4)
    orig_v = w.render
    def lost_midway():
        w.visible = (w.shots + 1) < 4
        return orig_v()
    w.render = lost_midway
    got = n.tap_at(300, 420)
    ok(not [c for c in w.clicks if max(abs(c[0] - 300), abs(c[1] - 420)) > 20],
       "tới «đích» bằng một nhịp DÀI thì chưa bấm: phải có thêm một nhịp ngắn xác nhận (con trỏ thật đang ở cách đích ~150px)", {"ok": got, "clicks": w.clicks, "con trỏ thật": (round(w.x), round(w.y))})
    # Cả màn hình tối đi ĐỀU sau khi chụp ảnh nền (không sinh ra vệt cỡ con trỏ nào) → vẫn phải chụp lại ảnh nền
    n, w = rig(clock=False)
    orig_d = w.render
    def dimmed():
        if w.shots + 1 == 3:
            w.base = np.clip(w.base.astype(np.int16) - 40, 0, 255).astype(np.uint8)
        return orig_d()
    w.render = dimmed
    got = n.tap_at(400, 700)
    ok(got is True and abs(w.clicks[0][0] - 400) <= 14 and abs(w.clicks[0][1] - 700) <= 14 and w.homes == 4,
       "cả màn hình đổi đều (tối đi) sau khi chụp ảnh nền → chụp lại ảnh nền rồi bấm đúng", {"ok": got, "clicks": w.clicks, "homes": w.homes})

    # con trỏ KHÔNG dò ra + hai vật lạ đứng yên cách nhau đúng một quãng nhích thử
    wrong = []
    for target in ((400, 700), (300, 420), (560, 500), (100, 100), (60, 60)):
        for side in (-60, 60):
            for frm in (1, 2, 3):
                n, w = rig(visible=False, clock=False)
                late(w, [target, (target[0] + side, target[1])], frm)
                got = n.tap_at(*target)
                wrong += [(target, side, frm, got, w.clicks)] if (got or w.clicks) else []
    ok(wrong == [], "con trỏ không dò ra + hai vật đứng yên cách nhau đúng quãng nhích thử → không bấm (30 lượt, trước đây 20/48 lượt bấm sai)", wrong[:3])
    # hai nút tròn xám CÓ SẴN cách nhau 60px, con trỏ không dò ra
    wrong = []
    for target in ((300, 110), (420, 640)):
        n, w = rig(visible=False, clock=False)
        cv2.circle(w.base, (600, 250), 24, (242, 242, 242), -1)
        cv2.circle(w.base, target, 20, (150, 150, 150), -1)
        cv2.circle(w.base, (target[0] + 60, target[1]), 20, (150, 150, 150), -1)
        got = n.tap_at(*target)
        wrong += [(target, got, w.clicks)] if (got or w.clicks) else []
    ok(wrong == [], "hai nút tròn xám có sẵn cách nhau 60px, con trỏ không dò ra → không bấm", wrong)
    # một khối phẳng mới hiện ra (toast) có kèm icon tròn cỡ con trỏ, nằm đúng đích
    n, w = rig(clock=False)
    orig_r = w.render
    def toast():
        img = orig_r()
        if w.shots >= 3:
            cv2.rectangle(img, (150, 600), (450, 690), (60, 60, 60), -1)
            cv2.circle(img, (240, 646), 19, (230, 230, 230), -1)
            if w.visible:
                img = draw_pointer(img, w.x, w.y)
        return img
    w.render = toast
    n.tap_at(240, 646)
    ok(all(max(abs(c[0] - 240), abs(c[1] - 646)) <= 20 for c in w.clicks), "một thông báo nổi có icon tròn hiện ra đúng đích → không nhận icon làm con trỏ (có bấm thì đúng đích)", w.clicks)
    # đích nằm sát chỗ xuất phát: tới nơi ngay ở nhịp xác nhận đầu → phải có thêm một nhịp xác nhận nữa rồi mới bấm
    n, w = rig(clock=False)
    got = n.tap_at(150, 150)
    ok(got is True and abs(w.clicks[0][0] - 150) <= 14 and abs(w.clicks[0][1] - 150) <= 14 and w.shots >= 4,
       "đích sát chỗ xuất phát → vẫn đòi phép thử «đi – đứng yên – về» rồi mới bấm", {"clicks": w.clicks, "shots": w.shots})

    n, w = rig()
    w.swap_from = 2                                        # ảnh nền chụp lúc trang cũ còn đang trượt đi; từ ảnh sau là trang mới
    got = n.tap_at(400, 700)
    c = w.clicks[0] if w.clicks else None
    ok(got is True and c and abs(c[0] - 400) <= 14 and abs(c[1] - 700) <= 14 and w.homes == 4,
       "màn hình đổi SAU khi chụp ảnh nền (chuyển trang xong muộn) → tự chụp lại ảnh nền rồi vẫn bấm đúng", {"ok": got, "clicks": w.clicks, "homes": w.homes})
    n, w = rig(button=(380, 720, 660, 840))
    n.tap_at(520, 780)
    ok(w.homes == 2, "một cái nút sáng lên (đổi vài % màn hình) KHÔNG bị coi là «màn hình đã đổi» → không chụp lại ảnh nền thừa", w.homes)
    n, w = rig()
    w.clock = True
    flip = {"k": 0}
    orig_render = w.render
    def flicker():                                         # màn hình đổi liên tục (video nền): mỗi ảnh một kiểu
        flip["k"] += 1
        w.base = make_screen(seed=flip["k"])[::(-1 if flip["k"] % 2 else 1)].copy()
        return orig_render()
    w.render = flicker
    got = n.tap_at(400, 700)
    ok(w.homes <= 2 * Nav.REANCHOR_MAX and (got is False or abs(w.clicks[0][0] - 400) <= 14), "màn hình đổi KHÔNG NGỪNG → chỉ chụp lại ảnh nền vài lần rồi thôi (không lặp vô hạn), không bấm bừa", {"ok": got, "homes": w.homes, "clicks": w.clicks})

    print("\n== 3c. Cử chỉ: bấm giữ, vuốt ==")
    n, w = rig()
    ok(n.hold_at(636, 468, 1.3) is True and w.gestures == [("hold", w.gestures[0][1], w.gestures[0][2], 1.3)] and abs(w.gestures[0][1] - 636) <= 14 and abs(w.gestures[0][2] - 468) <= 14 and w.clicks == [],
       "bấm giữ: đưa con trỏ tới đúng chỗ rồi mới nhấn-giữ, không bấm thêm cú nào", w.gestures)
    n, w = rig(visible=False)
    ok(n.hold_at(636, 468, 1.3) is False and w.gestures == [], "con trỏ không tới nơi → KHÔNG nhấn giữ", w.gestures)
    for d, (sx, sy, sign) in {"left": (0.93 * W, 0.52 * H, (-1, 0)), "right": (0.07 * W, 0.52 * H, (1, 0)),
                              "up": (0.5 * W, 0.75 * H, (0, -1)), "down": (0.5 * W, 0.32 * H, (0, 1))}.items():
        n, w = rig()
        got = n.flick(d)
        g = w.gestures[0] if w.gestures else None
        good = got is True and g and g[0] == "swipe" and abs(g[1] - sx) <= 14 and abs(g[2] - sy) <= 14 \
            and (g[3] * sign[0] > 0 or sign[0] == 0 and g[3] == 0) and (g[4] * sign[1] > 0 or sign[1] == 0 and g[4] == 0)
        ok(good and (abs(g[3]) >= W if sign[0] else abs(g[4]) >= 0.3 * H),
           "vuốt %s: xuất phát đúng mép, kéo đúng hướng%s" % (d, ", dài hơn cả bề ngang (lật trang phải qua nửa màn hình)" if sign[0] else ""), g)
    n, w = rig()
    n.swipe(375, 1000, 375, 400)
    g = w.gestures[0]
    ok(g[3] == 0 and g[4] == round(-600 * Nav.SWIPE_GAIN), "vuốt theo toạ độ: bù phần con trỏ đi hụt khi kéo dài", g)
    n, w = rig(visible=False)
    ok(n.flick("left") is False and w.gestures == [], "không đưa được con trỏ tới điểm đầu → không vuốt", w.gestures)
    n, w = rig(visible=False)
    ok(n.swipe(375, 1000, 375, 400) is False and w.gestures == [], "vuốt theo toạ độ cũng vậy: không tới điểm đầu → không nhấn nút", w.gestures)

    print("\n== 3e. Máy xoay NGANG (game): chuột vẫn chạy theo trục dọc của máy, ảnh chụp thì xoay theo giao diện ==")
    # Đo thật trên iPhone 8 đang mở eFootball: «về góc» đưa con trỏ lên góc trên-PHẢI của ảnh ngang; +x của chuột = đi XUỐNG trên ảnh.
    from nav import Frame

    class Landscape(FakeEyes):
        """Mắt của máy đang xoay ngang: thế giới giả vẫn tính trong hệ trục của chuột (dọc); ảnh chụp là ảnh đó QUAY đi."""
        def __init__(self, world, rot):
            super().__init__(world)
            self.fr = Frame(rot, H, W)                      # ảnh chụp ngang: rộng H, cao W
            self.verified = []

        def screenshot(self):
            return self.fr.raw(self.w.render())

        def to_img(self, u, v):                             # điểm trong hệ trục chuột → điểm trên ảnh chụp ngang
            return (H - 1 - v, u) if self.fr.rot == "ccw" else (v, W - 1 - u)

        def find_text(self, needle, img=None, scale=2):
            if img is not None:
                self.verified.append(img.shape[:2])
            if needle != "Wi-Fi" or (self.w.label_until is not None and self.w.shots > self.w.label_until):
                return None
            return self.to_img(*self.LABEL_AT)

    def lrig(rot, **kw):
        n, w = rig(**kw)
        n.e = Landscape(w, rot)
        return n, w
    fr = Frame("ccw", H, W)
    ok(fr.pt(*Landscape(World(), "ccw").to_img(186, 831)) == (186, 831) and Frame("cw", H, W).pt(*Landscape(World(), "cw").to_img(186, 831)) == (186, 831)
       and fr.vec(100, 0) == (0, -100) and fr.vec(0, 100) == (100, 0) and Frame("cw", H, W).vec(100, 0) == (0, 100) and Frame(0, W, H).pt(5, 6) == (5, 6) and Frame(0).vec(3, 4) == (3, 4),
       "đổi điểm / quãng kéo giữa ảnh chụp và hệ trục của chuột (hai chiều xoay ngang + máy dọc)")
    probe = np.arange(H * W * 3, dtype=np.uint32).astype(np.uint8).reshape(W, H, 3)       # một ảnh ngang bất kỳ
    ok(all((Frame(r, H, W).raw(Frame(r, H, W).dev(probe)) == probe).all() for r in ("ccw", "cw", 0)) and Frame("ccw", H, W).dev(probe).shape[:2] == (H, W),
       "quay ảnh về hệ trục chuột rồi quay trả lại → đúng ảnh cũ")
    for rot in ("ccw", "cw"):
        side = "trên-phải" if rot == "ccw" else "dưới-trái"
        for name, (u, v) in {"giữa màn": (186, 831), "gần đáy": (400, 1150), "sát mép": (700, 600)}.items():
            n, w = lrig(rot)
            X, Y = n.e.to_img(u, v)
            got = n.tap_at(X, Y)
            c = w.clicks[0] if w.clicks else None
            ok(got is True and len(w.clicks) == 1 and abs(c[0] - u) <= 14 and abs(c[1] - v) <= 14 and n._fr.rot == rot,
               "máy ngang (góc «về» ở %s của ảnh), điểm %s: tự nhận ra hướng, bấm đúng 1 lần đúng chỗ" % (side, name), {"ok": got, "clicks": w.clicks, "rot": n._fr.rot})
        n, w = lrig(rot)
        got = tap_text(n, "Wi-Fi")
        ok(got is True and len(w.clicks) == 1 and abs(w.clicks[0][0] - 186) <= 14 and abs(w.clicks[0][1] - 831) <= 14 and n.e.verified and all(sz == (W, H) for sz in n.e.verified),
           "máy ngang (%s): bấm vào chữ — toạ độ tìm trên ảnh ngang, hàm kiểm «chữ còn đó không» nhận lại ảnh NGANG như ảnh chụp" % side, (w.clicks, n.e.verified[:2]))
        n, w = lrig(rot, label_until=2)
        ok(tap_text(n, "Wi-Fi") is False and w.clicks == [], "máy ngang (%s): chữ biến mất trước khi con trỏ tới → KHÔNG bấm" % side, w.clicks)
        n, w = lrig(rot)
        X, Y = n.e.to_img(636, 468)
        ok(n.hold_at(X, Y, 1.3) is True and w.gestures and w.gestures[0][0] == "hold" and abs(w.gestures[0][1] - 636) <= 14 and abs(w.gestures[0][2] - 468) <= 14,
           "máy ngang (%s): bấm giữ đúng chỗ" % side, w.gestures)
        # vuốt: hướng nói theo ẢNH (trái / phải / lên / xuống như người nhìn màn hình ngang), chuột phải kéo theo hệ trục của nó
        for d, ui in {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}.items():
            n, w = lrig(rot)
            got = n.flick(d)
            g = w.gestures[0] if w.gestures else None
            want = Frame(rot, H, W).vec(*ui)                # hướng chuột phải kéo
            good = got is True and g and g[0] == "swipe" and (g[3] * want[0] > 0 or (want[0] == 0 and g[3] == 0)) and (g[4] * want[1] > 0 or (want[1] == 0 and g[4] == 0))
            ok(good, "máy ngang (%s): vuốt %s trên màn hình → chuột kéo đúng hướng theo trục của nó %s" % (side, d, want), g)
        n, w = lrig(rot)
        x1, y1 = n.e.to_img(375, 600)
        n.swipe(x1, y1, x1 + 300, y1)                       # kéo 300px sang PHẢI trên ảnh ngang
        g = w.gestures[0] if w.gestures else None
        want = Frame(rot, H, W).vec(300, 0)
        ok(g and g[0] == "swipe" and (g[3], g[4]) == (round(want[0] * Nav.SWIPE_GAIN), round(want[1] * Nav.SWIPE_GAIN)) and abs(g[1] - 375) <= 14 and abs(g[2] - 600) <= 14,
           "máy ngang (%s): vuốt theo toạ độ — điểm đầu đúng chỗ, quãng kéo đổi sang trục của chuột" % side, g)
    n, w = lrig("ccw", visible=False)
    ok(n.tap_at(600, 300) is False and w.clicks == [], "máy ngang mà KHÔNG thấy con trỏ rời góc nào (không biết ảnh xoay chiều nào) → không bấm", w.clicks)
    n, w = lrig("ccw")
    ok(n.tap_at(H + 50, 20) is False and n.tap_at(20, W + 50) is False and w.clicks == [], "điểm cần bấm nằm ngoài màn hình → không bấm")
    n, w = lrig("ccw")
    n.tap_at(*n.e.to_img(186, 831))
    n.e = FakeEyes(w)                                       # app trở lại màn hình dọc
    w.clicks.clear()
    ok(n.tap_at(186, 831) is True and n._fr.rot == 0 and abs(w.clicks[0][0] - 186) <= 14 and abs(w.clicks[0][1] - 831) <= 14, "xoay ngang rồi về lại dọc: mỗi lần bấm tự xác định lại hướng", (n._fr.rot, w.clicks))

    class Both(Landscape):                                  # ảnh gây nhầm: «con trỏ» hiện ở cả hai góc cùng lúc
        def screenshot(self):
            img = super().screenshot().copy()
            if self.w.shots >= 2:
                cv2.circle(img, (60, W - 60), R, (70, 70, 70), -1)
            return img
    n, w = lrig("ccw")
    n.e = Both(w, "ccw")
    ok(n.tap_at(600, 300) is False and w.clicks == [], "không phân định được hướng (dấu hiệu con trỏ ở hai góc) → KHÔNG bấm, không đoán", w.clicks)

    class Turning(Landscape):                               # ảnh chụp ĐỔI chiều giữa lúc đang đưa con trỏ (ngang → dọc) từ ảnh thứ `at`
        at = 5

        def screenshot(self):
            return super().screenshot() if self.w.shots + 1 < self.at else self.w.render()
    for at in (3, 5, 8):
        n, w = lrig("ccw")
        n.e = Turning(w, "ccw")
        n.e.at = at
        X, Y = n.e.to_img(186, 831)
        ok(n.tap_at(X, Y) is False and w.clicks == [], "ảnh chụp đổi cỡ / chiều GIỮA lúc đưa con trỏ (từ ảnh thứ %d) → toạ độ đích không còn đúng → KHÔNG bấm" % at, w.clicks)

    seen_steady = []

    class Spy(FakeEyes):                                    # trong lúc đưa con trỏ, cách quay ảnh THẲNG của máy phải được giữ nguyên
        def screenshot(self):
            seen_steady.append(Eyes._steady.get(None, 0))
            return super().screenshot()
    n, w = rig()
    n.e = Spy(w)
    got = n.tap_at(400, 700)
    ok(got is True and len(seen_steady) > 2 and seen_steady[0] == 0 and all(s > 0 for s in seen_steady[1:]) and Eyes._steady.get(None, 0) == 0,
       "tap_at: ảnh NỀN đầu tiên chụp ngoài «steady» (được xét lại cách quay — bước bấm toạ độ không có lần nhìn nào trước), mọi ảnh sau giữ "
       "nguyên cách quay; xong thì nhả", (got, seen_steady[:5], Eyes._steady.get(None)))
    seen_steady.clear()
    n, w = rig(visible=False)
    n.e = Spy(w)
    ok(n.tap_at(400, 700) is False and Eyes._steady.get(None, 0) == 0, "không tới nơi (không bấm) → cũng nhả «steady»", Eyes._steady.get(None))

    print("\n== 3d. Lệnh xuống board: gửi liền mạch, bấm giữ luôn nhả, không bấm đôi ==")
    class FakeSerial:
        """Cổng serial giả: trả "OK <lệnh>" cho mỗi dòng nhận được. `feed` = các MẨU dữ liệu board «nhả» dần
        (mỗi lần đọc một mẩu) thay cho câu trả lời tự sinh — để dựng cảnh dòng về nửa chừng, dòng lạ chen vào…"""
        def __init__(self, drop=(), feed=None, early=None):
            self.writes, self.queue, self.timeout, self.drop = [], b"", 2.0, set(drop)
            self.feed, self.reads = (list(feed) if feed is not None else None), 0
            self.early = list(early or [])     # các mẩu tới TRƯỚC khi lệnh kế được ghi (câu trả lời muộn của lệnh trước)
        def reset_input_buffer(self): self.queue = b""
        def flush(self): pass
        def write(self, data):
            self.writes.append(data.decode())
            if self.feed is not None:
                return
            for line in data.decode().split("\n"):
                if line and line not in self.drop:
                    self.queue += ("OK " + line.split(" ")[0] + "\n").encode()
        @property
        def in_waiting(self): return len(self.queue)
        def read(self, n=1):
            self.reads += 1
            if self.early and not self.writes:
                self.queue += self.early.pop(0)
            elif self.feed and self.writes:
                self.queue += self.feed.pop(0)
            if not self.queue:
                REAL_SLEEP(0.002)
            out, self.queue = self.queue[:n], self.queue[n:]
            return out
    def board(**kw):
        h = Hands.__new__(Hands); h.ser = FakeSerial(**kw); h._rx, h._sent_at = b"", 0.0; return h
    handsmod.time.sleep = lambda s: None
    h = board()
    r = h.burst(["down", "move -900 0", "up"], wait=0.2)
    ok(h.ser.writes == ["down\nmove -900 0\nup\n"] and r == ["OK down", "OK move", "OK up"], "burst: cả chuỗi lệnh đi trong MỘT lần ghi (nhấn-kéo-nhả không bị ngắt quãng)", h.ser.writes)
    h = board()
    ok(h.click() == "OK click" and h.ser.writes == ["move 1 0\nmove -1 0\nclick\nmove 1 0\nmove -1 0\n"], "bấm: đánh thức con trỏ → bấm đúng MỘT lần", h.ser.writes)
    h = board(drop={"click"})
    ok(not h.click().startswith("OK click") and len(h.ser.writes) == 1, "bấm mà mất phản hồi → KHÔNG tự bấm lại (tránh bấm đôi)", h.ser.writes)
    h = board()
    naps = []
    handsmod.time.sleep = lambda s: naps.append(round(s, 2))
    got = h.swipe(-900, 0)
    handsmod.time.sleep = lambda s: None
    again = "up\nmove 1 0\nmove -1 0\n"
    ok(got is True and h.ser.writes[0] == "move 1 0\nmove -1 0\ndown\nmove -900 0\nup\nmove 1 0\nmove -1 0\n", "vuốt: nhấn → kéo → nhả liền một mạch", h.ser.writes)
    ok(h.ser.writes[1:] == [again, again] and [x for x in naps if x in Hands.RELEASE_AGAIN] == list(Hands.RELEASE_AGAIN),
       "sau cú kéo: nghỉ rồi báo «đã nhả» thêm 2 lần (gói nhả đầu hay bị rớt sau loạt gói kéo dồn dập → trang kẹt lưng chừng)", (h.ser.writes[1:], naps))
    h = board(drop={"up"})
    ok(h.swipe(0, -400) is False and len(h.ser.writes) == 3 and all(x.startswith("up\n") for x in h.ser.writes[1:]), "vuốt mà không thấy xác nhận «nhả» → vẫn gửi nhả lại, và báo «không chắc»", h.ser.writes)
    h = board()
    ok(h.hold(1.0) is True and h.ser.writes[0].endswith("down\n") and h.ser.writes[1].startswith("up\n"), "bấm giữ: nhấn … nhả", h.ser.writes)
    h = board()
    def boom(s): raise KeyboardInterrupt()
    handsmod.time.sleep = boom
    try:
        h.hold(1.0); raised = False
    except KeyboardInterrupt:
        raised = True
    handsmod.time.sleep = lambda s: None
    ok(raised and any(w.startswith("up\n") for w in h.ser.writes), "bấm giữ bị ngắt giữa chừng → VẪN gửi lệnh nhả (chuột không kẹt ở trạng thái nhấn)", h.ser.writes)
    class Flaky(FakeSerial):                         # cổng rớt đúng lúc đọc phản hồi của lệnh «nhấn» (lệnh đã ghi ra rồi)
        boom = True
        def read(self, n=1):
            if Flaky.boom and self.writes:
                Flaky.boom = False
                raise OSError("cổng serial rớt")
            return super().read(n)
    for what, fn in (("bấm giữ", lambda hh: hh.hold(0.1)), ("vuốt", lambda hh: hh.swipe(-300, 0))):
        Flaky.boom = True
        h = board(); h.ser = Flaky()
        try:
            fn(h); raised = False
        except OSError:
            raised = True
        ok(raised and any(w.startswith("up\n") for w in h.ser.writes[1:]),
           "%s: lệnh «nhấn» đã ghi ra rồi mà cổng lỗi giữa chừng → VẪN gửi lệnh nhả (trước đây nút có thể kẹt ở trạng thái nhấn)" % what, h.ser.writes)

    # --- đọc phản hồi của board: trả NGAY khi có câu trả lời của chính lệnh đó ---
    h = board()
    t0 = time.time(); r = h.send("move 110 0", wait=3.0); dt = time.time() - t0
    ok(r == "OK move" and dt < 0.3, "có câu trả lời là trả về NGAY (không chờ thêm cho hết giờ)", (r, round(dt, 2)))
    h = board(feed=[b"OK mo", b"", b"ve\nOK cl", b"ick\n"])
    ok(h.send("click") == "OK click", "phản hồi MUỘN của lệnh trước («OK move») không bị nhận nhầm; dòng về nửa chừng được ghép lại cho trọn", h.ser.writes)
    h = board(feed=[b"[D][BLE] notify queued\n"])
    t0 = time.time(); r = h.send("key enter"); dt = time.time() - t0
    ok(r == "[D][BLE] notify queued" and 0.45 <= dt < 1.2, "chỉ có dòng lạ → chờ hết ~0,5s rồi trả dòng lạ (bên gọi coi là «không chắc»)", (r, round(dt, 2)))
    h = board(feed=[])
    t0 = time.time(); r = h.send("click"); dt = time.time() - t0
    ok(r == "" and 0.45 <= dt < 1.2, "board im lặng → trả chuỗi rỗng sau ~0,5s", (r, round(dt, 2)))
    h = board(feed=[b"ERR not-connected\n"])
    t0 = time.time(); r = h.send("click", wait=3.0)
    ok(r == "ERR not-connected" and time.time() - t0 < 0.3, "board từ chối (ERR…) → trả ngay")
    ok(board(feed=[b"pong\n"]).send("ping") == "pong" and board(feed=[b"NAME iPhoneFarm-01\n"]).send("whoami") == "NAME iPhoneFarm-01"
       and board(feed=[b"OK ble=connected\n"]).send("status") == "OK ble=connected", "ping / whoami / status: nhận đúng kiểu câu trả lời riêng của chúng")
    h = board(feed=[b"OK move\nOK mo", b"ve\n", b"OK click\n"])
    ok(h.burst(["move 1 0", "move -1 0", "click"], wait=0.3) == ["OK move", "OK move", "OK click"], "burst cũng ghép dòng về nửa chừng")
    h = board()
    h.send("move 5 0"); h.send("key enter"); h.burst(["move 1 0", "move -1 0"])
    p0 = h.presses
    h.click(); p1 = h.presses
    h.swipe(10, 0); p2 = h.presses
    h.hold(0.3); p3 = h.presses
    ok((p0, p1, p2, p3) == (0, 1, 2, 3), "đếm số lần NHẤN nút: di chuột / phím không tính; bấm, vuốt, giữ mỗi thứ +1 (để biết một cử chỉ hỏng đã kịp chạm vào máy chưa)", (p0, p1, p2, p3))
    class DropBle(FakeSerial):                       # Bluetooth rớt đúng lúc đang giữ: lệnh nhả bị board từ chối
        def write(self, data):
            self.writes.append(data.decode())
            for line in data.decode().split("\n"):
                if line:
                    self.queue += (("ERR not-connected" if (line == "up" and not self.back) else "OK " + line.split(" ")[0]) + "\n").encode()
    h = board(); h.ser = DropBle(); h.ser.back = False; waited = []
    def reconnect(t):
        waited.append(t); h.ser.back = True; return True
    h.wait_connected = reconnect
    got = h.hold(0.2)
    ok(got is True and waited == [8] and sum(1 for w_ in h.ser.writes if w_.startswith("up\n")) == 2,
       "đang giữ thì Bluetooth rớt (lệnh nhả bị từ chối) → CHỜ nối lại rồi nhả lần nữa, không bỏ mặc nút ở trạng thái nhấn", (got, waited, h.ser.writes))
    h = board(); h.send("move 1 0"); real = []
    handsmod.time.sleep = lambda s: real.append(round(s, 3))
    h.send("move 1 0"); handsmod.time.sleep = lambda s: None
    ok(len(real) == 1 and 0 < real[0] <= Hands.MIN_GAP, "hai lệnh liền nhau được giãn ra một nhịp nhỏ (không dồn sự kiện sát nhau)", real)
    # --- không cho thứ lạ lọt xuống board (verify vòng 5, W-4) ---
    h = board()
    bad = 0
    for cmd in ("key enter\nclick", "type tiếng Việt", "combo gui h\rdown", ""):
        try:
            h.send(cmd)
        except ValueError:
            bad += 1
    try:
        h.burst(["move 1 0", "up\ndown"])
    except ValueError:
        bad += 1
    ok(bad == 5 and h.ser.writes == [], "lệnh có lẫn xuống dòng / chữ có dấu / rỗng → từ chối, KHÔNG ghi gì ra cổng (xuống dòng = một lệnh thứ hai chạy mù)", (bad, h.ser.writes))
    # --- câu trả lời MUỘN của lệnh trước không được tính cho lệnh sau (W-5) ---
    h = board(feed=[])
    ok(h.send("type abcdef") == "" and h._owed is True, "lệnh hết giờ không có câu trả lời → ghi nhớ là còn «nợ» một câu trả lời")
    h.ser = FakeSerial(early=[b"OK type 6\n"], feed=[b"OK click\n"])
    ok(h.send("click") == "OK click" and h._owed is False and h.ser.early == [], "lệnh kế: chờ board im rồi mới gửi → câu trả lời muộn của lệnh trước bị bỏ đi, không lẫn vào", h.ser.writes)
    h = board(feed=[]); h.send("type abcdef")
    h.ser = FakeSerial(feed=[b"ERR not-connected\n"])
    r = h.send("key enter")
    ok(r == "" and h._owed is True, "đang «nợ» mà chỉ thấy một dòng ERR (không biết của lệnh nào) → KHÔNG coi là của lệnh mới (trước đây làm tool gửi lại phím Enter)", r)
    h.ser = FakeSerial(feed=[b"ERR not-connected\n", b"OK key enter\n"])
    ok(h.send("key enter") == "OK key enter" and h._owed is False, "…còn khi câu trả lời ĐÚNG TÊN lệnh tới thì nhận và hết «nợ»")
    h = board(feed=[b"OK move\n"])
    r = h.send("click")
    ok(r == "", "hết giờ mà chỉ thấy «OK» của lệnh KHÁC → không được coi là lệnh này đã chạy (trước đây trả «OK move» → bị hiểu là bấm thành công)", r)
    h = board(feed=[b"[D] log\n", b"OK move\n"])
    ok(h.burst(["move 1 0"], wait=0.3) == ["OK move"], "burst: dòng log của board không bị đếm là một câu trả lời")
    h = board(drop={"up"})
    h.burst(["down", "up"], wait=0.2)
    ok(h._owed is True, "burst thiếu câu trả lời → cũng ghi nhớ là còn «nợ»")

    # --- đường chụp nhanh: hỏng thì quay về cách cũ và NGHỈ dùng nó một lúc; dữ liệu rác không được coi là ảnh ---
    import eyes as eyesmod
    real_grab, real_avail = eyesmod.fastshot.grab, eyesmod.fastshot.AVAILABLE
    ev = Eyes("UDID-GIA")
    tries, slow = [], []
    def boom(udid): tries.append(udid); raise RuntimeError("mất kết nối")
    def old_way(path):
        slow.append(path); cv2.imwrite(path, np.full((40, 30, 3), 77, np.uint8)); return True
    ev._grab_png = old_way
    try:
        eyesmod.fastshot.AVAILABLE, eyesmod.fastshot.grab = True, boom
        Eyes._fast_off.clear()
        a = ev.screenshot(); n1 = len(tries)
        b = ev.screenshot(); n2 = len(tries)
        ok(a.shape == (40, 30, 3) and n1 == 2 and len(slow) == 2 and n2 == 2, "đường nhanh hỏng → thử lại 1 lần, rồi chụp kiểu cũ; các ảnh sau KHÔNG chờ đường nhanh nữa (nghỉ %ds)" % Eyes.FAST_COOLDOWN, (n1, n2, len(slow)))
        Eyes._fast_off["UDID-GIA"] = 0
        ev.screenshot()
        ok(len(tries) == 4, "hết thời gian nghỉ → thử lại đường nhanh")
        Eyes._fast_off.clear(); slow.clear()
        okpng = cv2.imencode(".png", np.full((20, 10, 3), 200, np.uint8))[1].tobytes()
        eyesmod.fastshot.grab = lambda udid: okpng
        c = ev.screenshot()
        ok(c.shape == (20, 10, 3) and slow == [], "đường nhanh chạy được → dùng ảnh của nó, không gọi lệnh kiểu cũ")
        eyesmod.fastshot.grab = lambda udid: b"day khong phai anh"
        d = ev.screenshot()
        ok(d.shape == (40, 30, 3) and len(slow) == 1, "đường nhanh trả dữ liệu KHÔNG phải ảnh → bỏ, chụp kiểu cũ")
    finally:
        eyesmod.fastshot.grab, eyesmod.fastshot.AVAILABLE = real_grab, real_avail
        Eyes._fast_off.clear()

    # --- dò board: cổng đang bị chương trình khác giữ = «bận», không phải «chưa nạp firmware» ---
    import esp as espmod
    real_serial = espmod.QuietSerial
    class Locked:
        def __init__(self): self.exclusive = None
        def open(self): raise espmod.serial.SerialException("Could not exclusively lock port /dev/cu.x: [Errno 35] Resource temporarily unavailable")
    class Dead(Locked):
        def open(self): raise espmod.serial.SerialException("could not open port: No such file or directory")
    try:
        espmod.QuietSerial = Locked
        p1 = espmod.probe("/dev/cu.x")
        espmod.QuietSerial = Dead
        p2 = espmod.probe("/dev/cu.x")
    finally:
        espmod.QuietSerial = real_serial
    ok(p1["busy"] is True and p1["flashed"] is False and p2["busy"] is False, "dò một cổng đang bị giữ độc quyền → báo «bận»; cổng hỏng thật thì không", (p1, p2))

    if os.name == "posix":
        import pty
        master, slave = pty.openpty()
        path = os.ttyname(slave)
        first = Hands(path)
        try:
            Hands(path); second = "mở được (SAI)"
        except RuntimeError as e:
            second = str(e)
        first.close()
        third = Hands(path); third.close()
        os.close(master); os.close(slave)
        ok("đang được chương trình khác điều khiển" in second, "cổng đang có bên điều khiển → bên mở sau bị TỪ CHỐI rõ ràng (không còn cảnh hai bên đọc lẫn phản hồi)", second)
        ok(True, "bên trước đóng cổng → mở lại được")

    class BurstNav:                                  # board trả lời theo kịch bản cho stepexec.click()
        def __init__(self, scripts): self.h = self; self.scripts, self.calls = list(scripts), 0; self.WAKE = Hands.WAKE
        def burst(self, cmds, wait=1.0): self.calls += 1; return self.scripts.pop(0) if self.scripts else []
        def wait_connected(self, t): return True
    full = ["OK move", "OK move", "OK click", "OK move", "OK move"]
    b = BurstNav([full]); ok(stepexec.click(b) == (True, "", True) and b.calls == 1, "stepexec.click: bấm được → đúng một lần gửi")
    b = BurstNav([["ERR not-connected"] * 5] * 3)
    r = stepexec.click(b); ok(r[0] is False and r[2] is False and b.calls == 3, "Bluetooth chưa nối (board từ chối CHÍNH lệnh bấm) → thử lại, báo chắc chắn chưa bấm", (r, b.calls))
    b = BurstNav([["ERR not-connected", "OK move"], full])
    r = stepexec.click(b); ok(r[0] is False and r[2] is True and b.calls == 1, "Bluetooth vừa nối lại giữa chừng, mất phản hồi của lệnh bấm → KHÔNG gửi lại (tránh bấm đôi), báo «không chắc»", (r, b.calls))

    class OneReply:
        def __init__(self, reply): self.h = self; self.reply = reply
        def send(self, cmd, wait=0.5): return self.reply
        def wait_connected(self, t): return True
    ok(stepexec.hid(OneReply("OK key enter"), "key enter") == (True, "", True), "phản hồi OK → đã chạy")
    r = stepexec.hid(OneReply("ERR key?"), "key f13"); ok(r[0] is False and r[2] is False, "board TỪ CHỐI lệnh (ERR…) → chắc chắn chưa chạy", r)
    r = stepexec.hid(OneReply("[D][BLE] notify queued"), "key enter"); ok(r[0] is False and r[2] is True, "board in ra dòng lạ thay cho phản hồi → KHÔNG được coi là chưa chạy", r)
    r = stepexec.hid(OneReply(""), "key enter"); ok(r[0] is False and r[2] is True, "board im lặng → không chắc", r)

    print("\n== 4. Kiểm bàn phím: bộ gõ tiếng Việt (Telex / VNI) phải bị phát hiện ==")
    tx, vn = Nav.KB_PROBES[0][1], Nav.KB_PROBES[1][1]
    ok(Nav.keyboard_ok(tx, "Q " + tx) and Nav.keyboard_ok(vn, ["", "x " + vn + " x"]), "tiếng Anh: đọc lại đúng chuỗi thử (ở ô tìm kiếm hoặc ở dòng gợi ý) → đạt")
    ok(Nav.keyboard_ok(tx, "Q ddaa ee oo dd aa eel") and Nav.keyboard_ok(tx, "goi y cua siri dd aa ee oo dd aa ee trang web"),
       "tiếng Anh, chữ còn đang hiện dần / OCR nhầm chữ cuối → vẫn đạt (2 lần đọc thật trên iPhone)")
    ok(Nav.keyboard_ok(vn, "Q a6 e6 o7 u7 d9 a8 e6 07") and Nav.keyboard_ok(tx, ". dd aa ee 00 ddaaee qd ("), "tiếng Anh nhưng OCR lẫn o/0 → vẫn đạt (lần đọc thật trên iPhone)")
    st = lambda probe, seen: Nav.keyboard_state(probe, next(m for _, p, m in Nav.KB_PROBES if p == probe), seen)
    ok(st(tx, ["", "Q daéodaed x)"]) == "ime" and st(tx, telex(tx)) == "ime" and st(vn, vni(vn)) == "ime",
       "THẤY RÕ chữ đã bị bộ gõ biến đổi («đ â ê ô…») → kết luận «đang Telex/VNI»", st(tx, ["", "Q daéodaed x)"]))
    ok(st(tx, ["", "", "Mes éeeskh ou."]) == "unreadable" and st(tx, []) == "unreadable",
       "OCR đọc hụt / ra chữ rác → «không đọc được», KHÔNG kết luận là Telex", st(tx, ["Mes éeeskh ou."]))
    ok(not Nav.keyboard_ok(tx, telex(tx)) and not Nav.keyboard_ok(tx, [telex(tx), "goi y cua siri " + telex(tx)]), "Telex: «dd aa ee oo…» ra «đ â ê ô…» → KHÔNG đạt", telex(tx))
    ok(not Nav.keyboard_ok(tx, "Q d a e o d a e o"), "Telex mà OCR đọc mất dấu → vẫn KHÔNG đạt")
    ok(not Nav.keyboard_ok(vn, vni(vn)), "VNI: «a6 e6 o7…» ra «â ê ơ…» → KHÔNG đạt", vni(vn))
    ok(not Nav.keyboard_ok(tx, "") and not Nav.keyboard_ok(tx, []) and not Nav.keyboard_ok(tx, "Q"), "không đọc được gì → KHÔNG đạt (nghi ngờ thì dừng)")
    ok(not Nav.keyboard_ok(tx, "Lỗi gõ aa, dd, ee, oo thành dđ, aâ, eê, oô trên Máy tính"), "chữ trong kết quả tìm web («lỗi gõ aa, dd, ee, oo…») không bị nhận nhầm là chuỗi vừa gõ")
    ok(not Nav.keyboard_ok("afaf", "âf"), "ca thật trên máy: «afaf» ra «âf» → KHÔNG đạt (cách cũ cho qua vì còn chữ f)")

    for mode, switchable, want, name in [("en", True, True, "đang tiếng Anh → đạt ngay, không đổi bộ gõ"),
                                         ("telex", True, True, "đang Telex, Ctrl+Space đổi được → tự đổi sang tiếng Anh rồi đạt"),
                                         ("vni", True, True, "đang VNI, Ctrl+Space đổi được → tự đổi rồi đạt"),
                                         ("telex", False, False, "máy CHỈ có bàn phím tiếng Việt → báo không đạt (tool sẽ dừng máy)")]:
        kb = Keyboard(mode, switchable)
        n = Nav.__new__(Nav)
        n.h, n.e = kb, kb
        got, seen = n.ensure_english()
        extra = (kb.mode == "en" and kb.field == "" and (kb.switches == 0 if mode == "en" else kb.switches >= 1)) if want else (kb.field == "" and n.kb_reason == "ime")
        ok(got is want and extra, name, {"ok": got, "mode": kb.mode, "switches": kb.switches, "field": kb.field, "seen": seen, "why": n.kb_reason})
    kb = Keyboard("en", True, blind=99)             # máy đang đúng tiếng Anh nhưng OCR không đọc ra chữ nào
    n = Nav.__new__(Nav)
    n.h, n.e = kb, kb
    got, seen = n.ensure_english()
    ok(got is False and n.kb_reason == "unreadable" and kb.switches == 0 and kb.mode == "en",
       "không đọc được chữ gõ thử → KHÔNG bấm đổi bộ gõ (máy đang đúng vẫn giữ nguyên), báo «không đọc được»", {"ok": got, "why": n.kb_reason, "switches": kb.switches})
    kb = Keyboard("en", True, blind=2)              # hai lần chụp đầu OCR hụt, lần sau đọc được
    n = Nav.__new__(Nav)
    n.h, n.e = kb, kb
    got, seen = n.ensure_english()
    ok(got is True and kb.switches == 0, "OCR hụt vài lần rồi đọc được → đạt, không đổi bộ gõ", {"ok": got, "switches": kb.switches})

    print("\n" + ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if FAIL == 0 else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(Nav.MISS_DIR, ignore_errors=True) if "ipf-tap-miss-" in Nav.MISS_DIR else None
