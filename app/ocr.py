#!/usr/bin/env python3
"""
ocr.py — đọc chữ trên ảnh màn hình. Hai bộ đọc, chọn tự động:
  • macOS: Apple Vision (CÓ SẴN trong máy, nạp bằng pyobjc-core — đã có vì pywebview dùng): nhanh (~0,15 s), đọc tốt nhất.
  • Windows / Linux (hoặc macOS không nạp được Vision): RapidOCR (mô hình PaddleOCR chạy bằng onnxruntime, cài bằng pip `rapidocr`,
    dùng mô hình chữ LATIN — có tiếng Việt) — đo trên 68 ảnh màn hình eFootball thật: thấy 96% số lần các câu chữ của kịch bản mà Vision
    thấy (chỗ sót chủ yếu là ảnh bị xoay — phần quay thẳng ảnh lo), ~0,5 s / ảnh (Vision ~0,15 s).
  Đặt IPF_OCR=vision | rapid để ép một bộ (vd thử RapidOCR ngay trên Mac); IPF_OCR=tesseract để tắt cả hai.

Vì sao không dùng tesseract: nó gần như không đọc được chữ đặt trên nền nhiều màu của game — màn hình tiêu đề eFootball nó trả về RỖNG.

Mô-đun này CHỈ thêm một nguồn đọc chữ; nơi gọi (eyes.py, control.py) tự quyết ghép với tesseract thế nào. Không có bộ đọc nào
(`available()` False) thì mọi hàm trả rỗng — nơi gọi dùng tesseract như trước.

    ocr.lines(img)            → [{"text", "x", "y", "w", "h", "conf"}]   (x, y = TÂM dòng chữ, pixel ảnh gốc, gốc toạ độ trên-trái)
    ocr.find(img, "Đăng nhập") → (cx, cy) tâm của ĐÚNG phần chữ khớp, hoặc None
"""
from __future__ import annotations
import os, threading, time, unicodedata

LANGS = ("vi-VT", "en-US")              # «vi-VT» là mã Apple đặt cho tiếng Việt trong Vision
_lock = threading.Lock()
_state = {"tried": False, "ok": False, "engine": "", "ns": {}, "rapid": None, "error": "", "retry_at": 0.0}
RETRY_SECS = 60.0       # nạp bộ đọc hỏng (vd lần đầu chạy RapidOCR không có mạng để tải mô hình) → chừng này giây sau tự thử lại
_rapid_lock = threading.Lock()          # một bộ RapidOCR dùng chung cho mọi máy: mỗi lúc chỉ đọc một ảnh (onnxruntime đã tự dùng nhiều nhân)


def _load_vision():
    import objc
    import Foundation
    ns = {}
    objc.loadBundle("Vision", bundle_path="/System/Library/Frameworks/Vision.framework", module_globals=ns)
    for name in ("VNRecognizeTextRequest", "VNImageRequestHandler"):
        if name not in ns:
            raise ImportError("Vision thiếu " + name)
    ns["NSData"], ns["objc"] = Foundation.NSData, objc
    _state["ns"] = ns


