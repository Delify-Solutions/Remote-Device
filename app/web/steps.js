// steps.js — CÁC BƯỚC của một kịch bản: mỗi loại bước viết thành một câu đọc được (stepSentence), nhãn + biểu tượng của từng loại, bước
// «nếu thấy chữ … thì bấm …», rồi cả danh sách vẽ thành LỘ TRÌNH — mỗi bước một trạm, kèm ảnh mẫu và các nút thử / sửa / xoá của bước đó.
// Thêm / sửa bước (bảng chọn hành động, hộp thoại hỏi tham số) và chạy thử cả kịch bản: stepedit.js.

/* =========================================================
   FLOWS — step builder
   ========================================================= */
function stepText(s) {
  switch (s.type) {
    case "tap": return `(${s.x}, ${s.y})`;
    case "tap_text": return `“${s.text}”` + (s.near ? ` + “${s.near}”` : "") + (Number(s.timeout) > 0 ? ` (chờ ${Number(s.timeout)}s)` : "");
    case "tap_image": return `vùng ảnh ${Number(s.w) || "?"}×${Number(s.h) || "?"}` + (Number(s.timeout) > 0 ? ` (chờ ${Number(s.timeout)}s)` : "");
    case "tap_if": return ifCases(s).map(k => `“${k.text}” → ${ifKey(k) ? "phím " + ifKey(k) : ifAt(k) ? `(${ifAt(k).join(", ")})` : `“${k.tap || k.text}”`}`).join("; ") + ` (${s.timeout || 0}s)`;
    case "type": return `“${s.text}”`;
    case "key": return s.name;
    case "combo": return s.keys;
    case "launch": return s.app + (s.fresh ? " (mở mới)" : "");
    case "home": return "màn hình chính";
    case "wait": return s.seconds + "s";
    case "wait_text": return `“${s.text}” (${s.timeout || 15}s)`;
    case "assert_text": return `“${s.text}”` + (s.near ? ` + “${s.near}”` : "");
    case "swipe": return s.dir ? (SWIPE_DIR[s.dir] || s.dir) : `(${s.x1}, ${s.y1}) → (${s.x2}, ${s.y2})`;
    case "hold": return `(${s.x}, ${s.y}) · ${s.seconds || 1}s`;
    case "hold_text": return `“${s.text}” · ${s.seconds || 1}s`;
    default: return "";
  }
}
const SWIPE_DIR = { left: "sang trái (trang sau)", right: "sang phải (trang trước)", up: "lên (cuộn xuống dưới)", down: "xuống (cuộn lên trên)" };
const STEP_LABEL = {
  tap: "Tap", tap_text: "Tap chữ", tap_image: "Bấm vào", tap_if: "Nếu thấy thì bấm", type: "Gõ", key: "Phím", combo: "Tổ hợp",
  launch: "Mở app", home: "Home", wait: "Chờ", wait_text: "Chờ chữ", assert_text: "Kiểm chữ",
  swipe: "Vuốt", hold: "Bấm giữ", hold_text: "Giữ chữ",
};

