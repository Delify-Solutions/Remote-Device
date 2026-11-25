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

from eyes import norm_text, text_has
from gateway import GatewayError, call_retry

PHASES = ["login", "otp", "nav", "purchase", "after", "finish"]
GW_LISTS = {"login": "login_steps", "otp": "otp_steps", "nav": "nav_steps",
            "purchase": "purchase_steps", "after": "after_purchase_steps", "finish": "finish_steps"}
PHASE_LABEL = {"login": "Đăng nhập", "otp": "Nhập OTP", "nav": "Vào danh sách gói",
               "purchase": "Mua 1 gói", "after": "Sau khi mua", "finish": "Kết thúc đơn"}
DEFAULT_OTP_STEPS = [{"type": "type", "text": "{{otp}}"}, {"type": "key", "name": "enter"}]
INPUT_TYPES = ("tap", "tap_text", "type", "key", "combo", "launch", "home",
               "swipe", "hold", "hold_text")                                    # bước có gửi thao tác vào máy
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
        return f"{name} «{show(str(step.get('text') or ''), vars)}»"
    if t == "type":
        return f"Gõ «{show(str(step.get('text') or ''), vars)}»"
    if t == "key":
        return f"Phím {step.get('name')}"
    if t == "combo":
        return f"Tổ hợp {step.get('keys')}"
    if t == "launch":
        return f"Mở app {step.get('app')}"
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
        return False, "con trỏ không tới được vị trí cần bấm, hoặc màn hình đã đổi trước khi kịp bấm", False
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


def exec_step(nav, tmpl: dict, vars: dict, abort=None):
    """Chạy 1 bước (mẫu chưa thế biến). Trả (ok, lý do, acted). Lý do không chứa giá trị bí mật."""
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
        if t == "tap_text":
            img = nav.e.screenshot()
            for a in alts:
                pos = nav.e.find_text(a, img)
                if pos:
                    return _tap(nav, pos[0], pos[1], verify=_still_there(nav, alts, pos))
            return False, "không thấy chữ «%s» trên màn hình" % label, False
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

    if t == "type":
        text = typable(str(tmpl.get("text") or ""), vars)
        if text == "":
            return True, "", False
        return _keyed(hid(nav, "type " + text, wait=0.8 + 0.08 * len(text)), abort)

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
        if any(not (32 <= ord(c) <= 126) for c in app):
            raise ConfigError("tên app ở bước «Mở app» chỉ gõ được chữ không dấu (vd «Settings», «eFootball») — «%s» có ký tự không gõ được" % app)
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
        _sleep(LOOK_SETTLE, abort)
        img = nav.e.screenshot()
        for a in alts:
            pos = nav.e.find_text(a, img)
            if pos:
                return gesture(nav, "bấm giữ", lambda: nav.hold_at(pos[0], pos[1], sec, verify=_still_there(nav, alts, pos)))
        return False, "không thấy chữ «%s» trên màn hình" % show(raw, vars), False

    raise ConfigError("loại bước lạ: %s" % t)


def typable(raw: str, vars: dict) -> str:
    """Chữ sẽ gõ của một bước «gõ chữ» (đã thế {{biến}}); ném InputError nếu tool không gõ được (ký tự có dấu, khoảng trắng cuối…)."""
    text = subst(raw, vars)
    if any(not (32 <= ord(c) <= 126) for c in text):
        raise InputError("«%s» có ký tự tool không gõ được (chỉ gõ được chữ không dấu, số, ký hiệu thường)" % show(raw, vars))
    if text != text.rstrip():
        raise InputError("«%s» kết thúc bằng khoảng trắng — tool không gõ được" % show(raw, vars))
    return text


def check_typable(steps: list, vars: dict):
    """Kiểm TRƯỚC khi chạy: mọi bước «gõ chữ» trong `steps` đều gõ được với dữ liệu này (không thì ném InputError) — để một tài khoản /
    mật khẩu tool không gõ được bị từ chối NGAY, khi chưa đụng gì vào game (không gõ dở nửa chừng)."""
    for st in steps or []:
        if st.get("type") == "type":
            typable(str(st.get("text") or ""), vars)


def run_steps(nav, steps: list, vars: dict, abort=None, on_step=None):
    """Chạy tuần tự, dừng ở bước lỗi đầu tiên.
    Trả (ok, lý do, chỉ_số_bước_lỗi|None, touched) — touched: đã có thao tác nào (có thể) tới máy chưa."""
    touched = False
    for i, st in enumerate(steps):
        if on_step:
            on_step(i, st)
        ok, why, acted = exec_step(nav, st, vars, abort)
        touched = touched or acted or (ok and st.get("type") in INPUT_TYPES)
        if not ok and not st.get("optional"):
            return False, "%s — %s" % (_describe(st, vars), why), i, touched
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
    ok = False
    for _ in range(3):                    # phản hồi status đầu tiên đôi khi còn là giá trị cũ
        if "ble=connected" in str(nav.h.send("status") or ""):
            ok = True
            break
        time.sleep(0.4)
    if not ok:
        return "Bluetooth chưa nối với iPhone"
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
    Chạy lại đoạn này bao nhiêu lần cũng không làm game đổi trạng thái đăng nhập."""
    out = []
    for st in login or []:
        t = st.get("type")
        if t in ("tap", "tap_text", "hold", "hold_text", "swipe") or _is_credential(st):
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
    không bấm vào đâu, không gõ gì của khách. Bước chờ/kiểm chữ trong đoạn đó hỏng thì bỏ qua (khi game
    đang đăng nhập sẵn thì màn hình chờ của nó khác)."""
    for st in open_prefix(steps.get("login") or []):
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
        fail_why = ""
        failed = False
        touched = False
        for i, st in enumerate(plist):
            sent0 = getattr(self.nav, "_hid_sent", 0)
            try:
                ok, why, acted = exec_step(self.nav, st, pv, self.abort)
            except Exception:
                # Bước ném lỗi giữa chừng (rớt cổng serial…): nếu lệnh bấm/gõ ĐÃ được ghi ra cổng thì
                # iPhone có thể đã nhận → «không chắc», tuyệt đối không được báo «chưa mua».
                if getattr(self.nav, "_hid_sent", 0) != sent0:
                    self.risky = True
                raise
            if acted or (ok and st.get("type") in INPUT_TYPES):
                touched = True
                self.risky = True                       # từ đây: chưa xác nhận thì không được báo failed
            if not ok and not st.get("optional"):
                failed, fail_why = True, "%s — %s" % (_describe(st, pv), why)
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
