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


def _read_strict(path):
    """Như _read nhưng KHÔNG nuốt lỗi: tệp không đọc được / hỏng thì ném lỗi thay vì trả []. Dùng ở nơi mà «danh sách rỗng» và «đọc lỗi»
    phải tách bạch (vd luồng tự báo gateway: báo nhầm «không còn máy / kịch bản nào» thì gateway xoá sạch dữ liệu của tool)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("%s không phải một danh sách" % os.path.basename(path))
    return data


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---- devices ----
def get_devices():
    _ensure(); return _read(DEVICES_FILE)


def get_devices_strict():
    _ensure(); return _read_strict(DEVICES_FILE)


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


# ---- groups (nhóm máy + danh sách kịch bản) ----
# group = {id, name, devices:[board_name...] (một máy có thể ở NHIỀU nhóm), mode:"loop"|"once"|"api" (giao diện nhóm hiện chỉ dùng "once"),
#          scripts:[{id, name, steps:[...], mode:"once"|"loop", loops:int}] — cách chạy (1 lần / lặp N vòng) nằm TRONG kịch bản;
#          một máy chỉ chạy một kịch bản một lúc (runner giữ chỗ theo tên máy),
#          created, updated,
#          api:{pool, steps:{login:[],otp:[],nav:[],purchase:[],finish:[]},
#               login_wait, purchase_wait, check_keyboard}}
# mode "api": máy trống tự xin đơn ở gateway; `api.steps` để TRỐNG giai đoạn nào thì giai
# đoạn đó dùng các bước cấu hình trên gateway (pool), có thì ghi đè riêng cho nhóm máy này.
def api_defaults(api=None):
    """Chuẩn hoá khối cấu hình API của nhóm (thiếu gì bù mặc định)."""
    api = dict(api) if isinstance(api, dict) else {}
    steps = api.get("steps") if isinstance(api.get("steps"), dict) else {}
    api["pool"] = str(api.get("pool") or "")
    # mỗi giai đoạn là một DANH SÁCH các bước (dict); dữ liệu rác (chuỗi, số, phần tử không phải bước) bị bỏ — không để nó tới bộ chạy
    api["steps"] = {ph: [x for x in steps.get(ph) if isinstance(x, dict)] if isinstance(steps.get(ph), list) else [] for ph in API_PHASES}

    def _num(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(api.get(key, default))))
        except (TypeError, ValueError):
            return default
    api["login_wait"] = _num("login_wait", 45, 5, 600)
    api["purchase_wait"] = _num("purchase_wait", 60, 5, 600)
    api["check_keyboard"] = bool(api.get("check_keyboard", True))
    return api


def norm_scripts(group):
    """Chuẩn hoá danh sách kịch bản của nhóm. MỖI kịch bản tự mang cách chạy của nó:
         {id, name, steps:[...], mode:"once"|"loop"|"orders", loops:int (chỉ khi lặp; 0 = vô hạn)}.
    Cách chạy «orders» = KỊCH BẢN NHẬN ĐƠN từ gateway: máy đứng chờ → gateway có đơn → tool giữ chỗ (xin đơn) cho máy → chạy các bước theo
    giai đoạn của đơn. Cấu hình nằm ở khoá `orders` (cùng dạng với `api` của nhóm nhận đơn: pool + bước từng giai đoạn + thời gian chờ) và
    được giữ lại cả khi kịch bản tạm chuyển sang cách chạy khác.
    Nhóm cũ (chỉ có `steps`, chưa có khoá `scripts`) → thành 1 kịch bản «Kịch bản 1» (id cố định «k1»; chạy theo `mode`/`loops` cũ của nhóm).
    Có khoá `scripts` (kể cả rỗng) thì danh sách đó là chuẩn — không dựng lại từ `steps` cũ. Nhóm không còn `steps` / `active_script`."""
    raw = group.get("scripts")
    if raw is None:
        old_mode = "loop" if group.get("mode") == "loop" else "once"
        raw = [{"id": "k1", "name": "Kịch bản 1", "steps": group.get("steps") or [], "mode": old_mode,
                "loops": group.get("loops", 0 if old_mode == "loop" else 1)}] if group.get("steps") else []
    scripts, seen = [], set()
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "")
        while not sid or sid in seen:
            sid = uuid.uuid4().hex[:6]
        seen.add(sid)
        name = str(s.get("name") or "").strip()[:80] or "Kịch bản %d" % (len(scripts) + 1)
        steps = s.get("steps")
        mode = s.get("mode") if s.get("mode") in ("loop", "orders") else "once"
        try:
            loops = max(0, min(100000, int(s.get("loops", 0 if mode == "loop" else 1))))
        except (TypeError, ValueError):
            loops = 0 if mode == "loop" else 1
        sc = {"id": sid, "name": name, "steps": list(steps) if isinstance(steps, list) else [], "mode": mode, "loops": loops}
        if mode == "orders" or isinstance(s.get("orders"), dict):
            sc["orders"] = api_defaults(s.get("orders") if isinstance(s.get("orders"), dict) else None)
        scripts.append(sc)
    group["scripts"] = scripts
    group.pop("steps", None)
    group.pop("active_script", None)
    return group


def pick_script(group, ref=None):
    """Kịch bản của nhóm theo id hoặc tên (không phân biệt hoa thường / dấu cách thừa); `ref` rỗng → chỉ khi nhóm có ĐÚNG 1 kịch bản.
    Không tìm ra / mơ hồ → None."""
    scripts = group.get("scripts") or []
    if not ref:
        return scripts[0] if len(scripts) == 1 else None
    want = " ".join(str(ref).split()).lower()
    hits = [s for s in scripts if s["id"] == ref] or [s for s in scripts if " ".join(s["name"].split()).lower() == want]
    return hits[0] if len(hits) == 1 else None


def get_groups():
    _ensure(); return [norm_scripts(g) for g in _read(GROUPS_FILE)]


def get_groups_strict():
    _ensure(); return [norm_scripts(g) for g in _read_strict(GROUPS_FILE)]


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
    norm_scripts(group)
    group.setdefault("devices", [])
    if group.get("mode") not in ("loop", "once", "api"):
        group["mode"] = "once"                       # «api» = nhóm nhận đơn từ gateway; còn lại nhóm chạy các kịch bản của nó
    try:
        group["loops"] = max(0, min(100000, int(group.get("loops", 1))))
    except (TypeError, ValueError):
        group["loops"] = 1
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


def groups_of_device(name):
    """Mọi nhóm (list dict) có máy `name` — một máy có thể ở NHIỀU nhóm."""
    return [g for g in get_groups() if name in g.get("devices", [])]


def group_of_device(name):
    """Nhóm đầu tiên chứa máy `name`, hoặc None (giữ cho chỗ cũ chỉ cần biết «có ở nhóm nào không»)."""
    gs = groups_of_device(name)
    return gs[0] if gs else None


def add_device_to_group(name, group_id):
    """Thêm máy vào nhóm `group_id` (giữ nguyên các nhóm khác của máy). False nếu nhóm không tồn tại."""
    groups = get_groups()
    g = next((x for x in groups if x["id"] == group_id), None)
    if g is None:
        return False
    if name not in g.setdefault("devices", []):
        g["devices"].append(name)
        _write(GROUPS_FILE, groups)
    return True


def remove_device_from_group(name, group_id):
    """Bỏ máy khỏi MỘT nhóm (các nhóm khác của máy giữ nguyên). False nếu nhóm không tồn tại."""
    groups = get_groups()
    g = next((x for x in groups if x["id"] == group_id), None)
    if g is None:
        return False
    if name in g.get("devices", []):
        g["devices"] = [d for d in g["devices"] if d != name]
        _write(GROUPS_FILE, groups)
    return True


def rename_in_groups(old_name, new_name):
    """Máy đổi tên (nạp lại firmware) → đổi tên trong MỌI nhóm chứa nó, giữ vị trí."""
    if not old_name or not new_name or old_name == new_name:
        return
    groups = get_groups()
    changed = False
    for g in groups:
        devs = g.get("devices", [])
        if old_name in devs:
            out = []
            for d in devs:
                d = new_name if d == old_name else d
                if d not in out:
                    out.append(d)
            g["devices"] = out
            changed = True
    if changed:
        _write(GROUPS_FILE, groups)