// Loại bước → [nhóm (màu biểu tượng), biểu tượng]. Nhóm: touch = chạm · key = bàn phím · app = ứng dụng · wait = chờ và kiểm.
const STEP_KIND = {
  tap: ["touch", "tabler-pointer"], tap_text: ["touch", "tabler-hand-finger"], hold: ["touch", "tabler-hand-stop"],
  hold_text: ["touch", "tabler-hand-stop"], swipe: ["touch", "tabler-hand-move"], tap_if: ["touch", "tabler-arrows-split"],
  tap_image: ["touch", "tabler-photo-search"],
  type: ["key", "tabler-keyboard"], key: ["key", "tabler-keyboard"], combo: ["key", "tabler-command"],
  launch: ["app", "tabler-apps"], home: ["app", "tabler-home"],
  wait: ["wait", "tabler-clock"], wait_text: ["wait", "tabler-eye"], assert_text: ["wait", "tabler-checks"],
};
function stepKind(type) {                    // (hasOwnProperty: loại bước lạ trùng tên thuộc tính có sẵn của Object — «constructor»… — không làm hỏng trang)
  return Object.prototype.hasOwnProperty.call(STEP_KIND, type) ? STEP_KIND[type] : ["", "tabler-point"];
}
// Phần do người dùng nhập của một bước: in đậm; {{biến}} thành nhãn riêng để thấy ngay chỗ nào lấy dữ liệu.
function stepVal(v) {
  return `<b>${esc(String(v ?? "")).replace(/\{\{\s*([A-Za-z0-9_.]+)\s*\}\}/g, "<code>{{$1}}</code>")}</b>`;
}
// Ô «giống tối thiểu (%)» của bước «bấm vào vùng ảnh» → số phần trăm 50…99. Trống / không phải số / số âm → 90 (mặc định); gõ kiểu 0.8 → 80.
function parseImageMin(raw) {
  let pm = parseFloat(raw);
  if (!(pm > 0)) pm = 90;
  else if (pm <= 1) pm *= 100;
  return Math.round(Math.min(99, Math.max(50, pm)));
}
// Ảnh mẫu của bước «bấm vào vùng ảnh» (PNG base64) → địa chỉ `data:` để hiện lên trang; không đúng dạng base64 → "" (không đưa chuỗi lạ vào trang).
function imageSrc(b64) {
  return typeof b64 === "string" && b64.length <= 1200000 && /^[A-Za-z0-9+/]+={0,2}$/.test(b64) ? "data:image/png;base64," + b64 : "";
}
// Một bước viết thành MỘT CÂU đọc được: «Bấm vào chữ «Mua»», «Chờ thấy chữ «Shop» tối đa 15 giây».
function stepSentence(s) {
  const dim = (t) => ` <span class="flow-dim">${esc(t)}</span>`;
  switch (s.type) {
    case "tap": return `Bấm tại ${stepVal(`(${s.x}, ${s.y})`)}`;
    case "tap_text": return `Bấm vào chữ ${stepVal(`«${s.text}»`)}${cardText(s)}${Number(s.timeout) > 0 ? dim(`chờ tối đa ${Number(s.timeout)} giây`) : ""}`;
    case "tap_image": {                                                // hình cần bấm hiện ngay trong câu
      const src = imageSrc(s.image);
      return `Bấm vào hình ${src ? `<img class="flow-thumb" src="${src}" alt="vùng ảnh cần bấm">` : stepVal("(ảnh không đọc được)")}`
        + (Number(s.timeout) > 0 ? dim(`chờ tối đa ${Number(s.timeout)} giây`) : "");
    }
    case "tap_if":                                                     // mỗi trường hợp một dòng: «Nếu thấy chữ A thì bấm B»
      return ifCases(s).map(k => `Nếu thấy chữ ${stepVal(`«${k.text}»`)} thì ` + (ifKey(k) ? `nhấn phím ${stepVal(ifKey(k))}`
        : ifAt(k) ? `bấm tại ${stepVal(`(${ifAt(k)[0]}, ${ifAt(k)[1]})`)}` : `bấm ${stepVal(`«${k.tap || k.text}»`)}`)).join("<br>")
        + dim((ifCases(s).length > 1 ? "không thấy gì thì bỏ qua · " : "") + (Number(s.timeout) > 0 ? `chờ tối đa ${s.timeout} giây` : "xem một lần")
              + (s.until ? ` · xong khi thấy «${s.until}»` : ""));
    case "type": return `Gõ ${stepVal(`«${s.text}»`)}` + (Number(s.gap) > 0 ? dim(`từng ký tự, cách nhau ${Number(s.gap)} giây`) : "");   // có ngoặc: thấy được cả chữ rỗng / khoảng trắng ở đầu, cuối
    case "key": return `Nhấn phím ${stepVal(s.name)}`;
    case "combo": return `Nhấn tổ hợp ${stepVal(s.keys)}`;
    case "launch": return `Mở app ${stepVal(s.app)}` + (s.fresh ? dim("tắt hẳn rồi mở mới") : "");
    case "home": return "Về màn hình chính";
    case "wait": return `Chờ ${stepVal(`${s.seconds} giây`)}`;
    case "wait_text": return `Chờ thấy chữ ${stepVal(`«${s.text}»`)}${dim(`tối đa ${s.timeout || 15} giây`)}`;
    case "assert_text": return `Kiểm có chữ ${stepVal(`«${s.text}»`)}${cardText(s)}`;
    case "swipe": return s.dir ? `Vuốt ${stepVal(SWIPE_DIR[s.dir] || s.dir)}` : `Vuốt từ ${stepVal(`(${s.x1}, ${s.y1})`)} tới ${stepVal(`(${s.x2}, ${s.y2})`)}`;
    case "hold": return `Bấm giữ tại ${stepVal(`(${s.x}, ${s.y})`)}${dim(`trong ${s.seconds || 1} giây`)}`;
    case "hold_text": return `Bấm giữ vào chữ ${stepVal(`«${s.text}»`)}${dim(`trong ${s.seconds || 1} giây` + (Number(s.timeout) > 0 ? ` · chờ chữ tối đa ${Number(s.timeout)} giây` : ""))}`;
    default: return `${esc(STEP_LABEL[s.type] || s.type)} ${stepVal(stepText(s))}`;
  }
}

