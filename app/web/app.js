// app.js — iPhone Farm Manager
// Toàn bộ gọi backend qua window.pywebview.api.<method>() (đều async).
// Khởi tạo trong sự kiện 'pywebviewready'.

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const API = () => window.pywebview.api;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let DEVICES = [];
let IOS = [];
let ESP = [];
let FLOWS = [];
let GROUPS = [];                       // danh sách nhóm
let GROUP = null;                      // nhóm đang chọn (bản sao để sửa)
let RUN_STATUS = {};                   // trạng thái chạy từng máy (poll)
let SEL = null;                        // tên board đang chọn để thử (tab Nhóm)
let GROUP_PAGE = "list";               // tab Nhóm: "list" = danh sách nhóm, "detail" = trang quản lý 1 nhóm
let GROUP_SUB = "home";                // trong 1 nhóm: "home" = máy + danh sách kịch bản, "script" = trình sửa 1 kịch bản
let EDIT_SID = null;                   // id kịch bản đang sửa (chế độ loop/once)
let GROUP_SNAP = "";                   // ảnh chụp trạng thái nhóm lúc mở / lưu (để biết có thay đổi chưa lưu)
let SCREEN = { w: 0, h: 0 };
let FLOW = { id: "", name: "", steps: [] };   // bản steps đang dựng (của nhóm)
let ESP_SCANNED = false;               // đã quét ESP lần nào chưa (để tự quét khi mở tab)
let SCANNING = false;                  // đang quét board (serial) — hiện trạng thái "đang quét"
let IOS_LOADING = false;               // đang tải danh sách iPhone qua USB

/* =========================================================
   Streaming — backend đẩy kết quả từng board về qua các hàm này
   ========================================================= */
window.__espUpdate = function (res) {
  const i = ESP.findIndex(b => b.port === res.port);
  if (i >= 0) ESP[i] = res; else ESP.push(res);
  renderESP(); updateCounts(); updateEspSummary();
};
window.__devBoard = function (b) {
  if (!b || !b.name) return;
  const d = DEVICES.find(x => x.name === b.name);
  if (d) { d.board_online = true; d.port = b.port; d.ble = b.ble; }
  else DEVICES.push({ name: b.name, udid: null, label: b.name, board_online: true,
    port: b.port, ble: b.ble, configured: false, ios: null, model: null, device_name: null, ios_connected: false });
  renderDevices(); updateCounts();
};
window.__scanDone = function () {
  SCANNING = false;
  renderESP(); updateEspSummary();
  loadDevices();   // chốt lại: board không thấy = offline, đồng thời làm mới iPhone
};

/* =========================================================
   Toasts + modal prompt + log
   ========================================================= */
function toast(msg, kind = "") {
  const icons = { ok: "✓", bad: "✕", warn: "!", "": "•" };
  const t = document.createElement("div");
  t.className = "app-toast " + kind;
  t.innerHTML = `<span class="ti">${icons[kind] || "•"}</span><span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 260); }, 3200);
}

// Modal prompt — fields: [{key,label,value,placeholder}]. Trả về object {key:value} hoặc null nếu huỷ.
function askForm(title, msg, fields) {
  return new Promise((resolve) => {
    const ov = $("#modal");
    $("#modal-title").textContent = title;
    $("#modal-msg").textContent = msg || "";
    const box = $("#modal-fields");
    box.innerHTML = "";
    fields.forEach((f, i) => {
      const wrap = document.createElement("div");
      if (f.type === "select") {
        const opts = (f.options || []).map(o =>
          `<option value="${esc(o.value)}" ${String(o.value) === String(f.value) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
        wrap.innerHTML = `<label>${esc(f.label)}</label>
          <select data-k="${esc(f.key)}" class="modal-select">${opts}</select>`;
      } else {
        wrap.innerHTML = `<label>${esc(f.label)}</label>
          <input type="${f.type === "password" ? "password" : "text"}" autocomplete="off" data-k="${esc(f.key)}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder ?? "")}">`;
      }
      box.appendChild(wrap);
    });
    ov.hidden = false;
    const first = box.querySelector("input, select"); if (first) { first.focus(); if (first.select) first.select(); }

    const close = (val) => {
      ov.hidden = true;
      $("#modal-ok").onclick = $("#modal-cancel").onclick = null;
      ov.onkeydown = null;
      resolve(val);
    };
    const collect = () => {
      const out = {};
      $$("#modal-fields input, #modal-fields select").forEach(inp => out[inp.dataset.k] = inp.value);
      return out;
    };
    $("#modal-ok").onclick = () => close(collect());
    $("#modal-cancel").onclick = () => close(null);
    ov.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); close(collect()); }
      if (e.key === "Escape") { e.preventDefault(); close(null); }
    };
  });
}
async function askOne(title, label, value = "", placeholder = "") {
  const r = await askForm(title, "", [{ key: "v", label, value, placeholder }]);
  return r ? r.v : null;
}
function confirmBox(msg) { return window.confirm(msg); }

function log(line, kind = "") {
  const el = $("#log");
  const cls = kind === "ok" ? "lok" : kind === "bad" ? "lbad" : "";
  el.innerHTML += `<span class="${cls}">${esc(line)}</span>\n`;
  el.scrollTop = el.scrollHeight;
  const last = $("#log-last");                                   // khung nhật ký đang gập: dòng mới nhất vẫn thấy được ở tiêu đề
  if (last) { last.textContent = String(line).trim(); last.className = "ed-log-last" + (cls ? " " + cls : ""); }
}

function setConn(ok, text) {
  const dot = $("#conn-dot");
  dot.className = "conn-dot " + (ok ? "ok" : "bad");
  $("#conn-text").textContent = text;
}

function busy(btn, on) {
  if (!btn) return;
  if (on) {
    btn.dataset._html = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" style="width:14px;height:14px;border-width:2px"></span>`;
  } else {
    btn.disabled = false;
    if (btn.dataset._html) btn.innerHTML = btn.dataset._html;
  }
}

/* =========================================================
   View navigation
   ========================================================= */
function showView(name) {
  const was = ($(".view.active") || {}).id;
  $$(".app-nav").forEach(b => b.closest(".menu-item").classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + name));
  const titles = { overview: "Tổng quan", devices: "Thiết bị", esp: "ESP32", flows: "Nhóm & Kịch bản", ai: "Kết nối AI" };
  const pt = document.getElementById("page-title"); if (pt) pt.textContent = titles[name] || "";
  if (name === "overview") loadOverview();
  if (name === "flows") {
    if (was === "view-flows" && GROUP_PAGE === "detail") backToList();   // bấm lại mục menu khi đang ở 1 nhóm → về danh sách
    (async () => { await loadGroups(); await loadGateway(); })();
    loadRunLog(); startStatusPoll();
  } else if (name === "devices") { startStatusPoll(); }
  else { stopStatusPoll(); }
  if (name === "esp" && !ESP_SCANNED) espScan();   // tự quét lần đầu mở tab ESP
  if (name === "ai") loadAI();
}

/* =========================================================
   DEVICES
   ========================================================= */
async function loadDevices() {
  IOS_LOADING = true;
  renderIOS();                      // hiện spinner bảng iPhone
  try {
    DEVICES = await API().list_devices() || [];
  } catch (e) { toast("Lỗi tải thiết bị: " + e, "bad"); DEVICES = []; }
  renderDevices();
  renderDevicePicker();
  if (GROUP) { renderMembers(); renderGroupAddDev(); renderScriptMachines(); }   // (tên hiển thị của máy trong dải «Chạy» cũng lấy từ danh sách này)
  updateCounts();
  try {
    IOS = await API().ios_list() || [];
  } catch (e) { IOS = []; }
  IOS_LOADING = false;
  renderIOS();
  updateCounts();
}

function updateCounts() {
  const online = DEVICES.filter(d => d.board_online).length;
  const iosConn = DEVICES.filter(d => d.ios_connected).length;
  const bleN = DEVICES.filter(d => d.ble === true).length;
  $("#nav-dev-count").textContent = DEVICES.length;
  $("#nav-esp-count").textContent = ESP.length;
  $("#nav-flow-count").textContent = GROUPS.length;
  $("#dev-summary").textContent =
    `${online}/${DEVICES.length} board online · ${bleN} Bluetooth nối · ${iosConn} iPhone USB`;
  $("#dev-count-lbl").textContent = `${DEVICES.length} board`;

  // stat cards
  $("#dev-stats").innerHTML = `
    ${stat(DEVICES.length, "Tổng board", "accent")}
    ${stat(online, "Board online", online === DEVICES.length && DEVICES.length ? "ok" : online ? "warn" : "bad")}
    ${stat(bleN, "Bluetooth nối iPhone", bleN ? "ok" : "warn")}
    ${stat(IOS.length, "iPhone đang cắm USB", "accent")}`;

  setConn(true, "Đã kết nối");
}
function bleBadge(ble) {
  const s = ble === true ? ["ok", "Bluetooth nối"]
          : ble === false ? ["bad", "Bluetooth rớt"]
          : ["mut", "Bluetooth ?"];
  return `<div style="margin-top:5px"><span class="pill ${s[0]}" style="font-size:.68rem">${s[1]}</span></div>`;
}
function stat(val, lbl, kind = "") {
  return `<div class="stat ${kind}"><div class="stat-val">${val}</div><div class="stat-lbl">${esc(lbl)}</div></div>`;
}

function shortPort(p) {
  if (!p) return "—";
  return String(p).replace(/^\/dev\/(cu\.|tty\.?)?/, "");   // /dev/cu.usbserial-5 → usbserial-5
}

// Ô UDID: hiện rút gọn + nút copy (bấm copy đầy đủ); rê chuột thấy full.
function udidCell(udid, emptyText = "chưa gán") {
  if (!udid) return `<span class="pill mut">${emptyText}</span>`;
  return `<span class="udid-wrap">
    <span class="mono udid-txt" title="${esc(udid)}">${esc(udid.slice(0, 12))}…</span>
    <button class="btn-copy" data-copyudid="${esc(udid)}" title="Copy UDID đầy đủ"><i class="ti tabler-copy"></i></button>
  </span>`;
}
function wireCopyUdid(root) {
  $$("[data-copyudid]", root).forEach(b => b.onclick = () => copyText(b.dataset.copyudid));
}

/* ---- tab con (Tất cả / Board / iPhone) + phân trang + tìm kiếm ---- */
const PAGE_SIZE = 8;
let DEV_TAB = "all", DEV_PAGE = 1, IOS_PAGE = 1, DEV_Q = "";
let PROBING = false;   // đang "dò máy" → tạm khoá quét ESP để không tranh cổng serial

function matchDev(d) {
  if (!DEV_Q) return true;
  return [d.name, d.label, d.udid, d.model, d.device_name, d.ios, d.port]
    .join(" ").toLowerCase().includes(DEV_Q);
}
function matchIos(p) {
  if (!DEV_Q) return true;
  return [p.name, p.model, p.product_type, p.udid, p.ios]
    .join(" ").toLowerCase().includes(DEV_Q);
}
function setSearch(q) {
  DEV_Q = (q || "").trim().toLowerCase();
  DEV_PAGE = 1; IOS_PAGE = 1;
  const clr = $("#dev-q-clear"); if (clr) clr.hidden = !DEV_Q;
  renderDevices(); renderIOS();
}

function setDevTab(t) {
  DEV_TAB = t;
  $$("#dev-tabs .seg-btn").forEach(b => b.classList.toggle("active", b.dataset.dtab === t));
  $("#card-board").hidden = (t === "ios");
  $("#card-ios").hidden = (t === "board");
}

function renderPager(elId, total, page, go) {
  const el = $("#" + elId);
  if (!el) return;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (total <= PAGE_SIZE) { el.innerHTML = ""; el.hidden = true; return; }
  el.hidden = false;
  const from = (page - 1) * PAGE_SIZE + 1, to = Math.min(total, page * PAGE_SIZE);
  let nums = "";
  for (let i = 1; i <= pages; i++)
    nums += `<button class="pg ${i === page ? "active" : ""}" data-pg="${i}">${i}</button>`;
  el.innerHTML = `
    <span class="pager-info">${from}–${to} / ${total}</span>
    <div class="pager-btns">
      <button class="pg" data-pg="${page - 1}" ${page <= 1 ? "disabled" : ""}>‹</button>
      ${nums}
      <button class="pg" data-pg="${page + 1}" ${page >= pages ? "disabled" : ""}>›</button>
    </div>`;
  $$(".pg[data-pg]", el).forEach(b => b.onclick = () => { if (!b.disabled) go(parseInt(b.dataset.pg)); });
}

function clampPage(page, total) { return Math.min(Math.max(1, page), Math.max(1, Math.ceil(total / PAGE_SIZE))); }

function renderDevices() {
  const tb = $("#dev-tbody");
  tb.innerHTML = "";
  const cnt = $("#seg-board-c"); if (cnt) cnt.textContent = DEVICES.length;
  const list = DEVICES.filter(matchDev);
  const emptyEl = $("#dev-empty");
  if (!list.length) {
    renderPager("dev-pager", 0, 1, () => {});
    if (!DEVICES.length) {
      emptyEl.textContent = "Chưa có board nào. Bấm “Quét board”.";
      emptyEl.hidden = SCANNING;
      if (SCANNING) tb.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-muted">
        <span class="spinner" style="width:18px;height:18px;vertical-align:-4px"></span>
        &nbsp; Đang quét board…</td></tr>`;
    } else {
      emptyEl.textContent = `Không board nào khớp “${DEV_Q}”.`;
      emptyEl.hidden = false;
    }
    return;
  }
  emptyEl.hidden = true;
  DEV_PAGE = clampPage(DEV_PAGE, list.length);
  const slice = list.slice((DEV_PAGE - 1) * PAGE_SIZE, DEV_PAGE * PAGE_SIZE);
  slice.forEach(d => {
    const online = d.board_online;
    const model = d.model || "";
    const phoneName = d.device_name || "";
    const statusHtml = online
      ? `<span class="dot on"></span><span class="txt">online</span>`
      : (SCANNING
          ? `<span class="spinner" style="width:12px;height:12px;border-width:2px"></span><span class="txt">quét…</span>`
          : `<span class="dot off"></span><span class="txt">offline</span>`);
    // cột iPhone gộp gọn: dòng 1 = model · tên máy; dòng 2 = iOS + UDID
    let phoneCell;
    if (d.udid || d.ios) {
      const title = d.ios
        ? `${esc(model || "iPhone")}${phoneName ? ` <span class="cell-sub" style="font-weight:400">· ${esc(phoneName)}</span>` : ""}`
        : "";
      const iosP = d.ios ? `<span class="pill ok">iOS ${esc(d.ios)}</span>` : `<span class="pill warn">chưa kết nối</span>`;
      phoneCell = `${title ? `<div class="cell-name">${title}</div>` : ""}
        <div class="cell-pills">${iosP} ${udidCell(d.udid)}</div>`;
    } else {
      phoneCell = `<span class="pill mut">chưa gán iPhone</span>`;
    }

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="col-status">
        <div class="status-cell">${statusHtml}</div>
        ${online ? bleBadge(d.ble) : ""}</td>
      <td>
        <div class="cell-name">${esc(d.label || d.name)}</div>
        <div class="cell-sub mono nowrap">${esc(d.name)} · ${esc(shortPort(d.port))}</div>
        <div class="cell-grp">
          <span class="group-chip ${d.group_id ? "has" : ""}" title="Các nhóm máy này thuộc về (thêm / bớt máy trong trang của từng nhóm)">${d.group_name ? "👥 " + esc(d.group_name) : "Chưa vào nhóm nào"}</span>
          ${d.running ? `<span class="pill ok" style="font-size:.66rem" title="Một máy chỉ chạy một kịch bản một lúc">▶ đang chạy ${esc([d.run_group, d.run_script].filter(Boolean).join(" · "))}</span>` : ""}
        </div>
        <div class="cell-run">${runControlsHtml(d.name, devRunState(d))}</div></td>
      <td>${phoneCell}</td>
      <td class="ta-r">
        <div class="row-actions-h">
          ${(d.board_online && d.ble === true) ? `<button class="btn btn-sm btn-primary" data-probe="${esc(d.name)}" title="Rung chuột để nhận diện iPhone đang nối board này">Dò máy</button>` : ""}
          ${d.udid ? `<button class="btn btn-sm btn-label-secondary" data-ready="${esc(d.udid)}" data-rname="${esc(d.label || d.name)}">Kiểm tra</button>` : ""}
          <button class="btn btn-sm btn-label-secondary" data-edit="${esc(d.name)}">Sửa</button>
          ${d.configured ? `<button class="btn btn-sm btn-label-danger" data-del="${esc(d.name)}">Xoá</button>` : ""}
        </div></td>`;
    tb.appendChild(tr);
  });
  $$("[data-edit]", tb).forEach(b => b.onclick = () => editDevice(b.dataset.edit));
  $$("[data-ready]", tb).forEach(b => b.onclick = () => openReadiness(b.dataset.ready, b.dataset.rname));
  $$("[data-del]", tb).forEach(b => b.onclick = () => deleteDevice(b.dataset.del));
  $$("[data-probe]", tb).forEach(b => b.onclick = () => probeMatch(b.dataset.probe));
  bindRunControls(tb);
  wireCopyUdid(tb);
  renderPager("dev-pager", list.length, DEV_PAGE, p => { DEV_PAGE = p; renderDevices(); });
}

