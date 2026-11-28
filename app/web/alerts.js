// alerts.js — trang «Thông báo & AI»: Telegram báo cho admin + nhà cung cấp AI xử lý màn hình lạ.
// Dùng chung các hàm của app.js: $, $$, esc, API, toast, busy, loadTelegram, loadAiScreen (app.js gọi alertsBadge lúc mở app + mỗi 30 giây).
// Mã bot / API key KHÔNG BAO GIỜ được trả về trang: ô để trống = giữ cái đang lưu.

let TG_CFG = null, AIP_CFG = null, TG_CHATS = null;

const AIP_INFO = {
  anthropic: { name: "Anthropic (Claude)", keyUrl: "console.anthropic.com → API Keys", keyPh: "sk-ant-…",
               urlHint: "Để trống = máy chủ chính thức. Máy chủ riêng: ghi địa chỉ gốc, KHÔNG thêm /v1." },
  openai: { name: "OpenAI / máy chủ tương thích OpenAI", keyUrl: "platform.openai.com → API keys", keyPh: "sk-…",
            urlHint: "Để trống = OpenAI. Máy chủ tương thích (LM Studio, Ollama, OpenRouter…): ghi địa chỉ, thường kết thúc bằng /v1; máy chủ không cần key thì để trống ô key." },
};

async function loadAlerts() {
  try { TG_CFG = await API().telegram_get(); } catch (e) { TG_CFG = null; }
  try { AIP_CFG = await API().ai_screen_get(); } catch (e) { AIP_CFG = null; }
  renderTelegram();
  renderAiProviders();
  alertsNavState();
}

// Nhãn ở menu: đọc lại cấu hình (không cần mở trang) rồi vẽ nhãn.
async function alertsBadge() {
  try { TG_CFG = await API().telegram_get(); } catch (e) {}
  try { AIP_CFG = await API().ai_screen_get(); } catch (e) {}
  alertsNavState();
}

function alertsNavState() {
  const b = $("#nav-alerts-state");
  if (!b) return;
  const tg = TG_CFG && TG_CFG.has_token && TG_CFG.chat, ai = AIP_CFG && AIP_CFG.usable;
  b.textContent = (tg ? "TG" : "") + (tg && ai ? " · " : "") + (ai ? "AI" : "") || "chưa cài";
  b.className = "badge rounded-pill ms-auto " + (tg || ai ? "bg-label-success" : "bg-label-secondary");
}