// Bước «nếu thấy chữ … thì bấm …»: danh sách trường hợp [{text, tap}] — bước ghi `cases` (nhiều) hoặc `text` / `tap` (một).
function ifCases(s) {
  const cs = Array.isArray(s.cases) ? s.cases.filter(k => k && typeof k === "object") : [];
  return cs.length ? cs : [{ text: s.text, tap: s.tap, key: s.key, at: s.at }];
}
// phím dùng được ở trường hợp «thì nhấn phím» (hộp thoại không nhận cú bấm của con trỏ)
const IF_KEYS = ["esc", "enter", "tab", "back", "space"];
function ifKey(k) {                      // phím hợp lệ của một trường hợp, hoặc "" (dữ liệu lạ không được đưa vào trang)
  const v = String((k && k.key) || "").trim().toLowerCase();
  return IF_KEYS.includes(v) ? v : "";
}
// Người dùng gõ mỗi dòng một trường hợp: «thấy chữ gì => bấm chữ gì» (bỏ «=> …» thì bấm chính chữ đó; cũng nhận «->» và «→»).
// «=> phím esc» (hoặc «=> key esc»): NHẤN PHÍM thay cho bấm — cho hộp thoại không nhận cú bấm của con trỏ (vd iOS hỏi «lưu mật khẩu»).
function parseIfCases(text) {
  const out = [];
  String(text || "").split(/\r?\n/).forEach(line => {
    const m = /^(.*?)(?:=>|->|→)(.*)$/.exec(line);
    const seen = (m ? m[1] : line).trim(), tap = m ? m[2].trim() : "";
    if (!seen) return;
    const one = { text: seen };
    const k = /^(?:phím|phim|key)\s+([a-z]+)$/i.exec(tap);
    const xy = /^@\s*(\d{1,4})\s*[,; ]\s*(\d{1,4})$/.exec(tap);         // «=> @667,571»: bấm tại toạ độ (nút không đọc được chữ)
    if (k && IF_KEYS.includes(k[1].toLowerCase())) one.key = k[1].toLowerCase();
    else if (xy) one.at = [Number(xy[1]), Number(xy[2])];
    else if (tap && tap !== seen) one.tap = tap;
    out.push(one);
  });
  return out.slice(0, 12);
}
function ifAt(k) {                       // toạ độ hợp lệ của trường hợp «bấm tại», hoặc null
  const a = k && k.at;
  return Array.isArray(a) && a.length === 2 && a.every(v => Number.isInteger(v) && v >= 0 && v < 10000) ? a : null;
}
function ifCaseLine(k) {                 // một trường hợp viết lại thành một dòng của ô nhập (ngược với parseIfCases)
  return ifKey(k) ? `${k.text} => phím ${ifKey(k)}` : ifAt(k) ? `${k.text} => @${ifAt(k)[0]},${ifAt(k)[1]}`
    : (k.tap && k.tap !== k.text) ? `${k.text} => ${k.tap}` : `${k.text}`;
}

