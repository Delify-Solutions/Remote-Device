#!/usr/bin/env python3
"""
presence.py — tool TỰ BÁO cho Topup Gateway: máy nào đang RẢNH ở kịch bản nào + danh mục kịch bản.

Gateway nằm ngoài Internet còn tool nằm trong mạng nội bộ → gateway không gọi được vào tool. Vì vậy tool tự gọi
`POST /api/tool/sync` mỗi ~20 giây và ngay khi có thay đổi (máy bắt đầu / xong việc, bị dừng, sửa kịch bản…):

  devices : ảnh chụp TOÀN BỘ máy lúc này — trạng thái từng máy + máy đó chạy được những kịch bản nào
  scripts : danh mục kịch bản (soạn ở «Nhóm & Kịch bản») — CHỈ gửi khi đổi: tool luôn gửi mã băm `scripts_rev`,
            gateway trả `need_scripts` nếu bản nó đang giữ khác.

Những gì KHÔNG rời khỏi máy này: nội dung gõ, toạ độ, tên app trong các bước (gateway chỉ nhận DÀN Ý: loại bước + ghi chú
+ tên các {{biến}} kịch bản cần dữ liệu), UDID của iPhone, cổng serial, lý do «dừng chờ kiểm tra» (có thể chứa mã đơn).

Luồng này chỉ BÁO TIN. Nó không nhận đơn, không đụng tới đơn đang chạy (việc đó của runner: claim / heartbeat / result).
"""
from __future__ import annotations
import hashlib, json, re, threading, time

from gateway import GatewayError

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")     # cùng dạng với apimode.PLACEHOLDER
VAR_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,59}$")
ID_OK = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
STEP_TYPE_OK = re.compile(r"^[a-z][a-z_]{0,19}$")
MAX_OUTLINE = 80
ORDER_PHASES = ("login", "otp", "nav", "purchase", "after", "finish")      # giai đoạn của một đơn (cùng thứ tự với apimode.PHASES)
MAX_DEVICES, MAX_SCRIPTS = 200, 300      # trần của gateway cho một khoá Tool
MAX_CATALOG_BYTES = 600_000              # danh mục lớn hơn chừng này thì bỏ dàn ý (gateway chỉ nhận thân tối đa 1 MB)
MAX_BODY_BYTES = 950_000

# trạng thái của một máy (gateway hiểu đúng các chữ này; chữ lạ bị coi là «chưa sẵn sàng»)
IDLE, RUNNING, ORDERS, PAUSED, HOLD, MANUAL, OFFLINE = "idle", "running", "orders", "paused", "hold", "manual", "offline"


def script_uid(group_id, script_id):
    """«mã nhóm:mã kịch bản» — định danh một kịch bản trên gateway; None nếu mã có ký tự gateway không nhận."""
    gid, sid = str(group_id or ""), str(script_id or "")
    return "%s:%s" % (gid, sid) if ID_OK.fullmatch(gid) and ID_OK.fullmatch(sid) else None


def step_vars(steps) -> list:
    """Tên các {{biến}} mà kịch bản cần dữ liệu, theo thứ tự xuất hiện, không lặp."""
    out = []

    def walk(v, depth=0):
        if isinstance(v, str):
            for k in PLACEHOLDER.findall(v):
                if VAR_OK.fullmatch(k) and k not in out:
                    out.append(k)
        elif depth < 4 and isinstance(v, dict):          # (bước «nếu … thì bấm» có danh sách trường hợp lồng bên trong)
            for x in v.values():
                walk(x, depth + 1)
        elif depth < 4 and isinstance(v, list):
            for x in v:
                walk(x, depth + 1)
    for st in steps or []:
        if isinstance(st, dict):
            walk(st)
    return out[:40]


