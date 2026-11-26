#!/usr/bin/env python3
"""
Kiểm BỘ NÚT điều khiển một máy trên giao diện (app/web/app.js → runControlsHtml) — không cần trình duyệt, không cần phần cứng.
Lấy đúng mã nguồn các hàm từ app.js, chạy bằng `node` trên MỌI tổ hợp trạng thái của máy, rồi kiểm:
  • không trạng thái nào «không có nút» (luôn có đường ra);
  • không bao giờ hiện cùng lúc «Dừng máy / Tạm dừng» và «Tiếp tục»;
  • máy đang nghỉ → «Dừng máy»; đang dừng để xử lý tay → «Tiếp tục»; đang chạy → «Tạm dừng» + «Dừng»;
  • máy đang GIỮ chờ kiểm tra → «Đã kiểm tra xong»; nếu đồng thời đang dừng để xử lý tay thì CÓ CẢ «Tiếp tục»
    (không có nút này thì «Chạy lại» của nhóm nhận đơn bị từ chối mà không gỡ được);
  • tên máy lạ không chèn được mã HTML.

    ./.venv/bin/python app/tests/test_ui_controls.py        (cần lệnh `node`; không có thì bỏ qua)
"""
from __future__ import annotations
import itertools, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_JS = os.path.join(os.path.dirname(HERE), "web", "app.js")
PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def function_source(src: str, name: str) -> str:
    """Mã nguồn nguyên văn của `function <name>(…) {…}` trong app.js (đếm ngoặc nhọn, bỏ qua chuỗi và chú thích)."""
    start = src.index("function %s(" % name)
    i = src.index("{", src.index(")", start))
    depth, quote, k = 0, None, i
    while k < len(src):
        ch = src[k]
        if quote:
            if ch == "\\":
                k += 2; continue
            if quote == "`" and ch == "$" and src[k + 1] == "{":      # ${…} trong chuỗi mẫu: nhảy qua biểu thức
                d = 1; k += 2
                while d:
                    if src[k] == "{": d += 1
                    elif src[k] == "}": d -= 1
                    k += 1
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "/" and src[k + 1] == "/":
            k = src.index("\n", k); continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:k + 1]
        k += 1
    raise ValueError("không tìm thấy hết hàm " + name)


