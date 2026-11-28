#!/usr/bin/env python3
"""
Kiểm phần LỘ TRÌNH CÁC BƯỚC của trình sửa kịch bản (app/web/steps.js, stepedit.js, screen.js, orders.js…) — lấy đúng mã nguồn các hàm từ các
tệp JS của trang (nối lại theo thứ tự nạp trong index.html), chạy bằng `node`, không cần trình duyệt:
  • mỗi loại bước viết thành một câu; chữ do người dùng / thiết bị đưa vào luôn được thoát HTML; {{biến}} thành nhãn riêng;
  • loại bước lạ (kể cả trùng tên thuộc tính có sẵn như «constructor») không làm hỏng trang;
  • đổi cách chạy của kịch bản sang «nhận đơn» và ngược lại: bước không bị mất, không bị nhân đôi;
  • «bấm lên ảnh để thêm bước chạm»: chèn theo BƯỚC đã chọn (không theo số thứ tự) — xoá / chèn bước khác không làm lệch chỗ;
    kịch bản nhận đơn mà chưa chọn giai đoạn thì không đoán chỗ;
  • ô bấm «Lấy từ đơn» của bước gõ chữ: đúng các trường đăng nhập của pool trên gateway theo từng giai đoạn, không đoán tên khi chưa đọc được pool;
  • bước của kịch bản nhận đơn CHỈ là bước ghi trong kịch bản (không mượn bước của gateway); giai đoạn bắt buộc trống thì có trong dòng «còn thiếu»;
    dấu «đã chép bước đời cũ từ gateway» được giữ qua các lần nạp / lưu, lời báo sau khi chép.

    ./.venv/bin/python app/tests/test_ui_steps.py
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_ui_controls import function_source, ui_source

PASS = FAIL = 0


def ok(cond, name, ctx=None):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, "→", ctx if ctx is not None else "")


def const_source(src: str, name: str) -> str:
    """Nguyên văn `const <name> = …;` (một dòng, hoặc nhiều dòng kết thúc bằng dòng `};` / `];`)."""
    start = src.index("const %s = " % name)
    line_end = src.index("\n", start)
    first = src[start:line_end]
    if first.rstrip().endswith(";"):
        return first
    m = re.compile(r"^[}\]];", re.M).search(src, line_end)
    return src[start:m.end()]


HARNESS = r"""
const out = {};
// ---- 1. câu của từng loại bước + thoát HTML ----
const X = '<img src=x onerror=alert(1)>"\'&';
const samples = {
  tap: { type: "tap", x: 12, y: 34 }, tap_text: { type: "tap_text", text: X }, type: { type: "type", text: X },
  key: { type: "key", name: X }, combo: { type: "combo", keys: X }, launch: { type: "launch", app: X }, home: { type: "home" },
  wait: { type: "wait", seconds: 1.5 }, wait_text: { type: "wait_text", text: X, timeout: 30 }, assert_text: { type: "assert_text", text: X },
  swipe_dir: { type: "swipe", dir: "left" }, swipe_bad: { type: "swipe", dir: X }, swipe_xy: { type: "swipe", x1: 1, y1: 2, x2: 3, y2: 4 },
  hold: { type: "hold", x: 5, y: 6, seconds: 1.2 }, hold_text: { type: "hold_text", text: X }, strange: { type: X, text: X },
  tap_if: { type: "tap_if", text: "Game Center", tap: "Hủy", timeout: 8 }, tap_if_self: { type: "tap_if", text: X }, tap_if_x: { type: "tap_if", text: "A", tap: X, timeout: 0 },
};
out.sentences = {};
for (const k of Object.keys(samples)) out.sentences[k] = stepSentence(samples[k]);
out.vars = stepSentence({ type: "type", text: "{{username}} và {{ package.ocr_text }} — {{<b>}} {{}}" });
out.spaces = stepSentence({ type: "type", text: "  " });
out.kinds = ["tap", "type", "launch", "wait_text", "constructor", "__proto__", "toString", "la"].map(t => stepKind(t));
out.kindIf = stepKind("tap_if");
out.multi = stepSentence({ type: "tap_if", timeout: 8, cases: [{ text: "mật khẩu", tap: "Hủy" }, { text: X }, "rác", null] });
out.multiText = stepText({ type: "tap_if", timeout: 8, cases: [{ text: "A", tap: "B" }, { text: "C" }] });
out.parse = parseIfCases("Game Center => Hủy\n  mật khẩu|Password ->  Hủy \n\nChỉ thấy\nA→B\n => thiếu chữ cần thấy\nĐóng => Đóng");
out.parseEmpty = [parseIfCases(""), parseIfCases(null), parseIfCases("   \n => x")];
out.parseMany = parseIfCases(Array.from({ length: 20 }, (_, i) => "a" + i).join("\n")).length;

// ---- 2. đổi cách chạy ----
const A = { type: "home" }, B = { type: "launch", app: "g" };
let sc = { id: "s", name: "S", steps: [A, B], mode: "once", loops: 1 };
setScriptMode(sc, "orders");
out.toOrders = { mode: sc.mode, steps: sc.steps.length, login: sc.orders.steps.login.length, sameObjects: sc.orders.steps.login[0] === A && sc.orders.steps.login[1] === B,
                 phases: Object.keys(sc.orders.steps).length, count: scriptStepCount(sc) };
setScriptMode(sc, "orders");
out.ordersTwice = { login: sc.orders.steps.login.length, steps: sc.steps.length };
setScriptMode(sc, "once");
out.backOnce = { mode: sc.mode, steps: sc.steps.length, login: sc.orders.steps.login.length, loops: sc.loops, count: scriptStepCount(sc) };
setScriptMode(sc, "orders"); sc.orders.steps.purchase.push({ type: "tap_text", text: "Mua" });
setScriptMode(sc, "loop");
out.backWithOther = { mode: sc.mode, steps: sc.steps.length, login: sc.orders.steps.login.length, purchase: sc.orders.steps.purchase.length, loops: sc.loops };
setScriptMode(sc, "orders");
out.againOrders = { login: sc.orders.steps.login.length, purchase: sc.orders.steps.purchase.length, steps: sc.steps.length, count: scriptStepCount(sc) };
let sc2 = { id: "t", name: "T", steps: [A], mode: "once", loops: 1, orders: normApi({ pool: "p", steps: { nav: [B] } }) };
setScriptMode(sc2, "orders");
out.keepExisting = { steps: sc2.steps.length, login: sc2.orders.steps.login.length, nav: sc2.orders.steps.nav.length, pool: sc2.orders.pool };
let sc3 = { id: "u", name: "U", steps: [A], mode: "once", loops: 1 };
setScriptMode(sc3, "la-lung"); out.strangeMode = sc3.mode;
setScriptMode(sc3, "loop"); out.loopLoops = sc3.loops;

// ---- 3. bấm ảnh để thêm bước chạm ----
const T = (n) => ({ type: "tap", x: n, y: n });
const s1 = { type: "home" }, s2 = { type: "wait", seconds: 1 }, s3 = { type: "key", name: "enter" };
FLOW.steps = [s1, s2, s3];
ORDERS = null; PICK_TO = { list: FLOW.steps, after: s1 };
addPicked(T(1)); addPicked(T(2));
out.afterAnchor = FLOW.steps.map(x => x.type + (x.x || ""));
FLOW.steps.splice(0, 1);                       // xoá bước đứng TRƯỚC chỗ đang chèn
addPicked(T(3));
out.afterDeleteOther = FLOW.steps.map(x => x.type + (x.x || ""));
const anchor = PICK_TO.after;
FLOW.steps.splice(FLOW.steps.indexOf(anchor), 1);   // xoá chính bước đang làm mốc
addPicked(T(4));
out.anchorGone = FLOW.steps.map(x => x.type + (x.x || ""));
PICK_TO = { list: FLOW.steps, after: null };
addPicked(T(5));
out.head = FLOW.steps.map(x => x.type + (x.x || "")).slice(0, 2);
PICK_TO = null; FLOW.steps = [s1];
out.noTargetPlain = addPicked(T(6)) === true && FLOW.steps.map(x => x.type + (x.x || "")).join(",") === "home,tap6";
PICK_TO = null; ORDERS = { orders: { steps: { login: [] } } }; TOASTS.length = 0;
const before = JSON.stringify(FLOW.steps);
out.noTargetOrders = addPicked(T(7)) === false && JSON.stringify(FLOW.steps) === before && TOASTS.length === 1 && PICK_TO === null;
const other = [];
PICK_TO = { list: other, after: null };
addPicked(T(8));
out.intoOtherList = other.length === 1 && JSON.stringify(FLOW.steps) === before;
out.renders = RENDERS;