let STEP_RES = new WeakMap();        // bước (đối tượng) → {ok, msg} của lần thử gần nhất. Sửa bước tạo đối tượng mới nên kết quả cũ tự mất.
let ADD_TO = null;                   // bảng chọn hành động đang mở để thêm vào đâu: {list, at} (at = null: cuối danh sách)
let PICK_TO = null;                  // lần bấm lên ảnh kế tiếp chèn bước chạm vào đâu: {list, after} — ngay SAU bước `after` (đối tượng bước; null = đầu danh sách)

function updateDirty() {
  const el = $("#ed-dirty");
  if (el) el.hidden = !(GROUP_PAGE === "detail" && GROUP_SUB === "script" && groupDirty());
}

// Các bước vẽ thành LỘ TRÌNH: mỗi bước là một trạm đánh số trên đường ray; thử xong thì trạm đổi màu (xanh = được, đỏ = trượt) kèm lời báo.
// Kịch bản nhận đơn: hai trạm đầu là việc của gateway (chờ đơn, giữ chỗ), rồi tới từng giai đoạn của đơn; trạm «báo kết quả» nằm trước giai đoạn kết thúc.
function renderSteps() {
  const ol = $("#steps"), pal = $("#step-palette"), sc = scriptOrders(), lists = flowLists();
  closePalette();                                                 // bảng chọn có thể đang nằm trong một <li> sắp bị vẽ lại → đưa về chỗ cũ trước
  ol.innerHTML = "";
  const total = lists.reduce((n, l) => n + l.steps.length, 0);
  let no = 0;                                                     // số thứ tự trạm, đếm xuyên suốt cả lộ trình
  $("#steps-empty").hidden = total > 0 || !!sc;
  $("#step-count").textContent = total ? String(total) : "";
  $("#step-add-label").textContent = total ? "Thêm bước" : "Thêm bước đầu tiên";
  $("#flow-add").hidden = !!sc;                                   // kịch bản nhận đơn: mỗi giai đoạn có nút thêm bước riêng…
  $("#btn-flow-test").hidden = !!sc;                              // …và nút thử riêng (không «chạy thử» một mạch qua cả bước mua)
  if (sc) { ol.appendChild(fixedStation(++no, "wait")); ol.appendChild(fixedStation(++no, "hold")); }
  lists.forEach(l => {
    let slot = null;
    if (sc) { const head = sectionHead(l); ol.appendChild(head.li); slot = head.slot; }
    l.steps.forEach((s, i) => ol.appendChild(stepItem(l, s, i, ++no)));
    if (sc) {
      ol.appendChild(slot);                                       // chỗ đặt bảng chọn khi bấm «Thêm bước» của giai đoạn (cuối giai đoạn)
      if (l.key === "after") ol.appendChild(fixedStation(++no, "result"));
    }
  });
  if (!sc && !total && pal) { pal.hidden = false; $("#btn-step-add").setAttribute("aria-expanded", "true"); }   // kịch bản trống: mở sẵn bảng chọn
  renderOrdersUi();                                               // (kịch bản nhận đơn: trạm chọn pool + dòng «còn thiếu gì»; ngoài ra thì ẩn)
  updateDirty();
  paintProgress();
}

function fixedStation(no, kind) {      // trạm do TOOL tự làm với gateway — không phải bước bấm trên máy nên không sửa / xoá được
  const [icon, title, note] = {
    wait: ["tabler-hourglass", "Chờ đơn từ gateway", "Máy đứng chờ. Cứ vài giây tool hỏi gateway một lần xem pool này có đơn không."],
    hold: ["tabler-lock", "Giữ chỗ cho máy", "Gateway giao đơn cho đúng một máy. Từ lúc này shop không huỷ đơn được nữa."],
    result: ["tabler-send", "Báo kết quả cho gateway", "Tool tự gửi ảnh bill và kết quả. Không chắc đã nạp hay chưa thì đơn chuyển đối soát và máy dừng chờ kiểm tra."],
  }[kind];
  const li = document.createElement("li");
  li.className = "flow-step flow-fixed";
  li.innerHTML = `<span class="flow-node" aria-hidden="true">${no}</span>
    <div class="flow-body">
      <div class="flow-line"><i class="ti ${icon} flow-ico"></i><span class="flow-text">${esc(title)}</span></div>
      ${kind === "wait" ? `<div class="flow-pool"><label class="flow-dim" for="flow-pool">của pool</label><select id="flow-pool" class="form-select form-select-sm"></select><span id="flow-pool-note"></span></div>` : ""}
      <div class="flow-note">${esc(note)}</div>
    </div>`;
  return li;
}

