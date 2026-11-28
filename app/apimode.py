#!/usr/bin/env python3
"""
apimode.py — xử lý MỘT đơn nạp (lấy từ Topup Gateway) trên MỘT máy.

    đăng nhập → (game đòi OTP → xin khách nhập → nhập) → vào danh sách gói
      → mua từng gói (chụp bill sau mỗi lần mua được) → báo kết quả

NGUYÊN TẮC TIỀN (khớp với gateway — đừng nới):
  * `failed`  CHỈ khi chắc chắn CHƯA mua gì (sai mật khẩu, hết lượt OTP, không thấy gói…).
  * Đã chạm vào luồng mua mà không xác nhận được kết quả → `review` (người đối soát), dừng ngay,
    không mua tiếp.
  * Mua được một phần → `review` kèm chi tiết từng gói.
  * Không bao giờ tự mua lại; lệnh bấm/gõ không được gửi lại khi không rõ đã chạy hay chưa.
  * Một lần mua chỉ được tính khi chữ «nạp thành công» XUẤT HIỆN MỚI sau khi bấm mua: trước mỗi lần
    mua màn hình phải sạch chữ đó (hộp thoại lần trước chưa đóng thì dừng, không đếm nhầm).
  * Chỉ gõ tài khoản của khách khi THẤY màn hình chưa đăng nhập (luật `logged_out`) — không bao giờ
    nạp vào tài khoản của khách trước còn đăng nhập sót.
  * Mật khẩu / OTP không bao giờ xuất hiện trong nhật ký (chỉ ghi tên biến {{password}}).

Chỉ dùng các thao tác cơ bản của máy (để test được bằng máy giả):
  nav.h.send(cmd, wait)  nav.h.wait_connected(t)
  nav.e.screenshot()  nav.e.read_text(img)  nav.e.find_text(chữ, img)
  nav.tap_at(x, y, click=False, verify=hàm_kiểm_ảnh)
"""
from __future__ import annotations
import json, os, re, threading, time

import cv2

from eyes import IMAGE_TOO_MANY, decode_image, norm_text, text_has
from gateway import GatewayError, call_retry

PHASES = ["login", "otp", "nav", "purchase", "after", "finish"]
GW_LISTS = {"login": "login_steps", "otp": "otp_steps", "nav": "nav_steps",
            "purchase": "purchase_steps", "after": "after_purchase_steps", "finish": "finish_steps"}
PHASE_LABEL = {"login": "Đăng nhập", "otp": "Nhập OTP", "nav": "Vào danh sách gói",
               "purchase": "Mua 1 gói", "after": "Sau khi mua", "finish": "Kết thúc đơn"}
DEFAULT_OTP_STEPS = [{"type": "type", "text": "{{otp}}"}, {"type": "key", "name": "enter"}]
INPUT_TYPES = ("tap", "tap_text", "tap_image", "tap_if", "type", "key", "combo", "launch", "home",
               "swipe", "hold", "hold_text")                                    # bước có (thể) gửi thao tác vào máy
SWIPE_DIRS = {"left": "trái", "right": "phải", "up": "lên", "down": "xuống"}
KEYS = ("enter", "return", "tab", "esc", "back", "space")
COMBO_MODS = ("gui", "cmd", "ctrl", "alt", "shift")


def combo_keys(value) -> str:
    """Chuẩn hoá + kiểm một tổ hợp phím: các phím bổ trợ rồi ĐÚNG MỘT phím cuối («gui h», «GUI+Space», «ctrl shift 4»).
    Sai dạng → ConfigError (không gửi thứ gì lạ xuống board)."""
    toks = str(value or "").lower().replace("+", " ").split()
    last = toks[-1] if toks else ""
    if not toks or len(toks) > 6 or any(t not in COMBO_MODS for t in toks[:-1]) \
            or not (last in ("enter", "return", "tab", "space") or (len(last) == 1 and 33 <= ord(last) <= 126)):
        raise ConfigError("tổ hợp phím phải có dạng «gui h», «gui space», «ctrl space»: các phím bổ trợ "
                          "(gui/cmd, ctrl, alt, shift) rồi MỘT phím cuối")
    return " ".join(toks)
RESULT_RULES = ("purchase_success", "purchase_fail", "package_unavailable")
REQUIRED_RULES = {"logged_out": "Màn hình CHƯA đăng nhập", "login_success": "Đăng nhập THÀNH CÔNG",
                  "purchase_success": "Nạp gói THÀNH CÔNG"}
REQUIRED_PHASES = ("login", "purchase", "finish")
STEP_GAP = 0.35
# Chụp màn hình giờ gần như tức thì (trước đây mỗi ảnh tự trễ ~1 giây vì phải khởi động lệnh chụp, vô tình
# đủ cho hiệu ứng chuyển màn của iOS chạy xong). Bước «nhìn MỘT lần rồi quyết» (bấm chữ, kiểm chữ, giữ chữ)
# vì thế phải chờ màn hình đứng yên trước khi nhìn — nếu không sẽ đọc phải khung hình đang trượt dở.
LOOK_SETTLE = 0.9
FRESH_SETTLE = 2.0       # nghỉ sau khi «tắt hẳn rồi mở mới» một app, cho app kịp lên màn hình
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


class ConfigError(Exception):
    """Cấu hình bước sai (lỗi phía người cấu hình/tool, không phải lỗi của khách)."""


class InputError(Exception):
    """Dữ liệu của khách không dùng được (vd mật khẩu có ký tự tool không gõ được)."""


class JobGone(Exception):
    """Gateway không còn coi đơn này là đang chạy (đã đối soát/quá hạn) → dừng, không báo kết quả."""


class Aborted(Exception):
    """Người vận hành bấm «Dừng ngay»."""


class NotAtLogin(Exception):
    """Trước khi gõ tài khoản mà không thấy màn hình «chưa đăng nhập» (luật `logged_out`) → không gõ."""


class StaleSession(Exception):
    """Game ĐANG đăng nhập sẵn một tài khoản trước khi tool kịp gõ tài khoản của đơn này
    (đơn trước đăng xuất hỏng) → dừng ngay, nếu làm tiếp sẽ nạp nhầm vào tài khoản khách trước."""


# ====================== bước: chuyển đổi + thế biến ======================
def gw_step_to_engine(s: dict) -> dict:
    """Bước kiểu gateway {type, value, note, optional} → bước của tool {type, text|x,y|…, optional}."""
    out = _gw_step(s)
    if s.get("optional"):
        out["optional"] = True          # lỗi ở bước này thì BỎ QUA, chạy tiếp bước sau
    return out


def _gw_step(s: dict) -> dict:
    t = s.get("type")
    v = str(s.get("value") or "")
    if t == "tap":
        m = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", v)
        if not m:
            raise ConfigError(f"bước «Tap toạ độ» cần giá trị dạng x,y (đang là «{v}»)")
        return {"type": "tap", "x": int(m.group(1)), "y": int(m.group(2))}
    if t in ("tap_text", "assert_text"):
        return {"type": t, "text": v}
    if t == "wait_text":        # "Chữ cần chờ @45s" = chờ tối đa 45 giây (mặc định 20)
        m = re.match(r"^(.*?)\s*@\s*(\d{1,3})\s*s\s*$", v)
        return {"type": t, "text": m.group(1), "timeout": int(m.group(2))} if m else {"type": t, "text": v, "timeout": 20}
    if t == "type":
        return {"type": "type", "text": v}
    if t == "key":
        return {"type": "key", "name": v.strip().lower()}
    if t == "combo":
        return {"type": "combo", "keys": v.strip().lower()}
    if t == "launch":
        return {"type": "launch", "app": v.strip()}
    if t == "home":
        return {"type": "home"}
    if t == "swipe":            # "left" | "right" | "up" | "down"   hoặc   "x1,y1 > x2,y2"
        d = v.strip().lower()
        if d in SWIPE_DIRS:
            return {"type": "swipe", "dir": d}
        m = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*(?:>|→|->|to)\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", v)
        if not m:
            raise ConfigError("bước «Vuốt» cần hướng (left/right/up/down) hoặc dạng x1,y1 > x2,y2 (đang là «%s»)" % v)
        return {"type": "swipe", "x1": int(m.group(1)), "y1": int(m.group(2)), "x2": int(m.group(3)), "y2": int(m.group(4))}
    if t in ("hold", "hold_text"):  # "x,y @1.5s"  /  "Chữ cần giữ @1.5s"  (mặc định giữ 1 giây)
        m = re.match(r"^(.*?)\s*@\s*(\d+(?:[.,]\d+)?)\s*s\s*$", v)
        body, sec = (m.group(1), float(m.group(2).replace(",", "."))) if m else (v, 1.0)
        sec = max(0.2, min(sec, 10.0))
        if t == "hold_text":
            return {"type": "hold_text", "text": body.strip(), "seconds": sec}
        m2 = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", body)
        if not m2:
            raise ConfigError("bước «Bấm giữ» cần giá trị dạng x,y hoặc x,y @1.5s (đang là «%s»)" % v)
        return {"type": "hold", "x": int(m2.group(1)), "y": int(m2.group(2)), "seconds": sec}
    if t == "wait":
        try:
            sec = float(v.replace(",", ".") or 1)
        except ValueError:
            raise ConfigError(f"bước «Chờ» cần số giây (đang là «{v}»)")
        return {"type": "wait", "seconds": max(0.0, min(sec, 600.0))}
    raise ConfigError(f"loại bước lạ: {t}")


def effective_steps(pool: dict, local: dict | None) -> dict:
    """Danh sách bước thực dùng cho từng giai đoạn: nhóm có bước riêng thì dùng của nhóm,
    không thì lấy từ cấu hình pool trên gateway."""
    local = local or {}
    out = {}
    for ph in PHASES:
        mine = [s for s in (local.get(ph) or []) if isinstance(s, dict) and s.get("type")]
        out[ph] = mine if mine else [gw_step_to_engine(s) for s in (pool.get(GW_LISTS[ph]) or [])]
    if not out["otp"]:
        out["otp"] = [dict(s) for s in DEFAULT_OTP_STEPS]
    return out


def subst(text: str, vars: dict) -> str:
    """Thế {{biến}} bằng giá trị thật. Biến không có giá trị → lỗi cấu hình (không gõ nguyên chữ {{…}})."""
    def rep(m):
        k = m.group(1)
        if vars.get(k) is None:
            raise ConfigError("bước dùng biến {{%s}} nhưng đơn không có giá trị này" % k)
        return str(vars[k])
    return PLACEHOLDER.sub(rep, text)


def show(text: str, vars: dict) -> str:
    """Chữ để GHI NHẬT KÝ: chỉ thế các biến về gói ({{package.*}}), giữ nguyên tên biến bí mật."""
    def rep(m):
        k = m.group(1)
        return str(vars[k]) if k.startswith("package.") and vars.get(k) is not None else m.group(0)
    return PLACEHOLDER.sub(rep, text)


def alternatives(text: str) -> list:
    """«1050|1,050» → ['1050', '1,050'] (dùng cho bước dò chữ)."""
    return [a.strip() for a in text.split("|") if a.strip()]


def placeholders(steps) -> list:
    """Các tên biến xuất hiện trong danh sách bước (để hỏi giá trị khi chạy thử)."""
    return sorted(set(PLACEHOLDER.findall(json.dumps(steps, ensure_ascii=False))))


def describe(step: dict, vars: dict | None = None) -> str:
    return _describe(step, vars or {}) + (" (bỏ qua nếu lỗi)" if step.get("optional") else "")


def _describe(step: dict, vars: dict) -> str:
    t = step.get("type")
    if t == "tap":
        return f"Tap ({step.get('x')},{step.get('y')})"
    if t in ("tap_text", "wait_text", "assert_text"):
        name = {"tap_text": "Tap chữ", "wait_text": "Chờ chữ", "assert_text": "Kiểm chữ"}[t]
        out = f"{name} «{show(str(step.get('text') or ''), vars)}»"
        if t != "wait_text" and str(step.get("near") or "").strip():
            out += " có «%s» %s" % (show(str(step.get("near")), vars), NEAR_DIRS.get(str(step.get("near_dir") or "below"), "ngay dưới"))
        if t != "wait_text" and str(step.get("scroll") or "") in SWIPE_DIRS:
            out += " (chưa thấy thì lướt %s)" % SWIPE_DIRS[str(step.get("scroll"))]
        return out
    if t == "tap_image":
        try:
            size = "%d×%d" % (int(step.get("w")), int(step.get("h")))
        except (TypeError, ValueError, OverflowError):
            size = ""
        return ("Bấm vào vùng ảnh " + size).strip()
    if t == "tap_if":
        cases = step.get("cases") if isinstance(step.get("cases"), list) and step.get("cases") else [step]
        def one(c):
            seen = show(str(c.get("text") or ""), vars)
            if c.get("key"):
                return "Nếu thấy chữ «%s» thì nhấn phím %s" % (seen, str(c.get("key")).strip().lower())
            if isinstance(c.get("at"), (list, tuple)) and len(c["at"]) == 2:
                return "Nếu thấy chữ «%s» thì bấm tại (%s, %s)" % (seen, c["at"][0], c["at"][1])
            return "Nếu thấy chữ «%s» thì bấm «%s»" % (seen, show(str(c.get("tap") or "") or str(c.get("text") or ""), vars))
        out = "; ".join(one(c) for c in cases if isinstance(c, dict))
        if str(step.get("until") or "").strip():
            out += " (xong khi thấy «%s»)" % show(str(step.get("until")), vars)
        return out
    if t == "type":
        return f"Gõ «{show(str(step.get('text') or ''), vars)}»"
    if t == "key":
        return f"Phím {step.get('name')}"
    if t == "combo":
        return f"Tổ hợp {step.get('keys')}"
    if t == "launch":
        return f"Mở app {step.get('app')}" + (" (tắt hẳn rồi mở mới)" if step.get("fresh") else "")
    if t == "wait":
        return f"Chờ {step.get('seconds')}s"
    if t == "home":
        return "Về màn hình chính"
    if t == "swipe":
        if step.get("dir"):
            return "Vuốt %s" % SWIPE_DIRS.get(step.get("dir"), step.get("dir"))
        return "Vuốt (%s,%s) → (%s,%s)" % (step.get("x1"), step.get("y1"), step.get("x2"), step.get("y2"))
    if t == "hold":
        return "Bấm giữ (%s,%s) %ss" % (step.get("x"), step.get("y"), step.get("seconds", 1))
    if t == "hold_text":
        return "Bấm giữ chữ «%s» %ss" % (show(str(step.get("text") or ""), vars), step.get("seconds", 1))
    return str(t)