// ---- 4. dữ liệu của ĐƠN chèn được vào bước (ô bấm «Lấy từ đơn») ----
const names = (v) => v.items.map(x => x.name);
out.varsNoOrders = orderVars([]);                                   // không phải kịch bản nhận đơn
CFG = normApi({ pool: "p", steps: {} }); GW_POOL = null;
out.varsNoPool = orderVars(CFG.steps.login);                        // chưa đọc được pool
GW_POOL = { code: "khac", login_fields: [{ key: "username", label: "U" }] };
out.varsOtherPool = orderVars(CFG.steps.login);                     // đang giữ cấu hình của pool KHÁC
GW_POOL = { code: "p", login_fields: [{ key: "username", label: "Email <b>", secret: false }, { key: "password", label: "", secret: true }, { key: "x y", label: "rác" }, null, { key: 5 }, { label: "thiếu tên" }] };
out.varsLogin = orderVars(CFG.steps.login);
out.varsOtp = names(orderVars(CFG.steps.otp));
out.varsBuy = names(orderVars(CFG.steps.purchase));
out.varsAfter = names(orderVars(CFG.steps.after));
out.varsNav = names(orderVars(CFG.steps.nav));
out.varsFinish = names(orderVars(CFG.steps.finish));
out.varsStranger = names(orderVars([]));                            // danh sách không thuộc giai đoạn nào
out.pkgLogin = orderVars(CFG.steps.login, "package.");
out.pkgBuy = names(orderVars(CFG.steps.purchase, "package."));
GW_POOL = { code: "p", login_fields: "rác" };
out.varsBadFields = orderVars(CFG.steps.login);
CFG = normApi({ pool: "", steps: {} }); GW_POOL = null;
out.varsNoPoolChosen = orderVars(CFG.steps.login);
out.chips = varChips({ items: [{ name: "username", label: X, secret: false }, { name: "password", label: "Mật khẩu", secret: true }], note: "" });
out.chipsNote = varChips({ items: [], note: X });
const inp = { value: "abXYcd", selectionStart: 2, selectionEnd: 4, focus() { this.focused = true; }, setSelectionRange(a, b) { this.sel = [a, b]; } };
insertAtCursor(inp, "{{username}}");
out.insert = [inp.value, inp.sel, inp.focused === true];
const inp2 = { value: "ab", selectionStart: null, selectionEnd: null, focus() {}, setSelectionRange(a, b) { this.sel = [a, b]; } };
insertAtCursor(inp2, "{{otp}}");
out.insertEnd = [inp2.value, inp2.sel];

// ---- 5. bước «bấm / giữ vào chữ»: chờ chữ hiện ra ----
out.waitSentence = [stepSentence({ type: "tap_text", text: "A", timeout: 5 }), stepSentence({ type: "tap_text", text: "A", timeout: 0 }), stepSentence({ type: "tap_text", text: "A", timeout: X }),
                    stepSentence({ type: "hold_text", text: "A", seconds: 1, timeout: 3 }), stepSentence({ type: "hold_text", text: "A", seconds: 1 }), stepText({ type: "tap_text", text: "A", timeout: 5 }),
                    stepText({ type: "tap_text", text: "A" })];
out.waitField = [textWaitField(null).value, textWaitField({ type: "tap_text", text: "A" }).value, textWaitField({ type: "tap_text", text: "A", timeout: 7 }).value, textWaitField({ timeout: "x" }).value];
const ws = (raw) => { const st = { type: "tap_text", text: "A", timeout: 9 }; setTextWait(st, raw); return "timeout" in st ? st.timeout : null; };
out.waitSet = [ws("5"), ws("0"), ws(""), ws("abc"), ws("-3"), ws("999"), ws("2.5")];

// ---- 6. bước «bấm vào vùng ảnh» ----
const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
out.imgSentence = [stepSentence({ type: "tap_image", image: PNG, w: 90, h: 90, timeout: 5 }), stepSentence({ type: "tap_image", image: PNG }),
                   stepSentence({ type: "tap_image", image: X }), stepSentence({ type: "tap_image" }), stepSentence({ type: "tap_image", image: PNG + '" onerror="alert(1)' })];
out.imgText = [stepText({ type: "tap_image", image: PNG, w: 90, h: 90, timeout: 5 }), stepText({ type: "tap_image", image: PNG, w: X, h: X })];
out.imgSrc = [imageSrc(PNG) === "data:image/png;base64," + PNG, imageSrc(""), imageSrc(null), imageSrc("abc def"), imageSrc("data:image/png;base64," + PNG), imageSrc("AAAA===="), imageSrc("A".repeat(1200001))];
out.imgKind = stepKind("tap_image");
// ---- 9. «trong cùng ô phải có chữ» + «chưa thấy thì lướt» ----
out.card = [stepSentence({ type: "tap_text", text: "{{package.ocr_text}}", near: "{{package.price_text}}", scroll: "left", timeout: 5 }),
            stepSentence({ type: "assert_text", text: "500", near: X, near_dir: "right", scroll: X }), stepSentence({ type: "tap_text", text: "A" }),
            stepText({ type: "tap_text", text: "500", near: "CHF 2.30" }), stepText({ type: "assert_text", text: "500" })];
const cs1 = { type: "tap_text", text: "A", near: "x", near_dir: "left", scroll: "up", scrolls: 3 };
setCard(cs1, { near: "  ", near_dir: "left", scroll: "" });
const cs2 = { type: "tap_text", text: "A" };
setCard(cs2, { near: " CHF 2.30 ", near_dir: "below", scroll: "left" });
const cs3 = { type: "tap_text", text: "A" };
setCard(cs3, { near: "B", near_dir: X, scroll: X });
out.setCard = [cs1, cs2, cs3];
const cs4 = { type: "tap_text", text: "A", near: "B", near_dir: "above" };          // hướng của bản trước, nay không còn
const f4 = cardFields(cs4, []).find(f => f.key === "near_dir");
setCard(cs4, { near: "B", near_dir: f4.value, scroll: "" });
out.legacyDir = [cs4, f4.options.some(o => o.value === "above"), stepSentence(cs4)];

// ---- 8. trang «Theo dõi» ----
out.atParse = parseIfCases("Sign Players => @667,571\nA => @ 12 ; 34\nB => @-1,5\nC => @x,y");
out.atLines = out.atParse.map(ifCaseLine);
out.atSentence = [stepSentence({ type: "tap_if", text: "Sign Players", at: [667, 571], timeout: 9 }), stepSentence({ type: "tap_if", text: "A", at: [X, 1] }),
                  stepText({ type: "tap_if", text: "A", at: [1, 2], timeout: 3 }), stepSentence({ type: "tap_if", text: "A", at: [-5, 3] })];
out.ifAt = [ifAt({ at: [1, 2] }), ifAt({ at: [-1, 5] }), ifAt({ at: [1, 2, 3] }), ifAt({ at: [1.5, 2] }), ifAt({ at: [10000, 1] }), ifAt(null)];
out.until = [stepSentence({ type: "tap_if", text: "A", tap: "B", timeout: 60, until: "Shop" }), stepSentence({ type: "tap_if", text: "A", tap: "B", timeout: 60, until: X })];
out.monDur = [0, 6.4, 59.6, 60, 130, 3600, 3785, -5, "abc"].map(monDur);
out.monResult = ["done", "failed", "review", "error", null, X].map(monResult);
out.monItems = [monItems([{ name: "1050 Coins", qty: 2 }, { code: "starter" }, null]), monItems(null), monItems("rác")];
out.monLive = [monLiveLine(null),
  monLiveLine({ kind: "nhận đơn", group: "Nhóm A", script: "nạp Efootball", order: { id: "7", ref: "T-7" }, phase: "Đăng nhập", step: { what: "Bấm vào chữ «Login»", i: 5, n: 16, phase: "Đăng nhập", since: 100 } }),
  monLiveLine({ kind: "chạy thử một bước", last: { what: "Tap chữ «Shop»", ok: false, msg: "không thấy chữ", t: 90, i: 1 } }),
  monLiveLine({ kind: "kịch bản", group: "G", phase: "Mua một gói", since: 50 })];