def outline(steps) -> list:
    """DÀN Ý của kịch bản: loại từng bước + ghi chú + cờ «bỏ qua nếu lỗi». Cố ý KHÔNG kèm chữ gõ / toạ độ / tên app."""
    out = []
    for st in steps or []:
        t = st.get("type") if isinstance(st, dict) else None
        if not isinstance(t, str) or not STEP_TYPE_OK.fullmatch(t):
            continue
        out.append({"type": t, "note": str(st.get("note") or "")[:120], "optional": bool(st.get("optional"))})
        if len(out) >= MAX_OUTLINE:
            break
    return out


def catalog(groups) -> tuple:
    """(danh mục kịch bản, mã băm)."""
    rows = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for sc in g.get("scripts") or []:
            uid = script_uid(g.get("id"), sc.get("id")) if isinstance(sc, dict) else None
            if not uid:
                continue
            steps = sc.get("steps") if isinstance(sc.get("steps"), list) else []
            try:
                loops = max(0, min(1000000, int(sc.get("loops", 1))))
            except (TypeError, ValueError):
                loops = 1
            row = {"uid": uid, "group": str(g.get("name") or g.get("id"))[:160], "name": str(sc.get("name") or sc.get("id"))[:160],
                   "mode": sc.get("mode") if sc.get("mode") in ("loop", "orders") else "once", "loops": loops}
            if row["mode"] == "orders":
                # KỊCH BẢN NHẬN ĐƠN: gateway cần biết nó phục vụ pool nào; các bước của nó chia theo giai đoạn của một đơn
                o = sc.get("orders") if isinstance(sc.get("orders"), dict) else {}
                phases = o.get("steps") if isinstance(o.get("steps"), dict) else {}
                steps, lines = [], []
                for ph in ORDER_PHASES:
                    part = phases.get(ph) if isinstance(phases.get(ph), list) else []
                    steps += part
                    lines += [dict(x, phase=ph) for x in outline(part)]
                row["pool"] = str(o.get("pool") or "")[:40]
                row.update(step_count=len(steps), vars=step_vars(steps), outline=lines[:MAX_OUTLINE])
            else:
                row.update(step_count=len(steps), vars=step_vars(steps), outline=outline(steps))
            rows.append(row)
    rows.sort(key=lambda r: r["uid"])
    rows = rows[:MAX_SCRIPTS]                               # gateway từ chối CẢ lời báo nếu vượt trần → tự cắt cho vừa
    blob = _blob(rows)
    if len(blob) > MAX_CATALOG_BYTES:                       # danh mục quá lớn: bỏ dàn ý (tên, số bước, biến vẫn đủ)
        rows = [dict(r, outline=[]) for r in rows]
        blob = _blob(rows)
    return rows, hashlib.sha256(blob).hexdigest()


