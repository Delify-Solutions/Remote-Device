// devices.js — trang «Thiết bị»: danh sách máy (board ESP32 + iPhone nối USB), thẻ con / tìm kiếm / phân trang, đổi nhãn, gán board, xoá,
// «dò máy» (nhận ra iPhone nào đang nối board nào) và hộp «Kiểm tra iPhone» (Trust, Developer Mode, Developer Disk Image, Bluetooth).

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
