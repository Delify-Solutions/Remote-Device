#!/usr/bin/env python3
"""
store.py — lưu trữ cấu hình dạng JSON (app/data/): máy, nhóm + kịch bản, cài đặt.

- devices.json : danh sách máy {name(board BLE), udid, label}
- groups.json  : nhóm máy, mỗi nhóm có danh sách kịch bản (các bước nằm trong kịch bản)
"""
from __future__ import annotations
import functools, json, os, threading, time, uuid

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")     # địa chỉ + khoá gateway (KHÔNG vào git)

# Kịch bản NHẬN ĐƠN: các giai đoạn của 1 đơn nạp. Mỗi giai đoạn có danh sách bước riêng.
#   login    đăng nhập tài khoản của khách
#   otp      nhập mã OTP khách vừa gửi ({{otp}})
#   nav      từ màn hình sau đăng nhập đi tới danh sách gói nạp
#   purchase mua MỘT gói (lặp theo số lượng) — dừng ở màn hình báo kết quả để tool chụp bill
#   after    sau khi mua xong 1 gói: đóng thông báo, quay lại danh sách gói
#   finish   kết thúc đơn: đăng xuất, về màn hình chính (để máy sẵn sàng cho đơn sau)
API_PHASES = ["login", "otp", "nav", "purchase", "after", "finish"]


DEFAULTS_DIR = os.path.join(os.path.dirname(__file__), "defaults")     # dữ liệu mặc định đi kèm bản phát hành (vd nhóm + kịch bản có sẵn)


# MỘT khoá cho mọi lần «đọc → sửa → ghi» các tệp ở đây. Giao diện gọi mỗi lệnh ở một luồng riêng, bộ chạy cũng ghi (chép bước đời cũ vào
# kịch bản): hai luồng cùng đọc-sửa-ghi mà không khoá thì bên ghi sau đè mất thay đổi của bên kia. (Khoá lồng được: hàm có khoá gọi nhau.)
_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def run(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return run


@_locked
def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DEVICES_FILE):
        _write(DEVICES_FILE, [])
    if not os.path.exists(GROUPS_FILE):
        # máy mới cài từ bản phát hành có kèm app/defaults/groups.json → bắt đầu với nhóm + kịch bản có sẵn. Chỉ khi CHƯA có tệp nhóm:
        # giải nén bản mới đè lên máy đang dùng không bao giờ ghi đè nhóm / kịch bản hiện có.
        seed = []
        try:
            with open(os.path.join(DEFAULTS_DIR, "groups.json"), "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            # chỉ nhận nhóm đúng dạng (có id, chuẩn hoá kịch bản được); tệp hỏng / sai dạng → bắt đầu trống, KHÔNG làm app không mở được
            for g in raw if isinstance(raw, list) else []:
                if not (isinstance(g, dict) and isinstance(g.get("id"), str) and g["id"]):
                    continue
                g = dict(g, devices=[])        # máy là của riêng từng nơi cài: không mang tên máy của nơi xuất sang
                try:
                    norm_scripts(dict(g))      # nhóm làm hỏng bước chuẩn hoá (vd số lần lặp vô hạn) sẽ làm app lỗi mỗi lần mở → bỏ
                except Exception:
                    continue
                seed.append(g)
        except (OSError, ValueError):
            seed = []
        _write(GROUPS_FILE, seed)


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
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())      # tên tạm RIÊNG từng tiến trình / luồng: không ai ghi đè tệp tạm của ai
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---- devices ----
def get_devices():
    _ensure(); return _read(DEVICES_FILE)


def get_devices_strict():
    _ensure(); return _read_strict(DEVICES_FILE)


@_locked
def save_devices(devices):
    _ensure(); _write(DEVICES_FILE, devices); return devices


@_locked
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


@_locked
def delete_device(name):
    devs = [d for d in get_devices() if d.get("name") != name]
    return save_devices(devs)


@_locked
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