function sectionHead(l) {              // đầu mỗi giai đoạn của đơn: tên + tình trạng + «Thêm bước» / «Thử»
  const n = l.steps.length;
  const state = n ? `<span class="flow-dim">${n} bước</span>`
    : l.required ? `<span class="text-danger">bắt buộc, chưa có bước nào</span>`
    : `<span class="flow-dim">${l.key === "otp" ? "để trống thì tool gõ mã rồi nhấn Enter" : "chưa có bước (bỏ qua giai đoạn này)"}</span>`;
  const li = document.createElement("li");
  li.className = "flow-sec";
  li.innerHTML = `<div class="flow-sec-row"><span class="flow-sec-title" title="${esc(l.help)}">${esc(l.label)}</span>${state}
      <span class="flow-sec-acts">
        ${n ? `<button class="flow-sec-btn" data-op="test" title="Chạy thử các bước của giai đoạn này trên máy đang chọn"><i class="ti tabler-player-play"></i>Thử</button>` : ""}
        <button class="flow-sec-btn" data-op="add" title="Thêm một bước vào cuối giai đoạn «${esc(l.label)}»"><i class="ti tabler-plus"></i>Thêm bước</button>
      </span></div>
    ${n ? "" : `<div class="flow-sec-help">${esc(l.help)}</div>`}`;        // đã có bước thì thôi lời dẫn (rê chuột vào tên giai đoạn vẫn xem được)
  const slot = document.createElement("li");
  slot.className = "flow-slot";
  $('[data-op=add]', li).onclick = () => openPalette({ list: l.steps, at: null }, slot);
  const t = $('[data-op=test]', li);
  if (t) t.onclick = (e) => testPhase(l, e.currentTarget);
  return { li, slot };
}

// Bước THAO TÁC được kiểm màn hình trước khi làm (khớp screencheck.CHECK_TYPES ở backend)
const SCREEN_TYPES = ["tap", "tap_text", "tap_image", "hold", "hold_text", "type", "key", "combo", "swipe"];
const screenOn = (s) => !!(s.screen && s.screen_check !== false);

// Lượt chạy thử trả về ẢNH MẪU (màn hình ngay trước bước) cho các bước thao tác: bước nào chưa có ảnh mẫu thì gắn vào.
// Có bước mới được gắn → kịch bản có thay đổi chưa lưu.
function adoptScreens(steps, results) {
  let n = 0;
  (results || []).forEach(x => {
    const st = steps && steps[x.i];
    if (st && x.ok && x.screen && !st.screen && SCREEN_TYPES.includes(st.type)) { st.screen = x.screen; n++; }
  });
  if (n) { log(`   📷 đã lưu ảnh mẫu cho ${n} bước — bấm «Lưu» để giữ`, "ok"); updateDirty(); }
  return n;
}