async function deleteDevice(name) {
  if (!confirmBox(`Xoá thiết bị “${name}” khỏi danh sách?\n(Chỉ xoá cấu hình trong app — không ảnh hưởng iPhone hay board ESP.)`)) return;
  try {
    const r = await API().delete_device(name);
    if (r && r.ok === false) { toast("Lỗi: " + (r.error || "?"), "bad"); return; }
    toast("Đã xoá " + name, "ok");
    await loadDevices();
  } catch (e) { toast("Lỗi xoá: " + e, "bad"); }
}

/* =========================================================
   DÒ MÁY — nhận diện iPhone đang nối board (rung chuột + so màn)
   ========================================================= */
async function probeMatch(name) {
  if (PROBING) { toast("Đang dò máy khác, chờ chút…", "warn"); return; }
  PROBING = true;
  $("#probe-sub").textContent = `Board: ${name}`;
  $("#probe-body").innerHTML = `<div class="py-4 text-center text-muted">
    <span class="spinner"></span><br><br>
    Đang rung chuột qua board &amp; so màn hình các iPhone…<br>
    <span class="small">Đừng động vào máy. Cần iPhone bật AssistiveTouch (con trỏ hiện) + đã mount DDI.</span></div>`;
  $("#probe-modal").hidden = false;
  try {
    const r = await API().probe_match(name);
    renderProbe(name, r);
    if (r && r.ok) await loadDevices();
  } catch (e) {
    $("#probe-body").innerHTML = `<div class="text-danger p-2">Lỗi: ${esc(e)}</div>`;
  } finally {
    PROBING = false;
  }
}

function renderProbe(name, r) {
  const body = $("#probe-body");
  const rankHtml = (r && r.ranked && r.ranked.length)
    ? `<div class="mt-3 small text-muted">Mức phản ứng từng máy: ${r.ranked.map(x => `${esc(x.name || "?")} = ${x.score}`).join(" · ")}</div>`
    : "";
  if (!r || !r.ok) {
    body.innerHTML = `<div class="pill warn" style="padding:.45rem .75rem">${esc((r && r.error) || "Không xác định được máy")}</div>${rankHtml}
      <div class="mt-3"><button class="btn btn-sm btn-primary" data-reprobe="${esc(name)}">Dò lại</button></div>`;
  } else {
    body.innerHTML = `
      <div class="pill ok mb-3" style="padding:.45rem .75rem">✓ Đã nhận diện &amp; gán vào board ${esc(name)}</div>
      <div class="ov-kv"><span>iPhone</span><span>${esc(r.name || "—")}</span></div>
      <div class="ov-kv"><span>Model</span><span>${esc(r.model || "—")}</span></div>
      <div class="ov-kv"><span>iOS</span><span>${esc(r.ios || "—")}</span></div>
      <div class="ov-kv"><span>UDID</span><span class="mono">${esc((r.udid || "").slice(0, 18))}…</span></div>
      ${r.shot ? `<img src="${r.shot}" alt="màn hình" style="width:100%;max-height:340px;object-fit:contain;margin-top:12px;border-radius:10px;border:1px solid var(--bs-border-color)">` : ""}
      ${rankHtml}`;
    toast(`Board ${name} → ${r.name || (r.udid || "").slice(0, 8)}`, "ok");
  }
  $$("[data-reprobe]", body).forEach(b => b.onclick = () => probeMatch(b.dataset.reprobe));
}

