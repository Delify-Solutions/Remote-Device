#!/usr/bin/env python3
"""
runner.py — chạy kịch bản của NHÓM trên từng máy bằng worker riêng.

Mỗi máy = 1 thread + 1 cờ dừng (Event) → dừng 1 máy không ảnh hưởng máy khác.
Chế độ: "loop" (lặp N vòng, 0 = vô hạn) · "once" (1 lần). (Chế độ "api" làm ở pha 2.)
"""
from __future__ import annotations
import threading
import engine


class Runner:
    def __init__(self, session_getter):
        self._session = session_getter      # name -> Nav
        self.lock = threading.Lock()
        self.workers = {}                   # name -> dict

    # ---- trạng thái ----
    def is_running(self, name):
        w = self.workers.get(name)
        return bool(w and not w["stop"].is_set() and w["thread"].is_alive())

    def _snap(self, name):
        w = self.workers.get(name)
        if not w:
            return {"name": name, "running": False, "status": "nghỉ"}
        return {
            "name": name,
            "running": not w["stop"].is_set() and w["thread"].is_alive(),
            "group_id": w["group_id"], "mode": w["mode"],
            "iter": w["iter"], "status": w["status"],
            "last_ok": w.get("last_ok"), "last_msg": w.get("last_msg"),
        }

    def status(self):
        with self.lock:
            return {n: self._snap(n) for n in list(self.workers)}

    # ---- điều khiển ----
    def start_machine(self, name, group):
        with self.lock:
            if self.is_running(name):
                return False
            stop = threading.Event()
            w = {"stop": stop, "group_id": group.get("id"), "mode": group.get("mode", "loop"),
                 "iter": 0, "status": "chuẩn bị", "last_ok": None, "last_msg": None}
            t = threading.Thread(target=self._run, args=(name, dict(group), w), daemon=True)
            w["thread"] = t
            self.workers[name] = w
            t.start()
            return True

    def stop_machine(self, name):
        with self.lock:
            w = self.workers.get(name)
            if w:
                w["stop"].set()
        return True

    def start_group(self, group, names=None):
        targets = names if names is not None else list(group.get("devices", []))
        return [n for n in targets if self.start_machine(n, group)]

    def stop_group(self, group):
        for n in list(group.get("devices", [])):
            self.stop_machine(n)
        return True

    def stop_all(self):
        with self.lock:
            for w in self.workers.values():
                w["stop"].set()

    # ---- vòng chạy của 1 máy ----
    def _run(self, name, group, w):
        stop = w["stop"]
        mode = group.get("mode", "loop")
        loops = int(group.get("loops") or 0)
        steps = group.get("steps", [])
        if not steps:
            w["status"] = "nhóm chưa có bước nào"
            return
        try:
            nav = self._session(name)
        except Exception as e:
            w["status"] = "lỗi mở máy: " + str(e)
            return
        count = 0
        while not stop.is_set():
            count += 1
            w["iter"] = count
            w["status"] = f"đang chạy · vòng {count}"
            try:
                res = engine.run_flow(nav, steps, stop_check=lambda: stop.is_set())
                oks = sum(1 for r in res if r.get("ok"))
                w["last_ok"] = (oks == len(res)) if res else True
                w["last_msg"] = f"{oks}/{len(res)} bước OK"
            except Exception as e:
                w["last_ok"] = False
                w["last_msg"] = str(e)
            if stop.is_set():
                break
            if mode == "once":
                break
            if mode == "loop" and loops > 0 and count >= loops:
                break
            stop.wait(1.0)      # nghỉ giữa vòng, vẫn thoát ngay khi bị dừng
        w["status"] = "đã dừng" if stop.is_set() else "xong"
