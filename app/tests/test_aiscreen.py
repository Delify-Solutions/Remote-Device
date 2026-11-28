#!/usr/bin/env python3
"""
Kiểm AI XỬ LÝ MÀN HÌNH LẠ (aiscreen.py) bằng AI GIẢ — không gọi máy chủ AI thật:
  • đọc câu trả lời (JSON lẫn chữ thừa, sai dạng → «khác», không bấm);
  • toạ độ AI đưa trên ảnh thu nhỏ được đổi về ảnh chụp gốc; ngoài ảnh → bỏ;
  • quảng cáo / hộp thông báo: tìm nút theo CHỮ trước, không thấy mới dùng toạ độ; bấm xong so lại ảnh mẫu, khớp thì làm tiếp;
  • AI chưa chắc / «màn hình khác» / «giống ảnh mẫu» → không bấm, giao admin; đang tải → chờ rồi so lại; tối đa TRIES lần;
  • lỗi AI (key sai, mất mạng) → giao admin, không làm hỏng lượt chạy.

    ./.venv/bin/python app/tests/test_aiscreen.py
"""
from __future__ import annotations
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["IPF_NO_TELEGRAM"] = "1"
import numpy as np
import aiscreen, screencheck

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


class Eyes:
    """Mắt giả: `labels` = {chữ: (x, y)} — mỗi chữ là MỘT dòng chữ (rộng 80, cao 30) ở chỗ đó."""
    def __init__(self, labels=None):
        self.labels = labels or {}

    def text_lines(self, img=None):
        out = []
        for t, v in self.labels.items():
            for (x, y) in (v if isinstance(v, list) else [v]):
                out.append({"text": t, "x": x, "y": y, "w": 80, "h": 30})
        return out


class Nav:
    def __init__(self, labels=None):
        self.e = Eyes(labels)


IMG = np.zeros((750, 1334, 3), np.uint8)
STEP = {"type": "tap_text", "text": "Shop", "screen": screencheck.capture(IMG, ["Home", "Shop", "Extras"])}
CFG = {"provider": "anthropic", "model": "claude-opus-5-5", "key": "k", "base_url": "", "enabled": True}


def run(answers, matches_seq, labels=None, tap_ok=True, cancel=None):
    """Chạy handle với AI giả trả lần lượt `answers`, phép so lại trả lần lượt `matches_seq`."""
    asked, taps, slept = [], [], []
    ans = list(answers)
    ms = list(matches_seq)

    def asker(cfg, img, ref, step_text, why):
        asked.append((step_text, why, ref is not None))
        a = ans.pop(0) if ans else {"kind": "other", "reason": "hết"}
        if isinstance(a, Exception):
            raise a
        return aiscreen.parse(json.dumps(a))

    def matches():
        good = ms.pop(0) if ms else False
        return good, IMG, "vẫn khác"

    def tap(x, y, verify=None):
        taps.append((x, y))
        if verify is not None and not verify(IMG):
            return False, "màn hình đổi"
        return (True, "") if tap_ok else (False, "con trỏ không tới được")
    r = aiscreen.handle(Nav(labels), STEP, "màn hình khác ảnh mẫu", IMG, CFG, matches, tap, sleep=lambda s: slept.append(s), asker=asker, cancel=cancel)
    return r, asked, taps, slept