const EV = [{ ev: "step", t: 1, what: "lẻ", ok: true, dur: 1 },
  { ev: "run_begin", t: 2, id: "r1", kind: "nhận đơn", group: "G", script: "S" }, { ev: "order_begin", t: 3, run: "r1", order: "7", ref: "T-7", items: [{ name: X, qty: 1 }] },
  { ev: "step", t: 4, run: "r1", order: "7", what: X, ok: false, msg: X, i: 2, n: 5, phase: "Đăng nhập", dur: 2.2 }, { ev: "note", t: 5, run: "r1", text: X, kind: "bad" },
  { ev: "order_end", t: 6, run: "r1", order: "7", ref: "T-7", result: "review", msg: X, dur: 70 }, { ev: "run_end", t: 7, run: "r1", status: "DỪNG", dur: 5 },
  { ev: "run_begin", t: 8, id: "r2", kind: "chạy thử" }, "rác", null];
const G8 = monGroup(EV);
out.monGroup = G8.map(b => [b.id, !!b.run, !!b.end, b.items.length]);
out.monGroupBad = [monGroup(null).length, monGroup("x").length];
out.monHtml = EV.filter(e => e && typeof e === "object").map(monEventHtml).join("|");
out.monBlocks = monBlocksHtml(EV, "trống");
out.monEmpty = monBlocksHtml([], X);
out.monClock = [monClock(0), monClock(1795700000, true)];
out.imgMin = ["90", "80", "0.8", "1", "", "abc", "-5", "0", "20", "100", "99.6"].map(parseImageMin);
const px = (list) => { const d = []; list.forEach(([r, g, b]) => d.push(r, g, b, 255)); return d; };
out.flat = [flatPixels(px(Array(100).fill([255, 0, 0]))), flatPixels(px(Array(100).fill([77, 77, 77]))), flatPixels(px(Array(50).fill([255, 0, 0]).concat(Array(50).fill([0, 255, 0])))),
            flatPixels(px(Array(50).fill([200, 200, 200]).concat(Array(50).fill([20, 20, 20])))), flatPixels([])];
const RECT = { left: 100, top: 50, width: 667, height: 375 }, SCR = { w: 1334, h: 750 };      // ảnh 1334×750 hiện thu nhỏ một nửa
out.region = [dragRegion({ x: 706, y: 368 }, { x: 751, y: 413 }, RECT, SCR),                    // kéo quanh nút menu (1257,682)
              dragRegion({ x: 751, y: 413 }, { x: 706, y: 368 }, RECT, SCR),                    // kéo ngược (từ dưới-phải lên trên-trái)
              dragRegion({ x: 300, y: 200 }, { x: 303, y: 204 }, RECT, SCR),                    // gần như không kéo → là một cú bấm
              dragRegion({ x: 300, y: 200 }, { x: 304, y: 208 }, RECT, SCR),                    // kéo tí tẹo → quá nhỏ
              dragRegion({ x: 110, y: 60 }, { x: 760, y: 420 }, RECT, SCR),                     // khoanh gần hết màn hình → quá lớn
              dragRegion({ x: 700, y: 380 }, { x: 900, y: 600 }, RECT, SCR),                    // kéo ra NGOÀI ảnh → cắt gọn trong ảnh
              dragRegion({ x: 300, y: 200 }, { x: 400, y: 300 }, { left: 0, top: 0, width: 0, height: 0 }, SCR), dragRegion({ x: 1, y: 1 }, { x: 50, y: 50 }, RECT, { w: 0, h: 0 }), dragRegion(null, null, RECT, SCR)];

// ---- 7. «nhấn phím» trong bước có điều kiện; mở mới app; gõ từng ký tự; «Chạy lại» máy đang giữ ----
out.keyParse = parseIfCases("lưu mật khẩu này => phím esc\nGame Center => Hủy\nx => key ENTER\ny => phim tab\nz => phím f13\nw => phím\nv => phím delete");
out.keyLines = out.keyParse.map(ifCaseLine);
out.keySentence = [stepSentence({ type: "tap_if", text: "lưu mật khẩu này", key: "esc", timeout: 5 }), stepSentence({ type: "tap_if", timeout: 0, cases: [{ text: "A", key: "esc" }, { text: "B", tap: "C" }] }),
                   stepSentence({ type: "tap_if", text: "A", key: X }), stepText({ type: "tap_if", text: "A", key: "esc", timeout: 3 })];
out.keyCases = [ifCases({ type: "tap_if", text: "A", key: "esc" }), ifKey({ key: " ESC " }), ifKey({ key: X }), ifKey(null)];
out.fresh = [stepSentence({ type: "launch", app: "efootball", fresh: true }), stepSentence({ type: "launch", app: "efootball" }), stepText({ type: "launch", app: "efootball", fresh: true }), stepText({ type: "launch", app: "efootball" })];
out.gap = [stepSentence({ type: "type", text: "{{otp}}", gap: 0.4 }), stepSentence({ type: "type", text: "abc" }), stepSentence({ type: "type", text: "abc", gap: X })];
const G = { id: "g1" }, S = { id: "s1", mode: "orders" };
out.rerun = [canRerunHeld({ hold: "đơn cần đối soát", group_id: "g1", script_id: "s1" }, G, S), canRerunHeld({ hold: "x", group_id: "g1", script_id: "khac" }, G, S),
             canRerunHeld({ hold: "x", group_id: "khac", script_id: "s1" }, G, S), canRerunHeld({ hold: "x", group_id: "g1", script_id: "s1", running: true }, G, S),
             canRerunHeld({ group_id: "g1", script_id: "s1" }, G, S), canRerunHeld({ hold: "x", group_id: "g1", script_id: "s1" }, G, { id: "s1", mode: "once" }), canRerunHeld(null, G, S)];

// ---- 10. kịch bản nhận đơn: bước chỉ nằm trong kịch bản; chép MỘT LẦN bước đời cũ từ gateway ----
const own = { type: "tap_text", text: "Mua" };
const OS = { id: "o", name: "O", steps: [], mode: "orders", loops: 1, orders: normApi({ pool: "p", steps: { purchase: [own] } }) };
ORDERS = OS;
// pool đang nạp có kèm khối `steps` kiểu cũ: giao diện không được đọc tới
GW_POOL = { code: "p", missing_rules: ["Nạp <b>"], required_phases: ["login", "purchase", "finish"], steps: { login: [{ type: "home" }], finish: [{ type: "home" }], nav: [{ type: "home" }] } };
const L = flowLists();
out.lists = { keys: L.map(l => l.key), labels: L.map(l => l.label), sameArrays: L.every(l => l.steps === OS.orders.steps[l.key]), counts: L.map(l => l.steps.length),
              required: L.filter(l => l.required).map(l => l.key), extra: [...new Set(L.flatMap(l => Object.keys(l)))].sort() };
ORDERS = null; FLOW.steps = [own];
out.listsPlain = flowLists().map(l => [l.key, l.steps === FLOW.steps]);
GW = { url: "https://gw", has_key: true };
out.missPool = ordersMissing(OS);
OS.orders.steps.login.push({ type: "home" }); OS.orders.steps.finish.push({ type: "home" });
out.missNone = ordersMissing(OS).filter(m => m.includes("giai đoạn"));
OS.orders.steps.login.length = 0; GW_POOL = null;
out.missNoPoolCfg = ordersMissing(OS);                          // chưa đọc được pool: bước bắt buộc còn thiếu vẫn phải được nhắc
GW = { url: "", has_key: false };
out.missNoGw = ordersMissing(OS);
out.copiedFlag = [normApi({}).gw_steps_copied, normApi({ gw_steps_copied: true }).gw_steps_copied, normApi({ gw_steps_copied: "true" }).gw_steps_copied, normApi({ gw_steps_copied: 1 }).gw_steps_copied,
                  normApi(JSON.parse(JSON.stringify(normApi({ gw_steps_copied: true })))).gw_steps_copied];