function renderIOS() {
  const tb = $("#ios-tbody");
  tb.innerHTML = "";
  const cnt = $("#seg-ios-c"); if (cnt) cnt.textContent = IOS.length;
  const lbl = $("#ios-count-lbl"); if (lbl) lbl.textContent = IOS.length ? `${IOS.length} máy` : "";
  const list = IOS.filter(matchIos);
  const emptyEl = $("#ios-empty");
  if (!list.length) {
    renderPager("ios-pager", 0, 1, () => {});
    if (!IOS.length) {
      emptyEl.textContent = "Không có iPhone nào đang cắm.";
      emptyEl.hidden = IOS_LOADING;
      if (IOS_LOADING) tb.innerHTML = `<tr><td colspan="3" class="p-4 text-center text-muted">
        <span class="spinner" style="width:18px;height:18px;vertical-align:-4px"></span>
        &nbsp; Đang tải iPhone…</td></tr>`;
    } else {
      emptyEl.textContent = `Không iPhone nào khớp “${DEV_Q}”.`;
      emptyEl.hidden = false;
    }
    return;
  }
  emptyEl.hidden = true;
  const mapped = new Set(DEVICES.filter(d => d.udid).map(d => d.udid));
  IOS_PAGE = clampPage(IOS_PAGE, list.length);
  const slice = list.slice((IOS_PAGE - 1) * PAGE_SIZE, IOS_PAGE * PAGE_SIZE);
  slice.forEach(p => {
    const isMapped = mapped.has(p.udid);
    const dv = DEVICES.find(d => d.udid && d.udid === p.udid);          // board đang điều khiển iPhone này (nếu đã gán)
    const u = esc(p.udid || "");
    const nm = esc(p.name || "—");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <div class="cell-name">${nm}</div>
        <div class="cell-pills">${isMapped
          ? `<span class="pill ok">đã gán board</span>`
          : `<span class="pill warn">chưa gán board</span>`}
          ${dv && dv.running ? `<span class="pill ok" style="font-size:.66rem">▶ đang chạy ${esc([dv.run_group, dv.run_script].filter(Boolean).join(" · "))}</span>` : ""}</div>
        ${dv ? `<div class="cell-run">${runControlsHtml(dv.name, devRunState(dv))}</div>` : ""}</td>
      <td>
        <div class="cell-name">${esc(p.model || p.product_type || "iPhone")}</div>
        <div class="cell-pills">${p.ios ? `<span class="pill ok">iOS ${esc(p.ios)}</span>` : `<span class="pill mut">—</span>`} ${udidCell(p.udid, "—")}</div></td>
      <td class="ta-r">
        <div class="row-actions-h">
          <button class="btn btn-sm btn-primary"          data-iosact="check"   data-u="${u}" data-nm="${nm}">Kiểm tra</button>
          <button class="btn btn-sm btn-label-secondary"  data-iosact="pair"    data-u="${u}">Ghép nối</button>
          <button class="btn btn-sm btn-label-secondary"  data-iosact="devmode" data-u="${u}">Bật Dev</button>
          <button class="btn btn-sm btn-label-secondary"  data-iosact="mount"   data-u="${u}">Mount</button>
          ${isMapped ? "" : `<button class="btn btn-sm btn-label-secondary" data-iosact="assign" data-u="${u}" data-nm="${nm}">Gán board</button>`}
        </div></td>`;
    tb.appendChild(tr);
  });
  $$("[data-iosact]", tb).forEach(b => b.onclick = () => iosRowAction(b.dataset.iosact, b));
  bindRunControls(tb);
  wireCopyUdid(tb);
  renderPager("ios-pager", list.length, IOS_PAGE, p => { IOS_PAGE = p; renderIOS(); });
}

async function iosRowAction(act, btn) {
  const u = btn.dataset.u;
  if (!u) { toast("iPhone này chưa đọc được UDID", "warn"); return; }
  if (act === "check")  return openReadiness(u, btn.dataset.nm || "");
  if (act === "assign") return assignBoard(u, btn.dataset.nm || "");
  const map = {
    pair:    { note: "Nhìn iPhone → bấm “Tin cậy” + nhập passcode." },
    devmode: { confirm: "Bật Developer Mode sẽ KHỞI ĐỘNG LẠI iPhone. Tiếp tục?",
               note: "Khởi động lại xong: mở khoá máy → xác nhận Developer Mode." },
    mount:   { note: "Đang tải & mount DDI (lần đầu cần mạng)." },
  }[act];
  const fn = { pair: "ios_pair", devmode: "ios_enable_devmode", mount: "ios_mount" }[act];
  if (!fn) return;
  if (map.confirm && !confirmBox(map.confirm)) return;
  busy(btn, true);
  try {
    const r = await API()[fn](u);
    if (r && r.ok) { toast("Xong", "ok"); if (map.note) toast(map.note, ""); }
    else toast("Lỗi: " + ((r && (r.log || r.error)) || "không rõ"), "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}

async function assignBoard(udid, name) {
  if (!DEVICES.length) { toast("Chưa có board nào. Quét board trước rồi gán.", "warn"); return; }
  const options = DEVICES.map(d => ({
    value: d.name,
    label: d.name
      + (d.ble === true ? "  ·  ● Bluetooth đang nối" : d.ble === false ? "  ·  Bluetooth rớt" : "")
      + (d.udid ? (d.udid === udid ? "  ·  (máy này)" : "  ·  (đã gán máy khác)") : "  ·  (trống)")
  }));
  // ưu tiên board ĐANG NỐI Bluetooth và chưa gán — nhiều khả năng là cái đang điều khiển máy này
  const prefer = DEVICES.find(d => d.ble === true && !d.udid)
              || DEVICES.find(d => d.ble === true) || DEVICES[0];
  const r = await askForm("Gán iPhone vào board",
    `iPhone: ${name} · ${udid.slice(0, 12)}…\nMẹo: chọn board đang “Bluetooth nối” — đó là board đang điều khiển máy này.`, [
    { key: "board", label: "Chọn board", type: "select", value: prefer.name, options },
    { key: "label", label: "Nhãn hiển thị", value: name, placeholder: "VD: Máy 01" },
  ]);
  if (!r || !r.board) return;
  try {
    const res = await API().set_udid(r.board.trim(), udid, r.label.trim());
    if (res && res.ok === false) { toast("Lỗi: " + (res.error || "?"), "bad"); return; }
    toast("Đã gán iPhone vào " + r.board, "ok");
    await loadDevices();
  } catch (e) { toast("Lỗi gán: " + e, "bad"); }
}

async function editDevice(name) {
  const d = DEVICES.find(x => x.name === name);
  if (!d) return;
  const fields = [];
  if (IOS.length || d.udid) {
    const opts = [{ value: "", label: "— Bỏ trống (gỡ gán) —" }];
    IOS.forEach(p => opts.push({ value: p.udid,
      label: `${p.name || "iPhone"} · ${p.model || p.product_type || ""} · ${(p.udid || "").slice(0, 8)}…` }));
    if (d.udid && !IOS.some(p => p.udid === d.udid))   // máy đã gán nhưng giờ không cắm USB
      opts.push({ value: d.udid, label: `(đã gán, hiện không cắm) ${d.udid.slice(0, 8)}…` });
    fields.push({ key: "udid", label: "iPhone (chọn máy đang cắm USB)", type: "select", value: d.udid || "", options: opts });
  } else {
    fields.push({ key: "udid", label: "UDID iPhone", value: d.udid || "", placeholder: "40 ký tự UDID" });
  }
  fields.push({ key: "label", label: "Nhãn hiển thị", value: d.label || "", placeholder: "VD: Máy 01" });
  const r = await askForm("Gán iPhone cho board", `Board: ${name}`, fields);
  if (!r) return;
  try {
    const res = await API().set_udid(name, r.udid.trim(), r.label.trim());
    if (res && res.ok === false) { toast("Lỗi: " + (res.error || "không rõ"), "bad"); return; }
    toast("Đã cập nhật " + name, "ok");
    await loadDevices();
  } catch (e) { toast("Lỗi: " + e, "bad"); }
}

async function rescan(btn) {
  busy(btn, true);
  setConn(true, "Đang quét…");
  try {
    const r = await API().rescan();
    if (r && r.ok === false) { toast("Lỗi quét: " + (r.error || ""), "bad"); }
    else toast("Đã quét lại board", "ok");
    await loadDevices();
  } catch (e) { toast("Lỗi quét: " + e, "bad"); }
  busy(btn, false);
}

/* =========================================================
   TỔNG QUAN — hệ thống, thư viện, công cụ
   ========================================================= */
function osIcon(os) {
  return os === "macOS" ? "tabler-brand-apple"
       : os === "Windows" ? "tabler-brand-windows"
       : "tabler-brand-ubuntu";
}

async function loadOverview() {
  const body = $("#ov-body");
  body.innerHTML = `<div class="py-5 text-center text-muted"><span class="spinner"></span>&nbsp; Đang kiểm tra hệ thống…</div>`;
  let r;
  try { r = await API().sys_overview(); }
  catch (e) { body.innerHTML = `<div class="text-danger p-3">Lỗi: ${esc(e)}</div>`; return; }
  if (!r || !r.ok) { body.innerHTML = `<div class="text-danger p-3">Lỗi: ${esc((r && r.error) || "không rõ")}</div>`; return; }
  renderOverview(r);
}

function renderOverview(r) {
  const s = r.system;
  const pm = [s.has_brew ? "brew" : null, s.has_apt ? "apt" : null, s.has_winget ? "winget" : null].filter(Boolean).join(", ") || "—";
  const sysCard = `
    <div class="card mb-4"><div class="card-body">
      <div class="d-flex align-items-center gap-3 mb-3">
        <div class="ov-os"><i class="ti ${osIcon(s.os)}"></i></div>
        <div>
          <div class="h5 mb-1">${esc(s.os)} <span class="text-muted fw-normal">${esc(s.os_version)}</span></div>
          <div class="text-muted small">${esc(s.arch)} · Python ${esc(s.python)}
            ${s.python_ok ? `<span class="pill ok">OK</span>` : `<span class="pill bad">cần ≥ 3.9</span>`}</div>
        </div>
      </div>
      <div class="ov-kv"><span>Thư mục môi trường</span><span class="mono">${esc(s.venv)}</span></div>
      <div class="ov-kv"><span>Trình quản lý gói</span><span>${esc(pm)}</span></div>
    </div></div>`;

  const pkgMissing = r.packages.filter(p => !p.ok);
  const pkgRows = r.packages.map(p => `
    <div class="ready-item">
      <div class="ready-ico ${p.ok ? "ok" : "bad"}">${p.ok ? "✓" : "✕"}</div>
      <div class="ready-info"><div class="ready-title">${esc(p.name)} ${p.version ? `<span class="text-muted" style="font-weight:400;font-size:.78rem">v${esc(p.version)}</span>` : ""}</div>
        <div class="ready-desc">${esc(p.desc)}</div></div>
      <div class="ready-act">${p.ok ? `<span class="pill ok">đã cài</span>` : `<button class="btn btn-sm btn-primary" data-pip="${esc(p.name)}">Cài</button>`}</div>
    </div>`).join("");
  const pkgCard = `
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">Thư viện Python <span class="text-muted" style="font-size:.8rem">(${r.pkgs_ok}/${r.pkgs_total})</span></h5>
        ${pkgMissing.length ? `<button class="btn btn-sm btn-primary" id="btn-pip-all">Cài tất cả thiếu (${pkgMissing.length})</button>` : `<span class="pill ok">Đủ</span>`}
      </div>
      <div class="card-body">${pkgRows}</div>
    </div>`;

  const toolRows = r.tools.map(t => `
    <div class="ready-item">
      <div class="ready-ico ${t.ok ? "ok" : "bad"}">${t.ok ? "✓" : "✕"}</div>
      <div class="ready-info"><div class="ready-title">${esc(t.name)}</div>
        <div class="ready-desc">${esc(t.desc)}${!t.ok && t.cmd ? `<div class="ov-cmd mono">${esc(t.cmd)}</div>` : ""}</div></div>
      <div class="ready-act">${t.ok ? `<span class="pill ok">đã cài</span>` :
        `<button class="btn btn-sm btn-primary" data-tool="${esc(t.name)}">Cài</button>
         ${t.cmd ? `<button class="btn btn-sm btn-label-secondary" data-copy="${esc(t.cmd)}">Copy</button>` : ""}`}</div>
    </div>`).join("");
  const toolCard = `
    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">Công cụ hệ thống <span class="text-muted" style="font-size:.8rem">(${r.tools_ok}/${r.tools_total})</span></h5>
        ${r.tools_ok === r.tools_total ? `<span class="pill ok">Đủ</span>` : `<span class="pill warn">thiếu ${r.tools_total - r.tools_ok}</span>`}
      </div>
      <div class="card-body">${toolRows}</div>
    </div>`;

  $("#ov-body").innerHTML = sysCard + pkgCard + toolCard;

  $$("[data-pip]", $("#ov-body")).forEach(b => b.onclick = () => installPip([b.dataset.pip], b));
  const allBtn = $("#btn-pip-all"); if (allBtn) allBtn.onclick = () => installPip("all", allBtn);
  $$("[data-tool]", $("#ov-body")).forEach(b => b.onclick = () => installTool(b.dataset.tool, b));
  $$("[data-copy]", $("#ov-body")).forEach(b => b.onclick = () => copyText(b.dataset.copy));
}

function logOv(t) {
  const c = $("#ov-logcard"), l = $("#ov-log");
  c.hidden = false; l.textContent += (t + "\n"); l.scrollTop = l.scrollHeight;
}

async function copyText(t) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(t);
    } else {
      // pywebview (file://) không có clipboard API → fallback execCommand
      const ta = document.createElement("textarea");
      ta.value = t; ta.style.position = "fixed"; ta.style.top = "-1000px"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    toast("Đã copy", "ok");
  } catch (e) { toast("Không copy được — tự bôi đen & copy", "warn"); }
}

/* =========================================================
   Nạp lại + tự động đọc lại (áp dụng toàn app)
   ========================================================= */
let AUTO_SECS = 0, AUTO_TIMER = null;

function refreshCurrentView(manual = false) {
  // bỏ qua khi đang quét/dò hoặc đang mở hộp thoại để không gián đoạn thao tác
  if (PROBING) return;
  if (SCANNING && !manual) return;
  const m1 = $("#modal"), m2 = $("#ready-modal"), m3 = $("#probe-modal");
  if (!manual && ((m1 && !m1.hidden) || (m2 && !m2.hidden) || (m3 && !m3.hidden))) return;
  const active = $(".view.active");
  const id = active ? active.id : "";
  if (id === "view-overview") loadOverview();
  else if (id === "view-esp" || id === "view-devices") { if (!SCANNING) espScan(); }
  else if (id === "view-flows") loadDevices();
  else if (id === "view-ai") loadAI();             // trang AI không đụng cổng serial → không quét board
  else espScan();
}

function setAuto(secs) {
  AUTO_SECS = secs | 0;
  try { localStorage.setItem("ipf-auto", String(AUTO_SECS)); } catch (e) {}
  if (AUTO_TIMER) { clearInterval(AUTO_TIMER); AUTO_TIMER = null; }
  if (AUTO_SECS > 0) AUTO_TIMER = setInterval(() => refreshCurrentView(false), AUTO_SECS * 1000);
}

async function installPip(names, btn) {
  busy(btn, true);
  logOv(`$ pip install ${names === "all" ? "(các gói thiếu)" : names.join(" ")}  — có thể mất 1–2 phút…`);
  try {
    const r = await API().sys_install_pip(names === "all" ? null : names);
    logOv(r.log || "");
    toast(r && r.ok ? "Cài thư viện xong" : "Cài thất bại — xem nhật ký", r && r.ok ? "ok" : "bad");
  } catch (e) { logOv("Lỗi: " + e); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  loadOverview();
}

async function installTool(name, btn) {
  busy(btn, true);
  logOv(`$ cài ${name}…`);
  try {
    const r = await API().sys_install_tool(name);
    logOv(r.log || "");
    if (r && r.ok) toast(name + ": cài xong", "ok");
    else if (r && r.manual) toast("Cần chạy lệnh tay — xem nhật ký bên dưới", "warn");
    else toast("Cài " + name + " thất bại", "bad");
  } catch (e) { logOv("Lỗi: " + e); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  loadOverview();
}

/* =========================================================
   Kiểm tra iPhone (sẵn sàng chụp màn hình)
   ========================================================= */
let READY_UDID = null, READY_NAME = "", READY_BOARD = "", READY_BLE = null;

function openReadiness(udid, name) {
  READY_UDID = udid; READY_NAME = name || "";
  const dev = DEVICES.find(d => d.udid === udid);
  READY_BOARD = dev ? dev.name : "";
  READY_BLE = dev ? dev.ble : null;   // theo lần quét gần nhất; có nút "Dò lại" để kiểm tra trực tiếp
  $("#ready-sub").textContent = `${name || ""} · ${udid.slice(0, 12)}…`;
  $("#ready-modal").hidden = false;
  checkReady();
}

async function checkReady() {
  const body = $("#ready-body");
  body.innerHTML = `<div class="py-4 text-center text-muted"><span class="spinner"></span>&nbsp; Đang kiểm tra…</div>`;
  let r;
  try { r = await API().ios_check(READY_UDID); }
  catch (e) { body.innerHTML = `<div class="text-danger p-2">Lỗi: ${esc(e)}</div>`; return; }
  if (!r || !r.ok) { body.innerHTML = `<div class="text-danger p-2">Lỗi: ${esc((r && r.error) || "không rõ")}</div>`; return; }
  renderReady(r);
}

function readyRow(ok, title, desc, actionsHtml) {
  return `<div class="ready-item">
    <div class="ready-ico ${ok ? "ok" : "bad"}">${ok ? "✓" : "✕"}</div>
    <div class="ready-info"><div class="ready-title">${esc(title)}</div><div class="ready-desc">${desc}</div></div>
    <div class="ready-act">${ok ? `<span class="pill ok">OK</span>` : actionsHtml}</div>
  </div>`;
}

function renderReady(r) {
  const body = $("#ready-body");
  const ble = READY_BLE;
  const shotBadge = r.ready
    ? `<span class="pill ok">✓ Chụp màn hình (USB): sẵn sàng</span>`
    : `<span class="pill warn">Chụp màn hình (USB): chưa sẵn sàng</span>`;
  const bleBadge = ble === true ? `<span class="pill ok">✓ Điều khiển (Bluetooth): đã nối</span>`
                 : ble === false ? `<span class="pill bad">✕ Điều khiển (Bluetooth): chưa nối</span>`
                 : `<span class="pill mut">Điều khiển (Bluetooth): ?</span>`;
  const bleDesc = ble === true
    ? "Board ESP32 đã nối Bluetooth với iPhone — bấm/gõ được."
    : "Vào iPhone → Bluetooth → ghép lại board ESP32 (nếu vừa xoá/nạp thì “Quên thiết bị này” rồi ghép lại).";
  body.innerHTML = `
    <div class="mb-3 d-flex flex-wrap gap-2">${shotBadge}${bleBadge}</div>
    <div class="ready-sec">Chụp màn hình — qua cáp USB</div>
    ${readyRow(r.trusted, "Tin cậy máy tính (Trust)", "Cắm USB → bấm “Tin cậy” + nhập passcode trên iPhone",
      `<button class="btn btn-sm btn-primary" data-act="pair">Ghép nối</button>`)}
    ${readyRow(r.dev_mode, "Developer Mode", "iOS 16+ cần bật (máy sẽ khởi động lại)",
      `<button class="btn btn-sm btn-primary" data-act="devmode">Bật</button>
       <button class="btn btn-sm btn-label-secondary" data-act="reveal">Hiện mục</button>`)}
    ${readyRow(r.ddi, "Developer Disk Image", "Mount để chụp màn (lần đầu cần mạng)",
      `<button class="btn btn-sm btn-primary" data-act="mount">Tải &amp; Mount</button>`)}
    <div class="ready-sec">Điều khiển chuột/phím — qua Bluetooth</div>
    ${readyRow(ble === true, "Bluetooth (board ESP32 ↔ iPhone)", bleDesc,
      `<button class="btn btn-sm btn-label-secondary" data-act="blerecheck">Dò lại</button>`)}`;
  $$("[data-act]", body).forEach(b => b.onclick = () => readyAction(b.dataset.act, b));
}

async function recheckBle(btn) {
  if (!READY_BOARD) { toast("Board chưa gán, không dò được", "warn"); return; }
  busy(btn, true);
  try {
    const r = await API().ble_status(READY_BOARD);
    if (r && r.ok) READY_BLE = !String(r.status).includes("disconnected");
    else { READY_BLE = null; toast("Không dò được: " + ((r && r.error) || "?"), "warn"); }
  } catch (e) { READY_BLE = null; toast("Lỗi dò BLE: " + e, "bad"); }
  const d = DEVICES.find(x => x.name === READY_BOARD);
  if (d) { d.ble = READY_BLE; renderDevices(); updateCounts(); }
  busy(btn, false);
  checkReady();   // dựng lại đầy đủ (query lại USB + BLE mới) để chắc chắn
}

async function readyAction(act, btn) {
  if (act === "blerecheck") return recheckBle(btn);
  const map = {
    pair:    { fn: "ios_pair",           confirm: null, note: "Nhìn iPhone và bấm “Tin cậy” + nhập passcode." },
    devmode: { fn: "ios_enable_devmode", confirm: "Bật Developer Mode sẽ KHỞI ĐỘNG LẠI iPhone. Tiếp tục?",
               note: "Sau khi khởi động lại: mở khóa máy → xác nhận Developer Mode → bấm “Kiểm tra lại”." },
    reveal:  { fn: "ios_reveal_devmode", confirm: null, note: "Mở Cài đặt → Quyền riêng tư & Bảo mật → Developer Mode." },
    mount:   { fn: "ios_mount",          confirm: null, note: null },
  }[act];
  if (!map) return;
  if (map.confirm && !confirmBox(map.confirm)) return;
  busy(btn, true);
  try {
    const r = await API()[map.fn](READY_UDID);
    if (r && r.ok) { toast("Xong", "ok"); if (map.note) toast(map.note, ""); }
    else toast("Lỗi: " + ((r && r.log) || "không rõ"), "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  setTimeout(checkReady, 900);
}

/* =========================================================
   ESP32
   ========================================================= */
async function espScan(btn) {
  if (PROBING) { if (btn) toast("Đang dò máy, thử lại sau khi xong", "warn"); return; }
  busy(btn, true);
  SCANNING = true;
  $("#esp-summary").textContent = "Đang quét cổng USB…";
  renderDevices();                     // hiện "đang quét" ở bảng thiết bị
  try {
    ESP = await API().esp_scan() || []; // trả ngay các cổng (flashed=null) → hiện khung + spinner
    ESP_SCANNED = true;
  } catch (e) { toast("Lỗi quét ESP: " + e, "bad"); ESP = []; SCANNING = false; }
  renderESP();
  updateCounts();
  updateEspSummary();
  busy(btn, false);
  // kết quả từng board về qua __espUpdate/__devBoard; __scanDone kết thúc
}

function updateEspSummary() {
  const pending = ESP.filter(b => b.flashed === null || b.flashed === undefined).length;
  $("#esp-summary").textContent = pending
    ? `Đang kiểm tra ${ESP.length - pending}/${ESP.length} board…`
    : (ESP.length ? `Tìm thấy ${ESP.length} board trên USB.`
                  : "Không thấy board nào. Cắm ESP32 rồi bấm “Quét board”.");
}

function renderESP() {
  const grid = $("#esp-grid");
  grid.innerHTML = "";
  $("#esp-empty").hidden = ESP.length > 0;
  ESP.forEach((b, idx) => {
    const card = document.createElement("div");
    card.className = "esp-card";
    card.dataset.port = b.port;
    const loading = (b.flashed === null || b.flashed === undefined);
    const flashed = b.flashed === true;
    const working = !!b.busy;            // máy đang chạy: lượt quét không đụng vào cổng của nó
    const badge = loading
      ? `<span class="pill mut"><span class="spinner" style="width:10px;height:10px;border-width:2px;vertical-align:-1px"></span> đang dò</span>`
      : working ? (b.locked ? `<span class="pill mut">🔒 đang được điều khiển</span>` : `<span class="pill ok">▶ đang chạy</span>`)
      : flashed ? `<span class="pill ok">đã nạp</span>` : `<span class="pill bad">chưa nạp</span>`;

    let body = `
      <div class="esp-top">
        <div>
          <div class="esp-port">${esc(b.port)}</div>
          <div class="esp-chip">${esc(b.chip_desc || "ESP32")}</div>
        </div>
        ${badge}
      </div>
      <div class="esp-meta">
        ${b.serial ? `<div class="row"><span>Serial</span><span class="val">${esc(b.serial)}</span></div>` : ""}
        ${(b.vid || b.pid) ? `<div class="row"><span>VID:PID</span><span class="val">${esc(b.vid || "?")}:${esc(b.pid || "?")}</span></div>` : ""}
        ${flashed ? `<div class="row"><span>Tên BLE</span><span class="val esp-name-big">${esc(b.name || "—")}</span></div>` : ""}
        ${flashed ? `<div class="row"><span>Bluetooth</span><span class="val">${b.ble === true ? "✓ đã nối iPhone" : b.ble === false ? "✕ chưa nối" : "?"}</span></div>` : ""}
        ${(flashed && b.health && b.health.ram_total) ? `<div class="row"><span>RAM</span><span class="val">dùng ${Math.round(b.health.ram_used / 1024)} / ${Math.round(b.health.ram_total / 1024)} KB (${Number(b.health.ram_pct)}%)</span></div>` : ""}
        ${(flashed && b.health) ? `<div class="esp-health ${esc(b.health.level)}" title="${esc((b.health.notes || []).join("\n"))}">${esc(b.health.ram_total ? b.health.summary.replace(/^RAM dùng [^·]*· /, "") : b.health.summary)}${(b.health.notes || []).map(n => `<div>⚠ ${esc(n)}</div>`).join("")}</div>` : ""}
      </div>`;

    if (loading) {
      body += `<div class="esp-actions"><span class="muted" style="font-size:.82rem">Đang kiểm tra firmware…</span></div>`;
    } else if (working) {
      body += b.locked
        ? `<div class="esp-actions"><span class="muted" style="font-size:.82rem">Cổng này đang do một chương trình ngoài app giữ (lệnh <b>farm</b> hoặc AI chạy lúc app chưa mở). Lần điều khiển kế tiếp sẽ tự đi qua app.</span></div>`
        : `<div class="esp-actions"><span class="muted" style="font-size:.82rem">Máy này đang chạy — dừng máy (tab Nhóm &amp; Kịch bản) rồi mới đổi tên / nạp lại được.</span></div>`;
    } else if (flashed) {
      body += `
        <div class="esp-actions">
          <button class="btn btn-sm btn-label-secondary" data-esp="rename" data-port="${esc(b.port)}" data-name="${esc(b.name || "")}">Đổi tên</button>
          <button class="btn btn-sm btn-label-secondary" data-esp="chip" data-port="${esc(b.port)}">Thông tin chip</button>
          <button class="btn btn-sm btn-label-warning" data-esp="restart" data-port="${esc(b.port)}" data-name="${esc(b.name || "")}" title="Khởi động lại board ESP32 (Bluetooth rớt vài giây rồi iPhone tự nối lại)">Khởi động lại</button>
          ${b.ble === true ? `<button class="btn btn-sm btn-label-warning" data-esp="btoff" data-port="${esc(b.port)}" data-name="${esc(b.name || "")}" title="Huỷ kết nối Bluetooth với iPhone đang nối (30 giây sau iPhone tự nối lại)">Huỷ kết nối BT</button>` : ""}
          <button class="btn btn-sm btn-danger" data-esp="erase" data-port="${esc(b.port)}">Xoá sạch</button>
        </div>`;
    } else {
      body += `
        <div class="esp-flash-row">
          <input data-flashname="${idx}" placeholder="Tên BLE, VD: iPhoneFarm-01">
          <button class="btn btn-sm btn-primary" data-esp="flash" data-port="${esc(b.port)}" data-idx="${idx}">Nạp firmware</button>
        </div>`;
    }

    body += `<div class="esp-logbox" data-logbox="${esc(b.port)}"></div>`;
    card.innerHTML = body;
    grid.appendChild(card);
  });

  $$("[data-esp]", grid).forEach(btn => {
    btn.onclick = () => handleEsp(btn.dataset.esp, btn);
  });
}

function espSpinner(card, text, on) {
  let sp = $(".card-spinner", card);
  if (on) {
    if (!sp) {
      sp = document.createElement("div");
      sp.className = "card-spinner";
      sp.innerHTML = `<span class="spinner"></span><span>${esc(text)}</span>`;
      card.appendChild(sp);
    }
    $$("button, input", card).forEach(el => { if (!el.closest(".card-spinner")) el.disabled = true; });
  } else {
    if (sp) sp.remove();
    $$("button, input", card).forEach(el => el.disabled = false);
  }
}

function showEspLog(card, logText) {
  const box = $(".esp-logbox", card);
  if (!box) return;
  box.innerHTML = `
    <details class="esp-log-wrap" open>
      <summary>Nhật ký thao tác</summary>
      <div class="esp-log">${esc(logText || "(trống)")}</div>
    </details>`;
}

async function handleEsp(action, btn) {
  const port = btn.dataset.port;
  const card = btn.closest(".esp-card");

  if (action === "rename") {
    const newName = await askOne("Đổi tên board", "Tên BLE mới", btn.dataset.name, "iPhoneFarm-01");
    if (!newName) return;
    espSpinner(card, "Đang nạp lại firmware… (20-40s)", true);
    try {
      const r = await API().esp_flash(port, newName.trim());
      espSpinner(card, "", false);
      if (r && r.ok) { toast(`Đã đổi tên → ${r.name}`, "ok"); showEspLog(card, r.log); await espScan(); }
      else { toast("Nạp thất bại", "bad"); showEspLog(card, (r && r.log) || ""); }
    } catch (e) { espSpinner(card, "", false); toast("Lỗi: " + e, "bad"); }

  } else if (action === "flash") {
    const idx = btn.dataset.idx;
    const inp = $(`[data-flashname="${idx}"]`, card);
    const name = (inp && inp.value.trim()) || "";
    if (!name) { toast("Nhập tên BLE trước", "warn"); if (inp) inp.focus(); return; }
    espSpinner(card, "Đang biên dịch & nạp… (20-40s)", true);
    try {
      const r = await API().esp_flash(port, name);
      espSpinner(card, "", false);
      if (r && r.ok) { toast(`Đã nạp firmware: ${r.name}`, "ok"); showEspLog(card, r.log); await espScan(); }
      else { toast("Nạp thất bại", "bad"); showEspLog(card, (r && r.log) || ""); }
    } catch (e) { espSpinner(card, "", false); toast("Lỗi: " + e, "bad"); }

  } else if (action === "erase") {
    if (!confirmBox(`Xoá sạch flash của board ${port}?\n\n⚠️ CẢNH BÁO: Xoá sạch sẽ MẤT ghép nối Bluetooth với iPhone.\nSau đó iPhone sẽ KHÔNG tự thấy lại board — phải vào iPhone →\nBluetooth → "Quên thiết bị này" rồi ghép lại từ đầu.\n\n👉 Chỉ cần đổi tên / cập nhật? Hãy dùng "Đổi tên" hoặc "Nạp\nfirmware" (nạp đè) — giữ nguyên ghép nối, iPhone tự nối lại.\n\nVẫn muốn xoá sạch?`)) return;
    espSpinner(card, "Đang xoá flash… (~10s)", true);
    try {
      const r = await API().esp_erase(port);
      espSpinner(card, "", false);
      if (r && r.ok) { toast("Đã xoá sạch board", "ok"); showEspLog(card, r.log); await espScan(); }
      else { toast("Xoá thất bại", "bad"); showEspLog(card, (r && r.log) || ""); }
    } catch (e) { espSpinner(card, "", false); toast("Lỗi: " + e, "bad"); }

  } else if (action === "restart" || action === "btoff") {
    const name = btn.dataset.name;
    if (!name) { toast("Board chưa có tên BLE", "warn"); return; }
    const restart = action === "restart";
    if (!confirmBox(restart
        ? `Khởi động lại board «${name}»?\n\nBluetooth rớt vài giây rồi iPhone đã ghép tự nối lại. Không làm được khi máy đang chạy.`
        : `Huỷ kết nối Bluetooth của board «${name}» với iPhone đang nối?\n\nBoard ngừng quảng bá 30 giây (iPhone không nối lại liền), sau đó iPhone đã ghép tự nối lại. Không làm được khi máy đang chạy.`)) return;
    espSpinner(card, restart ? "Đang khởi động lại board… (~10s)" : "Đang huỷ kết nối Bluetooth…", true);
    try {
      const r = restart ? await API().board_restart(name) : await API().board_disconnect_bt(name, 30);
      espSpinner(card, "", false);
      if (r && r.ok) { toast(r.msg, "ok"); await espScan(); }
      else toast((r && r.error) || "Không làm được", "bad");
    } catch (e) { espSpinner(card, "", false); toast("Lỗi: " + e, "bad"); }

  } else if (action === "chip") {
    espSpinner(card, "Đang đọc thông tin chip… (~5s)", true);
    try {
      const r = await API().esp_chip(port);
      espSpinner(card, "", false);
      if (r && r.ok) { toast(`Chip: ${r.chip}`, "ok"); showEspLog(card, `Chip: ${r.chip}\nMAC: ${r.mac}`); }
      else { toast("Không đọc được chip", "bad"); }
    } catch (e) { espSpinner(card, "", false); toast("Lỗi: " + e, "bad"); }
  }
}

/* =========================================================
   FLOWS — device picker + screen
   ========================================================= */
function renderDevicePicker() {
  const sel = $("#flow-device");
  if (!sel) return;
  const prev = SEL;
  // ưu tiên máy trong nhóm đang chọn để thử
  const members = (GROUP && GROUP.devices) ? GROUP.devices : [];
  const pool = DEVICES.filter(d => !members.length || members.includes(d.name));
  sel.innerHTML = "";
  if (!pool.length) {
    sel.innerHTML = `<option value="">(chưa có máy)</option>`;
    SEL = null; return;
  }
  pool.forEach(d => {
    const o = document.createElement("option");
    o.value = d.name;
    o.textContent = `${d.label || d.name}${d.board_online ? "" : " (offline)"}`;
    sel.appendChild(o);
  });
  SEL = pool.some(d => d.name === prev) ? prev : pool[0].name;
  sel.value = SEL;
}

async function shot(btn) {
  if (!SEL) { toast("Chọn máy trước", "warn"); return; }
  const img = $("#screen"), hint = $("#screen-hint"), spin = $("#screen-spin");
  spin.hidden = false; busy(btn, true);
  $("#screen-info").textContent = "đang chụp…";
  try {
    const r = await API().screenshot(SEL);
    spin.hidden = true; busy(btn, false);
    if (!r || !r.ok) {
      img.style.display = "none"; hint.style.display = "";
      $("#screen-info").textContent = "lỗi chụp";
      toast("Lỗi chụp: " + ((r && r.error) || ""), "bad");
      return;
    }
    img.src = r.img; img.style.display = "block"; hint.style.display = "none";
    SCREEN = { w: r.w, h: r.h };
    $("#screen-info").textContent = `${SEL} · ${r.w}×${r.h}`;
  } catch (e) {
    spin.hidden = true; busy(btn, false);
    toast("Lỗi chụp: " + e, "bad");
  }
}

function onScreenClick(e) {
  if (!$("#pick-mode").checked || !SCREEN.w) return;
  const img = $("#screen"), rect = img.getBoundingClientRect();
  const x = Math.round((e.clientX - rect.left) / rect.width * SCREEN.w);
  const y = Math.round((e.clientY - rect.top) / rect.height * SCREEN.h);
  addStep({ type: "tap", x, y }, PICK_AT);
  if (PICK_AT != null) PICK_AT++;                                // bấm tiếp thì chèn nối tiếp ngay sau bước vừa thêm
  toast(`Đã thêm bước: bấm tại (${x}, ${y})`, "ok");
}

async function bleStatus(btn) {
  if (!SEL) { toast("Chọn máy trước", "warn"); return; }
  busy(btn, true);
  try {
    const r = await API().ble_status(SEL);
    if (r && r.ok && r.health) toast("ESP32: " + r.health.summary + (r.health.notes.length ? " — " + r.health.notes[0] : ""), r.health.level === "bad" ? "bad" : (r.health.level === "warn" || r.status.includes("disconnected")) ? "warn" : "ok");
    else if (r && r.ok) toast(r.status, r.status.includes("disconnected") ? "warn" : "ok");
    else toast("Không rõ trạng thái BLE", "warn");
  } catch (e) { toast("Lỗi BLE: " + e, "bad"); }
  busy(btn, false);
}

/* =========================================================
   FLOWS — step builder
   ========================================================= */
function stepText(s) {
  switch (s.type) {
    case "tap": return `(${s.x}, ${s.y})`;
    case "tap_text": return `“${s.text}”`;
    case "type": return `“${s.text}”`;
    case "key": return s.name;
    case "combo": return s.keys;
    case "launch": return s.app;
    case "home": return "màn hình chính";
    case "wait": return s.seconds + "s";
    case "wait_text": return `“${s.text}” (${s.timeout || 15}s)`;
    case "assert_text": return `“${s.text}”`;
    case "swipe": return s.dir ? (SWIPE_DIR[s.dir] || s.dir) : `(${s.x1}, ${s.y1}) → (${s.x2}, ${s.y2})`;
    case "hold": return `(${s.x}, ${s.y}) · ${s.seconds || 1}s`;
    case "hold_text": return `“${s.text}” · ${s.seconds || 1}s`;
    default: return "";
  }
}
const SWIPE_DIR = { left: "sang trái (trang sau)", right: "sang phải (trang trước)", up: "lên (cuộn xuống dưới)", down: "xuống (cuộn lên trên)" };
const STEP_LABEL = {
  tap: "Tap", tap_text: "Tap chữ", type: "Gõ", key: "Phím", combo: "Tổ hợp",
  launch: "Mở app", home: "Home", wait: "Chờ", wait_text: "Chờ chữ", assert_text: "Kiểm chữ",
  swipe: "Vuốt", hold: "Bấm giữ", hold_text: "Giữ chữ",
};

// Loại bước → [nhóm (màu biểu tượng), biểu tượng]. Nhóm: touch = chạm · key = bàn phím · app = ứng dụng · wait = chờ và kiểm.
const STEP_KIND = {
  tap: ["touch", "tabler-pointer"], tap_text: ["touch", "tabler-hand-finger"], hold: ["touch", "tabler-hand-stop"],
  hold_text: ["touch", "tabler-hand-stop"], swipe: ["touch", "tabler-hand-move"],
  type: ["key", "tabler-keyboard"], key: ["key", "tabler-keyboard"], combo: ["key", "tabler-command"],
  launch: ["app", "tabler-apps"], home: ["app", "tabler-home"],
  wait: ["wait", "tabler-clock"], wait_text: ["wait", "tabler-eye"], assert_text: ["wait", "tabler-checks"],
};
// Phần do người dùng nhập của một bước: in đậm; {{biến}} thành nhãn riêng để thấy ngay chỗ nào lấy dữ liệu.
function stepVal(v) {
  return `<b>${esc(String(v ?? "")).replace(/\{\{\s*([A-Za-z0-9_.]+)\s*\}\}/g, "<code>{{$1}}</code>")}</b>`;
}
// Một bước viết thành MỘT CÂU đọc được: «Bấm vào chữ «Mua»», «Chờ thấy chữ «Shop» tối đa 15 giây».
function stepSentence(s) {
  const dim = (t) => ` <span class="flow-dim">${esc(t)}</span>`;
  switch (s.type) {
    case "tap": return `Bấm tại ${stepVal(`(${s.x}, ${s.y})`)}`;
    case "tap_text": return `Bấm vào chữ ${stepVal(`«${s.text}»`)}`;
    case "type": return `Gõ ${stepVal(s.text)}`;
    case "key": return `Nhấn phím ${stepVal(s.name)}`;
    case "combo": return `Nhấn tổ hợp ${stepVal(s.keys)}`;
    case "launch": return `Mở app ${stepVal(s.app)}`;
    case "home": return "Về màn hình chính";
    case "wait": return `Chờ ${stepVal(`${s.seconds} giây`)}`;
    case "wait_text": return `Chờ thấy chữ ${stepVal(`«${s.text}»`)}${dim(`tối đa ${s.timeout || 15} giây`)}`;
    case "assert_text": return `Kiểm có chữ ${stepVal(`«${s.text}»`)}`;
    case "swipe": return s.dir ? `Vuốt ${stepVal(SWIPE_DIR[s.dir] || s.dir)}` : `Vuốt từ ${stepVal(`(${s.x1}, ${s.y1})`)} tới ${stepVal(`(${s.x2}, ${s.y2})`)}`;
    case "hold": return `Bấm giữ tại ${stepVal(`(${s.x}, ${s.y})`)}${dim(`trong ${s.seconds || 1} giây`)}`;
    case "hold_text": return `Bấm giữ vào chữ ${stepVal(`«${s.text}»`)}${dim(`trong ${s.seconds || 1} giây`)}`;
    default: return `${esc(STEP_LABEL[s.type] || s.type)} ${stepVal(stepText(s))}`;
  }
}

let STEP_RES = new WeakMap();        // bước (đối tượng) → {ok, msg} của lần thử gần nhất. Sửa bước tạo đối tượng mới nên kết quả cũ tự mất.
let ADD_AT = null;                   // bảng chọn hành động đang mở để CHÈN vào vị trí này (null = thêm vào cuối)
let PICK_AT = null;                  // lần bấm lên ảnh kế tiếp chèn bước chạm vào vị trí này (null = thêm vào cuối)

function updateDirty() {
  const el = $("#ed-dirty");
  if (el) el.hidden = !(GROUP_PAGE === "detail" && GROUP_SUB === "script" && groupDirty());
}

// Các bước vẽ thành LỘ TRÌNH: mỗi bước là một trạm đánh số trên đường ray; thử xong thì trạm đổi màu (xanh = được, đỏ = trượt) kèm lời báo.
function renderSteps() {
  const ol = $("#steps"), pal = $("#step-palette"), n = FLOW.steps.length;
  closePalette();                                                 // bảng chọn có thể đang nằm trong một <li> sắp bị vẽ lại → đưa về chỗ cũ trước
  ol.innerHTML = "";
  $("#steps-empty").hidden = n > 0;
  $("#step-count").textContent = n ? String(n) : "";
  $("#step-add-label").textContent = n ? "Thêm bước" : "Thêm bước đầu tiên";
  FLOW.steps.forEach((s, i) => {
    const [kind, icon] = STEP_KIND[s.type] || ["", "tabler-point"];
    const res = STEP_RES.get(s);
    const editable = s.type !== "home";
    const li = document.createElement("li");
    li.className = "flow-step" + (kind ? " k-" + kind : "") + (res ? (res.ok ? " is-ok" : " is-bad") : "");
    li.innerHTML = `
      <span class="flow-node" aria-hidden="true">${res ? `<i class="ti ${res.ok ? "tabler-check" : "tabler-x"}"></i>` : i + 1}</span>
      <div class="flow-body" ${editable ? `data-op="edit" role="button" tabindex="0" title="Bấm để sửa bước này"` : `style="cursor:default"`}>
        <div class="flow-line"><i class="ti ${icon} flow-ico"></i><span class="flow-text">${stepSentence(s)}${s.optional ? `<span class="flow-tag">bỏ qua nếu lỗi</span>` : ""}</span></div>
        ${res && res.msg ? `<div class="flow-result">${esc(res.msg)}</div>` : ""}
      </div>
      <div class="flow-ops">
        <button data-op="test" title="Chạy thử bước này" aria-label="Chạy thử bước ${i + 1}"><i class="ti tabler-player-play"></i></button>
        <button data-op="opt" class="${s.optional ? "on" : ""}" aria-pressed="${s.optional ? "true" : "false"}" title="Bỏ qua nếu lỗi: bước này trượt (vd không thấy chữ) thì vẫn chạy tiếp bước sau" aria-label="Bỏ qua nếu lỗi"><i class="ti tabler-arrow-forward-up"></i></button>
        <button data-op="up" title="Đưa lên" aria-label="Đưa bước ${i + 1} lên" ${i === 0 ? "disabled" : ""}><i class="ti tabler-chevron-up"></i></button>
        <button data-op="down" title="Đưa xuống" aria-label="Đưa bước ${i + 1} xuống" ${i === n - 1 ? "disabled" : ""}><i class="ti tabler-chevron-down"></i></button>
        <button data-op="del" title="Xoá bước" aria-label="Xoá bước ${i + 1}"><i class="ti tabler-trash"></i></button>
      </div>
      <button class="flow-ins" data-op="ins" title="Chèn một bước vào sau bước ${i + 1}" aria-label="Chèn một bước vào sau bước ${i + 1}">+</button>`;
    $('[data-op=opt]', li).onclick = () => { if (s.optional) delete s.optional; else s.optional = true; renderSteps(); };
    $('[data-op=up]', li).onclick = () => { if (i > 0) { [FLOW.steps[i - 1], FLOW.steps[i]] = [FLOW.steps[i], FLOW.steps[i - 1]]; renderSteps(); } };
    $('[data-op=down]', li).onclick = () => { if (i < FLOW.steps.length - 1) { [FLOW.steps[i + 1], FLOW.steps[i]] = [FLOW.steps[i], FLOW.steps[i + 1]]; renderSteps(); } };
    $('[data-op=del]', li).onclick = () => { FLOW.steps.splice(i, 1); renderSteps(); };
    $('[data-op=ins]', li).onclick = () => openPalette(i + 1, li);
    if (editable) {
      const body = $('[data-op=edit]', li);
      const edit = async () => {
        const ns = await stepPrompt(s.type, s);
        const at = FLOW.steps.indexOf(s);                         // trong lúc hộp thoại mở, danh sách có thể đã đổi
        if (ns && at >= 0) { FLOW.steps[at] = ns; renderSteps(); }
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
        if (GROUP && GROUP.mode === "api") {            // cùng bộ chạy với lúc nạp thật (thế {{biến}})
          const res = await runApiSteps([s]);
          if (res) { res.forEach(x => log(`   ${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad")); if (res[0]) out = { ok: !!res[0].ok, msg: res[0].msg }; }
        } else {
          const r = await API().run_step(SEL, s);
          log(`   ${r.ok ? "✓" : "✗"} ${r.msg}`, r.ok ? "ok" : "bad");
          out = { ok: !!r.ok, msg: r.msg };
        }
      } catch (e) { log("   ✗ " + e, "bad"); out = { ok: false, msg: String(e) }; }
      busy(b, false);
      if (out) STEP_RES.set(s, out); else STEP_RES.delete(s);
      renderSteps();
      if (["tap", "tap_text", "swipe", "hold", "hold_text"].includes(s.type)) setTimeout(() => shot(null), 900);
    };
    ol.appendChild(li);
  });
  if (!n && pal) pal.hidden = false;                              // kịch bản trống: mở sẵn bảng chọn — màn hình trống là lời mời bắt đầu
  renderApiUi();
  updateDirty();
}

