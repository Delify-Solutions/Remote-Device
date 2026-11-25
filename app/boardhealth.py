"""
boardhealth.py — sức khoẻ của board ESP32: đọc (lệnh `status` / `info` của firmware v2), đánh giá, tự phục hồi.

Firmware v2 trả về RAM trống / đáy RAM, thời gian chạy, lý do reset lần trước, số lần BLE rớt, lỗi serial, nhiệt độ
(thô) — đủ để biết board sắp đơ TRƯỚC khi nó làm hỏng một lệnh, và để biết nó vừa tự reset vì sao (sụt nguồn USB,
watchdog, lỗi chương trình). Firmware cũ (v1) chỉ có «ble=…» → vẫn đọc được, chỉ không có số liệu.

Chỉ dùng để nhìn và để phục hồi LÚC RẢNH (trước khi nhận đơn, hay khi board đã im): reset là mất kết nối BLE vài giây,
nên KHÔNG BAO GIỜ gọi `recover()` giữa lúc một đơn / một thao tác đang chạy.
"""
from __future__ import annotations
import re
import time

# ---- ngưỡng ----
HEAP_WARN, HEAP_BAD = 40_000, 24_000        # RAM trống (byte). BLE Bluedroid ăn nhiều: bình thường còn ~100–170 KB
FLOOR_WARN = 20_000                          # đáy thấp nhất từ lúc bật: từng suýt cạn
BLOCK_WARN = 16_000                          # mảng liền lớn nhất nhỏ = RAM bị phân mảnh
TEMP_WARN, TEMP_BAD = 80.0, 95.0             # °C — cảm biến nội của ESP32 chỉ cho số THÔ, lệch nhiều; chỉ để thấy xu hướng nóng
TEMP_STUCK = 53.3                            # ESP32 gốc (D0WD) luôn trả đúng 53.3 °C: không có cảm biến thật → bỏ qua, đừng tin
RECENT_RESET_S = 900                         # lý do reset chỉ đáng báo khi board mới khởi động lại (≤ 15 phút)
DROP_PER_HOUR = 6                            # BLE rớt nhiều hơn bấy nhiêu lần mỗi giờ (và ≥ 3 lần) = bất thường

_INT = ("fw", "up", "heap", "min", "blk", "rxerr", "ovf", "drop", "cmds", "rev", "cores", "mhz")
_ORDER = {"ok": 0, "info": 1, "warn": 2, "bad": 3}


def temp_of(h: dict | None) -> float | None:
    """Nhiệt độ thô nếu đáng tin; None nếu chip không có cảm biến thật (giá trị kẹt cứng 53.3)."""
    t = (h or {}).get("temp")
    return None if t is None or abs(t - TEMP_STUCK) < 0.15 else t


def _kv(line: str, prefix: str) -> dict | None:
    if not line or not line.startswith(prefix):
        return None
    d = {}
    for tok in line[len(prefix):].split():
        k, eq, v = tok.partition("=")
        if not eq:
            continue
        if k in _INT:
            try:
                d[k] = int(v)
            except ValueError:
                pass
        elif k == "temp":
            try:
                d[k] = float(v)
            except ValueError:
                pass
        else:
            d[k] = v
    return d


def parse_status(line: str) -> dict | None:
    """«OK ble=connected fw=2 up=95 heap=180000 …» → dict. None nếu không phải dòng status. Firmware cũ → chỉ có ble, fw=1."""
    if not line or not line.startswith("OK ble="):
        return None
    d = _kv(line, "OK ") or {}
    d["connected"] = d.get("ble") == "connected"
    d.setdefault("fw", 1)
    return d


def parse_info(line: str) -> dict | None:
    return _kv(line, "OK info ")