/* ---------------- Telegram ---------------- */
function renderTelegram() {
  const box = $("#tg-body");
  if (!box) return;
  const c = TG_CFG;
  if (!c) { box.innerHTML = `<div class="alert alert-danger mb-0">Không đọc được cấu hình Telegram.</div>`; return; }
  const ready = c.has_token && c.chat;
  const badge = !ready ? `<span class="badge bg-label-secondary">Chưa cài</span>`
    : c.last_error ? `<span class="badge bg-label-danger" title="${esc(c.last_error)}">Lần gửi gần nhất lỗi</span>`
    : `<span class="badge bg-label-success">Đang bật · đã gửi ${esc(c.sent)} tin từ lúc mở app</span>`;
  const on = new Set(c.events || []);
  const chats = TG_CHATS === null ? "" : !TG_CHATS.length
    ? `<div class="api-note mt-2">Chưa thấy chat nào. Trong nhóm, nhắn <span class="mono">/start@tên_bot</span> (bot không đọc tin thường trong nhóm),
         hoặc gỡ bot ra rồi kéo vào lại; chat riêng thì nhắn <span class="mono">/start</span> cho bot. Sau đó bấm «Tìm chat» lại.</div>`
    : `<div class="tg-chats mt-2" role="radiogroup" aria-label="Chọn chat nhận thông báo">${TG_CHATS.map(ch => `
        <label class="tg-chat"><input type="radio" name="tg-chat-pick" value="${esc(ch.id)}" ${ch.id === ($("#tg-chat") || {}).value ? "checked" : ""}>
          <span><b>${esc(ch.title || "(không tên)")}</b><small class="text-muted"> · ${esc({ private: "người", group: "nhóm", supergroup: "nhóm", channel: "kênh" }[ch.type] || ch.type)} · ${esc(ch.id)}</small></span>
        </label>`).join("")}</div>`;
  box.innerHTML = `
    <div class="d-flex align-items-center justify-content-between gap-2 mb-3">
      <h5 class="mb-0"><i class="ti tabler-brand-telegram me-1"></i>Telegram</h5>${badge}
    </div>
    <ol class="tg-steps">
      <li>Nhắn <b>@BotFather</b> trên Telegram, gõ <span class="mono">/newbot</span>, đặt tên → dán <b>mã bot</b> vào ô dưới.</li>
      <li><b>Kéo bot vào nhóm</b> của admin (hoặc nhắn <span class="mono">/start</span> cho bot). Bot mặc định không đọc tin thường trong nhóm:
        nếu nhóm không hiện ra, nhắn <span class="mono">/start@tên_bot</span> trong nhóm (hoặc gỡ bot ra rồi thêm lại).</li>
      <li>Bấm <b>«Tìm chat»</b> rồi chọn nhóm → <b>Lưu</b>. Tool tự gửi một tin thử.</li>
    </ol>
    <label class="form-label" for="tg-token">Mã bot</label>
    <div class="input-group">
      <input type="password" class="form-control" id="tg-token" autocomplete="off" spellcheck="false"
             placeholder="${c.has_token ? `để trống = giữ mã đang lưu (${esc(c.token_hint)})` : "123456789:AA…"}">
      <button class="btn btn-label-primary" id="tg-find" type="button"><i class="ti tabler-search me-1"></i>Tìm chat</button>
    </div>
    ${chats}
    <label class="form-label mt-3" for="tg-chat">Chat id nhận thông báo</label>
    <input class="form-control" id="tg-chat" value="${esc(c.chat || "")}" placeholder="vd -1001234567890 (nhóm) · 123456789 (người) · @ten_kenh" spellcheck="false">
    <div class="form-label mt-3 mb-1">Báo khi</div>
    ${(c.all_events || []).map(ev => `
      <div class="form-check"><input class="form-check-input tg-ev" type="checkbox" id="tg-ev-${esc(ev.key)}" value="${esc(ev.key)}" ${on.has(ev.key) ? "checked" : ""}>
        <label class="form-check-label" for="tg-ev-${esc(ev.key)}">${esc(ev.label)}</label></div>`).join("")}
    <div class="d-flex flex-wrap gap-2 mt-4">
      <button class="btn btn-primary" id="tg-save"><i class="ti tabler-device-floppy me-1"></i>Lưu</button>
      <button class="btn btn-label-secondary" id="tg-test" ${ready ? "" : "disabled"}><i class="ti tabler-send me-1"></i>Gửi thử</button>
    </div>
    ${c.last_error ? `<div class="text-danger small mt-2">Lỗi gần nhất: ${esc(c.last_error)}</div>` : ""}`;
  $$('input[name="tg-chat-pick"]', box).forEach(r => r.onchange = () => { $("#tg-chat").value = r.value; });
  $("#tg-find").onclick = (e) => tgFindChats(e.currentTarget);
  $("#tg-save").onclick = (e) => tgSave(e.currentTarget);
  $("#tg-test").onclick = (e) => tgTest(e.currentTarget);
}

