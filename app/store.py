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
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")     # địa chỉ + khoá gateway (KHÔNG vào git)

# Chế độ "api": các giai đoạn của 1 đơn nạp. Mỗi giai đoạn có danh sách bước riêng.
#   login    đăng nhập tài khoản của khách
#   otp      nhập mã OTP khách vừa gửi ({{otp}})
#   nav      từ màn hình sau đăng nhập đi tới danh sách gói nạp
#   purchase mua MỘT gói (lặp theo số lượng) — dừng ở màn hình báo kết quả để tool chụp bill
#   after    sau khi mua xong 1 gói: đóng thông báo, quay lại danh sách gói
#   finish   kết thúc đơn: đăng xuất, về màn hình chính (để máy sẵn sàng cho đơn sau)
API_PHASES = ["login", "otp", "nav", "purchase", "after", "finish"]


def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DEVICES_FILE):
        _write(DEVICES_FILE, [])
    if not os.path.exists(FLOWS_FILE):
        _write(FLOWS_FILE, [])
    if not os.path.exists(GROUPS_FILE):
        _write(GROUPS_FILE, [])


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


# ---- settings (dict) ----
def get_settings():
    _ensure()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(patch):
    s = get_settings()
    s.update(patch)
    _write(SETTINGS_FILE, s)
    try:
        os.chmod(SETTINGS_FILE, 0o600)      # có khoá API → chỉ chủ máy đọc được
    except OSError:
        pass
    return s


# ---- groups (nhóm máy + 1 kịch bản riêng) ----
# group = {id, name, steps:[...], devices:[board_name...], mode:"loop"|"once"|"api",
#          loops:int (0=vô hạn), created, updated,
#          api:{pool, steps:{login:[],otp:[],nav:[],purchase:[],finish:[]},
#               login_wait, purchase_wait, check_keyboard}}
# mode "api": máy trống tự xin đơn ở gateway; `api.steps` để TRỐNG giai đoạn nào thì giai
# đoạn đó dùng các bước cấu hình trên gateway (pool), có thì ghi đè riêng cho nhóm máy này.
def api_defaults(api=None):
    """Chuẩn hoá khối cấu hình API của nhóm (thiếu gì bù mặc định)."""
    api = dict(api or {})
    steps = dict(api.get("steps") or {})
    api["pool"] = str(api.get("pool") or "")
    api["steps"] = {ph: list(steps.get(ph) or []) for ph in API_PHASES}

    def _num(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(api.get(key, default))))
        except (TypeError, ValueError):
            return default
    api["login_wait"] = _num("login_wait", 45, 5, 600)
    api["purchase_wait"] = _num("purchase_wait", 60, 5, 600)
    api["check_keyboard"] = bool(api.get("check_keyboard", True))
    return api


def get_groups():
    _ensure(); return _read(GROUPS_FILE)


def get_group(group_id):
    for g in get_groups():
        if g["id"] == group_id:
            return g
    return None


def save_group(group):
    _ensure()
    groups = get_groups()
    if not group.get("id"):
        group["id"] = uuid.uuid4().hex[:8]
        group["created"] = time.time()
    group.setdefault("steps", [])
    group.setdefault("devices", [])
    if group.get("mode") not in ("loop", "once", "api"):
        group["mode"] = "loop"
    group.setdefault("loops", 0)
    group["api"] = api_defaults(group.get("api"))
    group["updated"] = time.time()
    for i, g in enumerate(groups):
        if g["id"] == group["id"]:
            groups[i] = group
            break
    else:
        groups.append(group)
    _write(GROUPS_FILE, groups)
    return group


def delete_group(group_id):
    groups = [g for g in get_groups() if g["id"] != group_id]
    _write(GROUPS_FILE, groups)
    return True


def group_of_device(name):
    """Trả group (dict) chứa máy `name`, hoặc None."""
    for g in get_groups():
        if name in g.get("devices", []):
            return g
    return None


def set_device_group(name, group_id):
    """Gán máy vào 1 nhóm (gỡ khỏi nhóm cũ). group_id=None/"" = bỏ khỏi mọi nhóm."""
    groups = get_groups()
    for g in groups:
        devs = g.get("devices", [])
        if name in devs and g["id"] != group_id:
            g["devices"] = [d for d in devs if d != name]
    if group_id:
        for g in groups:
            if g["id"] == group_id and name not in g.get("devices", []):
                g.setdefault("devices", []).append(name)
    _write(GROUPS_FILE, groups)
    return True
