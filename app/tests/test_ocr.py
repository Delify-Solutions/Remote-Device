#!/usr/bin/env python3
"""
Kiểm bộ đọc chữ (ocr.py — Apple Vision, ghép với tesseract ở eyes.py / control.py) — không cần iPhone:
  • đọc được chữ tiếng Việt trên NỀN MÀU (kiểu màn hình game) kèm toạ độ đúng; tìm ĐÚNG PHẦN chữ khớp trong một dòng dài;
  • không «sửa chính tả»: chuỗi vô nghĩa (phép thử bàn phím) được đọc nguyên văn;
  • eyes.read_text: GHÉP Vision + tesseract (đọc được thêm, không mất cái cũ); kiểu đọc «một dòng» (psm) giữ nguyên tesseract;
  • eyes.find_text / control.ocr_lines / công cụ find_text: Vision trước, không thấy thì hỏi tesseract;
  • không có Vision (IPF_OCR=tesseract, hoặc không phải macOS) thì mọi thứ chạy như trước bằng tesseract;
  • gọi từ nhiều luồng cùng lúc (mỗi máy một luồng) vẫn đúng.

    ./.venv/bin/python app/tests/test_ocr.py
"""
from __future__ import annotations
import os, subprocess, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
import cv2
import numpy as np

import ocr
import eyes

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def draw(rows, size=(900, 520), bg=(120, 20, 40)):
    """Ảnh BGR nền màu với các dòng chữ [(x, y, chữ, màu RGB)] — kiểu chữ trắng / vàng trên nền game."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, bg[::-1])
    d = ImageDraw.Draw(im)
    font = None
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"):
        if os.path.exists(path):
            font = ImageFont.truetype(path, 38)
            break
    font = font or ImageFont.load_default()
    boxes = []
    for x, y, t, color in rows:
        d.text((x, y), t, font=font, fill=color)
        boxes.append(d.textbbox((x, y), t, font=font))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR), boxes


def inside(pt, box, pad=6):
    return pt is not None and box[0] - pad <= pt[0] <= box[2] + pad and box[1] - pad <= pt[1] <= box[3] + pad


def main():
    print("== 0. Có bộ đọc chữ của macOS không ==")
    if not ocr.available():
        print("  (bỏ qua: máy này không nạp được Apple Vision — %s. App sẽ dùng tesseract như trước.)" % ocr.why_unavailable())
        ok(ocr.lines(np.zeros((50, 50, 3), np.uint8)) == [] and ocr.find(np.zeros((50, 50, 3), np.uint8), "x") is None and ocr.text(None) == "",
           "không có Vision → mọi hàm trả rỗng, không ném lỗi")
        print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
        return 1 if FAIL else 0
    ok(True, "Apple Vision nạp được (không cần cài thêm gói)")

    print("== 1. Đọc chữ trên nền màu + toạ độ ==")
    img, boxes = draw([(60, 40, "Đăng nhập Konami ID", (255, 255, 255)), (60, 140, "afaf qwsx asdf", (255, 220, 0)),
                       (60, 240, "Mua thành công 1.050 Coins", (0, 255, 200)), (60, 340, "Cửa hàng", (255, 255, 255)), (520, 340, "Trang chủ", (255, 255, 255))])
    rows = ocr.lines(img)
    texts = [r["text"] for r in rows]
    ok("Đăng nhập Konami ID" in texts and "Mua thành công 1.050 Coins" in texts, "đọc đúng chữ tiếng Việt có dấu trên nền màu", texts)
    ok("afaf qwsx asdf" in texts, "chuỗi vô nghĩa được đọc NGUYÊN VĂN (không bị «sửa chính tả» thành chữ khác)", texts)
    ok(texts.index("Đăng nhập Konami ID") < texts.index("afaf qwsx asdf") < texts.index("Mua thành công 1.050 Coins")
       and texts.index("Cửa hàng") < texts.index("Trang chủ"), "thứ tự đọc: trên → dưới, cùng hàng thì trái → phải", texts)
    r0 = rows[texts.index("Đăng nhập Konami ID")]
    ok(inside((r0["x"], r0["y"]), boxes[0]) and abs(r0["w"] - (boxes[0][2] - boxes[0][0])) < 40 and set(r0) == {"text", "x", "y", "w", "h", "conf"},
       "mỗi dòng có tâm (x, y) nằm đúng trên dòng chữ, kèm bề rộng / cao / độ tin", (r0, boxes[0]))
    ok(ocr.text(img).split("\n")[0] == "Đăng nhập Konami ID", "text(): mỗi dòng một hàng theo thứ tự đọc")

    print("== 2. Tìm đúng PHẦN chữ khớp ==")
    whole = ocr.find(img, "Đăng nhập Konami ID")
    left, right = ocr.find(img, "đăng nhập"), ocr.find(img, "KONAMI ID")
    ok(inside(whole, boxes[0]) and inside(left, boxes[0]) and inside(right, boxes[0]), "tìm thấy cả câu lẫn từng phần của nó", (whole, left, right))
    ok(left[0] < whole[0] < right[0] and right[0] - left[0] > 120, "tâm trả về là của ĐÚNG phần khớp (phần đầu nằm bên trái, phần cuối nằm bên phải) — bấm trúng chữ cần bấm", (left, whole, right))
    ok(inside(ocr.find(img, "dang nhap"), boxes[0]) and inside(ocr.find(img, "MUATHANHCONG"), boxes[2]), "không phân biệt dấu, hoa thường, khoảng trắng")
    ok(inside(ocr.find(img, "trang chu"), boxes[4]) and inside(ocr.find(img, "cửa hàng"), boxes[3]) and ocr.find(img, "trang chu")[0] > ocr.find(img, "cửa hàng")[0] + 300,
       "hai nhãn trên cùng một hàng: tìm đúng từng nhãn")
    ok(ocr.find(img, "không có chữ này") is None and ocr.find(img, "") is None and ocr.find(img, "   ") is None, "không có / chuỗi rỗng → None")
    ok(ocr.lines(np.zeros((3, 3, 3), np.uint8)) == [] and ocr.lines(None) == [] and ocr.find(None, "x") is None, "ảnh rỗng / quá nhỏ → rỗng, không ném lỗi")
    blank = np.full((200, 300, 3), 90, np.uint8)
    ok(ocr.lines(blank) == [] and ocr.text(blank) == "", "ảnh không có chữ → không bịa ra chữ")

    print("== 3. Nhiều luồng cùng lúc (mỗi máy một luồng) ==")
    got, errs = [], []

    def work():
        try:
            got.append((len(ocr.lines(img)), ocr.find(img, "cửa hàng")))
        except Exception as e:
            errs.append(e)
    ths = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in ths]; [t.join(60) for t in ths]
    ok(not errs and len(got) == 6 and len(set(got)) == 1, "6 luồng đọc cùng một ảnh → cùng một kết quả, không lỗi", (got, errs))

    print("== 4. eyes.read_text / find_text: ghép với tesseract ==")
    e = eyes.Eyes("khong-dung-toi")
    real_tess = eyes.pytesseract

    class Tess:                                   # tesseract giả: ghi lại lần gọi, trả chữ cố định
        class Output:
            DICT = "dict"

        def __init__(self): self.calls = []

        def image_to_string(self, gray, lang=None, config=""):
            self.calls.append(("string", config))
            return "CHU CUA TESSERACT"

        def image_to_data(self, gray, lang=None, output_type=None):
            self.calls.append(("data", ""))
            return {"text": ["Chỉ", "tesseract", "thấy"], "block_num": [1, 1, 1], "par_num": [1, 1, 1], "line_num": [1, 1, 1],
                    "left": [100, 200, 420], "top": [600, 600, 600], "width": [80, 200, 100], "height": [40, 40, 40], "conf": [90, 90, 90]}
    try:
        fake = Tess()
        eyes.pytesseract = fake
        t = e.read_text(img)
        ok("Mua thành công 1.050 Coins" in t and "CHU CUA TESSERACT" in t and fake.calls == [("string", "")],
           "đọc cả màn hình: có chữ của Vision VÀ của tesseract (cái gì trước đây đọc được thì vẫn đọc được)", t)
        fake.calls.clear()
        real_text = ocr.text
        ocr.text = lambda im: (_ for _ in ()).throw(AssertionError("không được gọi Vision cho kiểu đọc một dòng"))
        try:
            one = e.read_text(img, region=(40, 130, 600, 200), scale=3, lang="eng", psm=7)
        finally:
            ocr.text = real_text
        ok(one == "CHU CUA TESSERACT" and fake.calls == [("string", "--psm 7")], "kiểu đọc MỘT DÒNG (psm — phép thử bàn phím) vẫn chỉ dùng tesseract như trước", (one, fake.calls))
        fake.calls.clear()
        hit = e.find_text("cửa hàng", img)
        ok(inside(hit, boxes[3]) and fake.calls == [], "tìm chữ: Vision thấy thì dùng luôn (không cần tesseract)", (hit, fake.calls))
        hit2 = e.find_text("tesseract thấy", img)
        ok(hit2 == (int((200 + 520) / 2 / 2), int((600 + 640) / 2 / 2)) and fake.calls == [("data", "")], "Vision không thấy → hỏi tesseract (toạ độ như trước)", (hit2, fake.calls))
        ok(e.find_text("hoàn toàn không có", img) is None, "cả hai không thấy → None")
        real_find, real_txt = ocr.find, ocr.text
        ocr.find = ocr.text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Vision hỏng giữa chừng"))
        try:
            ok(e.read_text(img) == "CHU CUA TESSERACT" and e.find_text("tesseract thấy", img) is not None, "Vision ném lỗi giữa chừng → vẫn đọc / tìm bằng tesseract, không ném lỗi ra ngoài")
        finally:
            ocr.find, ocr.text = real_find, real_txt
        eyes.pytesseract = None
        ok("Cửa hàng" in e.read_text(img) and inside(e.find_text("trang chủ", img), boxes[4]) and e.find_text("không có", img) is None,
           "máy không cài tesseract nhưng có Vision → vẫn đọc và tìm được (không báo «thiếu pytesseract»)")
        try:
            e.read_text(img, psm=7); raised = False
        except RuntimeError:
            raised = True
        ok(raised, "…riêng kiểu đọc một dòng (psm) thì vẫn cần tesseract → báo rõ khi thiếu")
    finally:
        eyes.pytesseract = real_tess

    print("== 5. control.ocr_lines + công cụ find_text ==")
    import control
    real_ct = control.pytesseract
    try:
        fake = Tess()
        control.pytesseract = fake
        rows_a = control.ocr_lines(img)
        ok([r["text"] for r in rows_a] == texts and set(rows_a[0]) == {"text", "x", "y", "w", "h"} and fake.calls == [], "ocr_lines (tự chọn): dùng Vision, cùng dạng dữ liệu như trước", rows_a[:2])
        rows_t = control.ocr_lines(img, engine="tesseract")
        ok([r["text"] for r in rows_t] == ["Chỉ tesseract thấy"] and fake.calls == [("data", "")], "ocr_lines(engine=tesseract): chỉ tesseract", rows_t)
        fake.calls.clear()
        ok([r["text"] for r in control.ocr_lines(blank)] == ["Chỉ tesseract thấy"] and fake.calls == [("data", "")], "Vision không đọc ra dòng nào → tự hỏi tesseract")

        class Host:
            pass
        c = control.Control(Host())
        c._eyes = lambda device=None: ("May-1", type("E", (), {"screenshot": staticmethod(lambda: img)})())
        r1 = c.find_text("Trang chủ")
        ok(r1.data["matches"] and inside((r1.data["matches"][0]["x"], r1.data["matches"][0]["y"]), boxes[4]), "công cụ find_text: thấy chữ trên nền màu", r1.data)
        r2 = c.find_text("tesseract thấy")
        ok([m["text"] for m in r2.data["matches"]] == ["Chỉ tesseract thấy"], "công cụ find_text: Vision không thấy → tìm thêm bằng tesseract", r2.data)
        ok(c.find_text("khong co dau").data["matches"] == [], "công cụ find_text: không thấy → danh sách rỗng")
        control.pytesseract = None
        ok([r["text"] for r in control.ocr_lines(img)] == texts and control.ocr_lines(blank) == [], "không cài tesseract nhưng có Vision → ocr_lines vẫn chạy (ảnh không chữ thì rỗng, không báo lỗi)")
    finally:
        control.pytesseract = real_ct

    print("== 6. Tắt Vision (IPF_OCR=tesseract) → như trước ==")
    code = ("import sys; sys.path.insert(0, %r); import ocr, numpy as np; im = np.zeros((80, 80, 3), np.uint8); "
            "print(ocr.available(), ocr.lines(im), ocr.find(im, 'x'), repr(ocr.text(im)), ocr.why_unavailable())" % APP)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="tesseract"), timeout=120)
    ok(r.stdout.strip().startswith("False [] None ''") and "IPF_OCR" in r.stdout, "IPF_OCR=tesseract → không dùng Vision; mọi hàm trả rỗng để nơi gọi dùng tesseract", (r.stdout, r.stderr[-200:]))

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
