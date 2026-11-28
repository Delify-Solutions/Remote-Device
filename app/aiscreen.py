#!/usr/bin/env python3
"""
aiscreen.py — hỏi AI về MÀN HÌNH LẠ (màn hình khác ảnh mẫu của bước sắp làm): có phải quảng cáo / hộp thông báo che màn hình không, nút
nào đóng / bỏ qua được. Tool bấm nút đó (bằng phép đưa con trỏ có đo như mọi cú bấm), rồi so lại với ảnh mẫu. Không xử lý được → bên gọi
TẠM DỪNG máy chờ admin (xem runner._screen_helper).

Cấu hình (app/data/settings.json — không vào git):
  ai_provider   "anthropic" | "openai"          (openai cũng dùng cho máy chủ TƯƠNG THÍCH OpenAI qua ai_base_url)
  ai_model      tên model (mặc định: claude-opus-5-5 / gpt-5)
  ai_key        API key
  ai_base_url   địa chỉ máy chủ riêng (tuỳ chọn)
  ai_screen     False = tắt (mặc định bật khi đã có key)

AI chỉ được làm MỘT việc: chỉ nút đóng / bỏ qua của quảng cáo, hộp thông báo, màn hình chờ. Không bao giờ được «cho qua» một màn hình vẫn
khác ảnh mẫu — chỉ màn hình KHỚP ảnh mẫu sau khi bấm mới được làm tiếp bước.
"""
from __future__ import annotations
import base64, json, re, threading, time

import cv2

DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "openai": "gpt-5"}
TRIES = 3                 # số lần hỏi AI + bấm tối đa cho một màn hình lạ
AFTER_TAP = 2.0           # nghỉ sau khi bấm nút AI chỉ rồi mới so lại (hộp thoại đóng, màn hình bên dưới hiện ra)
LOADING_WAIT = 4.0        # AI nói «đang tải / đang chuyển màn» → chờ chừng này rồi so lại
SEND_SIDE = 1280          # cạnh dài của ảnh gửi cho AI (đủ đọc chữ nút nhỏ, ít tốn token)
TIMEOUT = 45.0            # giây mỗi lần gọi (SDK thử lại tối đa 1 lần); «Dừng ngay» không phải chờ hết — xem _call
MIN_CONF = 0.6            # AI chắc dưới mức này → không bấm
NEAR = 60                 # chữ của nút (bộ đọc chữ) chỉ được dùng thay toạ độ AI khi cách toạ độ đó ≤ max(NEAR px, 6% cạnh dài)
# Nút / chữ quanh chỗ bấm có các từ này thì KHÔNG bấm (dù AI chọn): mua, thanh toán, xác nhận, đăng nhập, cài, mở cửa hàng… — lời dặn trong
# câu hỏi chưa đủ (chữ trên màn hình có thể «dụ» AI), phải chặn ở đây.
DENY = ("buy", "mua", "purchase", "pay", "payment", "thanh toan", "confirm", "xac nhan", "subscribe", "dang ky", "install", "cai dat",
        "get", "open", "mo ", "nap", "top up", "topup", "accept", "dong y", "agree", "sign in", "sign up", "log in", "login", "dang nhap",
        "store", "app store", "download", "tai ve", "upgrade", "claim", "redeem", "order", "dat hang", "checkout", "price", "gia ",
        "watch", "xem quang cao", "play", "choi")
KINDS = ("ad", "popup", "loading", "expected", "other")
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1", "claude-opus-5")

SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "close_label": {"type": "string"},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["kind", "close_label", "x", "y", "confidence", "reason"],
    "additionalProperties": False,
}

PROMPT = """You are helping an automation tool that drives a real iPhone (a mobile game / app) step by step.
Before doing the next step, the tool compared the CURRENT screen with the REFERENCE screen recorded for that step, and they differ.

Next step the tool wants to do: {step}
Why the tool thinks the screen differs: {why}

Image 1 is the CURRENT screen ({w}x{h} pixels). Image 2 is the REFERENCE screen the step expects.

Decide what the CURRENT screen is:
- "ad": an advertisement / promotion / offer overlay covering the expected screen.
- "popup": a dialog, notice, reward, news, rating prompt or similar overlay that can be dismissed.
- "loading": a loading / transition / splash screen that will go away by itself.
- "expected": actually the same screen as the reference (only minor differences).
- "other": anything else (a different screen, an error, a login problem, a purchase / payment sheet, anything you are unsure about).

If it is "ad" or "popup", give the ONE control that closes, skips or dismisses it WITHOUT accepting, buying, subscribing or opening
anything ("X", "Close", "Skip", "Later", "No thanks", "Don't show", "Đóng", "Bỏ qua", "Để sau"...). Never choose a button that buys,
pays, confirms a purchase, signs in, accepts an offer or opens a store / link. If no such safe control is clearly visible, use "other".
- close_label: the exact text written on that control, or "" if it is an icon without text (like an X).
- x, y: the CENTER of that control in Image 1 pixel coordinates (0,0 = top-left). Use -1, -1 when not giving a control.
- confidence: 0.0-1.0, how sure you are about kind and control.
- reason: one short sentence, in Vietnamese, describing what is on the screen.
Reply with the JSON object only."""


