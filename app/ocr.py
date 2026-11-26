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


def _norm(s) -> str:
    """Cùng cách chuẩn hoá với eyes.norm_text: chữ thường, bỏ dấu tiếng Việt (đ→d), gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(s.replace("đ", "d").split())


def _observe(img, correct=False):
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
    """Tâm (cx, cy) của ĐÚNG phần chữ khớp `needle` (không phân biệt hoa thường, dấu, khoảng trắng) — dòng đầu tiên theo thứ tự đọc.
    Không thấy / không có Vision → None."""
    nd = _norm(needle).replace(" ", "")
    if not nd:
        return None
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
        return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    return None


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
            return _to_px(obs.boundingBox(), r["w"], r["h"])
    except Exception:
        return None
