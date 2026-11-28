// esp.js — trang «ESP32»: quét các board đang cắm USB (kết quả về dần từng board), thẻ của từng board và các việc làm trên board:
// nạp firmware, đổi tên Bluetooth (nạp lại), xoá trắng, đọc thông tin chip — nhật ký của việc đó hiện ngay trong thẻ.

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
