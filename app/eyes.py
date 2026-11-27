#!/usr/bin/env python3
"""
eyes.py — "con mắt": chụp màn iPhone qua USB + nhận diện trên ảnh.

    from eyes import Eyes
    e = Eyes(udid)
    img = e.screenshot()                 # numpy BGR
    x,y,score = e.find("button.png")     # tìm mẫu, trả tâm + độ khớp
    e.save("shots/now.png")              # chụp ra file

Chụp dùng pymobiledevice3 (dvt screenshot) — chạy cả trên máy bypass, iOS 16.
Mặc định chụp qua MỘT kết nối giữ mở (fastshot.py, ~0,33s/ảnh); kết nối hỏng thì quay về cách gọi
lệnh cho từng ảnh (~1,3s) và tạm nghỉ dùng đường nhanh FAST_COOLDOWN giây (lần hỏng đó có thể tốn thêm
vài giây chờ đường nhanh hết giờ).
"""
from __future__ import annotations
import contextlib, subprocess, tempfile, os, sys, threading, time, unicodedata
import numpy as np
import cv2
import fastshot
import ocr
try:
    import pytesseract
except ImportError:
    pytesseract = None


def norm_text(s) -> str:
    """Chuẩn hoá để so khớp chữ OCR: chữ thường, BỎ DẤU tiếng Việt (đ→d), gộp khoảng trắng.
    OCR hay đọc sai dấu ("Đăng nhập" → "Dang nhap"/"Đăng nhâp") nên so khớp không dấu bền hơn. Chữ Kirin / Hy Lạp trông y hệt chữ Latin
    (Vision có lúc đọc «OK» thành «ОK» với «О» Kirin) được đổi về Latin."""
    s = unicodedata.normalize("NFD", str(s or "").lower().translate(ocr.CONFUSABLE))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(s.replace("đ", "d").split())


def text_has(haystack_norm: str, needle) -> bool:
    """`needle` (chưa chuẩn hoá) có nằm trong `haystack_norm` (đã norm_text) không.
    Thử cả dạng bỏ hết khoảng trắng vì OCR hay tách/gộp chữ ("1 050" ↔ "1050")."""
    n = norm_text(needle)
    if not n:
        return False
    return n in haystack_norm or n.replace(" ", "") in haystack_norm.replace(" ", "")

VENV_PMD = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "pymobiledevice3")


IMAGE_SIDE_MIN, IMAGE_SIDE_MAX = 8, 600      # cạnh nhỏ nhất / lớn nhất (điểm ảnh) của ảnh mẫu trong bước «bấm vào vùng ảnh»


def decode_image(b64):
    """Ảnh mẫu của bước «bấm vào vùng ảnh» (PNG / JPEG mã hoá base64, có hay không tiền tố `data:…,`) → ảnh BGR.
    Không đọc được, sai cỡ, hoặc gần như một màu (không có gì để nhận dạng) → ValueError kèm lý do."""
    import base64, binascii
    s = str(b64 or "").strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("ảnh mẫu không đọc được")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    if img is None:
        raise ValueError("ảnh mẫu không đọc được")
    h, w = img.shape[:2]
    if min(h, w) < IMAGE_SIDE_MIN or max(h, w) > IMAGE_SIDE_MAX:
        raise ValueError("ảnh mẫu %d×%d nằm ngoài cỡ cho phép (mỗi cạnh %d…%d điểm ảnh)" % (w, h, IMAGE_SIDE_MIN, IMAGE_SIDE_MAX))
    if float(img.reshape(-1, 3).std(axis=0).max()) < 4.0:      # độ lệch trong TỪNG kênh màu (mảng một màu bất kỳ đều ~0)
        raise ValueError("ảnh mẫu gần như một màu — chọn vùng có hình hoặc chữ")
    return img


IMAGE_PEAKS_MAX = 60      # số chỗ giống nhau nhiều nhất còn phân xử được; quá số này (hoa văn lặp kín màn hình) → không chọn bừa, coi như không thấy
IMAGE_TOO_MANY = 2.0      # «điểm» trả về khi quá nhiều chỗ giống nhau (điểm thật không bao giờ vượt 1) → bên gọi báo đúng lý do


