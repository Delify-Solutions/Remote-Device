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
let SEL = null;                        // tên board đang chọn (ở tab Kịch bản)
let SCREEN = { w: 0, h: 0 };
let FLOW = { id: "", name: "", steps: [] };
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
          <input data-k="${esc(f.key)}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder ?? "")}">`;
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
  $$(".app-nav").forEach(b => b.closest(".menu-item").classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + name));
  const titles = { overview: "Tổng quan", devices: "Thiết bị", esp: "ESP32", flows: "Kịch bản" };
  const pt = document.getElementById("page-title"); if (pt) pt.textContent = titles[name] || "";
  if (name === "overview") loadOverview();
  if (name === "flows") { renderDevicePicker(); renderMultiList(); }
  if (name === "esp" && !ESP_SCANNED) espScan();   // tự quét lần đầu mở tab ESP
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
  renderMultiList();
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
  $("#nav-flow-count").textContent = FLOWS.length;
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
        <div class="cell-sub mono nowrap">${esc(d.name)} · ${esc(shortPort(d.port))}</div></td>
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
    const u = esc(p.udid || "");
    const nm = esc(p.name || "—");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <div class="cell-name">${nm}</div>
        <div class="cell-pills">${isMapped
          ? `<span class="pill ok">đã gán board</span>`
          : `<span class="pill warn">chưa gán board</span>`}</div></td>
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
    const badge = loading
      ? `<span class="pill mut"><span class="spinner" style="width:10px;height:10px;border-width:2px;vertical-align:-1px"></span> đang dò</span>`
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
      </div>`;

    if (loading) {
      body += `<div class="esp-actions"><span class="muted" style="font-size:.82rem">Đang kiểm tra firmware…</span></div>`;
    } else if (flashed) {
      body += `
        <div class="esp-actions">
          <button class="btn btn-sm btn-label-secondary" data-esp="rename" data-port="${esc(b.port)}" data-name="${esc(b.name || "")}">Đổi tên</button>
          <button class="btn btn-sm btn-label-secondary" data-esp="chip" data-port="${esc(b.port)}">Thông tin chip</button>
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
  const prev = SEL;
  sel.innerHTML = "";
  if (!DEVICES.length) {
    sel.innerHTML = `<option value="">(chưa có board)</option>`;
    SEL = null; return;
  }
  DEVICES.forEach(d => {
    const o = document.createElement("option");
    o.value = d.name;
    o.textContent = `${d.label || d.name}${d.board_online ? "" : " (offline)"}`;
    sel.appendChild(o);
  });
  SEL = DEVICES.some(d => d.name === prev) ? prev : DEVICES[0].name;
  sel.value = SEL;
}

function renderMultiList() {
  const box = $("#multi-list");
  const checked = new Set($$(".multi-item input:checked", box).map(c => c.value));
  box.innerHTML = "";
  if (!DEVICES.length) { box.innerHTML = `<div class="empty">Chưa có board.</div>`; return; }
  DEVICES.forEach(d => {
    const lab = document.createElement("label");
    lab.className = "multi-item";
    lab.innerHTML = `
      <input type="checkbox" value="${esc(d.name)}" ${checked.has(d.name) ? "checked" : ""}>
      <span class="dot ${d.board_online ? "on" : "off"}"></span>
      <span class="nm">${esc(d.label || d.name)}</span>`;
    box.appendChild(lab);
  });
}
function checkedDevices() {
  return $$("#multi-list input:checked").map(c => c.value);
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
  addStep({ type: "tap", x, y });
  toast(`+ Tap (${x}, ${y})`, "ok");
}

async function bleStatus(btn) {
  if (!SEL) { toast("Chọn máy trước", "warn"); return; }
  busy(btn, true);
  try {
    const r = await API().ble_status(SEL);
    if (r && r.ok) toast(r.status, r.status.includes("disconnected") ? "warn" : "ok");
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
    default: return "";
  }
}
const STEP_LABEL = {
  tap: "Tap", tap_text: "Tap chữ", type: "Gõ", key: "Phím", combo: "Tổ hợp",
  launch: "Mở app", home: "Home", wait: "Chờ", wait_text: "Chờ chữ", assert_text: "Kiểm chữ",
};

function renderSteps() {
  const ol = $("#steps");
  ol.innerHTML = "";
  $("#steps-empty").hidden = FLOW.steps.length > 0;
  $("#step-count").textContent = FLOW.steps.length ? `(${FLOW.steps.length})` : "";
  FLOW.steps.forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "step";
    li.innerHTML = `
      <span class="t">${esc(STEP_LABEL[s.type] || s.type)}</span>
      <span class="v">${esc(stepText(s))}</span>
      <span class="ops">
        <button data-op="up" title="Lên">▲</button>
        <button data-op="down" title="Xuống">▼</button>
        <button data-op="test" title="Chạy thử">▶</button>
        <button data-op="del" title="Xoá">✕</button>
      </span>`;
    $('[data-op=up]', li).onclick = () => { if (i > 0) { [FLOW.steps[i - 1], FLOW.steps[i]] = [FLOW.steps[i], FLOW.steps[i - 1]]; renderSteps(); } };
    $('[data-op=down]', li).onclick = () => { if (i < FLOW.steps.length - 1) { [FLOW.steps[i + 1], FLOW.steps[i]] = [FLOW.steps[i], FLOW.steps[i + 1]]; renderSteps(); } };
    $('[data-op=del]', li).onclick = () => { FLOW.steps.splice(i, 1); renderSteps(); };
    $('[data-op=test]', li).onclick = async (ev) => {
      if (!SEL) { toast("Chọn máy", "warn"); return; }
      const b = ev.currentTarget; busy(b, true);
      log(`▶ thử ${s.type} ${stepText(s)}`);
      try {
        const r = await API().run_step(SEL, s);
        log(`   ${r.ok ? "✓" : "✗"} ${r.msg}`, r.ok ? "ok" : "bad");
      } catch (e) { log("   ✗ " + e, "bad"); }
      busy(b, false);
      if (s.type === "tap" || s.type === "tap_text") setTimeout(() => shot(null), 600);
    };
    ol.appendChild(li);
  });
}
function addStep(s) { FLOW.steps.push(s); renderSteps(); }

async function addStepPrompt(type) {
  const s = { type };
  if (type === "home") { addStep(s); return; }

  if (type === "type") {
    const t = await askOne("Thêm bước: Gõ chữ", "Nội dung cần gõ", "", "Nội dung…");
    if (t == null) return; s.text = t;
  } else if (type === "tap_text") {
    const t = await askOne("Thêm bước: Tap chữ", "Chữ hiển thị trên màn (OCR)", "", "VD: Đăng nhập");
    if (!t) return; s.text = t;
  } else if (type === "key") {
    const t = await askOne("Thêm bước: Phím", "Phím (enter/tab/back/esc/space)", "enter");
    if (!t) return; s.name = t.trim();
  } else if (type === "combo") {
    const t = await askOne("Thêm bước: Tổ hợp phím", "Tổ hợp (VD: gui h, gui space, ctrl space)", "gui h");
    if (!t) return; s.keys = t.trim();
  } else if (type === "launch") {
    const t = await askOne("Thêm bước: Mở app", "Tên app cần mở", "", "VD: efootball");
    if (!t) return; s.app = t.trim();
  } else if (type === "wait") {
    const t = await askOne("Thêm bước: Chờ", "Số giây chờ", "1.5");
    if (!t) return; s.seconds = parseFloat(t) || 0;
  } else if (type === "wait_text") {
    const r = await askForm("Thêm bước: Chờ chữ", "Chờ tới khi OCR thấy chữ.", [
      { key: "text", label: "Chữ cần chờ", value: "", placeholder: "VD: Trang chủ" },
      { key: "timeout", label: "Timeout (giây)", value: "15" },
    ]);
    if (!r || !r.text) return; s.text = r.text; s.timeout = parseFloat(r.timeout) || 15;
  } else if (type === "assert_text") {
    const t = await askOne("Thêm bước: Kiểm chữ", "Xác minh màn hình có chữ", "", "VD: Thành công");
    if (!t) return; s.text = t;
  }
  addStep(s);
}

/* =========================================================
   FLOWS — save / load / run
   ========================================================= */
async function loadFlows(selectId) {
  try { FLOWS = await API().get_flows() || []; }
  catch (e) { FLOWS = []; toast("Lỗi tải flow: " + e, "bad"); }
  const sel = $("#flow-select");
  sel.innerHTML = '<option value="">+ Flow mới</option>';
  FLOWS.forEach(f => {
    const o = document.createElement("option");
    o.value = f.id; o.textContent = f.name;
    sel.appendChild(o);
  });
  if (selectId) sel.value = selectId;
  $("#nav-flow-count").textContent = FLOWS.length;
}

function onFlowSelect() {
  const id = $("#flow-select").value;
  if (!id) FLOW = { id: "", name: "", steps: [] };
  else {
    const f = FLOWS.find(x => x.id === id);
    FLOW = f ? JSON.parse(JSON.stringify({ id: f.id, name: f.name, steps: f.steps || [] }))
             : { id: "", name: "", steps: [] };
  }
  $("#flow-name").value = FLOW.name || "";
  renderSteps();
}

async function saveFlow(btn) {
  FLOW.name = $("#flow-name").value.trim() || "Flow không tên";
  busy(btn, true);
  try {
    const saved = await API().save_flow(FLOW);
    FLOW.id = saved.id;
    await loadFlows(saved.id);
    toast("Đã lưu flow: " + saved.name, "ok");
  } catch (e) { toast("Lỗi lưu: " + e, "bad"); }
  busy(btn, false);
}

async function delFlow() {
  if (!FLOW.id) { toast("Chưa có flow để xoá", "warn"); return; }
  if (!confirmBox(`Xoá flow “${FLOW.name}”?`)) return;
  try {
    await API().delete_flow(FLOW.id);
    toast("Đã xoá flow", "ok");
  } catch (e) { toast("Lỗi xoá: " + e, "bad"); return; }
  FLOW = { id: "", name: "", steps: [] };
  $("#flow-name").value = ""; $("#flow-select").value = "";
  renderSteps();
  await loadFlows();
}

async function runFlow(btn) {
  if (!SEL) { toast("Chọn máy", "warn"); return; }
  if (!FLOW.id) { toast("Lưu flow trước khi chạy", "warn"); return; }
  busy(btn, true);
  log(`▶ Chạy “${FLOW.name}” trên ${SEL}`);
  try {
    const r = await API().run_flow(SEL, FLOW.id);
    if (!r || !r.ok) { log("✗ " + ((r && r.error) || "lỗi"), "bad"); toast("Chạy thất bại", "bad"); }
    else {
      let okN = 0;
      r.results.forEach(x => { if (x.ok) okN++; log(`   [${x.i + 1}] ${x.type}: ${x.ok ? "✓" : "✗"} ${x.msg}`, x.ok ? "ok" : "bad"); });
      toast(`${SEL}: ${okN}/${r.results.length} bước OK`, okN === r.results.length ? "ok" : "warn");
      setTimeout(() => shot(null), 600);
    }
  } catch (e) { log("✗ " + e, "bad"); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}

async function runMulti(btn) {
  const names = checkedDevices();
  if (!names.length) { toast("Tick ít nhất 1 máy", "warn"); return; }
  if (!FLOW.id) { toast("Lưu flow trước khi chạy", "warn"); return; }
  busy(btn, true);
  log(`⇉ Chạy “${FLOW.name}” trên: ${names.join(", ")}`);
  try {
    const r = await API().run_flow_multi(names, FLOW.id);
    if (!r || !r.ok) { log("✗ " + ((r && r.error) || "lỗi"), "bad"); toast("Chạy thất bại", "bad"); }
    else {
      Object.entries(r.results).forEach(([nm, res]) => {
        const okN = res.filter(x => x.ok).length;
        const allOk = okN === res.length;
        log(`   ${nm}: ${okN}/${res.length} bước OK`, allOk ? "ok" : "bad");
      });
      toast(`Đã chạy trên ${names.length} máy`, "ok");
    }
  } catch (e) { log("✗ " + e, "bad"); toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
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

  // flows — screen
  $("#flow-device").onchange = (e) => { SEL = e.target.value || null; };
  $("#btn-shot").onclick = (e) => shot(e.currentTarget);
  $("#btn-ble").onclick = (e) => bleStatus(e.currentTarget);
  $("#screen").onclick = onScreenClick;
  $("#pick-mode").onchange = (e) => $("#screen").classList.toggle("pick", e.target.checked);

  // flows — builder
  $$(".add-grid .chip").forEach(b => b.onclick = () => addStepPrompt(b.dataset.add));
  $("#flow-select").onchange = onFlowSelect;
  $("#flow-name").oninput = (e) => { FLOW.name = e.target.value; };
  $("#btn-save").onclick = (e) => saveFlow(e.currentTarget);
  $("#btn-del").onclick = delFlow;
  $("#btn-run").onclick = (e) => runFlow(e.currentTarget);
  $("#btn-run-multi").onclick = (e) => runMulti(e.currentTarget);
  $("#btn-clear-log").onclick = () => { $("#log").innerHTML = ""; };

  // initial load
  loadOverview();     // trang mặc định
  SCANNING = true;
  loadFlows();
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