class AIError(Exception):
    pass


def providers(settings: dict) -> dict:
    """Cấu hình RIÊNG của từng nhà cung cấp: {"anthropic": {key, model, base_url}, "openai": {…}} — mỗi nhà cung cấp giữ key của nó, đổi qua
    lại không phải nhập lại. Cấu hình kiểu cũ (một bộ ai_key / ai_model / ai_base_url) được coi là của nhà cung cấp `ai_provider`."""
    s = settings or {}
    raw = s.get("ai_providers") if isinstance(s.get("ai_providers"), dict) else {}
    out = {}
    for p in DEFAULT_MODEL:
        e = raw.get(p) if isinstance(raw.get(p), dict) else {}
        out[p] = {"key": str(e.get("key") or "").strip(), "model": str(e.get("model") or "").strip(),
                  "base_url": str(e.get("base_url") or "").strip().rstrip("/")}
    old = str(s.get("ai_provider") or "anthropic").strip().lower()
    if old in out and not raw.get(old) and (s.get("ai_key") or s.get("ai_model") or s.get("ai_base_url")):
        out[old] = {"key": str(s.get("ai_key") or "").strip(), "model": str(s.get("ai_model") or "").strip(),
                    "base_url": str(s.get("ai_base_url") or "").strip().rstrip("/")}
    return out


def config(settings: dict) -> dict:
    """Cấu hình của nhà cung cấp ĐANG DÙNG (`ai_provider`)."""
    s = settings or {}
    prov = str(s.get("ai_provider") or "anthropic").strip().lower()
    if prov not in DEFAULT_MODEL:
        prov = "anthropic"
    e = providers(s)[prov]
    return {"provider": prov, "model": e["model"] or DEFAULT_MODEL[prov], "key": e["key"], "base_url": e["base_url"],
            "enabled": s.get("ai_screen", True) is not False}


def usable(cfg) -> bool:
    return bool(cfg["enabled"] and (cfg["key"] or (cfg["provider"] == "openai" and cfg["base_url"])))


def _jpeg(img, side=SEND_SIDE):
    h, w = img.shape[:2]
    k = min(1.0, side / float(max(h, w)))
    small = cv2.resize(img, (max(1, int(round(w * k))), max(1, int(round(h * k)))), interpolation=cv2.INTER_AREA) if k < 1 else img
    good, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not good:
        raise AIError("không mã hoá được ảnh màn hình")
    return base64.b64encode(buf.tobytes()).decode("ascii"), k, small.shape[1], small.shape[0]


def parse(text) -> dict:
    """Đọc câu trả lời JSON của AI (chịu được chữ thừa / ```json```). Sai dạng → kind "other" (không bấm gì)."""
    raw = str(text or "")
    m = re.search(r"\{.*\}", raw, re.S)
    bad = {"kind": "other", "close_label": "", "x": -1, "y": -1, "confidence": 0.0, "reason": "AI trả lời sai dạng"}
    try:
        d = json.loads(m.group(0) if m else raw)
    except Exception:
        return bad
    if not isinstance(d, dict):
        return bad
    kind = str(d.get("kind") or "other").lower()
    try:
        x, y = int(d.get("x", -1)), int(d.get("y", -1))
    except (TypeError, ValueError, OverflowError):
        x = y = -1
    if x < 0 or y < 0:                               # thiếu một trong hai toạ độ = không có toạ độ (không bấm ở «x, -1»)
        x = y = -1
    try:
        conf = float(d.get("confidence") or 0)
        conf = max(0.0, min(1.0, conf)) if conf == conf else 0.0
    except (TypeError, ValueError, OverflowError):
        conf = 0.0
    return {"kind": kind if kind in KINDS else "other", "close_label": str(d.get("close_label") or "").strip()[:60],
            "x": x, "y": y, "confidence": conf, "reason": str(d.get("reason") or "").strip()[:300]}