# ====================== thao tác cơ bản ======================
def _sleep(sec: float, abort=None):
    end = time.time() + max(0.0, sec)
    while True:
        if abort and abort():
            raise Aborted()
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(0.25, left))


def hid(nav, cmd: str, wait: float = 0.5):
    """Gửi 1 lệnh bàn phím/chuột ĐÚNG MỘT LẦN. Chỉ gửi lại khi board báo rõ «not-connected»
    (chắc chắn chưa làm gì). Trả (ok, lý do, acted) — acted=True: lệnh CÓ THỂ đã được thực hiện."""
    r = ""
    for _ in range(3):
        # Đếm TRƯỚC khi gửi: nếu cổng serial ném lỗi sau khi đã ghi lệnh thì bên gọi vẫn biết lệnh
        # có thể đã tới iPhone (xem JobFlow._buy_one — «không chắc» chứ không phải «chưa mua»).
        nav._hid_sent = getattr(nav, "_hid_sent", 0) + 1
        r = str(nav.h.send(cmd, wait=wait) or "")
        if r.startswith("OK"):
            return True, "", True
        if "not-connected" not in r:
            break
        nav.h.wait_connected(8)
        time.sleep(0.2)
    if "not-connected" in r:
        return False, "Bluetooth chưa nối với iPhone", False
    if r == "":
        return False, "board không phản hồi (không rõ lệnh đã chạy hay chưa)", True
    if r.startswith("ERR"):               # board TỪ CHỐI lệnh (sai cú pháp, phím lạ…) → chắc chắn chưa làm gì
        return False, "board báo lỗi «%s»" % r[:60], False
    # dòng lạ (vd một dòng log của board chen vào) KHÔNG chứng minh được là lệnh chưa chạy
    return False, "board trả lời lạ «%s» (không rõ lệnh đã chạy hay chưa)" % r[:60], True


KEY_SETTLE = 0.4        # nghỉ sau mỗi lệnh bàn phím (gõ / phím / tổ hợp) cho app kịp xử lý rồi mới làm bước kế


def _keyed(result, abort=None):
    """Sau một lệnh BÀN PHÍM đã gửi được: nghỉ KEY_SETTLE. Lệnh xuống board giờ trả về ngay khi board làm xong
    (trước đây mỗi lệnh tự trễ thêm ~0,4s) — giữ lại nhịp cũ cho bàn phím để ô nhập kịp nhận chữ, kịp chuyển ô sau
    phím Tab, Spotlight kịp hiện kết quả. Phần được tăng tốc là con trỏ và chụp màn hình, không phải bàn phím."""
    if result[0]:
        _sleep(KEY_SETTLE, abort)
    return result


def park(nav):
    """Đưa con trỏ về góc trên-trái để nó KHÔNG che chữ trên màn hình trước khi đọc (con trỏ nằm đè lên
    đúng chữ cần đọc thì OCR đọc hụt). Chỉ di chuột, không bấm gì → không tính là thao tác vào app."""
    try:
        nav.h.send("home")
    except Exception:
        pass


def _tap(nav, x: int, y: int, verify=None):
    """Đưa con trỏ tới (x,y) rồi MỚI bấm. Con trỏ không tới nơi thì KHÔNG bấm.
    `verify(ảnh)`: kiểm trên ảnh chụp gần nhất (lúc con trỏ chưa che đích) rằng thứ cần bấm VẪN ở đó —
    đưa con trỏ tới nơi mất hơn chục giây, màn hình có thể đã đổi (hộp thoại bật lên, danh sách trôi)."""
    if not nav.tap_at(int(x), int(y), click=False, verify=verify):
        why = getattr(nav, "miss", None)
        return False, "con trỏ không tới được vị trí cần bấm, hoặc màn hình đã đổi trước khi kịp bấm" + (
            " — %s" % why if isinstance(why, str) and why else ""), False
    return click(nav)


def click(nav):
    """Bấm tại chỗ con trỏ đang đứng, ĐÚNG MỘT LẦN (cùng quy ước trả về với hid()).
    Board thật: đánh thức con trỏ rồi bấm trong một mạch (xem Hands.WAKE) — con trỏ iOS «ngủ» sau ~2 giây
    đứng yên và cú bấm lúc đó có thể bị bỏ qua."""
    if not hasattr(nav.h, "burst"):
        return hid(nav, "click")
    wake = list(getattr(nav.h, "WAKE", ()))
    r = []
    for _ in range(3):
        nav._hid_sent = getattr(nav, "_hid_sent", 0) + 1       # đếm TRƯỚC khi gửi (xem hid)
        r = [str(x) for x in (nav.h.burst([*wake, "click", *wake], wait=1.0) or [])]
        if any(x.startswith("OK click") for x in r):
            return True, "", True
        # Chỉ gửi lại khi CHÍNH lệnh bấm (dòng thứ len(wake)+1) bị board từ chối vì chưa nối Bluetooth.
        # «not-connected» ở dòng khác (lệnh nhích) không nói gì về lệnh bấm: Bluetooth có thể vừa nối lại
        # đúng lúc đó, cú bấm đã chạy mà mất phản hồi — gửi lại sẽ thành bấm đôi.
        if not (len(r) > len(wake) and "not-connected" in r[len(wake)]):
            break
        nav.h.wait_connected(8)
        time.sleep(0.2)
    if len(r) > len(wake) and "not-connected" in r[len(wake)]:
        return False, "Bluetooth chưa nối với iPhone", False
    return False, "board không phản hồi đủ (không rõ lệnh bấm đã chạy hay chưa)", True


def gesture(nav, label: str, fn):
    """Chạy một cử chỉ nhiều lệnh (vuốt, bấm giữ) của Nav. Trả (ok, lý do, acted).
    Cử chỉ hỏng: nếu nút chuột CHƯA hề được nhấn (con trỏ không tới được điểm đầu) thì chắc chắn chưa chạm vào
    app → acted=False. Đã nhấn rồi mới hỏng, hoặc không biết được (máy không đếm số lần nhấn) → acted=True,
    bên gọi coi là «không chắc»."""
    before = getattr(nav.h, "presses", None)
    sent0 = getattr(nav, "_hid_sent", 0)
    nav._hid_sent = sent0 + 1                   # đếm TRƯỚC (xem hid): cử chỉ ném lỗi giữa chừng thì bên gọi vẫn biết có thể đã chạm
    ok = bool(fn())
    if ok:
        return True, "", True
    pressed = before is None or getattr(nav.h, "presses", None) != before
    if not pressed:
        nav._hid_sent = sent0                   # không có lệnh nhấn nào ra cổng
        return False, "%s không thực hiện được: con trỏ không tới được điểm bắt đầu (chưa chạm vào máy)" % label, False
    return False, "%s không trọn vẹn (board không phản hồi đủ — không rõ đã chạm vào máy hay chưa)" % label, True


def _still_there(nav, alts: list, pos, tol: int = 45):
    """Hàm kiểm cho bước «tap chữ»: chữ cần bấm còn nằm quanh vị trí cũ trên ảnh `img` không."""
    def check(img) -> bool:
        for a in alts:
            p = nav.e.find_text(a, img)
            if p and abs(p[0] - pos[0]) <= tol and abs(p[1] - pos[1]) <= tol:
                return True
        return False
    return check


def _screen_text(nav) -> str:
    return norm_text(nav.e.read_text(nav.e.screenshot()))


TEXT_WAIT_MAX = 60.0     # bước «bấm / giữ vào chữ» chịu chờ chữ hiện ra tối đa chừng này giây (trường `timeout` của bước)


def _text_wait(tmpl: dict, what: str) -> float:
    """Số giây một bước «bấm / giữ vào chữ» chịu chờ cho chữ HIỆN RA. Không ghi `timeout` (hoặc 0) = nhìn đúng một lần, như trước giờ."""
    try:
        return max(0.0, min(float(tmpl.get("timeout") or 0), TEXT_WAIT_MAX))
    except (TypeError, ValueError):
        raise ConfigError("bước «%s»: thời gian chờ chữ hiện ra phải là số giây" % what)


def _find_wait(nav, alts: list, wait: float, abort=None):
    """Tìm một trong các cách viết `alts` trên màn hình; chưa thấy thì nhìn lại mỗi giây cho tới hết `wait` giây. Trả (x, y) hoặc None.
    Màn hình game chuyển cảnh mất 1–3 giây nên nhìn MỘT lần ngay sau bước trước thường hụt (đo trên eFootball: bấm «Data Transfer»
    xong, 0,9 giây sau màn kế chưa vẽ xong). Thấy ở lần nhìn LẠI thì chữ có thể còn đang trượt vào → chờ màn hình đứng yên rồi lấy lại
    vị trí (lần nhìn đầu thì bên gọi đã chờ đứng yên sẵn)."""
    def look():
        img = nav.e.screenshot()
        return next((p for p in (nav.e.find_text(a, img) for a in alts) if p), None)
    end = time.time() + wait
    again = False
    while True:
        pos = look()
        if pos and again:
            _sleep(LOOK_SETTLE, abort)
            pos = look()
        if pos:
            return pos
        if time.time() >= end:
            return None
        again = True
        _sleep(1.0, abort)


# Không có «ngay trên»: trong một ô gói, giá nằm DƯỚI số coin, nên «ngay trên» với chữ cần tìm là số coin sẽ vớ giá của ô HÀNG TRÊN (cách
# ~139 px, gần hơn giá của chính ô đó). Bố cục có chữ đi kèm nằm trên thì ghi ngược lại: tìm chữ phía trên, chữ đi kèm là chữ ngay dưới nó.
NEAR_DIRS = {"below": "ngay dưới", "right": "bên phải", "left": "bên trái"}
SCROLLS_MAX = 20         # số lần lướt tối đa của bước «bấm vào chữ … chưa thấy thì lướt» (mỗi chiều)


def card_opts(tmpl: dict, vars: dict):
    """Tuỳ chọn «trong cùng ô» của bước bấm / kiểm chữ: {near_alts, near_label, dir, scroll, scrolls} hoặc None nếu bước không dùng.
    `near`: chữ PHẢI nằm cùng ô với chữ cần tìm (vd giá của gói); `near_dir`: chữ đó nằm ở đâu so với chữ cần tìm (mặc định ngay dưới);
    `scroll`: chưa thấy thì lướt danh sách theo hướng này (left / right / up / down); `scrolls`: lướt tối đa bao nhiêu lần (mặc định 8)."""
    near_raw = str(tmpl.get("near") or "")
    scroll = str(tmpl.get("scroll") or "").strip().lower()
    if not near_raw.strip() and not scroll:
        return None
    if scroll and scroll not in SWIPE_DIRS:
        raise ConfigError("hướng lướt «%s» không hỗ trợ (chỉ: left, right, up, down)" % scroll)
    d = str(tmpl.get("near_dir") or "below").strip().lower()
    if d not in NEAR_DIRS:
        raise ConfigError("vị trí của chữ đi kèm «%s» không hỗ trợ (chỉ: %s)" % (d, ", ".join(NEAR_DIRS)))
    try:
        n = int(tmpl.get("scrolls") if tmpl.get("scrolls") not in (None, "") else 8)
    except (TypeError, ValueError):
        raise ConfigError("bước «Bấm vào chữ»: số lần lướt phải là số")
    near_alts = alternatives(subst(near_raw, vars)) if near_raw.strip() else []
    if near_raw.strip() and not near_alts:
        raise ConfigError("bước «Bấm vào chữ»: chữ đi kèm trong ô đang để trống")
    return {"near_alts": near_alts, "near_label": show(near_raw, vars), "dir": d, "scroll": scroll or None,
            "scrolls": max(0, min(n, SCROLLS_MAX)), "label": None}


def _flat(s) -> str:
    return norm_text(s).replace(" ", "")