# ---- settings (dict) ----
def get_settings():
    _ensure()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@_locked
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
# group = {id, name, devices:[board_name...] (một máy có thể ở NHIỀU nhóm), created, updated,
#          scripts:[{id, name, steps:[...], mode:"once"|"loop"|"orders", loops:int, orders:{…}}]}
# Cách chạy nằm TRONG kịch bản (1 lần / lặp N vòng / nhận đơn từ gateway); một máy chỉ chạy một kịch bản một lúc (runner giữ chỗ theo tên máy).
# Kịch bản NHẬN ĐƠN mang khối `orders` = {pool, steps:{login:[],otp:[],nav:[],purchase:[],after:[],finish:[]}, login_wait, purchase_wait,
# check_keyboard, gw_steps_copied, gw_copied_phases}. Bước của một đơn CHỈ soạn ở đây (gateway không còn soạn bước); `gw_steps_copied` = đã
# chép một lần các bước đời cũ còn lưu ở pool trên gateway vào kịch bản, `gw_copied_phases` = những giai đoạn lần chép đó đã điền (sổ riêng
# của backend — giao diện không cần gửi lại; xem adopt_gateway_steps, save_group).
def api_defaults(api=None):
    """Chuẩn hoá khối cấu hình nhận đơn `orders` của kịch bản (thiếu gì bù mặc định)."""
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
    api["gw_steps_copied"] = api.get("gw_steps_copied") is True
    filled = api.get("gw_copied_phases")
    api["gw_copied_phases"] = [ph for ph in API_PHASES if isinstance(filled, list) and ph in filled]
    return api


def norm_scripts(group):
    """Chuẩn hoá danh sách kịch bản của nhóm. MỖI kịch bản tự mang cách chạy của nó:
         {id, name, steps:[...], mode:"once"|"loop"|"orders", loops:int (chỉ khi lặp; 0 = vô hạn)}.
    Cách chạy «orders» = KỊCH BẢN NHẬN ĐƠN từ gateway: máy đứng chờ → gateway có đơn → tool giữ chỗ (xin đơn) cho máy → chạy các bước theo
    giai đoạn của đơn. Cấu hình nằm ở khoá `orders` (pool + bước từng giai đoạn + thời gian chờ) và được giữ lại cả khi kịch bản tạm chuyển
    sang cách chạy khác.
    Dữ liệu đời cũ được đổi NGAY KHI ĐỌC (lần lưu kế tiếp ghi lại dạng mới):
      • nhóm chỉ có `steps`, chưa có khoá `scripts` → 1 kịch bản «Kịch bản 1» (id cố định «k1»; chạy theo `mode`/`loops` cũ của nhóm);
      • NHÓM NHẬN ĐƠN kiểu cũ (`mode: "api"` + khối `api` của nhóm) → thêm 1 kịch bản nhận đơn «Nhận đơn» (id cố định «don») mang đúng cấu hình đó.
    Có khoá `scripts` (kể cả rỗng) thì danh sách đó là chuẩn — không dựng lại từ `steps` cũ. Sau khi chuẩn hoá nhóm KHÔNG còn `steps` /
    `active_script` / `mode` / `loops` / `api`: cách chạy chỉ nằm trong kịch bản."""
    raw = group.get("scripts")
    legacy_orders = group.get("mode") == "api"
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
    if legacy_orders:
        sid = "don"
        while sid in seen:                      # id phải Y HỆT ở mọi lần đọc (trước khi nhóm được lưu lại) → nối thêm «1», không lấy ngẫu nhiên
            sid += "1"
        scripts.append({"id": sid, "name": "Nhận đơn", "steps": [], "mode": "orders", "loops": 1, "orders": api_defaults(group.get("api"))})
    group["scripts"] = scripts
    for old in ("steps", "active_script", "mode", "loops", "api"):
        group.pop(old, None)
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