def _ask_anthropic(cfg, prompt, cur_b64, ref_b64):
    try:
        import anthropic
    except ImportError:
        raise AIError("máy chưa cài gói anthropic (pip install anthropic)")
    kw = {"api_key": cfg["key"], "timeout": TIMEOUT, "max_retries": 1}
    if cfg["base_url"]:
        kw["base_url"] = cfg["base_url"]
    client = anthropic.Anthropic(**kw)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": cur_b64}}]
    if ref_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": ref_b64}})
    content.append({"type": "text", "text": prompt})
    req = {"model": cfg["model"], "max_tokens": 8000, "messages": [{"role": "user", "content": content}]}
    structured = {"format": {"type": "json_schema", "schema": SCHEMA}}
    try:
        if cfg["model"] in _FALLBACK_MODELS:
            # Bộ lọc an toàn của model có thể từ chối nhầm: cho máy chủ tự chạy lại trên model dự phòng (fallbacks «default»).
            msg = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", output_config=structured, **req)
        else:
            msg = client.messages.create(output_config=structured, **req)
    except anthropic.BadRequestError as e:
        # model / máy chủ riêng không hỗ trợ JSON theo khuôn hay fallback → hỏi lại kiểu thường (vẫn đọc JSON trong câu trả lời).
        # Chỉ hai lý do này (lỗi ảnh, lỗi khác thì không hỏi lại — mỗi lần hỏi đều tốn tiền).
        if "output_config" not in str(e) and "fallback" not in str(e):
            raise AIError("Anthropic từ chối yêu cầu: %s" % getattr(e, "message", e))
        try:
            msg = client.messages.create(**req)
        except anthropic.APIStatusError as e2:
            raise AIError("Anthropic báo lỗi %s" % e2.status_code)
        except anthropic.APIConnectionError:
            raise AIError("không kết nối được tới Anthropic")
    except anthropic.AuthenticationError:
        raise AIError("API key của Anthropic không đúng")
    except anthropic.APIConnectionError:
        raise AIError("không kết nối được tới Anthropic")
    except anthropic.APIStatusError as e:
        raise AIError("Anthropic báo lỗi %s" % e.status_code)
    if getattr(msg, "stop_reason", None) == "refusal":
        return '{"kind": "other", "reason": "AI từ chối trả lời"}'
    return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


def _ask_openai(cfg, prompt, cur_b64, ref_b64):
    try:
        import openai
    except ImportError:
        raise AIError("máy chưa cài gói openai (pip install openai)")
    kw = {"api_key": cfg["key"] or "none", "timeout": TIMEOUT, "max_retries": 1}
    if cfg["base_url"]:
        kw["base_url"] = cfg["base_url"]
    client = openai.OpenAI(**kw)
    content = [{"type": "text", "text": prompt},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + cur_b64}}]
    if ref_b64:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + ref_b64}})
    req = {"model": cfg["model"], "messages": [{"role": "user", "content": content}]}
    try:
        try:
            r = client.chat.completions.create(response_format={"type": "json_object"}, **req)
        except openai.BadRequestError as e:
            if "response_format" not in str(e):
                raise
            r = client.chat.completions.create(**req)           # máy chủ tương thích không hỗ trợ json_object
    except openai.AuthenticationError:
        raise AIError("API key của OpenAI không đúng")
    except openai.APIConnectionError:
        raise AIError("không kết nối được tới máy chủ AI")
    except openai.APIStatusError as e:
        raise AIError("máy chủ AI báo lỗi %s" % e.status_code)
    return (r.choices[0].message.content or "") if r.choices else ""


def ask(cfg, img, ref_img, step_text, why):
    """Hỏi AI một lần. Trả dict (xem parse) với x, y đã đổi về toạ độ ẢNH CHỤP gốc."""
    cur_b64, k, w, h = _jpeg(img)
    ref_b64 = _jpeg(ref_img, 640)[0] if ref_img is not None else ""
    prompt = PROMPT.format(step=step_text, why=why, w=w, h=h)
    text = (_ask_anthropic if cfg["provider"] == "anthropic" else _ask_openai)(cfg, prompt, cur_b64, ref_b64)
    d = parse(text)
    if d["x"] >= 0 and d["y"] >= 0 and k > 0:
        d["x"], d["y"] = int(round(d["x"] / k)), int(round(d["y"] / k))
        H, W = img.shape[:2]
        if not (0 <= d["x"] < W and 0 <= d["y"] < H):
            d["x"] = d["y"] = -1
    return d