async function tgFindChats(btn) {
  const token = $("#tg-token").value.trim(), chat = $("#tg-chat").value;
  busy(btn, true);
  try {
    const r = await API().telegram_chats(token);
    if (!r || !r.ok) { toast("Không tìm được: " + ((r && r.error) || "?"), "bad"); busy(btn, false); return; }
    TG_CHATS = r.chats || [];
    if (TG_CHATS.length === 1 && !chat) chat_pick(TG_CHATS[0].id);
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  const keepTok = $("#tg-token").value, keepChat = $("#tg-chat").value, keepEv = $$(".tg-ev").map(x => [x.value, x.checked]);
  renderTelegram();                                     // vẽ lại danh sách chat, giữ những gì người dùng đang gõ / chọn
  $("#tg-token").value = keepTok; $("#tg-chat").value = keepChat;
  keepEv.forEach(([k, v]) => { const x = $("#tg-ev-" + k); if (x) x.checked = v; });
  const sel = $(`input[name="tg-chat-pick"][value="${CSS.escape(keepChat)}"]`); if (sel) sel.checked = true;
  function chat_pick(id) { $("#tg-chat").value = id; }
}

async function tgSave(btn) {
  const events = $$(".tg-ev").filter(x => x.checked).map(x => x.value);
  busy(btn, true);
  try {
    const res = await API().telegram_save($("#tg-token").value.trim(), $("#tg-chat").value.trim(), TG_CFG && TG_CFG.all_events ? events : null);
    if (!res || !res.ok) { toast("Chưa lưu: " + ((res && res.error) || "?"), "bad"); busy(btn, false); return; }
    if (res.has_token && res.chat) {
      const t = await API().telegram_test();
      if (t && t.ok) toast("Đã lưu — đã gửi tin thử tới Telegram", "ok");
      else toast("Đã lưu nhưng gửi thử KHÔNG được: " + ((t && t.error) || "?"), "bad");
    } else toast("Đã lưu — còn thiếu " + (res.has_token ? "chat id" : "mã bot") + " nên chưa gửi thông báo được", "warn");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  try { TG_CFG = await API().telegram_get(); } catch (e) {}
  renderTelegram();                                     // chỉ vẽ lại khung Telegram — không xoá những gì đang gõ dở ở khung AI
  alertsNavState(); loadTelegram();
}

async function tgTest(btn) {
  busy(btn, true);
  try {
    const t = await API().telegram_test();
    toast(t && t.ok ? "Đã gửi tin thử tới Telegram" : "Gửi thử KHÔNG được: " + ((t && t.error) || "?"), t && t.ok ? "ok" : "bad");
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
}

/* ---------------- Nhà cung cấp AI ---------------- */
function renderAiProviders() {
  const box = $("#aip-body");
  if (!box) return;
  const c = AIP_CFG;
  if (!c) { box.innerHTML = `<div class="alert alert-danger mb-0">Không đọc được cấu hình AI.</div>`; return; }
  const ro = c.editable === false;
  const badge = !c.enabled ? `<span class="badge bg-label-secondary">Đang tắt</span>`
    : c.usable ? `<span class="badge bg-label-success">Đang dùng · ${esc(AIP_INFO[c.provider] ? AIP_INFO[c.provider].name.split(" ")[0] : c.provider)} · ${esc(c.model)}</span>`
    : `<span class="badge bg-label-warning">Chưa có API key</span>`;
  const provs = c.providers || {};
  const block = (p) => {
    const e = provs[p] || {}, inf = AIP_INFO[p];
    return `
    <div class="aip-prov ${c.provider === p ? "is-active" : ""}" data-prov="${p}">
      <label class="aip-head">
        <input type="radio" name="aip-active" value="${p}" ${c.provider === p ? "checked" : ""} ${ro ? "disabled" : ""}>
        <b>${esc(inf.name)}</b>
        ${e.has_key ? `<span class="badge bg-label-success ms-auto">có key ${esc(e.key_hint)}</span>` : `<span class="badge bg-label-secondary ms-auto">chưa có key</span>`}
      </label>
      <div class="aip-fields">
        <label class="form-label" for="aip-${p}-key">API key <small class="text-muted">(${esc(inf.keyUrl)})</small></label>
        <input type="password" class="form-control" id="aip-${p}-key" autocomplete="off" spellcheck="false" ${ro ? "disabled" : ""}
               placeholder="${e.has_key ? `để trống = giữ key đang lưu (${esc(e.key_hint)})` : esc(inf.keyPh)}">
        <label class="form-label mt-2" for="aip-${p}-model">Model</label>
        <input class="form-control" id="aip-${p}-model" value="${esc(e.model || "")}" placeholder="để trống = ${esc(e.default_model)}" spellcheck="false" ${ro ? "disabled" : ""}>
        <label class="form-label mt-2" for="aip-${p}-url">Địa chỉ máy chủ riêng <small class="text-muted">(tuỳ chọn)</small></label>
        <input class="form-control" id="aip-${p}-url" value="${esc(e.base_url || "")}" placeholder="để trống" spellcheck="false" ${ro ? "disabled" : ""}>
        <div class="form-text">${esc(inf.urlHint)}</div>
      </div>
    </div>`;
  };
  box.innerHTML = `
    <div class="d-flex align-items-center justify-content-between gap-2 mb-3">
      <h5 class="mb-0"><i class="ti tabler-sparkles me-1"></i>AI xử lý màn hình lạ</h5>${badge}
    </div>
    <div class="api-note mb-3">Màn hình khác ảnh mẫu của bước → tool gửi ảnh màn hình (kể cả lúc làm đơn của khách) cho AI hỏi có phải quảng cáo /
      hộp thông báo không và nút nào đóng được; tool bấm rồi so lại. Không xử lý được → máy tạm dừng + báo Telegram.
      AI <b>không bao giờ</b> được bấm nút mua / thanh toán / xác nhận / đăng nhập, và không hỏi AI trong giai đoạn mua.
      Tốn tiền theo lần hỏi (chỉ hỏi khi gặp màn hình lạ).</div>
    ${ro ? `<div class="alert alert-warning py-2">Bản web chỉ XEM được. Cấu hình AI chỉ đổi được ở app dạng cửa sổ (<span class="mono">run.command</span> / <span class="mono">run.bat</span>).</div>` : ""}
    <div class="form-check form-switch mb-3">
      <input class="form-check-input" type="checkbox" id="aip-enabled" ${c.enabled ? "checked" : ""} ${ro ? "disabled" : ""}>
      <label class="form-check-label" for="aip-enabled">Dùng AI trước khi tạm dừng máy</label>
    </div>
    <div class="form-label mb-1" id="aip-active-label">Nhà cung cấp đang dùng <small class="text-muted">— mỗi nhà cung cấp giữ key riêng</small></div>
    <div role="radiogroup" aria-labelledby="aip-active-label">${block("anthropic")}${block("openai")}</div>
    <div class="d-flex flex-wrap gap-2 mt-4">
      <button class="btn btn-primary" id="aip-save" ${ro ? "disabled" : ""}><i class="ti tabler-device-floppy me-1"></i>Lưu</button>
      <button class="btn btn-label-secondary" id="aip-test" ${ro || !c.usable ? "disabled" : ""} title="Hỏi AI một ảnh quảng cáo vẽ sẵn (tốn một lần hỏi)"><i class="ti tabler-player-play me-1"></i>Thử hỏi AI</button>
    </div>
    <div id="aip-test-out" class="small mt-2"></div>`;
  $$('input[name="aip-active"]', box).forEach(r => r.onchange = () => $$(".aip-prov", box).forEach(b => b.classList.toggle("is-active", b.dataset.prov === r.value)));
  $("#aip-save").onclick = (e) => aiProvidersSave(e.currentTarget);
  $("#aip-test").onclick = (e) => aiProvidersTest(e.currentTarget);
}

async function aiProvidersSave(btn) {
  const pick = $('input[name="aip-active"]:checked');
  const cfg = { enabled: $("#aip-enabled").checked, active: pick ? pick.value : AIP_CFG.provider, providers: {} };
  Object.keys(AIP_INFO).forEach(p => {
    cfg.providers[p] = { key: $(`#aip-${p}-key`).value.trim(), model: $(`#aip-${p}-model`).value.trim(), base_url: $(`#aip-${p}-url`).value.trim() };
  });
  busy(btn, true);
  try {
    const res = await API().ai_settings_save(cfg);
    if (!res || !res.ok) { toast("Chưa lưu: " + ((res && res.error) || "?"), "bad"); busy(btn, false); return; }
    AIP_CFG = res;
    renderAiProviders();
    if (!res.enabled) toast("Đã lưu — đang TẮT AI (màn hình lạ là tạm dừng chờ admin luôn)", "warn");
    else if (!res.usable) toast("Đã lưu — nhà cung cấp đang dùng chưa có API key nên chưa dùng AI", "warn");
    else { toast("Đã lưu — đang thử hỏi AI một ảnh mẫu…", ""); await aiProvidersTest($("#aip-test")); }
  } catch (e) { toast("Lỗi: " + e, "bad"); }
  busy(btn, false);
  alertsNavState(); loadAiScreen();
}

async function aiProvidersTest(btn) {
  const out = $("#aip-test-out");
  busy(btn, true);
  if (out) out.textContent = "Đang hỏi AI…";
  try {
    const t = await API().ai_screen_test();
    if (t && t.ok) {
      const kind = { ad: "quảng cáo", popup: "hộp thông báo", loading: "đang tải", expected: "giống ảnh mẫu", other: "khác" }[t.kind] || t.kind;
      if (out) out.innerHTML = `<span class="text-success"><i class="ti tabler-check"></i> AI trả lời sau ${esc(t.secs)} giây (${esc(t.model)}): <b>${esc(kind)}</b>${t.close ? ` — nút «${esc(t.close)}»` : ""}${t.reason ? ` · ${esc(t.reason)}` : ""}</span>`;
    } else if (out) out.innerHTML = `<span class="text-danger"><i class="ti tabler-x"></i> Hỏi AI không được: ${esc((t && t.error) || "?")}</span>`;
  } catch (e) { if (out) out.innerHTML = `<span class="text-danger">Lỗi: ${esc(e)}</span>`; }
  busy(btn, false);
}

document.addEventListener("DOMContentLoaded", () => {
  const b = $("#btn-alerts-refresh");
  if (b) b.onclick = loadAlerts;
});
