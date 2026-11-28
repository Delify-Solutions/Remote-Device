#!/usr/bin/env python3
"""
notify.py — bắn THÔNG BÁO TELEGRAM cho admin khi một máy cần người: máy dừng chờ admin (màn hình lạ AI không xử lý được),
đơn của khách cần đối soát, bước lỗi / kịch bản dừng, board ESP32 / Bluetooth mất kết nối.

Cấu hình (app/data/settings.json — không vào git):
  telegram_token    mã bot (lấy từ @BotFather)
  telegram_chat     chat id nhận thông báo (người, nhóm hay kênh — bot phải được thêm vào nhóm / kênh)
  telegram_events   các loại sự kiện được bắn (mặc định: tất cả EVENTS)

Gửi trong MỘT luồng nền (không bao giờ làm chậm / làm hỏng máy đang chạy). Cùng một thông báo của cùng máy lặp lại trong DEDUPE giây
thì chỉ gửi một lần. Lời báo lỗi không bao giờ chứa mã bot.
"""
from __future__ import annotations
import json, os, queue, threading, time, urllib.error, urllib.parse, urllib.request, uuid

EVENTS = {
    "paused": "Máy dừng chờ admin",
    "review": "Đơn cần đối soát",
    "failed": "Bước lỗi / kịch bản dừng",
    "link": "Board / Bluetooth mất kết nối",
    "wallet": "Ví tài khoản Apple không đủ tiền",
}
OLD_EVENTS = ("paused", "review", "failed", "link")      # các loại đã có trước khi lưu kèm danh sách «đã biết» (telegram_events_known)
ICON = {"paused": "⏸", "review": "🧾", "failed": "⛔", "link": "🔌", "wallet": "💰"}
ZERO_DECIMAL = ("JPY", "KRW", "VND", "IDR", "CLP", "TWD", "HUF", "ISK")      # tiền không có phần lẻ khi hiển thị


def money(x100, currency) -> str:
    """Số tiền gateway gửi (đơn vị ×100, số nguyên) → chữ đọc được: 40000000 JPY → «400.000 JPY», 80 CHF → «0,80 CHF»."""
    try:
        v = int(x100)
    except (TypeError, ValueError):
        return "?"
    cur = str(currency or "").upper()
    neg, v = v < 0, abs(v)
    whole, frac = divmod(v, 100)
    s = "{:,}".format(whole).replace(",", ".")
    if cur not in ZERO_DECIMAL:
        s += ",%02d" % frac
    return ("-" if neg else "") + s + (" " + cur if cur else "")
DEDUPE = 600.0          # giây: cùng (loại, máy, nội dung) trong chừng này chỉ gửi một lần
QUEUE_MAX = 200         # hàng chờ đầy (mạng chết lâu) thì bỏ thông báo mới, không giữ bộ nhớ vô hạn
TIMEOUT = 15.0
API = "https://api.telegram.org"
TEXT_MAX = 3500         # Telegram giới hạn 4096 ký tự / tin; chú thích ảnh 1024
CAPTION_MAX = 1000


def link_trouble(text) -> bool:
    """Lý do lỗi này là do board ESP32 / Bluetooth (không phải do màn hình / kịch bản)?"""
    t = str(text or "").lower()
    return any(k in t for k in ("bluetooth", "board không phản hồi", "board esp32", "cổng serial", "board báo lỗi", "không thấy board"))