def _blob(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def device_status(f: dict) -> tuple:
    """(trạng thái, ghi chú) của một máy từ các dữ kiện `f`. Thứ tự ưu tiên: thứ gì CẤM chạy thì báo trước.
    Chỉ «idle» mới nghĩa là máy sẵn sàng nhận việc ngay — khi không chắc thì KHÔNG báo rảnh."""
    if f.get("hold"):
        return HOLD, "dừng chờ người kiểm tra sau đơn của khách"
    if f.get("parked"):
        return PAUSED, "người vận hành bấm Dừng máy để xử lý tay"
    if f.get("running"):
        return (ORDERS, "") if f.get("run_mode") == "api" else (RUNNING, "")
    if f.get("claimed"):
        return MANUAL, "đang được điều khiển tay (thử bước / AI)"
    if not f.get("board_online"):
        return OFFLINE, "board ESP32 chưa cắm / chưa quét thấy"
    if not f.get("udid"):
        return OFFLINE, "board chưa gán iPhone"
    if not f.get("ios_connected"):
        return OFFLINE, "iPhone chưa cắm USB"
    if f.get("ble") is False:
        return OFFLINE, "Bluetooth của board chưa nối với iPhone"
    if f.get("ble") is not True:                            # chưa đọc được trạng thái Bluetooth lần nào → chưa chắc bấm được lên máy
        return OFFLINE, "chưa biết Bluetooth của board đã nối chưa (bấm Quét board)"
    return IDLE, ""


def build(devices, groups, tool=None) -> tuple:
    """Dựng thân lời báo. `devices`: danh sách dữ kiện từng máy — {name, label, board_online, udid (có gán hay không), ios_connected, ble,
    running, run_mode, run_group_id, run_script_id, run_group, run_script, iter, parked, hold, claimed}.
    Trả (thân KHÔNG kèm danh mục, danh mục). Thân chỉ đổi khi có gì đó thật sự đổi → dùng làm dấu để biết có cần báo ngay không."""
    rows, rev = catalog(groups)
    by_dev = {}
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        uids = [u for u in (script_uid(g.get("id"), sc.get("id")) for sc in (g.get("scripts") or []) if isinstance(sc, dict)) if u]
        for name in g.get("devices") or []:
            have = by_dev.setdefault(name, [])
            have.extend(u for u in uids if u not in have)
    out = []
    for f in devices or []:
        name = str(f.get("name") or "").strip()[:80]
        if not name or any(d["name"] == name for d in out):
            continue
        status, note = device_status(f)
        entry = {"name": name, "status": status, "scripts": sorted(by_dev.get(name, []))[:100]}
        label = str(f.get("label") or "").strip()[:120]
        if label and label != name:
            entry["label"] = label
        if note:
            entry["note"] = note
        if f.get("running"):
            # đang chạy kịch bản — kể cả KỊCH BẢN NHẬN ĐƠN (run_mode «api»): gateway thấy máy đang nhận đơn bằng kịch bản nào
            run = {"group": str(f.get("run_group") or "")[:160], "script": str(f.get("run_script") or "")[:160]}
            uid = script_uid(f.get("run_group_id"), f.get("run_script_id"))
            if uid:
                run["uid"] = uid
            if f.get("iter") and f.get("run_mode") != "api":
                run["iter"] = int(f["iter"])
            entry["running"] = run
        out.append(entry)
    out.sort(key=lambda d: d["name"])
    body = {"tool": dict(tool or {}), "scripts_rev": rev, "devices": out[:MAX_DEVICES]}
    return body, rows


def signature(body) -> str:
    """Dấu để biết «có gì ĐÁNG báo ngay không». Số vòng đang chạy (`iter`) cố ý không tính: kịch bản lặp đổi số vòng liên tục, tính vào
    thì mỗi vài giây lại báo một lần; số vòng mới vẫn tới gateway theo nhịp đều."""
    devs = []
    for d in body.get("devices") or []:
        if isinstance(d.get("running"), dict) and "iter" in d["running"]:
            d = dict(d, running={k: v for k, v in d["running"].items() if k != "iter"})
        devs.append(d)
    return json.dumps(dict(body, devices=devs), sort_keys=True, ensure_ascii=False)


class Reporter:
    """Luồng nền báo tin cho gateway. Soát thay đổi mỗi TICK giây; gửi khi có thay đổi hoặc đã quá EVERY giây kể từ lần gửi được."""
    EVERY = 20.0            # nhịp báo đều (gateway coi lời báo cũ hơn 90 giây là mất kết nối)
    TICK = 3.0              # nhịp soát thay đổi
    ERROR_WAIT = 30.0       # gateway lỗi / mất mạng → bao lâu thử lại
    AUTH_WAIT = 300.0       # sai khoá / gateway chưa có API này → thưa hẳn ra (gateway chặn IP sai khoá quá 30 lần / 10 phút)
    IDLE_WAIT = 15.0        # chưa cấu hình gateway → bao lâu xem lại
    MIN_GAP = 2.0           # hai lần GỌI gateway cách nhau ít nhất chừng này (bấm «báo ngay» liên tục cũng không dội gateway)

    def __init__(self, gateway_factory, facts, tool_info=None, clock=time.monotonic, wallets=None):
        self._gateway = gateway_factory       # () -> Gateway (ném GatewayError nếu chưa cấu hình)
        # nguồn VÍ của các máy (module wallets hoặc đồ giả): report() / pending_acks() / acked(ids) / apply_events(events). None = không báo ví
        self._wallets = wallets
        self._facts = facts                   # () -> (devices, groups)   xem build()
        self._tool = tool_info or (lambda: {})
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._last_sig = None                 # dấu của lời báo gần nhất gateway đã nhận
        self._last_ok = None                  # lúc (đồng hồ) gửi được lần gần nhất
        self._acked_rev = None                # mã băm danh mục mà gateway xác nhận đang giữ
        self._not_before = 0.0                # đang lùi sau lỗi: chưa tới giờ này thì chưa thử lại
        self._last_try = None                 # lúc (đồng hồ) GỌI gateway lần gần nhất, dù được hay lỗi
        self._kicks = 0                       # số lần «báo ngay» — để một lời «báo ngay» tới GIỮA lúc đang gọi gateway không bị lỗi của lần gọi đó nuốt mất
        self._off = ""                        # khác rỗng = tiến trình này không báo (lý do), xem disable()
        self._state = {"configured": None, "ok": None, "at": None, "error": "", "devices": 0, "idle": 0, "scripts": 0, "sent": 0, "wallet_warn": "", "wallet_error": ""}

    # ---------- điều khiển ----------
    def disable(self, reason: str):
        """Tiến trình này KHÔNG báo cho gateway (vd một tiến trình khác của app đang báo) — ghi lý do để giao diện nói rõ."""
        self._off = str(reason or "không báo")
        self._set(configured=True, ok=False, error=self._off)

    def start(self):
        with self._lock:
            if self._off or (self._thread and self._thread.is_alive()):
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="gateway-presence")
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def kick(self):
        """Báo ngay ở nhịp kế tiếp (bỏ qua thời gian đang lùi sau lỗi) — dùng khi người vận hành vừa đổi cấu hình gateway / bấm «Báo ngay»."""
        with self._lock:
            self._not_before = 0.0
            self._last_sig = None
            self._kicks += 1
        self._wake.set()

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    # ---------- một nhịp ----------
    def once(self) -> float:
        """Soát và (nếu cần) gửi một lời báo. Trả số giây nên chờ tới nhịp kế tiếp. Không ném lỗi của gateway ra ngoài."""
        now = self._clock()
        if self._off:
            return self.IDLE_WAIT
        if now < self._not_before:
            return min(self.TICK, self._not_before - now)
        kicks = self._kicks
        try:
            facts = self._facts()
        except Exception as e:
            # Không gom được dữ kiện (tệp máy / nhóm đọc lỗi…): KHÔNG gửi gì — gửi «không có máy / kịch bản nào» thì gateway xoá sạch theo.
            self._set(ok=False, error="Chưa báo được: không đọc được dữ liệu máy / nhóm (%s)" % e)
            self._not_before = now + self.ERROR_WAIT
            return self.TICK
        if facts is None:                               # dữ kiện đang được dựng lại (đang quét board) → bỏ nhịp này, giữ lời báo cũ
            return self.TICK
        devices, groups = facts
        body, rows = build(devices, groups, self._tool())
        acks = []
        read_error = ""
        if self._wallets is not None:
            # ví do tool quản lý: bản sao ví (ảnh chụp toàn bộ, không có mật khẩu) + các sự kiện tiền đã áp → nằm trong dấu: số dư đổi /
            # vừa áp sự kiện thì báo ngay ở nhịp tới
            try:
                body["wallets"] = self._wallets.report()
                acks = self._wallets.pending_acks()
            except Exception as e:
                body.pop("wallets", None)
                read_error = "không đọc được ví của các máy (%s)" % e
            if acks:
                body["wallet_acks"] = acks
        sig = signature(body)
        if sig == self._last_sig and self._last_ok is not None and now - self._last_ok < self.EVERY:
            return self.TICK
        try:
            gw = self._gateway()
        except GatewayError:
            self._set(configured=False, ok=None, error="")
            self._last_sig = None
            return self.IDLE_WAIT
        if self._last_try is not None and now - self._last_try < self.MIN_GAP:
            return self.MIN_GAP - (now - self._last_try)
        if len(_blob(dict(body, scripts=rows))) > MAX_BODY_BYTES:
            # gateway sẽ từ chối (413) — gửi cũng vô ích, và gửi lại mỗi 30 giây chỉ làm phiền
            self._set(configured=True, ok=False, error="Lời báo quá lớn (quá nhiều máy / kịch bản cho một khoá Tool) — gateway không nhận")
            self._last_sig = None
            self._not_before = now + self.AUTH_WAIT
            return self.TICK
        self._last_try = now
        rev = body["scripts_rev"]
        try:
            r = gw.sync(dict(body, scripts=rows) if self._acked_rev != rev else body)
            if r.get("need_scripts"):                   # gateway giữ bản khác (vd vừa cài lại CSDL) → gửi lại kèm danh mục
                r = gw.sync(dict(body, scripts=rows))
        except GatewayError as e:
            if e.status == 404:
                msg = "Gateway này chưa có API /api/tool/sync (bản cũ) — cập nhật Web-topup-gateway"
            else:
                msg = e.vi()
            self._set(configured=True, ok=False, error=msg)
            self._last_sig = None
            self._acked_rev = None
            if self._kicks == kicks:                    # (có «báo ngay» tới trong lúc đang gọi thì thử lại ngay nhịp sau, không lùi)
                self._not_before = now + (self.AUTH_WAIT if e.status in (401, 403, 404, 413, 422, 429) else self.ERROR_WAIT)
            return self.TICK
        self._acked_rev = r.get("scripts_rev")
        if self._acked_rev != rev:                      # gateway vẫn chưa nhận danh mục → lần sau gửi lại, chưa coi là báo xong
            self._set(configured=True, ok=False, error="Gateway chưa nhận danh mục kịch bản")
            self._last_sig = None
            if self._kicks == kicks:
                self._not_before = now + self.ERROR_WAIT
            return self.TICK
        self._last_sig, self._last_ok = sig, now
        wallet_warn = ""
        if self._wallets is not None and body.get("wallets") and "wallet_events" not in r:
            # gateway bản cũ (hoặc chưa cập nhật CSDL) không biết ví do tool quản lý: không trừ tiền của đơn, không kiểm tiền khi giao đơn
            wallet_warn = ("Gateway chưa hỗ trợ ví do tool quản lý (bản cũ / chưa chạy php bin/setup.php) — máy nhận đơn KHÔNG được kiểm tiền, "
                           "sổ ví không tự trừ tiền của đơn")
        wallet_error = read_error
        if self._wallets is not None:
            try:
                if acks:
                    self._wallets.acked(acks)                    # gateway đã nhận lời «đã áp» → thôi gửi
                events = r.get("wallet_events")
                if isinstance(events, list) and events:
                    self._wallets.apply_events(events)            # tiền của các đơn: áp mỗi id một lần; id vừa áp sẽ được báo ở nhịp sau
            except Exception as e:
                # để riêng (không bị lời «gửi được» xoá): tiền của đơn KHÔNG vào được sổ — người vận hành phải thấy
                wallet_error = "lỗi khi áp tiền của đơn vào ví (%s)" % e
        with self._lock:
            self._state.update(configured=True, ok=True, error="", wallet_warn=wallet_warn, wallet_error=wallet_error, at=time.time(), devices=len(body["devices"]),
                               idle=sum(1 for d in body["devices"] if d["status"] == IDLE), scripts=len(rows),
                               sent=self._state["sent"] + 1)
        return self.TICK

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def _loop(self):
        while not self._stop.is_set():
            wait = self.TICK
            try:
                wait = self.once()
            except Exception as e:                      # lỗi bất ngờ khi gom dữ kiện không được làm luồng chết im lặng
                self._set(ok=False, error="lỗi khi báo gateway: %s" % e)
                wait = self.ERROR_WAIT
            self._wake.wait(max(0.2, wait))
            self._wake.clear()
