#!/usr/bin/env python3
"""
store.py — lưu trữ cấu hình & flow dạng JSON (app/data/).

- devices.json : danh sách máy {name(board BLE), udid, label}
- flows.json   : danh sách flow {id, name, steps:[...]}
"""
from __future__ import annotations
import json, os, time, uuid

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
FLOWS_FILE = os.path.join(DATA_DIR, "flows.json")


def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DEVICES_FILE):
        _write(DEVICES_FILE, [])
    if not os.path.exists(FLOWS_FILE):
        _write(FLOWS_FILE, [])


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---- devices ----
def get_devices():
    _ensure(); return _read(DEVICES_FILE)


def save_devices(devices):
    _ensure(); _write(DEVICES_FILE, devices); return devices


def upsert_device(name, udid, label=None):
    devs = get_devices()
    for d in devs:
        if d["name"] == name:
            d["udid"] = udid
            if label is not None: d["label"] = label
            break
    else:
        devs.append({"name": name, "udid": udid, "label": label or name})
    return save_devices(devs)


def delete_device(name):
    devs = [d for d in get_devices() if d.get("name") != name]
    return save_devices(devs)


def rename_device(old_name, new_name):
    """Đổi tên board: chuyển cấu hình (udid/label) từ tên cũ -> tên mới.
    Dùng khi nạp lại firmware đổi tên BLE, để không để lại 'máy cũ tên cũ'."""
    if not old_name or not new_name or old_name == new_name:
        return get_devices()
    devs = get_devices()
    old = next((d for d in devs if d.get("name") == old_name), None)
    if not old:
        return devs
    # bỏ entry trùng tên mới (nếu có) rồi gán tên cũ -> tên mới
    devs = [d for d in devs if d.get("name") != new_name]
    old["name"] = new_name
    if old.get("label") in (None, "", old_name):   # nhãn mặc định theo tên -> cập nhật theo tên mới
        old["label"] = new_name
    return save_devices(devs)


# ---- flows ----
def get_flows():
    _ensure(); return _read(FLOWS_FILE)


def get_flow(flow_id):
    for f in get_flows():
        if f["id"] == flow_id:
            return f
    return None


def save_flow(flow):
    _ensure()
    flows = get_flows()
    if not flow.get("id"):
        flow["id"] = uuid.uuid4().hex[:8]
        flow["created"] = time.time()
    flow["updated"] = time.time()
    for i, f in enumerate(flows):
        if f["id"] == flow["id"]:
            flows[i] = flow
            break
    else:
        flows.append(flow)
    _write(FLOWS_FILE, flows)
    return flow


def delete_flow(flow_id):
    flows = [f for f in get_flows() if f["id"] != flow_id]
    _write(FLOWS_FILE, flows)
    return True
