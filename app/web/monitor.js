// monitor.js — hai trang để XEM: «Theo dõi» (máy nào đang chạy bước nào + lịch sử theo máy / theo đơn; tự hỏi lại mỗi 2 giây khi đang mở)
// và «Tổng quan» (hệ điều hành, thư viện Python, công cụ hệ thống — kèm nút cài cái còn thiếu).

/* =========================================================
   THEO DÕI — máy nào đang chạy bước nào + lịch sử theo máy / theo đơn (dữ liệu từ app/history.py)
   ========================================================= */
let MON = { timer: null, live: {}, now: 0, machine: "", events: [], tab: "machine", sig: "", order: null };

// Khoảng thời gian đọc được: «6 giây», «2 phút 10 giây», «1 giờ 3 phút».
function monDur(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  if (sec < 60) return `${sec} giây`;
  if (sec < 3600) return `${Math.floor(sec / 60)} phút` + (sec % 60 ? ` ${sec % 60} giây` : "");
  return `${Math.floor(sec / 3600)} giờ` + (Math.floor(sec % 3600 / 60) ? ` ${Math.floor(sec % 3600 / 60)} phút` : "");
}
function monClock(t, withDay) {               // giờ địa phương HH:MM:SS (kèm ngày/tháng nếu cần)
  const d = new Date((Number(t) || 0) * 1000), p = (n) => String(n).padStart(2, "0");
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  return withDay ? `${p(d.getDate())}/${p(d.getMonth() + 1)} ${hm}` : hm;
}
// Kết quả của một đơn → [chữ, kiểu nhãn]
function monResult(r) {
  return ({ done: ["Hoàn tất", "ok"], failed: ["Thất bại", "bad"], review: ["Chờ đối soát", "warn"], error: ["Bộ chạy lỗi giữa chừng", "bad"] })[r] || ["Gateway đã đóng đơn", "mut"];
}
function monItems(items) {                    // «1050 Coins ×2, Gói khởi đầu ×1»
  return (Array.isArray(items) ? items : []).map(it => `${(it && (it.name || it.code)) || "?"} ×${(it && it.qty) || 1}`).join(", ");
}
// Việc một máy ĐANG làm → {head, step, since}: «nạp Efootball · đơn T-12», «Đăng nhập · bước 5/16 — Bấm vào chữ «Login»», mốc bắt đầu bước.
function monLiveLine(v) {
  if (!v) return null;
  const head = [v.kind, [v.group, v.script].filter(Boolean).join(" · "), v.order ? `đơn ${v.order.ref || v.order.id}` : ""].filter(Boolean).join(" — ");
  const st = v.step, la = v.last;
  const pos = (x) => [x.phase, x.i ? `bước ${x.i}${x.n ? "/" + x.n : ""}` : ""].filter(Boolean).join(" · ");
  if (st) return { head, step: [pos(st), st.what].filter(Boolean).join(" — "), since: st.since, running: true };
  if (la) return { head, step: [pos(la), la.what].filter(Boolean).join(" — "), since: la.t, running: false, ok: !!la.ok, msg: la.msg || "" };
  return { head, step: v.phase || "", since: v.since, running: false };
}
// Các sự kiện (cũ → mới) gom thành TỪNG LƯỢT CHẠY, lượt mới nhất đứng trước: [{run: sự kiện run_begin | null, end: run_end | null, items: [...]}]
function monGroup(events) {
  const blocks = [];
  let cur = null;
  (Array.isArray(events) ? events : []).forEach(e => {
    if (!e || typeof e !== "object") return;
    const rid = e.ev === "run_begin" ? e.id : (e.run || null);
    if (!cur || cur.id !== rid) { cur = { id: rid, run: null, end: null, items: [] }; blocks.push(cur); }
    if (e.ev === "run_begin") cur.run = e;
    else if (e.ev === "run_end") cur.end = e;
    else cur.items.push(e);
  });
  return blocks.reverse();
}
function monEventHtml(e) {                    // một dòng của lịch sử; mọi chữ lấy từ dữ liệu đều được thoát
  if (e.ev === "step") {
    const pos = [e.phase, e.i ? `${e.i}${e.n ? "/" + e.n : ""}` : ""].filter(Boolean).join(" ");
    return `<div class="mon-ev ${e.ok ? "ok" : "bad"}"><span class="mon-mark">${e.ok ? "✓" : "✗"}</span><span class="mon-t">${monClock(e.t)}</span>`
      + `<span class="mon-what">${pos ? `<span class="mon-pos">${esc(pos)}</span>` : ""}${esc(e.what || "")}${e.msg ? `<span class="mon-msg"> — ${esc(e.msg)}</span>` : ""}</span>`
      + `<span class="mon-dur">${esc(monDur(e.dur))}</span></div>`;
  }
  if (e.ev === "order_begin") return `<div class="mon-ev order"><span class="mon-mark">▸</span><span class="mon-t">${monClock(e.t)}</span><span class="mon-what"><b>Đơn ${esc(e.ref || e.order || "")}</b>${e.resumed ? " (làm tiếp)" : ""} — ${esc(monItems(e.items) || "không có gói")}</span></div>`;
  if (e.ev === "order_end") {
    const [label, cls] = monResult(e.result);
    return `<div class="mon-ev order"><span class="mon-mark">■</span><span class="mon-t">${monClock(e.t)}</span><span class="mon-what"><b>Đơn ${esc(e.ref || e.order || "")}</b> <span class="pill ${cls}">${esc(label)}</span>${e.msg ? `<span class="mon-msg"> — ${esc(e.msg)}</span>` : ""}</span><span class="mon-dur">${esc(monDur(e.dur))}</span></div>`;
  }
  if (e.ev === "note") return `<div class="mon-ev note ${e.kind === "bad" ? "bad" : ""}"><span class="mon-mark">·</span><span class="mon-t">${monClock(e.t)}</span><span class="mon-what">${esc(e.text || "")}</span></div>`;
  return "";
}
function monBlocksHtml(events, empty) {
  const blocks = monGroup(events);
  if (!blocks.length) return `<div class="api-note">${esc(empty)}</div>`;
  return blocks.map(b => {
    const r = b.run, first = r || b.items[0] || b.end || {};
    const title = r ? [r.kind, [r.group, r.script].filter(Boolean).join(" · ")].filter(Boolean).join(" — ") : "Thao tác lẻ (ngoài lượt chạy)";
    const tail = b.end ? `${b.end.status ? esc(b.end.status) + " · " : ""}${esc(monDur(b.end.dur))}` : (r ? `<span class="pill ok">đang chạy</span>` : "");
    return `<div class="mon-block"><div class="mon-block-head"><span class="mon-t">${monClock(first.t, true)}</span><b>${esc(title)}</b><span class="mon-block-tail">${tail}</span></div>`
      + (b.items.map(monEventHtml).join("") || `<div class="api-note">Chưa có bước nào.</div>`) + `</div>`;
  }).join("");
}

