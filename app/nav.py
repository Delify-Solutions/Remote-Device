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
import contextlib, math, os, random, sys, time

import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hands import Hands
from eyes import Eyes, norm_text


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class Frame:
    """Hướng của ẢNH CHỤP so với HỆ TRỤC CỦA CHUỘT.

    Chuột Bluetooth luôn chạy theo hệ trục DỌC của máy: lệnh «về góc» ghim con trỏ ở góc trên-trái của máy cầm dọc, +x là sang phải,
    +y là xuống. Khi một app xoay NGANG (game), ảnh chụp màn hình xoay theo giao diện nhưng con trỏ thì KHÔNG — đo thật trên iPhone 8 đang
    mở eFootball: «về góc» đưa con trỏ lên góc trên-PHẢI của ảnh ngang, di +x làm con trỏ đi XUỐNG trên ảnh, di +y làm nó đi sang TRÁI.
    Mọi phép đo con trỏ vì vậy làm trong hệ trục của chuột: ảnh chụp được quay về hệ đó (`dev`), điểm cần bấm được đổi sang (`pt`),
    quãng kéo được đổi sang (`vec`); ảnh đưa cho hàm kiểm của bên gọi thì quay trả lại như ảnh chụp (`raw`).

    rot = 0      ảnh chụp cùng chiều với hệ trục của chuột (máy dọc);
    rot = "ccw"  quay ảnh 90° NGƯỢC chiều kim đồng hồ thì về hệ trục của chuột (góc «về» nằm ở trên-phải của ảnh ngang);
    rot = "cw"   quay ảnh 90° THEO chiều kim đồng hồ (góc «về» nằm ở dưới-trái của ảnh ngang)."""

    def __init__(self, rot=0, w: int = 0, h: int = 0):
        self.rot, self.w, self.h = rot, int(w), int(h)       # w, h = cỡ ẢNH CHỤP

    def dev(self, img):
        if self.rot == "ccw":
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self.rot == "cw":
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        return img

    def raw(self, img):
        if self.rot == "ccw":
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        if self.rot == "cw":
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img

    def pt(self, x, y):
        """Điểm (x, y) trên ảnh chụp → điểm trong hệ trục của chuột."""
        if self.rot == "ccw":
            return int(y), int(self.w - 1 - x)
        if self.rot == "cw":
            return int(self.h - 1 - y), int(x)
        return int(x), int(y)

    def vec(self, dx, dy):
        """Quãng (dx, dy) trên ảnh chụp → quãng di của chuột."""
        if self.rot == "ccw":
            return dy, -dx
        if self.rot == "cw":
            return -dy, dx
        return dx, dy