def main():
    node = shutil.which("node")
    if not node:
        print("BỎ QUA: cần lệnh `node` để chạy mã giao diện.")
        return 0
    src = open(APP_JS, encoding="utf-8").read()
    funcs = "\n".join(function_source(src, n) for n in ("isHeld", "runControlsHtml", "devRunState"))
    esc_line = next(l for l in src.splitlines() if l.startswith("const esc ="))
    states = []
    for running, parked, paused, pause_req, stopping, mode, hold in itertools.product(
            (False, True), (False, True), (False, True), (False, True), (False, True), ("once", "api"), (None, "đơn T-9 cần đối soát")):
        if (paused or pause_req or stopping) and not running:
            continue                                  # các cờ này chỉ có khi máy đang chạy
        if hold and running:
            continue                                  # giữ chờ kiểm tra chỉ có khi máy đã dừng
        states.append({"running": running, "parked": parked, "paused": paused, "pause_requested": pause_req, "stopping": stopping, "mode": mode, "hold": hold})
    script = """
%s
%s
const states = %s;
const out = states.map(st => runControlsHtml("M1", st));
out.push(runControlsHtml("M1", undefined));                         // máy chưa có trạng thái gì
out.push(runControlsHtml('x"><img src=x onerror=1>', {running: false}));   // tên máy lạ
out.push(JSON.stringify(devRunState({running: 1, hold: null, parked: 1, paused: 0, pause_requested: 1, stopping: 0, run_mode: "api"})));
process.stdout.write(JSON.stringify(out));
""" % (esc_line, funcs, json.dumps(states, ensure_ascii=False))
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        ok(False, "chạy được mã giao diện bằng node", r.stderr[-400:]); return 1
    html = json.loads(r.stdout)
    rows = list(zip(states, html[:len(states)]))

    def has(h, attr):
        return ("data-%s=" % attr) in h

    print("== Bộ nút điều khiển một máy (%d trạng thái) ==" % len(rows))
    ok(all(any(has(h, a) for a in ("mpause", "mresume", "mstop", "mforce", "mack")) for _, h in rows), "trạng thái nào cũng có ít nhất một nút (luôn có đường ra)",
       [s for s, h in rows if not any(has(h, a) for a in ("mpause", "mresume", "mstop", "mforce", "mack"))][:2])
    ok(not any(has(h, "mpause") and has(h, "mresume") for _, h in rows), "không bao giờ hiện cùng lúc «Dừng máy / Tạm dừng» và «Tiếp tục»",
       [s for s, h in rows if has(h, "mpause") and has(h, "mresume")][:2])
    idle = [h for s, h in rows if not s["running"] and not s["hold"] and not s["parked"]]
    ok(idle and all(has(h, "mpause") and "Dừng máy" in h and not has(h, "mstop") and not has(h, "mack") for h in idle), "máy đang nghỉ → chỉ có «Dừng máy»")
    parked = [h for s, h in rows if not s["running"] and not s["hold"] and s["parked"]]
    ok(parked and all(has(h, "mresume") and "đang dừng" in h and not has(h, "mpause") for h in parked), "máy đang dừng để xử lý tay → nhãn «đang dừng» + «Tiếp tục»")
    held = [h for s, h in rows if s["hold"] and not s["parked"]]
    ok(held and all(has(h, "mack") and "Đã kiểm tra xong" in h and not has(h, "mresume") and not has(h, "mpause") for h in held), "máy đang giữ chờ kiểm tra → «Đã kiểm tra xong»")
    both = [h for s, h in rows if s["hold"] and s["parked"]]
    ok(both and all(has(h, "mack") and has(h, "mresume") for h in both),
       "máy VỪA đang giữ chờ kiểm tra VỪA đang dừng để xử lý tay → có cả «Đã kiểm tra xong» lẫn «Tiếp tục» (không thì «Chạy lại» không gỡ được)", both[:1])
    run_plain = [h for s, h in rows if s["running"] and not s["paused"] and not s["pause_requested"] and not s["stopping"]]
    ok(run_plain and all(has(h, "mpause") and has(h, "mstop") for h in run_plain), "máy đang chạy → «Tạm dừng» + «Dừng»")
    run_paused = [h for s, h in rows if s["running"] and (s["paused"] or s["pause_requested"])]
    ok(run_paused and all(has(h, "mresume") and not has(h, "mpause") and (has(h, "mstop") or has(h, "mforce")) for h in run_paused), "máy đang chạy mà đang / sắp tạm dừng → «Tiếp tục» + «Dừng»")
    api_stopping = [h for s, h in rows if s["running"] and s["stopping"] and s["mode"] == "api"]
    ok(api_stopping and all(has(h, "mforce") and "Dừng ngay" in h for h in api_stopping), "máy nhận đơn đang dừng dần → có «Dừng ngay»")
    ok(has(html[len(states)], "mpause"), "máy chưa có trạng thái gì (chưa từng chạy) → vẫn có «Dừng máy»")
    odd = html[len(states) + 1]
    ok("<img" not in odd and "&lt;img" in odd, "tên máy chứa mã HTML được vô hiệu hoá (không chèn được thẻ)", odd[:120])
    ok(json.loads(html[len(states) + 2]) == {"running": True, "hold": None, "parked": True, "paused": 0, "pause_requested": 1, "stopping": 0, "mode": "api"},
       "trạng thái lấy từ danh sách thiết bị (devRunState) mang đủ các cờ, kể cả «đang dừng»", html[len(states) + 2])

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
