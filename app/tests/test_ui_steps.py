#!/usr/bin/env python3
"""
Kiểm phần LỘ TRÌNH CÁC BƯỚC của trình sửa kịch bản (app/web/app.js) — lấy đúng mã nguồn các hàm, chạy bằng `node`, không cần trình duyệt:
  • mỗi loại bước viết thành một câu; chữ do người dùng / thiết bị đưa vào luôn được thoát HTML; {{biến}} thành nhãn riêng;
  • loại bước lạ (kể cả trùng tên thuộc tính có sẵn như «constructor») không làm hỏng trang;
  • đổi cách chạy của kịch bản sang «nhận đơn» và ngược lại: bước không bị mất, không bị nhân đôi;
  • «bấm lên ảnh để thêm bước chạm»: chèn theo BƯỚC đã chọn (không theo số thứ tự) — xoá / chèn bước khác không làm lệch chỗ;
    kịch bản nhận đơn mà chưa chọn giai đoạn thì không đoán chỗ;
  • ô bấm «Lấy từ đơn» của bước gõ chữ: đúng các trường đăng nhập của pool trên gateway theo từng giai đoạn, không đoán tên khi chưa đọc được pool.

    ./.venv/bin/python app/tests/test_ui_steps.py
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_ui_controls import APP_JS, function_source

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
console.log(JSON.stringify(out));
"""


def main():
    node = shutil.which("node")
    if not node:
        print("BỎ QUA: cần lệnh `node` để chạy mã giao diện.")
        return 0
    src = open(APP_JS, encoding="utf-8").read()
    esc_line = next(l for l in src.splitlines() if l.startswith("const esc ="))
    parts = [esc_line] + [const_source(src, n) for n in ("SWIPE_DIR", "STEP_LABEL", "STEP_KIND", "API_PHASES", "ORDER_LABEL", "TEXT_WAIT_NEW")]
    parts += [function_source(src, n) for n in ("ifCases", "parseIfCases", "stepText", "stepKind", "stepVal", "stepSentence", "normApi", "scriptStepCount", "setScriptMode", "addPicked",
                                                "orderVars", "varChips", "insertAtCursor", "textWaitField", "setTextWait")]
    stubs = ("let FLOW = { steps: [] }; let PICK_TO = null; let ORDERS = null; let RENDERS = 0; const TOASTS = []; let CFG = null; let GW_POOL = null;\n"
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

    print("\n%s" % ("✅ TẤT CẢ %d kiểm tra đều đạt." % PASS if not FAIL else "❌ %d lỗi / %d kiểm tra." % (FAIL, PASS + FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
