#!/usr/bin/env python3
"""
ocr.py — đọc chữ trên ảnh màn hình bằng bộ đọc chữ CÓ SẴN của macOS (Apple Vision).

Vì sao: tesseract (bộ đọc cũ) gần như không đọc được chữ đặt trên nền nhiều màu của game — màn hình tiêu đề eFootball nó trả về
RỖNG, trong khi Vision đọc ra «FOOTBALL», «2027», «Konami Digital Entertainment»… trong ~0,3 giây. Không cần cài thêm gì: khung Vision
được nạp thẳng bằng pyobjc-core (đã có sẵn vì pywebview dùng).

Mô-đun này CHỈ thêm một nguồn đọc chữ; nơi gọi (eyes.py, control.py) tự quyết ghép với tesseract thế nào. Không có Vision (không phải
macOS, thiếu pyobjc, nạp lỗi) thì `available()` trả False và mọi hàm trả rỗng — nơi gọi dùng tesseract như trước.

    ocr.lines(img)            → [{"text", "x", "y", "w", "h", "conf"}]   (x, y = TÂM dòng chữ, pixel ảnh gốc, gốc toạ độ trên-trái)
    ocr.find(img, "Đăng nhập") → (cx, cy) tâm của ĐÚNG phần chữ khớp, hoặc None
"""
from __future__ import annotations
import os, threading, unicodedata

LANGS = ("vi-VT", "en-US")              # «vi-VT» là mã Apple đặt cho tiếng Việt trong Vision
_lock = threading.Lock()
_state = {"tried": False, "ok": False, "ns": {}, "error": ""}


def _load():
    """Nạp khung Vision một lần. Đặt IPF_OCR=tesseract để tắt hẳn (vd khi cần so sánh hai bộ đọc)."""
    with _lock:
        if _state["tried"]:
            return _state["ok"]
        _state["tried"] = True
        if os.environ.get("IPF_OCR", "").lower() == "tesseract":
            _state["error"] = "tắt bằng IPF_OCR=tesseract"
            return False
        try:
            import objc
            import Foundation
            ns = {}
            objc.loadBundle("Vision", bundle_path="/System/Library/Frameworks/Vision.framework", module_globals=ns)
            for name in ("VNRecognizeTextRequest", "VNImageRequestHandler"):
                if name not in ns:
                    raise ImportError("Vision thiếu " + name)
            ns["NSData"], ns["objc"] = Foundation.NSData, objc
            _state["ns"], _state["ok"] = ns, True
        except Exception as e:                      # không phải macOS / thiếu pyobjc / hệ quá cũ
            _state["error"] = "%s: %s" % (type(e).__name__, e)
        return _state["ok"]


def available() -> bool:
    return _load()


def why_unavailable() -> str:
    _load()
    return _state["error"]


# Chữ cái Kirin / Hy Lạp TRÔNG Y HỆT chữ Latin. Vision đôi khi trả về chúng (đo thật: nút «OK» đọc ra «ОK» với «О» Kirin, «Epic» ra «Еріс»)
# → so khớp «OK» hỏng dù màn hình ghi đúng. Đổi về chữ Latin trước khi so (sau khi đã chuyển chữ thường).
CONFUSABLE = str.maketrans("аеорсухіјѕԁԛԝоаеорсухкмтвнѵ" "αοοιντκρεχ", "aeopcyxijsdqwoaeopcyxkmtbhv" "aooivtkpex")


