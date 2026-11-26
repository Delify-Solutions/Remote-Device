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
import subprocess, tempfile, os, sys, time, unicodedata
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
    OCR hay đọc sai dấu ("Đăng nhập" → "Dang nhap"/"Đăng nhâp") nên so khớp không dấu bền hơn."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
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

    def screenshot(self):
        """Trả về ảnh numpy BGR (OpenCV)."""
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
        (iPhone 8/SE: ×2 → 38px; dòng Plus / X trở lên: ×3 → 57px)."""
        return 19 * (3 if img.shape[1] > 900 else 2)

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

    @staticmethod
    def _pointer_inside(ref, img, raw, lab, i, box, D, disc):
        """Con trỏ nằm LẪN trong một vệt thay đổi TO hơn nó. Hai kiểu đã gặp trên iPhone thật:

          • NÚT ĐƯỢC PHỦ SÁNG — con trỏ đi vào nút của hộp thoại hệ thống thì iOS tô sẫm CẢ nút. Chấm tròn vẫn
            được vẽ bên trong, nhưng cả nút đều «đổi» so với ảnh nền nên không còn là một vệt riêng. Nút đổi
            ĐỀU một độ lệch màu (đo trên iPhone 8: 271×88px, lệch ≈ −19 mức xám, chỉ riêng chỗ con trỏ là khác)
            → trừ độ lệch chung đó đi, phần còn lại (đổi KHÁC hẳn) chính là con trỏ. Chữ trên nút không đổi
            màu nên tự rơi ra.
          • DÍNH VÀO NÉT MẢNH đang chuyển động (kim của icon Đồng hồ) → bào bỏ nét mảnh, còn lại chấm tròn.

        Chỉ xét vệt cỡ một cái nút (≤ 60 lần diện tích con trỏ): cả màn hình đổi (chuyển trang, hộp thoại mới
        bật lên) thì KHÔNG đoán — ở đó có vô số mảnh cỡ con trỏ. Trả các mảnh [(x, y, w, h, diện_tích)] theo toạ
        độ trong ô `box`; bên gọi lọc lại theo đúng cỡ con trỏ."""
        x, y, w, h, area = box
        comp = lab[y:y + h, x:x + w] == i
        k = int(0.45 * D) | 1
        if area >= 2 * disc:
            if area > 60 * disc or area < 0.75 * w * h:
                return []                                   # không phải một khối đặc cỡ cái nút
            core = comp & (raw[y:y + h, x:x + w] > 0)
            d = img[y:y + h, x:x + w].astype(np.int16) - ref[y:y + h, x:x + w].astype(np.int16)
            resid = np.abs(d - np.median(d[core], axis=0)).max(axis=2)
            # «Đổi đều» = cả vùng đổi cùng một độ lệch, TRỪ tối đa một mảnh cỡ con trỏ. Tính theo diện tích tuyệt
            # đối chứ không theo tỉ lệ: nút nhỏ (60×60) thì riêng con trỏ đã chiếm 1/3; vùng lớn thì 20% đã là
            # cả chục «con trỏ» nội dung lạ.
            if int((resid[core] > 10).sum()) > 2.2 * disc or int((resid[core] <= 10).sum()) < disc:
                return []                                   # không «đổi đều» → không phải nút được phủ sáng
            m = ((resid > 14) & core).astype(np.uint8) * 255
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
        if not psm:
            try:
                seen = ocr.text(img)                 # trên ảnh gốc (Vision tự lo cỡ chữ)
            except Exception:
                seen = ""
        if pytesseract is None:
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
        trắng (OCR hay tách/gộp chữ). Nhiều chỗ khớp thì lấy chỗ đầu tiên theo thứ tự đọc.
        Tìm bằng Apple Vision trước (đọc được chữ trên nền game); không thấy thì tìm bằng tesseract như trước."""
        if img is None:
            img = self.screenshot()
        try:
            hit = ocr.find(img, needle)
        except Exception:
            hit = None
        if hit:
            return (int(hit[0]), int(hit[1]))
        if pytesseract is None:
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
            return (int((x0 + x1) / 2 / scale), int((y0 + y1) / 2 / scale))
        return None

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