class Nav:
    _fr = Frame()         # hướng ảnh chụp ↔ hệ trục chuột của lần đưa con trỏ gần nhất (vuốt / lật trang dùng để đổi hướng kéo)

    def __init__(self, port: "str | None", udid: str):
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

    NUDGE = 60            # quãng di THỬ (đơn vị move) khi chưa biết vệt nào là con trỏ. Lớn hơn 1,5 lần cỡ con trỏ
                          # để vị trí cũ và mới của con trỏ tách hẳn nhau trên ảnh.
    TRACK_SETTLE = 0.15   # nghỉ sau nhịp di cuối rồi mới chụp: để iOS vẽ xong con trỏ ở chỗ mới (ảnh chụp giờ gần như tức thì)
    PRE_SETTLE = 0.25     # nghỉ trước khi chụp ảnh nền
    STALE_REF = 0.08      # ảnh mới khác ảnh nền quá 8% diện tích = màn hình đã ĐỔI (không phải chỉ có con trỏ / một nút sáng lên)
    REANCHOR_MAX = 3      # số lần tối đa chụp ảnh nền trong một lần bấm
    SAME = 6              # hai vệt lệch nhau ≤ 6px ở hai ảnh liên tiếp = cùng một thứ ĐỨNG YÊN
    gain = None           # con trỏ đi được bao nhiêu pixel cho mỗi đơn vị lệnh di. None = chưa đo trên máy này;
                          # tap_at tự HỌC ở nhịp xác nhận đầu tiên rồi dùng cho các lần sau. Mỗi máy / mỗi mức
                          # «tốc độ con trỏ» trong Cài đặt của iPhone một khác — đo thật trên hai iPhone 8:
                          # máy A 0,88–0,93 (một nhịp lẻ) … 1,00 (nhiều nhịp liền); máy B 0,94–1,17 … 1,27.
    gain_sure = None      # tỉ lệ ĐÃ CHẮC (hai lần đo liên tiếp khớp nhau trong 25%): chỉ tỉ lệ này mới được dùng để SIẾT phép kiểm
                          # «đi đúng quãng» (_match). Tỉ lệ mới đo một lần chỉ dùng để tính nhịp di — vì một vật lạ cũng có thể
                          # «dạy» tỉ lệ sai từ chuyển động của chính nó (verify vòng 8: học 0,4 từ vật sắp đỗ rồi để nó lọt qua).
    GAIN_RANGE = (0.5, 2.5)  # iPhone thật nằm trong khoảng này (đo: 0,9–1,4); số đo ngoài khoảng bị bỏ, không học
    FORGET = 2            # tỉ lệ đã học mà bấy nhiêu nhịp LIỀN không ghép được con trỏ → coi là sai, quên đi, học lại
    rng = random.Random()  # chọn hướng nhích thử (test gán Random(seed) để lặp lại được)
    STILL = 4             # lần nhìn «không ra lệnh» sau nhịp «nhích đi»: con trỏ thật đứng yên TUYỆT ĐỐI (đo thật 0 px trên 2 iPhone 8; cho ≤ 4px
                          # để chừa sai số đo / máy lướt chậm hơn); vật tự chuyển động thì không. Độ rộng này được ghim bằng test (jitter ±1 qua, ±4 trượt).

    @staticmethod
    def _went(a, b, move, gain=None) -> bool:
        """`b` có phải là «`a` sau khi đi theo lệnh di `move`» không: phải đi ĐÚNG HƯỚNG (lệch không quá ~25°) và
        quãng đi hợp lý so với quãng ra lệnh. Không so với một điểm đến cứng, vì tỉ lệ pixel/đơn vị tuỳ máy:
          • chưa biết tỉ lệ của máy (`gain=None`) → nhận dải rộng 0,45–2,6 lần;
          • đã đo được (`gain`) → chỉ nhận 0,6–1,6 lần quãng DỰ KIẾN (= gain × quãng ra lệnh)."""
        L = math.hypot(move[0], move[1])
        vx, vy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(vx, vy)
        if L < 8 or d <= 6:
            return False
        lo, hi = (0.45 * L, 2.6 * L) if gain is None else (0.6 * gain * L, 1.6 * gain * L)
        if not (lo - 12 <= d <= hi + 12):
            return False
        return (vx * move[0] + vy * move[1]) / (d * L) >= 0.9

    def _match(self, sources, now, before, move):
        """Trong ảnh mới, vệt nào là CON TRỎ? Chỉ nhận bằng chứng CHUYỂN ĐỘNG — con trỏ là thứ duy nhất trên màn
        hình đi theo lệnh di chuột. Vệt `b` (trong `now`) là con trỏ khi có vị trí cũ `a` (trong `sources`) mà:
          • b nằm ở chỗ «a đi theo quãng vừa ra lệnh di» — đúng hướng, quãng đường hợp lý (xem _went);
          • chỗ của b ở ảnh TRƯỚC còn trống — b vừa mới tới đó, không phải thứ đứng sẵn;
          • chỗ của a ở ảnh MỚI đã trống — thứ ở a đã rời đi; thứ đứng yên thì vẫn còn nguyên đó;
          • b là vệt mới DUY NHẤT trên cả màn hình. Có thêm một vệt mới nào khác (dù ở xa) thì chưa biết cái nào
            mới là con trỏ: lệnh di có thể bị rớt làm con trỏ dừng ở chỗ không ngờ, đúng lúc một icon hiện ra
            ngay chỗ «đáng lẽ» nó phải tới.
        `before` = mọi vệt cỡ con trỏ của ảnh trước. Trả cặp (a, b) khi có ĐÚNG MỘT cách ghép; không có, hoặc chưa
        phân định được → None.

        Vì sao phải chặt như vậy: icon tải muộn, số đếm, huy hiệu, nút tròn… đều «giống con trỏ» trên một ảnh tĩnh.
        Nhận nhầm một thứ như thế nằm đúng đích = bấm trong khi con trỏ thật đang ở chỗ khác."""
        fresh = [c for c in now if not any(_dist(c, q) <= self.SAME for q in before)]
        if len(fresh) != 1:
            return None                                     # không có vệt mới, hoặc có từ hai vệt mới → chưa phân định
        b = fresh[0]
        came_from = [a for a in sources
                     if not any(_dist(c, a) <= self.SAME for c in now)                       # chỗ cũ đã trống
                     and self._went(a, b, move, self.gain_sure)]                             # và b là «a đi theo lệnh di»
        return (came_from[0], b) if len(came_from) == 1 else None

    RELOOK = 2            # số lần tối đa «chỉ nhìn lại» (không ra lệnh mới) khi con trỏ chưa hiện rõ sau một nhịp di

    def _gliding(self, sources, now, before, move) -> bool:
        """Con trỏ có vẻ đang LƯỚT DỞ tới chỗ cuối: có đúng một vệt mới, chỗ cũ của nó đã trống, nó đi ĐÚNG HƯỚNG lệnh di
        nhưng mới được một đoạn NGẮN hơn dự kiến. iOS làm con trỏ lướt mượt ~0,4 s sau lệnh di — ảnh chụp trúng lúc đó
        thấy con trỏ ở giữa đường (hoặc mờ, không thấy). Khi đó phải CHỜ và nhìn lại, KHÔNG ra lệnh di thử mới: lệnh thừa
        kéo con trỏ ra khỏi chỗ nó vừa tới rồi lại lướt dở lần nữa (vòng lặp đo thật: bấm chậm 10–25 s hoặc hỏng)."""
        fresh = [c for c in now if not any(_dist(c, q) <= self.SAME for q in before)]
        if len(fresh) != 1:
            return False
        b, L = fresh[0], math.hypot(move[0], move[1])
        g = self.gain or 1.0
        for a in sources:
            if any(_dist(c, a) <= self.SAME for c in now):
                continue
            vx, vy = b[0] - a[0], b[1] - a[1]
            d = math.hypot(vx, vy)
            if L >= 8 and d > 6 and d < 0.6 * g * L and (vx * move[0] + vy * move[1]) / (d * L) >= 0.9:
                return True
        return False

    def _frame(self, raw, verbose=False):
        """Hướng của ảnh chụp `raw` (chụp lúc con trỏ đang ghim ở góc) so với hệ trục của chuột. Gọi NGAY SAU khi đã ra lệnh rời góc
        (50, 50). Ảnh dọc: cùng chiều. Ảnh ngang: chụp thêm một ảnh rồi xem con trỏ vừa hiện ra ở gần góc nào — thử cả ba cách quay,
        phải có ĐÚNG MỘT cách cho thấy con trỏ nằm ở chỗ nó phải nằm (cách góc «về» chừng 50 đơn vị theo đường chéo). Không phân định
        được → None (bên gọi không bấm)."""
        H, W = raw.shape[:2]
        if H >= W:
            return Frame(0, W, H)
        time.sleep(self.TRACK_SETTLE)
        try:
            raw2 = self.e.screenshot()
        except Exception:
            raw2 = None
        if raw2 is None or raw2.shape != raw.shape:
            if verbose: print("  (máy đang xoay ngang nhưng không chụp được ảnh để xem con trỏ nằm góc nào)")
            return None
        hits = []
        for rot in ("ccw", "cw", 0):
            fr = Frame(rot, W, H)
            a, b = fr.dev(raw), fr.dev(raw2)
            D = self.e.pointer_size(a)
            for x, y, _ in self.e.pointer_blobs(a, b, [(0, 0, int(D * 0.7), int(D * 0.7))]):
                if 20 <= x <= 120 and 20 <= y <= 120 and abs(x - y) <= 30:      # ~50 đơn vị theo đường chéo, tính từ góc «về»
                    hits.append(fr)
                    break
        if len(hits) != 1:
            if verbose: print("  (máy đang xoay ngang: %s → KHÔNG bấm)" % ("không thấy con trỏ rời góc nào" if not hits else "con trỏ có vẻ ở nhiều góc cùng lúc"))
            return None
        if verbose: print("  (máy đang xoay ngang: hệ trục chuột = ảnh quay %s)" % {"ccw": "90° ngược chiều kim đồng hồ", "cw": "90° theo chiều kim đồng hồ", 0: "0°"}[hits[0].rot])
        return hits[0]

    def tap_at(self, px: int, py: int, tol: int = 12, iters: int = 34, click=True, verbose=False, verify=None):
        """Xem _tap_at. Trong lúc đưa con trỏ, cách quay ảnh THẲNG của máy được giữ nguyên (Eyes.steady)."""
        # Ảnh NỀN đầu tiên được chụp NGOÀI steady (được xét lại cách quay nếu tới hạn): bước bấm theo toạ độ không có lần nhìn nào trước đó,
        # cách quay nhớ từ màn hình trước có thể đã cũ. Từ sau ảnh đó mới giữ nguyên (xem anchor).
        with contextlib.ExitStack() as hold:
            self._hold = hold
            try:
                return self._tap_at(px, py, tol, iters, click, verbose, verify)
            finally:
                self._hold = None

    def _tap_at(self, px: int, py: int, tol: int = 12, iters: int = 34,
                click=True, verbose=False, verify=None):
        """Đưa con trỏ tới pixel (px,py) rồi click. Trả True nếu con trỏ ĐÃ tới nơi.
        KHÔNG tới được thì KHÔNG click (bấm bừa vào chỗ khác còn tệ hơn là không bấm).

        Vòng kín: ghim góc → chụp ảnh NỀN → nhích ra → lặp (chụp, tìm con trỏ, di ≤CAP về đích) tới khi sát đích.
        «Tới nơi» = con trỏ được ĐO trong ±tol quanh đích VÀ được xác nhận bằng chuyển động: vệt được coi là con trỏ
        khi nó dời đi đúng theo lệnh di (xem _match), rồi qua phép thử «đi – đứng yên – về» tại đích (nhích ra chỗ trống,
        đứng yên tuyệt đối, quay lại bằng một nhịp ngắn). Không có nhánh suy đoán nào: không đo được, không phân định
        được → không bấm.

        Ảnh nền được chụp lại (tối đa REANCHOR_MAX lần) khi màn hình đổi nhiều, hoặc khi xuất hiện một vệt ĐỨNG YÊN
        qua một lệnh di — tức một thứ mới thêm vào màn hình sau khi chụp nền (icon tải muộn…): đưa nó vào nền thì
        nó hết gây nhiễu, và con trỏ đi lên trên nó vẫn đo được.

        `verify(ảnh) -> bool`: gọi MỘT lần ngay trước khi báo «tới nơi», trên ảnh chụp gần nhất mà con
        trỏ chưa che đích. Trả False = thứ cần bấm không còn ở đó (màn hình đã đổi trong lúc đưa con
        trỏ tới) → không bấm, trả False.

        (px, py) và ảnh đưa cho `verify` là toạ độ / ảnh CỦA ẢNH CHỤP như bên gọi thấy. Bên trong, mọi thứ làm trong HỆ TRỤC CỦA CHUỘT
        (xem Frame): máy đang xoay ngang thì ảnh được quay về hệ đó trước khi đo."""
        tol = max(int(tol), 12)            # nhịp di nhỏ hơn 10 đơn vị không dùng làm bằng chứng chuyển động được
        fr = None                          # hướng ảnh chụp ↔ hệ trục chuột, xác định ở lần ghim góc đầu tiên

        def grab():
            """Chụp màn hình, trả ảnh đã quay về hệ trục của chuột."""
            return fr.dev(self.e.screenshot())

        def anchor():
            """Ghim con trỏ về góc trên-trái (của hệ trục chuột), chụp ảnh NỀN (con trỏ không che gì), rồi nhích ra cho con trỏ hiện."""
            nonlocal fr
            self.home()
            time.sleep(self.PRE_SETTLE)
            try:
                shot = self.e.screenshot()
            except Exception:
                shot = None
            hold, steady = getattr(self, "_hold", None), getattr(self.e, "steady", None)
            if hold is not None and steady is not None and fr is None:
                hold.enter_context(steady())          # từ đây tới hết lần bấm: giữ nguyên cách quay ảnh của máy
            self.h.move(50, 50)            # rời góc để con trỏ hiện (ở góc là nửa hình, khó thấy)
            if shot is None:
                return None
            if fr is None:
                fr = self._frame(shot, verbose)
                if fr is None:
                    return None
            elif shot.shape[:2] != (fr.h, fr.w):
                if verbose: print("  (cỡ / chiều ảnh chụp đổi giữa chừng — màn hình đã khác) -> KHÔNG click")
                return None
            return fr.dev(shot)

        ref = anchor()
        anchors = 1
        if ref is None:
            if verbose: print("  (không chụp được ảnh nền / không rõ hướng màn hình) -> KHÔNG click")
            return False
        self._fr = fr
        px, py = fr.pt(px, py)             # từ đây (px, py) là điểm đích TRONG HỆ TRỤC CỦA CHUỘT
        H, W = ref.shape[:2]
        if not (0 <= px < W and 0 <= py < H):
            if verbose: print("  (điểm cần bấm nằm ngoài màn hình) -> KHÔNG click")
            return False
        D = self.e.pointer_size(ref)
        corner = [(0, 0, int(D * 0.7), int(D * 0.7))]       # phần tư con trỏ ghim ở góc trong ảnh nền
        clear = ref if _dist((px, py), (0, 0)) > 1.5 * D else None    # ảnh đích chưa bị con trỏ che
        # sources: các vị trí Ở ẢNH TRƯỚC có thể là con trỏ (None = chưa có ảnh nào để so);  before: mọi vệt của ảnh trước;
        # move: quãng đã ra lệnh di kể từ ảnh trước;  expect: chỗ con trỏ nhiều khả năng đang đứng;  streak: số nhịp xác nhận liền nhau
        sources, before, move, expect, streak, pos = None, [], (50, 50), (54, 54), 0, None
        misses = 0                         # số nhịp liền có đủ dữ kiện để ghép (có vị trí cũ, có vệt, có lệnh di) mà không ghép được
        relooks = 0                        # số lần liền đã «chỉ nhìn lại» (xem _gliding)
        statics = []                       # vệt ĐÃ BIẾT là đứng yên / cựa quậy tại chỗ, không phải con trỏ (icon đồng hồ có kim chạy…)
        lost = 0                           # số lần liền hoàn toàn không thấy vệt nào dù đã nhìn lại (mất dấu hẳn)

        def reanchor():
            """Ghim lại góc + chụp lại ảnh nền, bỏ mọi hiểu biết cũ về vị trí con trỏ. False = không chụp được ảnh nền."""
            nonlocal ref, clear, anchors, sources, before, move, expect, streak, pos, misses, away_ok, away_pending, relooks, lost
            anchors += 1
            ref = anchor()
            if ref is None:
                return False
            clear = ref if _dist((px, py), (0, 0)) > 1.5 * D else None
            sources, before, move, expect, streak, pos = None, [], (50, 50), (54, 54), 0, None
            misses, away_ok, away_pending, relooks, lost = 0, False, False, 0, 0
            return True
        away_pending = False               # vừa ra lệnh «nhích đi» TẠI ĐÍCH, đang chờ xem con trỏ có đi theo không
        away_ok = False                    # …và con trỏ đã đi theo (bước 1 của phép thử «đi – về»); bước 2 là nhịp quay lại đích
        gain0 = (self.gain, self.gain_sure)    # tỉ lệ của máy trước lần bấm này (để trả lại nếu lần học trong lần bấm này hoá ra do vật lạ)

        def plan(frm, limit):
            """Các nhịp di (mỗi nhịp ≤CAP) để đi ~90% quãng từ `frm` tới đích, tối đa `limit` nhịp. Trả tổng (gx, gy).
            Quãng còn lại (pixel) được đổi ra đơn vị lệnh theo tỉ lệ đã học của máy này (self.gain)."""
            g = self.gain or 1.0
            ex, ey = (px - frm[0]) / g, (py - frm[1]) / g
            hops = min(limit, -(-int(max(abs(ex), abs(ey)) * 0.9) // self.CAP))
            least = max(8, int(math.ceil(10.0 / g)))              # nhịp nhỏ nhất còn dùng làm bằng chứng chuyển động (≥ ~10px)
            gx = gy = 0
            for k in range(max(1, hops)):
                mx = max(-self.CAP, min(self.CAP, int((ex - gx) * 0.9)))
                my = max(-self.CAP, min(self.CAP, int((ey - gy) * 0.9)))
                if mx == 0 and my == 0:
                    break
                big = max(abs(mx), abs(my))
                if k == 0 and big < least:      # còn lệch rất ít: vẫn phải di đủ một nhịp «thấy được»
                    mx, my = int(round(mx * least / big)), int(round(my * least / big))
                self.h.move(mx, my); time.sleep(0.1)
                gx += mx; gy += my
            return gx, gy

        grad_cache = {}

        def busy(cx, cy):
            """Độ «bận» của ảnh nền quanh (cx,cy): trung bình độ lớn gradient trong cửa sổ ~1,6·D (chữ, icon, hình vẽ = cao;
            hình nền trống = thấp). Con trỏ đáp xuống chỗ bận (nhất là lên nhãn chữ dưới icon) rất khó tách ra khỏi nền.
            None = chỗ đáp quá sát mép màn hình (không dùng)."""
            if grad_cache.get("ref") is not ref:
                gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
                grad_cache["g"] = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
                grad_cache["ref"] = ref
            r = int(0.8 * D)
            x0, y0, x1, y1 = int(cx) - r, int(cy) - r, int(cx) + r, int(cy) + r
            m = int(1.5 * D)                    # lề an toàn: con trỏ sát mép màn hình hay bị cắt / mờ (đo thật: các vết lỗi đi kèm chỗ đáp x ≈ 710–722)
            if cx < m or cy < m or cx > W - m or cy > H - m:
                return None
            if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
                return None
            return float(grad_cache["g"][y0:y1, x0:x1].mean())

        def nudge(frm):
            """Một lệnh di THỬ (quãng ~NUDGE·1,4) đáp xuống CHỖ TRỐNG của ảnh nền: thử 8 hướng (4 chéo + 4 thẳng), bỏ hướng
            đẩy con trỏ ra mép / lên chỗ có chữ và icon (đo thật: nhích chéo từ icon «Sách» rơi đúng lên nhãn «Sách» → con
            trỏ biến mất khỏi ảnh, bấm hỏng hoặc chậm 10–25 s), rồi chọn NGẪU NHIÊN trong các hướng trống nhất — một vật tự
            chuyển động không đoán trước được hướng nên không thể giả vờ đi theo."""
            g = self.gain or 1.0
            n = self.NUDGE
            cands = []
            for vx, vy in ((n, n), (n, -n), (-n, n), (-n, -n), (int(n * 1.4), 0), (-int(n * 1.4), 0), (0, int(n * 1.4)), (0, -int(n * 1.4))):
                score = busy(frm[0] + vx * g, frm[1] + vy * g)
                if score is not None:
                    cands.append((score, vx, vy))
            if cands:
                best = min(c[0] for c in cands)
                vx, vy = self.rng.choice([(c[1], c[2]) for c in cands if c[0] <= best * 1.5 + 6])
            else:                                   # ảnh nền quá chật để chọn: nhích ngang về phía giữa màn hình
                vx, vy = (n if frm[0] < W / 2 else -n), 0
            self.h.move(vx, vy)
            return vx, vy

        for i in range(iters):
            time.sleep(self.TRACK_SETTLE)
            img = grab()
            if img.shape != ref.shape:     # cỡ / chiều ảnh đổi giữa chừng: toạ độ đích không còn đúng → không bấm
                if verbose: print("  (cỡ / chiều ảnh chụp đổi giữa chừng) -> KHÔNG click")
                return False
            now = [c[:2] for c in self.e.pointer_blobs(ref, img, corner)]
            # `vis` = các vệt KHÔNG nằm gần vật đã biết là đứng yên / cựa quậy tại chỗ (cỡ một icon, ~30px). Chỉ dùng `vis` để chọn
            # «chỗ con trỏ có thể đang đứng» và để xét «mất dấu» — đừng di chuột theo vệt kim đồng hồ (đo thật: con trỏ bị đẩy sát
            # mép và mất dấu hẳn). Phép GHÉP chuyển động vẫn dùng đủ `now`: con trỏ đi ngang qua một vật tĩnh vẫn phải ghép được.
            vis = [c for c in now if not any(_dist(c, q) <= 30 for q in statics)]
            moved = max(abs(move[0]), abs(move[1])) >= 8
            # Ảnh nền hết dùng được khi: (a) màn hình ĐỔI NHIỀU so với nó (chuyển trang chưa xong lúc chụp nền, nội
            # dung tải muộn, hộp thoại vừa bật…); (b) có vệt ĐỨNG YÊN qua một lệnh di = một thứ mới thêm vào màn hình.
            still = [c for c in vis if moved and any(_dist(c, q) <= self.SAME for q in before)]
            stale = self.e.changed_fraction(ref, img) > self.STALE_REF
            if still:
                statics.extend(still)
                del statics[:-8]
            if (stale or still) and anchors < self.REANCHOR_MAX:
                if verbose:
                    print("     %s → chụp lại ảnh nền (lần %d)" % ("màn hình đã đổi so với ảnh nền" if stale else "có vật mới đứng yên %s" % still, anchors + 1))
                if not reanchor():
                    return False
                continue

            pair = self._match(sources, now, before, move) if (sources is not None and moved) else None
            p = pair[1] if pair else None
            if verbose:
                print(f"  [{i}] vệt={now} | con trỏ={'%s (đã xác nhận %d nhịp)' % (p, streak + 1) if p else 'CHƯA phân định'}")
            if (p is None and moved and relooks < self.RELOOK
                    and (not vis or (sources is not None and self._gliding(sources, now, before, move)))):
                # Không thấy vệt nào, hoặc con trỏ mới đi được nửa đường (đang lướt): CHỜ rồi nhìn lại, không ra lệnh mới.
                relooks += 1
                if verbose: print("     (con trỏ chưa hiện rõ / đang lướt dở → nhìn lại, KHÔNG ra lệnh mới)")
                time.sleep(0.3)
                continue
            relooks = 0
            lost = lost + 1 if (p is None and not vis) else 0
            if lost >= 2 and anchors < self.REANCHOR_MAX + 1:
                # Hoàn toàn không thấy vệt nào dù đã nhìn lại: con trỏ có thể đã bị đẩy sát mép / ra khỏi tầm nhìn. Ghim lại góc và
                # chụp lại ảnh nền (được MỘT lần thêm ngoài hạn mức của vật đứng yên) thay vì di chuột mò trong bóng tối.
                if verbose: print("     (mất dấu con trỏ hẳn → ghim lại góc, chụp lại ảnh nền (lần %d))" % (anchors + 1))
                if not reanchor():
                    return False
                continue
            if p is None:
                # Lần nhìn đầu / vừa mất dấu / chưa phân định được → ra một lệnh di THỬ rồi nhìn lại: vệt nào dời đi
                # đúng theo lệnh thì đó là con trỏ. Nếu có vệt ở gần chỗ con trỏ hay đứng thì di thử luôn MỘT nhịp
                # về phía đích tính từ vệt đó (đoán đúng thì khỏi phí một nhịp); đang sát đích thì nhích ngang.
                streak, pos, away_ok, away_pending = 0, None, False, False
                if sources and now and moved:
                    misses += 1
                    if misses >= self.FORGET and self.gain is not None:
                        # Có vệt cũ, có vệt mới, có lệnh di mà mấy nhịp liền không cặp nào «đi theo lệnh»: nhiều khả năng
                        # tỉ lệ đã học không còn đúng (người dùng đổi tốc độ con trỏ, hoặc lần học rơi vào nhịp bị rớt lệnh).
                        if verbose: print("     (tỉ lệ đã học %.2f không còn khớp → quên, đo lại)" % self.gain)
                        self.gain, self.gain_sure, misses = None, None, 0
                guess = min(vis, key=lambda c: _dist(c, expect)) if vis else None
                sources, before = list(now), list(now)
                if guess is not None and max(abs(px - guess[0]), abs(py - guess[1])) > 1.5 * D:
                    move = plan(guess, 1)
                else:
                    move = nudge(guess or expect)
                g = self.gain or 1.0
                expect = ((guess or expect)[0] + move[0] * g, (guess or expect)[1] + move[1] * g)
                continue

            streak += 1
            misses = 0
            if away_pending:
                # Con trỏ ĐÃ đi theo lệnh «nhích đi» ra khỏi đích. Nhìn thêm MỘT lần KHÔNG ra lệnh gì, ngay tại chỗ trống này:
                # con trỏ thật đứng yên tuyệt đối (đo thật: lệch 0 px), vật tự chuyển động (hoạt ảnh, vật nhảy) thì đã đi chỗ khác.
                # Làm ở đây chứ không ở đích: iOS làm con trỏ mờ dần / chuyển sang vùng sáng của icon khi nó đứng yên trên icon
                # (đo thật: để con trỏ «đứng chờ» trên icon đích → bộ dò mất dấu, bấm chậm 10–25 s hoặc hỏng).
                time.sleep(self.TRACK_SETTLE)
                still_img = grab()
                if still_img.shape != ref.shape:
                    return False
                now2 = [c[:2] for c in self.e.pointer_blobs(ref, still_img, corner)]
                if not any(_dist(c, p) <= self.STILL for c in now2):
                    if verbose: print("     (vệt đã dời đi dù không có lệnh nào → không phải con trỏ, đo lại)")
                    streak, pos, away_ok, away_pending = 0, None, False, False
                    self.gain, self.gain_sure = gain0
                    sources, before = list(now2), list(now2)
                    move = nudge(p)
                    expect = (p[0] + move[0] * (self.gain or 1.0), p[1] + move[1] * (self.gain or 1.0))
                    continue
                away_ok, away_pending = True, False
            if math.hypot(move[0], move[1]) >= 40:
                # Học tỉ lệ pixel/đơn vị của máy này từ nhịp vừa xác nhận: lần đầu lấy thẳng số đo, các lần sau làm mượt.
                # Biết tỉ lệ thì nhịp sau đi vừa tới đích (không vọt quá ra mép màn hình) và phép kiểm «đi theo lệnh» chặt hơn.
                seen = _dist(p, pair[0]) / math.hypot(move[0], move[1])
                if self.GAIN_RANGE[0] <= seen <= self.GAIN_RANGE[1]:       # ngoài khoảng của iPhone thật → không tin, không học
                    if self.gain is None:
                        self.gain = seen
                    else:
                        agree = abs(seen - self.gain) <= 0.25 * self.gain      # khớp với lần đo trước → mới coi là «chắc»
                        self.gain = 0.5 * self.gain + 0.5 * seen
                        self.gain_sure = self.gain if agree else None
            pos = p
            ex, ey = px - p[0], py - p[1]
            if abs(ex) <= tol and abs(ey) <= tol:
                if not away_ok:
                    # PHÉP THỬ «ĐI – VỀ» TẠI ĐÍCH, bắt buộc trước mỗi cú bấm: nhích ra chỗ trống (hướng ngẫu nhiên), thấy con
                    # trỏ đi theo; rồi quay lại đích bằng một nhịp ngắn, thấy nó quay lại. Một vật chỉ bay tới rồi đỗ ở đích
                    # (verify vòng 8) không làm theo được lệnh «đi ra» — chuyển động ĐỀU là thứ duy nhất nó không bắt chước nổi.
                    sources, before = [p], list(now)
                    away_ok, away_pending = False, True
                    move = nudge(p)
                    if verbose: print("     (tới đích → phép thử đi–về: nhích %s)" % (move,))
                    expect = (p[0] + move[0] * self.gain, p[1] + move[1] * self.gain) if self.gain else (p[0] + move[0], p[1] + move[1])
                    continue
                if verify is not None and not verify(fr.raw(clear if clear is not None else img)):      # bên gọi kiểm trên ảnh như ảnh chụp
                    if verbose: print("  (tới nơi nhưng thứ cần bấm không còn ở đó) -> KHÔNG click")
                    return False
                if verbose: print("     (đã qua phép thử đi–về (đi → đứng yên → về) → %s)" % ("bấm" if click else "tới nơi, không bấm"))
                if click: self.h.click()
                return True
            if _dist(p, (px, py)) > 1.5 * D:
                clear = img                # con trỏ còn xa đích → ảnh này thấy rõ thứ cần bấm
            sources, before = [p], list(now)
            move = plan(p, 4)              # lúc còn xa thì di vài nhịp liền rồi mới chụp; càng gần càng đo từng nhịp
            g = self.gain or 1.0
            expect = (p[0] + move[0] * g, p[1] + move[1] * g)
        if verbose: print(f"  (hết vòng, con trỏ cuối={pos}) -> KHÔNG click")
        return False

    # Kéo một mạch dài thì con trỏ đi được ÍT pixel hơn số đơn vị gửi xuống, và hụt THẤT THƯỜNG (board gửi dày
    # nên rớt gói; đo trên iPhone 8: 560 đơn vị ≈ 340–450px). Vì vậy vuốt là thao tác ƯỚC LƯỢNG, không chính xác
    # từng pixel: cuộn một đoạn rồi đọc lại màn hình xem tới đâu, đừng tin vào quãng đã yêu cầu.
    SWIPE_GAIN = 1.28

    def hold_at(self, px: int, py: int, seconds: float = 1.0, verify=None) -> bool:
        """BẤM GIỮ tại pixel (px,py) trong `seconds` giây rồi nhả (menu ngữ cảnh, chế độ sửa màn hình chính…).
        Con trỏ không tới nơi thì không nhấn, trả False."""
        if not self.tap_at(px, py, click=False, verify=verify):
            return False
        return self.h.hold(seconds)

    def swipe(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """VUỐT từ pixel (x1,y1) về phía (x2,y2): đưa con trỏ tới điểm đầu → nhấn-kéo-nhả liền một mạch.
        Quãng kéo thực tế chỉ xấp xỉ (xem SWIPE_GAIN). Con trỏ không tới được điểm đầu thì không làm gì."""
        if not self.tap_at(x1, y1, click=False):
            return False
        dx, dy = self._fr.vec(x2 - x1, y2 - y1)          # hướng kéo trên ảnh chụp → hướng di của chuột (máy xoay ngang thì khác nhau)
        return self.h.swipe(round(dx * self.SWIPE_GAIN), round(dy * self.SWIPE_GAIN))

    def flick(self, direction: str, at: float | None = None) -> bool:
        """Vuốt cả trang theo hướng ngón tay: "left" | "right" (lật trang) | "up" | "down" (cuộn).
        Lật trang phải kéo qua NỬA màn hình mới ăn, mà quãng kéo hay bị hụt → kéo dài gần hết bề ngang
        (con trỏ chạm mép thì tự dừng): đo trên máy thật 5/5 lần mỗi hướng. `at` = vị trí trục còn lại
        theo tỉ lệ màn hình (mặc định giữa màn hình); tránh chỗ có nút AssistiveTouch."""
        img = self.e.screenshot()
        H, W = img.shape[:2]
        if direction in ("left", "right"):
            y = int(H * (0.52 if at is None else at))
            x, dx = (int(W * 0.93), -int(W * 1.2)) if direction == "left" else (int(W * 0.07), int(W * 1.2))
            return self.tap_at(x, y, click=False) and self.h.swipe(*self._fr.vec(dx, 0))
        if direction in ("up", "down"):
            x = int(W * (0.5 if at is None else at))
            y, dy = (int(H * 0.75), -int(H * 0.32)) if direction == "up" else (int(H * 0.32), int(H * 0.5))
            return self.tap_at(x, y, click=False) and self.h.swipe(*self._fr.vec(0, dy))
        raise ValueError("hướng vuốt lạ: %s" % direction)

    # Chuỗi thử bàn phím + thứ nó biến thành khi đi qua bộ gõ tiếng Việt (đã bỏ dấu, bỏ khoảng trắng).
    # Bộ gõ GỘP từng cặp phím thành một chữ có dấu (Telex: «dd»→«đ», «aa»→«â»; VNI: «a6»→«â», «d9»→«đ»)
    # nên chuỗi gõ vào không còn nguyên văn; bàn phím tiếng Anh thì ra y như gõ.
    # (Chuỗi VNI tránh các số dễ bị OCR đọc nhầm thành chữ: 1/l, 5/s.)
    KB_PROBES = (("Telex", "dd aa ee oo dd aa ee oo", "daeodaeo"), ("VNI", "a6 e6 o7 u7 d9 a8 e6 o7", "aeoudaeo"))
    _OCR_FOLD = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l"})      # OCR hay lẫn o/0, l/1/i

    @classmethod
    def _run(cls, needle: str, text: str) -> int:
        """Độ dài đoạn LIỀN dài nhất của `needle` xuất hiện trong `text` (đã bỏ dấu, bỏ khoảng trắng,
        coi các ký tự OCR hay lẫn là một)."""
        sig = "".join(needle.lower().split()).translate(cls._OCR_FOLD)
        hay = "".join(norm_text(text).split()).translate(cls._OCR_FOLD)
        best, prev = 0, [0] * (len(hay) + 1)
        for ch in sig:
            cur = [0] * (len(hay) + 1)
            for j, hc in enumerate(hay, 1):
                if ch == hc:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best = cur[j]
            prev = cur
        return best

    @classmethod
    def keyboard_state(cls, probe: str, mangled: str, seen) -> str:
        """Đọc các chữ trên màn hình (`seen`: chuỗi hoặc danh sách chuỗi OCR) sau khi gõ `probe`:
          "ok"         thấy một đoạn LIỀN ≥ 60% chuỗi thử → bàn phím gõ NGUYÊN VĂN;
          "ime"        thấy chính cái chuỗi mà bộ gõ tiếng Việt tạo ra (`mangled`) → chắc chắn đang Telex/VNI;
          "unreadable" không đọc ra cái nào → KHÔNG kết luận gì (OCR hụt, Spotlight chưa mở…).
        Không đòi khớp cả chuỗi vì OCR hay nhầm một hai chữ và iPhone hiện chữ chậm hơn lúc gõ."""
        texts = [seen] if isinstance(seen, str) else list(seen or [])
        sig = "".join(probe.split())
        if any(cls._run(probe, t) >= max(6, int(len(sig) * 0.6)) for t in texts):
            return "ok"
        if any(cls._run(mangled, t) >= max(5, len(mangled) - 2) for t in texts):
            return "ime"
        return "unreadable"

    @classmethod
    def keyboard_ok(cls, probe: str, seen) -> bool:
        mangled = next((m for _, p, m in cls.KB_PROBES if p == probe), "\0")
        return cls.keyboard_state(probe, mangled, seen) == "ok"

    def _typed_texts(self, img):
        """Chữ đọc được ở những nơi Spotlight hiện lại chuỗi vừa gõ: ô tìm kiếm (cắt sát dòng chữ, đọc kiểu
        một-dòng), vùng gợi ý phía trên (dòng đầu lặp lại chuỗi gõ, nền sạch nên OCR đọc tốt hơn ô tìm
        kiếm vốn nằm trên nền mờ) và cả màn hình."""
        H, W = img.shape[:2]
        k = 1.5 if W > 900 else 1.0                                              # máy ×3 điểm ảnh
        field = (int(100 * k), H - int(78 * k), W - int(104 * k), H - int(22 * k))
        top = (0, int(110 * k), W, int(360 * k))
        out = []
        for kw in ({"region": field, "scale": 3, "lang": "eng", "psm": 7}, {"region": field, "scale": 3, "psm": 7},
                   {"region": top}, {}):
            try:
                out.append(self.e.read_text(img, **kw))
            except Exception:
                out.append("")
        return out

    def ensure_english(self, tries: int = 3, verbose=False):
        """Đảm bảo bàn phím cứng gõ NGUYÊN VĂN (tiếng Anh, không Telex/VNI). Bộ gõ tiếng Việt sẽ biến
        đổi tài khoản, mật khẩu, tên app gõ vào («afaf» → «âf», «a6» → «â»). Dùng ô Spotlight làm ô thử:
        gõ chuỗi thử, đọc lại trên màn hình.
          * đọc được nguyên văn cả hai chuỗi thử → đạt;
          * THẤY RÕ chữ đã bị bộ gõ biến đổi → Ctrl+Space đổi bộ gõ rồi thử lại;
          * không đọc được gì → KHÔNG đổi bộ gõ (đổi mò có thể làm máy đang đúng thành sai), chỉ thử lại.
        Trả (True/False, chữ đọc được lần cuối); lý do không đạt ở `self.kb_reason`: "ime" | "unreadable"."""
        self.kb_reason = ""
        self.h.do("combo gui h"); time.sleep(1.0)        # về home
        self.h.do("combo gui space"); time.sleep(1.5)    # mở Spotlight
        state, seen = "unreadable", ""
        for i in range(tries):
            for kind, probe, mangled in self.KB_PROBES:
                self.h.do("combo cmd a"); time.sleep(0.5); self.h.key("back"); time.sleep(0.8)   # xoá ô
                self.h.type(probe); time.sleep(1.6)       # iPhone hiện chữ chậm hơn lúc board báo gõ xong
                for look in range(3):                     # chưa đọc ra thì nhìn lại (chữ còn đang hiện dần)
                    texts = self._typed_texts(self.e.screenshot())
                    seen = next((t for t in texts if t), "")
                    state = self.keyboard_state(probe, mangled, texts)
                    if verbose:
                        print(f"  [{i}] thử {kind}: gõ {probe!r} → đọc được {[t[:44] for t in texts]!r} → {state}")
                    if state != "unreadable":
                        break
                    time.sleep(1.0)
                if state != "ok":
                    break
            self.h.do("combo cmd a"); time.sleep(0.5); self.h.key("back"); time.sleep(0.4)   # xoá lại
            if state == "ok":
                break
            if state == "ime":                            # chắc chắn đang ở bộ gõ tiếng Việt → đổi rồi thử lại
                self.h.do("combo ctrl space"); time.sleep(1.2)
            else:                                         # không đọc được: mở lại Spotlight cho chắc, KHÔNG đổi bộ gõ
                self.h.do("combo gui h"); time.sleep(1.0)
                self.h.do("combo gui space"); time.sleep(1.5)
        self.h.do("combo gui h")
        self.kb_reason = "" if state == "ok" else state
        return state == "ok", seen

    LOOK_SETTLE = 0.9     # chờ màn hình đứng yên trước khi «nhìn một lần» (ảnh chụp giờ tức thì, xem apimode.LOOK_SETTLE)

    def tap_text(self, needle: str, verbose=False):
        """OCR tìm nhãn chữ rồi click vào giữa nó. Trả True nếu thấy & tap."""
        time.sleep(self.LOOK_SETTLE)
        img = self.e.screenshot()
        pos = self.e.find_text(needle, img)
        if not pos:
            if verbose: print(f"  không thấy chữ '{needle}'")
            return False
        if verbose: print(f"  '{needle}' ở {pos} -> tap")
        def still(shot):                       # chữ còn ở chỗ cũ ngay trước khi bấm?
            q = self.e.find_text(needle, shot)
            return bool(q) and abs(q[0] - pos[0]) <= 45 and abs(q[1] - pos[1]) <= 45
        return self.tap_at(pos[0], pos[1], verify=still)   # không tới nơi / màn hình đã đổi -> không bấm, False

    def home_screen(self):
        """Về màn hình chính (Cmd+H)."""
        self.h.do("combo gui h"); time.sleep(1.2)

    def shot(self, path: str):
        return self.e.save(path)

    def close(self):
        self.h.close()


if __name__ == "__main__":
    # Dùng: python app/nav.py <udid> <ax> <ay> [out.png] [cổng]   (cổng: /dev/cu.usbserial-… trên Mac, COM3… trên Windows; bỏ trống = tự dò)
    udid = sys.argv[1]
    ax = int(sys.argv[2]); ay = int(sys.argv[3])
    out = sys.argv[4] if len(sys.argv) > 4 else "shots/nav.png"
    n = Nav(sys.argv[5] if len(sys.argv) > 5 else None, udid)        # None → Hands tự dò cổng board (hands.find_port)
    print(f"tap_move({ax},{ay}) ->", n.tap_move(ax, ay))
    time.sleep(0.5)
    n.shot(out)
    n.close()
    print("chụp", out)