/* ---- bảng chọn hành động: thêm vào cuối, hoặc chèn sau một bước ---- */
function closePalette() {
  const pal = $("#step-palette"), home = $("#flow-add");
  if (!pal || !home) return;
  pal.hidden = true;
  if (pal.parentNode !== home) home.appendChild(pal);
  ADD_AT = null;
  $$(".flow-step.ins-open").forEach(x => x.classList.remove("ins-open"));
  $("#btn-step-add").setAttribute("aria-expanded", "false");
}
function openPalette(at, host) {       // at = vị trí chèn (null = cuối); host = <li> để đặt bảng chọn ngay dưới bước đó
  const pal = $("#step-palette");
  const again = !pal.hidden && ADD_AT === at && FLOW.steps.length > 0;     // bấm lại đúng nút đang mở → đóng
  closePalette();
  if (again) return;
  ADD_AT = at;
  if (host) { host.appendChild(pal); host.classList.add("ins-open"); }
  pal.hidden = false;
  if (!host) $("#btn-step-add").setAttribute("aria-expanded", "true");
  const first = $(".pal-item", pal);
  if (first) first.focus();
}
async function pickAction(type) {
  const at = ADD_AT;
  closePalette();
  if (type === "pick") { startPick(at); return; }
  await addStepPrompt(type, at);
}
function startPick(at) {               // «Bấm theo vị trí trên ảnh»: bật chế độ bấm ảnh, bước chạm sẽ được chèn vào đúng vị trí đang chọn
  PICK_AT = at;
  $("#pick-mode").checked = true;
  $("#screen").classList.add("pick");
  if (SCREEN.w) { toast("Bấm lên ảnh màn hình để thêm bước chạm", "ok"); return; }
  toast("Chụp màn hình rồi bấm lên ảnh để thêm bước chạm", "warn");
  if (SEL) shot(null);
}

function addStep(s, at) {
  if (at == null || at < 0 || at > FLOW.steps.length) FLOW.steps.push(s);
  else FLOW.steps.splice(at, 0, s);
  renderSteps();
}

