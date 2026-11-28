// stepedit.js — THÊM / SỬA bước của kịch bản: bảng chọn hành động (thêm vào cuối hoặc chèn sau một bước), chế độ «bấm lên ảnh để thêm bước»,
// hộp thoại hỏi tham số của từng loại bước (stepPrompt) cùng các ô «chờ chữ» / «trong cùng ô» / «lướt tìm», và «Chạy thử» cả kịch bản.

/* ---- bảng chọn hành động: thêm vào cuối một danh sách, hoặc chèn sau một bước ---- */
function closePalette() {
  const pal = $("#step-palette"), home = $("#flow-add");
  if (!pal || !home) return;
  pal.hidden = true;
  if (pal.parentNode !== home) home.appendChild(pal);
  ADD_TO = null;
  $$(".flow-step.ins-open, .flow-slot.open").forEach(x => x.classList.remove("ins-open", "open"));
  $("#btn-step-add").setAttribute("aria-expanded", "false");
}
function openPalette(to, host) {       // to = {list, at}; host = phần tử để đặt bảng chọn vào (bước vừa bấm dấu +, hoặc chỗ cuối giai đoạn); không có = dưới nút «Thêm bước»
  const pal = $("#step-palette");
  const again = !pal.hidden && ADD_TO && ADD_TO.list === to.list && ADD_TO.at === to.at && to.list.length > 0;     // bấm lại đúng nút đang mở → đóng
  closePalette();
  if (again) return;
  ADD_TO = to;
  if (host) { host.appendChild(pal); host.classList.add(host.classList.contains("flow-slot") ? "open" : "ins-open"); }
  pal.hidden = false;
  if (!host) $("#btn-step-add").setAttribute("aria-expanded", "true");
  const first = $(".pal-item", pal);
  if (first) first.focus();
}
async function pickAction(type) {
  const to = ADD_TO || { list: FLOW.steps, at: null };
  closePalette();
  if (type === "pick") { startPick(to); return; }
  if (type === "tap_image") { startPick(to, true); return; }       // không hỏi gì: kéo một khung quanh nút trên ảnh màn hình
  await addStepPrompt(type, to);
}
function startPick(to, region) {       // «Bấm theo vị trí trên ảnh» / «Bấm vào vùng ảnh» (region): bật chế độ bấm ảnh; bước chạm sẽ vào đúng chỗ đang chọn
  // neo theo BƯỚC đứng trước (đối tượng), không theo số thứ tự: xoá / chèn bước khác trong lúc đang bấm ảnh cũng không làm lệch chỗ
  PICK_TO = { list: to.list, after: to.at == null ? (to.list[to.list.length - 1] || null) : (to.at > 0 ? to.list[to.at - 1] || null : null) };
  setPickMode(true);
  const how = region ? "kéo một khung quanh nút cần bấm trên ảnh màn hình" : "bấm lên ảnh màn hình để thêm bước chạm";
  if (SCREEN.w) { toast(how[0].toUpperCase() + how.slice(1), "ok"); return; }
  toast("Chụp màn hình rồi " + how, "warn");
  if (SEL) shot(null);
}
function setPickMode(on) {             // bật / tắt «bấm vào ảnh để thêm bước chạm» (bấm một điểm = toạ độ, kéo một khung = vùng ảnh)
  $("#pick-mode").checked = !!on;
  $("#screen").classList.toggle("pick", !!on);
  $("#pick-hint").hidden = !on;
  if (!on) { PICK_TO = null; onScreenCancel(); }
}
function addPicked(step) {             // gọi khi người dùng bấm lên ảnh màn hình ở chế độ «bấm ảnh để thêm bước chạm»
  if (!PICK_TO) {
    if (scriptOrders()) { toast("Chọn giai đoạn trước: bấm «Thêm bước» ở giai đoạn cần thêm rồi chọn «Bấm theo vị trí trên ảnh»", "warn"); return false; }
    PICK_TO = { list: FLOW.steps, after: FLOW.steps[FLOW.steps.length - 1] || null };
  }
  const list = PICK_TO.list;
  const k = PICK_TO.after ? list.indexOf(PICK_TO.after) : -1;
  // bước neo đã bị xoá → thêm vào cuối (không đoán vị trí); chưa có bước neo (chèn ở đầu) → vị trí 0
  const at = PICK_TO.after ? (k >= 0 ? k + 1 : list.length) : 0;
  list.splice(at, 0, step);
  PICK_TO = { list, after: step };     // bấm tiếp thì nối ngay sau bước vừa thêm
  renderSteps();
  return true;
}

