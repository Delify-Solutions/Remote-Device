#!/usr/bin/env python3
"""
Kiểm GIAO DIỆN KHỞI ĐỘNG TRỌN VẸN: nạp đủ các tệp JS của trang (_mock.js giả API + app.js + ai.js + alerts.js) trong `node`, với một DOM giả
«cái gì cũng có», chạy hàm khởi động init() và mở từng trang, rồi kiểm KHÔNG CÓ lỗi «gọi hàm / biến không tồn tại» (ReferenceError).

Vì sao cần: các bài test giao diện khác chỉ lấy riêng từng hàm trong app.js ra chạy. Lỗi ở cấp cả trang — vd xoá một hàm mà chỗ khác còn gọi —
làm init() dừng giữa chừng và nửa số nút không còn tác dụng mà không bài nào bắt được (verify 2026-11-28: xoá nhầm loadAiScreen).

    ./.venv/bin/python app/tests/test_ui_boot.py        (cần lệnh `node`; không có thì bỏ qua)
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")
PASS = FAIL = 0

HARNESS = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const WEB = process.argv[process.argv.length - 1];
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
const document = new Proxy({}, {
  get(t, k) {
    if (k === "querySelector" || k === "getElementById") return () => any("el");
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
for (const f of ["_mock.js", "app.js", "ai.js", "alerts.js", "wallets.js"]) {
  try { new vm.Script(fs.readFileSync(path.join(WEB, f), "utf8"), { filename: f }).runInContext(ctx); }
  catch (e) { errors.push("load " + f + ": " + (e && e.stack ? e.stack.split("\n").slice(0, 2).join(" | ") : e)); }
}
(listeners["doc:DOMContentLoaded"] || []).forEach(f => { try { f(); } catch (e) { errors.push("DOMContentLoaded: " + e.stack.split("\n").slice(0, 2).join(" | ")); } });
const run = (label, src) => { try { new vm.Script(src, { filename: label }).runInContext(ctx); } catch (e) { errors.push(label + ": " + e.stack.split("\n").slice(0, 2).join(" | ")); } };
setTimeout(() => {
  run("init", "init()");
  setTimeout(() => {
    for (const v of ["overview", "devices", "esp", "flows", "monitor", "ai", "alerts", "wallets"]) run("showView(" + v + ")", `showView(${JSON.stringify(v)})`);
    setTimeout(() => { process.stdout.write(JSON.stringify(errors)); process.exit(0); }, 600);
  }, 600);
}, 200);
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
    print("== Khởi động cả trang (init + mở từng trang) ==")
    r = subprocess.run([node, "-e", HARNESS, WEB], capture_output=True, text=True, timeout=60)
    try:
        errs = json.loads(r.stdout)                     # không in ra gì (node sập) = HỎNG, không phải «không có lỗi»
    except Exception:
        errs = ["load: không đọc được kết quả (node thoát mã %s): %s %s" % (r.returncode, r.stdout[-300:], r.stderr[-400:])]
    refs = [e for e in errs if "ReferenceError" in e or "is not defined" in e or e.startswith("load ")]
    ok(not refs, "không có hàm / biến nào bị gọi mà không tồn tại, không tệp JS nào nạp lỗi", refs)
    syntax = [e for e in errs if "SyntaxError" in e]
    ok(not syntax, "không có lỗi cú pháp", syntax)
    names = ["loadAiScreen", "loadTelegram", "alertsBadge", "loadAlerts", "renderTelegram", "renderAiProviders", "showView", "init", "paintProgress", "runFrom", "loadWallets", "renderWallets", "walletEdit"]
    # kiểm ở phía node (không qua vm.run): hàm khai báo kiểu `function x()` ở cấp tệp là thuộc tính của ngữ cảnh vm
    probe = HARNESS.replace("setTimeout(() => {\n  run(\"init\"",
                            "process.stdout.write('MISSING[' + %s.filter(n => typeof ctx[n] !== 'function').join(',') + ']\\n');\nsetTimeout(() => {\n  run(\"init\"" % json.dumps(names), 1)
    assert probe != HARNESS, "không chèn được phép kiểm tên hàm"
    r2 = subprocess.run([node, "-e", probe, WEB], capture_output=True, text=True, timeout=60)
    line = next((ln for ln in (r2.stdout or "").splitlines() if ln.startswith("MISSING[")), None)
    missing = [n for n in line[len("MISSING["):].rstrip("]").split(",") if n] if line else None
    ok(missing == [], "các hàm chính của trang đều có: " + ", ".join(names), missing if missing is not None else (r2.stdout[-200:], r2.stderr[-200:]))
    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
