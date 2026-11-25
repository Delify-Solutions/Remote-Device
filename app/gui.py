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

import store, engine, fleet, esp, ios, iosdev, sysinfo, prober, apimode, control, boardhealth
from nav import Nav
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
            self.sessions[name] = nav
            return nav


MGR = Manager()

# Cửa sổ pywebview (đặt trong main) để đẩy cập nhật streaming về giao diện.
WINDOW = None
def _push(js):
    """Gọi 1 hàm JS trên giao diện (an toàn khi gọi từ thread nền)."""
    try:
        if WINDOW is not None:
            WINDOW.evaluate_js(js)
    except Exception:
        pass


def _gateway():
    """Khách gọi Topup Gateway theo cấu hình đã lưu (ném GatewayError nếu chưa cấu hình)."""
    s = store.get_settings()
    return Gateway(s.get("gateway_url") or "", s.get("gateway_key") or "")


# chạy kịch bản nhóm / nhận đơn từ gateway; mỗi máy một worker, dừng độc lập
RUNNER = Runner(MGR.session, gateway_factory=_gateway, journal=apimode.Journal(store.DATA_DIR),
                on_log=lambda entry: _push("window.__runLog && window.__runLog(%s)" % json.dumps(entry)))


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


class _Using:
    """Giữ máy cho MỘT thao tác thử trên giao diện (chạy thử bước / kịch bản). Dùng:  with _Using(name) as why: …
    `why` khác None = không lấy được máy (đang chạy, hoặc AI / dòng lệnh đang điều khiển) → không được làm gì."""
    def __init__(self, name):
        self.name, self.why = name, None

    def __enter__(self):
        self.why = CLAIMS.acquire(self.name, "ui")
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
        script = os.path.abspath(sys.argv[0])
        def _do():
            try:
                os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
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
        grp_by_dev = {}
        for g in store.get_groups():
            for dn in g.get("devices", []):
                grp_by_dev[dn] = {"id": g["id"], "name": g.get("name", g["id"])}
        def enrich(entry):
            info = ios_by_udid.get(entry.get("udid"))
            entry["ios_connected"] = info is not None
            entry["ios"] = info["ios"] if info else None
            entry["model"] = info["model"] if info else None
            entry["device_name"] = info["name"] if info else None
            g = grp_by_dev.get(entry.get("name"))
            entry["group_id"] = g["id"] if g else None
            entry["group_name"] = g["name"] if g else None
            entry["running"] = RUNNER.is_running(entry.get("name"))
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
        store.upsert_device(name, udid, label)
        return {"ok": True}

    def delete_device(self, name):
        why = _busy(name)
        if why:
            return {"ok": False, "error": why}
        store.delete_device(name)
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
            r = esp.flash(port, name)
        # đổi tên: chuyển gán iPhone + nhãn từ tên cũ -> tên mới, bỏ 'máy cũ tên cũ'
        if r.get("ok") and old_name and old_name != name:
            try:
                store.rename_device(old_name, name)
                grp = store.group_of_device(old_name)       # máy đổi tên thì vẫn ở nhóm cũ
                if grp:
                    store.set_device_group(old_name, None)
                    store.set_device_group(name, grp["id"])
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
        with _Using(name) as why:       # AI / dòng lệnh đang điều khiển máy này → cũng không chen lệnh vào
            if why:
                return {"ok": True, "status": "OK ble=connected (máy đang được điều khiển)"}
            try:
                nav = MGR.session(name)
                st = nav.h.status()
                return {"ok": True, "status": st, "health": boardhealth.view(st)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    # ---- điều khiển lẻ (dùng trong trình dựng bước) ----
    def run_step(self, name, step):
        with _Using(name) as why:
            if why:
                return {"ok": False, "msg": why}
            try:
                nav = MGR.session(name)
                ok, msg = engine.run_step(nav, step)
                return {"ok": ok, "msg": msg}
            except Exception as e:
                return {"ok": False, "msg": str(e)}

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
                results = engine.run_flow(nav, flow.get("steps", []))
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
                    out[nm] = engine.run_flow(nav, flow.get("steps", []))
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
            RUNNER.stop_group(g)
        store.delete_group(group_id)
        return {"ok": True}

    def set_device_group(self, name, group_id):
        store.set_device_group(name, group_id or None)
        return {"ok": True}

    def _runnable(self, g):
        """Nhóm đủ điều kiện chạy chưa → None, hoặc câu báo thiếu gì."""
        if g.get("mode") == "api":
            api = store.api_defaults(g.get("api"))
            if not api["pool"]:
                return "Nhóm chưa chọn pool của gateway."
            try:
                steps = apimode.effective_steps(_gateway().pool(api["pool"]), api["steps"])
            except GatewayError as e:
                return e.vi()
            except apimode.ConfigError as e:
                return "Cấu hình bước sai: %s" % e
            if not steps["purchase"]:
                return "Chưa có «các bước mua 1 gói» (cấu hình trên gateway hoặc trong nhóm)."
            return None
        if not g.get("steps"):
            return "Nhóm chưa có bước nào trong kịch bản."
        return None

    def group_run(self, group_id, names=None):
        g = store.get_group(group_id)
        if not g:
            return {"ok": False, "error": "nhóm không tồn tại"}
        why = self._runnable(g)
        if why:
            return {"ok": False, "error": why}
        targets = list(names) if names is not None else list(g.get("devices") or [])
        started, why = CLAIMS.start(targets, lambda: RUNNER.start_group(g, names))
        if why:
            return {"ok": False, "error": why}
        return {"ok": True, "started": started}

    def group_stop(self, group_id, force=False):
        g = store.get_group(group_id)
        if g:
            RUNNER.stop_group(g, bool(force))
        return {"ok": True}

    def machine_run(self, group_id, name):
        g = store.get_group(group_id)
        if not g:
            return {"ok": False, "error": "nhóm không tồn tại"}
        why = self._runnable(g)
        if why:
            return {"ok": False, "error": why}
        ok, why = CLAIMS.start([name], lambda: RUNNER.start_machine(name, g))
        if why:
            return {"ok": False, "error": why}
        return {"ok": True, "started": ok}

    def machine_stop(self, name, force=False):
        """force=False: (chế độ API) không nhận đơn mới, làm nốt đơn đang dở rồi dừng.
        force=True: bỏ dở ngay — chưa chạm luồng mua thì báo failed, đã chạm thì báo review."""
        RUNNER.stop_machine(name, bool(force))
        return {"ok": True}

    def run_status(self):
        return RUNNER.status()

    def run_log(self):
        """Nhật ký gần đây của các máy đang nhận đơn (để hiện lại khi mở tab)."""
        return RUNNER.log_tail()

    def test_flow(self, name, steps):
        """Chạy thử nguyên kịch bản (1 lượt) trên 1 máy — dùng trong trình dựng."""
        with _Using(name) as why:
            if why:
                return {"ok": False, "error": why}
            try:
                nav = MGR.session(name)
                return {"ok": True, "results": engine.run_flow(nav, steps)}
            except Exception as e:
                return {"ok": False, "error": str(e)}

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
            results = []
            for i, st in enumerate(steps or []):
                try:
                    ok, msg, _ = apimode.exec_step(nav, st, vars)
                except (apimode.ConfigError, apimode.InputError) as e:
                    ok, msg = False, str(e)
                except Exception as e:
                    ok, msg = False, "lỗi: %s" % e
                results.append({"i": i, "type": st.get("type"), "ok": ok,
                                "msg": apimode.describe(st, vars) + ("" if ok else " — " + msg)})
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
        url = (url or "").strip().rstrip("/")
        if url and not re.match(r"^https?://[^\s/]+", url):
            return {"ok": False, "error": "Địa chỉ gateway phải bắt đầu bằng http:// hoặc https://"}
        patch = {"gateway_url": url}
        if key and str(key).strip():        # để trống = giữ khoá đang lưu
            patch["gateway_key"] = str(key).strip()
        store.save_settings(patch)
        return self.gateway_test()

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


def main():
    global WINDOW, CONTROL
    api = Api()
    # Máy chủ điều khiển cho AI (MCP) + lệnh `farm`: chỉ nghe trên máy này (127.0.0.1), cần khoá.
    CONTROL = control.AppServer(control.AppHost(MGR, RUNNER, api, CLAIMS))
    settings = store.get_settings()
    if settings.get("ai_enabled", True) is not False:
        CONTROL.start(int(settings.get("ai_port") or control.DEFAULT_PORT))
    else:
        CONTROL.token = control.token()
    import atexit
    atexit.register(CONTROL.stop)               # tắt app → CLI / `farm mcp` biết app không còn nghe
    WINDOW = webview.create_window(
        "iPhone Farm Manager",
        os.path.join(WEB_DIR, "index.html"),
        js_api=api, width=1280, height=840, min_size=(1024, 640),
    )
    webview.start()


if __name__ == "__main__":
    main()
