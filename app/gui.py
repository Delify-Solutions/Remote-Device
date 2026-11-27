#!/usr/bin/env python3
"""
gui.py — App quản lý iPhone farm (desktop, cross-platform qua pywebview).

Chạy:  python app/gui.py       -> mở cửa sổ app (không cần trình duyệt)

Cấu trúc: Manager giữ phiên điều khiển từng board; Api là cầu nối cho giao diện
(web/index.html) gọi xuống Python; webview hiển thị giao diện trong cửa sổ native.
"""
from __future__ import annotations
import os, sys, base64, threading, traceback, json, pathlib, re, time
sys.path.insert(0, os.path.dirname(__file__))

import cv2
import webview

import store, engine, fleet, esp, ios, iosdev, sysinfo, prober, apimode, control, boardhealth, presence, history, notify
from nav import Nav
from hands import Hands
from eyes import Eyes
from runner import Runner
from gateway import Gateway, GatewayError

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class Manager:
    """Giữ phiên Nav cho từng board (mở lười, giữ cổng serial)."""
    def __init__(self):
        self.board_map = {}     # tên board -> cổng serial
        self.ble_map = {}       # tên board -> True/False/None (đã nối Bluetooth iPhone?)
        self.sessions = {}      # tên board -> Nav
        self.lock = threading.Lock()
        self.scan_idle = threading.Event()      # set = không có lượt dò board nào đang mở cổng serial
        self.scan_idle.set()

    def close_all(self):
        """Đóng hết phiên để trả cổng serial (cho dò/nạp ESP)."""
        self.close_idle(())

    def close_idle(self, keep):
        """Đóng các phiên KHÔNG thuộc `keep` (tên máy đang chạy — cổng của chúng không được đụng)."""
        for name in [n for n in self.sessions if n not in keep]:
            try: self.sessions[name].close()
            except Exception: pass
            self.sessions.pop(name, None)

    def rescan(self):
        self.close_all()
        self.board_map = fleet.discover()
        # seed store nếu trống
        if not store.get_devices():
            for d in fleet.DEVICES:
                store.upsert_device(d["name"], d["udid"], d.get("label"))
        return self.board_map

    def _udid(self, name):
        for d in store.get_devices():
            if d["name"] == name:
                return d.get("udid")
        return None

    def hands(self, name):
        """Tay (cổng serial) của board `name` cho thao tác lẻ KHÔNG cần iPhone (khởi động lại, huỷ kết nối BT): dùng lại phiên đang mở nếu có;
        chưa có thì mở riêng một Hands (không đòi gán UDID, không chờ BLE). Trả (hands, hàm_đóng)."""
        with self.lock:
            nav = self.sessions.get(name)
            if nav is not None:
                return nav.h, (lambda: None)
        self.scan_idle.wait(20)
        with self.lock:
            nav = self.sessions.get(name)
            if nav is not None:
                return nav.h, (lambda: None)
            port = self.board_map.get(name)
        if not port:
            raise RuntimeError(f"Không thấy board '{name}' (bấm Quét board)")
        h = Hands(port)
        return h, (lambda: h.ser.close())

    def session(self, name):
        with self.lock:
            if name in self.sessions:
                return self.sessions[name]
        # phiên mới phải mở cổng serial → chờ lượt dò board (cũng đang mở cổng) xong đã,
        # hai bên cùng mở một cổng sẽ đọc lẫn phản hồi của nhau
        self.scan_idle.wait(20)
        with self.lock:
            if name in self.sessions:
                return self.sessions[name]
            port = self.board_map.get(name)
            if not port:
                raise RuntimeError(f"Không thấy board '{name}' (bấm Quét board)")
            udid = self._udid(name)
            if not udid:
                raise RuntimeError(f"Board '{name}' chưa gán iPhone (UDID)")
            nav = Nav(port, udid)
            nav.observer = HISTORY.tracker(name)        # mọi bước chạy trên máy này (kịch bản, đơn, chạy thử, AI) đều được ghi lại
            self.sessions[name] = nav
            return nav


# «máy nào đang chạy bước nào» + lịch sử theo máy / theo đơn (app/data/history/ — không có trong git, không chứa thông tin đăng nhập của khách)
HISTORY = history.History(lambda: os.path.join(store.DATA_DIR, "history"))
MGR = Manager()

# Cửa sổ pywebview (đặt trong main) để đẩy cập nhật streaming về giao diện.
WINDOW = None
WEBDEV = None           # chế độ web (`--web`): máy chủ web thay cửa sổ pywebview (xem webdev.py)
def _push(js):
    """Gọi 1 hàm JS trên giao diện (an toàn khi gọi từ thread nền)."""
    try:
        if WEBDEV is not None:
            WEBDEV.push(js)
        elif WINDOW is not None:
            WINDOW.evaluate_js(js)
    except Exception:
        pass


def _customer_machines():
    """Tên các máy đang làm đơn của KHÁCH (chế độ API đang chạy) hoặc vừa dừng giữa đơn và đang GIỮ nguyên màn hình chờ người kiểm tra —
    màn hình các máy này có thể đang hiện tài khoản, mã OTP của khách."""
    return [c["name"] for c in RUNNER.customers()]


def _customer_conflict(name):
    """`name` có phải (hoặc đang trỏ vào) một máy của khách không → tên máy của khách đó, hoặc None. So theo MÁY THẬT ghi lúc bắt đầu chạy:
    cùng tên, cùng iPhone (UDID) hoặc cùng board (cổng) — nên gán lại UDID / đổi tên / xoá máy trong bảng cũng không lách được."""
    try:
        udid = MGR._udid(name)
    except Exception:
        udid = None
    hit = RUNNER.conflict(name, udid, MGR.board_map.get(name))
    if hit:
        return hit
    nav = MGR.sessions.get(name)                     # phiên đã mở sẵn cho tên này có thể đang trỏ vào iPhone / board KHÁC với bảng gán hiện tại
    if nav is not None:
        return RUNNER.conflict(None, getattr(getattr(nav, "e", None), "udid", None), getattr(getattr(nav, "h", None), "port", None))
    return None


def _web_privacy(name):
    """Chế độ WEB (`--web`): trang có thể đang được AI điều khiển qua trình duyệt → áp CÙNG luật riêng tư với cầu nối AI (control.AppHost.eyes):
    không chụp màn hình máy đang làm đơn của khách / đang giữ chờ kiểm tra. Trả câu từ chối, hoặc None nếu chụp được.
    Cửa sổ app thật (không --web) không bị ảnh hưởng."""
    if WEBDEV is None:
        return None
    hit = _customer_conflict(name)
    if hit:
        return ("Máy «%s» đang nhận đơn của khách (hoặc đang dừng chờ kiểm tra sau đơn của khách)%s — chế độ web không chụp màn hình lúc này "
                "(tránh lộ thông tin của khách). Xem trực tiếp trên máy, hoặc mở app dạng cửa sổ."
                % (name, "" if hit == name else " — cùng iPhone / board với máy «%s»" % hit))
    return None


def _web_hold(name):
    """Chế độ WEB: giao diện web KHÔNG được bấm / gõ / thử bước lên máy của khách (đang làm đơn hoặc đang dừng chờ kiểm tra) — như AI / dòng
    lệnh: màn hình phải giữ nguyên để đối soát, và «chờ chữ / kiểm chữ» sẽ thành cách dò nội dung màn hình. Trả câu từ chối hoặc None."""
    if WEBDEV is None:
        return None
    hit = _customer_conflict(name)
    if hit:
        why = RUNNER.hold_reason(hit)
        return ("Máy «%s» %s%s — chế độ web không điều khiển máy này cho tới khi người vận hành xử lý xong (ở app dạng cửa sổ)."
                % (name, ("đang DỪNG CHỜ NGƯỜI KIỂM TRA (%s)" % why) if why else "đang làm đơn của khách",
                   "" if hit == name else " (cùng iPhone / board với máy «%s»)" % hit))
    return None


# Chế độ WEB, khi đang có máy của khách: CHỈ các lệnh dưới đây được gọi (xem / chạy-dừng máy khác / sửa nhóm). Mọi lệnh khác — đổi bảng gán
# iPhone, xoá máy, nạp / xoá board, dò máy, khởi động lại, xoá nhóm, đổi gateway / cầu nối AI, cài đặt… — bị từ chối cho tới khi xử lý xong,
# vì chúng có thể làm mất dấu máy của khách hoặc gỡ trạng thái giữ. Lệnh mới thêm vào Api mặc định KHÔNG nằm trong danh sách này.
WEB_SAFE_WITH_CUSTOMERS = frozenset((
    "sys_overview", "reload_ui", "list_devices", "ios_list", "rescan", "esp_scan",
    "screenshot", "ble_status", "run_step", "test_flow", "test_api_steps",            # tự kiểm theo máy thật (_web_privacy / _web_hold)
    "get_flows", "groups_list", "group_save", "group_add_device", "group_remove_device",
    "group_run", "group_stop", "machine_run", "machine_pause", "machine_resume", "machine_stop", "machine_ack", "stop_all",
    "run_status", "run_log", "history_live", "history_machine", "history_orders", "history_order", "gateway_get", "gateway_test", "gateway_pools", "gateway_pool", "gateway_sync", "ai_info",
    "telegram_get",                                                                    # chỉ đọc, không có mã bot
))


WEB_NO_ORDERS = ("Chế độ web là bản dev (trang có thể đang do AI điều khiển) nên KHÔNG chạy đơn của khách. Nhận đơn từ gateway chỉ chạy ở app dạng "
                 "cửa sổ: tắt bản web rồi chạy `python app/gui.py` (không kèm --web).")


