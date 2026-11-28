#!/usr/bin/env python3
"""
jobflow.py — xử lý MỘT đơn nạp (lấy từ Topup Gateway) trên MỘT máy.

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

import stepexec
from eyes import text_has
from gateway import GatewayError, call_retry

PHASES = ["login", "otp", "nav", "purchase", "after", "finish"]


GW_LISTS = {"login": "login_steps", "otp": "otp_steps", "nav": "nav_steps",
            "purchase": "purchase_steps", "after": "after_purchase_steps", "finish": "finish_steps"}


PHASE_LABEL = {"login": "Đăng nhập", "otp": "Nhập OTP", "nav": "Vào danh sách gói",
               "purchase": "Mua 1 gói", "after": "Sau khi mua", "finish": "Kết thúc đơn"}


DEFAULT_OTP_STEPS = [{"type": "type", "text": "{{otp}}"}, {"type": "key", "name": "enter"}]


RESULT_RULES = ("purchase_success", "purchase_fail", "package_unavailable")


REQUIRED_RULES = {"logged_out": "Màn hình CHƯA đăng nhập", "login_success": "Đăng nhập THÀNH CÔNG",
                  "purchase_success": "Nạp gói THÀNH CÔNG"}


REQUIRED_PHASES = ("login", "purchase", "finish")


class JobGone(Exception):
    """Gateway không còn coi đơn này là đang chạy (đã đối soát/quá hạn) → dừng, không báo kết quả."""


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
    if str(s.get("note") or "").strip():
        out["note"] = str(s["note"]).strip()        # ghi chú của người soạn đi theo bước
    return out


def _gw_step(s: dict) -> dict:
    t = s.get("type")
    v = str(s.get("value") or "")
    if t == "tap":
        m = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", v)
        if not m:
            raise stepexec.ConfigError(f"bước «Tap toạ độ» cần giá trị dạng x,y (đang là «{v}»)")
        return {"type": "tap", "x": int(m.group(1)), "y": int(m.group(2))}
    if t in ("tap_text", "assert_text"):
        return {"type": t, "text": v}
    if t == "wait_text":        # "Chữ cần chờ @45s" = chờ tối đa 45 giây (dữ liệu đời cũ không ghi thì 20 — đúng như gateway từng hứa)
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
        if d in stepexec.SWIPE_DIRS:
            return {"type": "swipe", "dir": d}
        m = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*(?:>|→|->|to)\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", v)
        if not m:
            raise stepexec.ConfigError("bước «Vuốt» cần hướng (left/right/up/down) hoặc dạng x1,y1 > x2,y2 (đang là «%s»)" % v)
        return {"type": "swipe", "x1": int(m.group(1)), "y1": int(m.group(2)), "x2": int(m.group(3)), "y2": int(m.group(4))}
    if t in ("hold", "hold_text"):  # "x,y @1.5s"  /  "Chữ cần giữ @1.5s"  (mặc định giữ 1 giây)
        m = re.match(r"^(.*?)\s*@\s*(\d+(?:[.,]\d+)?)\s*s\s*$", v)
        body, sec = (m.group(1), float(m.group(2).replace(",", "."))) if m else (v, 1.0)
        sec = max(0.2, min(sec, 10.0))
        if t == "hold_text":
            return {"type": "hold_text", "text": body.strip(), "seconds": sec}
        m2 = re.match(r"^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$", body)
        if not m2:
            raise stepexec.ConfigError("bước «Bấm giữ» cần giá trị dạng x,y hoặc x,y @1.5s (đang là «%s»)" % v)
        return {"type": "hold", "x": int(m2.group(1)), "y": int(m2.group(2)), "seconds": sec}
    if t == "wait":
        try:
            sec = float(v.replace(",", ".") or 1)
        except ValueError:
            raise stepexec.ConfigError(f"bước «Chờ» cần số giây (đang là «{v}»)")
        return {"type": "wait", "seconds": max(0.0, min(sec, 600.0))}
    raise stepexec.ConfigError(f"loại bước lạ: {t}")


def order_steps(local: dict | None) -> dict:
    """Bước từng giai đoạn của MỘT đơn = đúng các bước soạn trong kịch bản nhận đơn ở tool (`orders.steps`) — nơi DUY NHẤT soạn bước;
    bộ chạy không bao giờ đọc bước nào từ gateway. Giai đoạn OTP để trống → gõ {{otp}} rồi nhấn Enter."""
    local = local or {}
    out = {ph: [s for s in (local.get(ph) or []) if isinstance(s, dict) and s.get("type")] for ph in PHASES}
    if not out["otp"]:
        out["otp"] = [dict(s) for s in DEFAULT_OTP_STEPS]
    return out


def legacy_gateway_steps(pool: dict) -> tuple:
    """Bước đời cũ còn lưu ở POOL trên gateway (trước đây bước soạn được ở cả hai nơi), đổi sang dạng của tool.
    Trả ({giai đoạn: [bước]}, {giai đoạn: lời báo}) — vế sau là giai đoạn có bước SAI DẠNG, bỏ cả giai đoạn đó (không chép nửa chừng).
    CHỈ dùng để chép MỘT LẦN vào kịch bản nhận đơn (store.adopt_gateway_steps)."""
    out, bad = {}, {}
    for ph in PHASES:
        try:
            steps = [gw_step_to_engine(s) for s in (pool.get(GW_LISTS[ph]) or []) if isinstance(s, dict)]
        except stepexec.ConfigError as e:
            bad[ph] = str(e)
            continue
        if steps:
            out[ph] = steps
    return out, bad


def legacy_blocked_text(blocked: dict) -> str:
    """Lời báo khi KHÔNG chép được bước đời cũ: kịch bản đang trống đúng giai đoạn mà bước lưu ở gateway sai dạng."""
    return ("bước đời cũ lưu ở gateway sai dạng nên chưa chép được về kịch bản (%s) — soạn bước cho giai đoạn đó ngay trong kịch bản rồi chạy lại "
            "(các giai đoạn còn lại sẽ được chép); chỉ xoá bước cũ ở gateway SAU khi kịch bản đã đủ bước"
            % "; ".join("%s: %s" % (PHASE_LABEL.get(p, p), m) for p, m in blocked.items()))


# ====================== nhận diện trạng thái bằng luật ======================
def match_rule(text_norm: str, rules: list, when: str):
    for r in rules:
        if r.get("when") != when:
            continue
        for alt in stepexec.alternatives(str(r.get("value") or "")):
            if text_has(text_norm, alt):
                return r
    return None


def wait_rules(nav, rules: list, whens: list, timeout: float, abort=None, interval: float = 1.0):
    """Chụp màn + OCR lặp lại tới khi khớp 1 trong `whens` (xét theo THỨ TỰ ưu tiên đưa vào).
    Trả (when, luật) hoặc (None, None) khi hết giờ."""
    end = time.time() + timeout
    while True:
        if abort and abort():
            raise stepexec.Aborted()
        try:
            txt = stepexec._screen_text(nav)
        except Exception:
            txt = ""                      # chụp/OCR lỗi tạm thời → thử lại tới hết giờ
        for w in whens:
            r = match_rule(txt, rules, w)
            if r:
                return w, r
        if time.time() >= end:
            return None, None
        stepexec._sleep(interval, abort)


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
    """Tên các luật bắt buộc mà pool chưa có (luật đặt ở pool trên gateway; bước thì soạn trong kịch bản nhận đơn ở tool)."""
    have = {r.get("when") for r in (pool.get("rules") or []) if str(r.get("value") or "").strip()}
    return [label for when, label in REQUIRED_RULES.items() if when not in have]


def _is_credential(st: dict) -> bool:
    """Bước gõ có dùng {{biến}} (tài khoản, mật khẩu…) — khác với gõ chữ cố định như tên app trong Spotlight."""
    return st.get("type") == "type" and bool(stepexec.PLACEHOLDER.search(str(st.get("text") or "")))


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
    stepexec.watch_phase(nav, "Kiểm game trước khi nhận đơn", len(prefix))
    for st in prefix:
        ok, why, _ = stepexec.exec_step(nav, st, {}, abort)
        if not ok and st.get("type") not in ("wait_text", "assert_text") and not st.get("optional"):
            return "unknown"
    stepexec.park(nav)
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
                 status=None, log=None, abort=None, on_purchase_start=None, apple=None):
        self.nav, self.gw, self.job, self.pool, self.steps = nav, gw, job, pool, steps
        self.apple = dict(apple or {})        # tài khoản / mật khẩu Apple ID của MÁY (ví ở tool) — biến {{apple.account}} / {{apple.password}}
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
        stepexec.watch_phase(self.nav, PHASE_LABEL[phase], len(steps))
        ok, why, idx, touched = stepexec.run_steps(self.nav, steps, vars, self.abort)
        if not ok:
            self._say("%s: lỗi ở bước %d — %s" % (PHASE_LABEL[phase], idx + 1, why), "bad")
        return ok, why, idx, touched

    def _upload(self, kind):
        if kind == "bill":                      # hộp thoại «nạp thành công» vừa hiện: chờ nó hiện hẳn rồi mới chụp bill
            stepexec._sleep(0.6, self.abort)
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
        except stepexec.Aborted:
            return self._finalize("Người vận hành dừng máy giữa chừng")
        except StaleSession:
            out = self._finalize("Máy vẫn đang đăng nhập tài khoản của đơn trước — chưa nạp gì cho đơn này", fault=True)
            out.halt = True
            return out
        except stepexec.InputError as e:
            return self._finalize(str(e))
        except stepexec.ConfigError as e:
            return self._finalize("Cấu hình bước sai: %s" % e, fault=True)
        except GatewayError as e:
            return self._finalize("Lỗi gateway giữa chừng: %s" % e.vi(), fault=True)
        except Exception as e:      # lỗi bất ngờ (rớt cổng serial, mất USB…)
            return self._finalize("Lỗi tool: %s" % e, fault=True)

    def _flow(self) -> Outcome:
        vars = {str(k): v for k, v in (self.job.get("login") or {}).items() if not str(k).startswith("apple.")}
        # tài khoản Apple của MÁY (gõ vào bảng mua của App Store) — trường đăng nhập của khách KHÔNG BAO GIỜ thay được (bỏ mọi khoá apple.*)
        for k in ("account", "password"):
            if self.apple.get(k):
                vars["apple." + k] = str(self.apple[k])
        # bước mua / sau mua dùng {{apple.*}} mà máy chưa lưu (hoặc tool không gõ được) → dừng NGAY, trước khi đăng nhập tài khoản khách
        # (phát hiện ở bảng mua thì đơn đã chạm luồng mua → phải đối soát)
        buy_steps = (self.steps.get("purchase") or []) + (self.steps.get("after") or [])
        need = sorted({k for k in stepexec.PLACEHOLDER.findall(json.dumps(buy_steps, ensure_ascii=False)) if k.startswith("apple.")})
        miss = [k for k in need if not vars.get(k)]
        if miss:
            raise stepexec.ConfigError("bước mua dùng %s nhưng ví của máy chưa lưu (trang «Ví & Apple» của tool)" % ", ".join("{{%s}}" % k for k in miss))
        stepexec.check_typable([st for st in buy_steps if "{{apple." in str(st.get("text") or "").replace(" ", "")], vars)
        missing = validate(self.pool, self.steps)
        if missing:
            raise stepexec.ConfigError("pool chưa đủ cấu hình (%s)" % "; ".join(missing))

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
            stepexec.park(self.nav)
            w, _ = wait_rules(self.nav, self.rules, ["login_success", "logged_out"], min(12.0, self.login_wait), self.abort)
            if w == "login_success":
                raise StaleSession()
            if w != "logged_out":
                raise NotAtLogin()
            # Từ ĐÂY tool bắt đầu gõ tài khoản của khách. Nếu bị dừng ngang giữa các bước đăng nhập (Dừng ngay, lỗi…) thì không còn chắc
            # «chưa ai đăng nhập» nữa — game có thể đã vào tài khoản của khách. Đánh dấu ngay bây giờ, không đợi các bước đăng nhập chạy xong.
            self.session = "unknown"

        stepexec.check_typable(login, vars)        # tài khoản / mật khẩu không gõ được → từ chối ngay, khi phiên còn chắc chắn «chưa đăng nhập»
        stepexec.watch_phase(self.nav, PHASE_LABEL["login"], len(login))
        try:
            ok, why, idx, _ = stepexec.run_steps(self.nav, login, vars, self.abort, on_step=before_step)
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
                    stale = match_rule(stepexec._screen_text(self.nav), self.rules, "login_success")
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
            if str(item.get("limit_type") or "multi") == "once":
                # gói «1 lần»: ô gói phải CÒN trên cửa hàng và trong ô có chữ «Remaining: 1» — mua rồi thì game ẩn ô / hết lượt → báo luôn,
                # không bấm gì (chưa mất tiền)
                left, why_once = self._once_left(item, pv)
                if left is None:                         # máy không ở cửa hàng → lỗi máy (không phải «đã mua»), chưa chạm luồng mua
                    res["status"], res["message"] = "failed", why_once
                    return self._finalize("%s: %s" % (name, why_once), fault=True)
                if not left:
                    res["status"], res["message"] = "unavailable", why_once
                    self._say("%s: %s" % (name, why_once), "bad")
                    return self._finalize("%s: %s" % (name, why_once))
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

    # ---------- gói «1 lần»: còn mua được không ----------
    ONCE_LEFT_DEFAULT = "Remaining: 1|Remaining:1|Remaining 1"

    def _once_left(self, item: dict, pv: dict):
        """(True, "") nếu ô của gói CÒN trên cửa hàng và trong CÙNG ô có chữ «còn 1 lượt» (luật «once_left» của pool; mặc định
        «Remaining: 1»); (False, lý do) = gói đã mua / hết lượt; (None, lý do) = máy không ở cửa hàng (lỗi máy, không phải «đã mua»). Tìm ô theo đúng cách bước mua tìm (chữ của gói + chữ giá cùng ô, lướt nếu bước có lướt).
        Không bấm gì; lướt danh sách không tính là đã chạm luồng mua."""
        vals = [str(r.get("value")) for r in self.rules if r.get("when") == "once_left" and str(r.get("value") or "").strip()]
        left_alts = [stepexec._flat(a) for a in stepexec.alternatives("|".join(vals) if vals else self.ONCE_LEFT_DEFAULT) if stepexec._flat(a)]
        tmpl = next((st for st in self.steps.get("purchase") or []
                     if st.get("type") in ("tap_text", "assert_text") and "{{package.ocr_text}}" in str(st.get("text") or "")), None)
        alts = stepexec.alternatives(stepexec.subst(str(tmpl.get("text")) if tmpl else "{{package.ocr_text}}", pv))
        card = stepexec.card_opts(tmpl, pv) if tmpl else None
        if card is None:
            price = stepexec.alternatives(str(pv.get("package.price_text") or ""))
            card = {"near_alts": price, "near_label": str(pv.get("package.price_text") or ""), "dir": "below", "scroll": None, "scrolls": 0}
        card["label"] = item.get("name") or item.get("code")
        name = item.get("name") or item.get("code")
        # lỗi của MÁY (board / cổng serial / đọc chữ) không bắt ở đây: lên tới run() thành «Lỗi tool» (lỗi máy, máy tự dừng nếu lặp lại) —
        # không được nói với khách là «đã mua»
        pos, why, _ = stepexec._find_card(self.nav, alts, card, stepexec._text_wait(tmpl or {}, "Bấm vào chữ") if tmpl else 5.0, self.abort)
        img = self.nav.e.screenshot()
        lines = self.nav.e.text_lines(img)
        if not pos:
            # Không thấy ô của gói: chỉ kết luận «đã mua» khi ĐANG Ở cửa hàng (thấy ô của gói khác trong pool). Không thấy gói nào = máy đang
            # ở màn hình khác → lỗi máy, KHÔNG báo khách «đã mua».
            others = []
            for k in self.pool.get("packages") or []:
                if str(k.get("code")) != str(item.get("code")):
                    others += stepexec.alternatives(str(k.get("ocr_text") or ""))
            W0 = img.shape[1] if hasattr(img, "shape") else None
            if others and stepexec._line_hits(lines, others, (W0, 0) if W0 else None):
                return False, "gói «1 lần» «%s» không còn trên cửa hàng — tài khoản này đã mua gói này rồi" % name
            return None, "không thấy cửa hàng / ô gói nào trên màn hình khi kiểm gói «1 lần» «%s» (%s) — máy đang ở màn hình khác, chưa mua" % (name, why)
        h, w = img.shape[:2] if hasattr(img, "shape") else (0, 0)
        if not w and lines:
            w = max(int(ln["x"]) + int(ln.get("w") or 0) for ln in lines) or 1
            h = max(int(ln["y"]) + int(ln.get("h") or 0) for ln in lines) or 1
        if stepexec.once_left_in_card(lines, pos, left_alts, (w or 1, h or 1)):
            return True, ""
        # ô gói còn mà không có chữ «còn 1 lượt»
        return False, "ô gói «1 lần» «%s» không có chữ «%s» — gói đã mua / hết lượt" % (name, (vals[0] if vals else "Remaining: 1"))

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
        stepexec.park(self.nav)          # con trỏ còn nằm trên nút vừa bấm có thể che đúng chữ cần đọc
        stepexec._sleep(stepexec.LOOK_SETTLE, self.abort)
        preset, clean = set(), 0
        while True:
            try:
                txt = stepexec._screen_text(self.nav)
            except Exception as e:                  # chụp/OCR lỗi tạm thời → thử lại; hết giờ vẫn lỗi thì chưa chạm gì
                if time.time() >= end:
                    return "failed_tool", "không đọc được màn hình trước khi mua (%s)" % e
                clean = 0
                stepexec._sleep(1.0, self.abort)
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
            stepexec._sleep(0.6 if clean else 1.0, self.abort)
        pre = [k for k in RESULT_RULES if k in preset]
        # chữ «thất bại» / «không mua được» đã có SẴN (vd nhãn in trên ô gói khác) thì không dùng để kết luận
        # cho lần mua này; chỉ chữ MỚI xuất hiện mới có nghĩa.
        fresh = [k for k in RESULT_RULES if k not in pre]
        if pre:
            self._say("Trước khi mua màn hình đã có sẵn chữ của luật %s — bỏ qua các luật đó cho lần mua này"
                      % ", ".join("«%s»" % k for k in pre))

        # (2) chạy các bước mua
        plist = self.steps["purchase"]
        stepexec.watch_phase(self.nav, PHASE_LABEL["purchase"], len(plist))
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
                seen, gwhy = stepexec.screen_gate(self.nav, st, self.abort)
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
                failed, fail_why = True, "%s — %s" % (stepexec.said(st, pv), gwhy)
                break
            try:
                ok, why, acted = stepexec.exec_step(self.nav, st, pv, self.abort)
            except Exception:
                # Bước ném lỗi giữa chừng (rớt cổng serial…): nếu lệnh bấm/gõ ĐÃ được ghi ra cổng thì
                # iPhone có thể đã nhận → «không chắc», tuyệt đối không được báo «chưa mua».
                if getattr(self.nav, "_hid_sent", 0) != sent0:
                    self.risky = True
                raise
            # bước có điều kiện xong theo hai kiểu — đã bấm (acted) hay không thấy nên bỏ qua (chưa đụng gì vào máy): chỉ kiểu đầu mới là «đã chạm»
            if acted or (ok and st.get("type") in stepexec.INPUT_TYPES and st.get("type") != "tap_if"):
                touched = True
                self.risky = True                       # từ đây: chưa xác nhận thì không được báo failed
            if not ok and not st.get("optional"):
                failed, fail_why = True, "%s — %s" % (stepexec.said(st, pv), stepexec.observed_why(st, why))
                break
            stepexec._sleep(stepexec.STEP_GAP, self.abort)
        if not touched:                                  # lỗi trước khi chạm vào gì (vd không thấy ô gói)
            return "failed_tool", "không bắt đầu mua được (%s)" % fail_why

        # (3) đọc kết quả: chỉ chữ MỚI xuất hiện sau khi bấm (cất con trỏ để nó không che chữ)
        stepexec.park(self.nav)
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
                raise stepexec.Aborted()
            try:
                txt = stepexec._screen_text(self.nav)
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
            stepexec._sleep(1.0, self.abort)

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
                    raise stepexec.Aborted()
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
                    stepexec._sleep(2.0, self.abort)
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