def assess(h: dict | None) -> list:
    """Đánh giá một bản status đã parse → danh sách phát hiện [{level, code, text, reset}], nặng nhất đứng đầu.
    `reset=True` = khởi động lại board thì khá hơn (thiếu RAM, phân mảnh); sụt nguồn thì reset không giúp được gì."""
    if not h:
        return [{"level": "bad", "code": "silent", "text": "Board không trả lời lệnh status", "reset": True}]
    out = []

    def add(level, code, text, reset=False):
        out.append({"level": level, "code": code, "text": text, "reset": reset})
    if h.get("fw", 1) < 2:
        add("info", "old_fw", "Firmware cũ — chưa báo được RAM / nhiệt độ / lý do reset. Nạp lại firmware để dùng đủ tính năng.")
        return out
    heap, floor, blk = h.get("heap"), h.get("min"), h.get("blk")
    if heap is not None and heap < HEAP_BAD:
        add("bad", "heap_low", "RAM trống chỉ còn %d KB — board sắp đơ, nên khởi động lại" % (heap // 1024), True)
    elif heap is not None and heap < HEAP_WARN:
        add("warn", "heap_low", "RAM trống thấp (%d KB)" % (heap // 1024), True)
    if floor is not None and floor < FLOOR_WARN and not (heap is not None and heap < HEAP_WARN):
        add("warn", "heap_floor", "RAM từng tụt xuống chỉ còn %d KB từ lúc bật (có lúc suýt cạn)" % (floor // 1024))
    if blk is not None and heap is not None and blk < BLOCK_WARN and heap >= HEAP_WARN:
        add("warn", "heap_frag", "RAM bị phân mảnh (mảng liền lớn nhất chỉ %d KB)" % (blk // 1024), True)
    t = temp_of(h)
    if t is not None and t >= TEMP_BAD:
        add("bad", "hot", "Chip rất nóng (%.0f °C thô) — kiểm tra thông gió / nguồn" % t)
    elif t is not None and t >= TEMP_WARN:
        add("warn", "hot", "Chip nóng (%.0f °C thô)" % t)
    up, rst = h.get("up"), h.get("rst")
    recent = up is not None and up <= RECENT_RESET_S
    if recent and rst == "brownout":
        add("bad", "brownout", "Board vừa tự reset vì SỤT NGUỒN — đổi cáp USB / cổng / dùng hub có nguồn riêng")
    elif recent and rst in ("panic", "int_wdt", "task_wdt", "wdt"):
        add("warn", "crash", "Board vừa tự reset vì lỗi / bị đơ (%s)" % rst)
    if h.get("rxerr", 0) > 0:
        add("warn", "rxerr", "Cổng serial từng bị tràn / lỗi khung %d lần (cáp kém, hoặc gửi lệnh quá dồn)" % h["rxerr"])
    drops = h.get("drop", 0)
    if drops >= 3 and up and drops / max(up / 3600.0, 0.1) > DROP_PER_HOUR:
        add("warn", "ble_drops", "BLE rớt %d lần trong %d phút (iPhone ở xa? Bluetooth chập chờn?)" % (drops, max(1, up // 60)))
    out.sort(key=lambda f: -_ORDER[f["level"]])
    return out


def level_of(findings: list) -> str:
    return max((f["level"] for f in findings), key=_ORDER.__getitem__, default="ok")


def summary(h: dict | None) -> str:
    """Một dòng cho người đọc: «RAM 142 KB (đáy 118) · chạy 3 giờ · 47 °C · reset: poweron · BLE rớt 0»."""
    if not h:
        return "không trả lời"
    if h.get("fw", 1) < 2:
        return "firmware cũ (BLE %s)" % ("đã nối" if h.get("connected") else "chưa nối")
    up = h.get("up", 0)
    upt = "%d giờ" % (up // 3600) if up >= 3600 else ("%d phút" % (up // 60) if up >= 60 else "%d giây" % up)
    return "RAM %d KB (đáy %d) · chạy %s · %s · reset: %s · BLE rớt %d%s" % (
        h.get("heap", 0) // 1024, h.get("min", 0) // 1024, upt,
        ("%.0f °C" % temp_of(h)) if temp_of(h) is not None else "— °C (chip không có cảm biến thật)", h.get("rst", "?"), h.get("drop", 0),
        " · lỗi serial %d" % h["rxerr"] if h.get("rxerr") else "")


def view(status_line: str) -> dict | None:
    """Cho giao diện: {level, summary, notes[], fw} từ MỘT dòng status; None nếu không phải dòng status."""
    h = parse_status(status_line or "")
    if h is None:
        return None
    f = assess(h)
    return {"level": level_of(f), "summary": summary(h), "notes": [x["text"] for x in f], "fw": h.get("fw", 1)}


def read(hands) -> dict | None:
    """Hỏi board và đánh giá. Trả {**status, findings, level, summary} hoặc None nếu board im."""
    h = parse_status(str(hands.send("status") or ""))
    if h is None:
        return None
    f = assess(h)
    h.update(findings=f, level=level_of(f), summary=summary(h))
    return h


def alive(hands, tries: int = 2) -> bool:
    return any(str(hands.send("ping", wait=0.6)) == "pong" for _ in range(max(1, tries)))


def _wait_alive(hands, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if alive(hands, 1):
            return True
        time.sleep(0.3)
    return False


def hard_reset(hands, boot_wait: float = 10.0) -> bool:
    """Reset CỨNG bằng chân EN qua RTS của mạch USB-serial (DTR giữ thấp để board vào chế độ chạy, không vào chế độ nạp).
    Dùng được cả khi firmware đã đơ hẳn. Trả True khi board trả lời lại."""
    hands.ser.dtr = False
    hands.ser.rts = True
    time.sleep(0.12)
    hands.ser.rts = False
    time.sleep(1.5)
    hands._rx = b""
    try:
        hands.ser.reset_input_buffer()
    except Exception:
        pass
    return _wait_alive(hands, boot_wait)


def soft_reset(hands, boot_wait: float = 10.0) -> bool:
    """Lệnh `reset` của firmware (board còn phản hồi). Trả True khi board khởi động xong và trả lời lại."""
    hands.send("reset", wait=0.8)
    time.sleep(1.5)
    hands._rx = b""
    try:
        hands.ser.reset_input_buffer()
    except Exception:
        pass
    return _wait_alive(hands, boot_wait)


def recover(hands, allow_reset: bool = True, ble_wait: float = 20.0, log=lambda s: None) -> dict:
    """Đưa board về trạng thái dùng được, LÚC RẢNH. Trả {ok, alive, level, actions, health}.
      1. board im → reset cứng (nếu được phép);
      2. board sống nhưng đang thiếu RAM / phân mảnh → reset mềm sớm, trước khi nó đơ giữa một lệnh;
      3. sau reset → chờ iPhone nối lại BLE."""
    actions = []
    reset_done = False
    if not alive(hands):
        if not allow_reset:
            return {"ok": False, "alive": False, "level": "bad", "actions": actions, "health": None}
        log("board không trả lời → reset cứng")
        actions.append("reset cứng (board không trả lời)")
        reset_done = True
        if not hard_reset(hands):
            return {"ok": False, "alive": False, "level": "bad", "actions": actions, "health": None}
    health = read(hands)
    if allow_reset and not reset_done and health and any(f["reset"] and f["level"] in ("warn", "bad") for f in health["findings"]):
        why = next(f["text"] for f in health["findings"] if f["reset"])
        log("khởi động lại board sớm: " + why)
        actions.append("reset mềm (%s)" % why)
        reset_done = True
        if not soft_reset(hands):
            return {"ok": False, "alive": False, "level": "bad", "actions": actions, "health": None}
        health = read(hands)
    ble_back = True
    if reset_done and not (health and health.get("connected")):
        if hands.wait_connected(ble_wait):
            health = read(hands) or health
        else:
            ble_back = False
            actions.append("iPhone chưa nối lại BLE sau reset")
    lvl = (health or {}).get("level", "bad")
    # Reset xong mà iPhone chưa nối lại BLE thì board CHƯA dùng được (nhận đơn lúc này = không bấm được gì → đơn hỏng oan)
    return {"ok": bool(health) and lvl != "bad" and ble_back, "alive": True, "level": lvl, "actions": actions, "health": health}
