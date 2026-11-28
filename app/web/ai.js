// ai.js — trang «Kết nối AI»: cầu nối MCP cho AI + dòng lệnh `farm`.
// Dùng chung các hàm của core.js: $, $$, esc, API, toast, busy, copyText.

let AI_INFO = null;

async function loadAI() {
  const box = $("#ai-body");
  if (!box) return;
  try {
    AI_INFO = await API().ai_info();
  } catch (e) {
    box.innerHTML = `<div class="alert alert-danger mb-0">Không lấy được trạng thái cầu nối AI.</div>`;
    return;
  }
  const dot = $("#nav-ai-state");
  if (dot) {
    dot.textContent = AI_INFO.running ? "bật" : "tắt";
    dot.className = "badge rounded-pill ms-auto " + (AI_INFO.running ? "bg-label-success" : "bg-label-secondary");
  }
  renderAI();
}

function aiCode(text, id) {
  return `<div class="ai-code"><pre class="mono mb-0" id="${id}">${esc(text)}</pre>
    <button class="btn btn-sm btn-label-secondary ai-copy" data-copy="${id}" title="Copy"><i class="ti tabler-copy"></i></button></div>`;
}

function renderAI() {
  const box = $("#ai-body");
  const i = AI_INFO || {};
  const on = !!i.running;
  const badge = on
    ? `<span class="badge bg-label-success"><i class="ti tabler-plug-connected me-1"></i>Đang bật · cổng ${esc(i.port)}</span>`
    : (i.error ? `<span class="badge bg-label-danger">Lỗi: ${esc(i.error)}</span>` : `<span class="badge bg-label-secondary">Đang tắt</span>`);
  const active = (i.active || []).length
    ? `<span class="badge bg-label-warning ms-2"><i class="ti tabler-robot me-1"></i>AI/CLI đang điều khiển: ${esc(i.active.join(", "))}</span>` : "";
  const masked = i.token ? esc(i.token.slice(0, 6) + "…" + i.token.slice(-4)) : "—";
  const groups = [["Xem", t => t.read_only], ["Điều khiển máy", t => !t.read_only && !["start_run", "stop_run", "rescan_boards"].includes(t.name)],
                  ["Chạy / dừng", t => ["start_run", "stop_run", "rescan_boards"].includes(t.name)]];
  const tools = groups.map(([title, pick]) => {
    const rows = (i.tools || []).filter(pick).map(t =>
      `<tr><td class="mono text-nowrap">farm ${esc(t.cli)}</td><td>${esc(t.help)}</td><td class="mono text-body-secondary text-nowrap">${esc(t.name)}</td></tr>`).join("");
    return rows ? `<tr class="table-light"><th colspan="3" class="small text-uppercase">${esc(title)}</th></tr>${rows}` : "";
  }).join("");
  const farm = i.farm || "./farm";

  box.innerHTML = `
    <div class="card mb-4">
      <div class="card-body d-flex flex-wrap align-items-center justify-content-between gap-3">
        <div>
          <div class="d-flex align-items-center flex-wrap gap-1">${badge}${active}</div>
          <div class="api-note mt-2">Khi bật, một AI (Claude Code, Claude Desktop, Cursor…) hoặc lệnh <span class="mono">farm</span> có thể
            <b>đọc màn hình iPhone</b> (ảnh + chữ kèm toạ độ) và <b>bấm, gõ, vuốt, chạy/dừng nhóm</b> thông qua app này.
            Chỉ nhận kết nối từ chính máy tính này.</div>
        </div>
        <div class="form-check form-switch m-0">
          <input class="form-check-input" type="checkbox" id="ai-enabled" ${i.enabled ? "checked" : ""}>
          <label class="form-check-label" for="ai-enabled">Cho phép AI / dòng lệnh điều khiển</label>
        </div>
      </div>
    </div>

    <div class="row g-4 mb-4">
      <div class="col-xl-6">
        <div class="card h-100">
          <h5 class="card-header"><i class="ti tabler-sparkles me-1"></i>Cách 1 — Claude Code</h5>
          <div class="card-body">
            <p class="api-note">Mở Claude Code ngay trong thư mục dự án này rồi bấm <b>đồng ý</b> khi được hỏi về máy chủ
              <span class="mono">iphone-farm</span> (đã khai sẵn trong <span class="mono">.mcp.json</span>). Hoặc chạy một lần:</p>
            ${aiCode(i.claude_code || "", "ai-cmd")}
            <p class="api-note mt-3 mb-0">Sau đó nói với AI, ví dụ: <i>«xem màn hình máy iPhoneFarm-01 rồi mở app Cài đặt»</i>.</p>
          </div>
        </div>
      </div>
      <div class="col-xl-6">
        <div class="card h-100">
          <h5 class="card-header"><i class="ti tabler-robot me-1"></i>Cách 2 — Claude Desktop, Cursor, client MCP khác</h5>
          <div class="card-body">
            <p class="api-note">Dán đoạn này vào tệp cấu hình MCP của ứng dụng đó:</p>
            ${aiCode(i.json || "", "ai-json")}
          </div>
        </div>
      </div>
      <div class="col-xl-6">
        <div class="card h-100">
          <h5 class="card-header"><i class="ti tabler-plug-connected me-1"></i>Cách 3 — Nối thẳng qua HTTP</h5>
          <div class="card-body">
            <p class="api-note">Cho client hỗ trợ MCP qua HTTP. Chỉ dùng được khi app đang mở và cầu nối đang bật.</p>
            <dl class="ai-kv mb-3">
              <dt>Địa chỉ</dt><dd><span class="mono" id="ai-url">${esc(i.url || "— (đang tắt)")}</span>
                ${i.url ? `<button class="btn btn-sm btn-icon btn-text-secondary ai-copy" data-copy="ai-url" title="Copy"><i class="ti tabler-copy"></i></button>` : ""}</dd>
              <dt>Khoá</dt><dd><span class="mono">${masked}</span>
                ${i.token ? `<button class="btn btn-sm btn-icon btn-text-secondary" id="ai-copy-token" title="Copy khoá đầy đủ"><i class="ti tabler-copy"></i></button>` : ""}
                <button class="btn btn-sm btn-label-secondary ms-2" id="ai-renew"><i class="ti tabler-key me-1"></i>Đổi khoá</button></dd>
              <dt>Tiêu đề</dt><dd class="mono">Authorization: Bearer &lt;khoá&gt;</dd>
            </dl>
            <div class="api-note mb-0"><i class="ti tabler-shield-lock me-1"></i>Ai có khoá này là điều khiển được máy — đừng chia sẻ. Nghi lộ thì bấm «Đổi khoá».</div>
          </div>
        </div>
      </div>
      <div class="col-xl-6">
        <div class="card h-100">
          <h5 class="card-header"><i class="ti tabler-terminal-2 me-1"></i>Dòng lệnh</h5>
          <div class="card-body">
            <p class="api-note">Điều khiển bằng lệnh trong terminal (app đang mở thì lệnh do app thực hiện):</p>
            ${aiCode([farm + " devices", farm + " screen iPhoneFarm-01", farm + " tap iPhoneFarm-01 --text \"Cài đặt\"",
                      farm + " swipe iPhoneFarm-01 left", farm + " status"].join("\n"), "ai-cli")}
            <p class="api-note mt-3 mb-0">Thêm <span class="mono">--json</span> để lấy kết quả cho script; <span class="mono">${esc(farm)} --help</span> để xem mọi lệnh.</p>
          </div>
        </div>
      </div>
    </div>

    <div class="card mb-4">
      <h5 class="card-header">AI và dòng lệnh làm được gì</h5>
      <div class="table-responsive">
        <table class="table table-sm mb-0"><thead><tr><th>Lệnh</th><th>Việc</th><th>Tên công cụ MCP</th></tr></thead><tbody>${tools}</tbody></table>
      </div>
      <div class="card-body pt-3">
        <div class="api-note mb-0">
          • Máy <b>đang chạy kịch bản / đang nhận đơn</b> thì AI không chen vào bấm được — phải dừng máy đó trước. Máy đang làm <b>đơn của khách</b>
            thì AI cũng không xem được màn hình (tránh lộ tài khoản / mã OTP của khách); xem tiến độ bằng <span class="mono">farm status</span>.<br>
          • Máy <b>dừng chờ đối soát</b> được giữ nguyên màn hình: AI không được điều khiển cho tới khi bạn bấm Dừng / Chạy lại cho máy đó.<br>
          • Mọi cú bấm đều đo vị trí con trỏ trên ảnh chụp rồi mới bấm; con trỏ không tới nơi thì không bấm.<br>
          • «Chạy nhóm» ở chế độ nhận đơn (API) là <b>nạp thật</b> — chỉ để AI làm khi bạn thật sự muốn.
        </div>
      </div>
    </div>`;

  $$(".ai-copy", box).forEach(b => b.onclick = () => copyText($("#" + b.dataset.copy).textContent));
  const ct = $("#ai-copy-token");
  if (ct) ct.onclick = () => copyText(i.token);
  $("#ai-enabled").onchange = async (e) => {
    e.target.disabled = true;
    try {
      AI_INFO = await API().ai_set_enabled(e.target.checked);
      toast(AI_INFO.running ? "Đã bật cầu nối AI" : (AI_INFO.error ? "Không bật được: " + AI_INFO.error : "Đã tắt cầu nối AI"), AI_INFO.error ? "bad" : "ok");
    } catch (err) { toast("Không đổi được trạng thái cầu nối", "bad"); }
    loadAI();
  };
  $("#ai-renew").onclick = async (e) => {
    if (!confirm("Đổi khoá? Mọi client đang nối thẳng qua HTTP bằng khoá cũ sẽ phải cấu hình lại (Cách 1 và 2 không bị ảnh hưởng).")) return;
    busy(e.currentTarget, true);
    try { AI_INFO = await API().ai_renew_token(); toast("Đã đổi khoá", "ok"); }
    catch (err) { toast("Không đổi được khoá", "bad"); }
    renderAI();
  };
}
