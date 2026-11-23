#!/usr/bin/env python3
"""
eyes.py — "con mắt": chụp màn iPhone qua USB + nhận diện trên ảnh.

    from eyes import Eyes
    e = Eyes(udid)
    img = e.screenshot()                 # numpy BGR
    x,y,score = e.find("button.png")     # tìm mẫu, trả tâm + độ khớp
    e.save("shots/now.png")              # chụp ra file

Chụp dùng pymobiledevice3 (dvt screenshot) — chạy cả trên máy bypass, iOS 16.
"""
from __future__ import annotations
import subprocess, tempfile, os, sys
import numpy as np
import cv2
try:
    import pytesseract
except ImportError:
    pytesseract = None

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

    def screenshot(self):
        """Trả về ảnh numpy BGR (OpenCV)."""
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

    def read_text(self, img=None, region=None, scale=2, lang=None):
        """OCR: trả chuỗi text đọc được. region=(x0,y0,x1,y1) để giới hạn vùng."""
        if pytesseract is None:
            raise RuntimeError("Thiếu pytesseract (pip install pytesseract) + tesseract (brew)")
        if img is None:
            img = self.screenshot()
        if region:
            x0, y0, x1, y1 = region
            img = img[y0:y1, x0:x1]
        if scale != 1:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        try:
            return pytesseract.image_to_string(gray, lang=lang or self.OCR_LANG).strip()
        except Exception:
            return pytesseract.image_to_string(gray).strip()

    def find_text(self, needle: str, img=None, scale=2):
        """Tìm nhãn chữ trên màn (OCR). Trả (cx, cy) tâm (pixel ảnh gốc) hoặc None.
        So khớp không phân biệt hoa thường, bỏ dấu phụ đơn giản."""
        if pytesseract is None:
            raise RuntimeError("Thiếu pytesseract")
        if img is None:
            img = self.screenshot()
        big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        try:
            data = pytesseract.image_to_data(gray, lang=self.OCR_LANG,
                                             output_type=pytesseract.Output.DICT)
        except Exception:
            data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        nd = needle.lower()
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
            words = [(data["text"][i] or "").strip() for i in idxs]
            line_text = " ".join(words).lower()
            if nd in line_text:
                xs = [data["left"][i] for i in idxs]
                ys = [data["top"][i] for i in idxs]
                xe = [data["left"][i] + data["width"][i] for i in idxs]
                ye = [data["top"][i] + data["height"][i] for i in idxs]
                cx = (min(xs) + max(xe)) / 2 / scale
                cy = (min(ys) + max(ye)) / 2 / scale
                return (int(cx), int(cy))
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
