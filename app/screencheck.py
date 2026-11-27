#!/usr/bin/env python3
"""
screencheck.py — ẢNH MẪU của một bước và phép so «màn hình bây giờ có phải màn hình của bước này không».

Ảnh mẫu (trường `screen` của bước, lưu ngay trong kịch bản):
  {"v": 1, "img": "<JPEG base64, cạnh dài SHOT_SIDE px>", "texts": ["shop", "product details", …], "w": 1334, "h": 750}
  • `img`  : ảnh thu nhỏ của màn hình NGAY TRƯỚC khi bước được làm (chụp lúc «Chạy thử» bước đó thành công, hoặc bấm «Chụp ảnh mẫu»);
  • `texts`: các dòng chữ đọc được trên màn hình đó, đã chuẩn hoá (bỏ dấu, chữ thường, chữ số → «9»), bỏ dòng toàn số / quá ngắn.

So khớp (score): game có nhiều hình động (thẻ cầu thủ, nền chuyển màu, đồng hồ đếm) nên so CHỮ là chính: tỉ lệ dòng chữ của ảnh mẫu
còn thấy trên màn hình bây giờ. Màn hình gần như không có chữ (< MIN_TEXTS dòng) thì so HÌNH (độ tương quan của ảnh xám thu nhỏ).
"""
from __future__ import annotations
import base64, re

import cv2
import numpy as np

from eyes import norm_text

SHOT_SIDE = 480          # cạnh dài của ảnh mẫu lưu trong kịch bản (đủ để người xem nhận ra màn hình, ~20–40 KB)
SHOT_QUALITY = 70
MIN_LEN = 3              # dòng chữ ngắn hơn (sau chuẩn hoá) không dùng để so: «OK», «x», số trang… quá dễ trùng
MIN_TEXTS = 3            # ảnh mẫu có ít hơn chừng này dòng chữ dùng được → so bằng hình
TEXT_PASS = 0.6          # tỉ lệ dòng chữ của ảnh mẫu phải còn thấy để coi là khớp
IMAGE_PASS = 0.7         # độ tương quan ảnh xám tối thiểu khi so bằng hình
CMP_SIDE = 96            # cạnh dài của ảnh xám dùng để so hình
TEXTS_MAX = 40
# Bước nào được kiểm màn hình trước khi làm: các bước THAO TÁC lên máy. Không kiểm: bước tự chờ / tự xử lý thứ lúc có lúc không
# (tap_if, wait_text, assert_text), bước không cần màn hình cụ thể (launch, home, wait).
CHECK_TYPES = ("tap", "tap_text", "tap_image", "hold", "hold_text", "type", "key", "combo", "swipe")
_NUM = re.compile(r"^[\d\s.,:;/'%+\-xX×]*$")
# email, mã / tên người chơi, số dài (OTP, số tài khoản), số điện thoại viết cách: không lưu vào ảnh mẫu
_PRIVATE = re.compile(r"@|\b(user\s*id|id\s*:|(user\s*|player\s*)?name\s*:?\s*\S|ten\s*:)|\d{5,}|\d[\d .\-]{6,}\d", re.I)


def text_key(s) -> str:
    """Dạng chuẩn của một dòng chữ để so: bỏ dấu, chữ thường, mọi chữ số thành «9» (số xu, giờ, số lượng đổi liên tục)."""
    return re.sub(r"\d", "9", norm_text(s))


def usable(line) -> bool:
    t = norm_text(line)
    return len(t.replace(" ", "")) >= MIN_LEN and not _NUM.match(t) and not _PRIVATE.search(t)


def ref_texts(lines) -> list:
    """Các dòng chữ của ảnh mẫu (không trùng, giữ thứ tự). `lines`: [{text,…}] hoặc [str]."""
    out = []
    for ln in lines or []:
        t = ln.get("text") if isinstance(ln, dict) else ln
        if usable(t):
            k = text_key(t)
            if k not in out:
                out.append(k)
    return out[:TEXTS_MAX]


