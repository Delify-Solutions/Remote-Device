// core.js — iPhone Farm Manager: phần DÙNG CHUNG của mọi trang (tệp nạp đầu tiên).
// Cầu nối tới backend (API() = window.pywebview.api, hàm nào cũng async), trạng thái chung của app, thoát HTML, thông báo nổi + hộp thoại
// nhập liệu, nhật ký, chuyển trang (showView), copy, nạp lại + tự động đọc lại. Việc khởi động (init) nằm ở main.js — tệp nạp sau cùng.

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const API = () => window.pywebview.api;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let DEVICES = [];
let IOS = [];
let ESP = [];
let GROUPS = [];                       // danh sách nhóm
let GROUP = null;                      // nhóm đang chọn (bản sao để sửa)
let RUN_STATUS = {};                   // trạng thái chạy từng máy (poll)
let SEL = null;                        // tên board đang chọn để thử (tab Nhóm)
let GROUP_PAGE = "list";               // tab Nhóm: "list" = danh sách nhóm, "detail" = trang quản lý 1 nhóm
let GROUP_SUB = "home";                // trong 1 nhóm: "home" = máy + danh sách kịch bản, "script" = trình sửa 1 kịch bản
let EDIT_SID = null;                   // id kịch bản đang sửa
let GROUP_SNAP = "";                   // ảnh chụp trạng thái nhóm lúc mở / lưu (để biết có thay đổi chưa lưu)
let SCREEN = { w: 0, h: 0 };
let FLOW = { id: "", name: "", steps: [] };   // bản steps đang dựng (của nhóm)
let ESP_SCANNED = false;               // đã quét ESP lần nào chưa (để tự quét khi mở tab)
let SCANNING = false;                  // đang quét board (serial) — hiện trạng thái "đang quét"
let IOS_LOADING = false;               // đang tải danh sách iPhone qua USB

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
      if (f.type === "image") {                           // chỉ để XEM (ảnh mẫu của bước); `src` đã qua imageSrc()
        wrap.innerHTML = f.src ? `<img class="modal-thumb" src="${f.src}" alt="${esc(f.alt || "Hình cần bấm")}">` : `<div class="text-danger small">Ảnh của bước này không đọc được.</div>`;
        box.appendChild(wrap);
        return;
      }
      if (f.type === "select") {
        const opts = (f.options || []).map(o =>
          `<option value="${esc(o.value)}" ${String(o.value) === String(f.value) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
        wrap.innerHTML = `<label>${esc(f.label)}</label>
          <select data-k="${esc(f.key)}" class="modal-select">${opts}</select>`;
      } else if (f.type === "textarea") {                 // ô nhiều dòng (Enter = xuống dòng, không phải «Xác nhận»)
        wrap.innerHTML = `<label>${esc(f.label)}</label>
          <textarea data-k="${esc(f.key)}" class="modal-select modal-area" rows="${f.rows || 4}" spellcheck="false" placeholder="${esc(f.placeholder ?? "")}">${esc(f.value ?? "")}</textarea>`;
      } else {
        wrap.innerHTML = `<label>${esc(f.label)}</label>
          <input type="${f.type === "password" ? "password" : "text"}" autocomplete="off" data-k="${esc(f.key)}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder ?? "")}">`;
      }
      if (f.vars && (f.vars.items.length || f.vars.note)) {      // dữ liệu của ĐƠN chèn được vào ô này: mỗi thứ một ô bấm
        wrap.insertAdjacentHTML("beforeend", varChips(f.vars));
        $$(".var-chip", wrap).forEach(b => b.onclick = () => insertAtCursor($("input, textarea", wrap), `{{${b.dataset.var}}}`));
      }
      box.appendChild(wrap);
    });
    ov.hidden = false;
    const first = box.querySelector("input, select, textarea"); if (first) { first.focus(); if (first.select && first.tagName !== "TEXTAREA") first.select(); }

    const close = (val) => {
      ov.hidden = true;
      $("#modal-ok").onclick = $("#modal-cancel").onclick = null;
      ov.onkeydown = null;
      resolve(val);
    };
    const collect = () => {
      const out = {};
      $$("#modal-fields input, #modal-fields select, #modal-fields textarea").forEach(inp => out[inp.dataset.k] = inp.value);
      return out;
    };
    $("#modal-ok").onclick = () => close(collect());
    $("#modal-cancel").onclick = () => close(null);
    ov.onkeydown = (e) => {
      const own = e.target && (e.target.tagName === "TEXTAREA" || (e.target.classList && e.target.classList.contains("var-chip")));   // Enter ở đây có nghĩa riêng (xuống dòng / bấm ô)
      if (e.key === "Enter" && !own) { e.preventDefault(); close(collect()); }
      if (e.key === "Escape") { e.preventDefault(); close(null); }
    };
  });
}
async function askOne(title, label, value = "", placeholder = "", vars = null) {
  const r = await askForm(title, "", [{ key: "v", label, value, placeholder, vars }]);
  return r ? r.v : null;
}
// Hàng ô bấm «Lấy từ đơn» dưới một ô nhập: vars = {items: [{name, label, secret}], note}. Tên / nhãn đến từ gateway → luôn thoát.
function varChips(vars) {
  const chips = vars.items.map(v =>
    `<button type="button" class="var-chip" data-var="${esc(v.name)}" title="Chèn {{${esc(v.name)}}} — lúc chạy, tool thay bằng giá trị trong đơn của khách">${v.secret ? `<i class="ti tabler-lock" aria-hidden="true"></i>` : ""}${esc(v.label)}</button>`).join("");
  return `<div class="modal-vars">${chips ? `<span class="modal-vars-title">Lấy từ đơn</span>${chips}` : ""}${vars.note ? `<span class="modal-vars-note">${esc(vars.note)}</span>` : ""}</div>`;
}
function insertAtCursor(inp, text) {   // chèn vào chỗ con trỏ (thay phần đang bôi), rồi đặt con trỏ ngay sau chỗ vừa chèn
  const a = inp.selectionStart ?? inp.value.length, z = inp.selectionEnd ?? inp.value.length;
  inp.value = inp.value.slice(0, a) + text + inp.value.slice(z);
  inp.focus();
  inp.setSelectionRange(a + text.length, a + text.length);
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
  const titles = { overview: "Tổng quan", devices: "Thiết bị", esp: "ESP32", flows: "Nhóm & Kịch bản", ai: "Kết nối AI", monitor: "Theo dõi", alerts: "Thông báo & AI", wallets: "Ví & Apple" };
  const pt = document.getElementById("page-title"); if (pt) pt.textContent = titles[name] || "";
  if (name === "overview") loadOverview();
  if (name === "flows") {
    if (was === "view-flows" && GROUP_PAGE === "detail") backToList();   // bấm lại mục menu khi đang ở 1 nhóm → về danh sách
    (async () => { await loadGroups(); await loadGateway(); })();
    loadRunLog(); startStatusPoll();
  } else if (name === "devices") { startStatusPoll(); }
  else { stopStatusPoll(); }
  if (name === "monitor") startMonitor(); else stopMonitor();
  if (name === "esp" && !ESP_SCANNED) espScan();   // tự quét lần đầu mở tab ESP
  if (name === "ai") loadAI();
  if (name === "alerts") loadAlerts();
  if (name === "wallets") loadWallets();
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