// Ảnh mẫu của một bước: xem, chụp lại từ máy đang chọn, xoá, bật / tắt «kiểm màn hình trước khi làm».
async function screenPrompt(s) {
  const has = !!s.screen;
  const r = await askForm("Ảnh mẫu của bước",
    has ? `Trước khi làm bước này, tool so màn hình với ảnh mẫu (theo chữ trên màn hình; ít chữ thì theo hình). Khác thì chờ ${8} giây, vẫn khác thì xử lý màn hình lạ (AI) hoặc tạm dừng máy chờ admin.`
        : "Bước này chưa có ảnh mẫu nên chưa được kiểm màn hình. Ảnh mẫu tự có khi «Chạy thử» bước thành công, hoặc chụp ngay màn hình của máy đang chọn.", [
    ...(has ? [{ type: "image", alt: "Ảnh mẫu của bước", src: /^[A-Za-z0-9+/=]+$/.test(String(s.screen.img || "")) ? "data:image/jpeg;base64," + s.screen.img : "" }] : []),
    { key: "act", type: "select", label: "Ảnh mẫu", value: "keep", options: [
      { value: "keep", label: has ? "Giữ ảnh mẫu này" : "Chưa có — để vậy" },
      { value: "shot", label: "Chụp lại từ màn hình máy đang chọn" + (SEL ? ` (${SEL})` : " — chưa chọn máy") },
      ...(has ? [{ value: "del", label: "Xoá ảnh mẫu (bước này không kiểm màn hình nữa)" }] : [])] },
    ...(has ? [{ key: "check", type: "select", label: "Kiểm màn hình trước khi làm bước", value: s.screen_check === false ? "0" : "1",
                 options: [{ value: "1", label: "Có" }, { value: "0", label: "Không (giữ ảnh mẫu nhưng không kiểm)" }] }] : []),
  ]);
  if (!r) return;
  if (r.act === "shot") {
    if (!SEL) { toast("Chọn máy ở khung màn hình trước", "warn"); return; }
    try {
      const res = await API().screen_capture(SEL);
      if (!res || !res.ok) { toast("Không chụp được: " + ((res && res.error) || "?"), "bad"); return; }
      s.screen = res.screen;
      toast(`Đã chụp ảnh mẫu (${res.screen.texts.length} dòng chữ)`, "ok");
    } catch (e) { toast("Lỗi: " + e, "bad"); return; }
  } else if (r.act === "del") { delete s.screen; delete s.screen_check; }
  if (s.screen && r.check === "0") s.screen_check = false; else delete s.screen_check;
  renderSteps(); updateDirty();
}