def capture(img, lines, again=None) -> dict:
    """Ảnh mẫu từ ảnh chụp `img` (BGR, đã quay thẳng) + các dòng chữ đọc được trên nó. `again`: các dòng đọc được ở MỘT LẦN ĐỌC NỮA
    (ảnh chụp sau đó một chút) — chỉ giữ chữ thấy ở CẢ HAI lần: chữ rác của logo cách điệu / hình động mỗi lần đọc ra một kiểu
    (đo trên màn tiêu đề eFootball: «fotbal», «apotb-l», «setbe-lam»…) sẽ bị bỏ, không làm tụt điểm so khớp về sau."""
    texts = ref_texts(lines)
    if again is not None:
        other = ref_texts(again)
        texts = [t for t in texts if t in other]
    h, w = img.shape[:2]
    k = SHOT_SIDE / float(max(h, w))
    small = cv2.resize(img, (max(1, int(round(w * k))), max(1, int(round(h * k)))), interpolation=cv2.INTER_AREA) if k < 1 else img
    good, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, SHOT_QUALITY])
    return {"v": 1, "img": base64.b64encode(buf.tobytes()).decode("ascii") if good else "", "texts": texts, "w": int(w), "h": int(h)}


def valid(ref) -> bool:
    return isinstance(ref, dict) and (bool(ref.get("img")) or bool(ref.get("texts")))


def ref_image(ref):
    """Ảnh (BGR) của ảnh mẫu, hoặc None nếu không đọc được."""
    try:
        raw = base64.b64decode(str(ref.get("img") or ""), validate=False)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        return img if img is not None and img.size else None
    except Exception:
        return None


def _gray(img, size):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.GaussianBlur(cv2.resize(g, size, interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)


def image_score(ref, img) -> float:
    """Độ tương quan (−1…1) giữa ảnh xám thu nhỏ của ảnh mẫu và của màn hình bây giờ. Khác chiều (dọc / ngang) → 0."""
    pic = ref_image(ref)
    if pic is None or img is None:
        return 0.0
    rh, rw = pic.shape[:2]
    h, w = img.shape[:2]
    if (rw >= rh) != (w >= h):
        return 0.0
    k = CMP_SIDE / float(max(rw, rh))
    size = (max(8, int(round(rw * k))), max(8, int(round(rh * k))))
    a, b = _gray(pic, size), _gray(img, size)
    a, b = a - a.mean(), b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 0.0


def text_score(ref, lines):
    """(tỉ lệ dòng chữ của ảnh mẫu còn thấy, số dòng dùng để so). Dòng mẫu «thấy» khi nằm trong một dòng bây giờ hoặc ngược lại
    (OCR hay tách / gộp dòng)."""
    texts = [t for t in (ref.get("texts") or []) if isinstance(t, str) and len(t.replace(" ", "")) >= MIN_LEN]
    if not texts:
        return 0.0, 0
    now = [text_key(ln.get("text") if isinstance(ln, dict) else ln) for ln in lines or []]
    now = [n for n in now if n]
    flat = " ".join(now).replace(" ", "")
    # Dòng bây giờ nằm TRONG dòng mẫu (OCR tách dòng) chỉ tính khi nó là chữ thật và dài ít nhất 60% dòng mẫu — một con số lẻ («120» →
    # «999») hay một chữ ngắn không được «khớp» mọi dòng mẫu có chứa nó (verify: màn quảng cáo «Ad / Install / 120» từng đạt 75%).
    parts = [n.replace(" ", "") for n in now if usable(n)]
    hit = 0
    for t in texts:
        tt = t.replace(" ", "")
        if tt in flat or any(len(n) >= max(MIN_LEN, 0.6 * len(tt)) and n in tt for n in parts):
            hit += 1
    return hit / float(len(texts)), len(texts)


def score(ref, img, lines) -> dict:
    """{"ok": khớp?, "how": "chữ" | "hình", "text": tỉ lệ chữ, "n": số dòng mẫu, "image": độ tương quan}."""
    ts, n = text_score(ref, lines)
    ims = image_score(ref, img)
    if n >= MIN_TEXTS:
        return {"ok": ts >= TEXT_PASS, "how": "chữ", "text": round(ts, 2), "n": n, "image": round(ims, 2)}
    return {"ok": ims >= IMAGE_PASS, "how": "hình", "text": round(ts, 2), "n": n, "image": round(ims, 2)}


def describe(sc) -> str:
    if sc["how"] == "chữ":
        return "màn hình khác ảnh mẫu của bước (chỉ thấy %d%% chữ của ảnh mẫu, cần %d%%)" % (sc["text"] * 100, TEXT_PASS * 100)
    return "màn hình khác ảnh mẫu của bước (giống %d%% theo hình, cần %d%%)" % (max(0.0, sc["image"]) * 100, IMAGE_PASS * 100)


def wants_check(step) -> bool:
    """Bước này có cần kiểm màn hình trước khi làm không: là bước thao tác, có ảnh mẫu, và người viết không tắt (`screen_check: false`)."""
    return (isinstance(step, dict) and step.get("type") in CHECK_TYPES and valid(step.get("screen"))
            and step.get("screen_check") is not False)
