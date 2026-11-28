// screen.js — khung «màn hình thử» của trình sửa kịch bản: chọn máy để thử, chụp màn hình, bấm lên ảnh hoặc kéo một khung trên ảnh
// (thành bước «bấm tại» / «bấm vào vùng ảnh» — thêm vào kịch bản bằng addPicked ở stepedit.js), cắt ảnh mẫu, hỏi trạng thái Bluetooth của board.

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
    const grid = $(".ed-grid");
    if (grid) grid.classList.toggle("is-landscape", r.w > r.h);
    $("#screen-info").textContent = `${SEL} · ${r.w}×${r.h}`;
  } catch (e) {
    spin.hidden = true; busy(btn, false);
    toast("Lỗi chụp: " + e, "bad");
  }
}

// Một VÙNG trên ảnh màn hình do người dùng kéo ra: hai điểm (toạ độ trang) + khung của ảnh trên trang + cỡ ảnh thật → {x, y, w, h} theo
// điểm ảnh của ảnh chụp (cắt gọn trong ảnh). Kéo chưa tới REGION_DRAG điểm = một cú BẤM (trả null). Khung quá nhỏ / quá lớn → {error}.
const REGION_DRAG = 6, REGION_MIN = 12, REGION_MAX = 400;
function dragRegion(a, b, rect, screen) {
  if (!a || !b || !rect || !(rect.width > 0) || !(rect.height > 0) || !screen || !(screen.w > 0) || !(screen.h > 0)) return null;
  if (Math.abs(b.x - a.x) < REGION_DRAG && Math.abs(b.y - a.y) < REGION_DRAG) return null;
  const cl = (v, hi) => Math.round(Math.max(0, Math.min(hi, v)));
  const fx = screen.w / rect.width, fy = screen.h / rect.height;
  const x0 = cl((Math.min(a.x, b.x) - rect.left) * fx, screen.w), x1 = cl((Math.max(a.x, b.x) - rect.left) * fx, screen.w);
  const y0 = cl((Math.min(a.y, b.y) - rect.top) * fy, screen.h), y1 = cl((Math.max(a.y, b.y) - rect.top) * fy, screen.h);
  const r = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  if (r.w < REGION_MIN || r.h < REGION_MIN) return { error: `Khung quá nhỏ (${r.w}×${r.h}) — kéo một khung bao trọn nút cần bấm, mỗi cạnh ít nhất ${REGION_MIN} điểm ảnh` };
  if (r.w > REGION_MAX || r.h > REGION_MAX) return { error: `Khung quá lớn (${r.w}×${r.h}) — chỉ khoanh sát quanh nút cần bấm, mỗi cạnh tối đa ${REGION_MAX} điểm ảnh` };
  return r;
}
// Dữ liệu điểm ảnh RGBA có «gần như một màu» không: độ lệch chuẩn của TỪNG kênh màu đều dưới 4 (cùng phép kiểm với phía máy — eyes.decode_image).
function flatPixels(d) {
  const sum = [0, 0, 0], sq = [0, 0, 0], n = d.length / 4;
  for (let i = 0; i < d.length; i += 4) for (let c = 0; c < 3; c++) { const v = d[i + c]; sum[c] += v; sq[c] += v * v; }
  return n < 1 || [0, 1, 2].every(c => Math.sqrt(Math.max(0, sq[c] / n - (sum[c] / n) ** 2)) < 4);
}
// Cắt vùng `r` từ ảnh màn hình đang hiện (ảnh PNG gốc, đủ điểm ảnh) → {image: PNG base64}; vùng gần như một màu (không có gì để nhận ra) → {error}.
function cropRegion(img, r) {
  const c = document.createElement("canvas");
  c.width = r.w; c.height = r.h;
  const g = c.getContext("2d");
  g.drawImage(img, r.x, r.y, r.w, r.h, 0, 0, r.w, r.h);
  const d = g.getImageData(0, 0, r.w, r.h).data;
  if (flatPixels(d)) return { error: "Vùng vừa chọn gần như một màu — khoanh vùng có hình hoặc chữ để máy nhận ra" };
  return { image: c.toDataURL("image/png").split(",")[1] };
}
let DRAG = null;                        // đang kéo khung trên ảnh màn hình: điểm bắt đầu {x, y} (toạ độ trang)
let DRAG_DONE = false;                  // vừa kéo xong một khung → bỏ qua sự kiện «click» đi liền sau
function onScreenDown(e) {
  if (!$("#pick-mode").checked || !SCREEN.w || e.button) return;
  DRAG = { x: e.clientX, y: e.clientY };
  DRAG_DONE = false;
  try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) { /* trình duyệt cũ: vẫn kéo được trong phạm vi ảnh */ }
}
function onScreenMove(e) {
  if (!DRAG) return;
  const sel = $("#screen-sel"), wrap = $("#screen-wrap"), rect = $("#screen").getBoundingClientRect(), wr = wrap.getBoundingClientRect();
  if (Math.abs(e.clientX - DRAG.x) < REGION_DRAG && Math.abs(e.clientY - DRAG.y) < REGION_DRAG) { sel.hidden = true; return; }
  const cl = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const x0 = cl(Math.min(DRAG.x, e.clientX), rect.left, rect.right), x1 = cl(Math.max(DRAG.x, e.clientX), rect.left, rect.right);
  const y0 = cl(Math.min(DRAG.y, e.clientY), rect.top, rect.bottom), y1 = cl(Math.max(DRAG.y, e.clientY), rect.top, rect.bottom);
  Object.assign(sel.style, { left: (x0 - wr.left - wrap.clientLeft) + "px", top: (y0 - wr.top - wrap.clientTop) + "px", width: (x1 - x0) + "px", height: (y1 - y0) + "px" });
  sel.hidden = false;
}
function onScreenUp(e) {
  if (!DRAG) return;
  const a = DRAG, img = $("#screen");
  DRAG = null;
  $("#screen-sel").hidden = true;
  const r = dragRegion(a, { x: e.clientX, y: e.clientY }, img.getBoundingClientRect(), SCREEN);
  if (!r) return;                       // không kéo → sự kiện «click» sẽ thêm bước bấm theo toạ độ như cũ
  DRAG_DONE = true;
  setTimeout(() => { DRAG_DONE = false; }, 0);            // «click» (nếu có) tới ngay sau «pointerup»; kéo ra ngoài ảnh thì không có «click» nào → tự gỡ cờ
  if (r.error) { toast(r.error, "warn"); return; }
  const c = cropRegion(img, r);
  if (c.error) { toast(c.error, "warn"); return; }
  if (addPicked({ type: "tap_image", image: c.image, x: r.x, y: r.y, w: r.w, h: r.h, timeout: TEXT_WAIT_NEW })) toast(`Đã thêm bước: bấm vào vùng ảnh ${r.w}×${r.h}`, "ok");
}
function onScreenCancel() { DRAG = null; $("#screen-sel").hidden = true; }

function onScreenClick(e) {
  if (DRAG_DONE) { DRAG_DONE = false; return; }           // cú «click» này là phần đuôi của một lần kéo khung
  if (!$("#pick-mode").checked || !SCREEN.w) return;
  const img = $("#screen"), rect = img.getBoundingClientRect();
  const x = Math.round((e.clientX - rect.left) / rect.width * SCREEN.w);
  const y = Math.round((e.clientY - rect.top) / rect.height * SCREEN.h);
  if (addPicked({ type: "tap", x, y })) toast(`Đã thêm bước: bấm tại (${x}, ${y})`, "ok");
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