def _web_gate(method):
    """Cổng chặn của chế độ web (webdev gọi trước MỌI lệnh): None = cho qua, hoặc câu từ chối."""
    if method in WEB_SAFE_WITH_CUSTOMERS:
        return None
    busy = _customer_machines()
    if busy:
        return ("Đang có máy làm đơn của khách / dừng chờ kiểm tra (%s) — chế độ web tạm khoá lệnh «%s» cho tới khi xử lý xong các máy đó "
                "(đối soát ở app dạng cửa sổ)." % (", ".join(busy), method))
    return None


def _origin(url):
    """«giao thức://máy chủ:cổng» của một địa chỉ (chữ thường) — để biết hai địa chỉ gateway có cùng MỘT máy chủ không."""
    import urllib.parse
    try:
        u = urllib.parse.urlsplit((url or "").strip())
        return ("%s://%s" % (u.scheme, u.netloc)).lower()
    except ValueError:
        return ""


def _gateway():
    """Khách gọi Topup Gateway theo cấu hình đã lưu (ném GatewayError nếu chưa cấu hình)."""
    s = store.get_settings()
    return Gateway(s.get("gateway_url") or "", s.get("gateway_key") or "")


# chạy kịch bản nhóm / nhận đơn từ gateway; mỗi máy một worker, dừng độc lập
RUNNER = Runner(MGR.session, gateway_factory=_gateway, journal=apimode.Journal(store.DATA_DIR),
                on_log=lambda entry: _push("window.__runLog && window.__runLog(%s)" % json.dumps(entry)))
RUNNER.history = HISTORY
# Thông báo Telegram cho admin (máy dừng chờ admin, đơn cần đối soát, bước lỗi, board / Bluetooth mất kết nối) — xem notify.py
TELEGRAM = notify.Telegram(store.get_settings)
RUNNER.alert = TELEGRAM.notify
def _ident_now(name):
    """iPhone + cổng board mà tên `name` sẽ DÙNG THẬT nếu chạy ngay bây giờ: phiên đã mở sẵn (nếu có), không thì theo bảng gán."""
    nav = MGR.sessions.get(name)
    udid = getattr(getattr(nav, "e", None), "udid", None) if nav is not None else None
    port = getattr(getattr(nav, "h", None), "port", None) if nav is not None else None
    return (udid or MGR._udid(name), port or MGR.board_map.get(name))


RUNNER.ident = _ident_now       # máy thật (iPhone + cổng board) ghi lại lúc bắt đầu chạy


# Máy chủ điều khiển cho AI (MCP) + dòng lệnh `farm` — tạo trong main() (cần đối tượng Api).
CONTROL = None

# Sổ «ai đang dùng cổng serial của máy nào»: AI / dòng lệnh, thao tác thử trên giao diện, và bộ chạy đều xin qua đây
# (cùng một khoá) → không bao giờ có hai bên cùng điều khiển một máy.
CLAIMS = control.Claims(running=RUNNER.is_running)


def _ai_active():
    """Các máy đang được AI / dòng lệnh điều khiển ngay lúc này (cổng serial của chúng đang bận)."""
    return CLAIMS.names("ai")


def _in_use():
    """Mọi máy mà cổng serial đang có người dùng: đang chạy kịch bản/đơn, hoặc đang được điều khiển tay (AI / giao diện)."""
    return set(RUNNER.running_names()) | set(CLAIMS.names())


def _busy(name=None):
    """Lý do KHÔNG được đụng cổng serial lúc này (None = được). name=None: xét mọi máy."""
    running = RUNNER.running_names()
    held = CLAIMS.names()
    if name is None and running:
        return "Đang có máy chạy (%s) — dừng các máy đó trước." % ", ".join(running)
    if name is None and held:
        return "Đang có máy được điều khiển tay — AI / dòng lệnh / thao tác thử (%s) — chờ lệnh đó xong." % ", ".join(held)
    if name is not None and name in running:
        return f"Máy «{name}» đang chạy — dừng máy đó trước."
    if name is not None and name in held:
        return f"Máy «{name}» đang được điều khiển tay (AI / dòng lệnh / thao tác thử) — chờ lệnh đó xong."
    return None


_IOS_SEEN = {"at": None, "udids": None}


def _ios_udids(max_age=20.0):
    """UDID (dạng chuẩn) của các iPhone đang cắm USB (iPhone chỉ thấy qua Wi-Fi không tính: không chụp màn hình ổn định được).
    Hỏi usbmux phải mở một tiến trình con nên kết quả được NHỚ TẠM `max_age` giây (đồng hồ đơn điệu — chỉnh giờ máy không làm kẹt)."""
    now = time.monotonic()
    if _IOS_SEEN["udids"] is None or _IOS_SEEN["at"] is None or now - _IOS_SEEN["at"] > max_age:
        try:
            udids = {Runner.canon_udid(d.get("udid")) for d in ios.list_connected()
                     if d.get("udid") and str(d.get("connection") or "USB").upper() != "NETWORK"}
        except Exception:
            udids = set()
        _IOS_SEEN.update(at=now, udids=udids)
    return _IOS_SEEN["udids"]


# Cổng / máy đang BẢO TRÌ (nạp / xoá firmware, dò máy): cổng serial bận nhưng không qua sổ CLAIMS → luồng tự báo phải biết để không báo «rảnh».
MAINT = set()


class _Maint:
    """with _Maint(port) / _Maint("*"): đánh dấu cổng (hoặc MỌI máy) đang bảo trì trong lúc làm."""
    def __init__(self, what):
        self.what = what

    def __enter__(self):
        MAINT.add(self.what)

    def __exit__(self, *exc):
        MAINT.discard(self.what)
        return False


def _note_ble(name, status):
    """Ghi trạng thái Bluetooth vừa ĐỌC ĐƯỢC từ board (chuỗi trạng thái của firmware) vào MGR.ble_map — để luồng tự báo không dựa mãi
    vào kết quả của lượt quét board trước đó (vd vừa bấm «Huỷ kết nối BT» thì máy không còn được báo là rảnh)."""
    text = str(status or "")
    if "ble=connected" in text:
        MGR.ble_map[name] = True
    elif "ble=" in text:
        MGR.ble_map[name] = False


def _owes_order(name):
    """Máy còn ĐƠN DỞ trong sổ (apimode.Journal — bền qua lần khởi động lại): đã nhận đơn mà chưa báo xong kết quả. Trạng thái «dừng chờ
    kiểm tra» chỉ nằm trong bộ nhớ, nên sau khi app khởi động lại đây là dấu vết duy nhất cho biết máy chưa được phép coi là rảnh."""
    j = RUNNER.journal
    if j is None:
        return False
    try:
        e = j.peek(name) if hasattr(j, "peek") else j.get(name)      # peek: đọc CHẶT (sổ hỏng thì ném lỗi, không trả «không có gì»)
    except Exception:
        return True                                  # không đọc được sổ → không dám nói máy rảnh
    return bool(e and e.get("job") and not e.get("delivered"))


def _presence_facts():
    """Dữ kiện cho luồng TỰ BÁO GATEWAY (presence.build): mọi máy + mọi nhóm. Không đụng cổng serial, không chụp màn hình.
    Trả None = «lúc này chưa có dữ kiện ổn định, bỏ nhịp này» (đang quét board: bảng board / Bluetooth đang được dựng lại).
    Tệp máy / nhóm không đọc được thì NÉM LỖI (không coi như «không còn máy / kịch bản nào» — gateway sẽ xoá sạch theo)."""
    if not MGR.scan_idle.is_set():
        return None
    devices = store.get_devices_strict()
    groups = store.get_groups_strict()
    run = RUNNER.status()
    claimed = set(CLAIMS.names())
    ios_now = _ios_udids()
    out, seen = [], set()

    def fact(name, label, udid):
        w = run.get(name) or {}
        port = MGR.board_map.get(name)
        running, mode = bool(w.get("running")), w.get("mode")
        hold = bool(RUNNER.hold_reason(name)) or (not running and _owes_order(name))
        # Tên này có thể đang trỏ vào CÙNG iPhone / board với một máy của khách dưới tên khác (bộ chạy cũng xét theo máy thật, xem
        # Runner.conflict): máy thật đó đang giữ / đang làm đơn thì tên này cũng không rảnh.
        other = _customer_conflict(name)
        if other and other != name:
            if RUNNER.hold_reason(other):
                hold = True
            else:
                running, mode = True, "api"
        return {"name": name, "label": label, "udid": bool(udid),
                # board đã quét thấy VÀ cổng còn đó (rút dây thì tệp cổng biến mất, không cần chờ lượt quét sau)
                "board_online": bool(port) and (not str(port).startswith("/") or os.path.exists(port)),
                "ios_connected": bool(udid) and Runner.canon_udid(udid) in ios_now,
                "ble": MGR.ble_map.get(name),
                "running": running, "run_mode": mode,
                "run_group_id": w.get("group_id"), "run_script_id": w.get("script_id"),
                "run_group": w.get("group_name"), "run_script": w.get("script_name"), "iter": w.get("iter"),
                "parked": RUNNER.is_parked(name), "hold": hold,
                "claimed": name in claimed or "*" in MAINT or (bool(port) and port in MAINT)}

    for d in devices:
        seen.add(d["name"])
        out.append(fact(d["name"], d.get("label") or "", d.get("udid")))
    for name in list(MGR.board_map):
        if name not in seen:
            out.append(fact(name, "", None))
    return out, groups


