#!/usr/bin/env python3
"""
gui.py — App quản lý iPhone farm (desktop, cross-platform qua pywebview).

Chạy:  python app/gui.py       -> mở cửa sổ app (không cần trình duyệt)

Cấu trúc: Manager giữ phiên điều khiển từng board; Api là cầu nối cho giao diện
(web/index.html) gọi xuống Python; webview hiển thị giao diện trong cửa sổ native.
"""
from __future__ import annotations
import os, sys, base64, threading, traceback, json, pathlib
sys.path.insert(0, os.path.dirname(__file__))

import cv2
import webview

import store, engine, fleet, esp, ios, iosdev, sysinfo, prober
from nav import Nav
from eyes import Eyes

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class Manager:
    """Giữ phiên Nav cho từng board (mở lười, giữ cổng serial)."""
    def __init__(self):
        self.board_map = {}     # tên board -> cổng serial
        self.ble_map = {}       # tên board -> True/False/None (đã nối Bluetooth iPhone?)
        self.sessions = {}      # tên board -> Nav
        self.lock = threading.Lock()

    def close_all(self):
        """Đóng hết phiên để trả cổng serial (cho dò/nạp ESP)."""
        for nav in self.sessions.values():
            try: nav.close()
            except Exception: pass
        self.sessions.clear()

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
            if not self.board_map:
                self.board_map = fleet.discover()
            port = self.board_map.get(name)
            if not port:
                raise RuntimeError(f"Không thấy board '{name}' (bấm Quét lại)")
            udid = self._udid(name)
            if not udid:
                raise RuntimeError(f"Board '{name}' chưa gán UDID iPhone")
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
        def enrich(entry):
            info = ios_by_udid.get(entry.get("udid"))
            entry["ios_connected"] = info is not None
            entry["ios"] = info["ios"] if info else None
            entry["model"] = info["model"] if info else None
            entry["device_name"] = info["name"] if info else None
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
        store.delete_device(name)
        MGR.sessions.pop(name, None)      # đóng phiên cũ nếu có
        return {"ok": True}

    def probe_match(self, board_name):
        """DÒ MÁY: xác định board này đang điều khiển iPhone nào (rung chuột + so màn),
        rồi tự (re)gán board -> UDID. Xử lý được ca thay/đổi máy."""
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
        with MGR.lock:
            MGR.close_all()
            ports = esp.list_boards()
            MGR.board_map = {}
            MGR.ble_map = {}
        initial = [dict(b, flashed=None, name=None) for b in ports]

        def worker(b):
            try:
                p = esp.probe(b["port"])
                name, flashed, ble = p.get("name"), bool(p["flashed"]), p.get("ble")
            except Exception:
                name, flashed, ble = None, False, None
            if name:
                with MGR.lock:
                    MGR.board_map[name] = b["port"]
                    MGR.ble_map[name] = ble
            _push("window.__espUpdate(%s)" % json.dumps(dict(b, flashed=flashed, name=name, ble=ble)))
            _push("window.__devBoard(%s)" % json.dumps({"name": name, "port": b["port"], "ble": ble}))

        threads = [threading.Thread(target=worker, args=(b,), daemon=True) for b in ports]
        for t in threads:
            t.start()

        def waiter():
            for t in threads:
                t.join()
            _push("window.__scanDone(%d)" % len(ports))
        threading.Thread(target=waiter, daemon=True).start()
        return initial

    def esp_chip(self, port):
        with MGR.lock:
            MGR.close_all()
            return esp.chip_info(port)

    def esp_flash(self, port, name):
        """Nạp firmware với tên chọn (dùng để nạp mới hoặc đổi tên)."""
        with MGR.lock:
            # tên board đang nạp trên cổng này (để chuyển cấu hình khi đổi tên)
            old_name = next((n for n, p in MGR.board_map.items() if p == port), None)
            MGR.close_all()
            r = esp.flash(port, name)
        # đổi tên: chuyển gán iPhone + nhãn từ tên cũ -> tên mới, bỏ 'máy cũ tên cũ'
        if r.get("ok") and old_name and old_name != name:
            try:
                store.rename_device(old_name, name)
                MGR.sessions.pop(old_name, None)
            except Exception:
                pass
        MGR.board_map = {}       # buộc quét lại
        return r

    def esp_erase(self, port):
        with MGR.lock:
            MGR.close_all()
            r = esp.erase(port)
        MGR.board_map = {}
        return r

    # ---- thiết bị iOS ----
    def ios_list(self):
        return ios.list_connected()

    def screenshot(self, name):
        try:
            nav = MGR.session(name)
            img = nav.e.screenshot()
            ok, buf = cv2.imencode(".png", img)
            b64 = base64.b64encode(buf.tobytes()).decode()
            h, w = img.shape[:2]
            return {"ok": True, "img": "data:image/png;base64," + b64, "w": w, "h": h}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ble_status(self, name):
        try:
            nav = MGR.session(name)
            return {"ok": True, "status": nav.h.status()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- điều khiển lẻ (dùng trong trình dựng bước) ----
    def run_step(self, name, step):
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
        """Chạy 1 flow trên nhiều máy song song."""
        flow = store.get_flow(flow_id)
        if not flow:
            return {"ok": False, "error": "flow không tồn tại"}
        out = {}
        threads = []
        def worker(nm):
            try:
                nav = MGR.session(nm)
                out[nm] = engine.run_flow(nav, flow.get("steps", []))
            except Exception as e:
                out[nm] = [{"ok": False, "msg": str(e)}]
        for nm in names:
            t = threading.Thread(target=worker, args=(nm,)); t.start(); threads.append(t)
        for t in threads: t.join()
        return {"ok": True, "results": out}


def main():
    global WINDOW
    api = Api()
    WINDOW = webview.create_window(
        "iPhone Farm Manager",
        os.path.join(WEB_DIR, "index.html"),
        js_api=api, width=1280, height=840, min_size=(1024, 640),
    )
    webview.start()


if __name__ == "__main__":
    main()