function monName(n) { const d = DEVICES.find(x => x.name === n); return d ? (d.label || d.name) : n; }
function renderMonLive() {
  const box = $("#mon-live");
  const names = [...new Set([...DEVICES.filter(d => d.board_online || d.udid).map(d => d.name), ...Object.keys(MON.live), ...Object.keys(RUN_STATUS)])];
  if (!names.length) { box.innerHTML = `<div class="api-note">Chưa có máy nào.</div>`; return; }
  let busy = 0;
  box.innerHTML = names.map(n => {
    const st = RUN_STATUS[n] || {}, v = monLiveLine(MON.live[n]);
    const running = !!st.running || !!(v && v.running);
    if (running) busy++;
    const state = st.hold && !st.running ? `<span class="pill bad" title="${esc(st.hold)}">dừng chờ kiểm tra</span>` : st.parked ? `<span class="pill warn">đang dừng để xử lý tay</span>`
      : st.running ? `<span class="pill ok">${esc(st.status || "đang chạy")}</span>` : (v && v.running) ? `<span class="pill ok">đang chạy thử</span>` : `<span class="pill mut">nghỉ</span>`;
    const line = v ? `<div class="mon-live-head">${esc(v.head)}</div>`
      + (v.step ? `<div class="mon-live-step ${v.running ? "" : (v.ok === false ? "bad" : "done")}">${v.running ? "" : (v.ok === false ? "✗ " : "✓ ")}${esc(v.step)}${v.msg ? ` — ${esc(v.msg)}` : ""}`
        + (v.since ? `<span class="mon-dur">${v.running ? esc(monDur(MON.now - v.since)) : "xong " + esc(monDur(MON.now - v.since)) + " trước"}</span>` : "") + `</div>` : "") : "";
    return `<div class="mon-live-row ${running ? "on" : ""}" data-mon-pick="${esc(n)}" role="button" tabindex="0" title="Xem lịch sử của máy này">
      <span class="dot ${running ? "on" : ""}"></span><div class="mon-live-main"><div class="mon-live-name">${esc(monName(n))} ${state}</div>${line}</div></div>`;
  }).join("");
  $$("[data-mon-pick]", box).forEach(r => r.onclick = () => { setMonTab("machine"); pickMonMachine(r.dataset.monPick); });
  const badge = $("#nav-mon-count"); if (badge) { badge.hidden = !busy; badge.textContent = String(busy); }
  const sel = $("#mon-machine"), keep = MON.machine || sel.value;
  const opts = names.map(n => `<option value="${esc(n)}">${esc(monName(n))}</option>`).join("");
  if (sel.dataset.sig !== opts) { sel.innerHTML = opts; sel.dataset.sig = opts; }
  if (keep && names.includes(keep)) sel.value = keep;
  if (!MON.machine && sel.value) pickMonMachine(sel.value);
}
async function pollMonitor() {
  try {
    const [r, st] = await Promise.all([API().history_live(), API().run_status()]);
    if (st) RUN_STATUS = st;
    if (r && r.ok) { MON.live = r.live || {}; MON.now = r.now || Date.now() / 1000; }
  } catch (e) { return; }
  renderMonLive();
  // máy đang xem vừa có bước mới xong → nạp lại lịch sử của nó (không nạp lại mỗi nhịp: tránh làm trôi chỗ người dùng đang đọc)
  const v = MON.live[MON.machine], sig = v ? JSON.stringify([v.last && v.last.t, v.order && v.order.id, !!v.step]) : "";
  if (sig !== MON.sig) { MON.sig = sig; if (MON.tab === "machine") loadMonMachine(); else loadMonOrders(); }
}
async function pickMonMachine(n) { MON.machine = n; MON.sig = ""; $("#mon-machine").value = n; await loadMonMachine(); }
async function loadMonMachine(older) {
  if (!MON.machine) return;
  try {
    const before = older && MON.events.length ? MON.events[0].t : null;
    const r = await API().history_machine(MON.machine, 300, before);
    const ev = (r && r.events) || [];
    MON.events = older ? ev.concat(MON.events) : ev;
    $("#btn-mon-older").hidden = ev.length < 300;
  } catch (e) { return; }
  $("#mon-machine-info").textContent = MON.events.length ? `${MON.events.filter(e => e.ev === "step").length} bước gần nhất` : "";
  $("#mon-timeline").innerHTML = monBlocksHtml(MON.events, "Máy này chưa có lịch sử — chạy một kịch bản hoặc bấm «Thử» một bước là có.");
}
async function loadMonOrders() {
  const box = $("#mon-orders");
  let rows = [];
  try { rows = ((await API().history_orders(200)) || {}).orders || []; } catch (e) { return; }
  if (!rows.length) { box.innerHTML = `<div class="api-note">Chưa có đơn nào chạy qua tool này.</div>`; $("#mon-order-detail").hidden = true; return; }
  box.innerHTML = `<div class="mon-table"><div class="mon-tr head"><span>Lúc</span><span>Đơn</span><span>Máy</span><span>Gói</span><span>Kết quả</span><span>Mất</span></div>`
    + rows.map(o => { const [label, cls] = monResult(o.result);
      return `<div class="mon-tr ${MON.order === String(o.id) ? "sel" : ""}" data-mon-order="${esc(o.id)}" role="button" tabindex="0" title="${esc(o.msg || "")}">
        <span class="mon-t">${monClock(o.t, true)}</span><span><b>${esc(o.ref || o.id)}</b></span><span>${esc(monName(o.machine || ""))}</span>
        <span>${esc(monItems(o.items))}</span><span><span class="pill ${cls}">${esc(label)}</span>${o.failed ? ` <small class="text-muted">${Number(o.failed)} bước lỗi</small>` : ""}</span><span>${esc(monDur((o.end || 0) - (o.t || 0)))}</span></div>`; }).join("") + `</div>`;
  $$("[data-mon-order]", box).forEach(r => r.onclick = () => openMonOrder(r.dataset.monOrder));
}
async function openMonOrder(id) {
  MON.order = String(id);
  $$("#mon-orders .mon-tr").forEach(r => r.classList.toggle("sel", r.dataset.monOrder === MON.order));
  const box = $("#mon-order-detail");
  box.hidden = false; box.innerHTML = `<div class="api-note">Đang tải…</div>`;
  try {
    const r = await API().history_order(id);
    const ev = (r && r.events) || [];
    box.innerHTML = `<h6 class="mon-title">Các bước của đơn ${esc(((r.runs || [])[0] || {}).ref || id)}</h6>`
      + (ev.length ? ev.map(monEventHtml).join("") : `<div class="api-note">Không còn lịch sử các bước của đơn này (đã quá cũ).</div>`);
  } catch (e) { box.innerHTML = `<div class="api-note">Không tải được: ${esc(String(e))}</div>`; }
}
function setMonTab(tab) {
  MON.tab = tab;
  $$(".mon-tab").forEach(b => b.classList.toggle("active", b.dataset.monTab === tab));
  $("#mon-pane-machine").hidden = tab !== "machine";
  $("#mon-pane-orders").hidden = tab !== "orders";
  if (tab === "orders") loadMonOrders(); else loadMonMachine();
}
function startMonitor() {
  if (!DEVICES.length) loadDevices();
  pollMonitor();
  if (!MON.timer) MON.timer = setInterval(pollMonitor, 2000);
}
function stopMonitor() { if (MON.timer) { clearInterval(MON.timer); MON.timer = null; } }

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
      <div class="ov-kv"><span>Bộ đọc chữ</span><span>${esc(s.ocr || "—")}</span></div>
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