// Hỏi tham số của một bước. `cur` = bước đang SỬA (điền sẵn giá trị cũ, giữ các trường khác) hoặc null khi thêm mới.
// Trả về bước MỚI (một đối tượng khác), hoặc null nếu huỷ / nhập sai.
async function stepPrompt(type, cur) {
  const c = cur || {}, T = cur ? "Sửa bước: " : "Thêm bước: ";
  const s = cur ? JSON.parse(JSON.stringify(cur)) : { type };
  if (type === "home") return s;
  const xy = (raw) => /^\s*\(?\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*\)?\s*$/.exec(raw || "");

  if (type === "type") {
    const t = await askOne(T + "Gõ chữ", "Nội dung cần gõ", c.text ?? "", "Nội dung…");
    if (t == null) return null; s.text = t;
  } else if (type === "tap_text") {
    const t = await askOne(T + "Bấm vào chữ", "Chữ hiển thị trên màn (OCR)", c.text ?? "", "VD: Đăng nhập");
    if (!t) return null; s.text = t;
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
    const t = await askOne(T + "Mở app", "Tên app cần mở", c.app ?? "", "VD: efootball");
    if (!t) return null; s.app = t.trim();
  } else if (type === "wait") {
    const t = await askOne(T + "Chờ", "Số giây chờ", String(c.seconds ?? "1.5"));
    if (!t) return null; s.seconds = parseFloat(t) || 0;
  } else if (type === "wait_text") {
    const r = await askForm(T + "Chờ thấy chữ", "Chờ tới khi OCR thấy chữ.", [
      { key: "text", label: "Chữ cần chờ", value: c.text ?? "", placeholder: "VD: Trang chủ" },
      { key: "timeout", label: "Chờ tối đa (giây)", value: String(c.timeout ?? 15) },
    ]);
    if (!r || !r.text) return null; s.text = r.text; s.timeout = parseFloat(r.timeout) || 15;
  } else if (type === "assert_text") {
    const t = await askOne(T + "Kiểm có chữ", "Xác minh màn hình có chữ", c.text ?? "", "VD: Thành công");
    if (!t) return null; s.text = t;
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
      { key: "seconds", label: "Giữ bao lâu (giây)", value: String(c.seconds ?? 1.2) },
    ]);
    if (!r) return null;
    s.seconds = Math.min(10, Math.max(0.2, parseFloat(r.seconds) || 1));
    if (byText) { if (!r.text) return null; s.text = r.text; }
    else {
      const m = xy(r.xy);
      if (!m) { toast("Toạ độ phải có dạng x,y", "warn"); return null; }
      s.x = Number(m[1]); s.y = Number(m[2]);
    }
  } else return null;                                    // loại bước lạ: không có gì để hỏi
  return s;
}

async function addStepPrompt(type, at) {
  const s = await stepPrompt(type, null);
  if (s) addStep(s, at);
}

/* =========================================================
   NHÓM — tải / chọn / lưu / xoá / chạy + thành viên + trạng thái
   ========================================================= */
async function loadGroups(selectId, force) {
  try { GROUPS = await API().groups_list() || []; }
  catch (e) { toast("Lỗi tải nhóm: " + e + " — giữ nguyên dữ liệu đang hiện", "bad"); return; }   // KHÔNG coi như «không còn nhóm nào»: đang sửa dở thì giữ nguyên
  $("#nav-flow-count").textContent = GROUPS.length;
  renderGroupCards();
  if (GROUP_PAGE !== "detail") return;
  const cur = selectId || (GROUP && GROUP.id);
  const g = GROUPS.find(x => x.id === cur);
  if (!g) { leaveGroup(); return; }                                  // nhóm đang mở đã bị xoá
  if (force || !GROUP || GROUP.id !== cur || !groupDirty()) selectGroup(cur);
  else { GROUP.devices = (g.devices || []).slice(); renderMembers(); renderGroupAddDev(); }   // đang sửa dở: giữ bản sửa, chỉ cập nhật danh sách máy
}