def locate_image(img, tmpl, min_score: float = 0.9, near=None):
    """Tìm ảnh mẫu `tmpl` trong ảnh `img` (cùng BGR, cùng tỉ lệ). Trả ((cx, cy) | None, điểm giống cao nhất 0…1).

    Điểm giống = độ khớp HÌNH DẠNG (so khớp mẫu chuẩn hoá) × (1 − chênh lệch MÀU / ĐỘ SÁNG trung bình). Chỉ khớp hình dạng thì một
    nút đang bị phủ mờ sau hộp thoại, hay cùng hình nhưng khác màu (nút xám «chưa bấm được»), vẫn ra điểm ~1 — nhân thêm phần màu để
    những chỗ đó KHÔNG còn «giống». Đo trên iPhone 8 (nút menu ở màn tiêu đề eFootball): đúng hình 1,00 trên cả hai máy; nén ảnh / làm
    mờ nhẹ 0,95–0,97; phủ mờ 70% 0,87; mất màu 0,75; ảnh thu còn 97% 0,79; chỗ giống nhì trên cùng màn hình 0,33.

    Nhiều chỗ cùng đạt `min_score` (dãy nút giống hệt nhau): xét HẾT các chỗ đó — có `near` thì lấy chỗ GẦN `near` nhất, không thì lấy
    chỗ giống nhất; hình còn nằm đúng chỗ `near` thì lấy luôn chỗ đó. Quá IMAGE_PEAKS_MAX chỗ (hoa văn lặp kín màn hình) → không phân xử
    được → trả (None, IMAGE_TOO_MANY), không chọn bừa.
    Ảnh mẫu lớn hơn màn hình (máy khác độ phân giải / đang xoay chiều khác), ảnh không phải 3 kênh màu 8 bit → không thấy, không ném lỗi."""
    def bgr8(a):
        return getattr(a, "ndim", 0) == 3 and a.shape[2] == 3 and a.dtype == np.uint8
    if img is None or tmpl is None or not bgr8(img) or not bgr8(tmpl):
        return None, 0.0
    th, tw = tmpl.shape[:2]
    ih, iw = img.shape[:2]
    if th > ih or tw > iw or th < 2 or tw < 2:
        return None, 0.0
    try:
        res = np.nan_to_num(cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED), nan=-1.0, posinf=-1.0, neginf=-1.0)
    except cv2.error:
        return None, 0.0
    t16 = tmpl.astype(np.int16)

    def score_at(x, y):
        return float(res[y, x]) * (1.0 - float(np.mean(np.abs(img[y:y + th, x:x + tw].astype(np.int16) - t16))) / 255.0)
    if near is not None:
        # Hình còn nằm ĐÚNG chỗ nó được cắt ra → lấy luôn chỗ đó. (Tìm đỉnh rồi xoá vùng quanh đỉnh sẽ nuốt mất đỉnh thật khi ảnh mẫu trùm
        # từ hai chu kỳ của một nội dung lặp — vd khoanh trùm hai nút giống hệt trong một dãy — và trả về chỗ lệch một chu kỳ.)
        x0, y0 = int(near[0]) - tw // 2, int(near[1]) - th // 2
        if 0 <= y0 < res.shape[0] and 0 <= x0 < res.shape[1] and res[y0, x0] >= min_score:
            s0 = score_at(x0, y0)
            if s0 >= min_score:
                return (x0 + tw // 2, y0 + th // 2), s0
    found, best = [], 0.0
    for n in range(IMAGE_PEAKS_MAX + 1):
        _, ncc, _, (x, y) = cv2.minMaxLoc(res)
        if ncc <= 0:
            break
        if n == IMAGE_PEAKS_MAX and ncc >= min_score:       # vẫn còn chỗ đạt ngưỡng sau ngần ấy chỗ → không phân xử
            return None, IMAGE_TOO_MANY
        score = score_at(x, y)
        best = max(best, score)
        if ncc < min_score:                              # các đỉnh sau chỉ thấp hơn nữa
            break
        if score >= min_score:
            found.append((x + tw // 2, y + th // 2, score))
        res[max(0, y - th // 2):y + th // 2 + 1, max(0, x - tw // 2):x + tw // 2 + 1] = -1.0      # xoá đỉnh này để tìm đỉnh kế
    if not found:
        return None, best
    if near is not None and len(found) > 1:
        found.sort(key=lambda p: (p[0] - near[0]) ** 2 + (p[1] - near[1]) ** 2)
    else:
        found.sort(key=lambda p: -p[2])
    return (int(found[0][0]), int(found[0][1])), best


class Eyes:
    def __init__(self, udid: str, pmd: str | None = None):
        self.udid = udid
        self.pmd = pmd or (VENV_PMD if os.path.exists(VENV_PMD) else "pymobiledevice3")

    def _grab_png(self, path: str) -> bool:
        env = dict(os.environ, PYTHONWARNINGS="ignore")
        r = subprocess.run(
            [self.pmd, "developer", "dvt", "screenshot", path, "--udid", self.udid],
            capture_output=True, env=env,
        )
        return r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0

    FAST = True       # False = luôn gọi lệnh cho từng ảnh (cách cũ) — để so sánh / khi nghi đường nhanh có vấn đề
    FAST_COOLDOWN = 30.0
    _fast_off = {}    # udid -> thời điểm được thử lại đường nhanh (sau một lần nó hỏng)

    def _grab_fast(self):
        """Chụp qua kết nối giữ mở. Trả ảnh, hoặc None nếu không được (bên gọi quay về cách cũ)."""
        if time.time() < Eyes._fast_off.get(self.udid, 0):
            return None
        for _ in range(2):                  # kết nối cũ có thể vừa chết (rút cáp, máy vừa khoá) → mở lại thử thêm 1 lần
            try:
                img = cv2.imdecode(np.frombuffer(fastshot.grab(self.udid), np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            except Exception:
                pass
        Eyes._fast_off[self.udid] = time.time() + self.FAST_COOLDOWN
        return None

    # ---- ẢNH THẲNG: mọi ảnh trả ra đều cùng chiều với GIAO DIỆN ----
    # Đo trên iPhone 8 (máy 01): sau khi mở trang đăng nhập web từ game đang ngang, máy chụp ra khung DỌC 750×1334 với nội dung nằm NGHIÊNG,
    # kéo dài cả khi mở lại game. Bước ghi theo toạ độ / vùng ảnh / hướng lướt / «trong cùng ô» đều được soạn trên ảnh THẲNG → mọi ảnh trả ra
    # được quay thẳng theo chữ trên màn hình (ocr.upright_turn). Con trỏ không cần biết chuyện này: Nav tự dò hướng của ảnh so với hệ trục
    # chuột theo góc con trỏ hiện ra (như với game xoay ngang — xem nav.Frame).
    # Cách quay được NHỚ theo từng máy và chỉ xét lại khi: cỡ ảnh chụp đổi; màn hình đổi nhiều (≥ TURN_CHANGE) sau ít nhất TURN_GAP giây;
    # lần xét trước chưa chắc (ít chữ); hoặc đã TURN_AGE giây. Trong lúc đang đưa con trỏ (steady) KHÔNG xét lại — đổi chiều giữa chừng
    # là toạ độ đích sai.
    UPRIGHT = True
    TURN_GAP = 2.0
    TURN_AGE = 30.0
    TURN_CHANGE = 0.25
    _turns = {}                   # udid -> {"k": số lần quay 90° theo chiều kim đồng hồ, "shape", "t", "thumb", "sure"}
    _steady = {}                  # udid -> số khối steady đang mở
    _turn_lock = threading.Lock()

    @staticmethod
    def rotate(img, k: int):
        """Quay ảnh k lần 90° theo chiều kim đồng hồ."""
        k %= 4
        return img if not k else cv2.rotate(img, (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)[k - 1])

    @staticmethod
    def _thumb(img):
        g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA)

    @contextlib.contextmanager
    def steady(self):
        """Giữ NGUYÊN cách quay ảnh của máy này trong khối lệnh (đang đưa con trỏ tới đích)."""
        key = getattr(self, "udid", None)
        with Eyes._turn_lock:
            Eyes._steady[key] = Eyes._steady.get(key, 0) + 1
        try:
            yield
        finally:
            with Eyes._turn_lock:
                Eyes._steady[key] = max(0, Eyes._steady.get(key, 1) - 1)

    def turn(self) -> int:
        """Cách quay đang dùng cho ảnh của máy này (0 = ảnh chụp đã thẳng)."""
        st = Eyes._turns.get(self.udid)
        return st["k"] if st else 0

    def upright(self, raw):
        """Ảnh chụp `raw` → ảnh THẲNG (xem chú thích ở trên)."""
        now = time.time()
        thumb = self._thumb(raw)
        with Eyes._turn_lock:
            st = Eyes._turns.get(self.udid)
            steady = Eyes._steady.get(self.udid, 0) > 0
        same = st is not None and st["shape"] == raw.shape
        if same:
            age = now - st["t"]
            due = age >= self.TURN_GAP and (age >= self.TURN_AGE or not st["sure"]
                                            or float(np.mean(cv2.absdiff(thumb, st["thumb"]) > 20)) >= self.TURN_CHANGE)
            if steady or not due:
                return self.rotate(raw, st["k"])
        k0 = st["k"] if same else 0
        try:
            k = ocr.upright_turn(self.rotate(raw, k0))
        except Exception:
            k = None
        sure = k is not None
        k = k0 if k is None else (k0 + k) % 4          # chưa biết → giữ cách quay cũ (cỡ ảnh đổi thì: không quay)
        with Eyes._turn_lock:
            cur = Eyes._turns.get(self.udid)
            if Eyes._steady.get(self.udid, 0) > 0 and cur is not None and cur["shape"] == raw.shape:
                # một luồng khác của CÙNG máy vừa bắt đầu đưa con trỏ trong lúc ta đang xét: không đổi cách quay giữa chừng của nó
                return self.rotate(raw, cur["k"])
            Eyes._turns[self.udid] = {"k": k, "shape": raw.shape, "t": now, "thumb": thumb, "sure": sure}
        return self.rotate(raw, k)

    def screenshot(self):
        """Trả về ảnh numpy BGR (OpenCV), đã quay THẲNG theo giao diện (xem `upright`)."""
        raw = self.grab()
        return self.upright(raw) if self.UPRIGHT else raw

    def grab(self):
        """Ảnh chụp NGUYÊN như máy trả về (chưa quay thẳng)."""
        if self.FAST and fastshot.AVAILABLE:
            img = self._grab_fast()
            if img is not None:
                return img
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        try:
            if not self._grab_png(tmp):
                raise RuntimeError(f"Chụp màn thất bại (udid {self.udid})")
            img = cv2.imread(tmp)
            if img is None:
                raise RuntimeError("Không đọc được ảnh chụp")
            return img
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        img = self.screenshot()
        cv2.imwrite(path, img)
        return path

    def size(self):
        img = self.screenshot()
        h, w = img.shape[:2]
        return w, h

    def find_pointer(self, img=None, exclude=None):
        """Tìm con trỏ chuột AssistiveTouch (chấm xám đặc tròn ~R18-24px).
        Trả (cx, cy, r) hoặc None. Nên gọi NGAY sau khi di chuột (con trỏ còn sáng).
        Tự loại vùng nút AssistiveTouch (mặc định góc dưới-phải)."""
        if img is None:
            img = self.screenshot()
        H, W = img.shape[:2]
        if exclude is None:
            # vùng nút AssistiveTouch (to ~130px) hay nằm góc dưới-phải — nới rộng
            exclude = [(W - 230, H - 440, W, H)]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=200,
            param1=100, param2=22, minRadius=14, maxRadius=30,
        )
        if circles is None:
            return None

        def in_exclude(x, y):
            for (x0, y0, x1, y1) in exclude:
                if x0 <= x <= x1 and y0 <= y <= y1:
                    return True
            return False

        best = None
        for c in circles[0]:
            cx, cy, r = int(c[0]), int(c[1]), int(c[2])
            if in_exclude(cx, cy):
                continue
            # con trỏ: vùng trong tròn phải xám ĐẶC đều (ít biến thiên), bão hoà thấp
            x0, y0 = max(cx - 5, 0), max(cy - 5, 0)
            patch = img[y0:cy + 5, x0:cx + 5]
            if patch.size == 0:
                continue
            b, g, rr = patch[..., 0].mean(), patch[..., 1].mean(), patch[..., 2].mean()
            std = patch.std()
            if abs(b - g) < 18 and abs(g - rr) < 18 and 90 < g < 210 and std < 25:
                score = -abs(g - 150)      # ưu tiên xám trung tính
                if best is None or score > best[3]:
                    best = (cx, cy, r, score)
        return best[:3] if best else None

    @staticmethod
    def pointer_size(img) -> int:
        """Đường kính con trỏ AssistiveTouch trên ảnh chụp (px) = 19pt × hệ số điểm ảnh của máy
        (iPhone 8/SE: ×2 → 38px; dòng Plus / X trở lên: ×3 → 57px). Xét theo CẠNH NGẮN của ảnh để ảnh chụp lúc máy xoay
        ngang (iPhone 8: 1334×750) không bị coi nhầm là máy ×3."""
        return 19 * (3 if min(img.shape[0], img.shape[1]) > 900 else 2)

    @staticmethod
    def _diff_max(a, b):
        """Độ lệch LỚN NHẤT trong ba kênh màu tại từng điểm ảnh (= absdiff(a,b).max(axis=2)) — làm bằng cv2.max trên
        các kênh tách sẵn: nhanh gấp ~10 lần so với numpy.max(axis=2) trên ảnh 750×1334×3 (mỗi lần nhìn gọi 2 lần)."""
        b_, g_, r_ = cv2.split(cv2.absdiff(a, b))
        return cv2.max(cv2.max(b_, g_), r_)

    @staticmethod
    def _changed(ref, img):
        """Những điểm ảnh KHÁC nhau giữa hai ảnh cùng cỡ: (mask thô, mask đã lấp các khe hẹp)."""
        raw = cv2.threshold(Eyes._diff_max(ref, img), 14, 255, cv2.THRESH_BINARY)[1]
        return raw, cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

    @staticmethod
    def changed_fraction(a, b) -> float:
        """Tỉ lệ điểm ảnh KHÁC nhau giữa hai ảnh (0…1). Khác cỡ / thiếu ảnh → 1.0 (coi như khác hẳn)."""
        if a is None or b is None or a.shape != b.shape:
            return 1.0
        return float(cv2.countNonZero(cv2.threshold(Eyes._diff_max(a, b), 14, 255, cv2.THRESH_BINARY)[1]) / (a.shape[0] * a.shape[1]))

    def pointer_blobs(self, ref, img, ignore=()):
        """Định vị con trỏ bằng cách SO `img` với `ref` — một ảnh cùng màn hình chụp lúc con trỏ
        KHÔNG nằm ở chỗ này (vd đang ghim ở góc). Con trỏ lộ ra thành một vệt thay đổi tròn đúng cỡ,
        bất kể nó đang đè lên thứ gì (chữ, icon, nút màu) — khác với find_pointer() chỉ nhận ra
        chấm xám trên nền phẳng. Con trỏ nằm LẪN trong một vệt thay đổi to hơn (nút đang được phủ sáng,
        kim đồng hồ đang chạy) cũng được tách ra — xem _pointer_inside().
        Trả danh sách [(cx, cy, diện_tích)] các vệt giống con trỏ;
        `ignore` = các ô (x0,y0,x1,y1) bỏ qua (vd chỗ con trỏ nằm trong ảnh `ref`)."""
        if ref is None or img is None or ref.shape != img.shape:
            return []
        D = self.pointer_size(img)
        disc = 3.1416 * (D / 2.0) ** 2
        raw, mask = self._changed(ref, img)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        out = []

        def take(x, y, w, h, area) -> bool:
            if not (0.6 * D <= w <= 1.5 * D and 0.6 * D <= h <= 1.5 * D):
                return False                                # đồng hồ đổi phút, chữ nhấp nháy… không đúng cỡ
            if not (0.4 * disc <= area <= 1.5 * disc):
                return False
            cx, cy = x + w / 2.0, y + h / 2.0
            if not any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in ignore):
                out.append((int(round(cx)), int(round(cy)), area))
            return True

        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if take(x, y, w, h, area):
                continue
            if w < 0.6 * D or h < 0.6 * D or area < 0.4 * disc:
                continue                                    # nhỏ hơn con trỏ → không thể chứa con trỏ
            for sx, sy, sw, sh, sa in self._pointer_inside(ref, img, raw, lab, i, (x, y, w, h, area), D, disc):
                take(x + sx, y + sy, sw, sh, sa)
        return out

    BLOCK_MAX = 140          # nút «được phủ sáng» lớn nhất còn soi tìm con trỏ bên trong, tính bằng số lần diện tích con trỏ
    BLOCK_TEXT = 0.08        # phần diện tích nút lớn được phép «đổi khác» ngoài con trỏ (chữ trên nút đổi màu theo)

    @staticmethod
    def _pointer_inside(ref, img, raw, lab, i, box, D, disc):
        """Con trỏ nằm LẪN trong một vệt thay đổi TO hơn nó. Hai kiểu đã gặp trên iPhone thật:

          • NÚT ĐƯỢC PHỦ SÁNG — con trỏ đi vào nút của hộp thoại hệ thống thì iOS tô sẫm CẢ nút. Chấm tròn vẫn
            được vẽ bên trong, nhưng cả nút đều «đổi» so với ảnh nền nên không còn là một vệt riêng. Nút đổi
            ĐỀU một độ lệch màu (đo trên iPhone 8: 271×88px, lệch ≈ −19 mức xám, chỉ riêng chỗ con trỏ là khác)
            → trừ độ lệch chung đó đi, phần còn lại (đổi KHÁC hẳn) chính là con trỏ. Chữ trên nút không đổi
            màu nên tự rơi ra.
          • NÚT CỦA TRANG WEB đổi màu khi con trỏ rê tới (:hover) — đo trên trang đăng nhập my.konami.net, iPhone 8 xoay ngang:
            nút «Login» 932×92px đổi từ đỏ sang trắng và CHỮ trên nút cũng đổi màu (trắng → xám). Nền nút vẫn đổi đều;
            phần đổi khác gồm con trỏ + các nét chữ mảnh → nét chữ bị bào bỏ ở bước dưới, còn lại chấm tròn.
          • DÍNH VÀO NÉT MẢNH đang chuyển động (kim của icon Đồng hồ) → bào bỏ nét mảnh, còn lại chấm tròn.

        Chỉ xét vệt cỡ một cái nút (≤ BLOCK_MAX lần diện tích con trỏ — vừa một nút dài hết chiều ngang màn hình): cả màn
        hình đổi (chuyển trang, hộp thoại mới bật lên) thì KHÔNG đoán — ở đó có vô số mảnh cỡ con trỏ. Trả các mảnh
        [(x, y, w, h, diện_tích)] theo toạ độ trong ô `box`; bên gọi lọc lại theo đúng cỡ con trỏ."""
        x, y, w, h, area = box
        comp = lab[y:y + h, x:x + w] == i
        k = int(0.45 * D) | 1
        if area >= 2 * disc:
            if area > Eyes.BLOCK_MAX * disc or area < 0.75 * w * h:
                return []                                   # không phải một khối đặc cỡ cái nút
            core = comp & (raw[y:y + h, x:x + w] > 0)
            d = img[y:y + h, x:x + w].astype(np.int16) - ref[y:y + h, x:x + w].astype(np.int16)
            resid = np.abs(d - np.median(d[core], axis=0)).max(axis=2)
            # «Đổi đều» = cả vùng đổi cùng một độ lệch, TRỪ một mảnh cỡ con trỏ và (với nút lớn) các nét chữ đổi màu theo nút.
            # Nút nhỏ tính theo diện tích tuyệt đối (nút 60×60 thì riêng con trỏ đã chiếm 1/3); nút lớn cho thêm phần chữ, tối
            # đa BLOCK_TEXT diện tích nút (đo thật: chữ «Login» đậm ≈ 1,5% nút). Nội dung lạ hiện ra thì đổi KHÁC ở phần lớn vùng.
            if int((resid[core] > 10).sum()) > max(2.2 * disc, Eyes.BLOCK_TEXT * area) or int((resid[core] <= 10).sum()) < disc:
                return []                                   # không «đổi đều» → không phải nút được phủ sáng
            m = ((resid > 14) & core).astype(np.uint8) * 255
            # Bỏ NÉT CHỮ đổi màu theo nút TRƯỚC khi lấp khe: nét chữ mảnh hơn con trỏ nhiều, nhưng lấp khe trước thì các chữ cái dính
            # lại thành một khối dày, dính luôn vào con trỏ đang đè lên chữ — đúng chỗ bước «bấm vào chữ» đưa con trỏ tới.
            k1 = int(0.34 * D) | 1
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k1, k1)))
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        else:
            m = comp.astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        return [tuple(int(v) for v in stats[j]) for j in range(1, n)]

    def find_assistive_button(self, img=None):
        """Tìm nút AssistiveTouch (nút tròn/vuông-bo to ~R40-75, có vòng đồng tâm, xám,
        thường nằm sát mép). Trả (cx, cy, r) hoặc None."""
        if img is None:
            img = self.screenshot()
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=120,
            param1=100, param2=30, minRadius=36, maxRadius=80,
        )
        if circles is None:
            return None
        best = None
        for c in circles[0]:
            cx, cy, r = int(c[0]), int(c[1]), int(c[2])
            # tâm xám trung tính + ưu tiên gần mép màn hình
            x0, y0 = max(cx - 6, 0), max(cy - 6, 0)
            patch = img[y0:cy + 6, x0:cx + 6]
            if patch.size == 0:
                continue
            b, g, rr = patch[..., 0].mean(), patch[..., 1].mean(), patch[..., 2].mean()
            if not (abs(b - g) < 22 and abs(g - rr) < 22 and 120 < g < 230):
                continue
            edge_dist = min(cx, W - cx, cy, H - cy)     # càng gần mép càng giống nút AT
            score = -edge_dist + r                      # ưu tiên sát mép + bán kính lớn
            if best is None or score > best[3]:
                best = (cx, cy, r, score)
        return best[:3] if best else None

    OCR_LANG = "vie+eng"      # có gói tiếng Việt (brew tesseract-lang)

    def read_text(self, img=None, region=None, scale=2, lang=None, psm=None):
        """OCR: trả chuỗi text đọc được. region=(x0,y0,x1,y1) để giới hạn vùng.
        psm=7: coi cả vùng là MỘT dòng chữ (đọc ô nhập liệu chính xác hơn hẳn) — kiểu đọc này giữ nguyên tesseract.
        Không ép psm: GHÉP chữ của Apple Vision (đọc được chữ trên nền nhiều màu của game, thứ tesseract bỏ sót hoàn toàn) với chữ của
        tesseract như trước — cái gì trước đây đọc được thì nay vẫn đọc được, chỉ đọc được THÊM."""
        seen = ""
        if img is None:
            img = self.screenshot()
        if region:
            x0, y0, x1, y1 = region
            img = img[y0:y1, x0:x1]
        broken = None
        if not psm:
            try:
                seen = ocr.text(img)                 # trên ảnh gốc (Vision tự lo cỡ chữ)
            except Exception as e:
                seen, broken = "", e
        if pytesseract is None:
            if broken is not None:                   # Vision hỏng giữa chừng mà không có tesseract đỡ: KHÔNG lặng lẽ trả «màn hình trống»
                raise RuntimeError("Bộ đọc chữ của macOS (Vision) báo lỗi (%s) và máy không cài tesseract — không đọc được màn hình" % broken)
            if seen or (not psm and ocr.available()):
                return seen
            raise RuntimeError("Thiếu pytesseract (pip install pytesseract) + tesseract (brew)")
        if scale != 1:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        config = ("--psm %d" % int(psm)) if psm else ""
        try:
            tess = pytesseract.image_to_string(gray, lang=lang or self.OCR_LANG, config=config).strip()
        except Exception:
            tess = pytesseract.image_to_string(gray, config=config).strip()
        return (seen + "\n" + tess).strip() if seen else tess

    def find_text(self, needle: str, img=None, scale=2):
        """Tìm nhãn chữ trên màn (OCR). Trả (cx, cy) = tâm của ĐÚNG CÁC CHỮ KHỚP (pixel ảnh
        gốc) hoặc None. So khớp không phân biệt hoa thường, bỏ dấu tiếng Việt, bỏ qua khoảng
        trắng (OCR hay tách/gộp chữ). Nhiều chỗ khớp: dòng mà CẢ DÒNG đúng bằng chữ cần tìm được chọn trước dòng chỉ «có
        chứa» nó; cùng loại thì lấy chỗ đầu tiên theo thứ tự đọc.
        Tìm bằng Apple Vision trước (đọc được chữ trên nền game); không thấy thì tìm bằng tesseract như trước."""
        if img is None:
            img = self.screenshot()
        broken = None
        try:
            hit = ocr.find(img, needle)
        except Exception as e:
            hit, broken = None, e
        if hit:
            return (int(hit[0]), int(hit[1]))
        if pytesseract is None:
            if broken is not None:                   # Vision hỏng giữa chừng mà không có tesseract đỡ: «không thấy chữ» ở đây là sai lý do
                raise RuntimeError("Bộ đọc chữ của macOS (Vision) báo lỗi (%s) và máy không cài tesseract — không tìm được chữ trên màn hình" % broken)
            if ocr.available():
                return None
            raise RuntimeError("Thiếu pytesseract")
        big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        try:
            data = pytesseract.image_to_data(gray, lang=self.OCR_LANG,
                                             output_type=pytesseract.Output.DICT)
        except Exception:
            data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        nd = norm_text(needle).replace(" ", "")
        if not nd:
            return None
        n = len(data["text"])
        # gộp theo dòng để khớp cụm từ
        lines = {}
        for i in range(n):
            t = (data["text"][i] or "").strip()
            if not t:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(i)
        first = None
        for key, idxs in lines.items():
            joined = ""
            owner = []                    # owner[k] = chỉ số từ chứa ký tự thứ k của `joined`
            for i in idxs:
                w = norm_text(data["text"][i]).replace(" ", "")
                joined += w
                owner.extend([i] * len(w))
            pos = joined.find(nd)
            if pos < 0:
                continue
            used = sorted(set(owner[pos:pos + len(nd)]))     # chỉ các từ thực sự khớp
            x0 = min(data["left"][i] for i in used)
            y0 = min(data["top"][i] for i in used)
            x1 = max(data["left"][i] + data["width"][i] for i in used)
            y1 = max(data["top"][i] + data["height"][i] for i in used)
            hit = (int((x0 + x1) / 2 / scale), int((y0 + y1) / 2 / scale))
            if ocr.whole_line(joined, nd):                   # cả dòng đúng bằng chữ cần tìm → chọn trước dòng chỉ «có chứa» (xem ocr.find)
                return hit
            if first is None:
                first = hit
        return first

    def relaunch(self, name: str) -> str:
        """Tắt hẳn rồi mở MỚI app `name` trên máy này qua USB (xem iosapp.relaunch). Trả bundle id; không làm được → ném lỗi kèm lý do."""
        import iosapp
        return iosapp.relaunch(self.udid, name)

    def text_lines(self, img=None) -> list:
        """Các DÒNG chữ trên ảnh: [{text, x, y, w, h}] — (x, y) là tâm dòng, pixel ảnh gốc. Apple Vision trước; không có / không đọc ra
        dòng nào thì tesseract (gộp theo dòng). Vision hỏng giữa chừng mà không có tesseract → báo lỗi (như read_text)."""
        if img is None:
            img = self.screenshot()
        broken = None
        try:
            seen = [{k: r[k] for k in ("text", "x", "y", "w", "h")} for r in ocr.lines(img)]
        except Exception as e:
            seen, broken = [], e
        if seen:
            return seen
        if pytesseract is None:
            if broken is not None:
                raise RuntimeError("Bộ đọc chữ của macOS (Vision) báo lỗi (%s) và máy không cài tesseract — không đọc được màn hình" % broken)
            return []
        scale = 2
        gray = cv2.cvtColor(cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2GRAY)
        try:
            d = pytesseract.image_to_data(gray, lang=self.OCR_LANG, output_type=pytesseract.Output.DICT)
        except Exception:
            d = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        rows = {}
        for i, t in enumerate(d["text"]):
            if (t or "").strip():
                rows.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        out = []
        for idxs in rows.values():
            idxs.sort(key=lambda i: d["left"][i])
            x0 = min(d["left"][i] for i in idxs); y0 = min(d["top"][i] for i in idxs)
            x1 = max(d["left"][i] + d["width"][i] for i in idxs); y1 = max(d["top"][i] + d["height"][i] for i in idxs)
            out.append({"text": " ".join(d["text"][i].strip() for i in idxs), "x": (x0 + x1) // (2 * scale), "y": (y0 + y1) // (2 * scale),
                        "w": (x1 - x0) // scale, "h": (y1 - y0) // scale})
        return out

    def find_image(self, tmpl, img=None, min_score: float = 0.9, near=None):
        """Tìm ảnh mẫu `tmpl` (BGR) trên màn hình — xem locate_image(). Trả ((cx, cy) | None, điểm giống cao nhất)."""
        if img is None:
            img = self.screenshot()
        return locate_image(img, tmpl, min_score, near)

    def find(self, template_path: str, img=None, threshold: float = 0.8):
        """Tìm mẫu template trong ảnh. Trả (cx, cy, score) hoặc None nếu < threshold."""
        if img is None:
            img = self.screenshot()
        tpl = cv2.imread(template_path)
        if tpl is None:
            raise RuntimeError(f"Không đọc được mẫu: {template_path}")
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        th, tw = tpl.shape[:2]
        cx, cy = maxloc[0] + tw // 2, maxloc[1] + th // 2
        if maxv < threshold:
            return None
        return (cx, cy, float(maxv))


if __name__ == "__main__":
    udid = sys.argv[1] if len(sys.argv) > 1 else None
    if not udid:
        print("Dùng: python app/eyes.py <udid> [out.png]"); sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else "shots/eyes.png"
    e = Eyes(udid)
    w, h = e.size()
    e.save(out)
    print(f"Chụp {w}x{h} -> {out}")
