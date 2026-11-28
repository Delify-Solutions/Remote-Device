#!/usr/bin/env python3
"""
Kiểm GIAO DIỆN KHỞI ĐỘNG TRỌN VẸN: nạp đủ các tệp JS của trang (_mock.js giả API + mọi tệp trong các thẻ <script src> của index.html, đúng
thứ tự nạp: core.js … main.js) trong `node`, với một DOM giả
«cái gì cũng có», chạy hàm khởi động init() và mở từng trang, rồi kiểm KHÔNG CÓ lỗi «gọi hàm / biến không tồn tại» (ReferenceError).

Vì sao cần: các bài test giao diện khác chỉ lấy riêng từng hàm trong các tệp JS ra chạy. Lỗi ở cấp cả trang — vd xoá một hàm mà chỗ khác còn gọi —
làm init() dừng giữa chừng và nửa số nút không còn tác dụng mà không bài nào bắt được (verify 2026-11-28: xoá nhầm loadAiScreen).

Sau đó mở KỊCH BẢN NHẬN ĐƠN của nhóm mẫu (cả trình sửa chạy trên DOM giả) và kiểm việc chép MỘT LẦN bước đời cũ từ gateway vào kịch bản:
lúc mở kịch bản, lúc bấm chạy (backend chép rồi trả bản mới của nhóm), sau khi lưu; đang sửa dở / đang mở hộp thoại thì không nạp đè.

    ./.venv/bin/python app/tests/test_ui_boot.py        (cần lệnh `node`; không có thì bỏ qua)
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_ui_controls import page_scripts

WEB = os.path.join(os.path.dirname(HERE), "web")
PASS = FAIL = 0

HARNESS = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const WEB = process.argv[process.argv.length - 2];
const FILES = JSON.parse(process.argv[process.argv.length - 1]);     // các tệp JS của trang, đúng thứ tự nạp (xem main: đọc từ thẻ <script src>)
const errors = [];
// DOM giả: mọi thuộc tính / lời gọi trả về chính nó (đọc gì cũng có, gọi gì cũng được), trừ vài thứ cần đúng kiểu.
function any(name) {
  const fn = function () {};
  const store = {};
  return new Proxy(fn, {
    get(t, k) {
      if (k in store) return store[k];
      if (k === "then") return undefined;                       // không phải promise
      if (k === Symbol.iterator) return function* () {};
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "length" || k === "childElementCount") return 0;
      if (k === "value" || k === "textContent" || k === "innerHTML" || k === "id" || k === "className") return "";
      if (k === "dataset" || k === "style") return (store[k] = {});
      if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
      if (k === "querySelectorAll" || k === "getElementsByClassName" || k === "getElementsByTagName") return () => [];
      if (k === "checked" || k === "disabled" || k === "hidden") return false;
      if (k === "options") return [];
      return any(name + "." + String(k));
    },
    set(t, k, v) { store[k] = v; return true; },
    apply() { return any(name + "()"); },
    construct() { return any("new " + name); },
  });
}
const listeners = {};
const docProxy = any("document");
const modal = any("modal"); modal.hidden = true;                // hộp thoại nhập liệu: đang đóng (phần tử duy nhất giữ trạng thái giữa các lần hỏi)
const document = new Proxy({}, {
  get(t, k) {
    if (k === "querySelector" || k === "getElementById") return (s) => s === "#modal" ? modal : any("el");
    if (k === "querySelectorAll") return () => [];
    if (k === "addEventListener") return (ev, f) => { (listeners["doc:" + ev] = listeners["doc:" + ev] || []).push(f); };
    if (k === "createElement") return () => any("created");
    return docProxy[k];
  },
});
const store = {};
const win = {
  document, console, Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Map, Set, WeakMap, Symbol, Error, Proxy,
  parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent, structuredClone: (x) => JSON.parse(JSON.stringify(x)),
  setTimeout, clearTimeout, setInterval: (f, ms) => 0, clearInterval: () => {}, requestAnimationFrame: (f) => setTimeout(f, 0),
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  location: { hash: "", href: "http://127.0.0.1/", reload() {}, search: "" },
  history: { pushState() {}, replaceState() {} },
  navigator: { clipboard: { writeText: async () => {} }, userAgent: "node" },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  CSS: { escape: (s) => String(s) }, Event: function (t) { this.type = t; }, CustomEvent: function (t) { this.type = t; },
  bootstrap: new Proxy({}, { get: () => function () { return any("bs"); } }),
  getComputedStyle: () => any("style"), scrollTo() {}, alert() {}, confirm: () => false, prompt: () => null,
  addEventListener: (ev, f) => { (listeners["win:" + ev] = listeners["win:" + ev] || []).push(f); },
  removeEventListener() {}, dispatchEvent: (e) => { (listeners["win:" + (e && e.type)] || []).forEach(f => f(e)); return true; },
  fetch: async () => ({ ok: false, json: async () => ({}) }), Image: function () { return any("img"); }, URL, Blob: function () {},
};
win.window = win; win.self = win; win.globalThis = win;
const ctx = vm.createContext(win);
const fmt = (e) => (e && e.stack ? e.stack.split("\n").slice(0, 2).join(" | ") : String(e));
process.on("unhandledRejection", (e) => errors.push("unhandledRejection: " + fmt(e)));
process.on("uncaughtException", (e) => errors.push("uncaughtException: " + fmt(e)));      // lỗi trong hàm hẹn giờ (vd init gọi từ pywebviewready)
for (const f of FILES) {
  try { new vm.Script(fs.readFileSync(path.join(WEB, f), "utf8"), { filename: f }).runInContext(ctx); }
  catch (e) { errors.push("load " + f + ": " + (e && e.stack ? e.stack.split("\n").slice(0, 2).join(" | ") : e)); }
}
(listeners["doc:DOMContentLoaded"] || []).forEach(f => { try { f(); } catch (e) { errors.push("DOMContentLoaded: " + e.stack.split("\n").slice(0, 2).join(" | ")); } });
const run = (label, src) => { try { return new vm.Script(src, { filename: label }).runInContext(ctx); } catch (e) { errors.push(label + ": " + e.stack.split("\n").slice(0, 2).join(" | ")); return null; } };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const snap = (label) => JSON.parse(run(label, "__snap()") || "null");
(async () => {
  await sleep(200);
  run("init", "init()");
  await sleep(600);
  for (const v of ["overview", "devices", "esp", "flows", "monitor", "ai", "alerts", "wallets"]) run("showView(" + v + ")", `showView(${JSON.stringify(v)})`);
  await sleep(600);

  // ---- kịch bản nhận đơn của nhóm mẫu (g2 / «don»): chép một lần bước đời cũ từ gateway ----
  const flow = {};
  run("flow-setup", `
    var __T = [], __CALLS = [];
    (() => {
      const toast0 = toast; toast = function (m, k) { __T.push(String(m)); return toast0(m, k); };
      const api = window.pywebview.api;
      for (const n of ["orders_adopt", "group_run", "group_save"]) { const f = api[n]; api[n] = function () { __CALLS.push(n); return f.apply(api, arguments); }; }
      window.confirm = () => true;
    })();
    function __snap() {
      const sc = currentScript(), saved = (GROUPS.find(g => g.id === "g2") || { scripts: [] }).scripts.find(x => sc && x.id === sc.id);
      return JSON.stringify({ sub: GROUP_SUB, sid: EDIT_SID, dirty: groupDirty(), calls: __CALLS.splice(0), toasts: __T.splice(0),
        flag: sc && sc.orders.gw_steps_copied, counts: sc && API_PHASES.map(([k]) => sc.orders.steps[k].length), first: sc && API_PHASES.map(([k]) => (sc.orders.steps[k][0] || {}).type || ""),
        savedFlag: saved && saved.orders.gw_steps_copied });
    }
    function __add(id, steps) { GROUP.scripts.push({ id, name: id, steps: [], mode: "orders", loops: 1, orders: normApi({ pool: "efootball-ios", steps }) }); openScript(id, false); }
    showView("flows");`);
  await sleep(700);
  run("flow-open", `openGroup("g2", false, "don")`);            // 1. mở kịch bản (nhóm không có thay đổi chưa lưu) → hỏi backend chép
  await sleep(700);
  flow.open = snap("flow-open");
  run("flow-run", `__add("moi", {}); var __snap0 = __snap(); runScript(null)`);     // 2. kịch bản mới đang sửa dở: không hỏi; bấm chạy → backend chép, trả bản mới
  flow.dirty = JSON.parse(run("flow-run", "__snap0") || "null");
  await sleep(800);
  flow.run = snap("flow-run");
  run("flow-save", `__add("ba", { login: [{ type: "home" }] }); saveGroup(null)`);    // 3. sửa dở rồi lưu → sau khi lưu mới hỏi; giai đoạn đã có bước thì giữ nguyên
  await sleep(800);
  flow.save = snap("flow-save");
  // 4. đang mở hộp thoại sửa bước lúc backend trả lời → không nạp đè bản đang sửa (GROUPS vẫn nhận bản mới)
  run("flow-modal", `currentScript().orders.gw_steps_copied = false; GROUP_SNAP = groupState(); document.querySelector("#modal").hidden = false; adoptGwSteps()`);
  await sleep(400);
  flow.modal = snap("flow-modal");
  process.stdout.write(JSON.stringify({ errors, flow }));
  process.exit(0);
})();
"""


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def main():
    node = shutil.which("node")
    if not node:
        print("  (BỎ QUA: máy không có node)")
        return 0
    # Nạp đúng các tệp của trang THẬT (thẻ <script src> của index.html, đúng thứ tự), đứng trước là _mock.js giả API — như trang thử _test.html.
    # Thêm / bớt một tệp JS của trang thì bài này tự theo; hai trang lệch danh sách tệp thì dừng ngay ở đây chứ không kiểm trên bản lệch.
    files = ["_mock.js"] + page_scripts()
    assert page_scripts("_test.html") == files, "_test.html phải nạp _mock.js rồi ĐÚNG các tệp JS của index.html, cùng thứ tự: %s ≠ %s" % (page_scripts("_test.html"), files)
    files_arg = json.dumps(files)
    print("== Khởi động cả trang (init + mở từng trang) ==")
    r = subprocess.run([node, "-e", HARNESS, WEB, files_arg], capture_output=True, text=True, timeout=60)
    try:
        res = json.loads(r.stdout)                      # không in ra gì (node sập) = HỎNG, không phải «không có lỗi»
        errs, flow = res["errors"], res["flow"]
    except Exception:
        errs, flow = ["load: không đọc được kết quả (node thoát mã %s): %s %s" % (r.returncode, r.stdout[-300:], r.stderr[-400:])], {}
    refs = [e for e in errs if "ReferenceError" in e or "is not defined" in e or e.startswith("load ")]
    ok(not refs, "không có hàm / biến nào bị gọi mà không tồn tại, không tệp JS nào nạp lỗi", refs)
    syntax = [e for e in errs if "SyntaxError" in e]
    ok(not syntax, "không có lỗi cú pháp", syntax)
    names = ["loadAiScreen", "loadTelegram", "alertsBadge", "loadAlerts", "renderTelegram", "renderAiProviders", "showView", "init", "paintProgress", "runFrom", "loadWallets", "renderWallets", "walletEdit",
             "adoptGwSteps", "applyAdopted"]
    # kiểm ở phía node (không qua vm.run): hàm khai báo kiểu `function x()` ở cấp tệp là thuộc tính của ngữ cảnh vm
    probe = HARNESS.replace("(async () => {\n  await sleep(200);",
                            "process.stdout.write('MISSING[' + %s.filter(n => typeof ctx[n] !== 'function').join(',') + ']\\n');\nprocess.exit(0);\n(async () => {\n  await sleep(200);" % json.dumps(names), 1)
    assert probe != HARNESS, "không chèn được phép kiểm tên hàm"
    r2 = subprocess.run([node, "-e", probe, WEB, files_arg], capture_output=True, text=True, timeout=60)
    line = next((ln for ln in (r2.stdout or "").splitlines() if ln.startswith("MISSING[")), None)
    missing = [n for n in line[len("MISSING["):].rstrip("]").split(",") if n] if line else None
    ok(missing == [], "các hàm chính của trang đều có: " + ", ".join(names), missing if missing is not None else (r2.stdout[-200:], r2.stderr[-200:]))

    print("== Kịch bản nhận đơn: chép một lần bước đời cũ từ gateway ==")
    ok(not errs, "mở nhóm + trình sửa kịch bản nhận đơn, chạy, lưu: không lỗi nào", errs)
    tail = " — từ giờ sửa bước ở đây"
    o = flow.get("open") or {}
    ok(o.get("calls") == ["orders_adopt"] and o.get("flag") is True and o.get("savedFlag") is True and o.get("counts") == [7, 0, 2, 2, 1, 2] and (o.get("first") or [""] * 4)[3] == "tap",
       "mở kịch bản nhận đơn chưa chép → hỏi backend đúng MỘT lần; giai đoạn trống nhận bước cũ, giai đoạn đã có bước giữ nguyên bước của mình; đánh dấu đã chép", o)
    ok(o.get("sub") == "script" and o.get("sid") == "don" and o.get("dirty") is False
       and o.get("toasts") == ["Đã chép 12 bước cũ từ gateway vào kịch bản (Đăng nhập: 7, Vào danh sách gói: 2, Sau mỗi lần mua: 1, Kết thúc đơn: 2)" + tail],
       "nạp lại nhóm từ bản backend trả về mà vẫn ở đúng trình sửa kịch bản đó, không thành «có thay đổi chưa lưu»; báo một lần số bước đã chép", o)
    d = flow.get("dirty") or {}
    ok(d.get("sid") == "moi" and d.get("dirty") is True and d.get("calls") == [] and d.get("flag") is False, "nhóm đang có thay đổi chưa lưu → KHÔNG hỏi backend chép", d)
    rn = flow.get("run") or {}
    ok(rn.get("calls") == ["group_save", "group_run"] and rn.get("flag") is True and rn.get("counts") == [7, 0, 2, 2, 1, 2] and rn.get("sid") == "moi" and rn.get("sub") == "script"
       and rn.get("dirty") is False and (rn.get("toasts") or [""])[0] == "Đã chép 14 bước cũ từ gateway vào kịch bản (Đăng nhập: 7, Vào danh sách gói: 2, Mua một gói: 2, Sau mỗi lần mua: 1, Kết thúc đơn: 2)" + tail,
       "bấm chạy: backend chép ngay trước khi chạy và trả bản mới của nhóm → trình sửa nạp lại bản đó (lần lưu sau không ghi đè mất bước vừa chép) + báo số bước", rn)
    sv = flow.get("save") or {}
    ok(sv.get("calls") == ["group_save", "orders_adopt"] and sv.get("flag") is True and sv.get("counts") == [1, 0, 2, 2, 1, 2] and (sv.get("first") or [""])[0] == "home" and sv.get("dirty") is False
       and sv.get("toasts") == ["Đã lưu kịch bản: ba", "Đã chép 7 bước cũ từ gateway vào kịch bản (Vào danh sách gói: 2, Mua một gói: 2, Sau mỗi lần mua: 1, Kết thúc đơn: 2)" + tail],
       "sửa dở rồi bấm Lưu → lưu xong mới hỏi backend chép; giai đoạn người dùng đã soạn không bị đụng tới", sv)
    md = flow.get("modal") or {}
    ok(md.get("calls") == ["orders_adopt"] and md.get("flag") is False and md.get("savedFlag") is True and md.get("toasts") == [] and md.get("sid") == "ba",
       "backend trả lời lúc đang mở hộp thoại sửa bước → không nạp đè bản đang sửa (danh sách nhóm vẫn nhận bản mới)", md)
    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