/* ---- tab Nhóm: trang 1 = danh sách nhóm (thẻ), trang 2 = quản lý kịch bản + máy của 1 nhóm ---- */
const MODE_LABEL = { loop: "Lặp lại kịch bản", once: "Chạy 1 lần", api: "Nhận đơn (API)" };
function groupStepCount(g) {                             // số bước RIÊNG của nhóm nhận đơn (API), cộng cả 6 giai đoạn
  const st = (g.api && g.api.steps) || {};
  return Object.keys(st).reduce((n, k) => n + (Array.isArray(st[k]) ? st[k].length : 0), 0);
}
function groupScriptLabel(g) {
  if (g.mode === "api") { const n = groupStepCount(g); return n ? `${n} bước riêng` : "dùng bước của gateway"; }
  const k = (g.scripts || []).length;
  return k ? `${k} kịch bản` : "chưa có kịch bản";
}
function renderGroupCards() {
  const box = $("#group-cards");
  if (!box) return;
  $("#group-empty").hidden = GROUPS.length > 0;
  box.innerHTML = GROUPS.map(g => {
    const devs = g.devices || [];
    const mineRun = (n) => { const st = RUN_STATUS[n]; return st && (!st.group_id || st.group_id === g.id) ? st : null; };   // máy đang chạy việc nhóm khác không tính cho nhóm này
    const run = devs.filter(n => { const st = mineRun(n); return st && st.running; }).length;
    const halted = devs.filter(n => { const st = mineRun(n); return st && !st.running && /^DỪNG/.test(st.status || ""); }).length;
    const state = run ? `<span class="pill ok">▶ ${run}/${devs.length} máy đang chạy</span>`
                : halted ? `<span class="pill bad">⚠ ${halted} máy dừng — cần xem</span>`
                : `<span class="pill mut">Nghỉ</span>`;
    const names = devs.slice(0, 4).map(n => { const d = DEVICES.find(x => x.name === n); return `<span class="group-dev">${esc(d ? (d.label || d.name) : n)}</span>`; }).join("")
                + (devs.length > 4 ? `<span class="group-dev">+${devs.length - 4}</span>` : "");
    return `<div class="card group-card" role="button" tabindex="0" data-gid="${esc(g.id)}">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
          <h5 class="mb-0 group-card-name">${esc(g.name)}</h5>${state}
        </div>
        ${g.mode && g.mode !== "once" ? `<div class="text-muted small mb-2">${esc(MODE_LABEL[g.mode] || g.mode)}${g.mode === "loop" ? (Number(g.loops) > 0 ? ` · ${Number(g.loops)} vòng` : " · ∞ vòng") : ""}</div>` : ""}
        <div class="group-meta"><span><i class="ti tabler-device-mobile me-1"></i>${devs.length} máy</span>
          <span><i class="ti tabler-list-details me-1"></i>${esc(groupScriptLabel(g))}</span></div>
        <div class="group-devs">${names || `<span class="text-muted small">Chưa có máy</span>`}</div>
      </div></div>`;
  }).join("");
  $$(".group-card", box).forEach(c => {
    c.onclick = () => openGroup(c.dataset.gid);
    c.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openGroup(c.dataset.gid); } };
  });
}
function setGroupPage(page) {
  GROUP_PAGE = page;
  $("#groups-page").hidden = page !== "list";
  $("#group-detail").hidden = page !== "detail";
}
function setHash(h) {
  if (location.hash === h) return;
  try { history.pushState(null, "", h); } catch (e) { try { location.hash = h; } catch (e2) {} }
}
function openGroup(id, push = true, sub = "") {
  if (!GROUPS.some(g => g.id === id)) { leaveGroup(push); return; }
  GROUP_SUB = "home"; EDIT_SID = null;
  selectGroup(id);
  setGroupPage("detail");
  if (sub && validSub(sub)) openScript(sub, push);
  else if (push) setHash("#flows/" + id);
  else fixHash();
}
function leaveGroup(push = true) {
  GROUP = null; GROUP_SUB = "home"; EDIT_SID = null;
  setGroupPage("list");
  if (push) setHash("#flows"); else fixHash();
  renderGroupCards();
}
// trạng thái có thể sửa của nhóm đang mở (máy trong nhóm lưu ngay khi thêm/bớt nên không tính)
function groupState() {
  if (!GROUP) return "";
  return JSON.stringify([$("#group-name").value.trim(), $("#group-mode").value, parseInt($("#group-loops").value) || 0,
    GROUP.scripts, GROUP.api, parseInt($("#api-login-wait").value) || 45, parseInt($("#api-purchase-wait").value) || 60, $("#api-kb").checked]);
}
function groupDirty() { return !!GROUP && GROUP_SNAP !== "" && groupState() !== GROUP_SNAP; }
function backToList() {
  if (GROUP_PAGE === "detail" && groupDirty() && !confirmBox("Nhóm này có thay đổi CHƯA LƯU (bấm «Lưu kịch bản» để giữ).\n\nBỏ thay đổi và quay về danh sách?")) return false;
  leaveGroup();
  return true;
}
/* ---- kịch bản trong nhóm: danh sách (trang nhóm) + trình sửa ---- */
const newSid = () => Math.random().toString(36).slice(2, 8);
function currentScript() { return GROUP && GROUP.scripts ? (GROUP.scripts.find(x => x.id === EDIT_SID) || null) : null; }
function currentHash() { return "#flows/" + (GROUP ? GROUP.id : "") + (GROUP_SUB === "script" ? "/" + (GROUP.mode === "api" ? "@" + API_PHASE : EDIT_SID) : ""); }
let SCRIPT_SEL = {};                   // máy được tích «chạy trên máy» của kịch bản đang mở (giữ qua các lần vẽ lại / lưu)
let SCRIPT_SEL_FOR = "";               // lựa chọn trên thuộc kịch bản nào ("<nhóm>/<kịch bản>")
function setGroupSub(sub) {
  GROUP_SUB = sub;
  $("#group-home").hidden = sub !== "home";
  $("#script-editor").hidden = sub !== "script";
  $("#group-config").hidden = sub === "script";          // đang sửa kịch bản: ẩn khung cấu hình nhóm cho gọn
  $("#group-head").hidden = sub === "script";            // …và hàng đầu trang của nhóm: trình sửa có hàng riêng «‹ nhóm / tên kịch bản … Lưu»
  closePalette();
  if (sub === "script") {
    $("#ed-group-name").textContent = GROUP.name || "Nhóm";
    const api = GROUP.mode === "api";
    $("#script-name").closest("div").hidden = api;
    $("#script-phase-title").hidden = !api;
    $("#script-phase-title").textContent = "Chế độ nhận đơn (API) — các giai đoạn của một đơn";
    const sc = currentScript();
    if (!api) $("#script-name").value = sc ? sc.name : "";
    $("#script-run-card").hidden = api || !sc;           // nhóm nhận đơn API: chạy ở trang nhóm, không có «cách chạy» theo kịch bản
    if (!api && sc) {
      $("#script-mode").value = sc.mode; $("#script-loops").value = sc.loops;
      $("#script-loops-wrap").hidden = sc.mode !== "loop";
      const key = GROUP.id + "/" + sc.id;
      if (SCRIPT_SEL_FOR !== key) { SCRIPT_SEL = {}; SCRIPT_SEL_FOR = key; }     // kịch bản khác → mặc định tích hết; cùng kịch bản → giữ lựa chọn của người dùng
      renderScriptMachines();
    }
    bindSteps();
  }
  updateDirty();
}
// «Chạy trên máy»: mỗi máy của nhóm một ô tích; máy đang chạy việc gì thì ghi rõ «nhóm · kịch bản» và không tích được
function renderScriptMachines() {
  const box = $("#script-machines");
  const sc = currentScript();
  if (!box || !GROUP || !sc || GROUP_SUB !== "script") return;
  if (!GROUP.devices.length) { box.innerHTML = `<div class="text-muted small">Nhóm chưa có máy — thêm máy ở trang nhóm.</div>`; return; }
  box.innerHTML = GROUP.devices.map(n => {
    const d = DEVICES.find(x => x.name === n);
    const st = RUN_STATUS[n];
    const running = !!(st && st.running);
    const held = isHeld(st);
    const parked = !!(st && st.parked);
    const busy = running || held || parked;              // máy đang dừng để xử lý tay cũng không tích được — bấm Tiếp tục trên máy đó trước
    const mine = running && st.group_id === GROUP.id && st.script_id === sc.id;
    const note = running ? (mine ? `<span class="pill ok">▶ đang chạy kịch bản này</span>` : `<span class="pill warn">đang chạy ${esc(whatRuns(st))}</span>`) : "";
    return `<div class="script-machine-row"><label class="script-machine ${busy ? "busy" : ""}"><input type="checkbox" data-m="${esc(n)}" ${busy ? "disabled" : (SCRIPT_SEL[n] !== false ? "checked" : "")}> ${esc(d ? (d.label || d.name) : n)} ${note}</label>
      <span class="script-machine-acts">${runControlsHtml(n, st)}</span></div>`;
  }).join("");
  $$("input[data-m]", box).forEach(cb => cb.onchange = () => { SCRIPT_SEL[cb.dataset.m] = cb.checked; });
  bindRunControls(box);
}
async function runScript(btn) {
  const sc = currentScript();
  if (!GROUP || !sc) return;
  const names = GROUP.devices.filter(n => SCRIPT_SEL[n] !== false && !(RUN_STATUS[n] && (RUN_STATUS[n].running || RUN_STATUS[n].parked)) && !isHeld(RUN_STATUS[n]));
  if (!GROUP.devices.length) { toast("Nhóm chưa có máy nào", "warn"); return; }
  if (!names.length) { toast("Chưa chọn máy rảnh nào để chạy", "warn"); return; }
  if (!sc.steps.length) { toast("Kịch bản chưa có bước nào", "warn"); return; }
  busy(btn, true);
  const saved = await saveGroupSilent();                 // chạy đúng bản đang hiện trên màn hình
  if (!saved) { toast("Lỗi lưu nhóm — chưa chạy", "bad"); busy(btn, false); return; }
  try {
    const r = await API().group_run(GROUP.id, names, sc.id);
    if (r && r.ok) {
      log(`▶ Chạy «${GROUP.name} · ${sc.name}» (${runLabel(sc)}): ${(r.started || []).join(", ") || "(không máy nào)"}`);
      const busyN = Object.keys(r.busy || {}), heldN = Object.keys(r.held || {});
      if (busyN.length) log(`⚠ Bỏ qua máy đang bận: ${busyN.map(n => `${n} (${r.busy[n]})`).join(", ")}`, "bad");
      if (heldN.length) log(`⚠ Bỏ qua máy đang DỪNG CHỜ KIỂM TRA: ${heldN.map(n => `${n} (${r.held[n]})`).join(", ")}`, "bad");
      if (busyN.length || heldN.length) toast(`Bỏ qua ${busyN.length + heldN.length} máy (đang bận / đang chờ kiểm tra)`, "warn");
      else toast(`Đã chạy trên ${(r.started || []).length} máy`, "ok");
    } else toast((r && r.error) || "Lỗi không rõ", "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  pollStatus();
}
async function stopScript(btn) {
  const sc = currentScript();
  if (!GROUP || !sc) return;
  busy(btn, true);
  try {
    await API().group_stop(GROUP.id, false, sc.id);      // chỉ dừng máy đang chạy ĐÚNG kịch bản này của nhóm này
    log(`■ Dừng «${GROUP.name} · ${sc.name}»`);
    toast("Đã yêu cầu dừng kịch bản này", "");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  pollStatus();
}
// «@giai đoạn» (chế độ API) hoặc id kịch bản (loop/once) có thật trong nhóm đang mở không
function validSub(sub) {
  if (!GROUP || !sub) return false;
  return sub[0] === "@" ? GROUP.mode === "api" && API_PHASES.some(p => p[0] === sub.slice(1))
                        : GROUP.mode !== "api" && GROUP.scripts.some(x => x.id === sub);
}
// địa chỉ trên thanh trình duyệt sai (nhóm / kịch bản không có) → sửa lại cho khớp trang đang hiện, không thêm vào lịch sử
function fixHash() {
  const h = GROUP && GROUP_PAGE === "detail" ? currentHash() : "#flows";
  if (location.hash !== h) { try { history.replaceState(null, "", h); } catch (e) {} }
}
function openScript(id, push = true) {
  if (!validSub(id)) { fixHash(); return; }
  if (id[0] === "@") { API_PHASE = id.slice(1); EDIT_SID = null; }
  else EDIT_SID = id;
  setGroupSub("script");
  if (push) setHash(currentHash());
}
function closeScript(push = true) {
  EDIT_SID = null;
  setGroupSub("home");
  renderScripts(); renderMembers();                      // vẽ lại ngay (trạng thái chạy có thể đã đổi lúc đang sửa)
  if (push) setHash("#flows/" + GROUP.id);
}
function renderScripts() {
  const box = $("#script-list");
  if (!box || !GROUP) return;
  const api = GROUP.mode === "api";
  $("#btn-script-new").hidden = api;
  const gwSteps = (GW_POOL && GW_POOL.steps) || {};
  if (api) {
    $("#script-count").textContent = "(6 giai đoạn)";
    $("#script-hint").textContent = "Chế độ nhận đơn: mỗi giai đoạn của một đơn nạp là một kịch bản. Giai đoạn để trống thì dùng bước cấu hình trên gateway.";
    box.innerHTML = API_PHASES.map(([k, label]) => {
      const mine = GROUP.api.steps[k].length, theirs = (gwSteps[k] || []).length;
      const tag = mine ? `<span class="pill ok">${mine} bước riêng</span>` : theirs ? `<span class="pill mut">dùng ${theirs} bước của gateway</span>` : `<span class="pill warn">chưa có bước</span>`;
      return `<div class="mem-row script-row" role="button" tabindex="0" data-sopen="@${k}"><div class="mem-info"><div class="mem-name">${esc(label)}</div></div>
        <div class="mem-act">${tag}<button class="btn btn-sm btn-label-secondary" data-sopen="@${k}">Sửa</button></div></div>`;
    }).join("");
  } else {
    const n = GROUP.scripts.length;
    $("#script-count").textContent = n ? `(${n})` : "";
    $("#script-hint").textContent = "Bấm vào một kịch bản để sửa các bước, chọn cách chạy và máy chạy.";
    box.innerHTML = n ? GROUP.scripts.map(sc => {
      const on = Object.keys(RUN_STATUS).filter(m => { const st = RUN_STATUS[m]; return st && st.running && st.group_id === GROUP.id && st.script_id === sc.id; }).length;
      return `<div class="mem-row script-row" role="button" tabindex="0" data-sopen="${esc(sc.id)}">
        <div class="mem-info"><div class="mem-name">${esc(sc.name)} ${on ? `<span class="pill ok">▶ đang chạy trên ${on} máy</span>` : ""}</div>
          <div class="mem-sub">${sc.steps.length ? sc.steps.length + " bước" : "chưa có bước"} · ${esc(runLabel(sc))}</div></div>
        <div class="mem-act">
          <button class="btn btn-sm btn-label-secondary" data-sopen="${esc(sc.id)}">Sửa</button>
          <button class="btn btn-sm btn-label-secondary" data-sdel="${esc(sc.id)}" title="Xoá kịch bản">✕</button>
        </div></div>`;
    }).join("") : `<div class="text-muted small py-2">Chưa có kịch bản. Bấm <b>«Thêm kịch bản»</b> để bắt đầu.</div>`;
  }
  const stop = (e) => e.stopPropagation();
  $$("[data-sopen]", box).forEach(b => b.onclick = (e) => { e.stopPropagation(); openScript(b.dataset.sopen); });
  $$(".script-row", box).forEach(r => r.onkeydown = (e) => { if (e.target === r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openScript(r.dataset.sopen); } });
  $$("[data-sdel]", box).forEach(b => b.onclick = (e) => { stop(e); delScript(b.dataset.sdel); });
}
async function addScript() {
  if (!GROUP || GROUP.mode === "api") return;
  const name = await askOne("Thêm kịch bản", "Tên kịch bản", "", "VD: Đăng nhập + mua gói");
  if (name == null) return;
  const sc = { id: newSid(), name: name.trim() || "Kịch bản " + (GROUP.scripts.length + 1), steps: [], mode: "once", loops: 1 };
  GROUP.scripts.push(sc);
  const saved = await saveGroupSilent();                     // lưu ngay: nhóm có kịch bản rồi mới sửa / chạy được
  if (!saved) { toast("Lỗi lưu nhóm", "bad"); return; }
  toast("Đã thêm kịch bản: " + sc.name, "ok");
  await loadGroups(GROUP.id, true);
  openScript(sc.id);                                         // vào luôn trình sửa kịch bản vừa tạo
}
async function delScript(id) {
  const sc = GROUP && GROUP.scripts.find(x => x.id === id);
  if (!sc) return;
  const on = Object.keys(RUN_STATUS).filter(m => { const st = RUN_STATUS[m]; return st && st.running && st.group_id === GROUP.id && st.script_id === id; });
  if (on.length) { toast(`Kịch bản đang chạy trên ${on.length} máy — dừng trước rồi mới xoá`, "warn"); return; }
  if (!confirmBox(`Xoá kịch bản “${sc.name}”${sc.steps.length ? ` (${sc.steps.length} bước)` : ""}?\n\nXoá ngay và không lấy lại được.`)) return;
  const backup = GROUP.scripts.slice();
  GROUP.scripts = GROUP.scripts.filter(x => x.id !== id);
  const saved = await saveGroupSilent();                     // lưu ngay (như «Thêm kịch bản»): trên màn hình sao thì trong tệp vậy
  if (!saved) { GROUP.scripts = backup; renderScripts(); toast("Lỗi lưu nhóm — chưa xoá", "bad"); return; }
  toast("Đã xoá kịch bản: " + sc.name, "ok");
  await loadGroups(GROUP.id, true);
}

// địa chỉ trang: #flows (danh sách) / #flows/<id nhóm> — tải lại trang hoặc bấm Back vẫn đúng chỗ
async function routeFromHash() {
  const m = /^#flows(?:\/([\w-]+)(?:\/(@?[\w-]+))?)?$/.exec(location.hash);
  if (!m) return;
  const id = m[1] || "", sub = m[2] || "";
  const flowsOn = ($(".view.active") || {}).id === "view-flows";
  if (!flowsOn) showView("flows");
  if (!GROUPS.length) { try { GROUPS = await API().groups_list() || []; } catch (e) {} renderGroupCards(); }
  if (id) {
    if (GROUP_PAGE === "detail" && GROUP && GROUP.id === id) {          // cùng nhóm: chỉ đổi giữa trang nhóm ↔ trình sửa kịch bản
      if (sub) openScript(sub, false); else if (GROUP_SUB === "script") closeScript(false);
      return;
    }
    if (GROUP_PAGE === "detail" && groupDirty() && !confirmBox("Nhóm đang mở có thay đổi CHƯA LƯU.\n\nBỏ thay đổi và chuyển nhóm?")) { setHash(currentHash()); return; }
    openGroup(id, false, sub);
  } else if (GROUP_PAGE === "detail") {
    if (groupDirty() && !confirmBox("Nhóm đang mở có thay đổi CHƯA LƯU.\n\nBỏ thay đổi và quay về danh sách?")) { setHash(currentHash()); return; }
    leaveGroup(false);
  }
}

/* ---- chế độ API: các giai đoạn của 1 đơn nạp (mỗi giai đoạn 1 danh sách bước) ---- */
const API_PHASES = [
  ["login",    "Đăng nhập",     "Mở game và đăng nhập tài khoản của khách. Biến: {{username}} {{password}} (mọi trường đăng nhập của pool)."],
  ["otp",      "Nhập OTP",      "Chạy khi game đòi OTP và khách đã gửi mã. Biến: {{otp}}. Để trống = gõ mã rồi Enter."],
  ["nav",      "Vào DS gói",    "Từ màn hình sau đăng nhập đi tới danh sách gói nạp."],
  ["purchase", "Mua 1 gói",     "Mua MỘT gói, lặp theo số lượng. Dừng ở màn hình báo kết quả (tool chụp bill ở đó). Biến: {{package.ocr_text}} {{package.price_text}} {{package.name}}."],
  ["after",    "Sau khi mua",   "Sau mỗi lần mua được: đóng thông báo, quay lại danh sách gói để mua tiếp."],
  ["finish",   "Kết thúc đơn",  "Sau khi báo kết quả: đăng xuất, về màn hình chính — để máy sẵn sàng cho đơn sau."],
];
let API_PHASE = "login";               // giai đoạn đang sửa trong trình dựng
let GW = { url: "", has_key: false, key_hint: "", ok: null, error: "", pools: [] };
let GW_POOL = null;                    // cấu hình pool đang chọn (để biết gateway có sẵn bước nào)
let TEST_VARS = {};                    // giá trị thử cho {{biến}} (chỉ giữ trong phiên, không lưu)

function normApi(a) {
  a = a || {};
  const steps = {};
  API_PHASES.forEach(([k]) => { steps[k] = Array.isArray((a.steps || {})[k]) ? a.steps[k] : []; });
  return { pool: a.pool || "", steps, login_wait: a.login_wait || 45, purchase_wait: a.purchase_wait || 60,
           check_keyboard: a.check_keyboard !== false };
}

// FLOW.steps luôn TRỎ vào đúng danh sách đang sửa (kịch bản thường, hoặc 1 giai đoạn của chế độ API)
function bindSteps() {
  if (!GROUP) return;
  const sc = currentScript();
  FLOW.steps = GROUP.mode === "api" ? GROUP.api.steps[API_PHASE] : (sc ? sc.steps : []);
  FLOW.name = GROUP.mode === "api" ? GROUP.name : (sc ? sc.name : GROUP.name);
  renderSteps();
}

function selectGroup(id) {
  const g = GROUPS.find(x => x.id === id);
  if (!g) { GROUP = null; GROUP_SNAP = ""; return; }
  const sc = (Array.isArray(g.scripts) ? g.scripts : ((g.steps || []).length ? [{ id: "k1", name: "Kịch bản 1", steps: g.steps }] : []))
    .map(x => ({ id: x.id, name: x.name, steps: x.steps || [], mode: x.mode === "loop" ? "loop" : "once", loops: Number.isFinite(+x.loops) ? +x.loops : (x.mode === "loop" ? 0 : 1) }));
  GROUP = JSON.parse(JSON.stringify({ id: g.id, name: g.name, scripts: sc,
    devices: g.devices || [], mode: g.mode || "once", loops: g.loops || 0, api: normApi(g.api) }));
  if (GROUP_SUB === "script" && GROUP.mode !== "api" && !currentScript()) { GROUP_SUB = "home"; EDIT_SID = null; }   // kịch bản đang sửa đã bị xoá
  FLOW = { id: GROUP.id, name: GROUP.name, steps: [] };            // tái dùng renderSteps/addStep (bindSteps trỏ vào đúng danh sách bước)
  $("#group-name").value = GROUP.name || "";
  $("#group-mode").value = GROUP.mode;
  $("#group-loops").value = GROUP.loops;
  $("#api-login-wait").value = GROUP.api.login_wait;
  $("#api-purchase-wait").value = GROUP.api.purchase_wait;
  $("#api-kb").checked = GROUP.api.check_keyboard;
  if (!GW_POOL || GW_POOL.code !== GROUP.api.pool) GW_POOL = null;
  bindSteps(); renderMembers(); renderGroupAddDev(); renderDevicePicker();
  if (GROUP.mode === "api") { renderPoolSelect(); loadGwPool(); }
  $("#group-title").textContent = GROUP.name || "Nhóm";
  $("#group-sub").textContent = `${GROUP.mode !== "once" ? (MODE_LABEL[GROUP.mode] || GROUP.mode) + " · " : ""}${GROUP.devices.length} máy`;
  renderScripts(); setGroupSub(GROUP_SUB);
  GROUP_SNAP = groupState();
}

/* ---- giao diện riêng của chế độ API ---- */
function renderApiUi() {
  if (!GROUP) return;
  const api = GROUP.mode === "api";
  $("#group-loops-wrap").style.display = GROUP.mode === "loop" ? "" : "none";
  $("#group-pool-wrap").hidden = !api;
  $("#group-api-row").hidden = !api;
  $("#btn-group-run").parentElement.hidden = !api;     // «Chạy nhóm» / «Dừng nhóm»: chỉ nhóm nhận đơn API (cũ); nhóm thường thử bằng «Chạy thử» trong trình sửa kịch bản
  $("#api-phase-box").hidden = !api;
  $("#btn-save").innerHTML = `<i class="ti tabler-device-floppy me-1"></i>${api ? "Lưu nhóm" : "Lưu kịch bản"}`;
  if (!api) {
    $("#steps-empty").textContent = "Chưa có bước nào. Chọn một hành động bên dưới để bắt đầu.";
    return;
  }
  const gwSteps = (GW_POOL && GW_POOL.steps) || {};
  $("#api-phases").innerHTML = API_PHASES.map(([k, label]) => {
    const mine = GROUP.api.steps[k].length, theirs = (gwSteps[k] || []).length;
    const tag = mine ? `<span class="seg-c own" title="Nhóm có ${mine} bước riêng">${mine}</span>`
              : theirs ? `<span class="seg-c" title="Dùng ${theirs} bước của gateway">gw ${theirs}</span>`
              : `<span class="seg-c none" title="Chưa có bước nào">0</span>`;
    return `<button class="seg-btn ${k === API_PHASE ? "active" : ""}" data-phase="${k}">${esc(label)} ${tag}</button>`;
  }).join("");
  $$("#api-phases .seg-btn").forEach(b => b.onclick = () => { API_PHASE = b.dataset.phase; bindSteps(); });

  // Pool/nhóm còn thiếu thứ bắt buộc → máy sẽ KHÔNG nhận đơn: nói rõ ngay ở đây thay vì để người vận hành tự mò.
  const warn = $("#api-warn");
  if (warn) {
    const miss = [];
    if (GW_POOL) {
      (GW_POOL.missing_rules || []).forEach(r => miss.push(`pool chưa có luật <b>«${esc(r)}»</b> (thêm ở trang quản trị gateway → Pool → mục 3)`));
      (GW_POOL.required_phases || []).forEach(k => {
        if (!GROUP.api.steps[k].length && !(gwSteps[k] || []).length)
          miss.push(`chưa có bước <b>«${esc((API_PHASES.find(p => p[0] === k) || [k, k])[1])}»</b> (thêm ở đây hoặc trên gateway)`);
      });
    }
    warn.hidden = !miss.length;
    warn.innerHTML = miss.length
      ? `<i class="ti tabler-alert-triangle me-1"></i><b>Máy sẽ KHÔNG nhận đơn</b> cho tới khi bổ sung: ${miss.join("; ")}.` : "";
  }

  const [, label, help] = API_PHASES.find(p => p[0] === API_PHASE);
  const mine = GROUP.api.steps[API_PHASE].length, theirs = (gwSteps[API_PHASE] || []).length;
  const src = mine ? `Nhóm đang dùng <b>${mine} bước RIÊNG</b> cho giai đoạn này (ghi đè gateway). Xoá hết để quay về dùng bước của gateway.`
            : theirs ? `Đang dùng <b>${theirs} bước cấu hình trên gateway</b>. Chỉ thêm bước ở đây nếu loại máy này cần cách bấm khác (vd toạ độ khác).`
            : (API_PHASE === "otp" ? "Chưa cấu hình ở đâu → tool sẽ <b>gõ mã OTP rồi nhấn Enter</b>."
               : ["login", "purchase", "finish"].includes(API_PHASE) ? "<b class=\"text-danger\">Chưa có bước nào cho giai đoạn BẮT BUỘC này</b> — phải cấu hình ở đây hoặc trên gateway thì máy mới nhận đơn."
               : "Chưa có bước nào cho giai đoạn này (bỏ qua giai đoạn).");
  $("#api-phase-hint").innerHTML = `<b>${esc(label)}:</b> ${esc(help)}<br>${src}`;
  $("#steps-empty").textContent = mine ? "" : (theirs ? "Nhóm chưa có bước riêng — đang dùng bước của gateway." : "Chưa có bước nào.");
}

function setGwState() {
  const dot = $("#gw-dot"), el = $("#gw-state");
  if (dot) dot.className = "gw-dot " + (GW.ok === true ? "ok" : GW.ok === false ? "bad" : "");
  if (!el) return;
  if (!GW.url || !GW.has_key) el.innerHTML = `Chưa cấu hình gateway — bấm nút <b>Gateway</b> ở trên để nhập địa chỉ + khoá Tool.`;
  else if (GW.ok === false) el.innerHTML = `<span class="text-danger">Gateway lỗi:</span> ${esc(GW.error)} <span class="text-muted">(${esc(GW.url)})</span>`;
  else if (GW.ok === true) el.innerHTML = `Đã nối gateway <b>${esc(GW.url)}</b> — máy trống sẽ tự xin đơn của pool đã chọn.`;
  else el.textContent = "Đang kiểm tra gateway…";
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

function renderPoolSelect() {
  const sel = $("#group-pool");
  if (!sel || !GROUP) return;
  const cur = GROUP.api.pool;
  const opts = [`<option value="">— chọn pool —</option>`]
    .concat(GW.pools.map(p => `<option value="${esc(p.code)}">${esc(p.name || p.code)}${p.active === false ? " (tạm dừng)" : ""}</option>`));
  if (cur && !GW.pools.some(p => p.code === cur)) opts.push(`<option value="${esc(cur)}">${esc(cur)} (không thấy trên gateway)</option>`);
  sel.innerHTML = opts.join("");
  sel.value = cur;
}

async function loadGateway() {
  try { Object.assign(GW, await API().gateway_get()); } catch (e) {}
  if (!GW.url || !GW.has_key) { GW.ok = null; GW.pools = []; setGwState(); renderPoolSelect(); return; }
  GW.ok = null; setGwState();
  try {
    const r = await API().gateway_pools();
    GW.ok = !!(r && r.ok); GW.error = (r && r.error) || ""; GW.pools = (r && r.pools) || [];
  } catch (e) { GW.ok = false; GW.error = String(e); GW.pools = []; }
  setGwState(); renderPoolSelect();
  if (GROUP && GROUP.mode === "api") loadGwPool();
}

async function loadGwPool() {
  const code = GROUP && GROUP.api.pool;
  if (!code || GW.ok !== true) { GW_POOL = null; renderApiUi(); return; }
  if (GW_POOL && GW_POOL.code === code) { renderApiUi(); return; }
  try {
    const r = await API().gateway_pool(code);
    GW_POOL = (r && r.ok) ? r : null;
    if (r && !r.ok) toast("Không tải được pool: " + r.error, "warn");
  } catch (e) { GW_POOL = null; }
  renderApiUi();
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

async function importGwSteps(btn) {
  if (!GROUP || GROUP.mode !== "api") return;
  const code = $("#group-pool").value;
  if (!code) { toast("Chọn pool trước", "warn"); return; }
  busy(btn, true);
  try {
    const r = await API().gateway_pool(code);
    if (!r || !r.ok) { toast("Không tải được pool: " + ((r && r.error) || "?"), "bad"); busy(btn, false); return; }
    const total = API_PHASES.reduce((n, [k]) => n + (r.steps[k] || []).length, 0);
    const have = API_PHASES.reduce((n, [k]) => n + GROUP.api.steps[k].length, 0);
    if (!total) { toast("Pool này chưa cấu hình bước nào trên gateway", "warn"); busy(btn, false); return; }
    if (!have || confirmBox(`Chép ${total} bước của pool «${r.name || code}» vào nhóm?\nCác bước RIÊNG hiện có của nhóm (${have} bước) sẽ bị thay.`)) {
      GROUP.api.pool = code;
      API_PHASES.forEach(([k]) => { GROUP.api.steps[k] = JSON.parse(JSON.stringify(r.steps[k] || [])); });
      GW_POOL = r;
      bindSteps();
      toast(`Đã chép ${total} bước — sửa cho hợp loại máy rồi bấm «Lưu nhóm»`, "ok");
    }
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}

// Chạy thử các bước ở chế độ API: hỏi giá trị cho {{biến}} rồi chạy bằng đúng bộ chạy lúc nạp thật.
async function runApiSteps(steps) {
  const names = [...new Set((JSON.stringify(steps).match(/\{\{\s*[A-Za-z0-9_.]+\s*\}\}/g) || []).map(s => s.replace(/[{}\s]/g, "")))];
  let vars = {};
  if (names.length) {
    const r = await askForm("Giá trị thử cho các biến", "Chỉ dùng cho lần chạy thử này, không lưu lại.",
      names.map(n => ({ key: n, label: `{{${n}}}`, value: TEST_VARS[n] || "",
                        type: /pass|otp|pin|secret|token|cookie/i.test(n) ? "password" : "text" })));
    if (!r) return null;
    vars = r; Object.assign(TEST_VARS, r);
  }
  const res = await API().test_api_steps(SEL, steps, vars);
  if (!res || !res.ok) { log("✗ " + ((res && res.error) || "lỗi"), "bad"); toast((res && res.error) || "Chạy thử lỗi", "bad"); return null; }
  return res.results;
}

async function newGroup() {
  const name = await askOne("Tạo nhóm mới", "Tên nhóm", "", "VD: iPhone 8 · iOS 16.7");
  if (name == null) return;
  try {
    const g = await API().group_save({ name: name.trim() || "Nhóm mới", mode: "once", loops: 1, devices: [] });
    toast("Đã tạo nhóm: " + g.name, "ok");
    await loadGroups();
    openGroup(g.id);                                 // vào luôn trang quản lý nhóm vừa tạo
  } catch (e) { toast("Lỗi tạo nhóm: " + e, "bad"); }
}

async function saveGroupSilent() {
  if (!GROUP) return;
  GROUP.name = $("#group-name").value.trim() || GROUP.name;
  GROUP.mode = $("#group-mode").value;
  GROUP.loops = parseInt($("#group-loops").value) || 0;
  // các bước đã nằm sẵn trong GROUP.scripts[].steps / GROUP.api.steps (FLOW.steps chỉ là tham chiếu tới chúng); `steps` của nhóm do backend suy ra từ kịch bản đang dùng
  GROUP.api.pool = $("#group-pool").value || GROUP.api.pool || "";
  GROUP.api.login_wait = parseInt($("#api-login-wait").value) || 45;
  GROUP.api.purchase_wait = parseInt($("#api-purchase-wait").value) || 60;
  GROUP.api.check_keyboard = $("#api-kb").checked;
  try {
    const saved = await API().group_save(GROUP);
    if (saved) GROUP_SNAP = groupState();           // đã lưu → không còn «thay đổi chưa lưu»
    return saved;
  } catch (e) {}
}

async function saveGroup(btn) {
  if (!GROUP) return;
  busy(btn, true);
  const saved = await saveGroupSilent();
  if (saved) { toast("Đã lưu nhóm: " + saved.name, "ok"); await loadGroups(saved.id, true); }
  else toast("Lỗi lưu nhóm", "bad");
  busy(btn, false);
  updateDirty();
}

async function delGroup() {
  if (!GROUP) return;
  if (!confirmBox(`Xoá nhóm “${GROUP.name}”?\n(Chỉ bỏ nhóm — các máy vẫn giữ nguyên, kể cả ở nhóm khác; không ảnh hưởng iPhone/board.)`)) return;
  try {
    const r = await API().group_delete(GROUP.id);
    if (r && r.ok === false) { toast(r.error || "Không xoá được nhóm", "warn"); return; }
    toast("Đã xoá nhóm", "ok");
    leaveGroup();
    await loadGroups();
    await loadDevices();
  } catch (e) { toast("Lỗi xoá: " + e, "bad"); }
}

// «Chạy 1 lần» / «Lặp lại ∞» / «Lặp lại 5 vòng»
function runLabel(sc) { return sc.mode === "loop" ? (sc.loops > 0 ? `lặp lại ${sc.loops} vòng` : "lặp lại ∞") : "chạy 1 lần"; }
function whatRuns(st) { return [st.group_name, st.script_name].filter(Boolean).join(" · "); }

// Bộ nút cho MỘT máy đang chạy — dùng chung ở trang Thiết bị, trang nhóm và trong kịch bản:
//   ⏸ Tạm dừng  = dừng để xử lý tay (việc đang chạy vẫn giữ nguyên, máy vẫn giữ chỗ);  ▶ Tiếp tục = chạy tiếp;  Dừng = kết thúc hẳn.
// Trạng thái chạy của một máy trong danh sách thiết bị (đủ cho bộ nút dùng chung)
function devRunState(d) {
  return { running: !!d.running, hold: d.hold, parked: !!d.parked, paused: d.paused, pause_requested: d.pause_requested, stopping: d.stopping, mode: d.run_mode };
}
// Máy đã dừng giữa đơn của khách và đang GIỮ nguyên màn hình chờ người kiểm tra / đối soát
function isHeld(st) { return !!(st && !st.running && st.hold); }
function runControlsHtml(name, st) {
  // máy đang «dừng để xử lý tay» mà không chạy gì: nhãn + nút Tiếp tục (dùng cho cả máy đang nghỉ lẫn máy đang giữ chờ kiểm tra)
  const parkedHtml = `<span class="pill warn" title="Bạn đã dừng máy này để xử lý tay: không kịch bản / đơn nào chạy lên máy cho tới khi bấm Tiếp tục">⏸ đang dừng · xử lý tay</span>
              <button class="btn btn-sm btn-success" data-mresume="${esc(name)}" title="Cho máy dùng lại bình thường">▶ Tiếp tục</button>`;
  if (isHeld(st)) {
    // Máy đang giữ chờ kiểm tra CÓ THỂ cũng đang «dừng để xử lý tay» (bấm Tạm dừng giữa đơn rồi đơn kết thúc ở «cần đối soát»):
    // phải hiện cả «Tiếp tục», không thì «Chạy lại» của nhóm nhận đơn bị từ chối mà không có nút nào để gỡ.
    return `<span class="pill bad" title="${esc(st.hold)}">⚠ dừng chờ kiểm tra</span>
            <button class="btn btn-sm btn-label-danger" data-mack="${esc(name)}" title="Xác nhận bạn đã kiểm tra / đối soát xong máy này — sau đó máy mới chạy việc khác được">Đã kiểm tra xong</button>`
         + (st.parked ? parkedHtml : "");
  }
  if (!st || !st.running) {                             // máy đang NGHỈ: vẫn dừng / cho chạy lại được (để xử lý tay)
    if (st && st.parked) return parkedHtml;
    return `<button class="btn btn-sm btn-label-warning" data-mpause="${esc(name)}" title="Dừng máy này để xử lý tay: không kịch bản / đơn nào chạy lên máy cho tới khi bấm Tiếp tục">⏸ Dừng máy</button>`;
  }
  const n = esc(name), api = st.mode === "api";
  let h = "";
  if (st.paused) {
    h += `<span class="pill warn" title="Máy đang đứng yên chờ bạn xử lý tay">⏸ đang tạm dừng</span>
          <button class="btn btn-sm btn-success" data-mresume="${n}" title="Chạy tiếp từ chỗ đang dừng">▶ Tiếp tục</button>`;
  } else if (st.pause_requested) {
    h += `<span class="pill warn" title="${api ? "Làm nốt đơn đang dở rồi tạm dừng (không nhận đơn mới)" : "Làm nốt bước đang dở rồi tạm dừng"}">⏸ sắp tạm dừng…</span>
          <button class="btn btn-sm btn-label-success" data-mresume="${n}" title="Bỏ yêu cầu tạm dừng">▶ Tiếp tục</button>`;
  } else if (!st.stopping) {
    h += `<button class="btn btn-sm btn-label-warning" data-mpause="${n}" title="${api ? "Không nhận đơn mới (đơn đang làm vẫn làm nốt) rồi đứng chờ — để xử lý tay" : "Dừng trước bước kế tiếp để xử lý tay — bấm Tiếp tục để chạy tiếp"}">⏸ Tạm dừng</button>`;
  }
  if (st.stopping && api) {
    h += `<span class="pill warn" title="Không nhận đơn mới; làm nốt đơn đang dở rồi dừng">đang dừng…</span>
          <button class="btn btn-sm btn-danger" data-mforce="${n}" title="Bỏ dở đơn đang làm ngay lập tức">Dừng ngay</button>`;
  } else {
    h += `<button class="btn btn-sm btn-label-danger" data-mstop="${n}" title="${api ? "Không nhận đơn mới; đơn đang làm vẫn làm cho xong rồi kết thúc" : "Kết thúc việc đang chạy trên máy này"}">Dừng</button>`;
  }
  return h;
}
function bindRunControls(root) {
  $$("[data-mpause]", root).forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); pauseMachine(b.dataset.mpause); });
  $$("[data-mresume]", root).forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); resumeMachine(b.dataset.mresume); });
  $$("[data-mstop]", root).forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); stopMachine(b.dataset.mstop); });
  $$("[data-mforce]", root).forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); stopMachine(b.dataset.mforce, true); });
  $$("[data-mack]", root).forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); ackHold(b.dataset.mack); });
}
// «Đã kiểm tra xong»: người vận hành xác nhận đã đối soát máy đang giữ (chế độ web không nhận lời xác nhận này — backend sẽ nói rõ)
async function ackHold(name) {
  const st = RUN_STATUS[name] || {};
  if (!confirmBox(`Xác nhận ĐÃ KIỂM TRA / ĐỐI SOÁT XONG máy ${name}?\n\nLý do máy đang giữ: ${st.hold || "(không rõ)"}\n\nSau khi xác nhận, máy được phép chạy việc khác (màn hình không còn được giữ nguyên).`)) return;
  try {
    const r = await API().machine_ack(name);
    if (r && r.ok) { log(`✓ Đã xác nhận kiểm tra xong máy ${name}`); toast("Đã gỡ trạng thái chờ kiểm tra", "ok"); }
    else toast((r && r.error) || "Không gỡ được", "warn");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}
async function pauseMachine(name) {
  try {
    const r = await API().machine_pause(name);
    if (r && r.ok) {
      log(`⏸ Dừng máy ${name} để xử lý tay`);
      toast(r.running ? "Máy sẽ tạm dừng sau bước đang làm — xử lý tay xong bấm «Tiếp tục»"
          : r.in_use ? "Đã dừng máy — lệnh đang chạy dở trên máy (thử bước / AI) sẽ làm NỐT rồi mới hết; sau đó không gì chạy lên máy cho tới khi bấm «Tiếp tục»"
          : "Đã dừng máy — không gì chạy lên máy này cho tới khi bấm «Tiếp tục»", r.in_use ? "warn" : "ok");
    } else toast((r && r.error) || "Không dừng được máy", "warn");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}
async function resumeMachine(name) {
  try {
    const r = await API().machine_resume(name);
    if (r && r.ok) { log(`▶ Tiếp tục máy ${name}`); toast("Máy dùng lại bình thường", "ok"); }
    else toast((r && r.error) || "Không tiếp tục được", "warn");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}
// DỪNG TẤT CẢ máy đang chạy (nút ở thanh trên cùng)
async function stopAll(btn) {
  let st = {};
  try { st = await API().run_status() || {}; } catch (e) {}
  const on = Object.keys(st).filter(n => st[n] && st[n].running);
  if (!on.length) { toast("Không có máy nào đang chạy", ""); return; }
  if (!confirmBox(`DỪNG TẤT CẢ ${on.length} máy đang chạy?\n\n${on.map(n => "• " + n + (whatRuns(st[n]) ? " — " + whatRuns(st[n]) : "")).join("\n")}\n\nKịch bản: kết thúc ngay sau bước đang làm. Máy nhận đơn: làm nốt đơn đang dở rồi dừng.`)) return;
  busy(btn, true);
  try { const r = await API().stop_all(false); log(`■ Dừng tất cả (${(r && r.stopped) || on.length} máy)`); toast(`Đã yêu cầu dừng ${on.length} máy`, "ok"); }
  catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  pollStatus();
}

function renderMembers() {
  const box = $("#group-members");
  if (!box || !GROUP) { if (box) box.innerHTML = ""; return; }
  $("#group-mem-count").textContent = GROUP.devices.length ? `(${GROUP.devices.length} máy)` : "";
  if (!GROUP.devices.length) {
    box.innerHTML = `<div class="text-muted small py-2">Chưa có máy. Thêm máy ở trên, hoặc gán nhóm từ trang Thiết bị.</div>`;
    return;
  }
  box.innerHTML = "";
  GROUP.devices.forEach(name => {
    const d = DEVICES.find(x => x.name === name);
    const ro = runOf(name, GROUP.id);
    const st = ro.other ? null : RUN_STATUS[name];                      // máy đang chạy việc của nhóm khác → không hiện trạng thái của việc đó ở đây
    const running = !!(st && st.running);
    const halted = !running && st && st.group_id === GROUP.id && /^DỪNG/.test(st.status || "");     // máy tự dừng, cần người xem
    const label = d ? (d.label || d.name) : name;
    const online = d ? d.board_online : false;
    const stAny = RUN_STATUS[name];
    const statusTxt = ro.other ? `đang chạy ${whatRuns(stAny)}` : st ? (running && whatRuns(st) ? `đang chạy ${whatRuns(st)} · ${st.status || ""}` : (st.status || (running ? "đang chạy" : "nghỉ"))) : "nghỉ";
    const dotStyle = running ? "" : halted ? "background:var(--bs-danger)" : online ? "background:var(--bs-warning)" : "background:var(--bs-secondary)";
    const c = (st && st.counts) || {};
    const counts = (c.done || c.failed || c.review)
      ? `<span class="mem-counts" title="Hoàn tất · Thất bại · Chờ đối soát (từ lúc bấm Chạy)">✓${c.done || 0} · ✕${c.failed || 0} · ?${c.review || 0}</span>` : "";
    let acts;
    if (isHeld(stAny) && !(GROUP.mode === "api" && stAny.group_id === GROUP.id)) {   // đang giữ chờ kiểm tra việc của nhóm KHÁC → chỉ xác nhận, không chạy đè
      acts = runControlsHtml(name, stAny);
    } else if (stAny && stAny.running) {                // máy đang chạy (việc của nhóm này hay nhóm khác): Tạm dừng / Tiếp tục / Dừng là của MÁY
      acts = (ro.other ? `<span class="pill warn" title="Một máy chỉ chạy một kịch bản một lúc — đang chạy ${esc(whatRuns(stAny))}">bận ở nhóm khác</span>` : "") + runControlsHtml(name, stAny);
    } else {                                            // máy đang nghỉ (hoặc đang giữ việc của chính nhóm nhận đơn này): «Dừng máy» / «Tiếp tục» luôn có
      acts = (GROUP.mode === "api" ? `<button class="btn btn-sm btn-success" data-mrun="${esc(name)}">${halted ? "Chạy lại" : "Chạy"}</button>` : "")
           + runControlsHtml(name, stAny);
    }
    const row = document.createElement("div");
    row.className = "mem-row" + (halted ? " halted" : "");
    row.innerHTML = `
      <span class="dot ${running ? "on" : ""}" style="${dotStyle}"></span>
      <div class="mem-info">
        <div class="mem-name">${esc(label)} ${counts}</div>
        <div class="mem-sub" title="${esc(statusTxt)}">${esc(statusTxt)}${st && st.last_msg && !halted ? " · " + esc(st.last_msg) : ""}</div>
      </div>
      <div class="mem-act">
        ${acts}
        <button class="btn btn-sm btn-label-secondary" data-mremove="${esc(name)}" title="Bỏ khỏi nhóm">✕</button>
      </div>`;
    box.appendChild(row);
  });
  $$("[data-mrun]", box).forEach(b => b.onclick = () => runMachine(b.dataset.mrun));
  bindRunControls(box);
  $$("[data-mremove]", box).forEach(b => b.onclick = () => removeMember(b.dataset.mremove));
}

// tên các nhóm KHÁC (không phải nhóm đang mở) mà máy cũng ở trong
function otherGroupsOf(name) {
  return GROUPS.filter(g => (!GROUP || g.id !== GROUP.id) && (g.devices || []).includes(name)).map(g => g.name).join(", ");
}
// Máy làm một việc một lúc: trạng thái chạy chỉ tính cho nhóm nào đang chạy nó; nhóm khác chỉ thấy «bận ở nhóm …»
function runOf(name, gid) {
  const st = RUN_STATUS[name];
  if (!st || !st.running) return { st, mine: false, other: null };
  if (st.group_id && st.group_id !== gid) { const g = GROUPS.find(x => x.id === st.group_id); return { st, mine: false, other: g ? g.name : "khác" }; }
  return { st, mine: true, other: null };
}
function renderGroupAddDev() {
  const sel = $("#group-add-dev");
  if (!sel || !GROUP) return;
  const avail = DEVICES.filter(d => !GROUP.devices.includes(d.name));
  sel.innerHTML = `<option value="">+ Thêm máy…</option>` +
    avail.map(d => `<option value="${esc(d.name)}">${esc(d.label || d.name)}${otherGroupsOf(d.name) ? ` — cũng ở: ${esc(otherGroupsOf(d.name))}` : ""}</option>`).join("");
}

async function addMember(name) {
  if (!GROUP || !name) return;
  try { await API().group_add_device(GROUP.id, name); await loadGroups(GROUP.id); await loadDevices(); }
  catch (e) { toast("Lỗi: " + e, "bad"); }
}
async function removeMember(name) {
  try { await API().group_remove_device(GROUP.id, name); await loadGroups(GROUP.id); await loadDevices(); }
  catch (e) { toast("Lỗi: " + e, "bad"); }
}

// Nhóm chạy được chưa (kiểm nhanh phía giao diện; backend kiểm lại đầy đủ, kể cả hỏi gateway)
function groupNotReady() {
  if (GROUP.mode === "api") {
    if (!GW.url || !GW.has_key) return "Chưa cấu hình gateway (bấm nút Gateway)";
    if (!$("#group-pool").value) return "Chưa chọn pool trên gateway";
    return "";
  }
  return "Nhóm chạy theo kịch bản — mở một kịch bản rồi bấm «Chạy»";
}

async function runGroup(btn) {
  if (!GROUP) return;
  if (!GROUP.devices.length) { toast("Nhóm chưa có máy nào", "warn"); return; }
  const why = groupNotReady();
  if (why) { toast(why, "warn"); return; }
  busy(btn, true);
  await saveGroupSilent();
  try {
    const r = await API().group_run(GROUP.id);
    if (r && r.ok) {
      log(`▶ Chạy nhóm “${GROUP.name}”: ${(r.started || []).join(", ") || "(không có máy mới)"}`);
      const busyN = Object.keys(r.busy || {}), heldN = Object.keys(r.held || {});
      if (busyN.length) log(`⚠ Bỏ qua máy đang bận: ${busyN.map(n => `${n} (${r.busy[n]})`).join(", ")}`, "bad");
      if (heldN.length) log(`⚠ Bỏ qua máy đang DỪNG CHỜ KIỂM TRA: ${heldN.map(n => `${n} (${r.held[n]})`).join(", ")}`, "bad");
      if (busyN.length || heldN.length) toast(`Bỏ qua ${busyN.length + heldN.length} máy (đang bận / đang chờ kiểm tra)`, "warn");
      else toast(GROUP.mode === "api" ? "Các máy bắt đầu nhận đơn từ gateway" : "Đã chạy nhóm", "ok");
    } else toast((r && r.error) || "Lỗi không rõ", "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  pollStatus();
}
async function stopGroup(btn) {
  if (!GROUP) return;
  busy(btn, true);
  try {
    await API().group_stop(GROUP.id, false);
    log(`■ Dừng nhóm “${GROUP.name}”`);
    toast(GROUP.mode === "api" ? "Đã ngừng nhận đơn mới — máy đang làm dở sẽ làm nốt rồi dừng" : "Đã dừng nhóm", "");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  pollStatus();
}
async function runMachine(name) {
  if (!GROUP) return;
  const why = groupNotReady();
  if (why) { toast(why, "warn"); return; }
  await saveGroupSilent();
  try {
    const r = await API().machine_run(GROUP.id, name);
    if (r && r.ok) log(`▶ Chạy máy ${name}`);
    else toast((r && r.error) || "Lỗi không rõ", "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}
async function stopMachine(name, force = false) {
  if (force && !confirmBox(`Dừng NGAY máy ${name}?\n\nĐơn đang làm sẽ bị bỏ dở:\n• chưa chạm tới bước mua → báo «thất bại (chưa nạp)»\n• đã chạm bước mua → báo «chờ đối soát» để bạn kiểm tra trong game.`)) return;
  try {
    const r = await API().machine_stop(name, force);
    if (r && r.ok === false) toast(r.error || "Không dừng được", "warn");
    else log(`■ ${force ? "Dừng ngay" : "Dừng"} máy ${name}`);
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}

async function testFlow(btn) {
  if (!SEL) { toast("Chọn máy để thử", "warn"); return; }
  const api = GROUP && GROUP.mode === "api";
  // chế độ API: nhóm chưa có bước riêng cho giai đoạn này thì thử luôn bước của gateway
  let steps = FLOW.steps;
  if (api && !steps.length && GW_POOL) steps = (GW_POOL.steps || {})[API_PHASE] || [];
  if (!steps.length) { toast("Chưa có bước nào để thử", "warn"); return; }
  busy(btn, true);
  STEP_RES = new WeakMap(); renderSteps();                       // lượt thử mới: xoá kết quả cũ trên lộ trình
  const what = api ? `giai đoạn «${API_PHASES.find(p => p[0] === API_PHASE)[1]}»` : "kịch bản";
  log(`▶ Chạy thử ${what} trên ${SEL}`);
  try {
    let results = null;
    if (api) results = await runApiSteps(steps);
    else {
      const r = await API().test_flow(SEL, steps);
      if (!r || !r.ok) { log("✗ " + ((r && r.error) || "lỗi"), "bad"); toast((r && r.error) || "Chạy thử lỗi", "bad"); }
      else results = r.results;
    }
    if (results) {
      let okN = 0;
      results.forEach(x => { if (x.ok) okN++; log(`   [${x.i + 1}] ${api ? "" : x.type + ": "}${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad");
        if (steps[x.i]) STEP_RES.set(steps[x.i], { ok: !!x.ok, msg: x.msg }); });
      renderSteps();
      toast(`${SEL}: ${okN}/${steps.length} bước OK`, okN === steps.length ? "ok" : "warn");
      setTimeout(() => shot(null), 600);
    }
  } catch (e) { log("✗ " + e, "bad"); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}

// nhật ký các máy đang nhận đơn: backend đẩy từng dòng về đây
let RUNLOG_LOADED = false;
function showRunLog(e) {
  log(`${e.t} [${e.name}] ${e.text}`, e.kind === "ok" ? "ok" : e.kind === "bad" ? "bad" : "");
}
window.__runLog = showRunLog;
async function loadRunLog() {
  if (RUNLOG_LOADED) return;
  RUNLOG_LOADED = true;
  try { (await API().run_log() || []).forEach(showRunLog); } catch (e) {}
}

// poll trạng thái chạy khi đang ở tab Nhóm & Kịch bản
let STATUS_TIMER = null;
let RUN_SIG = "";                      // dấu vết trạng thái chạy lần vẽ trước (để khỏi vẽ lại khi không có gì đổi)
async function pollStatus(force = true) {
  try { RUN_STATUS = await API().run_status() || {}; } catch (e) { return; }
  refreshGwSync();
  updateDirty();
  const active = $(".view.active");
  DEVICES.forEach(d => {                                 // trang Thiết bị: «đang chạy {nhóm} · {kịch bản}» theo trạng thái mới nhất
    const st = RUN_STATUS[d.name];
    d.running = !!(st && st.running); d.run_group = d.running ? st.group_name : null; d.run_script = d.running ? st.script_name : null;
    d.paused = d.running && !!st.paused; d.pause_requested = d.running && !!st.pause_requested; d.stopping = d.running && !!st.stopping; d.run_mode = d.running ? st.mode : null;
    d.hold = (st && !st.running && st.hold) || null;
    d.parked = !!(st && st.parked);
  });
  // Chỉ vẽ lại khi trạng thái chạy THẬT SỰ đổi: vẽ lại mỗi 2,5 giây làm mất con trỏ / nuốt cú bấm đang dở
  const sig = JSON.stringify(Object.keys(RUN_STATUS).sort().map(n => { const x = RUN_STATUS[n]; return [n, x.running, x.paused, x.pause_requested, x.stopping, x.group_id, x.script_id, x.status, x.last_msg, x.hold, x.parked, x.counts]; }));
  const changed = sig !== RUN_SIG || force;
  RUN_SIG = sig;
  if (!changed) return;
  if (active && active.id === "view-devices") { renderDevices(); renderIOS(); }
  if (active && active.id === "view-flows") {
    if (GROUP_PAGE !== "detail") renderGroupCards();
    else if (GROUP_SUB === "script") renderScriptMachines();
    else { renderMembers(); renderScripts(); }
  }
}
function startStatusPoll() {
  if (STATUS_TIMER) return;
  pollStatus();
  STATUS_TIMER = setInterval(() => pollStatus(false), 2500);     // định kỳ: chỉ vẽ lại khi có thay đổi; gọi tay (sau một cú bấm) thì luôn vẽ lại
}
function stopStatusPoll() {
  if (STATUS_TIMER) { clearInterval(STATUS_TIMER); STATUS_TIMER = null; }
}

/* =========================================================
   INIT
   ========================================================= */
let _inited = false;
function init() {
  if (_inited) return;
  _inited = true;
  setConn(true, "Đã kết nối");

  // nav
  $$(".app-nav").forEach(b => b.onclick = () => showView(b.dataset.view));
  const aiRefresh = $("#btn-ai-refresh");
  if (aiRefresh) aiRefresh.onclick = () => loadAI();
  if (typeof loadAI === "function") loadAI().catch(() => {});   // chấm trạng thái ở thanh bên đúng ngay từ đầu

  // theme toggle (light/dark) — persist + reload so Vuexy re-themes the menu
  const themeBtn = $("#btn-theme");
  if (themeBtn) {
    const cur = document.documentElement.getAttribute("data-bs-theme") || "dark";
    const ic = themeBtn.querySelector("i");
    if (ic) ic.className = "ti " + (cur === "dark" ? "tabler-sun" : "tabler-moon") + " icon-md";
    themeBtn.onclick = () => {
      const next = (document.documentElement.getAttribute("data-bs-theme") === "dark") ? "light" : "dark";
      try { localStorage.setItem("ipf-theme", next); } catch (e) {}
      location.reload();
    };
  }

  // nạp lại + tự động đọc lại (toàn app)
  const reloadBtn = $("#btn-reload-all");
  if (reloadBtn) reloadBtn.onclick = (e) => { busy(e.currentTarget, true); refreshCurrentView(true); setTimeout(() => busy(e.currentTarget, false), 800); };
  const reloadUiBtn = $("#btn-reload-ui");
  if (reloadUiBtn) reloadUiBtn.onclick = async () => {
    // Ưu tiên nhờ backend điều hướng lại (giữ cầu nối pywebview API).
    // location.reload() trên pywebview/macOS làm MẤT window.pywebview.api.
    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.reload_ui) {
        await window.pywebview.api.reload_ui();
        return;
      }
    } catch (e) {}
    location.reload();   // fallback (trình duyệt thường)
  };
  // nút ☰: ẩn / hiện menu bên trái, nhớ lựa chọn
  const menuBtn = $("#btn-menu");
  if (menuBtn) {
    const sync = () => menuBtn.setAttribute("aria-expanded", String(!document.documentElement.classList.contains("ipf-menu-off")));
    sync();
    menuBtn.onclick = () => {
      const off = document.documentElement.classList.toggle("ipf-menu-off");
      try { localStorage.setItem("ipf-menu", off ? "off" : "on"); } catch (e) {}
      sync();
    };
  }
  const stopAllBtn = $("#btn-stop-all");
  if (stopAllBtn) stopAllBtn.onclick = (e) => stopAll(e.currentTarget);
  const restartBtn = $("#btn-restart");
  if (restartBtn) restartBtn.onclick = async () => {
    if (!confirmBox("Khởi động lại app? Cửa sổ sẽ đóng rồi mở lại (vài giây).")) return;
    toast("Đang khởi động lại app…", "");
    try { await API().restart_app(); } catch (e) {}
  };
  const autoSel = $("#auto-sel");
  if (autoSel) {
    let saved = 60; try { const v = localStorage.getItem("ipf-auto"); saved = (v === null) ? 60 : (parseInt(v) || 0); } catch (e) {}
    autoSel.value = String(saved);
    setAuto(saved);
    autoSel.onchange = () => setAuto(parseInt(autoSel.value) || 0);
  }

  // devices
  $("#btn-refresh-dev").onclick = (e) => espScan(e.currentTarget);  // quét lại board + BLE (streaming)
  $("#btn-rescan").onclick = (e) => espScan(e.currentTarget);       // quét streaming (song song)
  $$("#dev-tabs .seg-btn").forEach(b => b.onclick = () => setDevTab(b.dataset.dtab));
  const q = $("#dev-q");
  if (q) q.oninput = (e) => setSearch(e.target.value);
  const qc = $("#dev-q-clear");
  if (qc) qc.onclick = () => { if (q) q.value = ""; setSearch(""); if (q) q.focus(); };

  // overview
  $("#btn-ov-refresh").onclick = () => loadOverview();
  $("#ov-logclear").onclick = () => { $("#ov-log").textContent = ""; $("#ov-logcard").hidden = true; };

  // esp
  $("#btn-esp-scan").onclick = (e) => espScan(e.currentTarget);

  // readiness modal
  $("#ready-close").onclick = () => { $("#ready-modal").hidden = true; };
  $("#ready-recheck").onclick = () => checkReady();

  // probe (dò máy) modal
  const pc = $("#probe-close"); if (pc) pc.onclick = () => { if (!PROBING) $("#probe-modal").hidden = true; };

  // nhóm & kịch bản — chọn nhóm / tạo / xoá / cấu hình / chạy
  $("#btn-group-new").onclick = newGroup;
  $("#btn-group-back").onclick = () => backToList();
  $("#btn-group-save").onclick = (e) => saveGroup(e.currentTarget);
  $("#btn-script-new").onclick = addScript;
  $("#btn-script-back").onclick = () => closeScript();
  $("#script-name").oninput = (e) => { const sc = currentScript(); if (sc) sc.name = e.target.value; updateDirty(); };
  $("#script-mode").onchange = (e) => { const sc = currentScript(); if (!sc) return; sc.mode = e.target.value === "loop" ? "loop" : "once"; sc.loops = sc.mode === "loop" ? 0 : 1; $("#script-loops").value = sc.loops; $("#script-loops-wrap").hidden = sc.mode !== "loop"; updateDirty(); };
  $("#script-loops").oninput = (e) => { const sc = currentScript(); if (sc) sc.loops = Math.max(0, Math.min(100000, parseInt(e.target.value) || 0)); updateDirty(); };
  $("#btn-script-run").onclick = (e) => runScript(e.currentTarget);
  $("#btn-script-stop").onclick = (e) => stopScript(e.currentTarget);
  $("#btn-group-del").onclick = delGroup;
  $("#group-mode").onchange = (e) => {
    if (!GROUP) return;
    GROUP.mode = e.target.value;
    bindSteps();                                    // đổi danh sách bước đang sửa theo chế độ
    renderScripts(); renderMembers();
    if (GROUP.mode === "api") { renderPoolSelect(); GW.ok === null ? loadGateway() : loadGwPool(); }
  };
  $("#group-pool").onchange = (e) => {
    if (!GROUP) return;
    GROUP.api.pool = e.target.value; GW_POOL = null; loadGwPool();
  };
  $("#btn-gw-settings").onclick = gatewaySettings;
  $("#btn-gw-import").onclick = (e) => importGwSteps(e.currentTarget);
  $("#btn-group-run").onclick = (e) => runGroup(e.currentTarget);
  $("#btn-group-stop").onclick = (e) => stopGroup(e.currentTarget);
  $("#group-add-dev").onchange = (e) => { const v = e.target.value; if (v) { addMember(v); e.target.value = ""; } };

  // màn hình thử
  $("#flow-device").onchange = (e) => { SEL = e.target.value || null; };
  $("#btn-shot").onclick = (e) => shot(e.currentTarget);
  $("#btn-ble").onclick = (e) => bleStatus(e.currentTarget);
  $("#screen").onclick = onScreenClick;
  $("#pick-mode").onchange = (e) => { $("#screen").classList.toggle("pick", e.target.checked); if (!e.target.checked) PICK_AT = null; };

  // trình dựng kịch bản
  $("#btn-step-add").onclick = () => openPalette(null, null);
  $$("#step-palette .pal-item").forEach(b => b.onclick = () => pickAction(b.dataset.add));
  $("#step-palette").onkeydown = (e) => { if (e.key === "Escape") { e.stopPropagation(); closePalette(); $("#btn-step-add").focus(); } };
  $("#btn-save").onclick = (e) => saveGroup(e.currentTarget);
  $("#btn-flow-test").onclick = (e) => testFlow(e.currentTarget);
  $("#btn-clear-log").onclick = (e) => { e.preventDefault(); $("#log").innerHTML = ""; $("#log-last").textContent = ""; };   // preventDefault: nút nằm trong tiêu đề khung gập

  // initial load
  loadOverview();     // trang mặc định
  API().groups_list().then(g => { GROUPS = g || []; updateCounts(); routeFromHash(); }).catch(() => {});   // số nhóm ở thanh bên + mở đúng trang theo địa chỉ (#flows/<nhóm>)
  window.addEventListener("hashchange", routeFromHash);
  SCANNING = true;
  espScan();          // quét song song + streaming → badge + board hiện dần
  loadDevices();      // tải iPhone (USB) song song; __scanDone sẽ chốt lại
  renderSteps();
}

// Khởi tạo bền với mọi thứ tự nạp của pywebview: nghe event + poll chờ API.
let __inited = false;
function __tryInit() {
  if (__inited) return;
  if (window.pywebview && window.pywebview.api) { __inited = true; init(); }
}
window.addEventListener("pywebviewready", __tryInit);
let __tries = 0;
const __poll = setInterval(() => {
  __tryInit();
  if (__inited || ++__tries > 80) clearInterval(__poll);   // thử tối đa ~8s
}, 100);