function addStep(s, to) {
  const list = (to && to.list) || FLOW.steps, at = to ? to.at : null;
  if (at == null || at < 0 || at > list.length) list.push(s);
  else list.splice(at, 0, s);
  renderSteps();
}

// Hỏi tham số của một bước. `cur` = bước đang SỬA (điền sẵn giá trị cũ, giữ các trường khác) hoặc null khi thêm mới.
// Trả về bước MỚI (một đối tượng khác), hoặc null nếu huỷ / nhập sai.
// Bước «bấm / giữ vào chữ»: chờ chữ HIỆN RA tối đa bao lâu rồi mới báo không thấy. Màn hình game chuyển cảnh mất 1–3 giây nên bước MỚI
// mặc định chờ 5 giây; bước cũ không ghi gì thì vẫn nhìn đúng một lần (0) cho tới khi người dùng đổi.
const TEXT_WAIT_NEW = 5, TEXT_WAIT_MAX = 60;
function textWaitField(cur) {
  return { key: "timeout", label: "Chữ chưa hiện thì chờ, tối đa (giây) — 0 = chỉ nhìn một lần", value: String(cur ? (Number(cur.timeout) || 0) : TEXT_WAIT_NEW) };
}
function setTextWait(s, raw) {
  const w = Math.min(TEXT_WAIT_MAX, Math.max(0, parseFloat(raw) || 0));
  if (w > 0) s.timeout = w; else delete s.timeout;
}

