#!/usr/bin/env python3
"""
control.py — LÕI ĐIỀU KHIỂN dùng chung cho AI (MCP) và dòng lệnh (CLI).

Một bộ công cụ duy nhất: xem danh sách máy, ĐỌC màn hình iPhone (ảnh + chữ kèm toạ độ), bấm, bấm giữ, vuốt,
gõ, phím, mở app, chờ chữ, chạy một chuỗi bước, xem trạng thái / chạy / dừng nhóm máy.
  • app đang mở  → app là nơi giữ cổng serial; MCP/CLI gọi sang app (xem mcpserver.Remote);
  • app chưa mở  → StandaloneHost tự dò board, tự mở cổng (chỉ điều khiển trực tiếp, không chạy nhóm).

Quy ước toạ độ: pixel của ảnh chụp màn hình GỐC (iPhone 8 = 750×1334), gốc (0,0) ở góc trên-trái —
giống hệt toạ độ trong kịch bản của app.
"""
from __future__ import annotations
import json, os, secrets, threading, time

import cv2

import stepexec, ocr, store
from eyes import Eyes, norm_text
from mcpserver import Remote, Result, Tool, ToolError, cancel_requested, image, text

try:
    import pytesseract
except ImportError:                                   # pragma: no cover
    pytesseract = None
pytesseract = ocr.usable_tesseract(pytesseract)     # có gói pip mà không có chương trình tesseract → coi như không có (xem eyes.py)

ENDPOINT_FILE = os.path.join(store.DATA_DIR, "control.json")      # cổng + khoá của máy chủ điều khiển (KHÔNG vào git)
DEFAULT_PORT = 47821
NEED_APP = "Việc này cần app iPhone Farm Manager đang mở (mở app rồi gọi lại)."

INSTRUCTIONS = (
    "Controls real iPhones (via a Bluetooth keyboard/mouse board) managed by the iPhone Farm Manager app. "
    "Typical loop: list_devices → read_screen (image + OCR text lines with coordinates) → tap / type_text / swipe → read_screen again. "
    "All coordinates are pixels of the full-size screenshot (origin top-left), exactly as returned by read_screen. "
    "Pointer actions are slow (a tap takes several seconds) and are verified: a tap is only performed when the pointer was "
    "measured at the target. type_text can only type printable ASCII. The phone UI may be in Vietnamese. "
    "start_run on a script whose mode is «orders» (listed as NHẬN ĐƠN THẬT) makes the phone process REAL paid "
    "top-up orders — only start it when the user asks. "
    "A device shown as ON HOLD stopped in the middle of a paid order and is waiting for a human to reconcile it: do not touch it, "
    "do not try to clear it (stop_run is refused for such a device; only the human can, in the app) and do not restart it."
)


# ====================== nơi lưu cổng + khoá ======================
def load_endpoint():
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            ep = json.load(f)
        return ep if isinstance(ep, dict) and ep.get("token") else None
    except (OSError, ValueError):
        return None


def save_endpoint(port: int, token: str, enabled: bool = True) -> dict:
    os.makedirs(store.DATA_DIR, exist_ok=True)
    ep = {"port": int(port), "token": token, "pid": os.getpid(), "enabled": bool(enabled), "started": int(time.time())}
    tmp = ENDPOINT_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # chỉ chủ máy đọc được khoá
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ep, f)
    os.replace(tmp, ENDPOINT_FILE)
    return ep


def token(renew: bool = False) -> str:
    """Khoá của máy chủ điều khiển — giữ nguyên qua các lần mở app (để cấu hình phía AI không phải sửa lại)."""
    ep = load_endpoint()
    if ep and not renew:
        return ep["token"]
    return secrets.token_urlsafe(32)


def remote(timeout: float = 600.0):
    """Kết nối tới app đang chạy, hoặc None nếu app chưa mở / đã tắt cầu nối."""
    ep = load_endpoint()
    if not ep or not ep.get("port"):
        return None
    r = Remote(ep["port"], ep["token"], timeout=timeout)
    info = r.health()
    # chỉ đưa khoá cho ĐÚNG app đã ghi tệp này (cùng tên, cùng tiến trình) — không phải bất cứ thứ gì đang nghe ở cổng đó
    if not info or info.get("app") != "iphone-farm" or info.get("pid") != ep.get("pid"):
        return None
    return r


class Claims:
    """Ai đang dùng cổng serial của từng máy: «ai» (AI qua MCP / lệnh farm) hay «ui» (thao tác thử trên giao diện).
    Bộ chạy kịch bản/đơn được hỏi qua hàm `running(name)`. MỌI bên xin, nhả và khởi chạy qua CÙNG một khoá, nên
    không có khe hở «kiểm tra xong rồi mới làm» để hai bên cùng lọt vào một máy."""
    WHO = {"ai": "AI / dòng lệnh", "ui": "giao diện app"}

    def __init__(self, running=None):
        self.lock = threading.RLock()
        self.held = {}                      # tên máy -> {"ai": số lệnh, "ui": số lệnh}
        self.running = running or (lambda name: False)

    def acquire(self, name: str, who: str):
        """Xin dùng máy `name`. Trả None nếu được, hoặc câu giải thích vì sao không."""
        other = "ui" if who == "ai" else "ai"
        with self.lock:
            if self.running(name):
                return "Máy «%s» đang chạy kịch bản / nhận đơn — dừng máy đó trước rồi mới điều khiển tay." % name
            h = self.held.setdefault(name, {"ai": 0, "ui": 0})
            if h[other] > 0:
                return "Máy «%s» đang được %s điều khiển — chờ lệnh đó xong." % (name, self.WHO[other])
            if who == "ui" and h["ui"] > 0:
                # Hai thao tác thử trên giao diện cùng lúc = hai luồng cùng trong một Nav (một bên về góc trong khi bên kia
                # đang đo con trỏ). Phía AI thì tự xếp hàng ở khoá của từng máy (Control._act) nên không cần chặn.
                return "Máy «%s» đang chạy một thao tác thử khác trên giao diện — chờ nó xong." % name
            h[who] += 1
            return None

    def release(self, name: str, who: str):
        with self.lock:
            h = self.held.get(name)
            if h and h[who] > 0:
                h[who] -= 1

    def names(self, who=None) -> list:
        """Các máy đang có người dùng (lọc theo «ai»/«ui» nếu nêu)."""
        with self.lock:
            return [n for n, h in self.held.items() if (h[who] if who else h["ai"] + h["ui"]) > 0]

    def start(self, names, start_fn):
        """Khởi chạy bộ chạy trên `names` — chỉ khi không máy nào trong đó đang có người dùng. Kiểm và chạy trong
        cùng một khoá. Trả (kết quả của start_fn, None) hoặc (None, lý do)."""
        with self.lock:
            busy = [n for n in names if sum((self.held.get(n) or {"ai": 0, "ui": 0}).values()) > 0]
            if busy:
                return None, "Máy %s đang được điều khiển tay (AI / dòng lệnh / giao diện) — chờ lệnh đó xong rồi chạy." % ", ".join(busy)
            return start_fn(), None


