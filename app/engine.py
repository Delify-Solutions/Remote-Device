#!/usr/bin/env python3
"""
engine.py — chạy flow (danh sách bước) trên 1 thiết bị (Nav).

Mỗi bước là dict JSON, ví dụ:
  {"type":"tap","x":300,"y":400}
  {"type":"tap_text","text":"Mua"}
  {"type":"type","text":"hello"}
  {"type":"key","name":"enter"}
  {"type":"combo","keys":"gui h"}
  {"type":"home"}
  {"type":"launch","app":"efootball"}
  {"type":"wait","seconds":1.5}
  {"type":"wait_text","text":"Shop","timeout":15}
  {"type":"assert_text","text":"Success"}
"""
from __future__ import annotations
import time

STEP_TYPES = ["tap", "tap_text", "type", "key", "combo", "home",
              "launch", "wait", "wait_text", "assert_text"]


def run_step(nav, step, log=print):
    """Chạy 1 bước. Trả (ok: bool, message: str)."""
    t = step.get("type")
    try:
        if t == "tap":
            ok = nav.tap_at(int(step["x"]), int(step["y"]))
            return ok, f"tap ({step['x']},{step['y']}) {'OK' if ok else 'lệch'}"
        if t == "tap_text":
            ok = nav.tap_text(step["text"])
            return ok, f"tap_text '{step['text']}' {'OK' if ok else 'không thấy'}"
        if t == "type":
            nav.h.type(step["text"])
            return True, f"gõ '{step['text']}'"
        if t == "key":
            nav.h.key(step["name"])
            return True, f"phím {step['name']}"
        if t == "combo":
            nav.h.do("combo " + step["keys"])
            return True, f"combo {step['keys']}"
        if t == "home":
            nav.home_screen()
            return True, "về home"
        if t == "launch":
            nav.h.do("combo gui h"); time.sleep(0.6)
            nav.h.do("combo gui space"); time.sleep(1.2)
            nav.h.do("combo cmd a"); nav.h.key("back"); time.sleep(0.3)
            nav.h.type(step["app"]); time.sleep(1.2)
            nav.h.key("enter"); time.sleep(2.5)
            return True, f"mở app '{step['app']}'"
        if t == "wait":
            time.sleep(float(step.get("seconds", 1)))
            return True, f"chờ {step.get('seconds',1)}s"
        if t == "wait_text":
            needle = step["text"]; timeout = float(step.get("timeout", 15))
            end = time.time() + timeout
            while time.time() < end:
                txt = nav.e.read_text().lower()
                if needle.lower() in txt:
                    return True, f"thấy '{needle}'"
                time.sleep(1)
            return False, f"hết giờ chờ '{needle}'"
        if t == "assert_text":
            txt = nav.e.read_text().lower()
            ok = step["text"].lower() in txt
            return ok, f"kiểm '{step['text']}' {'có' if ok else 'KHÔNG thấy'}"
        return False, f"bước lạ: {t}"
    except Exception as e:
        return False, f"lỗi {t}: {e}"


def run_flow(nav, steps, log=print, stop_on_fail=True):
    """Chạy cả flow. Trả list kết quả [{i, type, ok, msg}]."""
    results = []
    for i, step in enumerate(steps):
        ok, msg = run_step(nav, step, log)
        log(f"[{i+1}/{len(steps)}] {step.get('type')}: {msg}")
        results.append({"i": i, "type": step.get("type"), "ok": ok, "msg": msg})
        if not ok and stop_on_fail:
            log(f"  ⟂ dừng vì bước {i+1} thất bại")
            break
        time.sleep(0.3)
    return results
