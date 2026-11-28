// groups.js — trang «Nhóm & Kịch bản»: danh sách nhóm, trang của một nhóm (máy trong nhóm + danh sách kịch bản), mở / đóng trình sửa kịch bản,
// «Chạy trên máy» + tiến độ từng bước của máy đang chạy, địa chỉ trang (#flows/<nhóm>/<kịch bản>), nạp một nhóm vào trình sửa, tạo / lưu / xoá nhóm.
// Bước của kịch bản: steps.js, stepedit.js, screen.js · phần riêng của kịch bản nhận đơn: orders.js · bộ nút chạy / dừng một máy: run.js.

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
function groupScriptLabel(g) {
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
// trạng thái có thể sửa của nhóm đang mở: tên nhóm + mọi kịch bản (bước, cách chạy, cấu hình nhận đơn). Máy trong nhóm lưu ngay khi thêm/bớt nên không tính.
function groupState() {
  if (!GROUP) return "";
  return JSON.stringify([$("#group-name").value.trim(), GROUP.scripts]);
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
function currentHash() { return "#flows/" + (GROUP ? GROUP.id : "") + (GROUP_SUB === "script" ? "/" + EDIT_SID : ""); }
let SCRIPT_SEL = {};                   // máy được tích «chạy trên máy» của kịch bản đang mở (giữ qua các lần vẽ lại / lưu)
let SCRIPT_SEL_FOR = "";               // lựa chọn trên thuộc kịch bản nào ("<nhóm>/<kịch bản>")
function setGroupSub(sub) {
  GROUP_SUB = sub;
  $("#group-home").hidden = sub !== "home";
  $("#script-editor").hidden = sub !== "script";
  $("#group-config").hidden = sub === "script";          // đang sửa kịch bản: ẩn khung cấu hình nhóm cho gọn
  $("#group-head").hidden = sub === "script";            // …và hàng đầu trang của nhóm: trình sửa có hàng riêng «‹ nhóm / tên kịch bản … Lưu»
  closePalette();
  $("#log-box").open = sub !== "script";                 // trang nhóm: nhật ký mở sẵn (đang theo dõi máy chạy); trình sửa: gập, dòng mới nhất ở tiêu đề
  if (sub === "script") {
    $("#ed-group-name").textContent = GROUP.name || "Nhóm";
    const sc = currentScript();
    $("#script-name").value = sc ? sc.name : "";
    $("#script-run-card").hidden = !sc;
    if (sc) {
      $("#script-mode").value = sc.mode; $("#script-loops").value = sc.loops;
      $("#script-loops-wrap").hidden = sc.mode !== "loop";
      renderOrdersOpts(sc);
      const key = GROUP.id + "/" + sc.id;
      if (SCRIPT_SEL_FOR !== key) { SCRIPT_SEL = {}; SCRIPT_SEL_FOR = key; }     // kịch bản khác → mặc định tích hết; cùng kịch bản → giữ lựa chọn của người dùng
      renderScriptMachines();
      if (sc.mode === "orders") { GW.ok === null ? loadGateway() : loadGwPool(); }   // kịch bản nhận đơn: cần danh sách pool + cấu hình pool đang chọn
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
    // Máy đang DỪNG CHỜ KIỂM TRA sau một đơn của CHÍNH kịch bản nhận đơn này: «Chạy lại» được (máy tự kiểm game đã sạch rồi mới nhận đơn tiếp);
    // máy giữ vì việc khác thì chỉ có «Đã kiểm tra xong».
    const again = canRerunHeld(st, GROUP, sc);
    return `<div class="script-machine-row"><label class="script-machine ${busy ? "busy" : ""}"><input type="checkbox" data-m="${esc(n)}" ${busy ? "disabled" : (SCRIPT_SEL[n] !== false ? "checked" : "")}> ${esc(d ? (d.label || d.name) : n)} ${note}</label>
      <span class="script-machine-acts">${again ? `<button class="btn btn-sm btn-success" data-mrerun="${esc(n)}" title="Chạy lại CHÍNH kịch bản này trên máy đang dừng chờ kiểm tra: máy tự kiểm game đã đăng xuất sạch rồi mới nhận đơn tiếp">Chạy lại</button>` : ""}${runControlsHtml(n, st)}</span></div>`;
  }).join("");
  $$("input[data-m]", box).forEach(cb => cb.onchange = () => { SCRIPT_SEL[cb.dataset.m] = cb.checked; });
  $$("[data-mrerun]", box).forEach(b => b.onclick = () => {
    const n = b.dataset.mrerun, st = RUN_STATUS[n] || {};
    if (!confirmBox(`Chạy lại kịch bản «${sc.name}» trên máy ${n}?\n\nMáy đang DỪNG CHỜ KIỂM TRA: ${st.hold || "(không rõ lý do)"}\n\nChạy lại là gỡ trạng thái đó: máy tự kiểm game đã đăng xuất sạch rồi nhận ĐƠN THẬT tiếp theo của khách.`)) return;
    runMachine(n, sc.id);
  });
  bindRunControls(box);
}
async function runScript(btn) {
  const sc = currentScript();
  if (!GROUP || !sc) return;
  const names = GROUP.devices.filter(n => SCRIPT_SEL[n] !== false && !(RUN_STATUS[n] && (RUN_STATUS[n].running || RUN_STATUS[n].parked)) && !isHeld(RUN_STATUS[n]));
  if (!GROUP.devices.length) { toast("Nhóm chưa có máy nào", "warn"); return; }
  if (!names.length) { toast("Chưa chọn máy rảnh nào để chạy", "warn"); return; }
  const orders = sc.mode === "orders";
  if (!orders && !sc.steps.length) { toast("Kịch bản chưa có bước nào", "warn"); return; }
  if (orders && !confirmBox(`${names.length} máy đã chọn sẽ bắt đầu NHẬN ĐƠN THẬT của khách từ pool «${(sc.orders && sc.orders.pool) || "chưa chọn"}» và chạy kịch bản này cho từng đơn.\n\nBắt đầu nhận đơn?`)) return;
  busy(btn, true);
  const saved = await saveGroupSilent();                 // chạy đúng bản đang hiện trên màn hình
  if (!saved) { toast("Lỗi lưu nhóm — chưa chạy", "bad"); busy(btn, false); return; }
  try {
    const r = await API().group_run(GROUP.id, names, sc.id);
    applyAdopted(r);                                     // backend vừa chép bước đời cũ từ gateway ngay trước khi chạy (kể cả khi sau đó không chạy được) → trình sửa nạp lại bản đó
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

/* ---- TIẾN ĐỘ của máy chạy kịch bản (1 lần / lặp): máy đang ở bước nào, dừng ở bước nào, «Chạy tiếp từ bước N» ----
   Backend giữ tiến độ lượt chạy gần nhất của mỗi máy (run_status → prog: {n, types, iter, at, done, skip, bad, msg, next}).
   Kịch bản nhận đơn không có (không nhảy vào giữa đơn của khách) — theo dõi đơn ở trang «Theo dõi». */
function progScript() {                // kịch bản đang mở trong trình sửa nếu nó chạy 1 lần / lặp, không thì null
  const sc = (GROUP && GROUP_SUB === "script") ? currentScript() : null;
  return sc && sc.mode !== "orders" ? sc : null;
}
function progOf(n, sc) {               // trạng thái chạy của máy n nếu lượt gần nhất của nó là kịch bản sc (có tiến độ), không thì null
  const st = RUN_STATUS[n];
  return st && st.prog && GROUP && st.group_id === GROUP.id && st.script_id === sc.id ? st : null;
}
// «Dấu» của danh sách bước — tính ĐÚNG như runner.steps_sig (loại + chữ / phím / app, FNV-1a 32 bit trên đơn vị UTF-16)
function stepsSig(steps) {
  const s = steps.map(x => `${x.type}\x1f${x.text || x.name || x.app || x.keys || ""}`).join("\n");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, "0");
}
function progStepName(sc, i) {
  const s = sc.steps[i];
  return s ? `${STEP_LABEL[s.type] || s.type} ${stepText(s)}`.trim() : "";
}
function progRowHtml(n, sc, watched) {
  const st = RUN_STATUS[n], p = st.prog;
  const same = p.types === stepsSig(sc.steps) && p.n === sc.steps.length;   // kịch bản chưa bị sửa khác đi kể từ lượt chạy đó
  const N = p.n || 0;                                                  // số bước của LƯỢT CHẠY đó (kịch bản đã sửa thì có thể khác bây giờ)
  const done = (p.done || []).length, loop = st.mode === "loop" ? ` · vòng ${p.iter || 1}` : "";
  const name = `<button class="run-prog-name" data-prog-watch="${esc(n)}" title="Tô tiến độ của máy này lên các bước">${esc(monName(n))}</button>`;
  const go = (i, label) => `<button class="run-prog-step" data-prog-goto="${i}" title="Xem bước ${i + 1}">${label}</button>`;
  const bar = `<span class="run-bar" aria-hidden="true"><i style="width:${N ? Math.round(100 * Math.min(done, N) / N) : 0}%"></i></span>`;
  const idle = !st.running && !st.parked && !isHeld(st);
  let state = "", acts = "", cls = "";
  if (st.running) {
    cls = st.paused ? "warn" : "on";
    const at = p.at != null ? p.at : (st.paused && (p.next || 0) < N ? (p.next || 0) : null);   // tạm dừng GIỮA hai bước: chờ trước bước kế
    state = at != null ? `${st.paused ? (p.at != null ? "tạm dừng ở" : "tạm dừng trước") : "đang làm"} ${go(at, "bước " + (at + 1) + "/" + N)}${same ? ` <span class="run-prog-what">${esc(progStepName(sc, at))}</span>` : ""}`
                       : `đang chạy · xong ${done}/${N} bước`;
    state += loop;
  } else if (p.bad != null) {
    cls = "bad";
    state = `dừng ở ${go(p.bad, "bước " + (p.bad + 1) + "/" + N)}${p.msg ? ` <span class="run-prog-why">${esc(p.msg)}</span>` : ""}`;
    if (idle && same) acts = `<button class="btn btn-sm btn-success" data-prog-from="${esc(n)}" data-i="${p.bad}" title="Chạy lại bước lỗi rồi đi tiếp — màn hình máy phải đang ở đúng chỗ của bước này">Chạy tiếp từ bước ${p.bad + 1}</button>`
      + (p.bad + 1 < N ? `<button class="btn btn-sm btn-label-secondary" data-prog-from="${esc(n)}" data-i="${p.bad + 1}" title="Bạn đã làm tay bước ${p.bad + 1} trên máy: bỏ qua nó, chạy từ bước sau">Bỏ qua, chạy từ bước ${p.bad + 2}</button>` : "")
      + `<button class="btn btn-sm btn-label-secondary" data-prog-from="${esc(n)}" data-i="0">Chạy lại từ đầu</button>`;
  } else if ((p.next || 0) < N) {
    cls = "mut";
    state = `đã dừng trước ${go(p.next || 0, "bước " + ((p.next || 0) + 1) + "/" + N)} · xong ${done} bước`;
    if (idle && same) acts = `<button class="btn btn-sm btn-success" data-prog-from="${esc(n)}" data-i="${p.next || 0}">Chạy tiếp từ bước ${(p.next || 0) + 1}</button>`;
  } else {
    cls = "ok";
    state = `chạy xong ${N}/${N} bước${(p.skip || []).length ? ` (${p.skip.length} bước «bỏ qua nếu lỗi» bị trượt)` : ""}`;
  }
  if (!same) state += ` <span class="run-prog-why">— kịch bản đã sửa sau lượt chạy này, số bước có thể lệch (dùng nút «Chạy từ bước này» ở từng bước)</span>`;
  else if (!idle && !st.running) state += ` <span class="run-prog-why">— máy đang dừng / chờ kiểm tra, xử lý ở dải máy phía trên</span>`;
  return `<div class="run-prog-row ${cls}${watched ? " watched" : ""}" data-row="${esc(n)}"><div class="run-prog-main">${name}<span class="run-prog-state">${state}</span>${bar}</div>${acts ? `<div class="run-prog-acts">${acts}</div>` : ""}</div>`;
}
// Gọi sau mỗi lần vẽ lộ trình và mỗi nhịp hỏi trạng thái: chỉ đổi lớp CSS của các trạm (không vẽ lại lộ trình → không mất chỗ đang sửa).
function paintProgress() {
  const box = $("#run-prog"), ol = $("#steps");
  if (!box || !ol) return;
  const sc = GROUP_PAGE === "detail" ? progScript() : null;
  const names = sc ? GROUP.devices.filter(n => progOf(n, sc)) : [];
  const watch = names.includes(SEL) ? SEL : (names.find(n => RUN_STATUS[n].running) || names[0] || null);   // máy được tô lên lộ trình
  const st = watch ? RUN_STATUS[watch] : null, p = st ? st.prog : null;
  const same = !!(p && sc && p.types === stepsSig(sc.steps) && p.n === sc.steps.length);
  $$("li[data-si]", ol).forEach(li => {
    const at = p && p.at != null ? p.at : (st && st.paused ? p.next : null);       // tạm dừng giữa hai bước → tô bước sắp làm
    const i = Number(li.dataset.si), now = same && st.running && at === i;
    li.classList.toggle("run-now", now);
    li.classList.toggle("run-paused", now && !!st.paused);
    li.classList.toggle("run-bad", same && !now && p.bad === i);
    li.classList.toggle("run-done", same && !now && (p.done || []).includes(i));
    li.classList.toggle("run-skip", same && !now && (p.skip || []).includes(i));
  });
  box.hidden = !names.length;
  // vẽ lại TỪNG DÒNG khi chính dòng đó đổi: máy A đang chạy (đổi mỗi nhịp) không làm mất nút «Chạy tiếp» đang rê chuột của máy B
  const rows = new Map([...box.children].map(el => [el.dataset.row, el]));
  let prev = null;
  names.forEach(n => {
    const html = progRowHtml(n, sc, n === watch && names.length > 1);
    let el = rows.get(n);
    rows.delete(n);
    if (!el || el.dataset.sig !== html) {
      const t = document.createElement("div"); t.innerHTML = html;
      const fresh = t.firstElementChild; fresh.dataset.sig = html;
      bindProgRow(fresh, ol);
      if (el) el.replaceWith(fresh);
      el = fresh;
    }
    const want = prev ? prev.nextElementSibling : box.firstElementChild;
    if (want !== el) box.insertBefore(el, want);
    prev = el;
  });
  rows.forEach(el => box.removeChild(el));               // máy không còn tiến độ của kịch bản này
}
function bindProgRow(row, ol) {
  $$("[data-prog-from]", row).forEach(b => b.onclick = () => runFrom(b.dataset.progFrom, Number(b.dataset.i)));
  $$("[data-prog-goto]", row).forEach(b => b.onclick = () => { const li = $(`li[data-si="${b.dataset.progGoto}"]`, ol); if (li) li.scrollIntoView({ block: "center", behavior: "smooth" }); });
  $$("[data-prog-watch]", row).forEach(b => b.onclick = () => {
    const n = b.dataset.progWatch, sel = $("#flow-device");
    if (sel && [...sel.options].some(o => o.value === n)) { sel.value = n; SEL = n; paintProgress(); }
    else toast(`Máy ${monName(n)} không có trong danh sách máy ở khung màn hình (chưa thấy board) — không tô lên các bước được`, "warn");
  });
}
// Chạy kịch bản đang mở trên máy `name`, BẮT ĐẦU từ bước thứ i (0 = bước 1) — sau khi máy dừng vì lỗi, xử lý tay xong thì chạy tiếp.
async function runFrom(name, i) {
  const sc = progScript();
  if (!GROUP || !sc || !(i >= 0 && i < sc.steps.length)) return;
  const st = RUN_STATUS[name];
  if (st && (st.running || st.parked)) { toast(`Máy ${monName(name)} đang ${st.running ? "chạy" : "dừng để xử lý tay"} — dừng / bấm Tiếp tục trên máy đó trước`, "warn"); return; }
  if (isHeld(st)) { toast(`Máy ${monName(name)} đang dừng chờ kiểm tra — xác nhận «Đã kiểm tra xong» trước`, "warn"); return; }
  const N = sc.steps.length;
  if (!confirmBox(i ? `Chạy kịch bản «${sc.name}» trên máy ${monName(name)} từ bước ${i + 1}/${N}?\n\nBước ${i + 1}: ${progStepName(sc, i)}\n\nBỏ qua ${i} bước đầu — màn hình máy phải đang ở đúng chỗ của bước ${i + 1}.${sc.mode === "loop" ? `\nCác vòng sau chạy lại từ bước 1; số vòng đếm lại từ đầu${Number(sc.loops) > 0 ? ` (${Number(sc.loops)} vòng)` : ""}.` : ""}`
                    : `Chạy lại kịch bản «${sc.name}» trên máy ${monName(name)} từ bước 1?`)) return;
  if (!(await saveGroupSilent())) { toast("Lỗi lưu nhóm — chưa chạy", "bad"); return; }
  try {
    const r = await API().machine_run(GROUP.id, name, sc.id, i);
    if (r && r.ok) { log(`▶ Chạy «${GROUP.name} · ${sc.name}» trên ${name} từ bước ${i + 1}/${N}`); toast(`Máy ${monName(name)} chạy từ bước ${i + 1}`, "ok"); }
    else toast((r && r.error) || "Lỗi không rõ", "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  pollStatus();
}
// id kịch bản có thật trong nhóm đang mở không
function validSub(sub) {
  return !!(GROUP && sub && GROUP.scripts.some(x => x.id === sub));
}
// địa chỉ trên thanh trình duyệt sai (nhóm / kịch bản không có) → sửa lại cho khớp trang đang hiện, không thêm vào lịch sử
function fixHash() {
  const h = GROUP && GROUP_PAGE === "detail" ? currentHash() : "#flows";
  if (location.hash !== h) { try { history.replaceState(null, "", h); } catch (e) {} }
}
function openScript(id, push = true) {
  if (!validSub(id)) { fixHash(); return; }
  EDIT_SID = id;
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
  const n = GROUP.scripts.length;
  $("#script-count").textContent = n ? `(${n})` : "";
  $("#script-hint").textContent = "Bấm vào một kịch bản để sửa các bước, chọn cách chạy và máy chạy.";
  box.innerHTML = n ? GROUP.scripts.map(sc => {
    const on = Object.keys(RUN_STATUS).filter(m => { const st = RUN_STATUS[m]; return st && st.running && st.group_id === GROUP.id && st.script_id === sc.id; }).length;
    return `<div class="mem-row script-row" role="button" tabindex="0" data-sopen="${esc(sc.id)}">
      <div class="mem-info"><div class="mem-name">${esc(sc.name)} ${on ? `<span class="pill ok">▶ đang chạy trên ${on} máy</span>` : ""}</div>
        <div class="mem-sub">${scriptStepCount(sc) ? scriptStepCount(sc) + " bước" : "chưa có bước"} · ${esc(runLabel(sc))}</div></div>
      <div class="mem-act">
        <button class="btn btn-sm btn-label-secondary" data-sopen="${esc(sc.id)}">Sửa</button>
        <button class="btn btn-sm btn-label-secondary" data-sdel="${esc(sc.id)}" title="Xoá kịch bản">✕</button>
      </div></div>`;
  }).join("") : `<div class="text-muted small py-2">Chưa có kịch bản. Bấm <b>«Thêm kịch bản»</b> để bắt đầu.</div>`;
  const stop = (e) => e.stopPropagation();
  $$("[data-sopen]", box).forEach(b => b.onclick = (e) => { e.stopPropagation(); openScript(b.dataset.sopen); });
  $$(".script-row", box).forEach(r => r.onkeydown = (e) => { if (e.target === r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openScript(r.dataset.sopen); } });
  $$("[data-sdel]", box).forEach(b => b.onclick = (e) => { stop(e); delScript(b.dataset.sdel); });
}
async function addScript() {
  if (!GROUP) return;
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
  if (!confirmBox(`Xoá kịch bản “${sc.name}”${scriptStepCount(sc) ? ` (${scriptStepCount(sc)} bước)` : ""}?\n\nXoá ngay và không lấy lại được.`)) return;
  const backup = GROUP.scripts.slice();
  GROUP.scripts = GROUP.scripts.filter(x => x.id !== id);
  const saved = await saveGroupSilent();                     // lưu ngay (như «Thêm kịch bản»): trên màn hình sao thì trong tệp vậy
  if (!saved) { GROUP.scripts = backup; renderScripts(); toast("Lỗi lưu nhóm — chưa xoá", "bad"); return; }
  toast("Đã xoá kịch bản: " + sc.name, "ok");
  await loadGroups(GROUP.id, true);
}

// địa chỉ trang: #flows (danh sách) / #flows/<id nhóm> / #flows/<id nhóm>/<id kịch bản> — tải lại trang hoặc bấm Back vẫn đúng chỗ
async function routeFromHash() {
  const m = /^#flows(?:\/([\w-]+)(?:\/([\w-]+))?)?$/.exec(location.hash);
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

// FLOW.steps luôn TRỎ vào đúng danh sách đang sửa của kịch bản thường (kịch bản nhận đơn: giai đoạn «Đăng nhập» — mỗi giai đoạn có nút thêm bước riêng)
function bindSteps() {
  if (!GROUP) return;
  const sc = currentScript();
  PICK_TO = null;                                        // đổi kịch bản: lần bấm ảnh kế tiếp không còn chỗ chèn cũ
  FLOW.steps = sc ? (sc.mode === "orders" && sc.orders ? sc.orders.steps.login : sc.steps) : [];
  FLOW.name = sc ? sc.name : GROUP.name;
  renderSteps();
}

function selectGroup(id) {
  const g = GROUPS.find(x => x.id === id);
  if (!g) { GROUP = null; GROUP_SNAP = ""; return; }
  const sc = (g.scripts || []).map(x => {
    const mode = x.mode === "loop" || x.mode === "orders" ? x.mode : "once";
    const one = { id: x.id, name: x.name, steps: x.steps || [], mode, loops: Number.isFinite(+x.loops) ? +x.loops : (mode === "loop" ? 0 : 1) };
    if (mode === "orders" || x.orders) one.orders = normApi(x.orders);            // kịch bản nhận đơn: pool + bước từng giai đoạn của đơn
    return one;
  });
  GROUP = JSON.parse(JSON.stringify({ id: g.id, name: g.name, scripts: sc, devices: g.devices || [] }));
  if (GROUP_SUB === "script" && !currentScript()) { GROUP_SUB = "home"; EDIT_SID = null; }   // kịch bản đang sửa đã bị xoá
  FLOW = { id: GROUP.id, name: GROUP.name, steps: [] };            // tái dùng renderSteps/addStep (bindSteps trỏ vào đúng danh sách bước)
  $("#group-name").value = GROUP.name || "";
  GROUP_SNAP = groupState();                                       // chụp TRƯỚC khi vẽ: các hàm vẽ bên dưới hỏi «có thay đổi chưa lưu không» trên bản vừa nạp
  bindSteps(); renderMembers(); renderGroupAddDev(); renderDevicePicker();
  $("#group-title").textContent = GROUP.name || "Nhóm";
  $("#group-sub").textContent = `${GROUP.devices.length} máy`;
  renderScripts(); setGroupSub(GROUP_SUB);
}

async function newGroup() {
  const name = await askOne("Tạo nhóm mới", "Tên nhóm", "", "VD: iPhone 8 · iOS 16.7");
  if (name == null) return;
  try {
    const g = await API().group_save({ name: name.trim() || "Nhóm mới", devices: [] });
    toast("Đã tạo nhóm: " + g.name, "ok");
    await loadGroups();
    openGroup(g.id);                                 // vào luôn trang quản lý nhóm vừa tạo
  } catch (e) { toast("Lỗi tạo nhóm: " + e, "bad"); }
}

async function saveGroupSilent() {
  if (!GROUP) return;
  GROUP.name = $("#group-name").value.trim() || GROUP.name;
  // bước, cách chạy và cấu hình nhận đơn đã nằm sẵn trong GROUP.scripts[] (FLOW.steps và các ô nhập chỉ ghi thẳng vào đó)
  try {
    const saved = await API().group_save(GROUP);
    if (saved) {
      GROUP_SNAP = groupState();                    // đã lưu → không còn «thay đổi chưa lưu»
      // Bản vừa gửi cũ hơn một lần chép bước đời cũ từ gateway (backend chép lúc trình sửa đang bận): backend giữ lại các bước đã chép
      // → bản đã lưu khác bản đang hiện. Nạp lại ngay từ bản đã lưu để màn hình (và lần chạy kế tiếp) đúng với cái được lưu.
      const newer = (saved.scripts || []).some(s => s.orders && s.orders.gw_steps_copied && !(((GROUP.scripts.find(x => x.id === s.id) || {}).orders || {}).gw_steps_copied));
      if (newer) applyAdopted({ group: saved });
    }
    return saved;
  } catch (e) {}
}

async function saveGroup(btn) {
  if (!GROUP) return;
  busy(btn, true);
  const saved = await saveGroupSilent();
  if (saved) {
    const sc = GROUP_SUB === "script" ? currentScript() : null;
    toast(sc ? "Đã lưu kịch bản: " + sc.name : "Đã lưu nhóm: " + saved.name, "ok");
    await loadGroups(saved.id, true);
  }
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
    // Tạm dừng / Tiếp tục / Dừng / «Đã kiểm tra xong» là của MÁY — dù nó đang chạy việc của nhóm này hay nhóm khác (chạy thì vào kịch bản mà bấm)
    const acts = (ro.other ? `<span class="pill warn" title="Một máy chỉ chạy một kịch bản một lúc — đang chạy ${esc(whatRuns(stAny))}">bận ở nhóm khác</span>` : "")
               + runControlsHtml(name, stAny);
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