def _line_hits(lines: list, alts: list, size=None) -> list:
    """Các dòng mà CẢ DÒNG đúng bằng một trong `alts` (bỏ dấu câu / ký hiệu, không phân biệt hoa thường / dấu) — KHÔNG lấy dòng chỉ «có chứa»:
    «500» không khớp «1,500», «100» không khớp «Paid: 100», giá «26.000đ» không khớp «126.000đ». Bỏ dòng CHẠM MÉP màn hình (ô bị cắt dở:
    «1,500» bị cắt còn «500» sẽ thành khớp nhầm). Đọc chữ ra khác đi (vd «1.000» thay vì «1,000») thì khai thêm cách viết bằng «|»."""
    import ocr as _ocr
    want = [_flat(a) for a in alts if _flat(a)]
    W = size[0] if size else None
    out = []
    for ln in lines:
        if not any(_ocr.whole_line(_flat(ln.get("text")), w) for w in want):
            continue
        if W:
            half = float(ln.get("w") or 0) / 2.0
            if float(ln["x"]) - half <= 3 or float(ln["x"]) + half >= W - 3:
                continue
        if _number_piece(ln, lines):
            continue
        out.append(ln)
    return out


_NUMERIC = re.compile(r"^[0-9][0-9.,' ]*$|^[.,'][0-9][0-9.,' ]*$|^[0-9.,' ]*[0-9][.,']$")


def _number_piece(ln: dict, lines: list) -> bool:
    """Dòng toàn số này chỉ là MẢNH của một số lớn hơn: bộ đọc chữ có lúc tách «1,500» thành «1,» + «500» — mảnh «500» khớp nguyên dòng với
    gói 500 là bấm nhầm ô. Mảnh = có một dòng toàn số / dấu phân cách khác CÙNG HÀNG, nằm SÁT (khe hở không quá một chiều cao chữ)."""
    t = str(ln.get("text") or "").strip()
    if not _NUMERIC.match(t):
        return False
    x, y, w, h = float(ln["x"]), float(ln["y"]), float(ln.get("w") or 0), float(ln.get("h") or 0)
    for o in lines:
        if o is ln or not _NUMERIC.match(str(o.get("text") or "").strip()):
            continue
        ox, oy, ow, oh = float(o["x"]), float(o["y"]), float(o.get("w") or 0), float(o.get("h") or 0)
        hh = max(h, oh, 1.0)
        if abs(oy - y) <= 0.5 * hh and abs(ox - x) - (w + ow) / 2.0 <= hh:
            return True
    return False


def pick_card(lines: list, alts: list, near_alts: list, size, direction: str = "below"):
    """Trong các dòng chữ `lines` ([{text, x, y, w, h}]) của ảnh cỡ `size` = (W, H): dòng khớp `alts` mà CÙNG Ô có một dòng khớp `near_alts`
    nằm theo hướng `direction`. Trả (x, y) của dòng khớp `alts` (chỗ sẽ bấm), hoặc None.
    «Cùng ô» = lệch theo trục còn lại không quá 15% màn hình và cách theo trục hướng không quá 35% (dưới) hay 25% (trái / phải) màn
    hình (đo trên danh sách gói eFootball, iPhone 8 ngang: số coin và giá trong một ô thẳng cột, cách nhau ~146 px; ô bên cạnh cách ~590 px,
    hàng dưới ~285 px). Ngoài ra GIỮA hai chữ không được có dòng nào cùng loại với chữ cần tìm (một số coin khác = đã sang ô khác) — giá của
    ô hàng dưới / ô bên cạnh không ghép nhầm được vào số coin của ô này.
    Từ HAI ô trở lên cùng đủ điều kiện → None (nhập nhằng: không đoán — bấm nhầm ô là mua nhầm gói)."""
    W, H = size
    A = _line_hits(lines, alts, size)
    if not near_alts:
        return (int(A[0]["x"]), int(A[0]["y"])) if len(A) == 1 else None
    B = _line_hits(lines, near_alts, size)

    def fits(a, b):
        dx, dy = float(b["x"]) - float(a["x"]), float(b["y"]) - float(a["y"])
        if direction == "below":
            return abs(dx) <= 0.15 * W and 0 < dy <= 0.35 * H, dy
        along = dx if direction == "right" else -dx
        return abs(dy) <= 0.6 * max(float(a.get("h") or 0), float(b.get("h") or 0), 0.03 * H) and 0 < along <= 0.25 * W, along
    def kind(t):                                        # «loại» của một dòng: số thuần («1,500», «300») hay khung chữ («Starter Set: …»)
        f = re.sub(r"[^0-9a-z]", "", _flat(t))          # cả CỤM số thành một ký hiệu: «500 Coins» và «1,500 Coins» cùng loại «9coins»
        return "#" if f.isdigit() else re.sub(r"[0-9]+", "9", f)

    def between(a, b):                                  # các dòng nằm GIỮA a và b theo hướng đã chọn (cùng cột / cùng hàng)
        out = []
        for ln in lines:
            if ln is a or ln is b:
                continue
            if direction == "below":
                if abs(float(ln["x"]) - float(a["x"])) <= 0.15 * W and float(a["y"]) < float(ln["y"]) < float(b["y"]):
                    out.append(ln)
            elif abs(float(ln["y"]) - float(a["y"])) <= 0.6 * max(float(a.get("h") or 0), 0.03 * H) and \
                    min(float(a["x"]), float(b["x"])) < float(ln["x"]) < max(float(a["x"]), float(b["x"])):
                out.append(ln)
        return out
    pairs = [(a, b) for a in A for b in B if a is not b and fits(a, b)[0]]
    good = []
    for a, b in pairs:
        if any(kind(ln.get("text")) == kind(a.get("text")) for ln in between(a, b)):
            continue                                    # giữa hai chữ có một dòng CÙNG LOẠI với chữ cần tìm (số coin của ô khác) → đã sang ô khác
        good.append(a)
    if len({id(a) for a in good}) != 1:
        return None
    return int(good[0]["x"]), int(good[0]["y"])


def _card_look(nav, alts, card):
    img = nav.e.screenshot()
    lines = nav.e.text_lines(img)
    h, w = img.shape[:2] if hasattr(img, "shape") else (0, 0)
    if not w and lines:                                  # (máy giả không có ảnh thật) → ước cỡ màn hình theo chữ
        w = max(int(ln["x"]) + int(ln.get("w") or 0) for ln in lines) or 1
        h = max(int(ln["y"]) + int(ln.get("h") or 0) for ln in lines) or 1
    return pick_card(lines, alts, card["near_alts"], (w or 1, h or 1), card["dir"]), "\n".join(str(ln.get("text")) for ln in lines)


def _card_swipe(nav, direction: str):
    """Lướt danh sách một nhịp theo hướng ngón tay (left = kéo sang trái để xem phần bên phải). Kéo ~55% màn hình, giữa vùng nội dung."""
    img = nav.e.screenshot()
    H, W = img.shape[:2]
    r = None
    for k in (0.45, 0.62):                               # con trỏ không tới được điểm bắt đầu (chưa chạm gì) → thử lại ở độ cao khác một lần
        pts = {"left": (0.78 * W, k * H, 0.23 * W, k * H), "right": (0.22 * W, k * H, 0.77 * W, k * H),
               "up": (k * W, 0.75 * H, k * W, 0.3 * H), "down": (k * W, 0.3 * H, k * W, 0.75 * H)}[direction]
        r = gesture(nav, "lướt %s" % SWIPE_DIRS[direction], lambda: nav.swipe(*[int(v) for v in pts]))
        if r[0] or r[2]:
            return r
    return r


def _find_card(nav, alts, card, wait: float, abort=None):
    """Tìm ô (xem pick_card); chưa thấy thì nhìn lại tới hết `wait` giây, rồi (nếu có `scroll`) lướt danh sách theo hướng đó, hết danh
    sách (lướt mà chữ trên màn hình không đổi) hoặc đủ số lần thì lướt NGƯỢC lại (máy có thể đang đứng giữa danh sách). Trả ((x, y) | None,
    lý do, acted) — acted = đã có thao tác lướt (đã chạm vào máy)."""
    label = "«%s»" % card["label"] if card.get("label") is not None else " / ".join("«%s»" % a for a in alts)
    what = label + ((" có «%s» %s" % (card["near_label"], NEAR_DIRS[card["dir"]])) if card["near_alts"] else "")
    park(nav)
    _sleep(LOOK_SETTLE, abort)
    end = time.time() + wait
    while True:
        pos, seen = _card_look(nav, alts, card)
        if pos:
            return pos, "", False
        if time.time() >= end:
            break
        _sleep(1.0, abort)
    if not card["scroll"]:
        return None, ("chờ %gs không thấy ô %s" % (wait, what)) if wait else "không thấy ô %s trên màn hình" % what, False
    back = {"left": "right", "right": "left", "up": "down", "down": "up"}[card["scroll"]]
    # Một cú lướt HOÀN TẤT chỉ trượt danh sách, không bấm vào gì → không tính là «đã chạm» (không thấy gói sau khi lướt = «chưa mua», không
    # phải «không chắc»: gói sale hết hạn không được làm máy dừng chờ đối soát). Chỉ cú lướt hỏng GIỮA CHỪNG (không rõ đã nhả nút chưa —
    # có thể thành một cú bấm) mới là «đã chạm».
    acted, swipes = False, 0
    for direction, limit in ((card["scroll"], card["scrolls"]), (back, 2 * card["scrolls"])):
        for _ in range(limit):
            ok, why, a = _card_swipe(nav, direction)
            if not ok:
                return None, why, a
            swipes += 1
            park(nav)
            _sleep(LOOK_SETTLE, abort)
            pos, now = _card_look(nav, alts, card)
            if pos:
                _sleep(LOOK_SETTLE, abort)              # danh sách có thể còn trôi → chờ đứng yên rồi lấy lại vị trí
                pos2, _ = _card_look(nav, alts, card)
                if pos2:
                    return pos2, "", acted
                continue
            if now == seen:
                break                                   # lướt mà màn hình không đổi = hết danh sách theo hướng này
            seen = now
    return None, "lướt hết danh sách (%d lần) không thấy ô %s" % (swipes, what), acted


def _card_still_there(nav, alts, card, pos, tol: int = 45):
    """Hàm kiểm của bước bấm vào ô: ô đó (chữ + chữ đi kèm) còn ở quanh vị trí cũ trên ảnh `img` không."""
    def check(img) -> bool:
        lines = nav.e.text_lines(img)
        h, w = img.shape[:2] if hasattr(img, "shape") else (1, 1)
        p = pick_card(lines, alts, card["near_alts"], (w, h), card["dir"])
        return bool(p) and abs(p[0] - pos[0]) <= tol and abs(p[1] - pos[1]) <= tol
    return check


TYPE_GAP_MAX = 2.0       # quãng nghỉ dài nhất giữa hai ký tự của bước «gõ chữ» (trường `gap`)
IMAGE_MIN = 0.9          # độ giống tối thiểu mặc định của bước «bấm vào vùng ảnh» (xem eyes.locate_image)