function stepItem(l, s, i, no) {
  const list = l.steps;
  const [kind, icon] = stepKind(s.type);
  const res = STEP_RES.get(s);
  const editable = s.type !== "home";
  const fromOk = !!progScript();                          // kịch bản 1 lần / lặp: chạy từ bước này + tô tiến độ của máy đang chạy
  const li = document.createElement("li");
  li.className = "flow-step" + (kind ? " k-" + kind : "") + (res ? (res.ok ? " is-ok" : " is-bad") : "");
  if (fromOk) li.dataset.si = String(i);
  li.innerHTML = `
    <span class="flow-node" aria-hidden="true">${res ? `<i class="ti ${res.ok ? "tabler-check" : "tabler-x"}"></i>` : no}</span>
    <div class="flow-body" ${editable ? `data-op="edit" role="button" tabindex="0" title="Bấm để sửa bước này"` : `style="cursor:default"`}>
      <div class="flow-line"><i class="ti ${icon} flow-ico"></i><span class="flow-text">${stepSentence(s)}${s.optional ? `<span class="flow-tag">bỏ qua nếu lỗi</span>` : ""}</span></div>
      ${res && res.msg ? `<div class="flow-result">${esc(res.msg)}</div>` : ""}
    </div>
    <div class="flow-ops">
      <button data-op="test" title="Chạy thử bước này" aria-label="Chạy thử bước ${no}"><i class="ti tabler-player-play"></i></button>
      ${fromOk ? `<button data-op="from" title="Chạy kịch bản trên máy đang chọn, BẮT ĐẦU từ bước này (bỏ qua các bước trước)" aria-label="Chạy kịch bản từ bước ${no}"><i class="ti tabler-player-track-next"></i></button>` : ""}
      ${SCREEN_TYPES.includes(s.type) ? `<button data-op="screen" class="${screenOn(s) ? "on" : ""}" title="${s.screen ? (screenOn(s) ? "Có ảnh mẫu — kiểm màn hình trước khi làm" : "Có ảnh mẫu nhưng đang TẮT kiểm màn hình") : "Chưa có ảnh mẫu (chạy thử bước thành công để tự có)"}" aria-label="Bước ${no}: ảnh mẫu"><i class="ti ${s.screen ? "tabler-photo-check" : "tabler-photo"}"></i></button>` : ""}
      <button data-op="opt" class="${s.optional ? "on" : ""}" aria-pressed="${s.optional ? "true" : "false"}" title="Bỏ qua nếu lỗi: bước này trượt (vd không thấy chữ) thì vẫn chạy tiếp bước sau" aria-label="Bước ${no}: bỏ qua nếu lỗi"><i class="ti tabler-arrow-forward-up"></i></button>
      <button data-op="up" title="Đưa lên" aria-label="Đưa bước ${no} lên" ${i === 0 ? "disabled" : ""}><i class="ti tabler-chevron-up"></i></button>
      <button data-op="down" title="Đưa xuống" aria-label="Đưa bước ${no} xuống" ${i === list.length - 1 ? "disabled" : ""}><i class="ti tabler-chevron-down"></i></button>
      <button data-op="del" title="Xoá bước" aria-label="Xoá bước ${no}"><i class="ti tabler-trash"></i></button>
    </div>
    <button class="flow-ins" data-op="ins" title="Chèn một bước vào sau bước ${no}" aria-label="Chèn một bước vào sau bước ${no}">+</button>`;
  $('[data-op=opt]', li).onclick = () => { if (s.optional) delete s.optional; else s.optional = true; renderSteps(); };
  const from = $('[data-op=from]', li);
  if (from) from.onclick = () => { if (!SEL) { toast("Chọn máy ở khung màn hình trước", "warn"); return; } runFrom(SEL, list.indexOf(s)); };
  const scr = $('[data-op=screen]', li);
  if (scr) scr.onclick = () => screenPrompt(s);
  $('[data-op=up]', li).onclick = () => { const k = list.indexOf(s); if (k > 0) { [list[k - 1], list[k]] = [list[k], list[k - 1]]; renderSteps(); } };
  $('[data-op=down]', li).onclick = () => { const k = list.indexOf(s); if (k >= 0 && k < list.length - 1) { [list[k + 1], list[k]] = [list[k], list[k + 1]]; renderSteps(); } };
  $('[data-op=del]', li).onclick = () => { const k = list.indexOf(s); if (k >= 0) { list.splice(k, 1); renderSteps(); } };
  $('[data-op=ins]', li).onclick = () => openPalette({ list, at: list.indexOf(s) + 1 }, li);
  if (editable) {
    const body = $('[data-op=edit]', li);
    const edit = async () => {
      const ns = await stepPrompt(s.type, s, list);
      const at = list.indexOf(s);                               // trong lúc hộp thoại mở, danh sách có thể đã đổi
      if (ns && at >= 0) { list[at] = ns; renderSteps(); }
    };
    body.onclick = edit;
    body.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); edit(); } };
  }
  $('[data-op=test]', li).onclick = async (ev) => {
    if (!SEL) { toast("Chọn máy để thử ở khung màn hình", "warn"); return; }
    const b = ev.currentTarget; busy(b, true);
    li.classList.remove("is-ok", "is-bad"); li.classList.add("is-run");
    log(`▶ thử ${STEP_LABEL[s.type] || s.type} ${stepText(s)}`);
    let out = null;
    try {
      if (ordersCfg()) {                              // cùng bộ chạy với lúc nạp thật (thế {{biến}})
        const r = await runApiSteps([s]);
        if (r) { r.forEach(x => log(`   ${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad")); if (r[0]) out = { ok: !!r[0].ok, msg: r[0].msg }; adoptScreens([s], r); }
      } else {
        const r = await API().run_step(SEL, s);
        log(`   ${r.ok ? "✓" : "✗"} ${r.msg}`, r.ok ? "ok" : "bad");
        out = { ok: !!r.ok, msg: r.msg };
        adoptScreens([s], [{ i: 0, ok: r.ok, screen: r.screen }]);
      }
    } catch (e) { log("   ✗ " + e, "bad"); out = { ok: false, msg: String(e) }; }
    busy(b, false);
    if (out) STEP_RES.set(s, out); else STEP_RES.delete(s);
    renderSteps();
    if (["tap", "tap_text", "tap_image", "tap_if", "swipe", "hold", "hold_text"].includes(s.type)) setTimeout(() => shot(null), 900);
  };
  return li;
}
