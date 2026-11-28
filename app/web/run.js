// run.js — CHẠY / DỪNG máy, dùng chung cho trang Thiết bị, trang nhóm và trình sửa kịch bản: bộ nút của một máy (tạm dừng, tiếp tục, dừng,
// «Đã kiểm tra xong»), dừng tất cả, chạy lại một máy, nhật ký chạy do backend đẩy về, và nhịp hỏi trạng thái chạy mỗi 2,5 giây (pollStatus).

// «Chạy 1 lần» / «Lặp lại ∞» / «Lặp lại 5 vòng»
function runLabel(sc) {
  if (sc.mode === "orders") return `nhận đơn từ pool «${(sc.orders && sc.orders.pool) || "chưa chọn"}»`;
  return sc.mode === "loop" ? (sc.loops > 0 ? `lặp lại ${sc.loops} vòng` : "lặp lại ∞") : "chạy 1 lần";
}
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
    // phải hiện cả «Tiếp tục», không thì «Chạy lại» của kịch bản nhận đơn bị từ chối mà không có nút nào để gỡ.
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

// Máy đang dừng chờ kiểm tra có «Chạy lại» được bằng kịch bản `sc` của nhóm `group` không: chỉ khi nó dừng sau một đơn của CHÍNH kịch bản nhận đơn đó.
function canRerunHeld(st, group, sc) {
  return !!(st && !st.running && st.hold && group && sc && sc.mode === "orders" && st.group_id === group.id && st.script_id === sc.id);
}
async function runMachine(name, scriptId) {       // chạy kịch bản `scriptId` của nhóm đang mở trên MỘT máy («Chạy lại» máy đang dừng chờ kiểm tra)
  if (!GROUP) return;
  if (!(await saveGroupSilent())) { toast("Lỗi lưu nhóm — chưa chạy", "bad"); return; }
  try {
    const r = await API().machine_run(GROUP.id, name, scriptId);
    applyAdopted(r);
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

// nhật ký các máy đang nhận đơn: backend đẩy từng dòng về đây
let RUNLOG_LOADED = false;
function showRunLog(e) {
  log(`${e.t} [${e.name}] ${e.text}`, e.kind === "ok" ? "ok" : e.kind === "bad" ? "bad" : "");
}
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
  if (active && active.id === "view-flows") paintProgress();     // tiến độ từng bước: mỗi nhịp, chỉ đổi lớp CSS / dải tiến độ (không vẽ lại lộ trình)
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