def _norm(t):
    from eyes import norm_text
    return norm_text(t)


def denied(text) -> bool:
    """Chữ này là của nút mua / thanh toán / xác nhận / đăng nhập / cài / mở cửa hàng…? (xem DENY)"""
    t = " %s " % re.sub(r"[^a-z0-9 ]+", " ", _norm(text))
    return any((" %s " % w.strip()) in t if not w.endswith(" ") else (" " + w) in t for w in DENY)


def _lines(nav, img):
    """Các dòng chữ của ảnh, hoặc None khi bộ đọc chữ lỗi (bên gọi không bấm: không kiểm được chữ ngay tại chỗ bấm)."""
    try:
        return nav.e.text_lines(img) or []
    except Exception:
        return None


def pick_target(nav, img, d):
    """Chỗ bấm cho nút đóng AI chỉ: (x, y) hoặc (None, lý do).
    • Có toạ độ AI: đó là MỐC. Chữ của nút (bộ đọc chữ) chỉ được dùng để chỉnh cho trúng khi là NGUYÊN một dòng chữ đúng bằng nhãn AI nói và
      nằm sát mốc — không bao giờ nhảy sang một chữ giống ở chỗ khác (verify: nhãn «X» khớp chữ «x» trong «Extras» ở góc kia màn hình).
    • Không có toạ độ: chỉ bấm khi nhãn là nguyên một dòng chữ và chỉ có ĐÚNG MỘT dòng như thế trên màn hình.
    • Nhãn, hay dòng chữ ngay tại chỗ bấm, là của nút mua / thanh toán / xác nhận / đăng nhập… → không bấm."""
    label = d["close_label"]
    if label and denied(label):
        return None, "AI chọn nút «%s» — nút kiểu này tool không bao giờ bấm tự động" % label
    lines = _lines(nav, img)
    if lines is None:
        return None, "không đọc được chữ trên màn hình để kiểm chỗ bấm — không bấm"
    H, W = img.shape[:2]
    r = max(NEAR, 0.06 * max(H, W))
    same = [ln for ln in lines if label and _norm(ln.get("text")) == _norm(label)] if label else []
    if d["x"] >= 0:
        near = [ln for ln in same if ((ln["x"] - d["x"]) ** 2 + (ln["y"] - d["y"]) ** 2) ** 0.5 <= r]
        pos = min(near, key=lambda ln: (ln["x"] - d["x"]) ** 2 + (ln["y"] - d["y"]) ** 2) if near else None
        if same and not near and len(_norm(label).replace(" ", "")) > 1:
            # AI nói nút có CHỮ «Close» nhưng chữ đó chỉ thấy ở chỗ khác, không ở chỗ AI chỉ → hai thông tin trái nhau, không đoán
            return None, "AI chỉ nút «%s» ở một chỗ nhưng chữ đó lại nằm ở chỗ khác trên màn hình — không bấm" % label
        x, y = (int(pos["x"]), int(pos["y"])) if pos else (d["x"], d["y"])
    elif len(same) == 1:
        x, y = int(same[0]["x"]), int(same[0]["y"])
    else:
        return None, "AI không chỉ ra được chỗ nút đóng (không có toạ độ, chữ «%s» %s)" % (label or "?", "không thấy" if not same else "có nhiều chỗ")
    for ln in lines:                                     # dòng chữ NGAY TẠI chỗ bấm
        if abs(ln["x"] - x) <= ln.get("w", 0) / 2 + 12 and abs(ln["y"] - y) <= ln.get("h", 0) / 2 + 12 and denied(ln.get("text")):
            return None, "chỗ AI chỉ có chữ «%s» — nút kiểu này tool không bao giờ bấm tự động" % ln.get("text")
    return (x, y), ""