def _norm(s) -> str:
    """Cùng cách chuẩn hoá với eyes.norm_text: chữ thường, chữ Kirin / Hy Lạp giống Latin → Latin, bỏ dấu tiếng Việt (đ→d), gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", str(s or "").lower().translate(CONFUSABLE))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(s.replace("đ", "d").split())


def _sideways(rows) -> bool:
    """Phần lớn các dòng chữ (đủ dài) có hộp CAO hơn RỘNG → chữ đang nằm dọc: ảnh chụp bị xoay so với giao diện."""
    longs = [r for r in rows if len(r["text"].replace(" ", "")) >= 3]
    tall = [r for r in longs if (r["box"][3] - r["box"][1]) > 1.3 * (r["box"][2] - r["box"][0])]
    return len(tall) >= 2 and len(tall) >= 0.6 * len(longs)


def _unrotate_box(box, rot, W, H):
    """Hộp trên ảnh đã xoay (rot = "cw" | "ccw") → hộp trên ảnh GỐC cỡ W×H."""
    x0, y0, x1, y1 = box
    if rot == "cw":                                   # gốc (x, y) → xoay thuận (H-1-y, x)  ⇒  (u, v) → (v, H-1-u)
        pts = [(v, H - 1 - u) for u, v in ((x0, y0), (x1, y1))]
    else:                                             # gốc (x, y) → xoay ngược (y, W-1-x)  ⇒  (u, v) → (W-1-v, u)
        pts = [(W - 1 - v, u) for u, v in ((x0, y0), (x1, y1))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (max(0, min(xs)), max(0, min(ys)), min(W, max(xs) + 1), min(H, max(ys) + 1))


_CACHE: list = []                                    # [(khoá, các dòng)] — mới nhất ở cuối
_CACHE_MAX = 6
_cache_lock = threading.Lock()


def _observe(img, correct=False):
    """Như _observe_once, có nhớ kết quả theo NỘI DUNG ảnh: một lần nhìn thường gọi đọc chữ nhiều lần trên cùng một ảnh (read_text rồi
    find_text cho từng chữ cần bấm) — ảnh chụp bị xoay thì mỗi lần là 3 lượt Vision. Các dòng trả ra là CHUNG giữa các lần gọi: chỉ đọc, không sửa."""
    try:
        import zlib
        key = (zlib.crc32(img.tobytes()), img.shape, bool(correct))
    except Exception:
        return _observe_once(img, correct)
    with _cache_lock:
        for k, rows in _CACHE:
            if k == key:
                return rows
    rows = _observe_once(img, correct)
    if not rows:                     # không đọc được chữ nào (có thể Vision trục trặc nhất thời) → không nhớ, lần sau đọc lại
        return rows
    with _cache_lock:
        _CACHE.append((key, rows))
        del _CACHE[:-_CACHE_MAX]
    return rows


def _observe_once(img, correct=False):
    """Các dòng chữ của ảnh, theo thứ tự đọc. Ảnh chụp có lúc bị XOAY so với giao diện (đo trên iPhone 8: trang đăng nhập web mở từ game
    đang ngang trả về khung dọc 750×1334 với nội dung nằm nghiêng — chữ nằm dọc, Vision đọc sót / sai, «Tiếp tục» không tìm thấy) → khi phần
    lớn chữ nằm dọc thì đọc trên bản đã xoay thẳng (thử cả hai chiều, lấy chiều đọc được nhiều chữ nằm ngang hơn) rồi đổi hộp về ảnh GỐC —
    toạ độ trả ra vẫn là toạ độ của ảnh chụp như bên gọi thấy (con trỏ bấm theo đúng ảnh đó)."""
    rows = _observe_raw(img, correct)
    if not rows or not _sideways(rows):
        return rows
    import cv2
    H, W = img.shape[:2]

    def score(rs):
        return sum(len(r["text"]) for r in rs if (r["box"][2] - r["box"][0]) >= (r["box"][3] - r["box"][1]))

    forward = _forward
    best, best_rot, best_key = None, None, None
    for rot, code in (("cw", cv2.ROTATE_90_CLOCKWISE), ("ccw", cv2.ROTATE_90_COUNTERCLOCKWISE)):
        rs = _observe_raw(cv2.rotate(img, code), correct)
        key = (forward(rs), score(rs))
        if best is None or key > best_key:
            best, best_rot, best_key = rs, rot, key
    if not best or best_key[0] < 0 or score(best) <= score(rows):        # chiều = 0: không đo được chiều (dòng quá ngắn) → theo số chữ
        return rows
    for r in best:
        r["rot"], r["W"], r["H"] = best_rot, W, H
        r["fwd"] = best_key[0]    # > 0: đã đo được chiều đúng; 0: KHÔNG đo được (chỉ có dòng một từ) — chiều đọc có thể lộn ngược 180°
        r["box"] = _unrotate_box(r["box"], best_rot, W, H)
    return best                     # GIỮ thứ tự đọc của bản xoay thẳng (xếp lại theo toạ độ ảnh gốc là đọc theo cột → xáo dòng)


def _forward(rs) -> int:
    """Vision đọc được cả chữ LỘN NGƯỢC (xoay sai chiều = 180°) nên đếm chữ không phân biệt được hai chiều; chiều ĐÚNG là chiều mà ký tự
    đầu của dòng nằm BÊN TRÁI ký tự cuối (thứ tự đọc của bản lộn ngược bị đảo ngược hết). Trả (số dòng xuôi) − (số dòng ngược), tính
    trên khung của chính ảnh đã đọc ra `rs` (dòng chưa đổi hộp về ảnh khác)."""
    n = 0
    for r in rs:
        raw = r.get("raw") or ""
        if len(raw.replace(" ", "")) < 4:
            continue
        a, b = _range_box(r, 0, 1), _range_box(r, len(raw) - 1, len(raw))
        if not (a and b):
            continue
        d = (b[0] + b[2]) - (a[0] + a[2])
        if abs(d) > 8:                 # hộp TRÙNG nhau = không có thông tin (đo thật: dòng một từ — Vision trả hộp cả TỪ cho từng ký tự)
            n += 1 if d > 0 else -1
    return n


def upright_turn(img):
    """Ảnh `img` phải QUAY bao nhiêu thì chữ trên đó nằm thẳng: số lần quay 90° THEO chiều kim đồng hồ (0 = đã thẳng, 1, 2 = lộn ngược,
    3 = quay ngược chiều 90°). None = chưa biết (ít chữ quá — màn hình tải, logo; hoặc chữ nằm dọc mà xoay cũng không đọc tốt hơn).
    Dùng chung kết quả đọc chữ với read_text / find_text trên cùng ảnh (có nhớ theo nội dung ảnh) — ảnh đã thẳng thì không tốn thêm."""
    rows = _observe(img)
    longs = [r for r in rows if len((r.get("raw") or r.get("text") or "").replace(" ", "")) >= 4]
    if len(longs) < 2:
        return None
    rot = rows[0].get("rot")
    if rot:
        # chỉ tin chiều đã ĐO được (ký tự đầu nằm bên trái ký tự cuối trên bản xoay). Màn hình chỉ có dòng một từ thì cả hai chiều xoay đều
        # «không rõ» — chọn bừa một chiều là có thể ra ảnh LỘN NGƯỢC (verify vòng 30: hộp thoại «Cancel / Open») → chưa biết.
        if rows[0].get("fwd", 0) <= 0:
            return None
        return 1 if rot == "cw" else 3
    if _sideways(rows):
        return None
    return 2 if _forward(rows) <= -2 else 0


def _observe_raw(img, correct=False):
    """Chạy Vision trên ảnh BGR (numpy). Trả các dòng {text, raw, conf, box (x0, y0, x1, y1) pixel, cand…} theo thứ tự đọc.
    `correct=False`: KHÔNG cho Vision «sửa chính tả theo ngôn ngữ» — ta cần đúng những gì đang hiện trên màn (kiểm bàn phím gõ chuỗi vô
    nghĩa, đọc mã, đọc số tiền…), và việc so khớp phía trên vốn đã không phân biệt dấu / hoa thường."""
    if not _load() or img is None:
        return []
    import cv2
    ns = _state["ns"]
    h, w = img.shape[:2]
    if h < 4 or w < 4:
        return []
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return []
    out = []
    with ns["objc"].autorelease_pool():              # luồng nền (mỗi máy một luồng) không có sẵn vùng tự giải phóng
        raw = buf.tobytes()
        data = ns["NSData"].dataWithBytes_length_(raw, len(raw))
        req = ns["VNRecognizeTextRequest"].alloc().init()
        req.setRecognitionLevel_(0)                   # 0 = chính xác (1 = nhanh)
        req.setUsesLanguageCorrection_(bool(correct))
        try:
            req.setRecognitionLanguages_(list(LANGS))
        except Exception:
            pass                                      # hệ không có tiếng Việt cho Vision → dùng mặc định
        handler = ns["VNImageRequestHandler"].alloc().initWithData_options_(data, {})
        res = handler.performRequests_error_([req], None)
        if res is False or (isinstance(res, tuple) and not res[0]):
            return []
        for o in (req.results() or []):
            cands = o.topCandidates_(1)
            if not cands or not len(cands):
                continue
            c = cands[0]
            raw = str(c.string() or "")
            if not raw.strip():
                continue
            bb = o.boundingBox()                      # toạ độ CHUẨN HOÁ, gốc ở góc DƯỚI-trái
            # `cand` được Python giữ tham chiếu nên vẫn dùng được sau khi rời vùng tự giải phóng (để hỏi hộp của riêng phần chữ khớp)
            out.append({"text": raw.strip(), "raw": raw, "conf": float(c.confidence()), "box": _to_px(bb, w, h), "cand": c, "w": w, "h": h})
    return _reading_order(out)


def _reading_order(rows):
    """Xếp theo thứ tự đọc: trên → dưới; các dòng có tâm gần ngang nhau (cùng một hàng trên màn) thì trái → phải."""
    rows = sorted(rows, key=lambda r: (r["box"][1] + r["box"][3]) / 2)
    out, band = [], []
    for r in rows:
        cy, hh = (r["box"][1] + r["box"][3]) / 2, max(1, r["box"][3] - r["box"][1])
        if band and cy - band[0][0] > 0.6 * min(hh, band[0][1]):
            out += [x for _, _, x in sorted(band, key=lambda t: t[2]["box"][0])]
            band = []
        band.append((cy, hh, r))
    out += [x for _, _, x in sorted(band, key=lambda t: t[2]["box"][0])]
    return out


def _to_px(bb, w, h):
    x0 = int(round(bb.origin.x * w))
    y1 = int(round((1.0 - bb.origin.y) * h))
    x1 = int(round((bb.origin.x + bb.size.width) * w))
    y0 = int(round((1.0 - bb.origin.y - bb.size.height) * h))
    return (max(0, x0), max(0, y0), min(w, x1), min(h, y1))


def lines(img, min_conf: float = 0.3) -> list:
    """Các DÒNG chữ trên ảnh: [{text, x, y, w, h, conf}] — (x, y) là tâm dòng chữ, pixel ảnh gốc. Không có Vision → []."""
    out = []
    for r in _observe(img):
        if r["conf"] < min_conf:
            continue
        x0, y0, x1, y1 = r["box"]
        out.append({"text": r["text"], "x": (x0 + x1) // 2, "y": (y0 + y1) // 2, "w": x1 - x0, "h": y1 - y0, "conf": round(r["conf"], 2)})
    return out


def text(img) -> str:
    """Toàn bộ chữ đọc được, mỗi dòng một hàng. Không có Vision → ''."""
    return "\n".join(r["text"] for r in _observe(img))


def find(img, needle: str):
    """Tâm (cx, cy) của ĐÚNG phần chữ khớp `needle` (không phân biệt hoa thường, dấu, khoảng trắng). Không thấy / không có Vision → None.
    Nhiều dòng cùng khớp: dòng mà CẢ DÒNG đúng bằng `needle` được chọn trước dòng chỉ «có chứa» nó; cùng loại thì lấy dòng đầu theo thứ
    tự đọc. (Đo thật trên trang đăng nhập KONAMI: tìm «Login» khớp cả dòng «Log In with Another KONAMI ID» nằm phía trên nút «Login»
    — bấm theo chỗ khớp đầu tiên là bấm nhầm sang nút đổi tài khoản.)"""
    nd = _norm(needle).replace(" ", "")
    if not nd:
        return None
    first = None
    for r in _observe(img):
        raw = r["raw"]
        joined, owner = "", []                        # owner[k] = vị trí (trong `raw`) của ký tự sinh ra ký tự thứ k của `joined`
        for i, ch in enumerate(raw):
            piece = _norm(ch).replace(" ", "")
            joined += piece
            owner.extend([i] * len(piece))
        pos = joined.find(nd)
        if pos < 0:
            continue
        a, b = owner[pos], owner[pos + len(nd) - 1]
        box = _range_box(r, a, b + 1) or r["box"]     # không lấy được hộp của riêng phần khớp → dùng hộp cả dòng
        hit = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        if whole_line(joined, nd):
            return hit
        if first is None:
            first = hit
    return first


def whole_line(line: str, needle: str) -> bool:
    """Dòng `line` có ĐÚNG BẰNG `needle` không (cả hai đã chuẩn hoá, bỏ khoảng trắng) — không tính dấu câu / ký hiệu bao quanh («< Back», «Login »»)."""
    core = lambda s: "".join(ch for ch in s if ch.isalnum())
    return bool(core(needle)) and core(line) == core(needle)


def _range_box(r, start: int, end: int):
    """Hộp (pixel) của raw[start:end] trong dòng `r`, hoặc None."""
    try:
        raw = r["raw"]
        u0 = len(raw[:start].encode("utf-16-le")) // 2        # NSRange tính theo đơn vị UTF-16
        ulen = len(raw[start:end].encode("utf-16-le")) // 2
        with _state["ns"]["objc"].autorelease_pool():
            res = r["cand"].boundingBoxForRange_error_((u0, ulen), None)
            obs = res[0] if isinstance(res, tuple) else res
            if obs is None:
                return None
            box = _to_px(obs.boundingBox(), r["w"], r["h"])
            return _unrotate_box(box, r["rot"], r["W"], r["H"]) if r.get("rot") else box
    except Exception:
        return None