def main():
    print("== 1. Đọc câu trả lời của AI ==")
    d = aiscreen.parse('Đây:\n```json\n{"kind":"ad","close_label":"X","x":100,"y":50,"confidence":0.9,"reason":"Quảng cáo gói"}\n```')
    ok(d["kind"] == "ad" and d["x"] == 100 and d["confidence"] == 0.9, "JSON lẫn chữ thừa / ```json``` → đọc được", d)
    ok(aiscreen.parse("không biết")["kind"] == "other" and aiscreen.parse('{"kind":"hack","x":"a"}')["kind"] == "other",
       "sai dạng / loại lạ → «khác» (không bấm)")
    ok(aiscreen.parse('{"kind":"popup","confidence":7}')["confidence"] == 1.0, "độ chắc bị kẹp trong 0–1")

    print("== 2. Toạ độ AI đưa (ảnh thu nhỏ) → toạ độ ảnh chụp gốc ==")
    real = aiscreen._ask_anthropic
    try:
        big = np.zeros((1500, 2668, 3), np.uint8)                        # cạnh dài 2668 → gửi 1280 (k ≈ 0,48)
        aiscreen._ask_anthropic = lambda cfg, prompt, cur, ref: json.dumps({"kind": "ad", "close_label": "", "x": 640, "y": 360,
                                                                           "confidence": 0.9, "reason": "r"})
        d = aiscreen.ask(CFG, big, None, "Tap chữ «Shop»", "khác")
        ok(abs(d["x"] - 1334) <= 2 and abs(d["y"] - 750) <= 2, "x, y nhân ngược về ảnh gốc", d)
        aiscreen._ask_anthropic = lambda cfg, prompt, cur, ref: json.dumps({"kind": "ad", "close_label": "", "x": 5000, "y": 10,
                                                                           "confidence": 0.9, "reason": "r"})
        d = aiscreen.ask(CFG, big, None, "s", "w")
        ok(d["x"] == -1 and d["y"] == -1, "toạ độ ngoài ảnh → bỏ (không bấm bừa)", d)
        seen = {}
        aiscreen._ask_anthropic = lambda cfg, prompt, cur, ref: seen.update(prompt=prompt, ref=bool(ref)) or "{}"
        aiscreen.ask(CFG, IMG, IMG, "Tap chữ «Shop»", "chỉ thấy 20% chữ")
        ok("Tap chữ «Shop»" in seen["prompt"] and "20%" in seen["prompt"] and seen["ref"] and "Never choose a button that buys" in seen["prompt"],
           "gửi AI: ảnh hiện tại + ảnh mẫu + bước + lý do; dặn không bao giờ chọn nút mua / thanh toán / đăng nhập", seen.get("prompt", "")[:80])
    finally:
        aiscreen._ask_anthropic = real

    print("== 3. Xử lý ==")
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "Close", "x": 1190, "y": 90, "confidence": 0.9, "reason": "Quảng cáo"}], [True],
                            labels={"Close": [(1200, 80), (200, 600)]})
    ok(r == (True, "") and taps == [(1200, 80)], "quảng cáo có nút chữ «Close» → bấm đúng tâm dòng chữ SÁT toạ độ AI (không lấy «Close» ở chỗ khác)", (r, taps))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 1290, "y": 40, "confidence": 0.9, "reason": "a"}], [True],
                            labels={"Extras": (195, 631), "x": (195, 631)})
    ok(r == (True, "") and taps == [(1290, 40)], "nhãn «X» mà chữ «x» chỉ có ở chỗ khác (vd trong «Extras») → bấm theo toạ độ AI, không nhảy sang đó", (r, taps))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "Close", "x": 60, "y": 60, "confidence": 0.9, "reason": "a"}], [],
                            labels={"Close": (1160, 635)})
    ok(r[0] is False and not taps and "chỗ khác" in r[1], "AI nói nút chữ «Close» ở một chỗ mà chữ đó lại ở chỗ khác → không bấm", r)

    class Blind(Nav):
        def __init__(self):
            super().__init__()
            self.e.text_lines = lambda img=None: (_ for _ in ()).throw(RuntimeError("OCR lỗi"))
    r = aiscreen.handle(Blind(), STEP, "w", IMG, CFG, lambda: (True, IMG, ""), lambda x, y, v=None: (True, ""), sleep=lambda s: None,
                        asker=lambda *a: aiscreen.parse(json.dumps({"kind": "ad", "close_label": "", "x": 100, "y": 100, "confidence": 0.9, "reason": ""})))
    ok(r[0] is False and "không đọc được chữ" in r[1], "bộ đọc chữ lỗi (không kiểm được chữ tại chỗ bấm) → không bấm", r)
    ok(aiscreen.denied("Watch ad") and aiscreen.denied("Play") and not aiscreen.denied("Skip"), "chặn cả «Watch ad», «Play»")
    r, asked, taps, _ = run([{"kind": "popup", "close_label": "Later", "x": -1, "y": -1, "confidence": 0.9, "reason": "a"}], [True],
                            labels={"Later": (700, 500)})
    ok(r == (True, "") and taps == [(700, 500)], "không có toạ độ, nhãn là đúng MỘT dòng chữ trên màn hình → bấm dòng đó", (r, taps))
    r, asked, taps, _ = run([{"kind": "popup", "close_label": "Close", "x": -1, "y": -1, "confidence": 0.9, "reason": "a"}], [],
                            labels={"Close": [(700, 500), (100, 100)]})
    ok(r[0] is False and not taps and "nhiều chỗ" in r[1], "không có toạ độ, nhãn có ở nhiều chỗ → không đoán, giao admin", r)
    for lab, lines, what in (("Buy now", {}, "AI chọn nút «Buy now»"), ("X", {"Thanh toán": (1290, 40)}, "chỗ AI chỉ có chữ «Thanh toán»"),
                             ("Get", {}, "nút «Get» (nhận / cài)")):
        r, asked, taps, _ = run([{"kind": "ad", "close_label": lab, "x": 1290, "y": 40, "confidence": 0.95, "reason": "a"}], [], labels=lines)
        ok(r[0] is False and not taps and "không bao giờ bấm tự động" in r[1], what + " → KHÔNG bấm (chặn ở code, không chỉ dặn AI)", r)
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 1290, "y": 40, "confidence": 0.9, "reason": "a"}], [])
    import numpy as np2
    seen_v = {}

    def tap_v(x, y, verify=None):
        changed = IMG.copy(); changed[0:120, 1230:1334] = 255
        seen_v["same"] = verify(IMG); seen_v["changed"] = verify(changed)
        return True, ""
    aiscreen.handle(Nav(), STEP, "w", IMG, CFG, lambda: (True, IMG, ""), tap_v, sleep=lambda s: None,
                    asker=lambda *a: aiscreen.parse(json.dumps({"kind": "ad", "close_label": "", "x": 1290, "y": 40, "confidence": 0.9, "reason": ""})))
    ok(seen_v == {"same": True, "changed": False}, "bấm có kiểm: vùng quanh nút đã đổi trong lúc đưa con trỏ tới → không bấm", seen_v)
    import apimode, threading as th_, time as tm_
    flag = {"c": None}

    def slow_asker(cfg, img, ref, st, why):
        tm_.sleep(1.0)
        return aiscreen.parse(json.dumps({"kind": "ad", "close_label": "", "x": 100, "y": 100, "confidence": 0.9, "reason": ""}))
    taps2 = []
    th_.Timer(0.2, lambda: flag.update(c="abort")).start()
    t0 = tm_.time()
    try:
        aiscreen.handle(Nav(), STEP, "w", IMG, CFG, lambda: (True, IMG, ""), lambda x, y, v=None: taps2.append((x, y)) or (True, ""),
                        sleep=lambda s: None, asker=slow_asker, cancel=lambda: flag["c"])
        ok(False, "«Dừng ngay» trong lúc AI đang trả lời → dừng ngay, KHÔNG bấm")
    except apimode.Aborted:
        ok(not taps2 and tm_.time() - t0 < 0.8, "«Dừng ngay» trong lúc AI đang trả lời → dừng ngay (không chờ AI xong), KHÔNG bấm", (taps2, tm_.time() - t0))
    flag["c"] = None
    th_.Timer(0.2, lambda: flag.update(c="stop")).start()
    r = aiscreen.handle(Nav(), STEP, "w", IMG, CFG, lambda: (True, IMG, ""), lambda x, y, v=None: taps2.append((x, y)) or (True, ""),
                        sleep=lambda s: None, asker=slow_asker, cancel=lambda: flag["c"])
    ok(r[0] is False and not taps2, "bấm Dừng trong lúc AI đang trả lời → không bấm gì, giao lại", (r, taps2))
    ok(aiscreen.parse('{"kind":"ad","x":600,"y":-1}')["x"] == -1 and aiscreen.parse('[1,2]')["kind"] == "other"
       and aiscreen.parse('{"kind":"ad","confidence":1e999}')["confidence"] in (0.0, 1.0), "toạ độ thiếu một nửa → bỏ cả hai; JSON không phải object / số vô cực → không lỗi")
    r, asked, taps, _ = run([{"kind": "popup", "close_label": "", "x": 1290, "y": 40, "confidence": 0.8, "reason": "Hộp tin"}], [True])
    ok(r == (True, "") and taps == [(1290, 40)], "(lặp) nút X không chữ → toạ độ AI", (r, taps))
    ok(r == (True, "") and taps == [(1290, 40)], "nút X không có chữ → bấm theo toạ độ AI", (r, taps))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 5, "y": 5, "confidence": 0.9, "reason": "a"},
                             {"kind": "popup", "close_label": "Later", "x": 7, "y": 7, "confidence": 0.9, "reason": "b"}], [False, True],
                            labels={"Later": (12, 12)})
    ok(r == (True, "") and len(asked) == 2 and taps == [(5, 5), (12, 12)], "quảng cáo nối tiếp hộp thoại → xử lý lần lượt tới khi khớp ảnh mẫu", (r, taps))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 5, "y": 5, "confidence": 0.9, "reason": "a"}] * 5, [False] * 5)
    ok(r[0] is False and len(asked) == aiscreen.TRIES and "vẫn khác" in r[1], "xử lý TRIES lần mà vẫn khác → giao admin", (r, len(asked)))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 5, "y": 5, "confidence": 0.4, "reason": "có thể là quảng cáo"}], [])
    ok(r[0] is False and not taps, "AI chưa chắc (< MIN_CONF) → không bấm, giao admin", (r, taps))
    for kind in ("other", "expected"):
        r, asked, taps, _ = run([{"kind": kind, "close_label": "", "x": -1, "y": -1, "confidence": 0.95, "reason": "Màn hình thanh toán"}], [True])
        ok(r[0] is False and not taps and "Màn hình thanh toán" in r[1],
           "AI nói «%s» → không bấm, KHÔNG tự cho qua, giao admin kèm lời AI" % kind, (r, taps))
    r, asked, taps, slept = run([{"kind": "loading", "close_label": "", "x": -1, "y": -1, "confidence": 0.9, "reason": "Đang tải"}], [True])
    ok(r == (True, "") and not taps and aiscreen.LOADING_WAIT in slept, "đang tải → chờ rồi so lại, khớp thì làm tiếp", (r, slept))
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "", "x": -1, "y": -1, "confidence": 0.9, "reason": "a"}], [])
    ok(r[0] is False and not taps and "không chỉ ra được chỗ nút" in r[1], "quảng cáo mà AI không chỉ ra nút đóng → giao admin", r)
    r, asked, taps, _ = run([{"kind": "ad", "close_label": "X", "x": 5, "y": 5, "confidence": 0.9, "reason": "a"}], [], tap_ok=False)
    ok(r[0] is False and "không bấm được" in r[1], "bấm nút AI chỉ không được (con trỏ không tới) → giao admin", r)
    r, asked, taps, _ = run([aiscreen.AIError("API key của Anthropic không đúng")], [])
    ok(r[0] is False and "API key" in r[1] and not taps, "lỗi AI (key sai / mất mạng) → giao admin, nêu lý do", r)
    r, asked, taps, _ = run([RuntimeError("boom")], [])
    ok(r[0] is False and "boom" in r[1], "lỗi bất ngờ khi hỏi AI → giao admin, không ném lỗi", r)
    r = aiscreen.handle(Nav(), STEP, "khác", None, CFG, lambda: (False, None, ""), lambda x, y: (True, ""), asker=lambda *a: 1 / 0)
    ok(r[0] is False and "chụp lỗi" in r[1], "không có ảnh màn hình → không hỏi AI, giao admin", r)

    print("== 4. Cấu hình ==")
    c = aiscreen.config({"ai_provider": "OpenAI", "ai_key": " sk ", "ai_base_url": "http://127.0.0.1:1234/v1/"})
    ok(c == {"provider": "openai", "model": "gpt-5", "key": "sk", "base_url": "http://127.0.0.1:1234/v1", "enabled": True}, "đọc cấu hình, model mặc định theo nhà cung cấp", c)
    ok(aiscreen.config({"ai_provider": "la"})["provider"] == "anthropic" and aiscreen.config({})["model"] == "claude-opus-5-5", "nhà cung cấp lạ → anthropic")
    ok(not aiscreen.usable(aiscreen.config({})) and aiscreen.usable(aiscreen.config({"ai_key": "x"}))
       and aiscreen.usable(aiscreen.config({"ai_provider": "openai", "ai_base_url": "http://x"}))
       and not aiscreen.usable(aiscreen.config({"ai_key": "x", "ai_screen": False})),
       "chỉ dùng khi có key (máy chủ tương thích OpenAI riêng: có địa chỉ là đủ) và không bị tắt")

    print("== 4b. Yêu cầu THẬT mà SDK gửi đi (chặn ở tầng HTTP trên máy — không gọi máy chủ AI, không tốn tiền) ==")
    import httpx
    seen = []

    def anth_handler(req):
        body = json.loads(req.content)
        seen.append((str(req.url), dict(req.headers), body))
        if "output_config" in body and body.get("model") == "model-cu":
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "output_config: format not supported"}})
        txt = json.dumps({"kind": "popup", "close_label": "Close", "x": 640, "y": 100, "confidence": 0.9, "reason": "Hộp tin tức"})
        return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                         "content": [{"type": "text", "text": txt}], "stop_reason": "end_turn", "stop_sequence": None,
                                         "usage": {"input_tokens": 10, "output_tokens": 10}})
    import anthropic
    real_cls = anthropic.Anthropic
    anthropic.Anthropic = lambda **kw: real_cls(http_client=httpx.Client(transport=httpx.MockTransport(anth_handler)), **kw)
    try:
        d = aiscreen.ask(dict(CFG, key="sk-ant-test"), IMG, IMG, "Tap chữ «Shop»", "khác")
        url, hdr, body = seen[-1]
        imgs = [c for c in body["messages"][0]["content"] if c["type"] == "image"]
        ok(d["kind"] == "popup" and d["close_label"] == "Close" and url.split("?")[0].endswith("/v1/messages") and hdr.get("x-api-key") == "sk-ant-test"
           and body["model"] == "claude-opus-5-5" and len(imgs) == 2 and imgs[0]["source"]["media_type"] == "image/jpeg"
           and body["output_config"]["format"]["type"] == "json_schema" and body.get("fallbacks") == "default"
           and "server-side-fallback-2026-07-01" in hdr.get("anthropic-beta", "") and "thinking" not in body and "temperature" not in body,
           "Anthropic: 2 ảnh JPEG + chữ, JSON theo khuôn, fallbacks «default» (beta), không gửi tham số cũ", (url, hdr.get("anthropic-beta"), list(body)))
        seen.clear()
        d = aiscreen.ask(dict(CFG, key="sk-ant-test", model="model-cu"), IMG, None, "s", "w")
        ok(d["kind"] == "popup" and len(seen) == 2 and "output_config" not in seen[1][2] and "fallbacks" not in seen[0][2],
           "model không hỗ trợ JSON theo khuôn (400) → hỏi lại kiểu thường; model ngoài danh sách thì không gửi fallbacks", [list(x[2]) for x in seen])
        seen.clear()
        aiscreen.ask(dict(CFG, key="sk-ant-test", base_url="https://proxy.example/anthropic"), IMG, None, "s", "w")
        ok(seen and seen[-1][0].startswith("https://proxy.example/anthropic/"), "địa chỉ máy chủ riêng được dùng", seen[-1][0] if seen else None)
    finally:
        anthropic.Anthropic = real_cls

    def oai_handler(req):
        body = json.loads(req.content)
        seen.append((str(req.url), dict(req.headers), body))
        if body.get("response_format") and body.get("model") == "local-llava":
            return httpx.Response(400, json={"error": {"message": "response_format json_object not supported", "type": "invalid_request_error"}})
        txt = json.dumps({"kind": "ad", "close_label": "", "x": 1200, "y": 60, "confidence": 0.8, "reason": "Quảng cáo"})
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 1, "model": body["model"],
                                         "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": txt}}]})
    import openai
    real_o = openai.OpenAI
    openai.OpenAI = lambda **kw: real_o(http_client=httpx.Client(transport=httpx.MockTransport(oai_handler)), **kw)
    try:
        seen.clear()
        d = aiscreen.ask({"provider": "openai", "model": "gpt-5", "key": "sk-o", "base_url": "", "enabled": True}, IMG, IMG, "s", "w")
        url, hdr, body = seen[-1]
        parts = body["messages"][0]["content"]
        ok(d["kind"] == "ad" and url.endswith("/chat/completions") and hdr.get("authorization") == "Bearer sk-o" and body["model"] == "gpt-5"
           and sum(1 for p in parts if p["type"] == "image_url") == 2 and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
           and body.get("response_format") == {"type": "json_object"}, "OpenAI: chữ + 2 ảnh (data URL), yêu cầu JSON", list(body))
        seen.clear()
        d = aiscreen.ask({"provider": "openai", "model": "local-llava", "key": "", "base_url": "http://127.0.0.1:1234/v1", "enabled": True}, IMG, None, "s", "w")
        ok(d["kind"] == "ad" and len(seen) == 2 and "response_format" not in seen[1][2] and seen[1][0].startswith("http://127.0.0.1:1234/v1/"),
           "máy chủ tương thích OpenAI không hỗ trợ JSON → hỏi lại kiểu thường, đúng địa chỉ riêng", [x[0] for x in seen])
    finally:
        openai.OpenAI = real_o

    print("== 5. Bộ chạy: hỏi AI trước khi tạm dừng máy ==")
    import threading, time, runner as runmod, store
    R = runmod.Runner(lambda n: None)
    alerts, calls = [], []
    R.alert = lambda ev, name, lines, photo=None: alerts.append((ev, lines))
    saved = runmod.store.get_settings, aiscreen.handle
    settings = {"ai_key": "k"}
    runmod.store.get_settings = lambda: dict(settings)

    def worker():
        w = {"stop": threading.Event(), "abort": threading.Event(), "pause": threading.Event(), "paused": False, "name": "M1",
             "group_name": "G", "script_name": "S", "nav": Nav()}
        R.workers["M1"] = dict(w, thread=threading.current_thread())
        return w
    try:
        aiscreen.handle = lambda *a, **k: calls.append(a) or (True, "")
        w = worker()
        r = R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)
        ok(r == (True, "") and calls and not alerts and not R.is_parked("M1"), "AI xử lý được (đã khớp ảnh mẫu) → làm tiếp bước, KHÔNG tạm dừng / báo admin", (r, alerts))
        calls.clear()
        aiscreen.handle = lambda *a, **k: calls.append(a) or (False, "AI: Màn hình thanh toán App Store")
        w = worker()
        out = {}
        th = threading.Thread(target=lambda: out.update(r=R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG))); th.start(); time.sleep(0.3)
        paused = R.is_parked("M1")
        R.resume_machine("M1"); th.join(3)
        ok(paused and out.get("r") == (True, "") and alerts and alerts[0][0] == "paused" and any("Màn hình thanh toán" in x for x in alerts[0][1]),
           "AI không xử lý được → tạm dừng chờ admin, Telegram kèm lời AI; Tiếp tục → làm tiếp", (paused, out, alerts[:1]))
        R.parked.discard("M1"); alerts.clear(); calls.clear()
        w = worker(); w["mode"] = "api"
        th = threading.Thread(target=lambda: R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)); th.start(); time.sleep(0.3)
        R.resume_machine("M1"); th.join(3)
        ok(alerts and not any("thanh toán App Store" in x for x in alerts[0][1]) and any("nhật ký" in x for x in alerts[0][1]),
           "máy nhận đơn: Telegram KHÔNG chép lời AI (có thể nhắc chữ trên màn hình của khách), chỉ câu cố định", alerts[:1])
        R.parked.discard("M1"); alerts.clear(); calls.clear()
        w = worker(); w["nav"].buying = True
        th = threading.Thread(target=lambda: R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)); th.start(); time.sleep(0.3)
        R.resume_machine("M1"); th.join(3)
        ok(not calls and alerts, "giai đoạn MUA → không hỏi AI (AI không được bấm lúc đang mua), tạm dừng chờ admin", (calls, alerts[:1]))
        R.parked.discard("M1"); alerts.clear(); calls.clear()
        settings.clear()
        w = worker()
        th = threading.Thread(target=lambda: R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)); th.start(); time.sleep(0.3)
        R.resume_machine("M1"); th.join(3)
        ok(not calls and alerts, "chưa cấu hình AI → không hỏi, tạm dừng chờ admin luôn", (calls, alerts))
        R.parked.discard("M1"); alerts.clear()
        settings["ai_key"] = "k"
        w = worker(); w["stop"].set()
        r = R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)
        ok(not calls and r[0] is False and not alerts, "đã bấm Dừng → không hỏi AI, không tạm dừng", (calls, r))
        import apimode

        def slow(*a, sleep=None, **k):
            sleep(5)
            return True, ""
        aiscreen.handle = slow
        w = worker()
        threading.Timer(0.2, w["abort"].set).start()
        try:
            R._screen_helper("M1", w)(STEP, "khác ảnh mẫu", IMG)
            ok(False, "«Dừng ngay» trong lúc AI đang xử lý → dừng ngay (Aborted)")
        except apimode.Aborted:
            ok(True, "«Dừng ngay» trong lúc AI đang xử lý → dừng ngay (Aborted)")
    finally:
        runmod.store.get_settings, aiscreen.handle = saved

    print("== 6. Cài đặt AI trong app ==")
    import tempfile
    store.DATA_DIR = tempfile.mkdtemp(prefix="ai-data-")
    import gui
    api = gui.Api()
    mem = {}
    sg, ss, web = gui.store.get_settings, gui.store.save_settings, gui.WEBDEV
    try:
        gui.store.get_settings = lambda: dict(mem)
        gui.store.save_settings = lambda patch: mem.update(patch) or dict(mem)
        mem.update(ai_key="abcdefghij123")
        ok(api.ai_screen_get()["key_hint"] == "đã lưu", "key ngắn → gợi ý không lộ ký tự nào")
        mem.clear()
        r = api.ai_screen_save("anthropic", "", "sk-ant-THISISAFAKEKEY-1234567890", "", True)
        ok(api.ai_screen_get()["key_hint"] == "…7890", "key dài → chỉ hiện 4 ký tự cuối", api.ai_screen_get()["key_hint"])
        ok(r.get("ok") and mem["ai_providers"]["anthropic"]["key"] == "sk-ant-THISISAFAKEKEY-1234567890" and "THISISAFAKEKEY" not in json.dumps(r)
           and "THISISAFAKEKEY" not in json.dumps(api.ai_screen_get()) and r["usable"], "lưu key; lệnh trả về KHÔNG chứa key", r)
        r = api.ai_screen_save("openai", "", "", "", True)
        ok(r.get("ok") and r["provider"] == "openai" and not r["usable"] and not mem["ai_providers"]["openai"]["key"]
           and mem["ai_providers"]["anthropic"]["key"].startswith("sk-ant-"),
           "chuyển sang OpenAI chưa có key → lưu, chưa dùng được; key Anthropic KHÔNG bị chép sang OpenAI, vẫn giữ cho Anthropic", r)
        r = api.ai_screen_save("anthropic", None, "", None, True)
        ok(r.get("ok") and r["usable"] and r["provider"] == "anthropic", "chuyển lại Anthropic → dùng lại key cũ của nó, không phải nhập lại", r)
        r = api.ai_screen_save("anthropic", "", "", "https://ai.cua-ai-do.example/v1", True)
        ok(r.get("ok") is False, "đổi máy chủ mà không nhập lại key → từ chối", r)
        ok(api.ai_screen_save("anthropic", "model bad!", "", "", True).get("ok") is False and api.ai_screen_save("la", "", "x", "", True).get("ok") is False
           and api.ai_screen_save("openai", "", "x", "ftp://a", True).get("ok") is False, "model / nhà cung cấp / địa chỉ sai dạng → không lưu")
        r = api.ai_screen_save("anthropic", "claude-sonnet-5-5", "", "", False)
        ok(r.get("ok") and mem["ai_providers"]["anthropic"]["model"] == "claude-sonnet-5-5" and mem.get("ai_screen") is False and not r["usable"]
           and mem["ai_providers"]["anthropic"]["key"], "đổi model, tắt AI (giữ key)", r)
        r = api.ai_settings_save({"active": "openai", "enabled": True, "providers": {
            "anthropic": {"model": "claude-opus-5-5", "key": "", "base_url": ""},
            "openai": {"model": "llava", "key": "sk-local-123", "base_url": "http://127.0.0.1:1234/v1"}}})
        pv = mem["ai_providers"]
        ok(r.get("ok") and r["provider"] == "openai" and r["usable"] and pv["openai"]["base_url"] == "http://127.0.0.1:1234/v1"
           and pv["anthropic"]["model"] == "" and pv["anthropic"]["key"] and "sk-local-123" not in json.dumps(r),
           "trang cấu hình lưu cả hai nhà cung cấp một lần; model trùng mặc định thì lưu trống (luôn theo mặc định)", r)
        r = api.ai_settings_save({"active": "openai", "providers": {"openai": {"model": "llava", "key": "", "base_url": "https://khac.example/v1"}}})
        ok(r.get("ok") is False and "NHẬP LẠI" in r["error"] and mem["ai_providers"]["openai"]["base_url"] == "http://127.0.0.1:1234/v1",
           "đổi máy chủ của một nhà cung cấp mà không nhập lại key → từ chối (key không tự gửi sang máy chủ mới)", r)
        ok(api.ai_settings_save({"providers": ["x"]}).get("ok") is False, "cấu hình sai dạng → báo lỗi, không ném")
        r = api.ai_settings_save({"active": "anthropic", "providers": {"anthropic": {"key": "sk-ant-abc\nX-Evil: 1", "model": "", "base_url": ""}}})
        ok(r.get("ok") is False and "ký tự lạ" in r["error"], "API key có xuống dòng / dấu cách → không lưu", r)
        mem.clear(); mem.update(ai_provider="openai", ai_key="sk-cu-1234567890", ai_model="gpt-4.1")
        g = api.ai_screen_get()
        ok(g["provider"] == "openai" and g["providers"]["openai"]["has_key"] and g["providers"]["openai"]["model"] == "gpt-4.1"
           and not g["providers"]["anthropic"]["has_key"], "cấu hình kiểu cũ (một bộ key) vẫn đọc được — thuộc nhà cung cấp đang chọn", g)
        mem.clear(); mem.update(ai_key="sk-ant-THISISAFAKEKEY-1234567890", ai_provider="anthropic")
        gui.WEBDEV = object()
        before = json.dumps(mem, sort_keys=True)
        ok(api.ai_screen_save("anthropic", "", "sk-ant-WEB-ATTEMPT-123456", "", True).get("ok") is False and json.dumps(mem, sort_keys=True) == before,
           "bản web → không đổi được cấu hình AI (không ghi gì)")
        ok(api.ai_screen_get()["editable"] is False, "bản web → trang báo «chỉ xem»")
        ok(api.ai_screen_test().get("ok") is False, "bản web → không «thử» AI (mỗi lần hỏi đều tốn tiền)")
        gui.WEBDEV = web
        mem.clear()
        ok(api.ai_screen_test().get("ok") is False, "chưa có key → «thử» báo chưa cấu hình (không gọi AI)")
        real_ask = aiscreen.ask
        mem.update(ai_key="k")
        aiscreen.ask = lambda cfg, img, ref, st, why: {"kind": "ad", "close_label": "X", "x": 945, "y": 185, "confidence": 0.9, "reason": "Quảng cáo"}
        try:
            r = api.ai_screen_test()
            ok(r.get("ok") and r["kind"] == "ad" and r["close"] == "X", "«thử» hỏi AI một ảnh quảng cáo vẽ sẵn", r)
            aiscreen.ask = lambda *a: (_ for _ in ()).throw(aiscreen.AIError("API key của Anthropic không đúng"))
            ok(api.ai_screen_test() == {"ok": False, "error": "API key của Anthropic không đúng"}, "key sai → báo rõ")
        finally:
            aiscreen.ask = real_ask
    finally:
        gui.store.get_settings, gui.store.save_settings, gui.WEBDEV = sg, ss, web

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
