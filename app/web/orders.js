// orders.js — phần RIÊNG của KỊCH BẢN NHẬN ĐƠN (cách chạy «orders»: máy chờ đơn của gateway rồi chạy các bước theo từng giai đoạn của đơn):
// các giai đoạn + dữ liệu của đơn dùng được trong bước, thử một giai đoạn, trạm chọn pool + dòng «còn thiếu gì», chép một lần bước đời cũ
// từ gateway (adoptGwSteps / applyAdopted), đổi cách chạy của kịch bản, và kết nối Topup Gateway (cấu hình, danh sách pool, dòng «tự báo»).

/* ---- KỊCH BẢN NHẬN ĐƠN: cách chạy «orders» — máy chờ gateway → có đơn thì tool giữ chỗ cho máy → chạy các bước theo giai đoạn của đơn ---- */
const ORDER_LABEL = { login: "Đăng nhập", otp: "Nhập OTP", nav: "Vào danh sách gói", purchase: "Mua một gói", after: "Sau mỗi lần mua", finish: "Kết thúc đơn" };
// giai đoạn BẮT BUỘC: không có bước thì máy không nhận đơn
const REQUIRED_PHASES = ["login", "purchase", "finish"];
function scriptOrders() {            // kịch bản đang sửa nếu nó là kịch bản nhận đơn, không thì null
  const sc = (GROUP && GROUP_SUB === "script") ? currentScript() : null;
  return sc && sc.mode === "orders" ? sc : null;
}
function ordersCfg() {               // cấu hình nhận đơn của kịch bản đang sửa (không phải kịch bản nhận đơn → null)
  const sc = scriptOrders();
  return sc ? sc.orders : null;
}
// Dữ liệu của ĐƠN dùng được trong các bước của một danh sách (giai đoạn): {items: [{name, label, secret}], note}; không phải kịch bản
// nhận đơn → null. Tên các trường đăng nhập do POOL trên gateway quy định (mỗi game một khác) nên phải đọc được pool mới liệt kê — KHÔNG
// đoán tên: bước dùng một trường mà đơn không có thì máy dừng đơn đó. `only` = chỉ lấy các tên bắt đầu bằng tiền tố này.
function orderVars(list, only) {
  const cfg = ordersCfg();
  if (!cfg) return null;
  const phase = (API_PHASES.find(([k]) => cfg.steps[k] === list) || [""])[0];
  const known = !!(GW_POOL && GW_POOL.code === cfg.pool);
  const items = (known && Array.isArray(GW_POOL.login_fields) ? GW_POOL.login_fields : [])
    .filter(f => f && typeof f.key === "string" && /^[A-Za-z0-9_.]+$/.test(f.key))
    .map(f => ({ name: f.key, label: String(f.label || f.key), secret: !!f.secret }));
  if (phase === "otp") items.push({ name: "otp", label: "Mã OTP khách gửi", secret: true });
  if (phase === "purchase" || phase === "after") {
    items.push({ name: "package.ocr_text", label: "Chữ của gói", secret: false }, { name: "package.price_text", label: "Giá của gói", secret: false },
               { name: "package.name", label: "Tên gói", secret: false });
  }
  if (only) { const some = items.filter(v => v.name.startsWith(only)); return some.length ? { items: some, note: "" } : null; }
  const note = known ? "" : cfg.pool ? "Chưa đọc được pool trên gateway nên chưa biết đơn có những trường đăng nhập nào."
                                     : "Chọn pool ở trạm «Chờ đơn» để thấy các trường đăng nhập của đơn.";
  return { items, note };
}
function scriptStepCount(sc) {
  return sc.mode === "orders" && sc.orders ? API_PHASES.reduce((n, [k]) => n + sc.orders.steps[k].length, 0) : sc.steps.length;
}
// Các DANH SÁCH BƯỚC đang hiện trong trình sửa, theo thứ tự chạy: kịch bản thường có một; kịch bản nhận đơn có sáu (mỗi giai đoạn của đơn một danh sách).
// Bước của một giai đoạn chỉ là các bước ghi trong kịch bản — giai đoạn trống thì không có bước nào để chạy.
function flowLists() {
  const sc = scriptOrders();
  if (!sc) return [{ key: "", steps: FLOW.steps }];
  return API_PHASES.map(([k, help]) => ({ key: k, label: ORDER_LABEL[k], help, steps: sc.orders.steps[k], required: REQUIRED_PHASES.includes(k) }));
}