class Telegram:
    def __init__(self, settings, opener=None, clock=time.time):
        """`settings()` trả dict cấu hình hiện tại (đọc lại mỗi lần gửi: đổi cấu hình không cần khởi động lại).
        `opener(req, timeout)` gửi một urllib Request và trả bytes — test thay bằng hàm giả."""
        self._settings = settings
        self._open = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout).read())
        self._clock = clock
        self._q = queue.Queue(maxsize=QUEUE_MAX)
        self._seen = {}
        self._lock = threading.Lock()
        self._thread = None
        self.last_error = ""
        self.sent = 0

    # ---------- cấu hình ----------
    def config(self):
        s = self._settings() or {}
        events = s.get("telegram_events")
        if not isinstance(events, list):
            events = list(EVENTS)
        else:
            # Loại sự kiện MỚI thêm sau lần lưu cuối (vd «Ví không đủ tiền») tự BẬT: người đã lưu danh sách cũ không bị lặng lẽ mất cảnh báo.
            known = s.get("telegram_events_known")
            known = known if isinstance(known, list) else list(OLD_EVENTS)
            events = list(events) + [e for e in EVENTS if e not in known and e not in events]
        return {"token": str(s.get("telegram_token") or "").strip(), "chat": str(s.get("telegram_chat") or "").strip(),
                "events": [e for e in events if e in EVENTS]}

    def configured(self) -> bool:
        c = self.config()
        return bool(c["token"] and c["chat"])

    # ---------- gửi ----------
    def notify(self, event, machine, lines, photo=None) -> bool:
        """Xếp một thông báo vào hàng gửi. `lines`: các dòng nội dung (đã che dữ liệu bí mật). `photo`: ảnh JPEG (bytes) hoặc None.
        Trả False nếu không gửi (chưa cấu hình, loại sự kiện bị tắt, trùng thông báo vừa gửi, hàng chờ đầy)."""
        if event not in EVENTS or os.environ.get("IPF_NO_TELEGRAM"):     # bộ kiểm thử đặt biến này: không bao giờ bắn tin thật
            return False
        c = self.config()
        if not (c["token"] and c["chat"]) or event not in c["events"]:
            return False
        body = [str(x) for x in (lines if isinstance(lines, (list, tuple)) else [lines]) if str(x or "").strip()]
        key = (event, str(machine), "\n".join(body))
        now = self._clock()
        with self._lock:
            for k in [k for k, t in self._seen.items() if now - t > DEDUPE]:
                del self._seen[k]
            if key in self._seen:
                return False
            self._seen[key] = now
        text = "%s %s — %s\n%s\nLúc: %s" % (ICON[event], EVENTS[event], machine, "\n".join(body),
                                           time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))
        try:
            self._q.put_nowait((text, photo, key))
        except queue.Full:
            with self._lock:
                self._seen.pop(key, None)                # không gửi được thì lần sau (khi mạng / hàng chờ ổn lại) được báo lại
            return False
        self._ensure_worker()
        return True

    def send_now(self, text, photo=None):
        """Gửi NGAY (đồng bộ) — cho nút «Gửi thử». Trả (ok, lỗi)."""
        c = self.config()
        if not (c["token"] and c["chat"]):
            return False, "chưa nhập mã bot và chat id"
        if os.environ.get("IPF_NO_TELEGRAM"):
            return False, "đang chạy kiểm thử (IPF_NO_TELEGRAM) — không gửi tin thật"
        return self._send(c, text, photo)

    def chats(self, token=None):
        """Các chat đã nói chuyện với bot gần đây (người nhắn cho bot, nhóm / kênh có bot — kể cả lúc VỪA KÉO bot vào nhóm), để chọn chat id
        khỏi phải mở getUpdates bằng tay. Trả (danh sách [{id, title, type}], lỗi). Không bao giờ trả mã bot trong lỗi."""
        tok = str(token or "").strip() or self.config()["token"]
        if not tok:
            return [], "chưa nhập mã bot"
        if os.environ.get("IPF_NO_TELEGRAM"):
            return [], "đang chạy kiểm thử (IPF_NO_TELEGRAM) — không gọi Telegram thật"
        try:
            req = urllib.request.Request("%s/bot%s/getUpdates?%s" % (API, tok, urllib.parse.urlencode(
                # offset=-100: 100 tin MỚI NHẤT (không có offset thì là 100 tin CŨ NHẤT chưa xác nhận — bot bận thì nhóm vừa kéo vào bị lọt)
                {"offset": -100, "limit": 100, "timeout": 0,
                 "allowed_updates": json.dumps(["message", "channel_post", "my_chat_member", "chat_member"])})))
            raw = self._open(req, TIMEOUT)
            res = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        except urllib.error.HTTPError as e:
            try:
                desc = json.loads(e.read().decode("utf-8", "replace")).get("description") or ""
            except Exception:
                desc = ""
            if e.code == 409:
                if "webhook" in desc.lower():
                    return [], "bot đang dùng webhook nên không đọc được tin — tắt webhook của bot rồi thử lại"
                return [], _clean("bot đang được một chương trình khác đọc tin (%s) — tắt chương trình đó rồi thử lại" % (desc or "409"), tok)
            if e.code in (401, 404):
                return [], "mã bot không đúng"
            return [], _clean("Telegram báo lỗi %s%s" % (e.code, (": " + desc) if desc else ""), tok)
        except Exception as e:
            return [], _clean("không gọi được Telegram: %s" % e, tok)
        if not res.get("ok"):
            return [], _clean(res.get("description") or "Telegram từ chối", tok)
        found = {}
        for u in res.get("result") or []:
            for k in ("message", "edited_message", "channel_post", "my_chat_member", "chat_member"):
                ch = (u.get(k) or {}).get("chat") if isinstance(u.get(k), dict) else None
                if not isinstance(ch, dict) or "id" not in ch:
                    continue
                title = ch.get("title") or " ".join(x for x in (ch.get("first_name"), ch.get("last_name")) if x) or ch.get("username") or ""
                found.pop(ch["id"], None)
                found[ch["id"]] = {"id": str(ch["id"]), "title": str(title)[:80], "type": str(ch.get("type") or "")}
        return list(found.values())[::-1], ""                # mới thấy gần nhất lên đầu (dict giữ thứ tự lần GHI cuối: xoá rồi ghi lại)

    def _ensure_worker(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="telegram", daemon=True)
            self._thread.start()

    def _loop(self):
        # Luồng sống suốt đời tiến trình (daemon): một luồng tự thoát khi rảnh sẽ có kẽ hở — tin vừa xếp đúng lúc nó đang thoát nằm
        # chờ mãi tới tận lần báo sau.
        while True:
            text, photo, key = self._q.get()
            try:
                c = self.config()
                ok, err = (False, "chưa nhập mã bot và chat id")
                if c["token"] and c["chat"]:
                    ok, err = self._send(c, text, photo)
                    if not ok and photo is not None:     # ảnh không gửi được (quá to, mạng chập chờn) → vẫn phải báo bằng chữ
                        ok, err = self._send(c, text, None)
                self.last_error = "" if ok else err
                if not ok:
                    with self._lock:
                        self._seen.pop(key, None)        # tin này chưa tới được admin → lần báo sau không bị coi là «trùng»
            except Exception as e:                       # không bao giờ để luồng gửi chết (kể cả khi đọc cấu hình lỗi)
                try:
                    tok = self.config()["token"]
                except Exception:
                    tok = ""
                self.last_error = _clean("lỗi khi gửi: %s" % e, tok)

    def _send(self, c, text, photo):
        token = c["token"]
        try:
            if photo:
                boundary = uuid.uuid4().hex
                body = _multipart(boundary, {"chat_id": c["chat"], "caption": text[:CAPTION_MAX]},
                                  "photo", "man-hinh.jpg", "image/jpeg", photo)
                req = urllib.request.Request("%s/bot%s/sendPhoto" % (API, token), data=body,
                                             headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
            else:
                data = urllib.parse.urlencode({"chat_id": c["chat"], "text": text[:TEXT_MAX],
                                               "disable_web_page_preview": "true"}).encode()
                req = urllib.request.Request("%s/bot%s/sendMessage" % (API, token), data=data,
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
            raw = self._open(req, TIMEOUT)
            res = json.loads(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
            if not res.get("ok"):
                return False, _clean(res.get("description") or "Telegram từ chối", token)
            self.sent += 1
            return True, ""
        except urllib.error.HTTPError as e:
            try:
                desc = json.loads(e.read().decode("utf-8", "replace")).get("description")
            except Exception:
                desc = None
            return False, _clean("Telegram báo lỗi %s%s" % (e.code, (": " + desc) if desc else ""), token)
        except Exception as e:
            return False, _clean("không gửi được tới Telegram: %s" % e, token)


def _clean(msg, token) -> str:
    """Lời báo lỗi không bao giờ mang mã bot (urllib có thể in cả địa chỉ gọi)."""
    msg = str(msg)
    return msg.replace(token, "<mã bot>") if token else msg


def _multipart(boundary, fields, file_field, filename, ctype, payload) -> bytes:
    out = []
    for k, v in fields.items():
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode("utf-8"))
    out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                % (boundary, file_field, filename, ctype)).encode("utf-8"))
    out.append(payload)
    out.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(out)