def _load_rapid():
    # Mô hình nhận chữ LATIN (rapidocr gọi là bộ «PP-OCRv4» — tệp latin_PP-OCRv3_rec_mobile.onnx; có chữ có dấu tiếng Việt). Mô hình mặc
    # định Trung + Anh đọc «Tiếp tục» ra «Tiép tyc»; bản Latin PP-OCRv5 làm RƠI chữ: «lưu mật khẩu» ra «luu mt khu».
    from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType
    eng = RapidOCR(params={"Rec.lang_type": LangRec.LATIN, "Rec.model_type": ModelType.MOBILE,
                           "Rec.ocr_version": OCRVersion.PPOCRV4, "Global.log_level": "error"})
    # ĐỌC THỬ ngay lúc nạp: RapidOCR chỉ nạp mô hình (và lần đầu TẢI về, ~19 MB, cần mạng) ở lần đọc đầu tiên; thiếu onnxruntime / không tải
    # được mô hình mà không thử thì «có bộ đọc» vẫn báo có, rồi lần đọc nào cũng hỏng (verify vòng 31).
    import cv2
    import numpy as np
    probe = np.zeros((80, 360, 3), np.uint8)
    cv2.putText(probe, "OK 2027", (20, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    res = eng(probe, use_det=True, use_cls=False, use_rec=True, return_word_box=True)
    if getattr(res, "txts", None) is None:
        raise RuntimeError("RapidOCR đọc thử không ra chữ nào (mô hình hỏng?)")
    _state["rapid"] = eng


def _load():
    """Nạp bộ đọc chữ một lần: Vision (macOS) trước, không được thì RapidOCR. IPF_OCR=vision | rapid ép một bộ; =tesseract tắt cả hai."""
    if _state["tried"] and (_state["ok"] or time.time() < _state["retry_at"]):
        return _state["ok"]
    # Lần nạp ĐẦU: mọi luồng chờ (cần câu trả lời). Lần THỬ LẠI (sau khi hỏng): luồng khác KHÔNG chờ — đang có luồng thử thì trả ngay «chưa có»
    # (thử lại có thể là tải mô hình với mạng treo tới 60 giây — verify vòng 31: mọi máy đứng chờ khoá cả phút).
    if not _lock.acquire(blocking=_state["retry_at"] == 0.0):      # retry_at chỉ khác 0 sau một lần nạp HỎNG
        return _state["ok"]
    try:
        if _state["tried"] and (_state["ok"] or time.time() < _state["retry_at"]):
            return _state["ok"]
        _state["tried"] = True
        want = os.environ.get("IPF_OCR", "").strip().lower()
        if want == "tesseract":
            _state["error"] = "tắt bằng IPF_OCR=tesseract"
            _state["retry_at"] = float("inf")
            return False
        errs = []
        for name, fn in (("vision", _load_vision), ("rapid", _load_rapid)):
            if want in ("vision", "rapid") and want != name:
                continue
            try:
                fn()
                _state["engine"], _state["ok"] = name, True
                break
            except Exception as e:                  # không phải macOS / thiếu pyobjc / chưa cài rapidocr…
                errs.append("%s — %s: %s" % ({"vision": "Apple Vision", "rapid": "RapidOCR"}[name], type(e).__name__, e))
        if not _state["ok"]:
            _state["error"] = "; ".join(errs)
            _state["retry_at"] = time.time() + RETRY_SECS
        return _state["ok"]
    finally:
        _lock.release()


def available() -> bool:
    return _load()


def usable_tesseract(mod):
    """`mod` (gói pytesseract) nếu CHẠY được chương trình tesseract, không thì None. Có gói pip mà không có chương trình (Windows sau
    setup.bat — tesseract là tuỳ chọn) thì mọi lần gọi ném TesseractNotFoundError → đọc màn hình hỏng dù bộ đọc chính đọc đúng."""
    if mod is None:
        return None
    try:
        mod.get_tesseract_version()
        return mod
    except Exception:
        return None


def engine() -> str:
    """Bộ đọc đang dùng: "vision" | "rapid" | "" (không có)."""
    _load()
    return _state["engine"]


def engine_name() -> str:
    return {"vision": "Apple Vision", "rapid": "RapidOCR"}.get(engine(), "không có")


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
_CACHE_MAX = 12
_cache_lock = threading.Lock()


def _cached(tag, img, correct, fn):
    """Kết quả `fn(img, correct)` có nhớ theo NỘI DUNG ảnh (một lần nhìn thường đọc chữ nhiều lần trên cùng một ảnh: read_text rồi find_text
    cho từng chữ cần bấm, xét chiều ảnh…). Kết quả trả ra là CHUNG giữa các lần gọi: chỉ đọc, không sửa. Rỗng thì không nhớ (bộ đọc có
    thể trục trặc nhất thời — lần sau đọc lại)."""
    try:
        import zlib
        key = (tag, _state["engine"], zlib.crc32(img.tobytes()), img.shape, bool(correct))
    except Exception:
        return fn(img, correct)
    with _cache_lock:
        for k, rows in _CACHE:
            if k == key:
                return rows
    rows = fn(img, correct)
    if not rows:
        return rows
    with _cache_lock:
        _CACHE.append((key, rows))
        del _CACHE[:-_CACHE_MAX]
    return rows


def _observe(img, correct=False):
    """Các dòng chữ của ảnh (xem _observe_once), có nhớ theo nội dung ảnh."""
    return _cached("read", img, correct, _observe_once)


def _raw_cached(img, correct=False):
    """Đọc THÔ (không tự xoay) bằng bộ đọc đang dùng, có nhớ theo nội dung ảnh."""
    return _cached("raw", img, correct, _observe_raw)


def _rotate(img, k):
    import cv2
    k %= 4
    return img if not k else cv2.rotate(img, (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)[k - 1])


def _observe_once(img, correct=False):
    """Các dòng chữ của ảnh, theo thứ tự đọc. Ảnh chụp có lúc bị XOAY so với giao diện (đo trên iPhone 8: trang đăng nhập web mở từ game
    đang ngang trả về khung dọc 750×1334 với nội dung nằm nghiêng — chữ nằm dọc, bộ đọc đọc sót / sai, «Tiếp tục» không tìm thấy) → khi
    phần lớn chữ nằm dọc thì đọc trên bản đã xoay thẳng (thử cả hai chiều, lấy chiều có nhiều chữ nằm ngang ĐỌC XUÔI nhất — xem _orient)
    rồi đổi hộp về ảnh GỐC — toạ độ trả ra vẫn là toạ độ của ảnh chụp như bên gọi thấy (con trỏ bấm theo đúng ảnh đó)."""
    rows = _raw_cached(img, correct)
    if not rows or not _sideways(rows):
        return rows
    H, W = img.shape[:2]

    def score(rs):
        return sum(len(r["text"]) for r in rs if (r["box"][2] - r["box"][0]) >= (r["box"][3] - r["box"][1]))
    best, best_rot, best_key = None, None, None
    for rot, k in (("cw", 1), ("ccw", 3)):
        rs = _raw_cached(_rotate(img, k), correct)
        o = _orient(rs)
        key = (o["fw"] - o["bk"], score(rs))
        if best is None or key > best_key:
            best, best_rot, best_key = rs, rot, key
    if not best or best_key[0] < 0 or score(best) <= score(rows):        # chiều = 0: không đo được chiều (dòng quá ngắn) → theo số chữ
        return rows
    out = []
    for r in best:                  # bản SAO: các dòng đọc thô của ảnh xoay đang được nhớ chung — không sửa chúng
        r = dict(r)
        r["rot"], r["W"], r["H"] = best_rot, W, H
        r["box"] = _unrotate_box(r["box"], best_rot, W, H)
        out.append(r)
    return out                      # GIỮ thứ tự đọc của bản xoay thẳng (xếp lại theo toạ độ ảnh gốc là đọc theo cột → xáo dòng)


def _direction(r) -> int:
    """Chiều đọc của một dòng trên khung của chính ảnh đã đọc ra nó: +1 xuôi (ký tự đầu nằm BÊN TRÁI ký tự cuối), -1 ngược (Vision đọc được
    cả chữ LỘN NGƯỢC 180° — ra đúng chữ nhưng ký tự đầu nằm bên phải), 0 không biết (hộp trùng nhau — đo thật: dòng một từ, Vision trả
    hộp cả TỪ cho từng ký tự)."""
    raw = r.get("raw") or ""
    a, b = _range_box(r, 0, 1), _range_box(r, len(raw) - 1, len(raw))
    if not (a and b):
        return 0
    d = (b[0] + b[2]) - (a[0] + a[2])
    return 0 if abs(d) <= 8 else (1 if d > 0 else -1)


def _orient(rows) -> dict:
    """Thống kê chiều chữ của một lần đọc, tính theo DIỆN TÍCH hộp chữ (chữ to — tiêu đề, nút — nặng hơn chữ nhỏ: đo thật trên màn
    «Welcome Login Bonus», tên cầu thủ in DỌC trên các thẻ làm phép đếm theo số dòng tưởng ảnh xoay 90° là thẳng):
    hz / vt = diện tích chữ nằm ngang / nằm dọc; fw / bk = diện tích chữ nằm ngang đọc xuôi / ngược; chars = số ký tự đã xét.
    RapidOCR: bỏ dòng độ tin < 0,8 (chữ lộn ngược / xoay sai nó đọc ra rác với độ tin thấp)."""
    o = {"hz": 0.0, "vt": 0.0, "fw": 0.0, "bk": 0.0, "chars": 0}
    for r in rows:
        n = len((r.get("raw") or "").replace(" ", ""))
        if n < 3 or (r.get("cand") is None and r.get("conf", 0) < 0.8):
            continue
        x0, y0, x1, y1 = r["box"]
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        area = float(w * h)
        o["chars"] += n
        if h > 1.3 * w:
            o["vt"] += area
            continue
        o["hz"] += area
        d = _direction(r)
        if d > 0:
            o["fw"] += area
        elif d < 0:
            o["bk"] += area
    return o


def _det_boxes(img, correct=False):
    with _rapid_lock:
        res = _state["rapid"](img, use_det=True, use_cls=False, use_rec=False, return_word_box=False)
    b = getattr(res, "boxes", None)
    return [] if b is None else list(b)


def _text_boxes(img, rows) -> int:
    """Số khung chữ trên ảnh. RapidOCR: chỉ chạy bước DÒ khung (~0,2 s, không đọc) — chữ xoay sai chiều nó đọc ra rác rồi lọc bỏ hết (đo
    thật: 11 khung mà chỉ giữ lại 2 dòng), nhìn số dòng đọc được thì tưởng màn hình không có chữ. Vision đọc được chữ mọi chiều → đếm dòng."""
    if _state["engine"] == "rapid":
        try:
            return len(_cached("det", img, False, _det_boxes))
        except Exception:
            return 0
    return sum(1 for r in rows if len((r.get("raw") or "").replace(" ", "")) >= 3)


def upright_turn(img):
    """Ảnh `img` phải QUAY bao nhiêu thì chữ trên đó nằm thẳng: số lần quay 90° THEO chiều kim đồng hồ (0 = đã thẳng, 1, 2 = lộn ngược,
    3 = quay ngược chiều 90°). None = chưa biết (ít chữ — màn hình tải, logo; không hướng nào thắng rõ ràng — vd màn hình chỉ có dòng một
    từ: chiều đọc không đo được, đoán bừa là có thể ra ảnh LỘN NGƯỢC (verify vòng 30: hộp thoại «Cancel / Open»)).
    Ảnh đưa vào có phần lớn diện tích chữ nằm ngang → so với bản xoay 180°: chữ «ngang + xuôi» gấp ≥ 3 lần bản kia → 0 (đọc thêm đúng một
    lần; lần đọc ảnh đưa vào dùng chung với read_text / find_text trên cùng ảnh). Không rõ → đọc cả 4 hướng, chọn hướng có diện tích chữ
    «ngang + xuôi» lớn nhất, phải hơn hướng nhì ≥ 1,5 lần."""
    rows = _raw_cached(img)
    o = _orient(rows)
    if o["chars"] < 6 and _text_boxes(img, rows) < 3:
        return None                 # gần như không có khung chữ nào (màn hình tải, logo) — có khung mà đọc ra rác thì vẫn thử các hướng
    seen = {0: o}

    def at(k):
        if k not in seen:
            seen[k] = _orient(_raw_cached(_rotate(img, k)))
        return seen[k]
    if o["hz"] >= 1.5 * o["vt"]:
        # Ngang. Xuôi hay lộn ngược? So luôn với bản xoay 180°: RapidOCR đọc chữ lộn ngược ra vài dòng RÁC ngắn mà độ tin vẫn cao
        # (đo thật: «dous», «000'0L») nên chỉ nhìn chiều ký tự của một bản là chưa đủ; Vision thì bản lộn ngược đọc ra chữ «ngược».
        up, down = o["fw"] - o["bk"], at(2)["fw"] - at(2)["bk"]
        if up > 0 and up >= 3 * max(down, 0.0):
            return 0
        if down > 0 and down >= 3 * max(up, 0.0) and at(2)["hz"] >= 1.5 * at(2)["vt"]:
            return 2
    scores = {}
    for k in range(4):
        ok = at(k)
        scores[k] = (ok["fw"] - ok["bk"]) if ok["hz"] >= 1.5 * ok["vt"] else 0.0
    (k1, s1), (_, s2) = sorted(scores.items(), key=lambda t: -t[1])[:2]
    if s1 <= 0 or s1 < 1.5 * max(s2, 0.0):
        return None
    return k1


def _observe_raw(img, correct=False):
    """Đọc chữ ảnh BGR (numpy) bằng bộ đọc đang dùng. Trả các dòng {text, raw, conf, box (x0, y0, x1, y1) pixel, …} theo thứ tự đọc."""
    if not _load() or img is None:
        return []
    return _rapid_raw(img) if _state["engine"] == "rapid" else _vision_raw(img, correct)


def _quad_box(q, w, h):
    xs, ys = [float(p[0]) for p in q], [float(p[1]) for p in q]
    return (max(0, int(min(xs))), max(0, int(min(ys))), min(w, int(round(max(xs)))), min(h, int(round(max(ys)))))


def _rapid_raw(img):
    """RapidOCR: mỗi dòng kèm hộp của TỪNG ký tự (`cboxes`, theo thứ tự các ký tự không phải khoảng trắng của dòng) — để lấy hộp của riêng
    phần chữ khớp (bấm «Login» trong một dòng dài) và để đo chiều chữ (_forward). Không dùng bộ phân loại «chữ lộn ngược» của RapidOCR
    (use_cls=False): chữ lộn ngược thì đọc ra rác với độ tin thấp — chính dấu hiệu đó giúp chọn đúng chiều khi ảnh bị xoay."""
    h, w = img.shape[:2]
    if h < 4 or w < 4:
        return []
    with _rapid_lock:
        # truyền ĐỦ các thiết lập mỗi lần gọi: RapidOCR 3.x NHỚ thiết lập của lần gọi trước (đo thật: sau một lần «chỉ dò khung»
        # use_rec=False, các lần đọc sau không truyền use_rec thì không đọc chữ nữa — mọi ảnh ra rỗng)
        res = _state["rapid"](img, use_det=True, use_cls=False, use_rec=True, return_word_box=True)
    boxes, txts, scores = getattr(res, "boxes", None), getattr(res, "txts", None), getattr(res, "scores", None)
    words = getattr(res, "word_results", None) or ()
    if boxes is None or not txts:
        return []
    out = []
    for i, (quad, txt, conf) in enumerate(zip(boxes, txts, scores)):
        raw = str(txt or "")
        if not raw.strip():
            continue
        cboxes = None                                 # hộp cho TỪNG ký tự không phải khoảng trắng (mỗi ký tự lấy hộp của từ chứa nó)
        pieces = [(str(wd[0]), wd[2]) for wd in (words[i] if i < len(words) and words[i] else ()) if len(wd) >= 3]
        flat = [ch for ch in raw if not ch.isspace()]
        if pieces and sum(len(p.replace(" ", "")) for p, _ in pieces) == len(flat):
            cboxes = []
            for p, q in pieces:
                cboxes += [_quad_box(q, w, h)] * len(p.replace(" ", ""))
        out.append({"text": raw.strip(), "raw": raw, "conf": float(conf), "box": _quad_box(quad, w, h), "cboxes": cboxes, "w": w, "h": h})
    return _reading_order(out)


def _vision_raw(img, correct=False):
    """Chạy Vision. `correct=False`: KHÔNG cho Vision «sửa chính tả theo ngôn ngữ» — ta cần đúng những gì đang hiện trên màn (kiểm bàn
    phím gõ chuỗi vô nghĩa, đọc mã, đọc số tiền…), và việc so khớp phía trên vốn đã không phân biệt dấu / hoa thường."""
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
    """Các DÒNG chữ trên ảnh: [{text, x, y, w, h, conf}] — (x, y) là tâm dòng chữ, pixel ảnh gốc. Không có bộ đọc chữ → []."""
    out = []
    for r in _observe(img):
        if r["conf"] < min_conf:
            continue
        x0, y0, x1, y1 = r["box"]
        out.append({"text": r["text"], "x": (x0 + x1) // 2, "y": (y0 + y1) // 2, "w": x1 - x0, "h": y1 - y0, "conf": round(r["conf"], 2)})
    return out


def text(img) -> str:
    """Toàn bộ chữ đọc được, mỗi dòng một hàng. Không có bộ đọc chữ → ''."""
    return "\n".join(r["text"] for r in _observe(img))


def find(img, needle: str):
    """Tâm (cx, cy) của ĐÚNG phần chữ khớp `needle` (không phân biệt hoa thường, dấu, khoảng trắng). Không thấy / không có bộ đọc chữ → None.
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
    """Hộp (pixel, trên ảnh mà bên gọi đưa vào) của raw[start:end] trong dòng `r`, hoặc None."""
    try:
        box = _vision_range(r, start, end) if r.get("cand") is not None else _rapid_range(r, start, end)
        if box is None:
            return None
        return _unrotate_box(box, r["rot"], r["W"], r["H"]) if r.get("rot") else box
    except Exception:
        return None


def _vision_range(r, start, end):
    raw = r["raw"]
    u0 = len(raw[:start].encode("utf-16-le")) // 2        # NSRange tính theo đơn vị UTF-16
    ulen = len(raw[start:end].encode("utf-16-le")) // 2
    with _state["ns"]["objc"].autorelease_pool():
        res = r["cand"].boundingBoxForRange_error_((u0, ulen), None)
        obs = res[0] if isinstance(res, tuple) else res
        if obs is None:
            return None
        return _to_px(obs.boundingBox(), r["w"], r["h"])


def _rapid_range(r, start, end):
    """Hộp hợp của các ký tự raw[start:end] từ hộp từng ký tự của RapidOCR; không có thì chia đều theo số ký tự dọc chiều dài dòng."""
    raw, cb = r["raw"], r.get("cboxes")
    if cb:
        k, picked = 0, []
        for i, ch in enumerate(raw):
            if ch.isspace():
                continue
            if start <= i < end:
                picked.append(cb[k])
            k += 1
        if not picked:
            return None
        return (min(b[0] for b in picked), min(b[1] for b in picked), max(b[2] for b in picked), max(b[3] for b in picked))
    x0, y0, x1, y1 = r["box"]
    n = max(1, len(raw))
    if (x1 - x0) >= (y1 - y0):
        return (int(x0 + (x1 - x0) * start / n), y0, int(x0 + (x1 - x0) * end / n), y1)
    return (x0, int(y0 + (y1 - y0) * start / n), x1, int(y0 + (y1 - y0) * end / n))