def step_image(tmpl: dict):
    """Đọc bước «bấm vào vùng ảnh»: (ảnh mẫu BGR, độ giống tối thiểu 0,5…0,99, chỗ hình được cắt ra (cx, cy) | None). Sai → ConfigError."""
    try:
        pic = decode_image(tmpl.get("image"))
    except ValueError as e:
        raise ConfigError("bước «Bấm vào vùng ảnh»: %s" % e)
    try:
        need = float(tmpl.get("min") or IMAGE_MIN)
    except (TypeError, ValueError):
        raise ConfigError("bước «Bấm vào vùng ảnh»: độ giống tối thiểu phải là số")
    if not (need > 0):                                   # số âm, 0, NaN → mặc định (không tụt về mức dễ dãi nhất)
        need = IMAGE_MIN
    if need > 1:                                         # ghi theo phần trăm (90) cũng nhận
        need /= 100.0
    need = max(0.5, min(need, 0.99))
    try:
        near = (int(tmpl["x"]) + int(tmpl["w"]) // 2, int(tmpl["y"]) + int(tmpl["h"]) // 2)
    except (KeyError, TypeError, ValueError, OverflowError):
        near = None
    return pic, need, near


def _find_image_wait(nav, pic, need: float, near, wait: float, abort=None):
    """Tìm ảnh mẫu trên màn hình; chưa thấy thì nhìn lại mỗi giây tới hết `wait` giây. Trả ((x, y) | None, điểm giống cao nhất đã gặp).
    Thấy ở lần nhìn LẠI thì chờ màn hình đứng yên rồi lấy lại vị trí (như _find_wait)."""
    def look():
        return nav.e.find_image(pic, nav.e.screenshot(), need, near)
    end = time.time() + wait
    again, top = False, 0.0
    while True:
        pos, score = look()
        top = max(top, score)
        if pos and again:
            _sleep(LOOK_SETTLE, abort)
            pos, score = look()
            top = max(top, score)
        if pos:
            return pos, top
        if time.time() >= end:
            return None, top
        again = True
        _sleep(1.0, abort)


def _image_still_there(nav, pic, need: float, pos, tol: int = 45):
    """Hàm kiểm cho bước «bấm vào vùng ảnh»: hình cần bấm còn nằm quanh vị trí cũ trên ảnh `img` không."""
    def check(img) -> bool:
        p, _ = nav.e.find_image(pic, img, need, pos)
        return bool(p) and abs(p[0] - pos[0]) <= tol and abs(p[1] - pos[1]) <= tol
    return check


def _not_seen(label: str, wait: float) -> str:
    return ("chờ %gs không thấy chữ «%s» trên màn hình" % (wait, label)) if wait else "không thấy chữ «%s» trên màn hình" % label


def observed_what(step: dict, vars: dict) -> str:
    """Lời mô tả bước để GHI LỊCH SỬ. Bước gõ chữ ghi TRỰC TIẾP (không qua {{biến}}) có thể là mật khẩu gõ tay → chỉ ghi số ký tự."""
    if _literal_typed(step):
        return "Gõ %d ký tự" % len(str(step.get("text") or "")) + (" (bỏ qua nếu lỗi)" if step.get("optional") else "")
    return describe(step, vars)


def _literal_typed(step: dict) -> str:
    """Chữ gõ TRỰC TIẾP của bước «gõ chữ» (không qua {{biến}}) — có thể là mật khẩu gõ tay; "" nếu không phải."""
    raw = str(step.get("text") or "") if step.get("type") == "type" else ""
    return raw if raw and not PLACEHOLDER.search(raw) else ""


def observed_why(step: dict, why) -> str:
    """Lời kết quả của bước để GHI LỊCH SỬ / lời báo của đơn: bỏ chữ gõ trực tiếp («…» trong lời mô tả bước có nhắc lại nó) ra khỏi lời."""
    why = str(why or "")
    raw = _literal_typed(step)
    return why.replace("«%s»" % raw, "«(%d ký tự)»" % len(raw)) if raw else why


def said(step: dict, vars: dict) -> str:
    """Tên bước trong lời báo HỎNG của một giai đoạn / đơn (đi vào nhật ký, lời báo của đơn, lịch sử): như describe nhưng bước gõ chữ
    trực tiếp chỉ nói số ký tự."""
    return observed_what(step, vars) if _literal_typed(step) else _describe(step, vars)


def watch_phase(nav, label, total=None, start=0):
    """Báo cho bộ theo dõi của máy (nav.observer — xem history.Tracker): sắp chạy một DANH SÁCH bước (giai đoạn `label`, `total` bước),
    bắt đầu từ bước thứ `start` (0 = đầu; «chạy tiếp từ bước N» thì các bước được đếm tiếp từ N)."""
    obs = getattr(nav, "observer", None)
    if obs is not None:
        try:
            obs.phase(label, total, start) if start else obs.phase(label, total)
        except Exception:
            pass


def exec_step(nav, tmpl: dict, vars: dict, abort=None):
    """Chạy 1 bước (mẫu chưa thế biến). Trả (ok, lý do, acted). Lý do không chứa giá trị bí mật.
    Máy có bộ theo dõi (nav.observer) thì báo cho nó lúc BẮT ĐẦU và lúc XONG bước — «máy nào đang chạy bước nào» + lịch sử. Chữ báo đi là
    lời mô tả ĐÃ CHE (describe: giữ nguyên tên {{username}}, {{password}}, {{otp}}). Theo dõi trục trặc không bao giờ làm hỏng bước."""
    obs = getattr(nav, "observer", None)
    if obs is None:
        return _exec_step(nav, tmpl, vars, abort)
    try:
        obs.step_begin(observed_what(tmpl, vars), tmpl.get("type"))
    except Exception:
        return _exec_step(nav, tmpl, vars, abort)
    try:
        r = _exec_step(nav, tmpl, vars, abort)
    except Aborted:
        obs.step_end(False, "đã dừng theo yêu cầu")
        raise
    except (ConfigError, InputError) as e:              # lời của hai loại lỗi này do tool tạo ra (đã che biến bí mật; chữ gõ trực tiếp bỏ ra ở observed_why)
        obs.step_end(False, observed_why(tmpl, e))
        raise
    except Exception as e:
        obs.step_end(False, "lỗi: %s" % e.__class__.__name__)
        raise
    obs.step_end(r[0], observed_why(tmpl, r[1]))
    return r


def _exec_step(nav, tmpl: dict, vars: dict, abort=None):
    if abort and abort():
        raise Aborted()
    t = tmpl.get("type")
    if t == "tap":
        return _tap(nav, tmpl.get("x", 0), tmpl.get("y", 0))

    if t in ("tap_text", "wait_text", "assert_text"):
        raw = str(tmpl.get("text") or "")
        alts = alternatives(subst(raw, vars))
        if not alts:
            raise ConfigError("bước dò chữ đang để trống chữ cần tìm")
        label = show(raw, vars)
        if t != "wait_text":                    # bước chờ thì tự nhìn lại nhiều lần, không cần chờ trước
            _sleep(LOOK_SETTLE, abort)
        card = card_opts(tmpl, vars) if t != "wait_text" else None
        if card:
            # «Bấm vào chữ A trong ô có chữ B» (vd số coin + giá của MỘT gói): tìm đúng ô, chưa thấy thì lướt danh sách để tìm
            wait = _text_wait(tmpl, "Bấm vào chữ")
            card["label"] = label                       # lời báo chỉ dùng chữ đã che (show): {{username}}… giữ nguyên tên
            pos, why, acted = _find_card(nav, alts, card, wait, abort)
            if not pos:
                return False, why, acted
            if t == "assert_text":
                return True, "", acted
            ok, why2, acted2 = _tap(nav, pos[0], pos[1], verify=_card_still_there(nav, alts, card, pos))
            return ok, why2, acted or acted2
        if t == "tap_text":
            wait = _text_wait(tmpl, "Bấm vào chữ")
            pos = _find_wait(nav, alts, wait, abort)
            if not pos:
                return False, _not_seen(label, wait), False
            return _tap(nav, pos[0], pos[1], verify=_still_there(nav, alts, pos))
        if t == "assert_text":
            txt = _screen_text(nav)
            ok = any(text_has(txt, a) for a in alts)
            return ok, ("" if ok else "màn hình không có chữ «%s»" % label), False
        timeout = float(tmpl.get("timeout") or 20)
        end = time.time() + timeout
        while True:
            txt = _screen_text(nav)
            if any(text_has(txt, a) for a in alts):
                return True, "", False
            if time.time() >= end:
                return False, "chờ %ds không thấy chữ «%s»" % (int(timeout), label), False
            _sleep(1.0, abort)

    if t == "tap_image":
        # «Bấm vào VÙNG ẢNH»: tìm đúng hình đã cắt từ ảnh màn hình (nút không có chữ, biểu tượng…) rồi bấm vào GIỮA hình — thay cho bấm
        # theo toạ độ cố định (toạ độ thì bấm bừa cả khi nút chưa hiện / màn hình khác). `timeout`: hình chưa hiện thì nhìn lại tới hết
        # ngần ấy giây; `min`: độ giống tối thiểu (mặc định 0,9); `x,y,w,h`: chỗ hình được cắt ra — có nhiều chỗ giống thì lấy chỗ gần đó nhất.
        pic, need, near = step_image(tmpl)
        wait = _text_wait(tmpl, "Bấm vào vùng ảnh")
        park(nav)               # con trỏ còn nằm trên chính hình cần tìm (vd vừa bấm nút đó ở bước trước) thì điểm giống tụt dưới ngưỡng
        _sleep(LOOK_SETTLE, abort)
        pos, best = _find_image_wait(nav, pic, need, near, wait, abort)
        if not pos and best >= IMAGE_TOO_MANY:
            return False, "có quá nhiều chỗ giống hệt vùng ảnh cần bấm trên màn hình — khoanh vùng đặc trưng hơn (kèm chữ / biểu tượng riêng của nút)", False
        if not pos:
            return False, "%s vùng ảnh cần bấm trên màn hình (chỗ giống nhất %d%%, cần %d%%)" % (
                ("chờ %gs không thấy" % wait) if wait else "không thấy", int(best * 100), int(round(need * 100))), False
        return _tap(nav, pos[0], pos[1], verify=_image_still_there(nav, pic, need, pos))

    if t == "tap_if":
        # «NẾU thấy chữ A THÌ bấm chữ B» (hoặc nhấn một PHÍM) — cho thứ LÚC CÓ LÚC KHÔNG ngay sau một bước (hộp thoại Game Center, hỏi
        # lưu mật khẩu, thông báo, quảng cáo…). Một bước có thể mang NHIỀU trường hợp (`cases`); mỗi lần nhìn, trường hợp nào thấy trước
        # thì xử lý trước.
        #   • chờ tối đa `timeout` giây xem có trường hợp nào hiện ra không; KHÔNG thấy gì → bước XONG, không làm gì;
        #   • thấy → bấm chữ (hoặc nhấn phím) của trường hợp đó rồi NHÌN LẠI: còn thấy thì làm lại (cú bấm lên hộp thoại hệ thống có lúc
        #     không «ăn» — đo trên iPhone 8), hết thì xong. Bước nhiều trường hợp còn chờ thêm `timeout` giây xem hộp thoại KHÁC có hiện
        #     nối theo không; bước một trường hợp thì xong ngay khi hộp thoại đã đóng;
        #   • làm IF_REPEAT lần mà vẫn thấy, hoặc hết thời gian chờ mà thấy chữ nhưng không có chữ cần bấm → bước HỎNG (màn hình đang bị
        #     chắn — đi tiếp là bấm nhầm). Vì thế đừng dùng bước này cho thứ bấm xong VẪN CÒN trên màn hình (thẻ, nút bật / tắt): dùng
        #     «bấm vào chữ».
        cases = if_cases(tmpl, vars)
        # `until`: chữ chỉ hiện khi KHÔNG còn hộp thoại nào che (vd tab «Shop» của màn chính) → thấy nó mà không thấy trường hợp nào thì XONG
        # ngay, không chờ hết `timeout`. Nhờ vậy chờ được lâu (hộp thoại hiện muộn sau khi game tải) mà không tốn thời gian khi đã sạch.
        until = alternatives(subst(str(tmpl.get("until") or ""), vars))
        try:
            timeout = max(0.0, min(float(tmpl.get("timeout") or 0), 120.0))
        except (TypeError, ValueError):
            raise ConfigError("bước «Nếu thấy chữ … thì bấm»: thời gian chờ phải là số giây")
        done, hits, acted_any = [], [0] * len(cases), False
        # Chỗ chữ của từng trường hợp lúc được xử lý (where), đã từng mất đi sau đó chưa (gone), đã cho thêm thời gian chờ nút hiện chưa
        # (regrace) — để phân biệt «chữ còn ở CHỖ KHÁC sau khi hộp thoại đóng» với «hộp thoại HIỆN LẠI mà nút chưa kịp hiện».
        where, gone, regrace = [None] * len(cases), [False] * len(cases), [False] * len(cases)
        flips = 0                                     # số lần «thấy lại rồi lại không thấy» (chữ nhấp nháy / đọc lúc được lúc không)

        def case_at(c, img):
            return next((p for p in (nav.e.find_text(a, img) for a in c["alts"]) if p), None)

        def same_place(p, q, img):
            tol = max(40.0, 0.05 * max(img.shape[:2])) if hasattr(img, "shape") else 40.0
            return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
        end = time.time() + timeout
        until_since = None                            # lúc bắt đầu thấy chữ «until» liên tục (màn hình sạch phải giữ đủ UNTIL_STABLE giây)
        _sleep(LOOK_SETTLE, abort)
        while True:
            if flips > IF_FLIPS_MAX:                  # chốt dừng: không kết luận được hộp thoại đã đóng hay chưa thì DỪNG, không nhìn mãi
                return False, "hộp thoại lúc thấy lúc không sau %d lần nhìn lại — không xác định được đã đóng hay chưa" % flips, acted_any
            img = nav.e.screenshot()
            txt = norm_text(nav.e.read_text(img))
            # Trường hợp «bấm chữ» chỉ «xảy ra» khi thấy CẢ chữ của nó LẪN chữ cần bấm. Thấy chữ mà chưa thấy nút (hộp thoại đang trượt
            # vào, hoặc đây là một màn hình khác cũng có chữ đó — vd «Tính năng mới trong Game Center» chỉ có nút «Tiếp tục») thì xét
            # trường hợp kế; không trường hợp nào đủ thì NHÌN LẠI tới hết thời gian chờ rồi mới báo hỏng. Trường hợp «nhấn phím»: thấy chữ là đủ.
            k, pos, blocked = None, None, None
            for i, c in enumerate(cases):
                if not any(text_has(txt, a) for a in c["alts"]):
                    gone[i] = gone[i] or bool(hits[i])
                    continue
                if c["key"] or c["at"]:
                    k = i
                    break
                pos = next((p for p in (nav.e.find_text(a, img) for a in c["tap_alts"]) if p), None)
                if pos:
                    k = i
                    break
                if hits[i]:
                    # Đã xử lý rồi mà chữ còn, nút không còn: chữ ở CHỖ KHÁC (vd «konami.net» trên thanh địa chỉ của trang vừa mở) = hộp
                    # thoại đã đóng; chữ ở ĐÚNG CHỖ cũ (không đo được chỗ thì: chữ đã mất rồi hiện lại) = hộp thoại HIỆN LẠI, nút chưa kịp hiện.
                    p = case_at(c, img)
                    if not (same_place(p, where[i], img) if (p and where[i]) else gone[i]):
                        continue
                    if not regrace[i]:                # cho nút thêm IF_REAPPEAR_WAIT giây để hiện (hộp thoại đang trượt vào)
                        regrace[i] = True
                        end = max(end, time.time() + IF_REAPPEAR_WAIT)
                blocked = blocked or c                # thấy chữ mà không có nút để bấm: màn hình đang bị chắn
            if k is None:
                # «Sạch» = thấy chữ «until» mà không có trường hợp nào, LIÊN TỤC đủ UNTIL_STABLE giây (đo trên eFootball: tab «Shop» hiện
                # thoáng qua vài giây TRƯỚC khi «Login Bonus» / «Sign Players» trượt vào — kết luận ở lần thấy đầu là quá sớm).
                if until and not blocked and any(text_has(txt, u) for u in until):
                    until_since = until_since or time.time()
                else:
                    until_since = None
                clear = until_since is not None and time.time() - until_since >= UNTIL_STABLE
                if clear or time.time() >= end:
                    if blocked:
                        return False, "thấy chữ «%s» nhưng không thấy chữ «%s» để bấm" % (blocked["label"], blocked["tap_label"]), acted_any
                    if not done:
                        return True, ("thấy «%s» — không có gì phải xử lý" % show(str(tmpl.get("until")), vars)) if clear else \
                            "không thấy %s — bỏ qua" % " / ".join("«%s»" % c["label"] for c in cases), acted_any
                    if len(cases) == 1:
                        c = cases[0]
                        return True, "thấy «%s» → đã %s%s" % (c["label"], c["act"], (" (%d lần)" % hits[0]) if hits[0] > 1 else ""), acted_any
                    return True, "đã " + ", ".join(done), acted_any
                _sleep(1.0, abort)
                continue
            c = cases[k]
            if hits[k]:
                # Đã xử lý trường hợp này rồi mà vẫn thấy: hộp thoại ĐÓNG CHẬM hay cú bấm không ăn? Chờ thêm rồi nhìn lại một lần nữa —
                # vẫn còn mới làm lại (nhấn phím esc lần hai lúc hộp thoại đã tự đóng sẽ rơi vào màn hình bên dưới).
                _sleep(IF_RECHECK, abort)
                img = nav.e.screenshot()
                if not any(text_has(norm_text(nav.e.read_text(img)), a) for a in c["alts"]):
                    flips += 1
                    continue                          # đã đóng trong lúc chờ → nhìn lại từ đầu
                if not c["key"] and not c["at"]:
                    pos = next((p for p in (nav.e.find_text(a, img) for a in c["tap_alts"]) if p), None)
                    if not pos:
                        flips += 1
                        continue
            if not c["at"]:
                where[k] = case_at(c, img)            # nhớ chỗ chữ của hộp thoại lúc xử lý (xem `same_place` ở trên)
            gone[k] = regrace[k] = False
            hits[k] += 1
            if hits[k] > IF_REPEAT:
                return False, "đã %s %d lần mà vẫn còn thấy «%s» (hộp thoại không đóng)" % (c["act"], IF_REPEAT, c["label"]), acted_any
            if len(done) >= IF_MAX_TAPS:
                return False, "đã xử lý %d hộp thoại liên tiếp mà vẫn còn thấy «%s» — dừng lại (một bước xử lý tối đa %d lần)" % (len(done), c["label"], IF_MAX_TAPS), acted_any
            until_since = None
            if c["key"]:
                ok, why, acted = _keyed(hid(nav, "key " + c["key"]), abort)
            elif c["at"]:
                # nút không đọc được chữ (vd «OK» xanh nhạt của hộp «Sign Players»): bấm theo toạ độ — nhưng CHỈ khi chữ của hộp thoại còn
                # đang hiện ngay trước cú bấm (không bấm mù vào chỗ đó khi hộp thoại đã đóng)
                ok, why, acted = _tap(nav, c["at"][0], c["at"][1], verify=lambda im, c=c: any(text_has(norm_text(nav.e.read_text(im)), a) for a in c["alts"]))
            else:
                ok, why, acted = _tap(nav, pos[0], pos[1], verify=_still_there(nav, c["tap_alts"], pos))
            acted_any = acted_any or acted
            if not ok:
                if hits[k] > 1 and not acted:
                    # Lần bấm LẶP không thực hiện được (màn hình đổi trước khi con trỏ tới nơi): rất có thể hộp thoại vừa tự đóng trong lúc
                    # con trỏ đang đi → nhìn lại; đã hết thì lần bấm trước là đủ, không tính đây là lỗi.
                    _sleep(LOOK_SETTLE, abort)
                    if not any(text_has(norm_text(nav.e.read_text(nav.e.screenshot())), a) for a in c["alts"]):
                        hits[k] -= 1
                        flips += 1
                        end = time.time() + (timeout if len(cases) > 1 else 0)
                        continue
                return False, why, acted_any
            done.append("%s (thấy «%s»)" % (c["act"], c["label"]))
            _sleep(IF_AFTER_TAP, abort)               # cho hộp thoại vừa xử lý kịp đóng / hộp thoại kế kịp hiện
            end = time.time() + (timeout if len(cases) > 1 else 0)      # một trường hợp: chỉ nhìn lại xem hộp thoại đã đóng chưa

    if t == "type":
        text = typable(str(tmpl.get("text") or ""), vars)
        if text == "":
            return True, "", False
        try:
            gap = max(0.0, min(float(tmpl.get("gap") or 0), TYPE_GAP_MAX))
        except (TypeError, ValueError):
            raise ConfigError("bước «Gõ chữ»: quãng nghỉ giữa các ký tự phải là số giây")
        if gap <= 0:
            return _keyed(hid(nav, "type " + text, wait=0.8 + 0.08 * len(text)), abort)
        # Gõ TỪNG ký tự, nghỉ `gap` giây sau mỗi ký tự: ô mã «mỗi số một ô» tự nhảy sang ô kế bằng mã của trang, gõ liền một mạch thì
        # các phím tới trong lúc trang đang chuyển ô bị rơi (đo trên trang mã xác minh của KONAMI: gõ liền 6 số chỉ vào được 2 số).
        acted = False
        for ch in text:
            ok, why, a = hid(nav, "key space" if ch == " " else "type " + ch, wait=0.8)
            acted = acted or a
            if not ok:
                return False, why, acted
            _sleep(gap, abort)
        _sleep(max(0.0, KEY_SETTLE - gap), abort)        # sau ký tự cuối vẫn nghỉ đủ nhịp bàn phím như mọi lệnh gõ khác
        return True, "", True

    if t == "key":
        name = str(tmpl.get("name") or "").strip().lower()
        if name not in KEYS:
            raise ConfigError("phím «%s» không hỗ trợ (chỉ: %s)" % (name, ", ".join(KEYS)))
        return _keyed(hid(nav, "key " + name), abort)

    if t == "combo":
        if not str(tmpl.get("keys") or "").strip():
            raise ConfigError("bước «Tổ hợp phím» đang để trống")
        return _keyed(hid(nav, "combo " + combo_keys(tmpl.get("keys"))), abort)

    if t == "home":
        r = hid(nav, "combo gui h")
        _sleep(1.2, abort)
        return r

    if t == "launch":           # về home → Spotlight → xoá ô → gõ tên app → Enter
        app = subst(str(tmpl.get("app") or ""), vars).strip()
        if not app:
            raise ConfigError("bước «Mở app» đang để trống tên app")
        fresh = tmpl.get("fresh")
        fresh = fresh is True or fresh == 1 or (isinstance(fresh, str) and fresh.strip().lower() in ("1", "true", "yes"))
        if not fresh and any(not (32 <= ord(c) <= 126) for c in app):
            raise ConfigError("tên app ở bước «Mở app» chỉ gõ được chữ không dấu (vd «Settings», «eFootball») — «%s» có ký tự không gõ được" % app)
        if fresh:
            # «Tắt hẳn rồi mở MỚI» qua USB (không gõ phím): mở bằng ô tìm kiếm chỉ đưa app ra trước, app đang chạy dở ở màn nào thì
            # vẫn ở màn đó — kịch bản chạy lại sau một lượt dở dang sẽ bắt đầu từ một màn hình bất kỳ. Không làm được thì HỎNG
            # (không lặng lẽ quay về cách mở cũ: người viết kịch bản đã yêu cầu «bắt đầu từ màn đầu»).
            try:
                nav.e.relaunch(app)
            except LookupError as e:                 # không chọn được app theo tên → chắc chắn chưa đụng gì vào máy
                return False, "không tắt hẳn / mở mới được app «%s»: %s" % (app, e), False
            except Exception as e:                   # hết giờ, rút cáp… → app CÓ THỂ đã bị tắt mà chưa mở lại được
                return False, "không tắt hẳn / mở mới được app «%s»: %s" % (app, e), True
            _sleep(FRESH_SETTLE, abort)
            return True, "đã tắt hẳn rồi mở mới", True
        acted = False
        # Quãng nghỉ sau từng phím: Spotlight cần thời gian mở ra và CHỌN xong kết quả đầu trước khi nhận Enter
        # (nhấn Enter sớm thì app không mở — gặp trên máy thật khi lệnh xuống board được gửi nhanh hơn).
        for cmd, pause in (("combo gui h", 1.1), ("combo gui space", 1.7), ("combo cmd a", 0.6),
                           ("key back", 0.8), ("type " + app, 1.7), ("key enter", 3.0)):
            ok, why, a = hid(nav, cmd, wait=(0.8 + 0.08 * len(app)) if cmd.startswith("type ") else 0.5)
            acted = acted or a
            if not ok:
                return False, why, acted
            _sleep(pause, abort)
        return True, "", True

    if t == "wait":
        _sleep(float(tmpl.get("seconds") or 1), abort)
        return True, "", False

    if t == "swipe":
        if tmpl.get("dir"):
            d = str(tmpl.get("dir")).lower()
            if d not in SWIPE_DIRS:
                raise ConfigError("hướng vuốt «%s» không hỗ trợ (chỉ: left, right, up, down)" % d)
            return gesture(nav, "vuốt %s" % SWIPE_DIRS[d], lambda: nav.flick(d))
        try:
            pts = [int(tmpl[k]) for k in ("x1", "y1", "x2", "y2")]
        except (KeyError, TypeError, ValueError):
            raise ConfigError("bước «Vuốt» thiếu hướng hoặc toạ độ x1,y1 → x2,y2")
        return gesture(nav, "vuốt", lambda: nav.swipe(*pts))

    if t == "hold":
        sec = max(0.2, min(float(tmpl.get("seconds") or 1.0), 10.0))
        return gesture(nav, "bấm giữ", lambda: nav.hold_at(int(tmpl.get("x", 0)), int(tmpl.get("y", 0)), sec))

    if t == "hold_text":
        raw = str(tmpl.get("text") or "")
        alts = alternatives(subst(raw, vars))
        if not alts:
            raise ConfigError("bước «Bấm giữ vào chữ» đang để trống chữ cần tìm")
        sec = max(0.2, min(float(tmpl.get("seconds") or 1.0), 10.0))
        wait = _text_wait(tmpl, "Bấm giữ vào chữ")
        _sleep(LOOK_SETTLE, abort)
        pos = _find_wait(nav, alts, wait, abort)
        if not pos:
            return False, _not_seen(show(raw, vars), wait), False
        return gesture(nav, "bấm giữ", lambda: nav.hold_at(pos[0], pos[1], sec, verify=_still_there(nav, alts, pos)))

    raise ConfigError("loại bước lạ: %s" % t)


IF_REPEAT = 2            # cùng một trường hợp của bước «nếu … thì bấm» được bấm tối đa chừng này lần (bấm rồi vẫn thấy mãi = hộp thoại không đóng)
IF_MAX_TAPS = 6          # tổng số lần bấm tối đa của một bước «nếu … thì bấm»
IF_AFTER_TAP = 1.2       # nghỉ sau mỗi lần bấm rồi mới nhìn lại
UNTIL_STABLE = 4.0       # bước «nếu thấy chữ…» có `until`: màn hình phải «sạch» liên tục chừng này giây mới kết thúc sớm
IF_FLIPS_MAX = 4         # số lần tối đa «thấy lại hộp thoại vừa xử lý rồi lại không thấy» trong một bước; quá thì dừng (không nhìn mãi)
IF_REAPPEAR_WAIT = 3.0   # hộp thoại VỪA xử lý hiện lại (chữ ở đúng chỗ cũ) mà nút chưa thấy: chờ nút thêm chừng này rồi mới báo «bị chắn»
IF_RECHECK = 1.5        # thấy lại một hộp thoại VỪA xử lý: chờ thêm chừng này rồi nhìn lần nữa, vẫn còn mới làm lại (hộp thoại đóng chậm ≠ cú bấm không ăn)


def if_cases(tmpl: dict, vars: dict) -> list:
    """Các trường hợp của bước «nếu thấy chữ … thì bấm …»: [{alts, tap_alts, label, tap_label, key, act}].
    Bước ghi `cases: [{text, tap | key}, …]` (nhiều trường hợp) hoặc `text` + `tap` / `key` (một trường hợp). `tap` để trống = bấm chính chữ
    vừa thấy. `key` = nhấn PHÍM đó thay cho bấm (hộp «lưu mật khẩu» của iOS không nhận cú bấm của con trỏ, chỉ đóng được bằng phím esc)."""
    raw_cases = tmpl.get("cases") if isinstance(tmpl.get("cases"), list) and tmpl.get("cases") else [{"text": tmpl.get("text"), "tap": tmpl.get("tap"), "key": tmpl.get("key"), "at": tmpl.get("at")}]
    out = []
    for c in raw_cases[:12]:
        if not isinstance(c, dict):
            raise ConfigError("bước «Nếu thấy chữ … thì bấm»: mỗi trường hợp phải ghi chữ cần thấy")
        raw = str(c.get("text") or "")
        alts = alternatives(subst(raw, vars))
        if not alts:
            raise ConfigError("bước «Nếu thấy chữ … thì bấm» đang để trống chữ cần thấy")
        key = str(c.get("key") or "").strip().lower()
        if key and key not in KEYS:
            raise ConfigError("bước «Nếu thấy chữ … thì nhấn phím»: phím «%s» không hỗ trợ (chỉ: %s)" % (key, ", ".join(KEYS)))
        at = None
        if c.get("at") is not None and not key:
            try:
                at = (int(c["at"][0]), int(c["at"][1]))
                if len(c["at"]) != 2 or min(at) < 0:
                    raise ValueError
            except (TypeError, ValueError, IndexError, KeyError, OverflowError):
                raise ConfigError("bước «Nếu thấy chữ … thì bấm tại»: toạ độ phải là hai số x, y")
        tap_raw = str(c.get("tap") or "") or raw
        tap_label = show(tap_raw, vars)
        act = ("nhấn phím %s" % key) if key else ("bấm tại (%d, %d)" % at) if at else "bấm «%s»" % tap_label
        out.append({"alts": alts, "tap_alts": alternatives(subst(tap_raw, vars)) or alts, "label": show(raw, vars), "tap_label": tap_label,
                    "key": key, "at": at, "act": act})
    return out


def typable(raw: str, vars: dict) -> str:
    """Chữ sẽ gõ của một bước «gõ chữ» (đã thế {{biến}}); ném InputError nếu tool không gõ được (ký tự có dấu, khoảng trắng cuối…)."""
    text = subst(raw, vars)
    # tên chữ trong lời báo: chữ có {{biến}} thì giữ TÊN biến (show); chữ gõ trực tiếp (có thể là mật khẩu gõ tay) thì chỉ nói số ký tự
    label = "«%s»" % show(raw, vars) if PLACEHOLDER.search(raw) else "chữ gõ trực tiếp (%d ký tự)" % len(raw)
    if any(not (32 <= ord(c) <= 126) for c in text):
        raise InputError("%s có ký tự tool không gõ được (chỉ gõ được chữ không dấu, số, ký hiệu thường)" % label)
    if text != text.rstrip():
        raise InputError("%s kết thúc bằng khoảng trắng — tool không gõ được" % label)
    return text


def check_typable(steps: list, vars: dict):
    """Kiểm TRƯỚC khi chạy: mọi bước «gõ chữ» trong `steps` đều gõ được với dữ liệu này (không thì ném InputError) — để một tài khoản /
    mật khẩu tool không gõ được bị từ chối NGAY, khi chưa đụng gì vào game (không gõ dở nửa chừng)."""
    for st in steps or []:
        if st.get("type") == "type":
            typable(str(st.get("text") or ""), vars)


SCREEN_WAIT = 8.0        # màn hình khác ảnh mẫu của bước: chờ tối đa chừng này giây (game đang chuyển màn / hiệu ứng) rồi mới coi là «lạ»


def capture_screen(nav):
    """ẢNH MẪU của màn hình đang hiện (cho bước sắp làm): đưa con trỏ ra góc (không che chữ), chụp + đọc chữ HAI lần cách nhau một nhịp,
    chỉ giữ chữ thấy ở cả hai lần (xem screencheck.capture)."""
    import screencheck
    park(nav)
    time.sleep(0.3)
    img = nav.e.screenshot()
    lines = nav.e.text_lines(img)
    time.sleep(0.5)
    return screencheck.capture(img, lines, nav.e.text_lines(nav.e.screenshot()))


def screen_gate(nav, step: dict, abort=None):
    """KIỂM MÀN HÌNH trước khi làm bước (chỉ bước thao tác có ảnh mẫu — xem screencheck.wants_check). Trả (ok, lý do).
    • Khớp ảnh mẫu (ngay, hoặc trong SCREEN_WAIT giây) → (True, "").
    • Vẫn khác: bước «bỏ qua nếu lỗi» → (False, lý do) để bên gọi bỏ qua bước (không tạm dừng máy vì một bước được phép bỏ qua).
      Máy có `nav.screen_helper` (bộ chạy gắn vào khi chạy thật: hỏi AI xử lý quảng cáo, không được thì TẠM DỪNG MÁY chờ admin bấm
      Tiếp tục) thì giao cho nó — nó trả (ok, lý do). Không có (chạy thử, AI / dòng lệnh điều khiển) → (False, lý do): không làm bước.
    • Chụp / đọc chữ lỗi giữa chừng: tính là một lần nhìn hỏng, nhìn lại tới hết thời gian chờ (không làm hỏng cả lượt chạy).
    Bị dừng ngay (`abort`) giữa lúc chờ → ném Aborted như mọi bước khác."""
    import screencheck
    if not screencheck.wants_check(step):
        return True, ""
    ref = step["screen"]
    end = time.time() + SCREEN_WAIT
    img, sc, err, parked = None, None, None, False
    while True:
        try:
            shot = nav.e.screenshot()
            cur = screencheck.score(ref, shot, nav.e.text_lines(shot))
            img, sc, err = shot, cur, None
            if cur["ok"]:
                return True, ""
        except Aborted:
            raise
        except Exception as e:
            err = e
        if time.time() >= end:
            break
        if not parked:                              # con trỏ nằm đè lên chữ làm tụt điểm: cất ra góc rồi nhìn lại
            park(nav)
            parked = True
        _sleep(1.0, abort)
    why = screencheck.describe(sc) if sc is not None else "không đọc được màn hình để so với ảnh mẫu (%s)" % (err or "?")
    helper = getattr(nav, "screen_helper", None)
    if helper is None or step.get("optional"):
        return False, why
    return helper(step, why, img)


def run_steps(nav, steps: list, vars: dict, abort=None, on_step=None):
    """Chạy tuần tự, dừng ở bước lỗi đầu tiên.
    Trả (ok, lý do, chỉ_số_bước_lỗi|None, touched) — touched: đã có thao tác nào (có thể) tới máy chưa."""
    touched = False
    for i, st in enumerate(steps):
        if on_step:
            on_step(i, st)
        seen, why = screen_gate(nav, st, abort)
        if not seen:                                    # màn hình không phải màn hình của bước này → KHÔNG làm bước (bấm nhầm còn tệ hơn)
            if st.get("optional"):
                continue
            return False, "%s — %s" % (said(st, vars), why), i, touched
        ok, why, acted = exec_step(nav, st, vars, abort)
        touched = touched or acted or (ok and st.get("type") in INPUT_TYPES)
        if not ok and not st.get("optional"):
            return False, "%s — %s" % (said(st, vars), observed_why(st, why)), i, touched
        _sleep(STEP_GAP, abort)
    return True, "", None, touched


# ====================== nhận diện trạng thái bằng luật ======================
def match_rule(text_norm: str, rules: list, when: str):
    for r in rules:
        if r.get("when") != when:
            continue
        for alt in alternatives(str(r.get("value") or "")):
            if text_has(text_norm, alt):
                return r
    return None


def wait_rules(nav, rules: list, whens: list, timeout: float, abort=None, interval: float = 1.0):
    """Chụp màn + OCR lặp lại tới khi khớp 1 trong `whens` (xét theo THỨ TỰ ưu tiên đưa vào).
    Trả (when, luật) hoặc (None, None) khi hết giờ."""
    end = time.time() + timeout
    while True:
        if abort and abort():
            raise Aborted()
        try:
            txt = _screen_text(nav)
        except Exception:
            txt = ""                      # chụp/OCR lỗi tạm thời → thử lại tới hết giờ
        for w in whens:
            r = match_rule(txt, rules, w)
            if r:
                return w, r
        if time.time() >= end:
            return None, None
        _sleep(interval, abort)


def shot_jpeg(nav):
    """Ảnh màn hình hiện tại dạng JPEG (nhẹ hơn PNG nhiều lần) hoặc None nếu không chụp được."""
    try:
        ok, buf = cv2.imencode(".jpg", nav.e.screenshot(), [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buf.tobytes() if ok else None
    except Exception:
        return None


def preflight(nav):
    """Máy có sẵn sàng nhận đơn không? Trả None nếu ổn, hoặc lý do (chuỗi)."""
    ok, heard = False, False
    for _ in range(3):                    # phản hồi status đầu tiên đôi khi còn là giá trị cũ
        try:
            r = str(nav.h.send("status") or "")
        except Exception as e:            # cổng serial hỏng / board đã rút
            return "board ESP32 không trả lời — cổng serial lỗi (%s)" % e
        heard = heard or bool(r)
        if "ble=connected" in r:
            ok = True
            break
        time.sleep(0.4)
    if not ok:
        return "Bluetooth chưa nối với iPhone" if heard else "board ESP32 không trả lời (kiểm tra cáp USB / nguồn của board)"
    try:
        nav.e.screenshot()
    except Exception:
        return "không chụp được màn hình (kiểm tra cáp USB / Developer Mode / DDI)"
    return None


def validate(pool: dict, steps: dict) -> list:
    """Pool + các bước đã ĐỦ để máy tự chạy đơn chưa? Trả danh sách điều còn thiếu (rỗng = đủ).
    Thiếu thì máy không nhận đơn — thà đứng yên còn hơn chạy mà không phân biệt được «đã nạp» với
    «chưa nạp», hay «đang đăng nhập tài khoản khách này» với «tài khoản khách trước»."""
    out = ["thiếu luật «%s»" % label for label in missing_rules(pool)]
    for ph in REQUIRED_PHASES:
        if not steps.get(ph):
            out.append("chưa có bước «%s»" % PHASE_LABEL[ph])
    return out


def missing_rules(pool: dict) -> list:
    """Tên các luật bắt buộc mà pool chưa có (luật chỉ đặt được trên gateway, nhóm máy không ghi đè được)."""
    have = {r.get("when") for r in (pool.get("rules") or []) if str(r.get("value") or "").strip()}
    return [label for when, label in REQUIRED_RULES.items() if when not in have]


def _is_credential(st: dict) -> bool:
    """Bước gõ có dùng {{biến}} (tài khoản, mật khẩu…) — khác với gõ chữ cố định như tên app trong Spotlight."""
    return st.get("type") == "type" and bool(PLACEHOLDER.search(str(st.get("text") or "")))


def open_prefix(login: list) -> list:
    """«Đoạn mở game» của danh sách đăng nhập: các bước ĐẦU chỉ mở/chờ, chưa bấm vào đâu và chưa gõ gì của
    khách (mở app, tổ hợp phím, gõ chữ cố định, phím, chờ…). Dừng ở bước bấm đầu tiên hoặc bước gõ {{biến}}.
    Chạy lại đoạn này bao nhiêu lần cũng không làm game đổi trạng thái đăng nhập.
    Ngoại lệ có chủ ý: bước «nếu thấy chữ … thì bấm» (tap_if) VẪN thuộc đoạn mở game — nó dùng để dọn thứ chắn màn hình ngay sau khi
    mở app (hộp thoại Game Center, thông báo…); không dọn thì bước kiểm «game chưa đăng nhập» không nhìn thấy gì và máy không nhận đơn.
    Đừng dùng nó để bấm vào thứ đụng tới tài khoản của khách."""
    out = []
    for st in login or []:
        t = st.get("type")
        if t in ("tap", "tap_text", "tap_image", "hold", "hold_text", "swipe") or _is_credential(st):
            break
        out.append(st)
    return out


def credential_gate(login: list) -> int:
    """Chỉ số bước mà TRƯỚC khi chạy nó phải thấy màn hình chưa đăng nhập: bước gõ {{biến}} đầu tiên.
    Danh sách không gõ tài khoản (đăng nhập bằng cách bấm) thì chặn ngay sau đoạn mở game."""
    for i, st in enumerate(login or []):
        if _is_credential(st):
            return i
    return min(len(open_prefix(login)), max(len(login or []) - 1, 0))


def session_probe(nav, steps: dict, rules: list, timeout: float, abort=None) -> str:
    """Game đang ở trạng thái nào: "out" (chắc chắn chưa ai đăng nhập) | "in" (đang đăng nhập) |
    "unknown" (không nhận ra màn hình). Chỉ chạy «đoạn mở game» (xem open_prefix) rồi đọc màn hình —
    không gõ gì của khách; thứ duy nhất được bấm là hộp thoại chắn màn hình mà bước «nếu thấy chữ … thì bấm» trong đoạn đó dọn đi. Bước chờ/kiểm chữ trong đoạn đó hỏng thì bỏ qua (khi game
    đang đăng nhập sẵn thì màn hình chờ của nó khác)."""
    prefix = open_prefix(steps.get("login") or [])
    watch_phase(nav, "Kiểm game trước khi nhận đơn", len(prefix))
    for st in prefix:
        ok, why, _ = exec_step(nav, st, {}, abort)
        if not ok and st.get("type") not in ("wait_text", "assert_text") and not st.get("optional"):
            return "unknown"
    park(nav)
    w, _ = wait_rules(nav, rules, ["login_success", "logged_out"], timeout, abort)
    return {"login_success": "in", "logged_out": "out"}.get(w, "unknown")


# ====================== kết quả 1 đơn ======================
class Outcome:
    def __init__(self, result, message: str = "", items: list | None = None, fault: bool = False, halt: bool = False,
                 session: str = "unknown"):
        self.result = result          # "done" | "failed" | "review" | None (gateway đã đóng đơn → không báo)
        self.message = message
        self.items = items or []
        self.fault = fault            # True = lỗi phía tool/máy (không phải do tài khoản của khách)
        self.halt = halt              # True = máy phải DỪNG chờ người kiểm tra (không nhận đơn tiếp)
        # phiên đăng nhập trong game SAU đơn này: "none" chắc chắn chưa đăng nhập (vd sai mật khẩu)
        # · "in" đang đăng nhập · "unknown" không chắc → bước đăng xuất phải chạy được, không thì dừng máy
        self.session = session

    def to_dict(self) -> dict:
        return {"result": self.result, "message": self.message, "items": self.items, "fault": self.fault,
                "halt": self.halt, "session": self.session}

    @staticmethod
    def from_dict(d: dict) -> "Outcome":
        return Outcome(d.get("result"), d.get("message") or "", d.get("items") or [], bool(d.get("fault")),
                       bool(d.get("halt")), d.get("session") or "unknown")


class JobFlow:
    """Chạy trọn 1 đơn. `run()` luôn trả Outcome, không ném lỗi ra ngoài."""

    def __init__(self, nav, gw, job: dict, pool: dict, steps: dict, opts: dict | None = None,
                 status=None, log=None, abort=None, on_purchase_start=None):
        self.nav, self.gw, self.job, self.pool, self.steps = nav, gw, job, pool, steps
        opts = opts or {}
        self.login_wait = float(opts.get("login_wait", 45))
        self.purchase_wait = float(opts.get("purchase_wait", 60))
        self.otp_wait = int(opts.get("otp_wait", 20))
        self.status_cb, self.log_cb, self.abort = status, log, abort
        self.on_purchase_start = on_purchase_start
        self.jid = job["id"]
        self.rules = pool.get("rules") or []
        self.risky = False            # True = đã chạm luồng mua, CHƯA xác nhận kết quả → không được báo failed
        self.session = "none"         # none | in | unknown (xem Outcome.session)
        self.bought = 0
        self.seq = 0
        self.results = []
        self._marked = False
        self.clear_wait = float(opts.get("clear_wait", 8))      # chờ hộp thoại «nạp thành công» cũ biến mất
        # số lần đã xin OTP cho đơn này (đơn nhận lại sau khi tool khởi động lại thì đếm tiếp, không đếm lại)
        self.otp_n = int((job.get("otp") or {}).get("seq") or 0)

    # ---------- tiện ích ----------
    def _say(self, text, kind=""):
        if self.log_cb:
            self.log_cb(text, kind)

    def _status(self, text):
        if self.status_cb:
            self.status_cb(text)

    def _note(self, rule) -> str:
        n = (rule or {}).get("note") or ""
        return (": " + n) if n else ""

    def _progress(self, stage, message=None):
        self._status(message or stage)
        try:
            call_retry(lambda: self.gw.progress(self.jid, stage, message), tries=3)
        except GatewayError as e:
            if e.status in (404, 409):
                raise JobGone(e.body.get("status") or e.error)
            raise

    def _phase(self, phase, vars):
        steps = self.steps.get(phase) or []
        watch_phase(self.nav, PHASE_LABEL[phase], len(steps))
        ok, why, idx, touched = run_steps(self.nav, steps, vars, self.abort)
        if not ok:
            self._say("%s: lỗi ở bước %d — %s" % (PHASE_LABEL[phase], idx + 1, why), "bad")
        return ok, why, idx, touched

    def _upload(self, kind):
        if kind == "bill":                      # hộp thoại «nạp thành công» vừa hiện: chờ nó hiện hẳn rồi mới chụp bill
            _sleep(0.6, self.abort)
        data = shot_jpeg(self.nav)
        if not data:
            self._say("Không chụp được ảnh %s" % kind, "bad")
            return False
        self.seq += 1
        try:
            call_retry(lambda: self.gw.upload_image(self.jid, self.seq, kind, data), tries=3)
            return True
        except GatewayError as e:
            self._say("Gửi ảnh %s lỗi: %s" % (kind, e.vi()), "bad")
            return False

    def _items(self) -> list:
        done = {r["code"]: r for r in self.results}
        out = []
        for it in self.job.get("items") or []:
            qty = int(it.get("qty") or 1)
            r = done.get(it.get("code"))
            if not r:
                out.append({"code": it.get("code"), "qty_done": 0, "status": "skipped", "message": "chưa xử lý tới"})
                continue
            status = "done" if r["qty_done"] >= qty else (r["status"] if r["status"] != "done" else "skipped")
            out.append({"code": r["code"], "qty_done": r["qty_done"], "status": status, "message": r.get("message") or ""})
        return out

    def _finalize(self, reason: str = "", fault: bool = False) -> Outcome:
        items = self._items()
        total = sum(int(it.get("qty") or 1) for it in self.job.get("items") or [])
        done = sum(i["qty_done"] for i in items)
        if self.risky:
            return Outcome("review", reason or "Không xác nhận được kết quả mua", items)
        if total > 0 and done >= total:
            return Outcome("done", "Nạp đủ %d gói" % total, items)
        if done == 0:
            return Outcome("failed", reason or "Chưa nạp được gói nào", items, fault)
        return Outcome("review", "Nạp được %d/%d gói — %s" % (done, total, reason or "phần còn lại chưa nạp"), items)

    # ---------- luồng chính ----------
    def run(self) -> Outcome:
        out = self._run()
        out.session = self.session
        return out

    def _run(self) -> Outcome:
        try:
            return self._flow()
        except JobGone as e:
            if self.bought or self.risky:
                # gateway đã tự đóng đơn (vd tool im lặng quá lâu) nhưng tool ĐÃ mua / đã chạm mua →
                # vẫn gửi lời báo để người đối soát có số liệu (gateway ghi vào nhật ký đơn, không đổi trạng thái)
                out = self._finalize("Gateway đã đóng đơn (%s) khi tool đang mua" % e)
                out.result = "review"
                return out
            return Outcome(None, "Gateway đã đóng đơn này (%s) — dừng, không báo kết quả" % e)
        except Aborted:
            return self._finalize("Người vận hành dừng máy giữa chừng")
        except StaleSession:
            out = self._finalize("Máy vẫn đang đăng nhập tài khoản của đơn trước — chưa nạp gì cho đơn này", fault=True)
            out.halt = True
            return out
        except InputError as e:
            return self._finalize(str(e))
        except ConfigError as e:
            return self._finalize("Cấu hình bước sai: %s" % e, fault=True)
        except GatewayError as e:
            return self._finalize("Lỗi gateway giữa chừng: %s" % e.vi(), fault=True)
        except Exception as e:      # lỗi bất ngờ (rớt cổng serial, mất USB…)
            return self._finalize("Lỗi tool: %s" % e, fault=True)

    def _flow(self) -> Outcome:
        vars = {str(k): v for k, v in (self.job.get("login") or {}).items()}
        missing = validate(self.pool, self.steps)
        if missing:
            raise ConfigError("pool chưa đủ cấu hình (%s)" % "; ".join(missing))

        # 1) đăng nhập
        self._progress("login", "Đang đăng nhập")
        login = self.steps.get("login") or []
        # Điểm chặn: ngay trước bước gõ {{tài khoản}} đầu tiên (không gõ tài khoản thì ngay sau đoạn mở game).
        gate = credential_gate(login)

        def before_step(i, st):
            # CHỈ được gõ tài khoản của khách khi THẤY màn hình chưa đăng nhập. Thấy «đăng nhập thành công»
            # = phiên của khách TRƯỚC còn sót (đăng xuất hỏng) → làm tiếp là nạp nhầm tài khoản người khác.
            if i != gate:
                return
            park(self.nav)
            w, _ = wait_rules(self.nav, self.rules, ["login_success", "logged_out"], min(12.0, self.login_wait), self.abort)
            if w == "login_success":
                raise StaleSession()
            if w != "logged_out":
                raise NotAtLogin()
            # Từ ĐÂY tool bắt đầu gõ tài khoản của khách. Nếu bị dừng ngang giữa các bước đăng nhập (Dừng ngay, lỗi…) thì không còn chắc
            # «chưa ai đăng nhập» nữa — game có thể đã vào tài khoản của khách. Đánh dấu ngay bây giờ, không đợi các bước đăng nhập chạy xong.
            self.session = "unknown"

        check_typable(login, vars)        # tài khoản / mật khẩu không gõ được → từ chối ngay, khi phiên còn chắc chắn «chưa đăng nhập»
        watch_phase(self.nav, PHASE_LABEL["login"], len(login))
        try:
            ok, why, idx, _ = run_steps(self.nav, login, vars, self.abort, on_step=before_step)
        except StaleSession:
            self.session = "in"
            raise
        except NotAtLogin:
            self.session = "unknown"
            return self._finalize("Không nhận ra màn hình đăng nhập trước khi gõ tài khoản "
                                  "(xem luật «Màn hình CHƯA đăng nhập» của pool)", fault=True)
        self.session = "unknown"      # đã thao tác trên màn đăng nhập: chưa biết vào được hay không
        if not ok:
            self._say("%s: lỗi ở bước %d — %s" % (PHASE_LABEL["login"], idx + 1, why), "bad")
            if idx < gate:            # hỏng TRƯỚC cả lúc gõ tài khoản: có phải vì game đang đăng nhập sẵn người khác?
                try:
                    stale = match_rule(_screen_text(self.nav), self.rules, "login_success")
                except Exception:
                    stale = None
                if stale:
                    self.session = "in"
                    raise StaleSession()
            return self._finalize("Lỗi bước đăng nhập: " + why, fault=True)
        state, rule = wait_rules(self.nav, self.rules, ["login_fail", "need_otp", "login_success"], self.login_wait, self.abort)
        if state is None:
            return self._finalize("Không xác định được kết quả đăng nhập sau %d giây" % self.login_wait, fault=True)
        if state == "login_fail":
            self.session = "none"       # game từ chối → chắc chắn chưa có ai đăng nhập
            return self._finalize("Đăng nhập thất bại" + self._note(rule))

        # 2) OTP
        if state == "need_otp":
            out = self._otp(vars)
            if out is not None:
                return out

        # 3) tới danh sách gói
        self.session = "in"
        self._progress("logged_in", "Đăng nhập thành công")
        ok, why, _, _ = self._phase("nav", vars)
        if not ok:
            return self._finalize("Lỗi đường vào danh sách gói: " + why, fault=True)

        # 4) mua từng gói
        for item in self.job.get("items") or []:
            qty = int(item.get("qty") or 1)
            res = {"code": item.get("code"), "qty_done": 0, "status": "done", "message": ""}
            self.results.append(res)
            name = item.get("name") or item.get("code")
            pv = dict(vars)                             # biến dùng trong bước mua: thêm thông tin gói
            pv.update({"package.ocr_text": item.get("ocr_text") or item.get("name") or "",
                       "package.price_text": item.get("price_text") or "",
                       "package.name": item.get("name") or "", "package.code": item.get("code") or ""})
            for n in range(qty):
                # gateway còn coi đơn đang chạy thì mới được mua (409 → JobGone, dừng trước khi tốn tiền)
                self._progress("purchasing", "Đang mua %s (%d/%d)" % (name, n + 1, qty))
                if not self._marked:
                    self._marked = True
                    if self.on_purchase_start:
                        self.on_purchase_start()        # ghi sổ cục bộ TRƯỚC khi chạm vào luồng mua
                verdict, why = self._buy_one(item, pv)
                if verdict == "ok":
                    res["qty_done"] += 1
                    self.bought += 1
                    self._say("Đã mua %s (%d/%d)" % (name, n + 1, qty), "ok")
                    self._upload("bill")
                    last = item is (self.job.get("items") or [])[-1] and n == qty - 1
                    ok, why2, _, _ = self._phase("after", pv)
                    if not ok and not last:
                        return self._finalize("Mua xong nhưng không quay lại được danh sách gói: " + why2, fault=True)
                    continue
                res["status"] = "unavailable" if verdict == "unavailable" else "failed"
                res["message"] = why
                if verdict == "uncertain":
                    return self._finalize(why)          # self.risky đang True → review
                # không mua được gói này (chắc chắn chưa tốn tiền) → dừng, không mò tiếp từ màn hình lạ
                return self._finalize("%s: %s" % (name, why), fault=verdict in ("failed_tool", "stale"))
        return self._finalize()

    # ---------- mua 1 gói ----------
    def _buy_one(self, item: dict, pv: dict):
        """Mua 1 lần gói `item` (pv = biến đã gồm thông tin gói).
        Trả (verdict, lý do): ok | unavailable | failed | failed_tool | stale | uncertain."""
        # (1) Màn hình phải SẠCH chữ kết quả trước khi mua. Nếu chữ «nạp thành công» của lần trước còn đó
        #     (hộp thoại chưa đóng) thì sau khi bấm mua không thể biết nó là của lần nào → đếm nhầm
        #     «đã mua» cho lần chưa mua. Chờ một chút cho hộp thoại tự tắt; còn thì DỪNG, không mua.
        #     KHÔNG quyết bằng một lần nhìn (một khung hình đang vẽ dở hay một lần OCR đọc hụt là đủ sai):
        #       • chữ «thành công» phải VẮNG ở PRE_LOOKS lần nhìn LIỀN NHAU mới coi là sạch;
        #       • chữ «thất bại» / «không mua được» thấy ở BẤT KỲ lần nhìn nào đều tính là có SẴN (vd nhãn in
        #         trên ô gói khác) → không dùng nó để kết luận cho lần mua này.
        end = time.time() + self.clear_wait
        park(self.nav)          # con trỏ còn nằm trên nút vừa bấm có thể che đúng chữ cần đọc
        _sleep(LOOK_SETTLE, self.abort)
        preset, clean = set(), 0
        while True:
            try:
                txt = _screen_text(self.nav)
            except Exception as e:                  # chụp/OCR lỗi tạm thời → thử lại; hết giờ vẫn lỗi thì chưa chạm gì
                if time.time() >= end:
                    return "failed_tool", "không đọc được màn hình trước khi mua (%s)" % e
                clean = 0
                _sleep(1.0, self.abort)
                continue
            seen = [k for k in RESULT_RULES if match_rule(txt, self.rules, k)]
            preset.update(k for k in seen if k != "purchase_success")
            if "purchase_success" in seen:
                clean = 0
                if time.time() >= end:
                    return "stale", ("màn hình vẫn còn chữ «nạp thành công» của lần mua trước — hộp thoại chưa đóng "
                                     "(thêm bước đóng ở «Sau mỗi lần mua») hoặc chữ của luật có sẵn trên màn hình")
            else:
                clean += 1
                if clean >= self.PRE_LOOKS:
                    break
            _sleep(0.6 if clean else 1.0, self.abort)
        pre = [k for k in RESULT_RULES if k in preset]
        # chữ «thất bại» / «không mua được» đã có SẴN (vd nhãn in trên ô gói khác) thì không dùng để kết luận
        # cho lần mua này; chỉ chữ MỚI xuất hiện mới có nghĩa.
        fresh = [k for k in RESULT_RULES if k not in pre]
        if pre:
            self._say("Trước khi mua màn hình đã có sẵn chữ của luật %s — bỏ qua các luật đó cho lần mua này"
                      % ", ".join("«%s»" % k for k in pre))

        # (2) chạy các bước mua
        plist = self.steps["purchase"]
        watch_phase(self.nav, PHASE_LABEL["purchase"], len(plist))
        fail_why = ""
        failed = False
        touched = False
        for i, st in enumerate(plist):
            # Kiểm màn hình trước bước mua (bước có ảnh mẫu): khác ảnh mẫu → không làm bước này. Chưa chạm gì → «lỗi tool»;
            # đã chạm (risky) → đi tiếp xuống phần đọc kết quả như mọi lần mua dở (không chắc thì đối soát, không báo «chưa mua»).
            # `buying`: bộ xử lý màn hình lạ không cho AI bấm trong giai đoạn mua. Đếm lệnh xuống board TỪ TRƯỚC bước kiểm: lệnh nào đi ra
            # trong lúc kiểm (cất con trỏ, hay bất cứ cú bấm nào) cũng làm đơn thành «không chắc», không bao giờ thành «chắc chắn chưa mua».
            sent0 = getattr(self.nav, "_hid_sent", 0)
            try:
                self.nav.buying = True
            except Exception:
                pass
            try:
                seen, gwhy = screen_gate(self.nav, st, self.abort)
            finally:
                try:
                    self.nav.buying = False
                except Exception:
                    pass
            if getattr(self.nav, "_hid_sent", 0) != sent0:     # có lệnh bấm / gõ ra board trong lúc kiểm màn hình → coi như đã chạm
                touched = True
                self.risky = True
            if not seen:
                if st.get("optional"):
                    continue
                failed, fail_why = True, "%s — %s" % (said(st, pv), gwhy)
                break
            try:
                ok, why, acted = exec_step(self.nav, st, pv, self.abort)
            except Exception:
                # Bước ném lỗi giữa chừng (rớt cổng serial…): nếu lệnh bấm/gõ ĐÃ được ghi ra cổng thì
                # iPhone có thể đã nhận → «không chắc», tuyệt đối không được báo «chưa mua».
                if getattr(self.nav, "_hid_sent", 0) != sent0:
                    self.risky = True
                raise
            # bước có điều kiện xong theo hai kiểu — đã bấm (acted) hay không thấy nên bỏ qua (chưa đụng gì vào máy): chỉ kiểu đầu mới là «đã chạm»
            if acted or (ok and st.get("type") in INPUT_TYPES and st.get("type") != "tap_if"):
                touched = True
                self.risky = True                       # từ đây: chưa xác nhận thì không được báo failed
            if not ok and not st.get("optional"):
                failed, fail_why = True, "%s — %s" % (said(st, pv), observed_why(st, why))
                break
            _sleep(STEP_GAP, self.abort)
        if not touched:                                  # lỗi trước khi chạm vào gì (vd không thấy ô gói)
            return "failed_tool", "không bắt đầu mua được (%s)" % fail_why

        # (3) đọc kết quả: chỉ chữ MỚI xuất hiện sau khi bấm (cất con trỏ để nó không che chữ)
        park(self.nav)
        w, rule = self._read_result(fresh)
        if w == "purchase_success":
            self.risky = False
            return "ok", ""
        if w == "purchase_fail":
            self.risky = False
            return "failed", "game báo nạp thất bại" + self._note(rule)
        if w == "package_unavailable":
            self.risky = False
            return "unavailable", "gói không mua được (đã mua / hết lượt)" + self._note(rule)
        return "uncertain", "Không xác nhận được kết quả mua «%s» sau %d giây%s" % (
            item.get("name") or item.get("code"), self.purchase_wait, (" (" + fail_why + ")") if failed else "")

    PRE_LOOKS = 3           # số lần nhìn LIỀN NHAU phải sạch chữ «nạp thành công» trước khi được mua
    NEG_LOOKS = 2           # chữ «thất bại» / «không mua được» phải thấy ở bấy nhiêu lần nhìn LIỀN NHAU…
    NEG_GRACE = 30.0        # …và đã hiện ít nhất bấy nhiêu giây mà vẫn không thấy «thành công» thì mới kết luận.
                            # Dài có chủ ý: game / mạng chậm có thể hiện «thành công» tới 15–20 s sau khi bấm, trong khi một
                            # nhãn có sẵn («Đã mua gói này») ở ô khác của cửa hàng có thể hiện muộn hơn cả lần kiểm trước khi
                            # mua. Chỉ tốn thời gian ở đường «thất bại» (hiếm) — đổi lại không báo sai «chưa nạp» cho đơn đã trừ tiền.
                            # CỐ ĐỊNH, không co theo purchase_wait: purchase_wait ngắn hơn (~40 s) thì không bao giờ đủ thời gian
                            # để kết luận «thất bại» → đơn chuyển ĐỐI SOÁT (hướng an toàn), không bao giờ báo sai.

    def _read_result(self, fresh: list):
        """Đọc kết quả một lần mua. Trả (luật khớp, chi tiết luật) hoặc (None, None) nếu hết giờ vẫn chưa rõ.

        «Thành công» thắng: thấy chữ nạp thành công (mới xuất hiện) ở bất kỳ lần nhìn nào là xong.
        «Thất bại» / «không mua được» thì KHÔNG kết luận ngay ở lần nhìn đầu tiên: phải thấy ở NEG_LOOKS lần
        nhìn liền nhau và đã hiện được NEG_GRACE giây mà vẫn không có chữ thành công. Lý do: báo «chưa nạp» cho
        một đơn thật ra ĐÃ trừ tiền là sai lầm đắt nhất — một nhãn có sẵn bị đọc hụt lúc kiểm trước khi mua, hay
        một lần OCR đọc nhầm, không được phép quyết định thay cho kết quả thật đang hiện ra chậm."""
        end = time.time() + self.purchase_wait
        grace = self.NEG_GRACE
        neg, neg_rule, neg_count, neg_at = None, None, 0, 0.0
        while True:
            if self.abort and self.abort():
                raise Aborted()
            try:
                txt = _screen_text(self.nav)
            except Exception:
                txt = None                      # chụp/OCR lỗi tạm thời → coi như chưa nhìn được, thử lại
            if txt is not None:
                if "purchase_success" in fresh:
                    r = match_rule(txt, self.rules, "purchase_success")
                    if r:
                        return "purchase_success", r
                hit = next(((k, match_rule(txt, self.rules, k)) for k in fresh
                            if k != "purchase_success" and match_rule(txt, self.rules, k)), None)
                if hit is None:
                    neg, neg_count = None, 0
                else:
                    if hit[0] != neg:
                        neg, neg_count, neg_at = hit[0], 0, time.time()
                    neg_rule, neg_count = hit[1], neg_count + 1
                    if neg_count >= self.NEG_LOOKS and time.time() - neg_at >= grace:
                        return neg, neg_rule
            if time.time() >= end:
                # hết giờ: chữ báo lỗi phải đã hiện ỔN ĐỊNH đủ NEG_LOOKS lần nhìn VÀ đủ `grace` giây (như trên) mới nhận;
                # chưa đủ chắc thì «không xác nhận được» (đơn chuyển đối soát — an toàn hơn là báo sai)
                stable = bool(neg) and neg_count >= self.NEG_LOOKS and time.time() - neg_at >= grace
                return (neg, neg_rule) if stable else (None, None)
            _sleep(1.0, self.abort)

    # ---------- OTP ----------
    def _otp(self, vars: dict):
        """Xin OTP → chờ khách → nhập. Trả None nếu qua được, hoặc Outcome nếu thất bại."""
        reason = "first"
        net_since = None
        while True:
            self.otp_n += 1                     # gửi lại vì mất phản hồi dùng CÙNG số này → không tốn thêm lượt
            attempt = self.otp_n
            try:
                call_retry(lambda: self.gw.otp_request(self.jid, reason, attempt=attempt), tries=3)
            except GatewayError as e:
                if e.error == "otp_limit":
                    return self._finalize("Hết số lần xin OTP (khách nhập sai hoặc không kịp nhập)")
                if e.error == "otp_disabled":
                    return self._finalize("Game đòi OTP nhưng pool chưa bật OTP", fault=True)
                if e.status in (404, 409):
                    raise JobGone(e.body.get("status") or e.error)
                raise
            self._status("Chờ khách nhập OTP")
            self._say("Game đòi OTP → đã báo shop, chờ khách nhập" + (" (mã trước sai/hết hạn)" if reason != "first" else ""))
            otp = None
            while otp is None:
                if self.abort and self.abort():
                    raise Aborted()
                try:
                    r = self.gw.otp_read(self.jid, wait=self.otp_wait)
                    net_since = None
                except GatewayError as e:
                    if e.status in (404, 409):
                        raise JobGone(e.body.get("status") or e.error)
                    if not e.retryable:
                        raise
                    net_since = net_since or time.time()
                    if time.time() - net_since > 600:       # mất gateway quá 10 phút khi đang chờ OTP
                        raise
                    _sleep(2.0, self.abort)
                    continue
                st = r.get("state")
                if st == "ready":
                    otp = str(r.get("otp") or "")
                elif st == "expired":
                    break
                elif st == "none":
                    raise JobGone(r.get("status") or "không còn chờ OTP")
            if otp is None:
                reason = "expired"
                self._say("Khách chưa nhập OTP kịp → xin lại")
                continue
            vars["otp"] = otp
            self._status("Đang nhập OTP")
            ok, why, _, _ = self._phase("otp", vars)
            if not ok:
                return self._finalize("Lỗi bước nhập OTP: " + why, fault=True)
            w, rule = wait_rules(self.nav, self.rules, ["otp_wrong", "login_fail", "login_success"], self.login_wait, self.abort)
            if w == "otp_wrong":
                reason = "wrong"
                self._say("OTP sai → xin khách nhập lại")
                continue
            if w == "login_fail":
                self.session = "none"
                return self._finalize("Đăng nhập thất bại sau khi nhập OTP" + self._note(rule))
            if w is None:
                return self._finalize("Không xác định được kết quả sau khi nhập OTP (%d giây)" % self.login_wait, fault=True)
            return None


# ====================== sổ cục bộ (chống mua trùng khi tool khởi động lại) ======================
class Journal:
    """Ghi lại đơn mỗi máy đang giữ + đã tới giai đoạn nào, BỀN qua lần khởi động lại.

    state[máy] = {job, ref, phase: claimed|purchasing|finished, outcome, delivered, at}
    - Tool chết SAU khi đã chạm luồng mua (phase=purchasing) → lần sau gặp lại đơn đó phải báo
      `review`, tuyệt đối không chạy lại từ đầu (tránh mua 2 lần).
    - Đã có kết quả mà chưa gửi được (mất mạng) → lần sau gửi lại đúng kết quả đó.
    Kèm file .jsonl ghi lịch sử mọi đơn để người vận hành đối soát.
    """

    def __init__(self, directory: str):
        self.dir = directory
        self.state_file = os.path.join(directory, "api_state.json")
        self.log_file = os.path.join(directory, "api_journal.jsonl")
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, device: str):
        with self.lock:
            return self._read().get(device)

    def peek(self, device: str):
        """Như get() nhưng đọc CHẶT: tệp sổ chưa có = chưa từng có đơn (None); tệp có mà không đọc được / hỏng → NÉM LỖI thay vì trả «không có gì».
        Chỉ để HỎI (không dùng trong luồng làm đơn): nơi mà trả lời nhầm «máy không còn đơn dở» là nguy hiểm — luồng tự báo gateway."""
        with self.lock:
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except FileNotFoundError:
                return None
            if not isinstance(d, dict):
                raise ValueError("sổ đơn không đúng dạng")
            return d.get(device)

    def set(self, device: str, **fields):
        with self.lock:
            d = self._read()
            cur = dict(d.get(device) or {})
            cur.update(fields)
            cur["at"] = time.time()
            d[device] = cur
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())        # phải nằm trên đĩa TRƯỚC khi bấm mua
            os.replace(tmp, self.state_file)
            return cur

    def record(self, **event):
        event["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            try:
                os.makedirs(self.dir, exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError:
                pass