# ====================== đọc chữ kèm toạ độ ======================
def ocr_lines(img, lang: str = Eyes.OCR_LANG, scale: int = 2, min_conf: float = 30.0, engine: str = "auto") -> list:
    """Các DÒNG chữ trên ảnh: [{text, x, y, w, h}] — (x,y) là TÂM dòng chữ, đơn vị pixel của ảnh gốc.
    engine «auto»: Apple Vision (macOS) hoặc RapidOCR (Windows / Linux) — xem ocr.py; không có / không đọc ra dòng nào thì dùng tesseract như trước.
    engine «tesseract»: chỉ tesseract."""
    if engine != "tesseract":
        try:
            seen = [{k: r[k] for k in ("text", "x", "y", "w", "h")} for r in ocr.lines(img)]
        except Exception:
            seen = []
        if seen:
            return seen
        if pytesseract is None and ocr.available():
            return []
    if pytesseract is None:
        raise ToolError("Thiếu pytesseract/tesseract nên không đọc được chữ (vẫn xem được ảnh).")
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else img
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    try:
        d = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)
    except Exception:
        d = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
    rows = {}
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not t or conf < min_conf:
            continue
        rows.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
    out = []
    for idxs in rows.values():
        idxs.sort(key=lambda i: d["left"][i])
        tall = sorted(d["height"][i] for i in idxs)[len(idxs) // 2]
        gap = max(1.4 * tall, 36 * scale)       # khoảng trống lớn hơn hẳn một dấu cách = hai cụm chữ khác nhau
        groups, cur = [], [idxs[0]]             # (vd nhãn của các icon nằm cùng một hàng)
        for a, b in zip(idxs, idxs[1:]):
            if d["left"][b] - (d["left"][a] + d["width"][a]) > gap:
                groups.append(cur)
                cur = []
            cur.append(b)
        groups.append(cur)
        for g in groups:
            x0 = min(d["left"][i] for i in g)
            y0 = min(d["top"][i] for i in g)
            x1 = max(d["left"][i] + d["width"][i] for i in g)
            y1 = max(d["top"][i] + d["height"][i] for i in g)
            out.append({"text": " ".join((d["text"][i] or "").strip() for i in g),
                        "x": int((x0 + x1) / 2 / scale), "y": int((y0 + y1) / 2 / scale),
                        "w": int((x1 - x0) / scale), "h": int((y1 - y0) / scale)})
    # thứ tự đọc: từ trên xuống, cùng một hàng (lệch nhau vài pixel) thì từ trái sang
    out.sort(key=lambda r: r["y"])
    rows, last = [], None
    for r in out:
        if last is None or r["y"] - last > max(10, 0.6 * r["h"]):
            rows.append([])
        rows[-1].append(r)
        last = r["y"]
    return [r for row in rows for r in sorted(row, key=lambda r: r["x"])]


class _EyesOnly:
    """Vật thay cho Nav khi chỉ cần ĐỌC màn hình (không mở cổng serial → dùng được cả lúc máy đang chạy)."""
    def __init__(self, eyes):
        self.e = eyes


# ====================== lõi ======================
class Control:
    LOCK_WAIT = 180.0

    def __init__(self, host):
        self.host = host
        self._locks = {}
        self._guard = threading.Lock()
        self._gen = 0                   # tăng lên mỗi lần «huỷ hết» → mọi lệnh đang chạy thấy và dừng

    def active(self) -> list:
        """Các máy đang được AI/CLI điều khiển ngay lúc này (cổng serial của chúng đang bận)."""
        return self.host.active()

    def cancel_all(self):
        """Dừng mọi lệnh AI/CLI đang chạy dở ở chỗ an toàn gần nhất (giữa hai bước / trong lúc chờ)."""
        self._gen += 1

    def _abort(self):
        gen = self._gen
        return lambda: self._gen != gen or cancel_requested()

    # ---------- nội bộ ----------
    def _resolve(self, device) -> str:
        if device and device in self.host.names():
            return device
        devs = self.host.devices()
        names = [d["name"] for d in devs]
        if not device:
            ready = [d["name"] for d in devs if d.get("board") and d.get("iphone")]
            if len(ready) == 1:
                return ready[0]
            if len(names) == 1:
                return names[0]
            raise ToolError("Cần nêu tên máy (device). Các máy: %s" % (", ".join(names) or "chưa có máy nào"))
        want = norm_text(device)
        for d in devs:
            if d["name"] == device:
                return d["name"]
        hits = [d["name"] for d in devs if norm_text(d["name"]) == want or norm_text(d.get("label") or "") == want]
        if not hits:
            hits = [d["name"] for d in devs if want in norm_text(d["name"]) or want in norm_text(d.get("label") or "")]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ToolError("«%s» khớp nhiều máy (%s) — ghi đúng tên máy." % (device, ", ".join(hits)))
        raise ToolError("Không có máy «%s». Các máy: %s" % (device, ", ".join(names) or "chưa có máy nào"))

    def _lock(self, name):
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    def _act(self, device, fn):
        """Chạy một thao tác CÓ CHẠM vào máy. Phải xin được quyền dùng máy trước (máy đang chạy đơn/kịch bản, đang
        chờ đối soát, hoặc đang có bên khác điều khiển thì bị từ chối); mỗi máy một lệnh một lúc."""
        name = self._resolve(device)
        why = self.host.acquire(name)
        if why:
            raise ToolError(why)
        lock = self._lock(name)
        try:
            if not lock.acquire(timeout=self.LOCK_WAIT):
                raise ToolError("Máy «%s» đang thực hiện một lệnh khác — thử lại sau." % name)
            try:
                try:
                    nav = self.host.session(name)
                except ToolError:
                    raise
                except Exception as e:
                    raise ToolError(str(e))
                try:
                    return name, fn(nav)
                except stepexec.Aborted:
                    raise ToolError("Đã dừng theo yêu cầu huỷ (lệnh chưa chạy hết).")
                finally:
                    self.host.done(name)
            finally:
                lock.release()
        finally:
            self.host.release(name)

    @staticmethod
    def _need(ok, why, what):
        if not ok:
            raise ToolError("%s: %s" % (what, why or "không thực hiện được"))

    def _step(self, device, step: dict, what: str):
        abort = self._abort()

        def run(nav):
            try:
                ok, why, _ = stepexec.exec_step(nav, step, {}, abort)
            except (stepexec.ConfigError, stepexec.InputError, ValueError) as e:
                raise ToolError(str(e))
            self._need(ok, why, what)
        name, _ = self._act(device, run)
        return name

    def _eyes(self, device):
        name = self._resolve(device)
        try:
            return name, self.host.eyes(name)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(str(e))

    # ---------- xem ----------
    def list_devices(self):
        devs = self.host.devices()
        if not devs:
            return Result("Chưa có máy nào. Mở app → trang Thiết bị để gán board với iPhone.", {"devices": []})
        lines = []
        for d in devs:
            bt = {True: "Bluetooth đã nối", False: "Bluetooth CHƯA nối", None: "Bluetooth chưa rõ"}[d.get("bluetooth")]
            lines.append("%s%s — board %s, %s, iPhone %s%s%s%s" % (
                d["name"], (" (%s)" % d["label"]) if d.get("label") and d["label"] != d["name"] else "",
                "có" if d.get("board") else "KHÔNG thấy", bt,
                ("%s iOS %s" % (d.get("model") or "", d.get("ios") or "?")).strip() if d.get("iphone") else "CHƯA cắm USB / chưa gán",
                (" — nhóm «%s»" % d["group"]) if d.get("group") else "",
                (" — ĐANG CHẠY: %s" % (d.get("status") or "")) if d.get("running") else "",
                (" — ĐANG DỪNG CHỜ NGƯỜI KIỂM TRA (ON HOLD): %s" % d["hold"]) if d.get("hold") else "")
                + (" — NGƯỜI VẬN HÀNH ĐÃ DỪNG MÁY để xử lý tay (không điều khiển được cho tới khi họ bấm Tiếp tục)" if d.get("parked") else ""))
        return Result("\n".join(lines), {"devices": devs})

    def read_screen(self, device=None, include_text=True, include_image=True, scale=1.0):
        name, eyes = self._eyes(device)
        img = eyes.screenshot()
        h, w = img.shape[:2]
        data = {"device": name, "width": w, "height": h}
        head = "%s — màn hình %d×%d px. Toạ độ = pixel của ảnh gốc, gốc (0,0) ở góc trên-trái." % (name, w, h)
        parts = []
        if include_text:
            lines = ocr_lines(img)
            data["texts"] = lines
            head += "\nChữ đọc được (x,y = tâm dòng chữ):\n" + ("\n".join("(%d,%d) %s" % (r["x"], r["y"], r["text"]) for r in lines) or "(không đọc được chữ nào)")
        if include_image:
            s = max(0.2, min(float(scale or 1.0), 1.0))
            small = img if s >= 0.999 else cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if not ok:
                raise ToolError("không nén được ảnh chụp")
            data["image_scale"] = s
            if s < 0.999:
                head += "\nẢnh kèm theo đã thu nhỏ còn %.0f%% — toạ độ thật = toạ độ trên ảnh ÷ %.2f." % (s * 100, s)
            parts.append(image(buf.tobytes()))
        return Result([text(head)] + parts, data)

    def find_text(self, text, device=None):
        name, eyes = self._eyes(device)
        want = [norm_text(a).replace(" ", "") for a in stepexec.alternatives(text)]
        if not want:
            raise ToolError("Chưa nêu chữ cần tìm.")
        shot = eyes.screenshot()
        match = lambda rows: [r for r in rows if any(a in norm_text(r["text"]).replace(" ", "") for a in want)]
        hits = match(ocr_lines(shot))
        if not hits and pytesseract is not None:        # bộ đọc chính không thấy → hỏi thêm tesseract (thứ gì trước đây tìm được thì nay vẫn tìm được)
            hits = match(ocr_lines(shot, engine="tesseract"))
        if not hits:
            return Result("Không thấy chữ «%s» trên màn hình máy %s." % (text, name), {"device": name, "matches": []})
        return Result("\n".join("(%d,%d) %s" % (r["x"], r["y"], r["text"]) for r in hits), {"device": name, "matches": hits})

    def wait_for_text(self, text, device=None, timeout=stepexec.WAIT_TEXT_TIMEOUT):
        name, eyes = self._eyes(device)
        try:
            ok, why, _ = stepexec.exec_step(_EyesOnly(eyes), {"type": "wait_text", "text": text, "timeout": timeout}, {}, self._abort())
        except stepexec.ConfigError as e:
            raise ToolError(str(e))
        except stepexec.Aborted:
            raise ToolError("Đã dừng chờ theo yêu cầu huỷ.")
        self._need(ok, why, "Chờ chữ")
        return Result("Đã thấy chữ «%s» trên máy %s." % (text, name))

    # ---------- chạm ----------
    def tap(self, device=None, x=None, y=None, text=None):
        if text:
            name = self._step(device, {"type": "tap_text", "text": text}, "Bấm vào chữ «%s»" % text)
            return Result("Đã bấm vào chữ «%s» trên máy %s." % (text, name))
        if x is None or y is None:
            raise ToolError("Cần toạ độ x,y hoặc chữ cần bấm (text).")
        name = self._step(device, {"type": "tap", "x": x, "y": y}, "Bấm (%d,%d)" % (x, y))
        return Result("Đã bấm (%d,%d) trên máy %s." % (x, y, name))

    def long_press(self, device=None, x=None, y=None, text=None, seconds=1.0):
        if text:
            name = self._step(device, {"type": "hold_text", "text": text, "seconds": seconds}, "Bấm giữ chữ «%s»" % text)
            return Result("Đã bấm giữ %.1fs vào chữ «%s» trên máy %s." % (seconds, text, name))
        if x is None or y is None:
            raise ToolError("Cần toạ độ x,y hoặc chữ cần bấm giữ (text).")
        name = self._step(device, {"type": "hold", "x": x, "y": y, "seconds": seconds}, "Bấm giữ (%d,%d)" % (x, y))
        return Result("Đã bấm giữ %.1fs tại (%d,%d) trên máy %s." % (seconds, x, y, name))

    def swipe(self, device=None, direction=None, x1=None, y1=None, x2=None, y2=None):
        if direction:
            name = self._step(device, {"type": "swipe", "dir": direction}, "Vuốt %s" % direction)
            return Result("Đã vuốt %s trên máy %s (quãng vuốt chỉ xấp xỉ — đọc lại màn hình để xem tới đâu)." % (direction, name))
        if None in (x1, y1, x2, y2):
            raise ToolError("Cần hướng vuốt (left/right/up/down) hoặc đủ 4 toạ độ x1,y1,x2,y2.")
        name = self._step(device, {"type": "swipe", "x1": x1, "y1": y1, "x2": x2, "y2": y2}, "Vuốt")
        return Result("Đã vuốt từ (%d,%d) về phía (%d,%d) trên máy %s (quãng vuốt chỉ xấp xỉ)." % (x1, y1, x2, y2, name))

    def type_text(self, text, device=None, enter=False):
        if text == "":
            raise ToolError("Chưa có chữ cần gõ.")
        if any(not (32 <= ord(c) <= 126) for c in text):
            raise ToolError("Chỉ gõ được chữ không dấu, số và ký hiệu thường (ASCII) — không gõ được tiếng Việt có dấu.")
        if text != text.rstrip():
            raise ToolError("Chuỗi kết thúc bằng khoảng trắng — board không gõ được.")
        def run(nav):
            ok, why, _ = stepexec.hid(nav, "type " + text, wait=0.8 + 0.08 * len(text))
            self._need(ok, why, "Gõ chữ")
            time.sleep(stepexec.KEY_SETTLE)
            if enter:
                ok, why, _ = stepexec.hid(nav, "key enter")
                self._need(ok, why, "Phím Enter")
        name, _ = self._act(device, run)
        return Result("Đã gõ %d ký tự%s trên máy %s." % (len(text), " rồi Enter" if enter else "", name))   # không lặp lại nội dung (có thể là mật khẩu)

    def press_key(self, key, device=None):
        name = self._step(device, {"type": "key", "name": key}, "Phím %s" % key)
        return Result("Đã nhấn phím %s trên máy %s." % (key, name))

    def key_combo(self, keys, device=None):
        try:
            combo = stepexec.combo_keys(keys)
        except stepexec.ConfigError as e:
            raise ToolError(str(e))
        name = self._step(device, {"type": "combo", "keys": combo}, "Tổ hợp phím")
        return Result("Đã nhấn tổ hợp «%s» trên máy %s." % (combo, name))

    def board_health(self, device=None):
        """Sức khoẻ của board ESP32 điều khiển máy này: RAM, thời gian chạy, lý do reset lần trước, BLE rớt, lỗi serial…"""
        import boardhealth
        name, h = self._act(device, lambda nav: boardhealth.read(nav.h))
        if h is None:
            raise ToolError("Board của máy %s không trả lời lệnh status (đơ hoặc rớt kết nối). Thử board_recover." % name)
        lines = ["Board %s: %s — %s" % (name, {"ok": "KHOẺ", "info": "ổn (có ghi chú)", "warn": "CẢNH BÁO", "bad": "NẶNG"}[h["level"]], h["summary"])]
        lines += ["  • %s" % f["text"] for f in h["findings"]]
        data = {"device": name, **{k: h[k] for k in ("level", "summary", "findings", "connected", "fw", "up", "heap", "tot", "min", "blk", "rst", "drop", "rxerr", "cmds") if k in h}}
        return Result("\n".join(lines), data)

    def board_recover(self, device=None):
        """Đưa board về dùng được (LÚC RẢNH): board im → reset cứng; thiếu RAM / phân mảnh → reset mềm; rồi chờ iPhone nối lại BLE."""
        import boardhealth
        name, r = self._act(device, lambda nav: boardhealth.recover(nav.h, log=lambda m: None))
        h = r.get("health")
        head = "Board %s: %s." % (name, "đã dùng được" if r["ok"] else "VẪN CHƯA ỔN")
        acts = ("Đã làm: " + "; ".join(r["actions"])) if r["actions"] else "Không cần làm gì."
        if not r["ok"]:
            raise ToolError("%s %s %s" % (head, acts, ("Tình trạng: " + h["summary"]) if h else "Board không trả lời — kiểm tra cáp USB / nguồn."))
        return Result("%s %s Tình trạng: %s" % (head, acts, h["summary"]), {"device": name, "actions": r["actions"], "level": r["level"]})

    def go_home(self, device=None):
        name = self._step(device, {"type": "home"}, "Về màn hình chính")
        return Result("Đã về màn hình chính trên máy %s." % name)

    def open_app(self, app, device=None):
        name = self._step(device, {"type": "launch", "app": app}, "Mở app")
        return Result("Đã gõ «%s» vào ô tìm kiếm (Spotlight) rồi nhấn Enter trên máy %s. Hãy đọc lại màn hình để chắc app đã mở "
                      "(nếu vẫn ở trang kết quả tìm kiếm thì bấm vào dòng tên app)." % (app, name))

    def run_steps(self, steps, device=None, vars=None):
        if not isinstance(steps, list) or not steps:
            raise ToolError("steps phải là một danh sách bước, vd [{\"type\":\"tap_text\",\"text\":\"Cài đặt\"}].")
        plan = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or s.get("type") not in stepexec.STEP_TYPES:
                raise ToolError("Bước %d không hợp lệ: «type» phải là một trong %s." % (i + 1, ", ".join(stepexec.STEP_TYPES)))
            if "value" in s:                      # dạng {type, value} của gateway đời cũ không còn được nhận: chạy nó như bước thiếu tham số là bấm / gõ sai chỗ
                raise ToolError("Bước %d: không có trường «value» — ghi tham số theo từng loại bước (vd tap {x,y}, tap_text {text}, type {text}, wait {seconds})." % (i + 1))
            plan.append(dict(s))
        values = {str(k): str(v) for k, v in (vars or {}).items()} if isinstance(vars, dict) else {}

        abort = self._abort()

        def what(st):                      # mô tả bước để trả về: KHÔNG lặp lại chữ được gõ (có thể là mật khẩu)
            if st.get("type") == "type":
                return "Gõ %d ký tự" % len(str(st.get("text") or ""))
            return stepexec.describe(st, values)

        def run(nav):
            out = []
            obs = getattr(nav, "observer", None)          # lịch sử của máy (history.Tracker): cả chuỗi bước là MỘT lượt chạy, bước đánh số 1…N
            if obs is not None:
                obs.run_begin("AI / dòng lệnh: %d bước" % len(plan))
            stepexec.watch_phase(nav, None, len(plan))
            try:
                return run_plan(nav, out)
            finally:
                if obs is not None:
                    obs.run_end("chạy xong" if out and all(r["ok"] or plan[r["step"] - 1].get("optional") for r in out) and len(out) == len(plan) else "dừng ở bước lỗi")

        def run_plan(nav, out):
            for i, st in enumerate(plan):
                if abort():
                    out.append({"step": i + 1, "ok": False, "what": what(st), "why": "đã dừng theo yêu cầu huỷ"})
                    break
                try:
                    ok, why, _ = stepexec.exec_step(nav, st, values, abort)
                except (stepexec.ConfigError, stepexec.InputError, ValueError) as e:
                    ok, why = False, str(e)
                except stepexec.Aborted:
                    ok, why = False, "đã dừng theo yêu cầu huỷ"
                # bước có điều kiện xong theo HAI kiểu (đã bấm / không thấy nên bỏ qua) → người gọi phải biết kiểu nào; các bước khác xong thì không kèm lời
                out.append({"step": i + 1, "ok": bool(ok), "what": what(st), "why": why if (not ok or st.get("type") == "tap_if") else ""})
                if not ok and not st.get("optional"):
                    break
                time.sleep(stepexec.STEP_GAP)
            return out
        name, results = self._act(device, run)
        done = all(r["ok"] or plan[r["step"] - 1].get("optional") for r in results) and len(results) == len(plan)
        lines = ["%s %d. %s%s" % ("✓" if r["ok"] else "✗", r["step"], r["what"], (" — " + r["why"]) if r["why"] else "") for r in results]
        res = Result("Máy %s: %s\n%s" % (name, "chạy xong cả %d bước" % len(plan) if done else "DỪNG ở bước lỗi", "\n".join(lines)),
                     {"device": name, "completed": done, "results": results})
        if not done:
            raise ToolError(res.content[0]["text"])
        return res

    # ---------- nhóm máy / chạy kịch bản ----------
    def farm_status(self, log_lines=30):
        st = self.host.status()
        machines = st.get("machines") or {}
        lines = []
        for n, m in machines.items():
            c = m.get("counts") or {}
            what = " · ".join(x for x in (m.get("group_name"), m.get("script_name")) if x)          # «đang chạy {nhóm} · {kịch bản}»
            lines.append("%s: %s%s — %s%s" % (n, "đang chạy" if m.get("running") else ("DỪNG CHỜ NGƯỜI KIỂM TRA (ON HOLD)" if m.get("hold") else "nghỉ"),
                                              (" " + what) if (what and (m.get("running") or m.get("hold"))) else "", m.get("status") or "",
                                              (" (xong %s, lỗi %s, đối soát %s)" % (c.get("done", 0), c.get("failed", 0), c.get("review", 0))) if c else ""))
        log = (st.get("log") or [])[-int(log_lines):] if int(log_lines) > 0 else []
        body = ("\n".join(lines) or "Chưa có máy nào chạy.") + (("\n" + st["note"]) if st.get("note") else "")
        if log:
            body += "\n— nhật ký gần đây —\n" + "\n".join("%s %s: %s" % (e.get("t", ""), e.get("name", ""), e.get("text", "")) for e in log)
        return Result(body, {"machines": machines, "log": log})

    def list_groups(self):
        groups = self.host.groups()
        if not groups:
            return Result("Chưa có nhóm nào.", {"groups": []})
        def scripts_txt(g):
            sc = g.get("scripts") or []
            how = lambda s: ("NHẬN ĐƠN THẬT từ pool «%s»" % (s.get("pool") or "chưa chọn")) if s["mode"] == "orders" else ("lặp" if s["mode"] == "loop" else "1 lần")
            return " — kịch bản: " + (", ".join("«%s» (%d bước, %s)" % (s["name"], s["steps"], how(s)) for s in sc) or "chưa có")
        return Result("\n".join("%s (id %s) — máy: %s%s" % (
            g["name"], g["id"], ", ".join(g["devices"]) or "chưa có", scripts_txt(g)) for g in groups),
            {"groups": groups})

    def _group(self, group):
        groups = self.host.groups()
        want = norm_text(group)
        hits = [g for g in groups if g["id"] == group or norm_text(g["name"]) == want]
        if len(hits) != 1:
            raise ToolError("Không rõ nhóm «%s». Các nhóm: %s" % (group, ", ".join("%s (id %s)" % (g["name"], g["id"]) for g in groups) or "chưa có"))
        return hits[0]

    def start_run(self, group, device=None, script=None):
        g = self._group(group)
        name = self._resolve(device) if device else None
        scripts = g.get("scripts") or []           # phải biết chạy kịch bản nào (nhóm chỉ có 1 kịch bản thì tự lấy)
        if not scripts:
            raise ToolError("Nhóm «%s» chưa có kịch bản nào." % g["name"])
        hits = [s for s in scripts if s["id"] == script or (script and norm_text(s["name"]) == norm_text(script))] if script else (scripts if len(scripts) == 1 else [])
        if len(hits) != 1:
            raise ToolError("%s Các kịch bản của nhóm «%s»: %s." % (("Không rõ kịch bản «%s»." % script) if script else "Nhóm có nhiều kịch bản — nêu rõ chạy kịch bản nào (tham số script).",
                                                                   g["name"], ", ".join("«%s»" % s["name"] for s in scripts)))
        script, orders = hits[0]["id"], hits[0]["mode"] == "orders"
        held = {d["name"]: d["hold"] for d in self.host.devices() if d.get("hold") and d["name"] in ([name] if name else g["devices"])}
        if held:
            raise ToolError("Máy %s đang DỪNG CHỜ NGƯỜI KIỂM TRA (đơn dở cần đối soát): %s. Chỉ chạy lại khi người vận hành đã xử lý — "
                            "chỉ người vận hành gỡ được (nút «Đã kiểm tra xong» / «Chạy lại» trong app)." % (", ".join(held), "; ".join(held.values())))
        r = self.host.start(g["id"], name, script)
        if not r.get("ok"):
            raise ToolError(r.get("error") or "không chạy được")
        r = {k: v for k, v in r.items() if k != "group"}        # nhóm trả kèm (sau khi chép bước đời cũ) có cả nội dung bước — không đưa cho AI
        return Result("Đã cho %s của nhóm «%s» chạy kịch bản «%s»%s." % (("máy " + name) if name else "các máy", g["name"], hits[0]["name"],
                                                                     " (nhận đơn từ gateway)" if orders else ""), r)

    def stop_run(self, device=None, group=None, force=False):
        if not device and not group:
            raise ToolError("Nêu máy (device) hoặc nhóm (group) cần dừng.")
        name = self._resolve(device) if device else None
        grp = self._group(group) if group else None
        gid = grp["id"] if grp else None
        # Máy đang «dừng chờ người kiểm tra»: gỡ trạng thái này là LỜI XÁC NHẬN «tôi đã đối soát xong» (nút «Đã kiểm tra xong»). Lời xác nhận đó chỉ
        # người vận hành được đưa ra — AI/dòng lệnh không gỡ được (verify vòng 6, W-3).
        held = {d["name"]: d["hold"] for d in self.host.devices() if d.get("hold") and d["name"] in ([name] if name else (grp or {}).get("devices", []))}
        if held:
            raise ToolError("Máy %s đang DỪNG CHỜ NGƯỜI KIỂM TRA (%s). Việc gỡ trạng thái này là xác nhận «đã đối soát xong» nên chỉ người "
                            "vận hành làm được, bằng nút «Đã kiểm tra xong» / «Chạy lại» trong app. Muốn dừng các máy khác thì dừng riêng từng máy." % (
                                ", ".join(held), "; ".join(held.values())))
        r = self.host.stop(name, gid, bool(force))
        if not r.get("ok"):
            raise ToolError(r.get("error") or "không dừng được")
        return Result("Đã yêu cầu dừng %s%s." % (
            ("máy " + name) if name else "nhóm «%s»" % group,
            " NGAY (bỏ dở)" if force else " (chế độ nhận đơn: làm nốt đơn đang dở rồi dừng)"), r)

    def rescan_boards(self):
        r = self.host.rescan()
        if not r.get("ok"):
            raise ToolError(r.get("error") or "không quét được")
        return self.list_devices()


# ====================== danh sách công cụ (MCP + CLI dùng chung) ======================
_DEV = {"type": "string", "description": "Device (board) name from list_devices, e.g. \"iPhoneFarm-01\". May be omitted when only one device is ready."}
_X = {"type": "integer", "minimum": 0, "maximum": 5000}


def build_tools(c: Control) -> list:
    px = lambda d: dict(_X, description=d)
    return [
        Tool("list_devices", "List devices",
             "List the phones this farm controls: board present, Bluetooth link, iPhone model/iOS, group, and whether a run is active.",
             fn=c.list_devices, read_only=True, idempotent=True, cli="devices", help="Danh sách máy: board, Bluetooth, iPhone, nhóm, đang chạy hay không"),
        Tool("read_screen", "Read the phone screen",
             "Take a screenshot of the phone and return it as an image plus the OCR text lines with their centre coordinates "
             "(pixels of the full-size screenshot). Use it before and after every action. Not available while the device is processing a "
             "customer's paid order (privacy) — use farm_status then.",
             {"device": _DEV,
              "include_text": {"type": "boolean", "description": "Run OCR and list text lines with coordinates (default true; takes ~2 s)."},
              "include_image": {"type": "boolean", "description": "Attach the screenshot image (default true)."},
              "scale": {"type": "number", "minimum": 0.2, "maximum": 1.0, "description": "Shrink the attached image (default 1.0 = pixel coordinates read off the image are exact)."}},
             fn=c.read_screen, read_only=True, idempotent=True, cli="screen", positional=("device",), help="Chụp màn hình + đọc chữ kèm toạ độ"),
        Tool("find_text", "Find text on screen",
             "Locate a text on the phone screen by OCR (accent- and case-insensitive; use «a|b» for alternative spellings). Returns centre coordinates of every matching line.",
             {"text": {"type": "string", "description": "Text to look for."}, "device": _DEV}, ("text",),
             fn=c.find_text, read_only=True, idempotent=True, cli="find", positional=("device", "text"), help="Tìm chữ trên màn hình → toạ độ"),
        Tool("wait_for_text", "Wait for text",
             "Wait until a text appears on the phone screen (polls with OCR). Fails after the timeout.",
             {"text": {"type": "string", "description": "Text to wait for («a|b» = any of them)."}, "device": _DEV,
              "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "description": "Seconds to wait (default %d)." % stepexec.WAIT_TEXT_TIMEOUT}}, ("text",),
             fn=c.wait_for_text, read_only=True, idempotent=True, cli="wait", positional=("device", "text"), help="Chờ tới khi thấy chữ trên màn hình"),
        Tool("tap", "Tap",
             "Tap the phone screen either at pixel coordinates (x,y) or on a visible text. The pointer is moved in a closed loop and "
             "the tap only happens once the pointer is measured at the target (takes several seconds). On the home screen tap the ICON, not the label under it.",
             {"device": _DEV, "x": px("X in screenshot pixels."), "y": px("Y in screenshot pixels."),
              "text": {"type": "string", "description": "Tap the centre of this visible text instead of coordinates («a|b» = alternatives)."}},
             fn=c.tap, destructive=True, cli="tap", positional=("device", "x", "y"), help="Bấm vào toạ độ (x y) hoặc vào chữ (--text)"),
        Tool("long_press", "Long press",
             "Press and hold at (x,y) or on a visible text for a number of seconds, then release (context menus, edit mode…).",
             {"device": _DEV, "x": px("X in screenshot pixels."), "y": px("Y in screenshot pixels."),
              "text": {"type": "string", "description": "Hold on this visible text instead of coordinates."},
              "seconds": {"type": "number", "minimum": 0.2, "maximum": 10, "description": "How long to hold (default 1.0)."}},
             fn=c.long_press, destructive=True, cli="hold", positional=("device", "x", "y"), help="Bấm giữ tại toạ độ hoặc vào chữ"),
        Tool("swipe", "Swipe",
             "Swipe the screen: direction «left»/«right» flips a page, «up»/«down» scrolls a list (finger direction). "
             "Or give start (x1,y1) and end (x2,y2). The travelled distance is approximate — read the screen afterwards.",
             {"device": _DEV, "direction": {"type": "string", "enum": ["left", "right", "up", "down"], "description": "Finger direction."},
              "x1": px("Start X."), "y1": px("Start Y."), "x2": px("End X."), "y2": px("End Y.")},
             fn=c.swipe, destructive=True, cli="swipe", positional=("device", "direction"), help="Vuốt theo hướng (left/right/up/down) hoặc theo toạ độ"),
        Tool("type_text", "Type text",
             "Type text with the hardware keyboard into whatever field has focus (tap the field first). Printable ASCII only — "
             "no Vietnamese accents. Set enter=true to press Enter afterwards.",
             {"text": {"type": "string", "description": "Text to type."}, "device": _DEV,
              "enter": {"type": "boolean", "description": "Press Enter after typing (default false)."}}, ("text",),
             fn=c.type_text, destructive=True, cli="type", positional=("device", "text"), help="Gõ chữ (chỉ ASCII) vào ô đang được chọn"),
        Tool("press_key", "Press a key", "Press one key: enter, tab, esc, back (backspace) or space.",
             {"key": {"type": "string", "enum": list(stepexec.KEYS), "description": "Key name."}, "device": _DEV}, ("key",),
             fn=c.press_key, destructive=True, cli="key", positional=("device", "key"), help="Nhấn một phím: enter, tab, esc, back, space"),
        Tool("key_combo", "Key combination",
             "Press a keyboard shortcut: modifiers (gui/cmd, ctrl, alt, shift) followed by one key, e.g. «gui h» (Home), "
             "«gui space» (Spotlight search), «gui tab» (app switcher), «ctrl space» (switch input language).",
             {"keys": {"type": "string", "description": "Space-separated, e.g. \"gui h\"."}, "device": _DEV}, ("keys",),
             fn=c.key_combo, destructive=True, cli="combo", positional=("device", "keys"), help="Tổ hợp phím, vd \"gui h\" (về Home), \"gui space\" (tìm kiếm)"),
        Tool("board_health", "Check the ESP32 board health",
             "Read the health of the ESP32 board that drives a phone: RAM used / total, uptime, why it last reset (brownout = weak USB power, "
             "watchdog, crash), Bluetooth drops, serial errors. Refused while the device runs a script/order.",
             {"device": _DEV}, fn=c.board_health, read_only=True, idempotent=True, cli="health", positional=("device",),
             help="Sức khoẻ board ESP32: RAM, thời gian chạy, lý do reset, BLE rớt, lỗi serial"),
        Tool("board_recover", "Recover the ESP32 board",
             "Bring a stuck or low-memory ESP32 board back: reset it when it does not answer or is nearly out of RAM, then wait for the "
             "phone to reconnect over Bluetooth. Does nothing when the board is healthy. Never use it in the middle of an order "
             "(refused while the device runs); a reset drops Bluetooth for a few seconds.",
             {"device": _DEV}, fn=c.board_recover, destructive=True, idempotent=True, cli="recover", positional=("device",),
             help="Khởi động lại board ESP32 khi đơ / thiếu RAM (chỉ lúc rảnh)"),
        Tool("go_home", "Go to home screen", "Return to the iOS home screen (Cmd+H).", {"device": _DEV},
             fn=c.go_home, destructive=True, idempotent=True, cli="home", positional=("device",), help="Về màn hình chính"),
        Tool("open_app", "Open an app",
             "Open an app through Spotlight: goes home, types the app name and presses Enter. Read the screen afterwards to confirm; "
             "if the search results are still shown, tap the app's row.",
             {"app": {"type": "string", "description": "App name as typed into search (ASCII), e.g. \"Settings\"."}, "device": _DEV}, ("app",),
             fn=c.open_app, destructive=True, cli="open", positional=("device", "app"), help="Mở app qua ô tìm kiếm (Spotlight)"),
        Tool("run_steps", "Run a list of steps",
             "Run several steps in order on one device and stop at the first failure. Step types: tap {x,y}, tap_text {text,timeout} "
             "(`timeout` = seconds to wait for the text to appear before giving up; omit to look once — game screens take 1-3 s to change), "
             "tap_image {image,x,y,w,h,timeout,min} (`image` = base64 PNG crop of a full-size screenshot: finds that picture on screen and taps its centre — "
             "use it instead of fixed coordinates for buttons without text; ALWAYS pass `x,y,w,h` = the rectangle the crop was cut from: when several "
             "identical pictures are on screen the one nearest to it is tapped, without them the best/first match wins; `min` = minimum similarity, default 0.9), "
             "hold {x,y,seconds}, hold_text {text,seconds,timeout}, swipe {dir} or {x1,y1,x2,y2}, type {text}, key {name}, combo {keys}, "
             "launch {app,fresh} (`fresh`: true = force-quit the app and start it again over USB so it always begins at its first screen; "
             "without it a running app just comes to the front in whatever screen it was), home, wait {seconds}, wait_text {text,timeout}, "
             "assert_text {text}, type also takes `gap` (seconds between characters — use ~0.4 for one-digit-per-box code inputs), "
             "tap_if {text,tap|key,timeout} (if `text` shows up within `timeout` seconds tap the text `tap` — or press the key `key`, e.g. esc — "
             "and check it went away; else do nothing and continue. For dialogs that only sometimes appear). "
             "Add \"optional\": true to skip a step on failure.",
             {"steps": {"type": "array", "items": {"type": "object"}, "description": "Steps to run."}, "device": _DEV,
              "vars": {"type": "object", "description": "Values for {{placeholders}} used in step texts."}}, ("steps",),
             fn=c.run_steps, destructive=True, cli="run", positional=("device", "steps"), help="Chạy một chuỗi bước (JSON hoặc @tệp.json)"),
        Tool("farm_status", "Run status and log", "Show what each machine is doing right now (status, counters) and the recent run log.",
             {"log_lines": {"type": "integer", "minimum": 0, "maximum": 200, "description": "How many recent log lines (default 30)."}},
             fn=c.farm_status, read_only=True, idempotent=True, cli="status", help="Trạng thái các máy + nhật ký chạy gần đây"),
        Tool("list_groups", "List groups", "List device groups with their member devices and scripts (each script says how it runs: once / loop / NHẬN ĐƠN THẬT = takes real orders from the gateway).",
             fn=c.list_groups, read_only=True, idempotent=True, cli="groups", help="Danh sách nhóm máy"),
        Tool("start_run", "Start a script of a group on its machines",
             "Run one script of a group on all its devices (or just one). A machine runs ONE script at a time — a busy machine is skipped. "
             "A script whose mode is «orders» (list_groups shows it as NHẬN ĐƠN THẬT) takes REAL paid top-up orders "
             "from the gateway — only start those when the user explicitly asks.",
             {"group": {"type": "string", "description": "Group name or id (see list_groups)."}, "device": dict(_DEV, description="Only this device of the group (optional)."),
              "script": {"type": "string", "description": "Script name or id (see list_groups). Optional when the group has exactly one script."}},
             ("group",), fn=c.start_run, destructive=True, cli="start", positional=("group", "device"), help="Cho một kịch bản của nhóm (trên mọi máy, hoặc một máy) chạy; --script tên"),
        Tool("stop_run", "Stop a machine or group",
             "Stop a running machine or a whole group. Default: a machine taking orders finishes the current order first. "
             "force=true aborts immediately (an order that already touched the purchase flow goes to manual review).",
             {"device": dict(_DEV, description="Machine to stop."), "group": {"type": "string", "description": "Or: group name / id to stop."},
              "force": {"type": "boolean", "description": "Abort immediately (default false)."}},
             fn=c.stop_run, destructive=True, cli="stop", positional=("device",), help="Dừng một máy (hoặc --group nhóm); --force = dừng ngay"),
        Tool("rescan_boards", "Rescan boards", "Re-detect the Bluetooth boards on USB (after plugging/unplugging), then list devices.",
             fn=c.rescan_boards, destructive=False, idempotent=True, cli="rescan", help="Quét lại các board đang cắm"),
    ]


# ====================== không có app: tự mở cổng ======================
class StandaloneHost:
    """App chưa mở → tiến trình này tự dò board và tự mở cổng serial. Phiên điều khiển tự đóng sau IDLE giây
    không dùng để NHẢ cổng (mở app lên sau đó vẫn dùng được máy). Không chạy/dừng nhóm ở chế độ này."""
    IDLE = 25.0

    def __init__(self):
        self.lock = threading.Lock()
        self.boards = None          # tên board -> cổng
        self.ble = {}
        self.sessions, self.used, self.inuse = {}, {}, {}
        self._reaper = None

    def _scan(self):
        import esp
        found, ble = {}, {}
        def probe(b):
            p = esp.probe(b["port"])
            if p.get("name"):
                found[p["name"]] = b["port"]
                ble[p["name"]] = p.get("ble")
        threads = [threading.Thread(target=probe, args=(b,), daemon=True) for b in esp.list_boards()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.boards, self.ble = found, ble

    def udid(self, name):
        return next((d.get("udid") for d in store.get_devices() if d["name"] == name), None)

    def names(self):
        """Tên các máy đã biết — rẻ, không đụng cổng serial."""
        return [d["name"] for d in store.get_devices()]

    def eyes(self, name):
        udid = self.udid(name)
        if not udid:
            raise ToolError("Máy «%s» chưa gán iPhone (mở app → Thiết bị để gán)." % name)
        return Eyes(udid)

    def session(self, name):
        with self.lock:
            nav = self.sessions.get(name)
            if nav is None:
                # Dò board = mở MỌI cổng để hỏi tên → chỉ dò khi tiến trình này không đang giữ phiên nào
                # (dò chen vào cổng đang dùng sẽ làm lẫn phản hồi của lệnh đang chạy).
                if name not in (self.boards or {}) and not self.sessions:
                    self._scan()
                port = (self.boards or {}).get(name)
                if not port:
                    raise ToolError("Không thấy board «%s» đang cắm (hoặc cổng đang bị chương trình khác giữ)." % name)
                udid = self.udid(name)
                if not udid:
                    raise ToolError("Máy «%s» chưa gán iPhone (mở app → Thiết bị để gán)." % name)
                from nav import Nav
                try:
                    nav = Nav(port, udid)
                except Exception as e:
                    raise ToolError("Không mở được cổng của máy «%s» (%s) — có chương trình khác đang điều khiển máy này?" % (name, e))
                self.sessions[name] = nav
            self.inuse[name] = self.inuse.get(name, 0) + 1
            self.used[name] = time.time()
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap, name="control-idle", daemon=True)
                self._reaper.start()
            return nav

    def done(self, name):
        with self.lock:
            self.inuse[name] = max(0, self.inuse.get(name, 0) - 1)
            self.used[name] = time.time()

    def _reap_once(self, now=None):
        """Đóng các phiên đã rảnh quá IDLE giây. Phiên ĐANG chạy lệnh thì không bao giờ đóng, dù lệnh chạy lâu."""
        with self.lock:
            now = time.time() if now is None else now
            for n in [n for n in self.sessions if not self.inuse.get(n) and now - self.used.get(n, now) > self.IDLE]:
                try:
                    self.sessions.pop(n).close()
                except Exception:
                    pass

    def _reap(self):
        while True:
            time.sleep(3.0)
            self._reap_once()

    def close(self):
        """Đóng mọi phiên KHÔNG đang chạy lệnh (nhả cổng serial). Dùng lại host sau đó vẫn được."""
        with self.lock:
            for n in [n for n in self.sessions if not self.inuse.get(n)]:
                try:
                    self.sessions.pop(n).close()
                except Exception:
                    pass

    def acquire(self, name):
        return None                     # không có app: không ai khác trong tiến trình này tranh máy (cổng đã khoá độc quyền)

    def release(self, name):
        pass

    def active(self):
        with self.lock:
            return [n for n, k in self.inuse.items() if k > 0]

    def devices(self):
        import ios
        try:
            ios_by = {d["udid"]: d for d in ios.list_connected()}
        except Exception:
            ios_by = {}
        with self.lock:
            if self.boards is None and not self.sessions:
                self._scan()
            boards, ble = dict(self.boards or {}), dict(self.ble)
        grp = {}
        for g in store.get_groups():
            for dn in g.get("devices", []):
                grp[dn] = (grp[dn] + ", " if dn in grp else "") + g.get("name", g["id"])      # máy có thể ở nhiều nhóm
        out = []
        seen = set()
        for d in store.get_devices():
            info = ios_by.get(d.get("udid"))
            seen.add(d["name"])
            out.append({"name": d["name"], "label": d.get("label") or d["name"], "board": d["name"] in boards,
                        "bluetooth": ble.get(d["name"]), "iphone": info is not None, "ios": info["ios"] if info else None,
                        "model": info["model"] if info else None, "group": grp.get(d["name"]), "running": False, "status": ""})
        for n in boards:
            if n not in seen:
                out.append({"name": n, "label": n, "board": True, "bluetooth": ble.get(n), "iphone": False, "ios": None,
                            "model": None, "group": grp.get(n), "running": False, "status": ""})
        return out

    def status(self):
        return {"machines": {}, "log": [], "note": "App iPhone Farm Manager chưa mở nên không có máy nào đang chạy kịch bản."}

    def groups(self):
        return [group_view(g) for g in store.get_groups()]

    def start(self, group_id, name=None, script=None):
        return {"ok": False, "error": NEED_APP}

    def stop(self, name=None, group_id=None, force=False):
        return {"ok": False, "error": NEED_APP}

    def rescan(self):
        with self.lock:
            if self.sessions:
                return {"ok": False, "error": "Đang có máy được điều khiển — thử lại sau vài chục giây."}
            self._scan()
        return {"ok": True}


def group_view(g: dict) -> dict:
    """Thông tin một nhóm cho AI/CLI (không kèm các bước có thể chứa dữ liệu riêng)."""
    return {"id": g.get("id"), "name": g.get("name") or g.get("id"), "devices": list(g.get("devices") or []),
            "scripts": [script_view(s) for s in (g.get("scripts") or [])]}


def script_view(s: dict) -> dict:
    """Một kịch bản cho AI/CLI: tên, số bước, cách chạy — không kèm nội dung bước. Kịch bản NHẬN ĐƠN (mode «orders») kèm pool nó phục vụ;
    số bước của nó là tổng các giai đoạn."""
    out = {"id": s.get("id"), "name": s.get("name"), "steps": len(s.get("steps") or []), "mode": s.get("mode") or "once", "loops": s.get("loops", 0)}
    if out["mode"] == "orders":
        o = s.get("orders") or {}
        out["pool"] = o.get("pool") or None
        out["steps"] = sum(len(v or []) for v in (o.get("steps") or {}).values())
    return out


# ====================== app đang mở thì gọi sang app, không thì tự làm ======================
def proxied_tools():
    """Bộ công cụ cho CLI và máy chủ MCP stdio. Với MỖI lệnh: app đang mở → chuyển cho app làm (app là nơi
    giữ cổng serial, giao diện thấy được việc đang diễn ra); app chưa mở → tự mở cổng làm tại chỗ.
    Trả (danh sách Tool, host tại chỗ)."""
    host = StandaloneHost()
    tools = build_tools(Control(host))

    def wrap(tool):
        local = tool.fn

        def fn(**args):
            r = None if os.environ.get("FARM_LOCAL") == "1" else remote()
            if r is None:
                return local(**args)
            host.close()                      # nhả các cổng đang giữ tại chỗ để app mở được
            res = r.call(tool.name, args)
            content = res.get("content") or []
            if res.get("isError"):
                raise ToolError(next((c.get("text") for c in content if c.get("type") == "text"), "lỗi không rõ"))
            return Result(content, res.get("structuredContent"))
        tool.fn = fn
        return tool
    return [wrap(t) for t in tools], host


# ====================== bên trong app ======================
class AppHost:
    """App đang mở: dùng chính phiên điều khiển (cổng serial) và bộ chạy của app — một nơi giữ cổng duy nhất.
    `claims` (Claims) là sổ «ai đang dùng máy nào» dùng chung với giao diện và bộ chạy."""
    def __init__(self, mgr, runner, api, claims=None):
        self.mgr, self.runner, self.api = mgr, runner, api
        self.claims = claims or Claims(running=runner.is_running)
        self._scan = threading.Lock()

    def names(self):
        return [d["name"] for d in store.get_devices()]

    def _hold(self, name):
        fn = getattr(self.runner, "hold_reason", None)
        return fn(name) if fn else None

    def devices(self):
        st = self.runner.status()
        return [{"name": d["name"], "label": d.get("label") or d["name"], "board": bool(d.get("board_online")),
                 "bluetooth": d.get("ble"), "iphone": bool(d.get("ios_connected")), "ios": d.get("ios"), "model": d.get("model"),
                 "group": d.get("group_name"), "running": bool(d.get("running")),
                 "status": (st.get(d["name"]) or {}).get("status") or "", "hold": self._hold(d["name"]),
                 "parked": bool((st.get(d["name"]) or {}).get("parked"))} for d in self.api.list_devices()]

    def acquire(self, name):
        hold = self._hold(name)
        if hold:
            return ("Máy «%s» đang DỪNG CHỜ NGƯỜI KIỂM TRA: %s. Màn hình đang được giữ nguyên để đối soát — không điều khiển "
                    "cho tới khi người vận hành xử lý xong (nút «Đã kiểm tra xong» / «Chạy lại» trong app)." % (name, hold))
        is_parked = getattr(self.runner, "is_parked", None)
        if is_parked and is_parked(name):
            return ("Máy «%s» đang DỪNG để người vận hành xử lý tay — không điều khiển qua AI / dòng lệnh cho tới khi họ bấm «Tiếp tục» trong app." % name)
        conflict = getattr(self.runner, "conflict", None)       # tên khác nhưng CÙNG iPhone / board với một máy của khách → cũng không điều khiển
        if conflict:
            try:
                udid = self.mgr._udid(name)
            except Exception:
                udid = None
            hit = conflict(name, udid, getattr(self.mgr, "board_map", {}).get(name))
            if hit and hit != name:
                return ("Máy «%s» dùng chung iPhone / board với máy «%s» đang làm đơn của khách (hoặc đang dừng chờ kiểm tra) — không điều khiển "
                        "qua AI / dòng lệnh lúc này." % (name, hit))
        return self.claims.acquire(name, "ai")

    def release(self, name):
        self.claims.release(name, "ai")

    def active(self):
        return self.claims.names("ai")

    def session(self, name):
        with self._scan:
            if name not in self.mgr.board_map and not self.mgr.sessions and not self.runner.running_names():
                # App vừa mở, chưa quét board lần nào (hoặc board vừa cắm lại) → quét rồi mới mở phiên. Chỉ quét
                # khi không máy nào đang chạy và không phiên nào đang mở: quét = mở MỌI cổng để hỏi tên.
                try:
                    self.mgr.rescan()
                except Exception:
                    pass
        return self.mgr.session(name)

    def done(self, name):
        pass

    def eyes(self, name):
        udid = self.mgr._udid(name)
        if not udid:
            raise ToolError("Máy «%s» chưa gán iPhone (trang Thiết bị → gán UDID / Dò máy)." % name)
        w = self.runner.status().get(name) or {}
        conflict = getattr(self.runner, "conflict", None)       # so theo MÁY THẬT (iPhone + cổng board ghi lúc bắt đầu chạy), không chỉ theo tên
        same_phone = conflict(name, udid, getattr(self.mgr, "board_map", {}).get(name)) if conflict else None
        if same_phone or (w.get("mode") == "api" and (w.get("running") or self._hold(name))):
            # Máy đang làm đơn của KHÁCH — hoặc vừa dừng giữa chừng và màn hình được GIỮ NGUYÊN cho người kiểm tra:
            # màn hình có thể đang hiện tài khoản, mã OTP… → không đưa ảnh/chữ đó cho AI hay lưu ra tệp.
            # Xem tiến độ bằng farm_status.
            raise ToolError("Máy «%s» đang nhận đơn của khách (hoặc đang dừng chờ người kiểm tra sau đơn của khách) — không xem màn hình "
                            "qua AI / dòng lệnh lúc này (tránh lộ thông tin của khách). Dùng farm_status để xem tiến độ." % name)
        return Eyes(udid)

    def status(self):
        machines = self.runner.status()
        for n, m in machines.items():
            m["hold"] = self._hold(n)
        return {"machines": machines, "log": self.runner.log_tail(200)}

    def groups(self):
        return [group_view(g) for g in store.get_groups()]

    def start(self, group_id, name=None, script=None):
        return self.api.machine_run(group_id, name, script) if name else self.api.group_run(group_id, None, script)

    def stop(self, name=None, group_id=None, force=False):
        return self.api.machine_stop(name, force) if name else self.api.group_stop(group_id, force)

    def rescan(self):
        return self.api.rescan()


class AppServer:
    """Máy chủ điều khiển của app: MCP qua HTTP trên 127.0.0.1 + tệp cổng/khoá cho CLI và `farm mcp` tìm thấy."""
    def __init__(self, host, version="1.0.0"):
        from mcpserver import McpServer
        self.control = Control(host)
        self.server = McpServer(build_tools(self.control), version=version, instructions=INSTRUCTIONS)
        self.httpd, self.port, self.token, self.error = None, None, None, None

    def start(self, port: int = DEFAULT_PORT) -> bool:
        from mcpserver import serve_http
        self.stop()
        self.token = token()
        try:
            self.httpd, self.port = serve_http(self.server, self.token, port, extra_health=lambda: {"host": "app"})
        except OSError as e:
            self.error = str(e)
            return False
        self.error = None
        save_endpoint(self.port, self.token)
        return True

    def stop(self):
        self.control.cancel_all()           # tắt cầu nối / đổi khoá = dừng luôn các lệnh AI đang chạy dở
        self.server.cancel()
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd, self.port = None, None
        ep = load_endpoint()
        if ep and ep.get("pid") == os.getpid():          # giữ khoá, xoá cổng → CLI biết app không còn nghe
            save_endpoint(0, ep["token"], enabled=False)

    def renew_token(self) -> bool:
        """Đổi khoá (khi nghi lộ): mọi client HTTP đang dùng khoá cũ sẽ bị từ chối."""
        port = self.port or DEFAULT_PORT
        self.stop()
        save_endpoint(0, token(renew=True), enabled=False)
        return self.start(port)

    def info(self) -> dict:
        farm = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "farm.bat" if os.name == "nt" else "farm")
        return {"running": self.httpd is not None, "port": self.port, "token": self.token, "error": self.error,
                "url": ("http://127.0.0.1:%d/mcp" % self.port) if self.port else None,
                "farm": farm, "active": self.control.active(),
                # đường dẫn có dấu cách (vd C:\\Users\\Nguyen Van A\\AppData\\…) phải nằm trong nháy kép thì lệnh dán vào terminal mới chạy
                "claude_code": "claude mcp add iphone-farm -- %s mcp" % ('"%s"' % farm if " " in farm else farm),
                "json": json.dumps({"mcpServers": {"iphone-farm": {"command": farm, "args": ["mcp"]}}}, ensure_ascii=False, indent=2)}