out.adoptText = [adoptedText({ after: 1, finish: 4 }), adoptedText({ finish: 2, login: 7, la: 9, nav: "3", otp: 0, purchase: -1 }), adoptedText({}), adoptedText(null), adoptedText({ login: X })];
console.log(JSON.stringify(out));
"""


def main():
    node = shutil.which("node")
    if not node:
        print("BỎ QUA: cần lệnh `node` để chạy mã giao diện.")
        return 0
    src = ui_source()
    esc_line = next(l for l in src.splitlines() if l.startswith("const esc ="))
    parts = [esc_line] + [const_source(src, n) for n in ("SWIPE_DIR", "STEP_LABEL", "STEP_KIND", "API_PHASES", "ORDER_LABEL", "REQUIRED_PHASES", "TEXT_WAIT_NEW", "REGION_DRAG", "IF_KEYS",
                                                         "NEAR_DIR_LABEL", "SCROLL_LABEL")]
    parts += [function_source(src, n) for n in ("monDur", "monClock", "monResult", "monItems", "monLiveLine", "monGroup", "monEventHtml", "monBlocksHtml")]
    parts += [function_source(src, n) for n in ("ifCases", "parseIfCases", "stepText", "stepKind", "stepVal", "stepSentence", "normApi", "scriptStepCount", "setScriptMode", "addPicked",
                                                "orderVars", "varChips", "insertAtCursor", "textWaitField", "setTextWait", "imageSrc", "dragRegion",
                                                "ifKey", "ifAt", "ifCaseLine", "canRerunHeld", "parseImageMin", "flatPixels",
                                                "cardText", "setCard", "cardFields", "flowLists", "ordersMissing", "adoptedText")]
    stubs = ("let FLOW = { steps: [] }; let PICK_TO = null; let ORDERS = null; let RENDERS = 0; const TOASTS = []; let CFG = null; let GW_POOL = null; let GW = { url: \"\", has_key: false };\n"
             "function scriptOrders() { return ORDERS; }\nfunction ordersCfg() { return CFG; }\nfunction renderSteps() { RENDERS++; }\nfunction toast(m) { TOASTS.push(m); }\n")
    r = subprocess.run([node, "-e", stubs + "\n".join(parts) + HARNESS], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        ok(False, "mã giao diện chạy được bằng node", r.stderr[-600:])
        print("\n❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL))
        return 1
    o = json.loads(r.stdout)

    print("== 1. Mỗi bước một câu; chữ lạ luôn được thoát ==")
    s = o["sentences"]
    ok(all("<img" not in v and "onerror=alert(1)>" not in v for v in s.values()), "không câu nào để lọt thẻ HTML do người dùng / thiết bị đưa vào", {k: v for k, v in s.items() if "<img" in v})
    ok(all("&lt;img src=x onerror=alert(1)&gt;" in s[k] for k in ("tap_text", "type", "key", "combo", "launch", "wait_text", "assert_text", "swipe_bad", "hold_text", "strange")),
       "…chữ đó hiện ra đúng nguyên văn (đã thoát) ở mọi loại bước có chữ")
    ok(s["tap"] == "Bấm tại <b>(12, 34)</b>" and s["home"] == "Về màn hình chính" and s["wait"] == "Chờ <b>1.5 giây</b>" and s["swipe_xy"] == "Vuốt từ <b>(1, 2)</b> tới <b>(3, 4)</b>",
       "câu của bước bấm toạ độ / về màn hình chính / chờ / vuốt theo toạ độ", [s["tap"], s["home"], s["wait"], s["swipe_xy"]])
    ok(s["tap_if"] == 'Nếu thấy chữ <b>«Game Center»</b> thì bấm <b>«Hủy»</b> <span class="flow-dim">chờ tối đa 8 giây</span>'
       and "xem một lần" in s["tap_if_x"] and s["tap_if_self"].count("&lt;img") == 2 and "&lt;img" in s["tap_if_x"],
       "bước có điều kiện: «Nếu thấy chữ … thì bấm …» + thời gian chờ; không ghi chỗ bấm thì bấm chính chữ đó; chữ lạ vẫn được thoát", [s["tap_if"], s["tap_if_x"]])
    ok(o["multi"].count("Nếu thấy chữ") == 2 and "<br>" in o["multi"] and "không thấy gì thì bỏ qua" in o["multi"] and "&lt;img" in o["multi"] and "<img" not in o["multi"]
       and o["multiText"] == "“A” → “B”; “C” → “C” (8s)",
       "bước nhiều trường hợp: mỗi trường hợp một dòng, phần tử rác bị bỏ, chữ lạ vẫn được thoát", [o["multi"], o["multiText"]])
    ok(o["parse"] == [{"text": "Game Center", "tap": "Hủy"}, {"text": "mật khẩu|Password", "tap": "Hủy"}, {"text": "Chỉ thấy"}, {"text": "A", "tap": "B"}, {"text": "Đóng"}],
       "gõ mỗi dòng «thấy => bấm»: nhận =>, ->, →; bỏ dòng trống / dòng thiếu chữ cần thấy; bấm chính chữ đó thì không ghi lặp", o["parse"])
    ok(o["parseEmpty"] == [[], [], []] and o["parseMany"] == 12, "không có dòng nào hợp lệ → rỗng; tối đa 12 trường hợp")
    ok("sang trái" in s["swipe_dir"] and "tối đa 30 giây" in s["wait_text"] and "trong 1.2 giây" in s["hold"] and s["type"].startswith("Gõ <b>«"), "vuốt theo hướng, thời gian chờ tối đa, thời gian giữ; chữ gõ nằm trong ngoặc «»")
    ok(o["vars"].count("<code>") == 2 and "<code>{{username}}</code>" in o["vars"] and "<code>{{package.ocr_text}}</code>" in o["vars"] and "{{&lt;b&gt;}}" in o["vars"],
       "{{biến}} hợp lệ thành nhãn riêng; thứ trông giống biến nhưng chứa ký tự lạ thì chỉ là chữ đã thoát", o["vars"])
    ok(o["spaces"] == "Gõ <b>«  »</b>", "chữ gõ toàn khoảng trắng vẫn thấy được (nằm trong ngoặc)", o["spaces"])
    k = o["kinds"]
    ok(k[0] == ["touch", "tabler-pointer"] and k[1][0] == "key" and k[2][0] == "app" and k[3][0] == "wait", "mỗi loại bước thuộc đúng nhóm (chạm / bàn phím / ứng dụng / chờ)", k[:4])
    ok(o["kindIf"][0] == "touch", "bước có điều kiện thuộc nhóm «chạm»", o["kindIf"])
    ok(all(x == ["", "tabler-point"] for x in k[4:]), "loại bước lạ — kể cả «constructor», «__proto__», «toString» — dùng biểu tượng mặc định, không làm hỏng trang", k[4:])

    print("== 2. Đổi cách chạy của kịch bản ==")
    ok(o["toOrders"] == {"mode": "orders", "steps": 0, "login": 2, "sameObjects": True, "phases": 6, "count": 2},
       "sang «nhận đơn»: các bước đang có thành giai đoạn «Đăng nhập» (chính các bước đó, không nhân đôi); đủ 6 giai đoạn", o["toOrders"])
    ok(o["ordersTwice"] == {"login": 2, "steps": 0}, "chọn lại «nhận đơn» lần nữa → không đổi gì")
    ok(o["backOnce"] == {"mode": "once", "steps": 2, "login": 0, "loops": 1, "count": 2}, "về «1 lần» khi chỉ «Đăng nhập» có bước → các bước quay về danh sách thường", o["backOnce"])
    ok(o["backWithOther"] == {"mode": "loop", "steps": 0, "login": 2, "purchase": 1, "loops": 0},
       "về «lặp» khi giai đoạn KHÁC cũng có bước → giữ nguyên cấu hình nhận đơn (không gộp bừa, không mất bước); số vòng về mặc định của «lặp»", o["backWithOther"])
    ok(o["againOrders"] == {"login": 2, "purchase": 1, "steps": 0, "count": 3}, "quay lại «nhận đơn» → mọi giai đoạn còn nguyên", o["againOrders"])
    ok(o["keepExisting"] == {"steps": 1, "login": 0, "nav": 1, "pool": "p"}, "kịch bản đã có sẵn cấu hình nhận đơn → KHÔNG chép đè bước thường lên giai đoạn «Đăng nhập»", o["keepExisting"])
    ok(o["strangeMode"] == "once" and o["loopLoops"] == 0, "cách chạy lạ bị coi là «1 lần»; «lặp» mặc định lặp vô hạn")

    print("== 3. Bấm lên ảnh để thêm bước chạm ==")
    ok(o["afterAnchor"] == ["home", "tap1", "tap2", "wait", "key"], "chèn ngay sau bước đã chọn; bấm tiếp thì nối tiếp theo thứ tự bấm", o["afterAnchor"])
    ok(o["afterDeleteOther"] == ["tap1", "tap2", "tap3", "wait", "key"], "xoá một bước KHÁC ở phía trước → lần bấm kế vẫn vào đúng chỗ (neo theo bước, không theo số thứ tự)", o["afterDeleteOther"])
    ok(o["anchorGone"] == ["tap1", "tap2", "wait", "key", "tap4"], "bước làm mốc bị xoá → thêm vào CUỐI (không đoán vị trí)", o["anchorGone"])
    ok(o["head"] == ["tap5", "tap1"], "mốc «đầu danh sách» → chèn ở vị trí đầu", o["head"])
    ok(o["noTargetPlain"] is True, "kịch bản thường, chưa chọn chỗ → thêm vào cuối")
    ok(o["noTargetOrders"] is True, "kịch bản nhận đơn mà chưa chọn giai đoạn → KHÔNG thêm, nhắc chọn giai đoạn")
    ok(o["intoOtherList"] is True and o["renders"] >= 6, "chèn vào đúng danh sách của giai đoạn đã chọn (không lẫn sang danh sách khác); vẽ lại sau mỗi lần thêm")

    print("== 4. Dữ liệu của đơn chèn được vào bước ==")
    login = ["username", "password"]
    pkg = ["package.ocr_text", "package.price_text", "package.name"]
    ok(o["varsNoOrders"] is None, "kịch bản thường (không nhận đơn) → không có ô «Lấy từ đơn»", o["varsNoOrders"])
    ok(o["varsLogin"] == {"items": [{"name": "username", "label": "Email <b>", "secret": False}, {"name": "password", "label": "password", "secret": True}], "note": ""},
       "giai đoạn «Đăng nhập»: đúng các trường đăng nhập của POOL (tên + nhãn + có phải bí mật); trường sai dạng / tên có ký tự lạ bị bỏ; thiếu nhãn thì dùng tên", o["varsLogin"])
    ok(o["varsNoPool"]["items"] == [] and "Chưa đọc được pool" in o["varsNoPool"]["note"] and o["varsOtherPool"]["items"] == [] and o["varsOtherPool"]["note"]
       and o["varsBadFields"]["items"] == [],
       "chưa đọc được pool (hoặc đang giữ cấu hình của pool KHÁC) → KHÔNG đoán tên trường, nói rõ lý do", [o["varsNoPool"], o["varsOtherPool"]])
    ok("Chọn pool" in o["varsNoPoolChosen"]["note"] and o["varsNoPoolChosen"]["items"] == [], "kịch bản chưa chọn pool → nhắc chọn pool", o["varsNoPoolChosen"])
    ok(o["varsOtp"] == login + ["otp"] and o["varsNav"] == login and o["varsFinish"] == login and o["varsStranger"] == login,
       "mã OTP chỉ có ở giai đoạn «Nhập OTP»; các giai đoạn khác chỉ có trường đăng nhập", [o["varsOtp"], o["varsNav"], o["varsFinish"], o["varsStranger"]])
    ok(o["varsBuy"] == login + pkg and o["varsAfter"] == login + pkg, "thông tin gói đang mua chỉ có ở «Mua một gói» và «Sau mỗi lần mua»", [o["varsBuy"], o["varsAfter"]])
    ok(o["pkgLogin"] is None and o["pkgBuy"] == pkg, "bước «tìm chữ» chỉ được gợi ý chữ của gói (không bao giờ gợi ý tài khoản / mật khẩu), và chỉ ở giai đoạn mua", [o["pkgLogin"], o["pkgBuy"]])
    c = o["chips"]
    ok("<img" not in c and "&lt;img" in c and c.count('class="var-chip"') == 2 and 'data-var="username"' in c and 'data-var="password"' in c
       and c.count("tabler-lock") == 1 and c.count("Lấy từ đơn") == 1,
       "mỗi dữ liệu một ô bấm; nhãn đến từ gateway luôn được thoát; trường bí mật có hình khoá", c)
    ok("<img" not in o["chipsNote"] and "&lt;img" in o["chipsNote"] and "var-chip" not in o["chipsNote"] and "Lấy từ đơn" not in o["chipsNote"],
       "không có dữ liệu nào → chỉ hiện lời nhắn (đã thoát), không có hàng ô trống", o["chipsNote"])
    ok(o["insert"] == ["ab{{username}}cd", [14, 14], True] and o["insertEnd"] == ["ab{{otp}}", [9, 9]],
       "bấm ô → chèn {{tên}} vào chỗ con trỏ (thay phần đang bôi), con trỏ đứng ngay sau; không biết chỗ con trỏ thì chèn ở cuối", [o["insert"], o["insertEnd"]])

    print("== 5. Bước «bấm / giữ vào chữ»: chờ chữ hiện ra ==")
    w = o["waitSentence"]
    ok(w[0] == 'Bấm vào chữ <b>«A»</b> <span class="flow-dim">chờ tối đa 5 giây</span>' and w[1] == w[2] == "Bấm vào chữ <b>«A»</b>" and "<img" not in w[2],
       "câu của bước nói rõ thời gian chờ khi có ghi; không ghi / 0 / giá trị lạ → câu như cũ (không in giá trị lạ ra trang)", w[:3])
    ok("trong 1 giây · chờ chữ tối đa 3 giây" in w[3] and "chờ chữ" not in w[4] and w[5] == "“A” (chờ 5s)" and w[6] == "“A”", "bấm giữ vào chữ và dòng nhật ký cũng nói thời gian chờ", w[3:])
    ok(o["waitField"] == ["5", "0", "7", "0"], "bước MỚI mặc định chờ 5 giây; bước cũ không ghi gì hiện 0 (đang nhìn một lần) — không tự đổi hành vi của bước đã có", o["waitField"])
    ok(o["waitSet"] == [5, None, None, None, None, 60, 2.5], "lưu: 0 / trống / không phải số / âm → bỏ trường (nhìn một lần); quá lớn → 60 giây; số lẻ giữ nguyên", o["waitSet"])

    print("== 6. Bước «bấm vào vùng ảnh» ==")
    g = o["imgSentence"]
    ok(g[0].startswith('Bấm vào hình <img class="flow-thumb" src="data:image/png;base64,iVBOR') and g[0].endswith('<span class="flow-dim">chờ tối đa 5 giây</span>') and "flow-dim" not in g[1] and "<img" in g[1],
       "câu của bước hiện luôn HÌNH cần bấm (và thời gian chờ nếu có)", g[:2])
    ok(all("<img" not in x and "ảnh không đọc được" in x for x in g[2:]) and "onerror" not in "".join(g[2:]).replace("&quot;", ""),
       "ảnh không phải base64 / thiếu ảnh / có ký tự chen vào → KHÔNG đưa vào trang, ghi «ảnh không đọc được»", g[2:])
    ok(o["imgText"] == ["vùng ảnh 90×90 (chờ 5s)", "vùng ảnh ?×?"] and o["imgKind"] == ["touch", "tabler-photo-search"], "dòng nhật ký ghi cỡ vùng ảnh (cỡ lạ → «?»); bước thuộc nhóm «chạm»", [o["imgText"], o["imgKind"]])
    ok(o["imgMin"] == [90, 80, 80, 99, 90, 90, 90, 90, 50, 99, 99],
       "ô «giống tối thiểu (%)»: gõ 0.8 hiểu là 80%; trống / chữ / số âm / 0 → 90 (mặc định, không tụt về mức dễ dãi nhất); kẹp trong 50…99", o["imgMin"])
    ok(o["flat"] == [True, True, False, False, True],
       "vùng «gần như một màu» xét theo TỪNG kênh màu như phía máy: mảng đỏ thuần / xám thuần bị từ chối; hai màu đồng độ sáng hay sáng–tối đều được nhận", o["flat"])
    ok(o["imgSrc"] == [True, "", "", "", "", "", ""], "chỉ chuỗi base64 thuần (không khoảng trắng, không tiền tố, đệm đúng, không quá lớn) mới thành địa chỉ ảnh", o["imgSrc"])
    r = o["region"]
    ok(r[0] == {"x": 1212, "y": 636, "w": 90, "h": 90} and r[1] == r[0], "kéo một khung trên ảnh đang thu nhỏ → đúng vùng theo điểm ảnh của ảnh chụp, kéo xuôi hay ngược đều như nhau", r[:2])
    ok(r[2] is None and "quá nhỏ" in (r[3] or {}).get("error", "") and "quá lớn" in (r[4] or {}).get("error", ""),
       "gần như không kéo → coi là một cú BẤM (toạ độ); khung quá nhỏ / quá lớn → báo, không tạo bước", r[2:5])
    ok(r[5] == {"x": 1200, "y": 660, "w": 134, "h": 90} and r[6] is None and r[7] is None and r[8] is None,
       "kéo ra ngoài ảnh → vùng được cắt gọn trong ảnh; chưa có ảnh / thiếu điểm → không tạo gì", r[5:])

    print("== 9. «Trong cùng ô phải có chữ» + «chưa thấy thì lướt» ==")
    cd = o["card"]
    ok(cd[0] == 'Bấm vào chữ <b>«<code>{{package.ocr_text}}</code>»</b> có <b>«<code>{{package.price_text}}</code>»</b> ngay dưới <span class="flow-dim">chưa thấy thì lướt sang trái (xem phần bên phải)</span> <span class="flow-dim">chờ tối đa 5 giây</span>'
       and "bên phải" in cd[1] and "&lt;img" in cd[1] and "<img" not in cd[1] and "lướt" not in cd[1] and cd[2] == "Bấm vào chữ <b>«A»</b>"
       and cd[3] == "“500” + “CHF 2.30”" and cd[4] == "“500”",
       "câu của bước nói rõ «có … ngay dưới · chưa thấy thì lướt …»; chữ lạ được thoát; hướng lướt lạ không in ra; bước không dùng thì như cũ", cd)
    sc = o["setCard"]
    ok(sc[0] == {"type": "tap_text", "text": "A"} and sc[1] == {"type": "tap_text", "text": "A", "near": "CHF 2.30", "scroll": "left"} and sc[2] == {"type": "tap_text", "text": "A", "near": "B"},
       "lưu: để trống thì bỏ hẳn các tuỳ chọn (bước như cũ); «ngay dưới» là mặc định nên không ghi; giá trị lạ bị bỏ", sc)
    lg = o["legacyDir"]
    ok(lg[0].get("near_dir") == "above" and lg[1] is True and "không còn dùng" in lg[2] and "ngay dưới" not in lg[2],
       "bước còn hướng CŨ («above»): mở ra lưu lại KHÔNG bị đổi lặng lẽ thành «ngay dưới» (đảo nghĩa) — giữ nguyên, câu của bước báo phải chọn lại", lg)

    ok(o["atParse"] == [{"text": "Sign Players", "at": [667, 571]}, {"text": "A", "at": [12, 34]}, {"text": "B", "tap": "@-1,5"}, {"text": "C", "tap": "@x,y"}]
       and o["atLines"][:2] == ["Sign Players => @667,571", "A => @12,34"],
       "gõ «=> @x,y»: trường hợp BẤM TẠI TOẠ ĐỘ; toạ độ sai dạng thì vẫn là bấm vào chữ như đã gõ; mở ra sửa hiện lại đúng dòng", o["atParse"])
    ok("bấm tại <b>(667, 571)</b>" in o["atSentence"][0] and "bấm tại" not in o["atSentence"][1] and "<img" not in o["atSentence"][1] and o["atSentence"][2] == "“A” → (1, 2) (3s)",
       "câu của bước nói «bấm tại (x, y)»; toạ độ lạ không in ra", o["atSentence"])
    ok(o["ifAt"] == [[1, 2], None, None, None, None, None] and "bấm tại" not in o["atSentence"][3],
       "toạ độ hợp lệ = hai số nguyên không âm (< 10000); toạ độ âm / thừa số / số lẻ → không coi là «bấm tại»", o["ifAt"])
    ok(o["until"][0].endswith('<span class="flow-dim">chờ tối đa 60 giây · xong khi thấy «Shop»</span>') and "<img" not in o["until"][1] and "&lt;img" in o["until"][1],
       "câu của bước có điều kiện nói «xong khi thấy …»; chữ lạ được thoát", o["until"])
    print("== 8. Trang «Theo dõi» ==")
    ok(o["monDur"] == ["0 giây", "6 giây", "1 phút", "1 phút", "2 phút 10 giây", "1 giờ", "1 giờ 3 phút", "0 giây", "0 giây"], "khoảng thời gian viết thành chữ đọc được; số âm / chữ lạ → 0 giây", o["monDur"])
    ok(o["monResult"] == [["Hoàn tất", "ok"], ["Thất bại", "bad"], ["Chờ đối soát", "warn"], ["Bộ chạy lỗi giữa chừng", "bad"], ["Gateway đã đóng đơn", "mut"], ["Gateway đã đóng đơn", "mut"]],
       "kết quả của đơn → nhãn + màu; giá trị lạ không được in ra", o["monResult"])
    ok(o["monItems"] == ["1050 Coins ×2, starter ×1, ? ×1", "", ""], "gói của đơn viết thành «tên ×số lượng»", o["monItems"])
    ml = o["monLive"]
    ok(ml[0] is None and ml[1]["head"] == "nhận đơn — Nhóm A · nạp Efootball — đơn T-7" and ml[1]["step"] == "Đăng nhập · bước 5/16 — Bấm vào chữ «Login»" and ml[1]["running"] is True and ml[1]["since"] == 100,
       "máy ĐANG chạy: «nhận đơn — nhóm · kịch bản — đơn …» + «giai đoạn · bước 5/16 — tên bước»", ml[1])
    ok(ml[2]["running"] is False and ml[2]["ok"] is False and ml[2]["step"] == "bước 1 — Tap chữ «Shop»" and ml[2]["msg"] == "không thấy chữ" and ml[3]["step"] == "Mua một gói",
       "máy vừa xong một bước: hiện bước đó kèm kết quả / lý do; chưa có bước nào thì hiện giai đoạn", ml[2:])
    ok(o["monGroup"] == [["r2", True, False, 0], ["r1", True, True, 4], [None, False, False, 1]] and o["monGroupBad"] == [0, 0],
       "lịch sử gom theo TỪNG LƯỢT CHẠY, lượt mới nhất đứng trước; bước lẻ thành một khối riêng; dữ liệu rác bị bỏ", o["monGroup"])
    h = o["monHtml"] + o["monBlocks"] + o["monEmpty"]
    ok("<img" not in h and h.count("&lt;img") >= 6 and "Chờ đối soát" in o["monHtml"] and "Đăng nhập 2/5" in o["monHtml"] and "đang chạy" in o["monBlocks"]
       and "Thao tác lẻ" in o["monBlocks"] and "nhận đơn — G · S" in o["monBlocks"],
       "mọi chữ lấy từ lịch sử (tên bước, lý do, tên gói, lời nhắn) đều được thoát; khối đang chạy có nhãn «đang chạy»", h[:300])
    import re as _re
    ok(_re.fullmatch(r"\d\d:\d\d:\d\d", o["monClock"][0]) and _re.fullmatch(r"\d\d/\d\d \d\d:\d\d:\d\d", o["monClock"][1]), "giờ hiện dạng HH:MM:SS (kèm ngày/tháng ở đầu khối)", o["monClock"])

    print("== 7. «Nhấn phím» trong bước có điều kiện; mở mới app; gõ từng ký tự; «Chạy lại» ==")
    ok(o["keyParse"] == [{"text": "lưu mật khẩu này", "key": "esc"}, {"text": "Game Center", "tap": "Hủy"}, {"text": "x", "key": "enter"}, {"text": "y", "key": "tab"},
                         {"text": "z", "tap": "phím f13"}, {"text": "w", "tap": "phím"}, {"text": "v", "tap": "phím delete"}],
       "gõ «=> phím esc» (hoặc «key», không dấu): thành trường hợp NHẤN PHÍM; phím lạ / thiếu tên phím thì vẫn là «bấm vào chữ» như đã gõ", o["keyParse"])
    ok(o["keyLines"][:4] == ["lưu mật khẩu này => phím esc", "Game Center => Hủy", "x => phím enter", "y => phím tab"], "mở bước ra sửa: mỗi trường hợp hiện lại đúng một dòng như lúc gõ", o["keyLines"])
    ks = o["keySentence"]
    ok(ks[0].startswith("Nếu thấy chữ <b>«lưu mật khẩu này»</b> thì nhấn phím <b>esc</b>") and "nhấn phím <b>esc</b><br>Nếu thấy chữ <b>«B»</b> thì bấm <b>«C»</b>" in ks[1]
       and "<img" not in ks[2] and "nhấn phím" not in ks[2] and ks[3] == "“A” → phím esc (3s)",
       "câu của bước nói «nhấn phím …»; phím lạ trong dữ liệu không được đưa vào trang (coi như bấm chính chữ đó)", ks)
    ok(o["keyCases"] == [[{"text": "A", "key": "esc"}], "esc", "", ""], "bước một trường hợp ghi gọn `text` + `key`; tên phím được chuẩn hoá, phím lạ → rỗng", o["keyCases"])
    ok(o["fresh"] == ['Mở app <b>efootball</b> <span class="flow-dim">tắt hẳn rồi mở mới</span>', "Mở app <b>efootball</b>", "efootball (mở mới)", "efootball"], "câu của «Mở app» nói rõ khi chọn tắt hẳn rồi mở mới", o["fresh"])
    ok("từng ký tự, cách nhau 0.4 giây" in o["gap"][0] and "từng ký tự" not in o["gap"][1] and "từng ký tự" not in o["gap"][2] and "<img" not in o["gap"][2], "câu của «Gõ chữ» nói rõ khi gõ từng ký tự; giá trị lạ không được in ra", o["gap"])
    ok(o["rerun"] == [True, False, False, False, False, False, False],
       "«Chạy lại» chỉ hiện cho máy đang DỪNG CHỜ KIỂM TRA sau đơn của CHÍNH nhóm + kịch bản nhận đơn đang mở (không phải kịch bản khác, nhóm khác, máy đang chạy, máy không giữ, kịch bản thường)", o["rerun"])

    print("== 10. Kịch bản nhận đơn: bước chỉ nằm trong kịch bản; chép một lần bước đời cũ từ gateway ==")
    phases = ["login", "otp", "nav", "purchase", "after", "finish"]
    ls = o["lists"]
    ok(ls["keys"] == phases and ls["sameArrays"] is True and ls["counts"] == [0, 0, 0, 1, 0, 0]
       and ls["labels"] == ["Đăng nhập", "Nhập OTP", "Vào danh sách gói", "Mua một gói", "Sau mỗi lần mua", "Kết thúc đơn"],
       "sáu giai đoạn theo thứ tự chạy; bước của mỗi giai đoạn là ĐÚNG danh sách ghi trong kịch bản — pool có kèm bước cũng không được mượn", ls)
    ok(ls["required"] == ["login", "purchase", "finish"] and ls["extra"] == ["help", "key", "label", "required", "steps"],
       "giai đoạn bắt buộc: Đăng nhập, Mua một gói, Kết thúc đơn; không còn số «bước của gateway» đi kèm giai đoạn", [ls["required"], ls["extra"]])
    ok(o["listsPlain"] == [["", True]], "kịch bản thường: một danh sách bước duy nhất", o["listsPlain"])
    ok(o["missPool"] == ["pool chưa có luật <b>«Nạp &lt;b&gt;»</b> (thêm ở trang quản trị gateway → Pool → mục 3)",
                         "chưa có bước cho giai đoạn <b>«Đăng nhập»</b>", "chưa có bước cho giai đoạn <b>«Kết thúc đơn»</b>"],
       "dòng «còn thiếu»: luật pool chưa có (tên luật được thoát) + MỌI giai đoạn bắt buộc đang trống trong kịch bản, dù pool trên gateway có bước cho giai đoạn đó", o["missPool"])
    ok(o["missNone"] == [], "giai đoạn bắt buộc nào cũng có bước → không còn lời nhắc về giai đoạn", o["missNone"])
    ok(o["missNoPoolCfg"] == ["chưa có bước cho giai đoạn <b>«Đăng nhập»</b>"] and o["missNoGw"] == ["chưa nối gateway", "chưa có bước cho giai đoạn <b>«Đăng nhập»</b>"],
       "chưa đọc được pool / chưa nối gateway: giai đoạn bắt buộc đang trống vẫn được nhắc (không còn chờ xem gateway có bước hay không)", [o["missNoPoolCfg"], o["missNoGw"]])
    ok(o["copiedFlag"] == [False, True, False, False, True],
       "dấu «đã chép bước đời cũ» (gw_steps_copied): mặc định chưa; chỉ đúng `true` mới tính; giữ nguyên qua nạp → lưu → nạp", o["copiedFlag"])
    at = o["adoptText"]
    ok(at[0] == "Đã chép 5 bước cũ từ gateway vào kịch bản (Sau mỗi lần mua: 1, Kết thúc đơn: 4) — từ giờ sửa bước ở đây"
       and at[1] == "Đã chép 12 bước cũ từ gateway vào kịch bản (Đăng nhập: 7, Vào danh sách gói: 3, Kết thúc đơn: 2) — từ giờ sửa bước ở đây" and at[2:] == ["", "", ""],
       "lời báo sau khi chép: tổng số bước + từng giai đoạn theo thứ tự chạy; giai đoạn lạ / số lạ bị bỏ; không chép bước nào → không báo", at)

    print("== 11. MỘT bảng loại bước: giao diện, ảnh mẫu, lời mô tả cho AI đều khớp bộ chạy (stepexec.STEP_TYPES) ==")
    import inspect
    sys.path.insert(0, os.path.dirname(HERE))
    import jobflow, stepexec, screencheck, store
    app_dir = os.path.dirname(HERE)
    js = ui_source()
    html = open(os.path.join(app_dir, "web", "index.html"), encoding="utf-8").read()
    body_of = lambda name: const_source(js, name).split("=", 1)[1]
    arr = lambda name: json.loads(body_of(name).strip().rstrip(";"))
    types = set(stepexec.STEP_TYPES)
    label_keys, kind_keys = set(re.findall(r"([a-z_]+): \"", body_of("STEP_LABEL"))), set(re.findall(r"([a-z_]+): \[", body_of("STEP_KIND")))
    palette = set(re.findall(r'data-add="([a-z_]+)"', html)) - {"pick"}            # «pick» = bấm lên ảnh để thêm bước tap
    ok(len(stepexec.STEP_TYPES) == len(types) == 15 and label_keys == types and kind_keys == types and palette | {"tap"} == types,
       "mọi loại bước của bộ chạy đều có nhãn + biểu tượng + nút trong bảng chọn của trình sửa; giao diện không có loại nào bộ chạy không biết",
       {"thiếu nhãn": sorted(types - label_keys), "nhãn lạ": sorted(label_keys - types), "thiếu nút": sorted(types - palette - {"tap"}), "nút lạ": sorted(palette - types)})
    import glob
    from test_ui_controls import page_scripts
    on_disk = {os.path.basename(f) for f in glob.glob(os.path.join(app_dir, "web", "*.js"))} - {"_mock.js"}
    ok(set(page_scripts()) == on_disk and len(page_scripts()) == len(set(page_scripts())),
       "mọi tệp .js của giao diện đều được trang nạp (đúng một lần) — không tệp nào nằm đó mà không chạy", sorted(on_disk ^ set(page_scripts())))
    test_html = open(os.path.join(app_dir, "web", "_test.html"), encoding="utf-8").read()
    ok(set(re.findall(r'data-add="([a-z_]+)"', test_html)) == palette | {"pick"}, "trang thử (_test.html) có đúng bảng chọn hành động của trang thật")

    # Mỗi loại trong bảng phải có NHÁNH THẬT trong bộ chạy. Gọi bộ chạy với một máy «chạm vào là nổ»: vào đúng nhánh thì hoặc chạm máy (Touched),
    # hoặc xong, hoặc báo lỗi cấu hình KHÁC «loại bước lạ». Ngược lại, bộ chạy không được có nhánh cho loại nằm ngoài bảng.
    class Touched(Exception):
        pass

    class Boom:
        def __getattr__(self, name):
            raise Touched(name)
    minimal = {"tap": {"x": 1, "y": 1}, "tap_text": {"text": "a"}, "tap_image": {"image": "x"}, "tap_if": {"text": "a", "tap": "b"}, "type": {"text": "a"},
               "key": {"name": "enter"}, "combo": {"keys": "gui h"}, "home": {}, "launch": {"app": "a"}, "wait": {"seconds": 0}, "wait_text": {"text": "a"},
               "assert_text": {"text": "a"}, "swipe": {"dir": "left"}, "hold": {"x": 1, "y": 1}, "hold_text": {"text": "a"}}

    def enters(step):                # → "" nếu bộ chạy có nhánh cho bước này, không thì lời lỗi «loại bước lạ»
        try:
            stepexec._exec_step(Boom(), step, {})
        except stepexec.ConfigError as e:
            return str(e) if "loại bước lạ" in str(e) else ""
        except Exception:
            pass
        return ""
    real_sleep, stepexec._sleep = stepexec._sleep, (lambda *a, **k: None)
    try:
        lost = [t for t in stepexec.STEP_TYPES if enters(dict(minimal[t], type=t))]
        unknown = enters({"type": "loai_la"})
        run_src = inspect.getsource(stepexec._exec_step)
        branches = set(re.findall(r'"([a-z_]+)"', " ".join(re.findall(r"^    if t (?:==|in) ([^\n]*?):", run_src, re.M))))
        ok(sorted(minimal) == sorted(stepexec.STEP_TYPES) and lost == [] and branches == types and "loại bước lạ" in unknown,
           "bộ chạy có nhánh THẬT cho đủ các loại trong bảng và không có nhánh nào ngoài bảng; loại lạ → báo lỗi cấu hình (không lặng lẽ bỏ qua)",
           {"mất nhánh": lost, "nhánh ngoài bảng": sorted(branches - types), "thiếu trong bộ chạy": sorted(types - branches)})

        # bước bấm / giữ theo toạ độ mà THIẾU toạ độ → lỗi cấu hình trước khi chạm máy (không bao giờ bấm bừa vào 0,0)
        def refuses(step):
            try:
                stepexec._exec_step(Boom(), step, {})
            except stepexec.ConfigError as e:
                return "toạ độ" in str(e)
            except Exception:
                return False
            return False
        ok(all(refuses(st) for st in ({"type": "tap"}, {"type": "tap", "text": "Mua"}, {"type": "tap", "x": "a", "y": 1}, {"type": "hold", "seconds": 1}, {"type": "hold", "x": 5})),
           "bước «bấm / bấm giữ theo toạ độ» thiếu x, y (hoặc không phải số) → lỗi cấu hình, KHÔNG chạm vào máy")
        sec = stepexec._seconds
        bad_sec = None
        try:
            sec({"seconds": "abc"}, "seconds", 1.0, "Chờ")
        except stepexec.ConfigError as e:
            bad_sec = str(e)
        ok(sec({"seconds": 0}, "seconds", 1.0, "x") == 0.0 and sec({}, "seconds", 1.0, "x") == 1.0 and sec({"seconds": ""}, "seconds", 2.5, "x") == 2.5
           and sec({"seconds": "1.5"}, "seconds", 1.0, "x") == 1.5 and bad_sec and "số giây" in bad_sec,
           "số giây ghi 0 là 0 (không bị coi là «không ghi»); không ghi → mặc định; không phải số → lỗi cấu hình")
    finally:
        stepexec._sleep = real_sleep
    ok(arr("SCREEN_TYPES") == list(screencheck.CHECK_TYPES) and set(screencheck.CHECK_TYPES) <= types and set(stepexec.INPUT_TYPES) <= types,
       "loại bước có ảnh mẫu trong giao diện = screencheck.CHECK_TYPES; các bảng con (bước chạm máy, bước có ảnh mẫu) nằm trong bảng gốc", arr("SCREEN_TYPES"))
    js_phases = re.findall(r'\["([a-z]+)",', body_of("API_PHASES"))
    ok(js_phases == list(jobflow.PHASES) == list(store.API_PHASES) and arr("REQUIRED_PHASES") == list(jobflow.REQUIRED_PHASES)
       and set(re.findall(r"([a-z]+):", body_of("ORDER_LABEL"))) == set(jobflow.PHASES),
       "sáu giai đoạn của đơn + ba giai đoạn bắt buộc: giao diện, kho lưu và bộ chạy cùng một danh sách, cùng thứ tự", (js_phases, arr("REQUIRED_PHASES")))
    ok(set(arr("IF_KEYS")) <= set(stepexec.KEYS), "phím chọn được ở bước có điều kiện đều là phím bộ chạy nhận", arr("IF_KEYS"))

    # «chờ thấy chữ» không ghi thời gian: MỘT con số — trình sửa hiện / điền sẵn bao nhiêu thì bộ chạy chờ đúng bấy nhiêu
    in_text = re.findall(r'case "wait_text":[^\n]*s\.timeout \|\| (\d+)', js)
    in_form = re.findall(r'label: "Chờ tối đa \(giây\)", value: String\(c\.timeout \?\? (\d+)\)', js)
    in_save = re.findall(r"s\.text = r\.text; s\.timeout = parseFloat\(r\.timeout\) \|\| (\d+)", js)
    import types as types_mod

    class Blank:                     # màn hình không bao giờ có chữ cần chờ
        class e:
            screenshot = staticmethod(lambda: None)
            read_text = staticmethod(lambda img=None: "")
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 4.0
        return clock["t"]
    real_time, real_sleep2, real_park = stepexec.time, stepexec._sleep, stepexec.park
    stepexec.time, stepexec._sleep, stepexec.park = types_mod.SimpleNamespace(time=tick, sleep=lambda s: None), (lambda *a, **k: None), (lambda nav: None)
    try:
        dflt = stepexec._exec_step(Blank(), {"type": "wait_text", "text": "zzz"}, {})
        zero = stepexec._exec_step(Blank(), {"type": "wait_text", "text": "zzz", "timeout": 0}, {})
    finally:
        stepexec.time, stepexec._sleep, stepexec.park = real_time, real_sleep2, real_park
    want = str(stepexec.WAIT_TEXT_TIMEOUT)
    ok(len(in_text) == 2 and len(in_form) == 1 and len(in_save) == 1 and set(in_text + in_form + in_save) == {want}
       and dflt[0] is False and ("chờ %ss không thấy" % want) in dflt[1] and zero[0] is False and "chờ 0s không thấy" in zero[1],
       "bước «chờ thấy chữ» không ghi thời gian: câu của bước, ô điền sẵn, giá trị ghi khi để trống và thời gian bộ chạy THẬT SỰ chờ là cùng một con số; ghi 0 = nhìn một lần",
       (in_text, in_form, in_save, dflt, zero))
    ctl = open(os.path.join(app_dir, "control.py"), encoding="utf-8").read()
    desc = ctl[ctl.index('Tool("run_steps"'):ctl.index('Tool(', ctl.index('Tool("run_steps"') + 10)]
    undocumented = [t for t in stepexec.STEP_TYPES if not re.search(r"(?<![a-z_])%s%s" % (t, r"(?![a-z_])" if t == "home" else r" \{"), desc)]
    ok(undocumented == [], "lời mô tả công cụ run_steps cho AI nêu đủ mọi loại bước kèm tham số của nó (dạng «tên {…}»)", undocumented)

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
