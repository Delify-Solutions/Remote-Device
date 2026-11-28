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
    # phông PHẢI có chữ tiếng Việt có dấu (phông mặc định của PIL không có → ảnh mẫu thiếu dấu, bộ đọc chữ bị chê oan)
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf",
                 os.path.join(windir, "Fonts", "arial.ttf"), os.path.join(windir, "Fonts", "segoeui.ttf"),
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
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
    # Trang đăng nhập KONAMI (đo thật): dòng «Log In with Another KONAMI ID» nằm TRÊN nút «Login» — tìm «Login» phải ra NÚT, không ra dòng trên
    web, wb = draw([(60, 40, "Log In with Another KONAMI ID", (0, 120, 220)), (60, 140, "Password", (90, 90, 90)), (300, 240, "Login", (255, 255, 255)),
                    (60, 340, "< Back", (255, 255, 255)), (60, 430, "Login now or later", (255, 255, 255))], bg=(40, 30, 170))
    ok(inside(ocr.find(web, "Login"), wb[2]) and inside(ocr.find(web, "login"), wb[2]),
       "nhiều dòng cùng khớp: dòng mà CẢ DÒNG đúng bằng chữ cần tìm được chọn trước dòng chỉ «có chứa» nó (dù dòng kia đứng trước)", (ocr.find(web, "Login"), wb[2]))
    ok(inside(ocr.find(web, "Log In with"), wb[0]) and inside(ocr.find(web, "another konami"), wb[0]) and inside(ocr.find(web, "login now"), wb[4]),
       "…chữ dài hơn thì vẫn tìm đúng dòng chứa nó; không dòng nào khớp nguyên dòng → lấy dòng đầu theo thứ tự đọc")
    ok(inside(ocr.find(web, "Back"), wb[3]), "dấu câu / ký hiệu quanh chữ («< Back») không cản việc khớp nguyên dòng", ocr.find(web, "Back"))
    ok(ocr.whole_line("login", "login") and ocr.whole_line("<back", "back") and ocr.whole_line("login»", "log in".replace(" ", ""))
       and not ocr.whole_line("loginwithanotherkonamiid", "login") and not ocr.whole_line("abc", "") and not ocr.whole_line("...", "..."),
       "whole_line: bằng nhau sau khi bỏ ký hiệu; chuỗi chỉ toàn ký hiệu / rỗng thì không tính")
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

    print("== 3b. Ảnh chụp bị XOAY (chữ nằm dọc) → đọc trên bản xoay thẳng, toạ độ trả về theo ảnh GỐC ==")
    # đo thật: trang đăng nhập web mở từ game đang ngang trả về khung DỌC với nội dung nằm nghiêng → Vision đọc sót «Tiếp tục»
    flat, fb = draw([(60, 40, "eFootball muốn sử dụng konami.net", (255, 255, 255)), (60, 140, "Tiếp tục", (255, 255, 255)), (420, 140, "Hủy", (255, 255, 255)),
                     (60, 240, "KONAMI ID / E-mail address", (255, 255, 255))], size=(900, 360))
    for code, name in ((cv2.ROTATE_90_CLOCKWISE, "thuận"), (cv2.ROTATE_90_COUNTERCLOCKWISE, "ngược")):
        side = cv2.rotate(flat, code)
        H0, W0 = flat.shape[:2]

        def rot_pt(x, y):                       # điểm trên ảnh phẳng → điểm trên ảnh xoay
            return (H0 - 1 - y, x) if code == cv2.ROTATE_90_CLOCKWISE else (y, W0 - 1 - x)

        def rot_box(b):
            p1, p2 = rot_pt(b[0], b[1]), rot_pt(b[2], b[3])
            return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
        hit = ocr.find(side, "Tiếp tục")
        side_texts = [r["text"] for r in ocr.lines(side)]
        ok(inside(hit, rot_box(fb[1]), pad=10) and "Tiếp tục" in side_texts and "KONAMI ID / E-mail address" in side_texts and inside(ocr.find(side, "Hủy"), rot_box(fb[2]), pad=10),
           "ảnh xoay %s 90°: đọc được đủ chữ, và vị trí «Tiếp tục» / «Hủy» là vị trí TRÊN ẢNH XOAY (chỗ con trỏ sẽ bấm)" % name, (hit, rot_box(fb[1]), side_texts))
        order = [next((i for i, t in enumerate(side_texts) if want in t), -1) for want in ("eFootball", "Tiếp tục", "KONAMI ID")]
        ok(-1 not in order and order == sorted(order),
           "ảnh xoay %s 90°: các dòng giữ THỨ TỰ ĐỌC của giao diện (trên → dưới), không bị xếp lại theo cột của ảnh gốc" % name, (order, side_texts))
    ok(not ocr._sideways([{"text": "abc", "box": (0, 0, 10, 40)}]) and ocr._sideways([{"text": "abcd", "box": (0, 0, 10, 40)}, {"text": "efgh", "box": (20, 0, 30, 50)}, {"text": "ij", "box": (0, 0, 50, 5)}])
       and not ocr._sideways([{"text": "abcd", "box": (0, 0, 100, 20)}, {"text": "efgh", "box": (0, 0, 10, 40)}]),
       "chỉ coi là «chữ nằm dọc» khi PHẦN LỚN các dòng đủ dài có hộp cao hơn rộng (một dòng dọc lẻ — chữ trang trí — không làm xoay cả ảnh)")
    ok(ocr._unrotate_box((10, 20, 30, 60), "cw", 100, 200) == (20, 169, 61, 190) and ocr._unrotate_box((10, 20, 30, 60), "ccw", 100, 200) == (39, 10, 80, 31),
       "đổi hộp từ ảnh xoay về ảnh gốc (cả hai chiều)")

    ok(eyes.norm_text("ОK") == "ok" and eyes.norm_text("Еріс") == "epic" and ocr._norm("ВАСК") == "back" and eyes.text_has(eyes.norm_text("Nút ОK"), "OK")
       and eyes.norm_text("Đăng nhập") == "dang nhap" and eyes.norm_text("Эра") == "эpa",
       "chữ Kirin / Hy Lạp trông y hệt chữ Latin được đổi về Latin khi so (Vision từng đọc «OK» thành «ОK»); chữ Kirin không giống Latin giữ nguyên")

    print("== 3c. Ảnh THẲNG: Eyes.screenshot() luôn trả ảnh cùng chiều với giao diện ==")
    # đo thật (máy 01): sau khi mở trang đăng nhập web từ game ngang, ảnh chụp ra khung DỌC với nội dung nằm nghiêng
    ui, _ = draw([(60, 40, "eFootball muốn sử dụng konami.net", (255, 255, 255)), (60, 140, "Tiếp tục", (255, 255, 255)),
                  (420, 140, "Hủy", (255, 255, 255)), (60, 240, "KONAMI ID / E-mail address", (255, 255, 255))], size=(900, 360))
    blank = np.full_like(ui, 200)
    portrait_ui, _ = draw([(40, 60, "Cài đặt chung", (255, 255, 255)), (40, 160, "Giới thiệu máy", (255, 255, 255)),
                           (40, 260, "Cập nhật phần mềm", (255, 255, 255))], size=(360, 900))
    calls = []
    real_turn = ocr.upright_turn

    def counted(img):
        calls.append(img.shape)
        return real_turn(img)

    class Cam(eyes.Eyes):                             # «máy» trả ảnh chụp theo danh sách đặt sẵn
        def __init__(self, udid):
            super().__init__(udid)
            self.feed = []

        def grab(self):
            return self.feed.pop(0) if len(self.feed) > 1 else self.feed[0]
    real_gap = eyes.Eyes.TURN_GAP
    ocr.upright_turn = counted
    try:
        for k, name in ((1, "thuận"), (3, "ngược")):
            eyes.Eyes._turns.clear()
            cam = Cam("may-xoay-%d" % k)
            cam.feed = [eyes.Eyes.rotate(ui, k)]          # khung dọc, nội dung xoay `k` lần 90° theo chiều kim đồng hồ
            got = cam.screenshot()
            ok(got.shape == ui.shape and np.array_equal(got, ui) and cam.turn() == (4 - k) % 4,
               "ảnh chụp xoay %s 90° → trả đúng ảnh THẲNG như giao diện (toạ độ / vùng ảnh / hướng lướt ghi trên ảnh thẳng dùng được)" % name, (got.shape, cam.turn()))
        calls.clear()
        for _ in range(4):
            cam.screenshot()
        ok(calls == [] and cam.turn() == 1, "đã biết cách quay, màn hình không đổi → KHÔNG đọc chữ lại (mỗi ảnh chỉ tốn một lần quay ảnh)", calls)
        eyes.Eyes.TURN_GAP = 0
        cam.feed = [eyes.Eyes.rotate(blank, 3)]
        g2 = cam.screenshot()
        ok(cam.turn() == 1 and g2.shape == ui.shape and eyes.Eyes._turns[cam.udid]["sure"] is False,
           "màn hình đổi sang trang KHÔNG có chữ (đang tải) → giữ cách quay cũ, đánh dấu «chưa chắc» để xét lại sau", (cam.turn(), g2.shape))
        cam.feed = [portrait_ui]                          # cùng cỡ khung dọc, nhưng giờ là giao diện DỌC thật (về màn hình chính)
        with cam.steady():
            g3 = cam.screenshot()
        ok(g3.shape[:2] == (360, 900) and cam.turn() == 1,
           "đang đưa con trỏ (steady) → KHÔNG xét lại cách quay giữa chừng, dù màn hình đã đổi", g3.shape)
        g4 = cam.screenshot()
        ok(cam.turn() == 0 and np.array_equal(g4, portrait_ui), "hết steady → xét lại: giao diện dọc thật → không quay nữa", (cam.turn(), g4.shape))
        cam.feed = [ui]                                   # cỡ ảnh chụp đổi (khung ngang bình thường trở lại)
        g5 = cam.screenshot()
        ok(cam.turn() == 0 and np.array_equal(g5, ui), "cỡ ảnh chụp đổi → xét lại ngay; ảnh ngang đã thẳng → không quay", cam.turn())
        eyes.Eyes._turns.clear()
        cam.feed = [eyes.Eyes.rotate(ui, 2)]
        ok(np.array_equal(cam.screenshot(), ui) and cam.turn() == 2, "ảnh lộn ngược (chữ đọc được nhưng ký tự đầu nằm bên phải ký tự cuối) → quay 180°", cam.turn())
        eyes.Eyes._turns.clear()
        cam.feed = [eyes.Eyes.rotate(blank, 1)]
        ok(cam.screenshot().shape == blank.shape[:2][::-1] + (3,) and cam.turn() == 0, "máy mới, màn hình chưa có chữ → không quay (chưa biết thì không đoán)", cam.turn())
        words, _ = draw([(80, 60, "Cancel", (255, 255, 255)), (520, 60, "Open", (255, 255, 255)), (80, 220, "Settings", (255, 255, 255)),
                         (520, 220, "Download", (255, 255, 255))], size=(900, 360))
        for k in (1, 3):
            t = real_turn(eyes.Eyes.rotate(words, k))
            eyes.Eyes._turns.clear()
            cam.feed = [eyes.Eyes.rotate(words, k)]
            gw = cam.screenshot()
            ok(t in (None, (4 - k) % 4) and (cam.turn() in (0, (4 - k) % 4)) and not (cam.turn() == (6 - k) % 4),
               "màn hình chỉ có chữ MỘT từ, xoay %d lần: không đo được chiều → không đoán (không bao giờ ra ảnh lộn ngược 180°)" % k, (t, cam.turn()))
        ok(eyes.Eyes._turns[cam.udid]["sure"] is (real_turn(eyes.Eyes.rotate(words, 3)) is not None),
           "…và «chưa chắc» khi không đo được → lần sau xét lại")
        eyes.Eyes._turns.clear()
        cam.feed = [eyes.Eyes.rotate(ui, 1)]
        cam.screenshot()
        calls.clear()
        other, _ = draw([(60, 60, "Purchase Successful today", (255, 255, 255)), (60, 200, "eFootball Coins were added", (255, 255, 255))], size=(900, 360), bg=(30, 110, 60))
        cam.feed = [eyes.Eyes.rotate(other, 1)]
        cam.screenshot()
        ok(len(calls) == 1 and cam.turn() == 3, "đã chắc mà màn hình ĐỔI nhiều → xét lại (một lần)", (calls, cam.turn()))
        calls.clear()
        cam.screenshot()
        ok(calls == [], "màn hình đứng yên → không xét lại", calls)
        eyes.Eyes._turns[cam.udid]["t"] -= eyes.Eyes.TURN_AGE + 1
        cam.screenshot()
        ok(len(calls) == 1, "đứng yên nhưng đã quá %ds → xét lại cho chắc" % eyes.Eyes.TURN_AGE, calls)

        def racing(img):                              # luồng KHÁC của cùng máy bắt đầu đưa con trỏ ngay trong lúc ta đang xét
            eyes.Eyes._steady[cam.udid] = eyes.Eyes._steady.get(cam.udid, 0) + 1
            return 2
        ocr.upright_turn = racing
        eyes.Eyes._turns[cam.udid]["t"] -= eyes.Eyes.TURN_AGE + 1
        try:
            gr = cam.screenshot()
        finally:
            eyes.Eyes._steady[cam.udid] -= 1
            ocr.upright_turn = counted
        ok(cam.turn() == 3 and np.array_equal(gr, other), "kết quả xét lại tới SAU khi luồng khác đã bắt đầu đưa con trỏ → không đổi cách quay giữa chừng của nó", cam.turn())
        eyes.Eyes.UPRIGHT = False
        eyes.Eyes._turns.clear()
        cam.feed = [eyes.Eyes.rotate(ui, 1)]
        ok(cam.screenshot().shape[:2] == (900, 360), "tắt UPRIGHT → trả nguyên ảnh chụp")
    finally:
        eyes.Eyes.UPRIGHT = True
        eyes.Eyes.TURN_GAP = real_gap
        ocr.upright_turn = real_turn
        eyes.Eyes._turns.clear()

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

        class Tess2(Tess):                        # tesseract thấy hai dòng: «Chi tesseract thay them» (trên) và «tesseract thay» (dưới)
            def image_to_data(self, gray, lang=None, output_type=None):
                return {"text": ["Chi", "tesseract", "thay", "them", "tesseract", "thay"], "block_num": [1] * 6, "par_num": [1] * 6, "line_num": [1, 1, 1, 1, 2, 2],
                        "left": [100, 200, 420, 540, 300, 520], "top": [600] * 4 + [800] * 2, "width": [80, 200, 100, 100, 200, 100], "height": [40] * 6, "conf": [90] * 6}
        eyes.pytesseract = Tess2()
        ok(e.find_text("tesseract thay", img) == (int((300 + 620) / 2 / 2), int((800 + 840) / 2 / 2)) and e.find_text("thay them", img) == (int((420 + 640) / 2 / 2), int((600 + 640) / 2 / 2)),
           "đường tesseract cũng vậy: dòng khớp NGUYÊN DÒNG được chọn trước dòng chỉ chứa chữ đó", e.find_text("tesseract thay", img))
        eyes.pytesseract = fake
        real_find, real_txt = ocr.find, ocr.text
        ocr.find = ocr.text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Vision hỏng giữa chừng"))
        try:
            ok(e.read_text(img) == "CHU CUA TESSERACT" and e.find_text("tesseract thấy", img) is not None, "Vision ném lỗi giữa chừng → vẫn đọc / tìm bằng tesseract, không ném lỗi ra ngoài")
        finally:
            ocr.find, ocr.text = real_find, real_txt
        eyes.pytesseract = None
        real_txt2 = ocr.text
        ocr.text = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Vision hỏng"))
        try:
            e.read_text(img); raised_v = False
        except RuntimeError as err:
            raised_v = "Vision" in str(err) and "tesseract" in str(err)
        finally:
            ocr.text = real_txt2
        ok(raised_v, "Vision báo lỗi giữa chừng mà máy không cài tesseract → BÁO LỖI (không lặng lẽ trả «màn hình trống» — trống thì mọi luật nhận diện đều sai)")
        real_find2 = ocr.find
        ocr.find = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Vision hỏng"))
        try:
            e.find_text("cửa hàng", img); raised_f = False
        except RuntimeError as err:
            raised_f = "Vision" in str(err)
        finally:
            ocr.find = real_find2
        ok(raised_f, "…tìm chữ cũng vậy: BÁO LỖI chứ không trả «không thấy chữ» (sai lý do)")
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

    print("== 7. RapidOCR — bộ đọc chữ trên Windows / Linux (chạy được cả trên Mac để đo) ==")
    try:
        import rapidocr  # noqa: F401
        have_rapid = True
    except Exception:
        have_rapid = False
    if not have_rapid:
        print("  (BỎ QUA: máy này chưa cài rapidocr)")
    else:
        saved, env0 = dict(ocr._state), os.environ.get("IPF_OCR")
        os.environ["IPF_OCR"] = "rapid"
        ocr._state.update(tried=False, ok=False, engine="", error="")
        try:
            ok(ocr.available() and ocr.engine() == "rapid" and ocr.engine_name() == "RapidOCR", "IPF_OCR=rapid → dùng RapidOCR", ocr.why_unavailable())
            pg, pb = draw([(60, 60, "Log In with Another KONAMI ID", (90, 160, 255)), (60, 200, "KONAMI ID / E-mail address", (255, 255, 255)),
                           (60, 330, "Login", (255, 255, 255)), (500, 330, "Tiếp tục", (255, 255, 255)), (760, 330, "Hủy", (255, 255, 255))], size=(900, 420))
            ok(inside(ocr.find(pg, "Login"), pb[2]) and inside(ocr.find(pg, "Tiếp tục"), pb[3]) and inside(ocr.find(pg, "Hủy"), pb[4], pad=12),
               "tìm chữ: «Login» chọn dòng khớp NGUYÊN DÒNG (không nhầm sang «Log In with Another…»); chữ tiếng Việt khớp dù đọc ra không dấu",
               (ocr.find(pg, "Login"), ocr.find(pg, "Tiếp tục"), ocr.find(pg, "Hủy"), [r["text"] for r in ocr.lines(pg)]))
            part = ocr.find(pg, "KONAMI ID / E-mail")
            ok(part is not None and pb[1][0] - 6 <= part[0] < (pb[1][0] + pb[1][2]) / 2 + 40, "hộp của RIÊNG phần chữ khớp trong một dòng dài (từ hộp từng ký tự)", (part, pb[1]))
            rows = ocr._raw_cached(pg)
            ok(any(r.get("cboxes") for r in rows) and all(r.get("cand") is None for r in rows), "mỗi dòng có hộp từng ký tự; không lẫn kiểu dòng của Vision")
            for code, name in ((cv2.ROTATE_90_CLOCKWISE, "thuận"), (cv2.ROTATE_90_COUNTERCLOCKWISE, "ngược")):
                side = cv2.rotate(pg, code)
                H0, W0 = pg.shape[:2]
                rp = (lambda x, y: (H0 - 1 - y, x)) if code == cv2.ROTATE_90_CLOCKWISE else (lambda x, y: (y, W0 - 1 - x))
                b = pb[3]
                p1, p2 = rp(b[0], b[1]), rp(b[2], b[3])
                rb = (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
                ok(inside(ocr.find(side, "Tiếp tục"), rb, pad=12), "ảnh xoay %s 90°: vẫn tìm được «Tiếp tục», toạ độ theo ảnh xoay" % name, (ocr.find(side, "Tiếp tục"), rb))
            got = [ocr.upright_turn(eyes.Eyes.rotate(ui, k)) for k in range(4)]
            ok(got == [0, 3, 2, 1], "nhận chiều ảnh đủ 4 hướng (lộn ngược: RapidOCR đọc ra rác — so với bản xoay 180° mới biết)", got)
            eyes.Eyes._turns.clear()
            camr = Cam("may-rapid")
            camr.feed = [eyes.Eyes.rotate(ui, 1)]
            ok(np.array_equal(camr.screenshot(), ui), "Eyes.screenshot() quay thẳng ảnh bằng RapidOCR như với Vision")
            ok(ocr.upright_turn(blank) is None, "màn hình không có chữ → chưa biết (chỉ dò khung chữ, không đọc cả 4 hướng)")
            ocr._det_boxes(cv2.rotate(pg, cv2.ROTATE_180))            # một lần «chỉ dò khung» (use_rec=False)…
            ok(len(ocr._observe_raw(pg)) >= 4, "…lần đọc SAU vẫn đọc ra chữ (RapidOCR 3.x nhớ thiết lập của lần gọi trước — đo thật: mọi ảnh sau đó ra rỗng)")
        finally:
            eyes.Eyes._turns.clear()
            ocr._state.clear(); ocr._state.update(saved)
            if env0 is None:
                os.environ.pop("IPF_OCR", None)
            else:
                os.environ["IPF_OCR"] = env0

    print("== 6. Tắt Vision (IPF_OCR=tesseract) → như trước ==")
    code = ("import sys; sys.path.insert(0, %r); import ocr, numpy as np; im = np.zeros((80, 80, 3), np.uint8); "
            "print(ocr.available(), ocr.lines(im), ocr.find(im, 'x'), repr(ocr.text(im)), ocr.why_unavailable())" % APP)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, IPF_OCR="tesseract"), timeout=120)
    ok(r.stdout.strip().startswith("False [] None ''") and "IPF_OCR" in r.stdout, "IPF_OCR=tesseract → không dùng Vision; mọi hàm trả rỗng để nơi gọi dùng tesseract", (r.stdout, r.stderr[-200:]))

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