@_locked
def save_group(group):
    _ensure()
    groups = get_groups()
    if not group.get("id"):
        group["id"] = uuid.uuid4().hex[:8]
        group["created"] = time.time()
    norm_scripts(group)
    group.setdefault("devices", [])
    # Bản gửi lên có thể CŨ HƠN lần chép bước đời cũ từ gateway (trình sửa giữ bản sao của nhóm; việc chép diễn ra ở backend): kịch bản đã lưu
    # mang dấu «đã chép» mà bản gửi lên thì chưa → người sửa chưa hề thấy các bước vừa chép. Khi đó dấu được giữ, và CHỈ những giai đoạn lần
    # chép đã điền (gw_copied_phases) mà bản gửi lên còn để trống mới lấy theo bản đã lưu — giai đoạn khác người dùng xoá trống thì trống thật.
    was = {s["id"]: s for g in groups if g["id"] == group["id"] for s in g["scripts"] if "orders" in s}
    for s in group["scripts"]:
        old = was.get(s["id"])
        if not (old and "orders" in s):
            continue
        saved, new = old["orders"], s["orders"]
        if saved["gw_steps_copied"] and not new["gw_steps_copied"]:
            new["gw_steps_copied"] = True
            for ph in saved["gw_copied_phases"]:
                if not new["steps"][ph]:
                    new["steps"][ph] = saved["steps"][ph]
        if new["gw_steps_copied"] and not new["gw_copied_phases"]:
            new["gw_copied_phases"] = saved["gw_copied_phases"]          # sổ của backend: bản gửi lên không mang theo thì giữ cái đang có
    group["updated"] = time.time()
    for i, g in enumerate(groups):
        if g["id"] == group["id"]:
            groups[i] = group
            break
    else:
        groups.append(group)
    _write(GROUPS_FILE, groups)
    return group


@_locked
def adopt_gateway_steps(group_id, script_id, legacy, bad=None):
    """CHÉP MỘT LẦN các bước đời cũ còn lưu ở pool trên gateway vào kịch bản nhận đơn. `legacy` = {giai đoạn: [bước dạng của tool]};
    `bad` = {giai đoạn: lời báo} cho giai đoạn mà bước đời cũ SAI DẠNG (không đổi được).
    Chỉ điền giai đoạn mà kịch bản đang TRỐNG, rồi đánh dấu `orders.gw_steps_copied` — từ đó không bao giờ chép lại (người dùng xoá hết bước
    của một giai đoạn thì nó trống thật). Kịch bản đang trống đúng một giai đoạn sai dạng → KHÔNG chép gì, không đánh dấu (`blocked`): trước
    đây máy từ chối chạy trong trường hợp đó, không được lặng lẽ chạy thiếu một giai đoạn.
    Trả None nếu nhóm không có kịch bản nhận đơn đó; ngược lại {"copied": {giai đoạn: số bước vừa chép}, "blocked": {giai đoạn: lời báo},
    "already": đã chép từ trước (không ghi gì)}."""
    groups = get_groups()
    g = next((x for x in groups if x["id"] == group_id), None)
    sc = next((s for s in (g or {}).get("scripts", []) if s["id"] == script_id), None)
    if sc is None or sc.get("mode") != "orders":
        return None
    o = sc["orders"]
    if o["gw_steps_copied"]:
        return {"copied": {}, "blocked": {}, "already": True}
    blocked = {ph: str(msg) for ph, msg in (bad or {}).items() if ph in API_PHASES and not o["steps"][ph]}
    if blocked:
        return {"copied": {}, "blocked": blocked, "already": False}
    copied = {}
    for ph in API_PHASES:
        add = [dict(s) for s in (legacy.get(ph) or []) if isinstance(s, dict) and s.get("type")]
        if add and not o["steps"][ph]:
            o["steps"][ph] = add
            copied[ph] = len(add)
    o["gw_steps_copied"] = True
    o["gw_copied_phases"] = list(copied)
    g["updated"] = time.time()
    _write(GROUPS_FILE, groups)
    return {"copied": copied, "blocked": {}, "already": False}


@_locked
def delete_group(group_id):
    groups = [g for g in get_groups() if g["id"] != group_id]
    _write(GROUPS_FILE, groups)
    return True


def groups_of_device(name):
    """Mọi nhóm (list dict) có máy `name` — một máy có thể ở NHIỀU nhóm."""
    return [g for g in get_groups() if name in g.get("devices", [])]


@_locked
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


@_locked
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


@_locked
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