def patch_same(a, b, x, y, r=40, limit=30.0) -> bool:
    """Vùng quanh (x, y) của ảnh `b` còn giống ảnh `a` (ảnh AI đã xem)? — để không bấm khi màn hình đã đổi trong lúc đưa con trỏ tới."""
    try:
        if a is None or b is None or a.shape != b.shape:
            return False
        H, W = a.shape[:2]
        x0, y0, x1, y1 = max(0, x - r), max(0, y - r), min(W, x + r), min(H, y + r)
        if x1 <= x0 or y1 <= y0:
            return False
        pa = cv2.cvtColor(a[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype("float32")
        pb = cv2.cvtColor(b[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype("float32")
        return float(abs(pa - pb).mean()) < limit
    except Exception:
        return False


def _call(fn, cancel, poll=0.25):
    """Gọi `fn()` trong luồng phụ, cứ `poll` giây xem `cancel()` — bị dừng thì trả ("cancel", lý do) NGAY, không chờ AI trả lời xong."""
    box = {}

    def run():
        try:
            box["r"] = fn()
        except BaseException as e:
            box["e"] = e
    t = threading.Thread(target=run, name="ai-ask", daemon=True)
    t.start()
    while t.is_alive():
        t.join(poll)
        c = cancel() if cancel else None
        if c:
            return "cancel", c
    if "e" in box:
        raise box["e"]
    return "ok", box.get("r")


def handle(nav, step, why, img, cfg, matches, tap, say=lambda *a, **k: None, sleep=time.sleep, asker=None, cancel=None):
    """Xử lý màn hình lạ bằng AI. `matches()` → (khớp ảnh mẫu?, ảnh mới, lý do); `tap(x, y, verify)` → (bấm được?, lý do);
    `cancel()` → None | "stop" | "abort" (người vận hành bấm Dừng / Dừng ngay).
    Trả (True, "") khi màn hình đã KHỚP ảnh mẫu sau khi AI xử lý; (False, lý do) khi không xử lý được (bên gọi tạm dừng máy chờ admin).
    Bị «Dừng ngay» → ném stepexec.Aborted (kể cả khi đang chờ AI trả lời — không chờ hết); bấm Dừng → (False, …), không bấm thêm gì."""
    import screencheck, stepexec
    asker = asker or ask
    ref_img = screencheck.ref_image(step.get("screen") or {})
    step_text = stepexec.observed_what(step, {})
    last = why

    def stopped():
        c = cancel() if cancel else None
        if c == "abort":
            raise stepexec.Aborted()
        return c == "stop"
    for n in range(TRIES):
        if img is None:
            return False, "AI không xem được màn hình (chụp lỗi)"
        if stopped():
            return False, "đã dừng theo yêu cầu"
        try:
            how, d = _call(lambda: asker(cfg, img, ref_img, step_text, last), cancel)
        except AIError as e:
            return False, "không hỏi được AI: %s" % e
        except Exception as e:
            return False, "không hỏi được AI: %s" % (str(e)[:120] or type(e).__name__)
        if how == "cancel" or stopped():
            if d == "abort":
                raise stepexec.Aborted()
            return False, "đã dừng theo yêu cầu"
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            return False, "AI trả lời sai dạng"
        say("AI xem màn hình lạ (lần %d): %s — %s (chắc %d%%)" % (n + 1, {"ad": "quảng cáo", "popup": "hộp thông báo", "loading": "đang tải",
            "expected": "giống ảnh mẫu", "other": "màn hình khác"}[d["kind"]], d["reason"] or "?", d["confidence"] * 100))
        if d["kind"] == "loading":
            sleep(LOADING_WAIT)
        elif d["kind"] in ("ad", "popup") and d["confidence"] >= MIN_CONF:
            pos, pwhy = pick_target(nav, img, d)
            if pos is None:
                return False, pwhy
            if stopped():                                # bấm Dừng / Dừng ngay trong lúc chờ AI: không bấm gì nữa
                return False, "đã dừng theo yêu cầu"
            seen = img
            ok, twhy = tap(int(pos[0]), int(pos[1]), lambda now, x=int(pos[0]), y=int(pos[1]): patch_same(seen, now, x, y))
            if not ok:
                return False, "AI chỉ nút «%s» nhưng không bấm được (%s)" % (d["close_label"] or "X", twhy)
            say("Đã bấm «%s» theo AI" % (d["close_label"] or "nút đóng"))
            sleep(AFTER_TAP)
        else:
            # «giống ảnh mẫu» không được tính là khớp (AI không được cho qua một màn hình mà phép so vẫn thấy khác); «khác» / chưa chắc → admin
            return False, "AI: %s" % (d["reason"] or "không nhận ra màn hình")
        good, img, last = matches()
        if good:
            return True, ""
    return False, "AI đã xử lý %d lần mà màn hình vẫn khác ảnh mẫu" % TRIES