def _presence_tool():
    """Tool này là gì và có đang nhận đơn của khách không (bản web dev thì KHÔNG — gateway phải biết để không trông vào máy của nó)."""
    return {"app": "iphone-farm", "mode": "web" if WEBDEV is not None else "desktop", "accepting": bool(RUNNER.allow_api)}


# Luồng tự báo cho gateway: máy nào rảnh ở kịch bản nào + danh mục kịch bản (chạy trong main()).
PRESENCE = presence.Reporter(_gateway, _presence_facts, _presence_tool)
_PRESENCE_LOCK = None           # tệp khoá đang giữ: mỗi bản cài chỉ MỘT tiến trình được báo cho gateway


LINK_EVERY = 20.0               # giây: nhịp hỏi board của các máy đang mở (rảnh) xem board / Bluetooth còn không
LINK_CONFIRM = 2                # phải thấy trạng thái MỚI chừng này nhịp liền mới tin (board vừa khởi động lại / BLE đang nối lại thì chập chờn)
_LINK = {}                      # tên máy -> {"base": (board trả lời?, Bluetooth đã nối?), "cand": trạng thái mới đang chờ xác nhận, "n": số nhịp, "quiet": đến lúc}
_LINK_LOCK = threading.Lock()


def _link_quiet(names=None, secs=120.0):
    """Người vận hành VỪA tự làm board / Bluetooth đổi trạng thái (khởi động lại board, huỷ kết nối BT, nạp firmware, gán máy, quét lại):
    trong `secs` giây tới không báo «mất kết nối» cho các máy đó (None = mọi máy), và quên trạng thái cũ để học lại từ đầu."""
    until = time.time() + secs
    with _LINK_LOCK:
        for n in (list(_LINK) if names is None else names):
            _LINK[n] = {"base": None, "cand": None, "n": 0, "quiet": until}
        if names is None:
            _LINK["*"] = {"quiet": until}


def _link_probe(name):
    """Hỏi board của máy `name` NGAY (chỉ khi máy đã có phiên mở trong tiến trình này, đang rảnh, không ai đang dùng): trả (board trả lời?,
    Bluetooth đã nối?) hoặc None = lúc này không hỏi được (không đụng vào máy đang chạy / đang được điều khiển / đang nạp, quét)."""
    nav = MGR.sessions.get(name)
    if nav is None or RUNNER.is_running(name) or not MGR.scan_idle.is_set() or "*" in MAINT:
        return None
    if getattr(getattr(nav, "h", None), "port", None) in MAINT:
        return None
    with _Using(name, board_only=True) as why:
        if why:
            return None
        try:
            st = nav.h.status()
        except Exception:
            return (False, None)                     # cổng serial hỏng / đã rút
        if not st:
            return (False, None)                     # board không trả lời
        _note_ble(name, st)
        return (True, "ble=connected" in st)


def _link_watch(probe=None, alert=None, names=None, now=None):
    """Một nhịp: hỏi board của các máy đang mở, trạng thái XẤU ĐI (board không trả lời / Bluetooth rớt) giữ đủ LINK_CONFIRM nhịp thì báo một
    lần. Không báo trạng thái lúc mới mở, không báo khi người vận hành vừa tự làm đổi (xem _link_quiet). Trả bảng trạng thái (để test)."""
    probe = probe or _link_probe
    alert = alert or RUNNER._alert
    now = time.time() if now is None else now
    if names is None:
        names = list(MGR.sessions)
        with _LINK_LOCK:                        # phiên đã đóng (quét lại, nạp firmware…): quên trạng thái cũ, mở lại thì học lại từ đầu
            for n in [n for n in _LINK if n != "*" and n not in names]:
                del _LINK[n]
    for n in names:
        obs = probe(n)
        if obs is None:
            continue
        with _LINK_LOCK:
            rec = _LINK.setdefault(n, {"base": None, "cand": None, "n": 0, "quiet": 0.0})
            quiet = now < max(rec.get("quiet") or 0.0, (_LINK.get("*") or {}).get("quiet") or 0.0)
            if rec["base"] is None or obs == rec["base"]:
                rec.update(base=obs, cand=None, n=0)
                continue
            if obs == rec["cand"]:
                rec["n"] += 1
            else:
                rec["cand"], rec["n"] = obs, 1
            if rec["n"] < LINK_CONFIRM:
                continue
            old = rec["base"]
            rec.update(base=obs, cand=None, n=0)
        if quiet:
            continue
        if old[0] and not obs[0]:
            alert(n, "link", "board ESP32 của máy không còn trả lời (rút cáp USB / mất nguồn / board treo?)")
        elif obs[0] and old[1] is True and obs[1] is False:
            alert(n, "link", "Bluetooth giữa board ESP32 và iPhone bị rớt")
    return _LINK


def _start_link_watch():
    def loop():
        while True:
            time.sleep(LINK_EVERY)
            try:
                _link_watch()
            except Exception:
                pass
    threading.Thread(target=loop, name="link-watch", daemon=True).start()


def _start_presence():
    """Chạy luồng tự báo — nhưng chỉ ở MỘT tiến trình của bản cài này. App cửa sổ và bản web chạy cùng lúc dùng chung khoá Tool; hai bên
    cùng báo thì ghi đè lời báo của nhau (bên không giữ máy sẽ báo máy của bên kia là «chưa sẵn sàng» hoặc tệ hơn là «rảnh»).
    Tiến trình không lấy được khoá thì KHÔNG báo và nói rõ lý do ở dòng trạng thái."""
    global _PRESENCE_LOCK
    try:
        import fcntl

        def grab(f):
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:                 # Windows: khoá byte đầu của tệp bằng msvcrt (không chờ; tiến trình tắt thì hệ điều hành tự nhả)
        import msvcrt

        def grab(f):
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    if _PRESENCE_LOCK is None:
        try:
            os.makedirs(store.DATA_DIR, exist_ok=True)
            f = open(os.path.join(store.DATA_DIR, "presence.lock"), "a+")
            try:
                grab(f)
            except OSError:
                f.close()
                PRESENCE.disable("Một cửa sổ / tiến trình khác của app đang báo cho gateway — tiến trình này không báo (tránh ghi đè lẫn nhau).")
                return False
            _PRESENCE_LOCK = f            # giữ tệp mở suốt đời tiến trình; tiến trình tắt thì hệ điều hành tự nhả khoá
        except OSError:
            pass                          # không tạo được tệp khoá (đĩa chỉ đọc…): vẫn báo
    PRESENCE.start()
    return True


class _Using:
    """Giữ máy cho MỘT thao tác thử trên giao diện (chạy thử bước / kịch bản). Dùng:  with _Using(name) as why: …
    `why` khác None = không lấy được máy (đang chạy, hoặc AI / dòng lệnh đang điều khiển) → không được làm gì."""
    def __init__(self, name, board_only=False):
        # board_only: thao tác chỉ đụng tới BOARD (hỏi / huỷ Bluetooth, khởi động lại board), không bấm gõ lên iPhone → vẫn làm được khi
        # máy đang «dừng để xử lý tay» (đó chính là lúc người vận hành hay cần tới các thao tác này).
        self.name, self.why, self.board_only = name, None, board_only

    def __enter__(self):
        parked = None
        if RUNNER.is_parked(self.name) and not self.board_only:
            parked = "Máy «%s» đang DỪNG để xử lý tay — bấm «Tiếp tục» trên máy đó rồi mới thử." % self.name
        self.why = parked or _web_hold(self.name) or CLAIMS.acquire(self.name, "ui")
        return self.why

    def __exit__(self, *exc):
        if self.why is None:
            CLAIMS.release(self.name, "ui")
        return False