// Ô «trong cùng ô phải có chữ» + «chưa thấy thì lướt» của bước bấm / kiểm chữ (xem stepexec.card_opts).
const NEAR_DIR_LABEL = { below: "ngay dưới", right: "bên phải", left: "bên trái" };
const SCROLL_LABEL = { "": "Không lướt", left: "Lướt sang trái (xem phần bên phải)", right: "Lướt sang phải", up: "Lướt lên (xem phần bên dưới)", down: "Lướt xuống" };
function cardFields(cur, pkg) {
  const c = cur || {};
  return [
    { key: "near", label: "Trong cùng ô phải có chữ (để trống = không cần)", value: c.near ?? "", placeholder: "VD: {{package.price_text}}", vars: pkg },
    // hướng cũ không còn dùng được (vd «above» của bản trước): GIỮ nguyên làm một lựa chọn riêng — đổi lặng lẽ sang «ngay dưới» là đảo nghĩa
    // của bước; để nguyên thì tool báo lỗi cấu hình lúc chạy, người sửa tự chọn lại
    { key: "near_dir", type: "select", label: "Chữ đó nằm ở", value: c.near_dir || "below",
      options: Object.entries(NEAR_DIR_LABEL).map(([v, l]) => ({ value: v, label: l }))
        .concat(c.near_dir && !Object.hasOwn(NEAR_DIR_LABEL, c.near_dir) ? [{ value: String(c.near_dir), label: "(hướng cũ không còn dùng — chọn lại)" }] : []) },
    { key: "scroll", type: "select", label: "Chưa thấy thì", value: c.scroll || "", options: Object.entries(SCROLL_LABEL).map(([v, l]) => ({ value: v, label: l })) },
  ];
}
function setCard(s, r) {                   // ghi các tuỳ chọn «trong cùng ô» vào bước; để trống thì bỏ hẳn (bước như cũ)
  const near = String(r.near || "").trim();
  if (near) s.near = near; else delete s.near;
  // hướng lạ chỉ được GIỮ khi đó chính là giá trị cũ của bước (xem cardFields) — không nhận giá trị lạ mới
  if (near && r.near_dir && r.near_dir !== "below" && (Object.hasOwn(NEAR_DIR_LABEL, r.near_dir) || r.near_dir === s.near_dir)) s.near_dir = String(r.near_dir); else delete s.near_dir;
  if (SCROLL_LABEL[r.scroll] && r.scroll) s.scroll = r.scroll; else { delete s.scroll; delete s.scrolls; }
}
function cardText(s) {                      // phần câu mô tả «có … ngay dưới · chưa thấy thì lướt …»; dữ liệu lạ không được in ra
  const out = [];
  if (s.near) out.push(`có ${stepVal(`«${s.near}»`)} ${!s.near_dir ? NEAR_DIR_LABEL.below : Object.hasOwn(NEAR_DIR_LABEL, s.near_dir) ? NEAR_DIR_LABEL[s.near_dir] : "(hướng không còn dùng — chọn lại)"}`);
  if (SCROLL_LABEL[s.scroll] && s.scroll) out.push(`<span class="flow-dim">chưa thấy thì ${esc(SCROLL_LABEL[s.scroll].toLowerCase())}</span>`);
  return out.length ? " " + out.join(" ") : "";
}
// `list` = danh sách bước chứa nó (để biết đang ở giai đoạn nào của đơn → những dữ liệu nào của đơn dùng được).
async function stepPrompt(type, cur, list) {
  const c = cur || {}, T = cur ? "Sửa bước: " : "Thêm bước: ";
  const s = cur ? JSON.parse(JSON.stringify(cur)) : { type };
  if (type === "home") return s;
  const xy = (raw) => /^\s*\(?\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*\)?\s*$/.exec(raw || "");
  const pkg = orderVars(list, "package.");               // chữ của gói đang mua — dùng được ở các bước «tìm chữ» của giai đoạn mua

  if (type === "type") {
    const vars = orderVars(list);                         // kịch bản nhận đơn: tài khoản, mật khẩu… của từng đơn
    const r = await askForm(T + "Gõ chữ", vars && vars.items.length ? "Gõ chữ cố định, hoặc bấm một ô «Lấy từ đơn» để gõ dữ liệu của từng đơn (mỗi đơn một khác)." : "",
      [{ key: "v", label: "Nội dung cần gõ", value: c.text ?? "", placeholder: "Nội dung…", vars },
       { key: "gap", label: "Nghỉ giữa các ký tự (giây) — 0 = gõ liền một mạch; ô mã «mỗi số một ô» nên để 0.4", value: String(Number(c.gap) > 0 ? Number(c.gap) : 0) }]);
    if (!r) return null; s.text = r.v;
    const gap = Math.min(2, Math.max(0, parseFloat(r.gap) || 0));
    if (gap > 0) s.gap = gap; else delete s.gap;
  } else if (type === "tap_text") {
    const r = await askForm(T + "Bấm vào chữ", "Có nhiều ô giống nhau (vd danh sách gói): ghi thêm chữ phải có TRONG CÙNG Ô (giá…) để bấm đúng ô; danh sách dài thì chọn hướng lướt để máy tự tìm.", [
      { key: "text", label: "Chữ hiển thị trên màn (OCR)", value: c.text ?? "", placeholder: "VD: Đăng nhập", vars: pkg },
      textWaitField(cur),
    ].concat(cardFields(cur, pkg)));
    if (!r || !r.text) return null; s.text = r.text; setTextWait(s, r.timeout); setCard(s, r);
  } else if (type === "tap_image") {
    if (!cur) return null;                                 // thêm mới không qua hộp thoại: kéo khung trên ảnh màn hình (xem startPick)
    const m0 = Number(c.min) > 1 ? Number(c.min) / 100 : Number(c.min) > 0 ? Number(c.min) : 0.9;
    const r = await askForm(T + "Bấm vào vùng ảnh", "Máy tìm đúng hình này trên màn hình rồi bấm vào giữa nó. Muốn đổi hình: xoá bước này rồi kéo khung mới trên ảnh màn hình.", [
      { type: "image", src: imageSrc(c.image) },
      Object.assign(textWaitField(cur), { label: "Hình chưa hiện thì chờ, tối đa (giây) — 0 = chỉ nhìn một lần" }),
      { key: "min", label: "Giống tối thiểu (%) — hạ xuống nếu nền phía sau hình thay đổi", value: String(Math.round(m0 * 100)) },
    ]);
    if (!r) return null;
    setTextWait(s, r.timeout);
    const m = parseImageMin(r.min);
    if (m === 90) delete s.min; else s.min = m / 100;       // 90% là mặc định → không ghi
  } else if (type === "tap_if") {
    const lines = (cur ? ifCases(c).filter(k => k.text) : []).map(ifCaseLine).join("\n");
    const r = await askForm(T + "Nếu thấy chữ … thì bấm",
      "Cho hộp thoại lúc có lúc không (thông báo, quảng cáo, hỏi lưu mật khẩu). Thấy trường hợp nào thì xử lý trường hợp đó rồi kiểm lại là nó đã đóng; không thấy gì thì bước coi như xong. Mỗi hộp thoại ghi một dòng, dùng chữ chỉ nó có.", [
      { key: "cases", type: "textarea", label: "Mỗi dòng một trường hợp:  thấy chữ gì  =>  bấm chữ gì   (hoặc  =>  phím esc   /   =>  @x,y  bấm tại toạ độ)", value: lines, placeholder: "Tính năng mới => Tiếp tục\nChào mừng đến => Hủy\nlưu mật khẩu này => phím esc" },
      // bước cũ không ghi thời gian thì đang chạy «xem một lần» (0) → hiện đúng 0, không tự đổi hành vi khi người dùng chỉ mở ra xem
      { key: "timeout", label: "Chờ xem có hiện không, tối đa (giây) — 0 = chỉ xem một lần", value: String(c.timeout ?? (cur ? 0 : 8)) },
      { key: "until", label: "Xong ngay khi thấy chữ (để trống = chờ hết thời gian) — chữ chỉ có khi không còn hộp thoại nào, vd «Shop»", value: c.until ?? "", placeholder: "VD: Shop" },
    ]);
    if (!r) return null;
    const cases = parseIfCases(r.cases);
    if (String(r.until || "").trim()) s.until = String(r.until).trim(); else delete s.until;
    if (!cases.length) { toast("Ghi ít nhất một dòng: thấy chữ gì => bấm chữ gì", "warn"); return null; }
    delete s.text; delete s.tap; delete s.key; delete s.at; delete s.cases;
    if (cases.length === 1) Object.assign(s, cases[0]);        // một trường hợp: ghi gọn `text` / `tap`
    else s.cases = cases;
    s.timeout = Math.min(120, Math.max(0, parseFloat(r.timeout) || 0));
  } else if (type === "tap") {
    const t = await askOne(T + "Bấm theo toạ độ", "Toạ độ x,y (pixel ảnh chụp)", cur ? `${c.x},${c.y}` : "", "375,820");
    if (!t) return null;
    const m = xy(t);
    if (!m) { toast("Toạ độ phải có dạng x,y", "warn"); return null; }
    s.x = Number(m[1]); s.y = Number(m[2]);
  } else if (type === "key") {
    const t = await askOne(T + "Nhấn phím", "Phím (enter/tab/back/esc/space)", c.name ?? "enter");
    if (!t) return null; s.name = t.trim();
  } else if (type === "combo") {
    const t = await askOne(T + "Tổ hợp phím", "Tổ hợp (VD: gui h, gui space, ctrl space)", c.keys ?? "gui h");
    if (!t) return null; s.keys = t.trim();
  } else if (type === "launch") {
    const r = await askForm(T + "Mở app", "", [
      { key: "app", label: "Tên app cần mở (không dấu)", value: c.app ?? "", placeholder: "VD: efootball" },
      { key: "fresh", type: "select", label: "Nếu app đang chạy dở", value: (cur ? c.fresh : true) ? "1" : "0", options: [
        { value: "1", label: "Tắt hẳn rồi mở mới — luôn bắt đầu từ màn đầu (qua USB)" },
        { value: "0", label: "Chỉ đưa ra trước — giữ nguyên màn hình đang dở" }] },
    ]);
    if (!r || !r.app.trim()) return null;
    s.app = r.app.trim();
    if (r.fresh === "1") s.fresh = true; else delete s.fresh;
  } else if (type === "wait") {
    const t = await askOne(T + "Chờ", "Số giây chờ", String(c.seconds ?? "1.5"));
    if (!t) return null; s.seconds = parseFloat(t) || 0;
  } else if (type === "wait_text") {
    const r = await askForm(T + "Chờ thấy chữ", "Chờ tới khi OCR thấy chữ.", [
      { key: "text", label: "Chữ cần chờ", value: c.text ?? "", placeholder: "VD: Trang chủ", vars: pkg },
      { key: "timeout", label: "Chờ tối đa (giây)", value: String(c.timeout ?? 15) },
    ]);
    if (!r || !r.text) return null; s.text = r.text; s.timeout = parseFloat(r.timeout) || 15;
  } else if (type === "assert_text") {
    const r = await askForm(T + "Kiểm có chữ", "Xác minh màn hình có chữ (không bấm gì). Có ghi chữ đi kèm / hướng lướt thì kiểm đúng một ô — dùng để chạy thử việc tìm gói mà không mua.", [
      { key: "text", label: "Xác minh màn hình có chữ", value: c.text ?? "", placeholder: "VD: Thành công", vars: pkg },
    ].concat(cardFields(cur, pkg)));
    if (!r || !r.text) return null; s.text = r.text; setCard(s, r);
  } else if (type === "swipe") {
    const byXy = !!cur && !c.dir;
    const r = await askForm(T + "Vuốt",
      "Lật trang cần kéo gần hết bề ngang nên tool tự kéo dài. Cuộn chỉ là ước lượng — cuộn xong nên thêm bước «Chờ thấy chữ» để biết đã tới đâu.", [
      { key: "dir", label: "Hướng vuốt (theo ngón tay)", type: "select", value: byXy ? "xy" : (c.dir || "left"), options: [
        { value: "left", label: "Sang trái — lật sang trang sau" }, { value: "right", label: "Sang phải — về trang trước" },
        { value: "up", label: "Lên — cuộn nội dung xuống dưới" }, { value: "down", label: "Xuống — cuộn nội dung lên trên" },
        { value: "xy", label: "Tự nhập toạ độ đầu → cuối" }] },
      { key: "xy", label: "Toạ độ (chỉ khi chọn «tự nhập»)", value: byXy ? `${c.x1},${c.y1} > ${c.x2},${c.y2}` : "", placeholder: "375,1000 > 375,400" },
    ]);
    if (!r) return null;
    ["dir", "x1", "y1", "x2", "y2"].forEach(k => delete s[k]);
    if (r.dir === "xy") {
      const m = /^\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*(?:>|→|->)\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*$/.exec(r.xy || "");
      if (!m) { toast("Toạ độ phải có dạng x1,y1 > x2,y2", "warn"); return null; }
      [s.x1, s.y1, s.x2, s.y2] = m.slice(1).map(Number);
    } else s.dir = r.dir;
  } else if (type === "hold" || type === "hold_text") {
    const byText = type === "hold_text";
    const r = await askForm(T + (byText ? "Bấm giữ vào chữ" : "Bấm giữ"),
      "Nhấn và giữ rồi nhả (mở menu ngữ cảnh, vào chế độ sửa màn hình chính…).", [
      byText ? { key: "text", label: "Chữ hiển thị trên màn (OCR)", value: c.text ?? "", placeholder: "VD: Sách" }
             : { key: "xy", label: "Toạ độ x,y (pixel ảnh chụp)", value: cur ? `${c.x},${c.y}` : "", placeholder: "636,468" },
      { key: "seconds", label: "Giữ bao lâu (giây)", value: String(c.seconds ?? (cur ? 1 : 1.2)) },      // bước cũ không ghi số giây thì đang chạy 1 giây
    ].concat(byText ? [textWaitField(cur)] : []));
    if (!r) return null;
    s.seconds = Math.min(10, Math.max(0.2, parseFloat(r.seconds) || 1));
    if (byText) { if (!r.text) return null; s.text = r.text; setTextWait(s, r.timeout); }
    else {
      const m = xy(r.xy);
      if (!m) { toast("Toạ độ phải có dạng x,y", "warn"); return null; }
      s.x = Number(m[1]); s.y = Number(m[2]);
    }
  } else return null;                                    // loại bước lạ: không có gì để hỏi
  return s;
}

