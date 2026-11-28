// main.js — KHỞI ĐỘNG giao diện. Phải nạp SAU CÙNG: mã chạy ngay lúc nạp tệp đặt cả ở đây, các tệp trước nó chỉ khai báo hàm / biến
// (riêng alerts.js tự gắn nút «Tải lại» của trang mình). Gồm: các hàm backend gọi vào để đẩy kết quả về trang (window.__espUpdate,
// __devBoard, __scanDone, __runLog), init() — gắn nút của mọi trang với hàm ở các tệp kia rồi tải dữ liệu lần đầu — và phần chờ cầu nối
// pywebview sẵn sàng (sự kiện 'pywebviewready' + hỏi lại mỗi 100 ms).

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
window.__runLog = showRunLog;

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

  // nhóm & kịch bản — chọn nhóm / tạo / xoá / lưu; kịch bản — cách chạy, máy chạy
  $("#btn-group-new").onclick = newGroup;
  $("#btn-group-back").onclick = () => backToList();
  $("#btn-group-save").onclick = (e) => saveGroup(e.currentTarget);
  $("#btn-script-new").onclick = addScript;
  $("#btn-script-back").onclick = () => closeScript();
  $("#script-name").oninput = (e) => { const sc = currentScript(); if (sc) sc.name = e.target.value; updateDirty(); };
  $("#script-mode").onchange = (e) => {
    const sc = currentScript();
    if (!sc) return;
    setScriptMode(sc, e.target.value);
    $("#script-loops").value = sc.loops; $("#script-loops-wrap").hidden = sc.mode !== "loop";
    renderOrdersOpts(sc);
    if (sc.mode === "orders") { GW.ok === null ? loadGateway() : loadGwPool(); }
    bindSteps();
  };
  $("#script-loops").oninput = (e) => { const sc = currentScript(); if (sc) sc.loops = Math.max(0, Math.min(100000, parseInt(e.target.value) || 0)); updateDirty(); };
  // tuỳ chọn của kịch bản nhận đơn: ghi thẳng vào sc.orders (5–600 giây; ô trống / chữ lạ → mặc định); rời ô thì ô hiện đúng số sẽ lưu
  [["#orders-login-wait", "login_wait", 45], ["#orders-purchase-wait", "purchase_wait", 60]].forEach(([sel, key, def]) => {
    $(sel).oninput = (e) => { const sc = scriptOrders(); if (sc) sc.orders[key] = Math.max(5, Math.min(600, parseInt(e.target.value) || def)); updateDirty(); };
    $(sel).onchange = (e) => { const sc = scriptOrders(); if (sc) e.target.value = sc.orders[key]; };
  });
  $("#orders-kb").onchange = (e) => { const sc = scriptOrders(); if (sc) sc.orders.check_keyboard = e.target.checked; updateDirty(); };
  $("#btn-script-run").onclick = (e) => runScript(e.currentTarget);
  $("#btn-script-stop").onclick = (e) => stopScript(e.currentTarget);
  $("#btn-group-del").onclick = delGroup;
  $("#btn-gw-settings").onclick = gatewaySettings;
  $("#btn-tg-settings").onclick = () => showView("alerts");          // cấu hình ở trang «Thông báo & AI»
  $("#btn-ai-screen").onclick = () => showView("alerts");
  const walRefresh = $("#btn-wal-refresh"); if (walRefresh) walRefresh.onclick = () => loadWallets();
  loadAiScreen();
  loadTelegram();
  alertsBadge();                                     // nhãn «Thông báo & AI» ở menu: đã cài Telegram / AI chưa
  setInterval(() => { loadTelegram(); loadAiScreen(); alertsBadge(); }, 30000);   // lần gửi Telegram gần nhất lỗi thì chấm đỏ
  $("#group-add-dev").onchange = (e) => { const v = e.target.value; if (v) { addMember(v); e.target.value = ""; } };

  // màn hình thử
  $("#flow-device").onchange = (e) => { SEL = e.target.value || null; paintProgress(); };     // máy đang chọn có tiến độ của kịch bản này → tô nó lên lộ trình
  $("#btn-shot").onclick = (e) => shot(e.currentTarget);
  $("#btn-ble").onclick = (e) => bleStatus(e.currentTarget);
  $$(".mon-tab").forEach(b => b.onclick = () => setMonTab(b.dataset.monTab));
  $("#btn-mon-refresh").onclick = () => { MON.sig = ""; pollMonitor(); };
  $("#mon-machine").onchange = (e) => pickMonMachine(e.target.value);
  $("#btn-mon-older").onclick = () => loadMonMachine(true);
  $("#screen").onclick = onScreenClick;
  $("#screen").onpointerdown = onScreenDown;
  $("#screen").onpointermove = onScreenMove;
  $("#screen").onpointerup = onScreenUp;
  $("#screen").onpointercancel = onScreenCancel;
  $("#pick-mode").onchange = (e) => setPickMode(e.target.checked);

  // trình dựng kịch bản
  $("#btn-step-add").onclick = () => openPalette({ list: FLOW.steps, at: null }, null);
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