// Thử MỘT giai đoạn của kịch bản nhận đơn trên máy đang chọn.
async function testPhase(l, btn) {
  if (!SEL) { toast("Chọn máy để thử ở khung màn hình", "warn"); return; }
  const steps = l.steps;
  if (!steps.length) { toast("Giai đoạn này chưa có bước nào để thử", "warn"); return; }
  if (l.key === "purchase" && !confirmBox("Thử giai đoạn «Mua một gói» sẽ BẤM MUA THẬT trên máy đang chọn — có thể trừ tiền / tiêu gói của tài khoản đang đăng nhập trên máy đó.\n\nVẫn chạy thử?")) return;
  busy(btn, true);
  steps.forEach(s => STEP_RES.delete(s));
  log(`▶ Chạy thử giai đoạn «${l.label}» trên ${SEL}`);
  try {
    const results = await runApiSteps(steps);
    if (results) {
      let okN = 0;
      results.forEach(x => { if (x.ok) okN++; log(`   [${x.i + 1}] ${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad"); if (steps[x.i]) STEP_RES.set(steps[x.i], { ok: !!x.ok, msg: x.msg }); });
      adoptScreens(steps, results);
      toast(`${SEL}: ${okN}/${steps.length} bước OK`, okN === steps.length ? "ok" : "warn");
      setTimeout(() => shot(null), 600);
    }
  } catch (e) { log("✗ " + e, "bad"); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  renderSteps();
}

// Trạm «Chờ đơn từ gateway»: chọn pool mà kịch bản nhận đơn này phục vụ
function renderOrdersPool() {
  const sel = $("#flow-pool"), sc = scriptOrders();
  if (!sel || !sc) return;
  const cur = sc.orders.pool || "";
  const opts = [`<option value="">— chọn pool —</option>`]
    .concat(GW.pools.map(p => `<option value="${esc(p.code)}">${esc(p.name || p.code)}${p.active === false ? " (tạm dừng)" : ""}</option>`));
  if (cur && !GW.pools.some(p => p.code === cur)) opts.push(`<option value="${esc(cur)}">${esc(cur)} (không thấy trên gateway)</option>`);
  sel.innerHTML = opts.join("");
  sel.value = cur;
  sel.onchange = (e) => { sc.orders.pool = e.target.value; GW_POOL = null; updateDirty(); loadGwPool(); };
  const note = $("#flow-pool-note");
  note.innerHTML = (!GW.url || !GW.has_key) ? `<a href="#" id="flow-gw-link">Nối gateway trước</a>`
    : GW.ok === false ? `<span class="text-danger">gateway lỗi: ${esc(GW.error)}</span>` : "";
  const a = $("#flow-gw-link");
  if (a) a.onclick = (ev) => { ev.preventDefault(); gatewaySettings(); };
}
// Kịch bản nhận đơn `sc` còn thiếu gì thì máy chưa nhận đơn được → danh sách lời nhắc (HTML đã thoát); đủ cả thì rỗng.
// Giai đoạn bắt buộc phải có bước NGAY TRONG kịch bản (không còn nguồn bước nào khác).
function ordersMissing(sc) {
  const miss = [];
  if (!GW.url || !GW.has_key) miss.push("chưa nối gateway");
  else if (!sc.orders.pool) miss.push("chưa chọn pool ở trạm «Chờ đơn từ gateway»");
  else if (GW_POOL && GW_POOL.code === sc.orders.pool) {
    (GW_POOL.missing_rules || []).forEach(r => miss.push(`pool chưa có luật <b>«${esc(r)}»</b> (thêm ở trang quản trị gateway → Pool → mục 3)`));
  }
  REQUIRED_PHASES.forEach(k => { if (!sc.orders.steps[k].length) miss.push(`chưa có bước cho giai đoạn <b>«${esc(ORDER_LABEL[k])}»</b>`); });
  return miss;
}
// Dòng cảnh báo phía trên lộ trình: kịch bản nhận đơn còn thiếu gì thì máy chưa nhận đơn được
function renderOrdersUi() {
  const box = $("#orders-warn"), sc = scriptOrders();
  if (!box) return;
  if (!sc) { box.hidden = true; box.innerHTML = ""; return; }
  renderOrdersPool();
  const miss = ordersMissing(sc);
  box.hidden = !miss.length;
  box.innerHTML = miss.length ? `<i class="ti tabler-alert-triangle me-1"></i><b>Máy sẽ KHÔNG nhận đơn</b> cho tới khi bổ sung: ${miss.join("; ")}.` : "";
}
// Hàng tuỳ chọn riêng của kịch bản nhận đơn (dưới dải «Chạy»): chờ kết quả đăng nhập / mua tối đa bao lâu + có kiểm bàn phím lúc bắt đầu không
function renderOrdersOpts(sc) {
  const on = !!(sc && sc.mode === "orders" && sc.orders);
  $("#script-orders-opts").hidden = !on;
  if (!on) return;
  $("#orders-login-wait").value = sc.orders.login_wait;
  $("#orders-purchase-wait").value = sc.orders.purchase_wait;
  $("#orders-kb").checked = sc.orders.check_keyboard;
}

/* ---- bước đời cũ còn lưu ở pool trên gateway: backend chép MỘT LẦN vào các giai đoạn còn trống của kịch bản rồi đánh dấu `gw_steps_copied` ---- */
// Lời báo sau một lần chép: copied = {giai đoạn: số bước}; không chép bước nào → "".
function adoptedText(copied) {
  const parts = API_PHASES.map(([k]) => [k, Number((copied || {})[k]) || 0]).filter(([, n]) => n > 0);
  if (!parts.length) return "";
  return `Đã chép ${parts.reduce((s, [, n]) => s + n, 0)} bước cũ từ gateway vào kịch bản (${parts.map(([k, n]) => `${ORDER_LABEL[k]}: ${n}`).join(", ")}) — từ giờ sửa bước ở đây`;
}
// Backend vừa chép (orders_adopt, hoặc ngay trước khi chạy kịch bản): r = {copied, group: bản mới của nhóm}. Thay nhóm trong GROUPS rồi nạp lại
// nhóm đang mở từ bản đó (vẫn ở trang con đang xem). Đang sửa dở (có thay đổi chưa lưu / hộp thoại sửa bước đang mở) thì giữ bản đang sửa:
// lúc lưu, backend giữ lại các giai đoạn lần chép đã điền mà bản đang sửa còn để trống, rồi trình sửa nạp lại bản đã lưu (saveGroupSilent).
function applyAdopted(r) {
  const g = r && r.group, i = g ? GROUPS.findIndex(x => x.id === g.id) : -1;
  if (i < 0) return;
  GROUPS[i] = g;
  if (GROUP && GROUP.id === g.id) {
    if (groupDirty() || !$("#modal").hidden) return;
    selectGroup(g.id);
  }
  const msg = adoptedText(r.copied);
  if (msg) toast(msg, "ok");
}
// Hỏi backend chép cho kịch bản nhận đơn đang mở — chỉ khi nó chưa được đánh dấu, đã chọn pool, gateway đang nối và nhóm không có thay đổi
// chưa lưu (đang sửa dở thì thôi: lưu xong sẽ hỏi lại). Backend không chép được (vd gateway không trả lời) → im lặng, lần sau hỏi lại.
const ADOPTING = new Set();          // "<nhóm>/<kịch bản>" đang chờ backend trả lời (không hỏi chồng)
async function adoptGwSteps() {
  const sc = scriptOrders();
  if (!sc || sc.orders.gw_steps_copied || !sc.orders.pool || GW.ok !== true || groupDirty()) return;
  const gid = GROUP.id, key = gid + "/" + sc.id;
  if (ADOPTING.has(key)) return;
  ADOPTING.add(key);
  try {
    let r = null;
    try { r = await API().orders_adopt(gid, sc.id); } catch (e) {}
    if (r && r.ok) applyAdopted(r);                      // (nạp lại nhóm trong lúc còn giữ khoá ở trên → không tự hỏi lại lần nữa)
    else if (r && r.blocked) toast(r.error, "warn");     // bước đời cũ ở gateway sai dạng → nói rõ cho người vận hành (máy sẽ không chạy cho tới khi xử lý)
  } finally { ADOPTING.delete(key); }
}
// Đổi cách chạy của kịch bản. Sang «nhận đơn»: các bước đang có thành giai đoạn «Đăng nhập» (mở game là việc đầu tiên của một đơn).
// Về lại «1 lần» / «lặp»: nếu chỉ giai đoạn «Đăng nhập» có bước thì các bước đó quay về làm danh sách bước của kịch bản.
function setScriptMode(sc, mode) {
  const was = sc.mode;
  sc.mode = mode === "loop" || mode === "orders" ? mode : "once";
  if (sc.mode === "orders") {
    sc.orders = normApi(sc.orders);
    if (was !== "orders" && sc.steps.length && API_PHASES.every(([k]) => !sc.orders.steps[k].length)) { sc.orders.steps.login = sc.steps; sc.steps = []; }
  } else {
    if (was === "orders" && sc.orders && !sc.steps.length && API_PHASES.every(([k]) => k === "login" || !sc.orders.steps[k].length)) {
      sc.steps = sc.orders.steps.login; sc.orders.steps.login = [];
    }
    if (was !== sc.mode) sc.loops = sc.mode === "loop" ? 0 : 1;
  }
}

/* ---- kịch bản nhận đơn: các giai đoạn của 1 đơn nạp (mỗi giai đoạn 1 danh sách bước) — [khoá, lời dẫn] ---- */
const API_PHASES = [
  ["login",    "Mở game và đăng nhập tài khoản của khách. Biến: {{username}} {{password}} (mọi trường đăng nhập của pool)."],
  ["otp",      "Chạy khi game đòi OTP và khách đã gửi mã. Biến: {{otp}}. Để trống = gõ mã rồi Enter."],
  ["nav",      "Từ màn hình sau đăng nhập đi tới danh sách gói nạp."],
  ["purchase", "Mua MỘT gói, lặp theo số lượng. Dừng ở màn hình báo kết quả (tool chụp bill ở đó). Biến: {{package.ocr_text}} {{package.price_text}} {{package.name}}."],
  ["after",    "Sau mỗi lần mua được: đóng thông báo, quay lại danh sách gói để mua tiếp."],
  ["finish",   "Sau khi báo kết quả: đăng xuất, về màn hình chính — để máy sẵn sàng cho đơn sau."],
];
let GW = { url: "", has_key: false, key_hint: "", ok: null, error: "", pools: [] };
let GW_POOL = null;                    // cấu hình pool của kịch bản nhận đơn đang mở (trường đăng nhập của đơn, luật còn thiếu)
let TEST_VARS = {};                    // giá trị thử cho {{biến}} (chỉ giữ trong phiên, không lưu)

function normApi(a) {
  a = a || {};
  const steps = {};
  API_PHASES.forEach(([k]) => { steps[k] = Array.isArray((a.steps || {})[k]) ? a.steps[k] : []; });
  return { pool: a.pool || "", steps, login_wait: a.login_wait || 45, purchase_wait: a.purchase_wait || 60,
           check_keyboard: a.check_keyboard !== false, gw_steps_copied: a.gw_steps_copied === true };
}

function setGwState() {
  const dot = $("#gw-dot");
  if (dot) dot.className = "gw-dot " + (GW.ok === true ? "ok" : GW.ok === false ? "bad" : "");
}

// Dòng «tự báo gateway»: tool tự gửi lên gateway máy nào rảnh ở kịch bản nào + danh mục kịch bản (gateway không gọi được vào tool).
let GW_SYNC_SIG = "";
function gwSyncHtml(st) {
  if (!st || st.configured === false) return "";                                   // chưa cấu hình gateway → nút Gateway đã nói rồi
  const link = ` <a href="#" id="gw-sync-now" title="Gửi ngay thay vì chờ nhịp kế (~20 giây)">báo ngay</a>`;
  if (st.ok === false) return `<span class="text-danger">Chưa báo được cho gateway:</span> ${esc(st.error || "?")} ·${link}`;
  if (st.ok !== true) return `Đang báo cho gateway…`;
  const at = st.at ? new Date(st.at * 1000).toLocaleTimeString("vi-VN", { hour12: false }) : "";
  return `<span class="text-success">●</span> Đã báo gateway lúc <b>${esc(at)}</b>: ${st.devices} máy (<b>${st.idle} rảnh</b>) · ${st.scripts} kịch bản ·${link}`;
}
async function refreshGwSync(now = false) {
  const el = $("#gw-sync");
  if (!el) return;
  let st = null;
  try { st = await API().gateway_sync(!!now); } catch (e) { return; }
  const html = gwSyncHtml(st);
  const sig = html;
  if (sig === GW_SYNC_SIG) return;                                                  // không vẽ lại khi không đổi (giữ cú bấm đang dở)
  GW_SYNC_SIG = sig;
  el.hidden = !html;
  el.innerHTML = html;
  const a = $("#gw-sync-now");
  if (a) a.onclick = (ev) => { ev.preventDefault(); toast("Đang báo cho gateway…"); refreshGwSync(true); setTimeout(() => refreshGwSync(), 2500); };
}

async function loadGateway() {
  try { Object.assign(GW, await API().gateway_get()); } catch (e) {}
  if (!GW.url || !GW.has_key) { GW.ok = null; GW.pools = []; setGwState(); renderOrdersUi(); return; }
  GW.ok = null; setGwState();
  try {
    const r = await API().gateway_pools();
    GW.ok = !!(r && r.ok); GW.error = (r && r.error) || ""; GW.pools = (r && r.pools) || [];
  } catch (e) { GW.ok = false; GW.error = String(e); GW.pools = []; }
  setGwState();
  if (ordersCfg()) loadGwPool(); else renderOrdersUi();
}

// Nạp cấu hình pool của kịch bản nhận đơn đang mở (gọi khi mở kịch bản, đổi pool, vừa nối gateway, vừa lưu xong) rồi vẽ lại lộ trình.
async function loadGwPool() {
  const oc = ordersCfg(), code = oc && oc.pool;
  const redraw = () => { if (scriptOrders()) renderSteps(); else renderOrdersUi(); };
  if (!code || GW.ok !== true) { GW_POOL = null; redraw(); return; }
  if (!GW_POOL || GW_POOL.code !== code) {
    try {
      const r = await API().gateway_pool(code);
      GW_POOL = (r && r.ok) ? r : null;
      if (r && !r.ok) toast("Không tải được pool: " + r.error, "warn");
    } catch (e) { GW_POOL = null; }
  }
  redraw();
  adoptGwSteps();
}

async function gatewaySettings() {
  try { Object.assign(GW, await API().gateway_get()); } catch (e) {}
  const r = await askForm("Kết nối Topup Gateway",
    "Tạo khoá ở trang quản trị gateway → Khoá API → loại «Tool». Khoá chỉ lưu trên máy này.", [
    { key: "url", label: "Địa chỉ gateway", value: GW.url, placeholder: "https://gateway.cua-ban.vn" },
    { key: "key", label: "Khoá Tool (gwt_…)", type: "password", value: "",
      placeholder: GW.has_key ? `để trống = giữ khoá đang lưu (${GW.key_hint})` : "gwt_…" },
  ]);
  if (!r) return;
  try {
    const res = await API().gateway_save(r.url, r.key);
    if (res && res.ok) toast(`Đã nối gateway — khoá «${res.key || "tool"}»`, "ok");
    else toast("Chưa nối được: " + ((res && res.error) || "?"), "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  await loadGateway();
}

// Chạy thử các bước của kịch bản nhận đơn: hỏi giá trị cho {{biến}} rồi chạy bằng đúng bộ chạy lúc nạp thật.
async function runApiSteps(steps) {
  const names = [...new Set((JSON.stringify(steps).match(/\{\{\s*[A-Za-z0-9_.]+\s*\}\}/g) || []).map(s => s.replace(/[{}\s]/g, "")))];
  let vars = {};
  if (names.length) {
    const field = (n) => ((GW_POOL && Array.isArray(GW_POOL.login_fields) ? GW_POOL.login_fields : []).find(f => f && f.key === n)) || {};   // tên dễ đọc của trường, theo pool
    const r = await askForm("Giá trị thử cho dữ liệu của đơn", "Chỉ dùng cho lần chạy thử này, không lưu lại.",
      names.map(n => ({ key: n, label: field(n).label ? `${field(n).label} — {{${n}}}` : `{{${n}}}`, value: TEST_VARS[n] || "",
                        type: (field(n).secret || /pass|otp|pin|secret|token|cookie/i.test(n)) ? "password" : "text" })));
    if (!r) return null;
    vars = r; Object.assign(TEST_VARS, r);
  }
  const res = await API().test_api_steps(SEL, steps, vars);
  if (!res || !res.ok) { log("✗ " + ((res && res.error) || "lỗi"), "bad"); toast((res && res.error) || "Chạy thử lỗi", "bad"); return null; }
  return res.results;
}