async function addStepPrompt(type, to) {
  const s = await stepPrompt(type, null, (to && to.list) || FLOW.steps);
  if (s) addStep(s, to);
}

async function testFlow(btn) {
  if (!SEL) { toast("Chọn máy để thử", "warn"); return; }
  const steps = FLOW.steps;
  if (!steps.length) { toast("Chưa có bước nào để thử", "warn"); return; }
  busy(btn, true);
  STEP_RES = new WeakMap(); renderSteps();                       // lượt thử mới: xoá kết quả cũ trên lộ trình
  log(`▶ Chạy thử kịch bản trên ${SEL}`);
  try {
    const r = await API().test_flow(SEL, steps);
    if (!r || !r.ok) { log("✗ " + ((r && r.error) || "lỗi"), "bad"); toast((r && r.error) || "Chạy thử lỗi", "bad"); }
    else {
      let okN = 0;
      r.results.forEach(x => { if (x.ok) okN++; log(`   [${x.i + 1}] ${x.type}: ${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad");
        if (steps[x.i]) STEP_RES.set(steps[x.i], { ok: !!x.ok, msg: x.msg }); });
      adoptScreens(steps, r.results);
      renderSteps();
      toast(`${SEL}: ${okN}/${steps.length} bước OK`, okN === steps.length ? "ok" : "warn");
      setTimeout(() => shot(null), 600);
    }
  } catch (e) { log("✗ " + e, "bad"); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}