class Api:
    """Các hàm giao diện web gọi: window.pywebview.api.<tên>()"""

    # ---- tổng quan / môi trường ----
    def sys_overview(self):
        try:
            return {"ok": True, **sysinfo.overview()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sys_install_pip(self, names=None):
        try:
            return sysinfo.pip_install(names or "all")
        except Exception as e:
            return {"ok": False, "log": str(e)}

    def sys_install_tool(self, name):
        try:
            return sysinfo.tool_install(name)
        except Exception as e:
            return {"ok": False, "log": str(e)}

    def reload_ui(self):
        """Tải lại giao diện (như F5) — phải do pywebview điều hướng để GẮN LẠI
        window.pywebview.api; location.reload() của JS làm MẤT cầu nối API trên macOS."""
        def _do():
            try:
                url = WINDOW.get_current_url() or pathlib.Path(os.path.join(WEB_DIR, "index.html")).as_uri()
                WINDOW.load_url(url)
            except Exception:
                pass
        threading.Timer(0.2, _do).start()
        return {"ok": True}

    def restart_app(self):
        """Khởi động lại toàn bộ app (đóng cửa sổ, chạy lại tiến trình)."""
        if WEBDEV is not None and _web_gate("restart_app"):
            # Trạng thái «đang làm đơn / đang giữ chờ kiểm tra» chỉ nằm trong bộ nhớ: khởi động lại là mất, và luật riêng tư không còn gì để dựa vào.
            return {"ok": False, "error": _web_gate("restart_app")}
        script = os.path.abspath(sys.argv[0])
        env = dict(os.environ)
        if WEBDEV is not None:                          # giữ phiên web qua lần khởi động lại — CHỈ đưa cho tiến trình mới, không để trong môi trường chung
            import webdev
            env[webdev.SESSION_ENV] = WEBDEV.session
        def _do():
            try:
                os.execve(sys.executable, [sys.executable, script] + sys.argv[1:], env)
            except Exception:
                os._exit(1)
        threading.Timer(0.4, _do).start()
        return {"ok": True}

    # ---- thiết bị ----
    def rescan(self):
        why = _busy()
        if why:
            return {"ok": False, "error": why}
        try:
            MGR.rescan()
            return {"ok": True, "boards": MGR.board_map}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_devices(self):
        # KHÔNG đụng serial ở đây (việc dò board do esp_scan làm, song song + streaming).
        # Hàm này chỉ ghép: store + board_map (đã có) + iOS (usbmux, không phải serial).
        try:
            ios_by_udid = {d["udid"]: d for d in ios.list_connected()}
        except Exception:
            ios_by_udid = {}
        grp_by_dev = {}                                      # tên máy → danh sách nhóm (một máy có thể ở nhiều nhóm)
        for g in store.get_groups():
            for dn in g.get("devices", []):
                grp_by_dev.setdefault(dn, []).append({"id": g["id"], "name": g.get("name", g["id"])})
        run_by_dev = RUNNER.status()
        def enrich(entry):
            info = ios_by_udid.get(entry.get("udid"))
            entry["ios_connected"] = info is not None
            entry["ios"] = info["ios"] if info else None
            entry["model"] = info["model"] if info else None
            entry["device_name"] = info["name"] if info else None
            gs = grp_by_dev.get(entry.get("name")) or []
            entry["groups"] = gs
            entry["group_id"] = gs[0]["id"] if gs else None                       # nhóm đầu tiên (chỗ cũ chỉ cần biết có nhóm hay không)
            entry["group_name"] = ", ".join(x["name"] for x in gs) if gs else None
            entry["running"] = RUNNER.is_running(entry.get("name"))
            run = run_by_dev.get(entry.get("name")) if entry["running"] else None
            entry["run_group"] = (run or {}).get("group_name")                      # «đang chạy {nhóm} · {kịch bản}»
            entry["run_script"] = (run or {}).get("script_name")
            entry["paused"] = bool((run or {}).get("paused"))
            entry["pause_requested"] = bool((run or {}).get("pause_requested"))
            entry["run_mode"] = (run or {}).get("mode")
            entry["stopping"] = bool((run or {}).get("stopping"))
            entry["hold"] = RUNNER.hold_reason(entry.get("name"))                 # đang dừng chờ người kiểm tra (đơn của khách)
            entry["parked"] = RUNNER.is_parked(entry.get("name"))                 # người vận hành bấm «Dừng máy» để xử lý tay
            return entry
        out = []
        for d in store.get_devices():
            out.append(enrich({
                "name": d["name"], "udid": d.get("udid"),
                "label": d.get("label", d["name"]),
                "board_online": d["name"] in MGR.board_map,
                "port": MGR.board_map.get(d["name"]),
                "ble": MGR.ble_map.get(d["name"]),
                "configured": True,     # có trong store → cho phép Xoá
            }))
        for name, port in MGR.board_map.items():
            if not any(o["name"] == name for o in out):
                out.append(enrich({"name": name, "udid": None, "label": name,
                                   "board_online": True, "port": port,
                                   "ble": MGR.ble_map.get(name), "configured": False}))
        return out

    def set_udid(self, name, udid, label=None):
        why = _busy(name)
        if why:
            return {"ok": False, "error": why}
        hit = RUNNER.conflict(name, udid, MGR.board_map.get(name))
        if hit:         # tên này đang là máy của khách, hoặc iPhone định gán chính là máy của khách (đang làm đơn / đang dừng chờ kiểm tra)
            return {"ok": False, "error": "Máy «%s» đang làm đơn của khách / dừng chờ kiểm tra — chưa đổi bảng gán iPhone liên quan tới máy đó được." % hit}
        store.upsert_device(name, udid, label)
        with MGR.lock:
            nav = MGR.sessions.pop(name, None)      # phiên cũ đang trỏ vào iPhone CŨ → bỏ, lần sau mở theo bảng gán mới
        if nav:
            try: nav.close()
            except Exception: pass
        return {"ok": True}

    def delete_device(self, name):
        why = _busy(name)
        if why:
            return {"ok": False, "error": why}
        hit = _customer_conflict(name)
        if hit:
            return {"ok": False, "error": "Máy «%s» đang làm đơn của khách / dừng chờ kiểm tra — xử lý xong («Đã kiểm tra xong») rồi mới xoá." % hit}
        store.delete_device(name)
        RUNNER.forget_parked(name)                  # máy không còn → bỏ luôn trạng thái «đang dừng» (không để tên ma trong danh sách)
        with MGR.lock:
            nav = MGR.sessions.pop(name, None)      # đóng phiên cũ nếu có (trả cổng serial)
        if nav:
            try: nav.close()
            except Exception: pass
        return {"ok": True}

    def probe_match(self, board_name):
        """DÒ MÁY: xác định board này đang điều khiển iPhone nào (rung chuột + so màn),
        rồi tự (re)gán board -> UDID. Xử lý được ca thay/đổi máy."""
        why = _busy()       # dò máy rung chuột + đóng mọi phiên → không làm khi có máy đang chạy
        if why:
            return {"ok": False, "error": why}
        if RUNNER.is_parked(board_name):
            return {"ok": False, "error": "Máy «%s» đang DỪNG để xử lý tay — bấm «Tiếp tục» trên máy đó rồi mới dò (dò sẽ rung chuột trên máy)." % board_name}
        if WEBDEV is not None and _web_gate("probe_match"):     # dò = rung chuột + chụp MỌI iPhone, kể cả máy đang giữ màn hình của khách
            return {"ok": False, "error": _web_gate("probe_match")}
        try:
            with MGR.lock:
                MGR.close_all()                     # nhả cổng serial cho Hands dùng
                port = MGR.board_map.get(board_name)
            if not port:
                return {"ok": False, "error": "Không thấy board (bấm Quét lại board)."}
            try:
                cands = [c for c in ios.list_connected() if c.get("udid")]
            except Exception:
                cands = []
            if not cands:
                return {"ok": False, "error": "Không có iPhone nào đang cắm USB để dò."}

            with _Maint("*"):                       # dò = rung chuột trên board + chụp mọi iPhone: trong lúc đó không máy nào là «rảnh»
                best, ranked, note = prober.identify(port, cands)
            ranked_out = [{"name": c.get("name"), "udid": c.get("udid"), "score": s} for c, s in ranked]
            if not best:
                return {"ok": False, "error": note or "Không xác định được máy.", "ranked": ranked_out}

            udid = best["udid"]
            # giữ nhãn người dùng đặt riêng; nếu chưa đặt thì dùng tên máy dò được
            cur = next((d for d in store.get_devices() if d["name"] == board_name), None)
            keep = cur.get("label") if cur else None
            label = keep if keep not in (None, "", board_name) else (best.get("name") or board_name)
            store.upsert_device(board_name, udid, label)

            shot = None
            try:
                img = Eyes(udid).screenshot()
                ok, buf = cv2.imencode(".png", img)
                if ok:
                    shot = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()
            except Exception:
                pass

            MGR.board_map = {}                      # buộc quét lại để mapping mới có hiệu lực
            _link_quiet()                           # gán lại máy: mọi phiên / board sắp đổi → không báo «mất kết nối» nhầm
            return {"ok": True, "board": board_name, "udid": udid, "label": label,
                    "name": best.get("name"), "model": best.get("model"), "ios": best.get("ios"),
                    "shot": shot, "ranked": ranked_out}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- kiểm tra & chuẩn bị iPhone cho việc chụp màn hình ----
    def ios_check(self, udid):
        try:
            return {"ok": True, **iosdev.check(udid)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ios_pair(self, udid):
        try: return iosdev.pair(udid)
        except Exception as e: return {"ok": False, "log": str(e)}

    def ios_enable_devmode(self, udid):
        try: return iosdev.enable_dev_mode(udid)
        except Exception as e: return {"ok": False, "log": str(e)}

    def ios_reveal_devmode(self, udid):
        try: return iosdev.reveal_dev_mode(udid)
        except Exception as e: return {"ok": False, "log": str(e)}

    def ios_mount(self, udid):
        try: return iosdev.mount_ddi(udid)
        except Exception as e: return {"ok": False, "log": str(e)}

    # ---- quản lý ESP32 ----
    def esp_scan(self):
        """Quét SONG SONG tất cả cổng USB-UART. Trả ngay danh sách cổng (flashed=None
        = đang dò), rồi đẩy kết quả từng board về UI khi xong — cho cả tab ESP và Thiết bị.
        Nhiều board cũng chỉ tốn ~thời gian của 1 board, và hiện dần từng cái."""
        # Máy ĐANG CHẠY (đang nạp/đang chạy kịch bản) giữ cổng serial của nó: KHÔNG đóng phiên,
        # KHÔNG dò cổng đó (dò = gửi lệnh chen vào giữa lúc máy đang gõ/bấm).
        # (máy đang được AI / dòng lệnh điều khiển cũng vậy: cổng của nó đang giữa một thao tác)
        with MGR.lock:
            running = _in_use()
            ports = esp.list_boards()
            present = {b["port"] for b in ports}
            busy = {MGR.board_map[n]: n for n in running if MGR.board_map.get(n) in present}   # cổng -> tên máy
            MGR.close_idle(running)
            old_ble = dict(MGR.ble_map)
            old_names = {p: n for n, p in MGR.board_map.items()}      # cổng -> tên đã biết từ lượt quét trước
            MGR.board_map = {n: p for p, n in busy.items()}
            MGR.ble_map = {n: old_ble.get(n) for n in busy.values()}
            MGR.scan_idle.clear()
        initial, todo = [], []
        for b in ports:
            n = busy.get(b["port"])
            if n:
                initial.append(dict(b, flashed=True, name=n, ble=MGR.ble_map.get(n), busy=True))
            else:
                initial.append(dict(b, flashed=None, name=None))
                todo.append(b)

        def worker(b):
            locked = False
            try:
                p = esp.probe(b["port"])
                name, flashed, ble = p.get("name"), bool(p["flashed"]), p.get("ble")
                locked = bool(p.get("busy"))
                health = boardhealth.view(p.get("status"))      # RAM / thời gian chạy / lý do reset… (firmware v2)
            except Exception:
                name, flashed, ble, health = None, False, None, None
            if locked:
                # Cổng đang do một chương trình NGOÀI app giữ (lệnh `farm` / AI tự mở cổng lúc app chưa chạy):
                # không hỏi được tên, nhưng đó vẫn là board cũ → giữ tên đã biết, đừng báo «chưa nạp».
                name, flashed, ble, health = old_names.get(b["port"]), True, old_ble.get(old_names.get(b["port"])), None
            if name:
                with MGR.lock:
                    MGR.board_map[name] = b["port"]
                    MGR.ble_map[name] = ble
            _push("window.__espUpdate(%s)" % json.dumps(dict(b, flashed=flashed, name=name, ble=ble, busy=locked, locked=locked, health=health)))
            _push("window.__devBoard(%s)" % json.dumps({"name": name, "port": b["port"], "ble": ble}))

        threads = [threading.Thread(target=worker, args=(b,), daemon=True) for b in todo]
        for t in threads:
            t.start()

        def waiter():
            try:
                for t in threads:
                    t.join()
            finally:
                MGR.scan_idle.set()         # từ đây phiên mới mới được mở cổng
            for port, n in busy.items():
                _push("window.__devBoard(%s)" % json.dumps({"name": n, "port": port, "ble": MGR.ble_map.get(n)}))
            _push("window.__scanDone(%d)" % len(ports))
        threading.Thread(target=waiter, daemon=True).start()
        return initial

    def _port_guard(self, port):
        """Cổng này có đang do một máy ĐANG CÓ NGƯỜI DÙNG giữ không (đang chạy, hoặc AI / dòng lệnh / thao tác thử
        đang điều khiển) → trả câu báo lỗi, không thì None."""
        held = RUNNER.conflict(None, None, port)
        if held and RUNNER.hold_reason(held):       # nạp / xoá / đổi tên board của máy đang giữ sẽ làm mất dấu trạng thái giữ
            return f"Board này thuộc máy «{held}» đang DỪNG CHỜ NGƯỜI KIỂM TRA — kiểm tra máy, bấm «Đã kiểm tra xong» rồi mới thao tác với board."
        running = set(RUNNER.running_names())
        for n in _in_use():
            if MGR.board_map.get(n) == port:
                return (f"Board này đang chạy (máy «{n}») — dừng máy đó trước." if n in running
                        else f"Board này đang được điều khiển tay (máy «{n}») — chờ lệnh đó xong.")
        return None

    def esp_chip(self, port):
        why = self._port_guard(port)
        if why:
            return {"ok": False, "error": why}
        with MGR.lock:
            MGR.close_idle(_in_use())
            return esp.chip_info(port)

    def esp_flash(self, port, name):
        """Nạp firmware với tên chọn (dùng để nạp mới hoặc đổi tên)."""
        why = self._port_guard(port)
        if why:
            return {"ok": False, "log": why}
        with MGR.lock:
            # tên board đang nạp trên cổng này (để chuyển cấu hình khi đổi tên)
            old_name = next((n for n, p in MGR.board_map.items() if p == port), None)
            MGR.close_idle(_in_use())
            with _Maint(port):
                r = esp.flash(port, name)
        # đổi tên: chuyển gán iPhone + nhãn từ tên cũ -> tên mới, bỏ 'máy cũ tên cũ'
        if r.get("ok") and old_name and old_name != name:
            try:
                store.rename_device(old_name, name)
                store.rename_in_groups(old_name, name)      # máy đổi tên thì vẫn ở đủ các nhóm cũ
                RUNNER.rename_parked(old_name, name)        # …và vẫn «đang dừng để xử lý tay» nếu đang dừng
            except Exception:
                pass
        with MGR.lock:                       # bỏ ánh xạ của riêng board này → lượt quét sau dò lại
            for n in [n for n, p in MGR.board_map.items() if p == port]:
                MGR.board_map.pop(n, None)
                MGR.ble_map.pop(n, None)
        return r

    def esp_erase(self, port):
        why = self._port_guard(port)
        if why:
            return {"ok": False, "log": why}
        with MGR.lock:
            MGR.close_idle(_in_use())
            with _Maint(port):
                r = esp.erase(port)
            for n in [n for n, p in MGR.board_map.items() if p == port]:
                MGR.board_map.pop(n, None)
                MGR.ble_map.pop(n, None)
        return r

    # ---- thiết bị iOS ----
    def ios_list(self):
        return ios.list_connected()

    def screenshot(self, name):
        try:
            why = _web_privacy(name)
            if why:
                return {"ok": False, "error": why}
            udid = MGR._udid(name)              # chỉ CHỤP: đi qua USB, không mở / không đụng cổng serial của board
            if not udid:
                return {"ok": False, "error": f"Board '{name}' chưa gán iPhone (UDID)"}
            img = Eyes(udid).screenshot()
            ok, buf = cv2.imencode(".png", img)
            b64 = base64.b64encode(buf.tobytes()).decode()
            h, w = img.shape[:2]
            return {"ok": True, "img": "data:image/png;base64," + b64, "w": w, "h": h}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ble_status(self, name):
        if RUNNER.is_running(name):     # máy đang chạy: không chen lệnh vào cổng serial của nó
            return {"ok": True, "status": "OK ble=connected (máy đang chạy)"}
        with _Using(name, board_only=True) as why:       # AI / dòng lệnh đang điều khiển máy này → cũng không chen lệnh vào
            if why:
                return {"ok": True, "status": "OK ble=connected (máy đang được điều khiển)"}
            try:
                nav = MGR.session(name)
                st = nav.h.status()
                _note_ble(name, st)
                return {"ok": True, "status": st, "health": boardhealth.view(st)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def _board_op(self, name, fn):
        """Thao tác lẻ trên board của máy `name` (khởi động lại / huỷ kết nối BT): không chen vào máy đang chạy hay đang được điều khiển."""
        if RUNNER.is_running(name):
            return {"ok": False, "error": "Máy đang chạy — dừng máy (tab Nhóm & Kịch bản) rồi mới làm được."}
        with _Using(name, board_only=True) as why:
            if why:
                return {"ok": False, "error": why}
            try:
                hands, close = MGR.hands(name)
            except Exception as e:
                return {"ok": False, "error": str(e)}
            try:
                return fn(hands)
            except Exception as e:
                return {"ok": False, "error": str(e)}
            finally:
                close()

    def board_restart(self, name):
        """KHỞI ĐỘNG LẠI board ESP32 (lệnh `reset`); Bluetooth rớt vài giây rồi iPhone đã ghép tự nối lại."""
        _link_quiet([name], 120)                    # người vận hành tự làm board / Bluetooth rớt: không báo «mất kết nối»
        def run(hands):
            r = boardhealth.restart(hands)
            if not r["ok"]:
                return {"ok": False, "error": "Board không khởi động lại được (đã thử cả reset cứng) — kiểm tra cáp USB / nguồn."}
            back = hands.wait_connected(20)
            st = hands.status()
            _note_ble(name, st)
            health = boardhealth.view(st)
            return {"ok": True, "msg": "Đã khởi động lại board %s (reset %s) — %s." % (name, r["how"], "iPhone đã nối lại Bluetooth" if back else "iPhone chưa nối lại Bluetooth (đợi thêm vài giây rồi bấm «Dò lại»)"),
                    "health": health}
        return self._board_op(name, run)

    def board_disconnect_bt(self, name, hold=30):
        """HUỶ kết nối Bluetooth với iPhone đang nối; board ngừng quảng bá `hold` giây rồi iPhone đã ghép tự nối lại."""
        try:
            secs = max(0, int(hold))
        except (TypeError, ValueError):
            secs = 30
        _link_quiet([name], secs + 90)              # người vận hành tự huỷ Bluetooth: không báo «mất kết nối» cho tới khi iPhone nối lại
        def run(hands):
            r = boardhealth.disconnect_bt(hands, int(hold))
            if not r["ok"]:
                return {"ok": False, "error": r.get("error") or "không huỷ được kết nối"}
            st = hands.status()
            _note_ble(name, st)                      # vừa huỷ kết nối: từ giờ máy không còn được báo là rảnh cho tới khi đọc lại thấy đã nối
            if r.get("none"):
                return {"ok": True, "msg": "Board %s hiện không nối với iPhone nào." % name, "health": boardhealth.view(st)}
            return {"ok": True, "msg": "Đã huỷ kết nối Bluetooth của board %s; %s." % (
                name, ("sau %d giây iPhone sẽ tự nối lại" % int(hold)) if int(hold) > 0 else "iPhone sẽ tự nối lại ngay"), "health": boardhealth.view(st)}
        return self._board_op(name, run)

    # ---- điều khiển lẻ (dùng trong trình dựng bước) ----
    def run_step(self, name, step):
        with _Using(name) as why:
            if why:
                return {"ok": False, "msg": why}
            tr = HISTORY.tracker(name)
            try:
                nav = MGR.session(name)
                tr.run_begin("chạy thử một bước")
                ref = engine.capture_ref(nav, step)          # ảnh mẫu (màn hình ngay trước bước) cho bước chưa có
                ok, msg = engine.run_step(nav, step)
                return dict({"ok": ok, "msg": msg}, **({"screen": ref} if ok and ref else {}))
            except Exception as e:
                return {"ok": False, "msg": str(e)}
            finally:
                tr.run_end()

    # ---- flow ----
    def get_flows(self):
        return store.get_flows()

    def save_flow(self, flow):
        return store.save_flow(flow)

    def delete_flow(self, flow_id):
        store.delete_flow(flow_id)
        return {"ok": True}

    def run_flow(self, name, flow_id):
        with _Using(name) as why:
            if why:
                return {"ok": False, "error": why}
            try:
                nav = MGR.session(name)
                flow = store.get_flow(flow_id)
                if not flow:
                    return {"ok": False, "error": "flow không tồn tại"}
                results = engine.run_flow(nav, flow.get("steps", []), check=False)
                return {"ok": True, "results": results}
            except Exception as e:
                return {"ok": False, "error": str(e), "tb": traceback.format_exc()}

    def run_flow_multi(self, names, flow_id):
        """Chạy 1 flow trên nhiều máy song song (1 lượt, đồng bộ)."""
        flow = store.get_flow(flow_id)
        if not flow:
            return {"ok": False, "error": "flow không tồn tại"}
        out = {}
        threads = []
        def worker(nm):
            with _Using(nm) as why:
                try:
                    if why:
                        raise RuntimeError(why)
                    nav = MGR.session(nm)
                    out[nm] = engine.run_flow(nav, flow.get("steps", []), check=False)
                except Exception as e:
                    out[nm] = [{"ok": False, "msg": str(e)}]
        for nm in names:
            t = threading.Thread(target=worker, args=(nm,)); t.start(); threads.append(t)
        for t in threads: t.join()
        return {"ok": True, "results": out}

    # ---- NHÓM (group) + chạy/dừng từng máy ----
    def groups_list(self):
        return store.get_groups()

    def group_save(self, group):
        return store.save_group(group)

    def group_delete(self, group_id):
        g = store.get_group(group_id)
        if g:
            held = [c["name"] for c in RUNNER.customers() if c["hold"] and c["group_id"] == g.get("id")]
            if held:        # xoá nhóm không phải lời xác nhận «đã đối soát»: còn máy đang giữ thì chưa xoá
                return {"ok": False, "error": "Nhóm còn máy đang DỪNG CHỜ NGƯỜI KIỂM TRA (%s) — kiểm tra và bấm «Đã kiểm tra xong» trên các máy đó "
                                              "rồi mới xoá nhóm." % ", ".join(held)}
            RUNNER.stop_group(g)
        store.delete_group(group_id)
        return {"ok": True}

    def group_add_device(self, group_id, name):
        """Thêm máy vào nhóm (máy có thể ở nhiều nhóm; các nhóm khác của máy giữ nguyên)."""
        return {"ok": bool(store.add_device_to_group(name, group_id))}

    def group_remove_device(self, group_id, name):
        """Bỏ máy khỏi MỘT nhóm."""
        return {"ok": bool(store.remove_device_from_group(name, group_id))}

    @staticmethod
    def _orders_ready(api, what):
        """Cấu hình nhận đơn `api` (của nhóm nhận đơn hoặc của kịch bản nhận đơn) đủ để chạy chưa → None, hoặc câu báo thiếu gì."""
        api = store.api_defaults(api)
        if not api["pool"]:
            return "%s chưa chọn pool của gateway." % what
        try:
            steps = apimode.effective_steps(_gateway().pool(api["pool"]), api["steps"])
        except GatewayError as e:
            return e.vi()
        except apimode.ConfigError as e:
            return "Cấu hình bước sai: %s" % e
        if not steps["purchase"]:
            return "Chưa có «các bước mua 1 gói» (cấu hình trên gateway hoặc trong %s)." % what.lower()
        return None

    @staticmethod
    def _takes_orders(g, script=None):
        """Lần chạy này có NHẬN ĐƠN CỦA KHÁCH không: nhóm nhận đơn kiểu cũ, hoặc kịch bản có cách chạy «nhận đơn từ gateway»."""
        if g.get("mode") == "api":
            return True
        sc = store.pick_script(g, script)
        return bool(sc and sc.get("mode") == "orders")

    def _runnable(self, g, script=None):
        """Nhóm (và kịch bản `script`) đủ điều kiện chạy chưa → None, hoặc câu báo thiếu gì."""
        if g.get("mode") == "api":
            return Api._orders_ready(g.get("api"), "Nhóm")
        scripts = g.get("scripts") or []
        if not scripts:
            return "Nhóm chưa có kịch bản nào."
        sc = store.pick_script(g, script)
        if sc is None:
            if script:
                return "Nhóm không có kịch bản «%s» (hoặc tên trùng nhau). Các kịch bản: %s." % (script, ", ".join(s["name"] for s in scripts))
            return "Nhóm có %d kịch bản — nói rõ chạy kịch bản nào (%s)." % (len(scripts), ", ".join(s["name"] for s in scripts))
        if sc.get("mode") == "orders":
            return Api._orders_ready(sc.get("orders"), "Kịch bản «%s»" % sc["name"])
        if not sc["steps"]:
            return "Kịch bản «%s» chưa có bước nào." % sc["name"]
        return None

    def _running_what(self, names):
        """{tên máy: «nhóm · kịch bản»} cho các máy trong `names` ĐANG CHẠY việc gì đó (một máy chỉ chạy một kịch bản một lúc)."""
        out = {}
        st = RUNNER.status()
        for n in names:
            w = st.get(n) or {}
            if w.get("running"):
                what = " · ".join(x for x in (w.get("group_name"), w.get("script_name")) if x)
                out[n] = what or "việc khác"
        return out

    def _held_what(self, g, names, script=None):
        """{tên máy: lý do} cho các máy trong `names` đang DỪNG CHỜ NGƯỜI KIỂM TRA mà nhóm `g` không được phép chạy đè lên (chỉ chính nhóm nhận đơn
        đã gây ra trạng thái đó mới «Chạy lại» được — và ở chế độ web thì không ai được: gỡ giữ là lời xác nhận của người vận hành)."""
        out = {}
        st = RUNNER.status()
        for n in names:
            hold = RUNNER.hold_reason(n)
            w = st.get(n) or {}
            # «Chạy lại» chỉ dành cho CHÍNH lần nhận đơn đã để máy ở trạng thái giữ: cùng nhóm, và (với kịch bản nhận đơn) cùng kịch bản
            same_api_group = Api._takes_orders(g, script) and w.get("group_id") == g.get("id") and w.get("script_id") == ((store.pick_script(g, script) or {}).get("id") if g.get("mode") != "api" else None)
            if hold and (WEBDEV is not None or not same_api_group):       # chế độ web: «Chạy lại» cũng là gỡ giữ → chỉ làm ở app cửa sổ
                out[n] = hold
            elif not (st.get(n) or {}).get("running"):
                hit = _customer_conflict(n)                               # tên khác nhưng CÙNG iPhone / board với một máy của khách
                if hit and hit != n:
                    out[n] = "cùng iPhone / board với máy «%s» đang làm đơn của khách / dừng chờ kiểm tra" % hit
        return out

    def group_run(self, group_id, names=None, script=None):
        """Chạy một kịch bản của nhóm trên các máy (mặc định: mọi máy của nhóm) — máy nào đang bận việc khác thì bỏ qua và báo trong `busy`.
        Nhóm nhận đơn API không cần `script`."""
        g = store.get_group(group_id)
        if not g:
            return {"ok": False, "error": "nhóm không tồn tại"}
        if Api._takes_orders(g, script) and not RUNNER.allow_api:
            return {"ok": False, "error": WEB_NO_ORDERS}
        why = self._runnable(g, script)
        if why:
            return {"ok": False, "error": why}
        sc = None if g.get("mode") == "api" else store.pick_script(g, script)
        targets = list(names) if names is not None else list(g.get("devices") or [])
        stray = [n for n in targets if n not in (g.get("devices") or [])]
        if stray:
            return {"ok": False, "error": "Máy không thuộc nhóm «%s»: %s." % (g.get("name"), ", ".join(map(str, stray)))}
        held = self._held_what(g, targets, script)        # máy đang giữ chờ kiểm tra: KHÔNG khởi động (kể cả cố ý), báo lại cho người bấm
        go = [n for n in targets if n not in held]
        started, why = CLAIMS.start(go, lambda: RUNNER.start_group(g, go, sc))
        if why:
            return {"ok": False, "error": why}
        left = [n for n in go if n not in (started or [])]
        busy = self._running_what(left)
        for n in left:
            if n not in busy and RUNNER.is_parked(n):
                busy[n] = "đang DỪNG để xử lý tay — bấm «Tiếp tục» trên máy đó"
        return {"ok": True, "started": started, "busy": busy, "held": held}

    def group_stop(self, group_id, force=False, script=None):
        """Dừng các máy đang chạy việc của nhóm này. Có `script` → chỉ những máy đang chạy ĐÚNG kịch bản đó; không nêu → mọi việc của nhóm
        (kể cả máy đang chạy một kịch bản đã bị xoá khỏi nhóm)."""
        g = store.get_group(group_id)
        if g:
            sid = None
            if script and g.get("mode") != "api":
                sc = store.pick_script(g, script)
                if sc is None:
                    return {"ok": False, "error": "Nhóm không có kịch bản «%s»." % script}
                sid = sc["id"]
            RUNNER.stop_group(g, bool(force), sid)          # không bao giờ gỡ «dừng chờ kiểm tra» (xem machine_ack)
        return {"ok": True}

    def machine_run(self, group_id, name, script=None):
        g = store.get_group(group_id)
        if not g:
            return {"ok": False, "error": "nhóm không tồn tại"}
        if Api._takes_orders(g, script) and not RUNNER.allow_api:
            return {"ok": False, "error": WEB_NO_ORDERS}
        why = self._runnable(g, script)
        if why:
            return {"ok": False, "error": why}
        sc = None if g.get("mode") == "api" else store.pick_script(g, script)
        if name not in (g.get("devices") or []):
            return {"ok": False, "error": "Máy «%s» không thuộc nhóm «%s»." % (name, g.get("name"))}
        held = self._held_what(g, [name], script).get(name)
        if held:
            return {"ok": False, "error": "Máy đang DỪNG CHỜ NGƯỜI KIỂM TRA (%s) — kiểm tra máy và xác nhận «Đã kiểm tra xong»%s rồi mới chạy việc khác trên máy này."
                                          % (held, " ở app dạng cửa sổ" if WEBDEV is not None else "")}
        ok, why = CLAIMS.start([name], lambda: RUNNER.start_machine(name, g, sc))
        if why:
            return {"ok": False, "error": why}
        if not ok:
            busy = self._running_what([name]).get(name)
            if busy:
                return {"ok": False, "error": "Máy đang chạy %s — một máy chỉ chạy một kịch bản một lúc, dừng bên đó rồi mới chạy ở đây." % busy}
            if RUNNER.is_parked(name):
                return {"ok": False, "error": "Máy «%s» đang DỪNG để xử lý tay — bấm «Tiếp tục» trên máy đó rồi mới chạy." % name}
            return {"ok": False, "error": "Máy không chạy được lúc này."}
        return {"ok": True, "started": ok}

    def machine_pause(self, name):
        """«Dừng máy» để xử lý tay: máy đang chạy thì tạm dừng (không kết thúc việc đang chạy); máy đang nghỉ thì từ giờ không kịch bản / đơn
        nào chạy lên nó. Máy giữ trạng thái này cho tới khi bấm «Tiếp tục»."""
        known = {d["name"] for d in store.get_devices()} | set(MGR.board_map)
        if name not in known and name not in RUNNER.status():
            return {"ok": False, "error": "Không có máy «%s»." % name}
        RUNNER.pause_machine(name)
        # in_use: đang có MỘT lệnh chạy dở trên máy (thử bước / thử kịch bản trên giao diện, hoặc AI / dòng lệnh). Lệnh đó làm nốt rồi mới
        # hết — «Dừng máy» chỉ chặn các lệnh SAU đó.
        return {"ok": True, "running": RUNNER.is_running(name), "in_use": name in CLAIMS.names()}

    def machine_resume(self, name):
        """«Tiếp tục»: bỏ trạng thái đang dừng của máy; việc đang tạm dừng (nếu có) chạy tiếp."""
        if RUNNER.resume_machine(name):
            return {"ok": True}
        return {"ok": False, "error": "Máy «%s» không đang dừng." % name}

    def stop_all(self, force=False):
        """DỪNG TẤT CẢ máy đang chạy (nhóm nhận đơn: làm nốt đơn dở rồi dừng; force: bỏ dở ngay). Không gỡ trạng thái «dừng chờ kiểm tra» —
        việc đó chỉ người vận hành làm từng máy."""
        n = len(RUNNER.running_names())
        RUNNER.stop_all(bool(force))
        return {"ok": True, "stopped": n}

    def machine_stop(self, name, force=False):
        """force=False: (chế độ API) không nhận đơn mới, làm nốt đơn đang dở rồi dừng.
        force=True: bỏ dở ngay — chưa chạm luồng mua thì báo failed, đã chạm thì báo review."""
        hold = RUNNER.hold_reason(name)
        if hold:            # máy đã dừng và đang giữ: «Dừng» không làm gì và KHÔNG phải lời xác nhận — dùng «Đã kiểm tra xong» (machine_ack)
            return {"ok": False, "error": "Máy «%s» đã dừng và đang CHỜ NGƯỜI KIỂM TRA (%s). Kiểm tra máy rồi bấm «Đã kiểm tra xong»." % (name, hold)}
        RUNNER.stop_machine(name, bool(force))
        return {"ok": True}

    def machine_ack(self, name):
        """«Đã kiểm tra xong»: người vận hành xác nhận đã kiểm tra / đối soát máy đang dừng chờ → gỡ trạng thái giữ. Chỉ nhận ở app dạng CỬA SỔ:
        trang web có thể đang do AI điều khiển, mà lời xác nhận này phải là của người."""
        hold = RUNNER.hold_reason(name)
        if not hold:
            return {"ok": False, "error": "Máy «%s» không ở trạng thái chờ kiểm tra." % name}
        if WEBDEV is not None:
            return {"ok": False, "error": "Máy «%s» đang DỪNG CHỜ NGƯỜI KIỂM TRA (%s). Xác nhận «đã kiểm tra xong» chỉ làm được ở app dạng cửa sổ "
                                          "(chạy `python app/gui.py` không kèm --web)." % (name, hold)}
        return {"ok": bool(RUNNER.ack_hold(name))}

    def run_status(self):
        return RUNNER.status()

    # ---- theo dõi: máy nào đang chạy bước nào + lịch sử theo máy / theo đơn ----
    def history_live(self):
        """{tên máy: việc đang làm}: lượt chạy (nhóm · kịch bản), đơn, giai đoạn, bước thứ mấy / tổng số, bước vừa xong."""
        return {"ok": True, "now": round(time.time(), 2), "live": HISTORY.live()}

    def history_machine(self, name, limit=300, before=None):
        try:
            return {"ok": True, "name": name, "events": HISTORY.machine(str(name), int(limit or 300), float(before) if before else None)}
        except Exception as e:
            return {"ok": False, "error": str(e), "events": []}

    def history_orders(self, limit=200, machine=None):
        try:
            return {"ok": True, "orders": HISTORY.orders(int(limit or 200), str(machine) if machine else None)}
        except Exception as e:
            return {"ok": False, "error": str(e), "orders": []}

    def history_order(self, order_id):
        try:
            return dict(HISTORY.order(order_id), ok=True)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def run_log(self):
        """Nhật ký gần đây của các máy đang nhận đơn (để hiện lại khi mở tab)."""
        return RUNNER.log_tail()

    def test_flow(self, name, steps):
        """Chạy thử nguyên kịch bản (1 lượt) trên 1 máy — dùng trong trình dựng."""
        with _Using(name) as why:
            if why:
                return {"ok": False, "error": why}
            tr = HISTORY.tracker(name)
            try:
                nav = MGR.session(name)
                tr.run_begin("chạy thử kịch bản")
                return {"ok": True, "results": engine.run_flow(nav, steps, capture=True)}
            except Exception as e:
                return {"ok": False, "error": str(e)}
            finally:
                tr.run_end()

    def test_api_steps(self, name, steps, vars=None):
        """Chạy thử các bước của chế độ API trên 1 máy bằng ĐÚNG bộ chạy dùng khi nạp thật
        (bấm an toàn, dò chữ nhiều cách viết, thế {{biến}}). `vars` = giá trị thử cho các biến."""
        with _Using(name) as why:
            if why:
                return {"ok": False, "error": why}
            try:
                nav = MGR.session(name)
            except Exception as e:
                return {"ok": False, "error": str(e)}
            vars = {str(k): str(v) for k, v in (vars or {}).items()}
            tr = HISTORY.tracker(name)
            tr.run_begin("chạy thử một giai đoạn" if len(steps or []) > 1 else "chạy thử một bước")
            try:
                return self._test_api_steps(nav, steps, vars)
            finally:
                tr.run_end()

    @staticmethod
    def _test_api_steps(nav, steps, vars):
            results = []
            apimode.watch_phase(nav, None, len(steps or []))
            for i, st in enumerate(steps or []):
                ref = engine.capture_ref(nav, st)            # ảnh mẫu (màn hình ngay trước bước) cho bước thao tác chưa có
                try:
                    ok, msg, _ = apimode.exec_step(nav, st, vars)
                except (apimode.ConfigError, apimode.InputError) as e:
                    ok, msg = False, str(e)
                except Exception as e:
                    ok, msg = False, "lỗi: %s" % e
                results.append(dict({"i": i, "type": st.get("type"), "ok": ok,
                                     "msg": apimode.describe(st, vars) + ((" — " + msg) if msg else "")}, **({"screen": ref} if ok and ref else {})))     # (bước có điều kiện: «đã bấm» hay «không thấy — bỏ qua»)
                if not ok:
                    break
                time.sleep(apimode.STEP_GAP)
            return {"ok": True, "results": results}

    # ---- kết nối Topup Gateway (chế độ API của nhóm) ----
    def gateway_get(self):
        s = store.get_settings()
        key = s.get("gateway_key") or ""
        return {"url": s.get("gateway_url") or "", "has_key": bool(key), "key_hint": (key[:8] + "…") if key else ""}

    def gateway_save(self, url, key=None):
        if WEBDEV is not None:
            # Khoá gateway là chìa vào đơn của khách; bản web (có thể đang do AI điều khiển) không chạy đơn nên cũng không được đổi nơi gửi khoá tới.
            return {"ok": False, "error": "Cấu hình gateway chỉ đổi được ở app dạng cửa sổ (chạy `python app/gui.py` không kèm --web)."}
        url = (url or "").strip().rstrip("/")
        if url and not re.match(r"^https?://[^\s/]+", url):
            return {"ok": False, "error": "Địa chỉ gateway phải bắt đầu bằng http:// hoặc https://"}
        patch = {"gateway_url": url}
        new_key = str(key).strip() if key else ""
        if new_key:
            patch["gateway_key"] = new_key
        else:               # để trống = giữ khoá đang lưu — CHỈ khi vẫn là máy chủ cũ; đổi máy chủ mà giữ khoá cũ là gửi khoá cho máy chủ mới
            old = store.get_settings()
            if old.get("gateway_key") and _origin(old.get("gateway_url")) != _origin(url):
                return {"ok": False, "error": "Đổi địa chỉ gateway sang máy chủ khác thì phải NHẬP LẠI khoá Tool (khoá cũ không tự gửi sang máy chủ mới)."}
        store.save_settings(patch)
        PRESENCE.kick()                       # cấu hình mới → tự báo ngay theo địa chỉ / khoá mới
        return self.gateway_test()

    def gateway_sync(self, now=False):
        """Trạng thái luồng TỰ BÁO cho gateway (máy nào rảnh ở kịch bản nào + danh mục kịch bản). now=True: báo ngay thay vì chờ nhịp kế.
        Chỉ gửi tới địa chỉ gateway + khoá đã lưu; nội dung bước, UDID không nằm trong lời báo (xem presence.py)."""
        if now:
            PRESENCE.kick()
        return PRESENCE.state()

    def gateway_test(self):
        try:
            r = _gateway().ping()
            return {"ok": True, "key": r.get("key"), "server_time": r.get("server_time")}
        except GatewayError as e:
            return {"ok": False, "error": e.vi()}

    def gateway_pools(self):
        try:
            return {"ok": True, "pools": _gateway().pools()}
        except GatewayError as e:
            return {"ok": False, "error": e.vi(), "pools": []}

    # ---- ảnh mẫu của bước (kiểm màn hình trước khi làm) ----
    def screen_capture(self, name):
        """Chụp ẢNH MẪU từ màn hình đang hiện của máy `name` (nút «Chụp lại ảnh mẫu» trong trình sửa bước)."""
        with _Using(name) as why:
            if why:
                return {"ok": False, "error": why}
            try:
                nav = MGR.session(name)
                priv = _web_privacy(name) if WEBDEV is not None else None
                if priv:
                    return {"ok": False, "error": priv}
                return {"ok": True, "screen": apimode.capture_screen(nav)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    # ---- thông báo Telegram cho admin ----
    def telegram_get(self):
        c = TELEGRAM.config()
        tok = c["token"]
        return {"has_token": bool(tok), "token_hint": (tok.split(":")[0] + ":…") if tok else "", "chat": c["chat"],
                "events": c["events"], "all_events": [{"key": k, "label": v} for k, v in notify.EVENTS.items()],
                "last_error": TELEGRAM.last_error, "sent": TELEGRAM.sent}

    def telegram_save(self, token=None, chat=None, events=None):
        """Lưu cấu hình Telegram. `token` để trống = giữ mã bot đang lưu. Trả cấu hình mới (không bao giờ trả mã bot)."""
        patch = {}
        tok = str(token or "").strip()
        if tok:
            if not re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", tok):
                return {"ok": False, "error": "Mã bot không đúng dạng — lấy ở @BotFather, dạng 123456789:AA…"}
            patch["telegram_token"] = tok
        if chat is not None:
            ch = str(chat).strip()
            if ch and not re.match(r"^(-?\d{3,}|@[A-Za-z0-9_]{4,})$", ch):
                return {"ok": False, "error": "Chat id phải là số (vd 123456789, nhóm thì -100…) hoặc @tên_kênh"}
            patch["telegram_chat"] = ch
        if events is not None:
            patch["telegram_events"] = [e for e in (events or []) if e in notify.EVENTS]
        store.save_settings(patch)
        return dict(self.telegram_get(), ok=True)

    def telegram_test(self):
        ok, err = TELEGRAM.send_now("✅ iPhone Farm: thử thông báo — nếu bạn đọc được tin này thì cấu hình Telegram đã đúng.")
        return {"ok": ok, "error": err}

    # ---- cầu nối cho AI (MCP) + dòng lệnh `farm` ----
    def ai_info(self):
        s = store.get_settings()
        info = CONTROL.info() if CONTROL is not None else {"running": False, "error": "chưa khởi tạo"}
        info["enabled"] = s.get("ai_enabled", True) is not False
        info["tools"] = ([{"name": t.name, "cli": t.cli, "help": t.help, "read_only": t.read_only}
                          for t in CONTROL.server.tools.values()] if CONTROL is not None else [])
        return info

    def ai_set_enabled(self, on):
        store.save_settings({"ai_enabled": bool(on)})
        if CONTROL is not None:
            if on:
                CONTROL.start(int(store.get_settings().get("ai_port") or control.DEFAULT_PORT))
            else:
                CONTROL.stop()
        return self.ai_info()

    def ai_renew_token(self):
        if CONTROL is not None:
            if CONTROL.httpd is not None:
                CONTROL.renew_token()
            else:                               # đang tắt: chỉ đổi khoá, không mở cổng
                control.save_endpoint(0, control.token(renew=True), enabled=False)
                CONTROL.token = control.token()
        return self.ai_info()

    def gateway_pool(self, code):
        """Cấu hình 1 pool, các bước đã đổi sang dạng của tool — để xem và nhập vào nhóm."""
        try:
            pool = _gateway().pool(code)
            steps = {ph: [apimode.gw_step_to_engine(s) for s in (pool.get(apimode.GW_LISTS[ph]) or [])]
                     for ph in apimode.PHASES}
            return {"ok": True, "code": pool.get("code"), "name": pool.get("name"), "active": pool.get("active"),
                    "steps": steps, "rules": pool.get("rules") or [], "packages": pool.get("packages") or [],
                    "login_fields": pool.get("login_fields") or [], "otp": pool.get("otp") or {},
                    # thiếu các thứ này thì máy KHÔNG nhận đơn — giao diện phải nói rõ cho người vận hành
                    "missing_rules": apimode.missing_rules(pool), "required_phases": list(apimode.REQUIRED_PHASES)}
        except GatewayError as e:
            return {"ok": False, "error": e.vi()}
        except apimode.ConfigError as e:
            return {"ok": False, "error": "Cấu hình bước trên gateway sai: %s" % e}


def main(argv=None):
    """`python app/gui.py` mở cửa sổ app. `--web [--web-port N]` chạy giao diện như một trang WEB trên máy này (dev; xem webdev.py)."""
    global WINDOW, CONTROL, WEBDEV
    argv = sys.argv[1:] if argv is None else argv
    web_port = 47822
    if "--web" in argv and "--web-port" in argv:      # kiểm tham số TRƯỚC khi mở bất cứ cổng nào
        i = argv.index("--web-port")
        raw = argv[i + 1] if i + 1 < len(argv) else ""
        if not (raw.isascii() and raw.isdigit()) or not (1024 <= int(raw) <= 65515):          # start() có thể dời tối đa 20 cổng
            print("--web-port cần một số cổng từ 1024 tới 65515 (vd: --web-port 47822).", file=sys.stderr, flush=True)
            return 2
        web_port = int(raw)
    if "--web" in argv:
        # Chế độ web KHÔNG chạy đơn của khách → trong tiến trình này không bao giờ có «máy của khách». Đặt TRƯỚC khi mở bất cứ cổng nào
        # (cầu nối AI mở ngay dưới đây cũng gọi được «chạy nhóm»).
        RUNNER.allow_api = False
    api = Api()
    # Xem board / Bluetooth của các máy ĐANG MỞ trong tiến trình này (cổng serial mở độc quyền: mỗi board chỉ một tiến trình hỏi được → không báo trùng)
    _start_link_watch()
    # Máy chủ điều khiển cho AI (MCP) + lệnh `farm`: chỉ nghe trên máy này (127.0.0.1), cần khoá.
    CONTROL = control.AppServer(control.AppHost(MGR, RUNNER, api, CLAIMS))
    settings = store.get_settings()
    if settings.get("ai_enabled", True) is not False:
        CONTROL.start(int(settings.get("ai_port") or control.DEFAULT_PORT))
    else:
        CONTROL.token = control.token()
    import atexit
    atexit.register(CONTROL.stop)               # tắt app → CLI / `farm mcp` biết app không còn nghe
    if "--web" in argv:
        import webdev
        port = web_port
        token = webdev.load_or_create_token(os.path.join(store.DATA_DIR, "webdev.json"))
        WEBDEV = webdev.WebDev(api, WEB_DIR, token, port, gate=_web_gate)
        WEBDEV.start()
        atexit.register(WEBDEV.stop)
        _start_presence()                       # bản web vẫn báo máy + kịch bản, kèm «không nhận đơn»
        print("Giao diện WEB (dev, chỉ máy này): %s" % WEBDEV.url(), file=sys.stderr, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return
    _start_presence()
    WINDOW = webview.create_window(
        "iPhone Farm Manager",
        os.path.join(WEB_DIR, "index.html"),
        js_api=api, width=1280, height=840, min_size=(1024, 640),
    )
    webview.start()


if __name__ == "__main__":
    sys.exit(main())
