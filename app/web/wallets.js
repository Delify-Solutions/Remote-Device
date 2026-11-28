/* =========================================================
   VÍ & TÀI KHOẢN APPLE của từng máy — TOOL quản lý (nguồn gốc); gateway chỉ giữ bản sao để admin xem.
   Mỗi máy: MỘT tài khoản Apple đăng nhập trên máy, MỘT loại tiền (vùng App Store), số dư + sổ nạp / trừ.
   Tiền của từng đơn (mua / tạm giữ / admin chốt / hoàn) gateway tính rồi gửi về khi đồng bộ — tool tự áp vào sổ.
   Mật khẩu Apple ID chỉ để gõ vào bảng mua của App Store: lưu MÃ HOÁ ở máy tính này, không bao giờ hiện lại / gửi đi.
   ========================================================= */
let WAL = { data: null, open: "" };

async function loadWallets() {
  const box = $("#wal-body");
  if (!box) return;
  try { WAL.data = await API().wallet_list(); }
  catch (e) { box.innerHTML = `<div class="api-note">Không tải được ví: ${esc(String(e))}</div>`; return; }
  renderWallets();
  if (WAL.open) walletLedger(WAL.open, true);
}

function walletSyncNote(sync) {
  if (!sync || sync.configured === false) return `<span class="text-muted">Chưa cấu hình gateway — ví chỉ lưu ở tool, máy nhận đơn sẽ không kiểm tiền.</span>`;
  if (sync.wallet_error) return `<span class="text-danger">${esc(sync.wallet_error)}.</span>`;
  if (sync.ok && sync.wallet_warn) return `<span class="text-danger">${esc(sync.wallet_warn)}.</span>`;
  if (sync.ok) return `<span class="text-success">Gateway đã nhận bản sao ví (đồng bộ tự động mỗi ~20 giây, đổi gì là gửi ngay).</span>`;
  return `<span class="text-warning">Chưa đồng bộ được với gateway${sync.error ? ": " + esc(sync.error) : ""}.</span>`;
}

function renderWallets() {
  const d = WAL.data || {}, box = $("#wal-body");
  const devs = d.devices || [], ws = d.wallets || {}, cur = d.currencies || [];
  const pools = Object.values(d.pools || {});
  const curNote = pools.length
    ? pools.map(p => `<b>${esc(p.name)}</b>: ${p.currencies.length ? p.currencies.map(c => `<code>${esc(c)}</code>${p.sample && p.sample[c] ? ` <span class="text-muted">(${esc(p.sample[c])})</span>` : ""}`).join(", ") : `<span class="text-warning">chưa khai loại tiền + giá gói</span>`}`).join(" · ")
    : `<span class="text-muted">Chưa đọc được pool nào trên gateway (kịch bản nhận đơn chưa chọn pool, hoặc gateway chưa cấu hình).</span>`;
  if (!devs.length) { box.innerHTML = `<div class="api-note">Chưa có máy nào — thêm máy ở trang Thiết bị.</div>`; return; }
  const rows = devs.map(dev => {
    const w = ws[dev.name];
    const name = `<div class="fw-medium">${esc(dev.label)}</div>${dev.label !== dev.name ? `<div class="small text-muted mono">${esc(dev.name)}</div>` : ""}${dev.gone ? `<span class="pill warn">máy đã gỡ khỏi tool</span>` : ""}`;
    if (!w) {
      return `<tr><td>${name}</td><td colspan="5" class="text-muted small">Chưa có ví — máy nhận đơn mà không kiểm tiền.</td>
        <td class="text-end"><button class="btn btn-sm btn-primary" data-wal-edit="${esc(dev.name)}"><i class="ti tabler-plus me-1"></i>Khai ví</button></td></tr>`;
    }
    const neg = w.available < 0;
    return `<tr class="${w.active ? "" : "text-muted"}">
      <td>${name}</td>
      <td>${esc(w.apple_account)} <span class="pill mut mono">${esc(w.currency)}</span>${w.active ? "" : ` <span class="pill mut">ngừng dùng</span>`}
        <div class="small ${w.has_password ? "text-success" : "text-warning"}">${w.has_password ? "đã lưu mật khẩu Apple ID" : "chưa lưu mật khẩu Apple ID"}</div>
        ${w.note ? `<div class="small text-muted">${esc(w.note)}</div>` : ""}</td>
      <td class="text-end text-nowrap">${esc(w.balance_text)}</td>
      <td class="text-end text-nowrap">${w.held ? esc(w.held_text) : `<span class="text-muted">—</span>`}</td>
      <td class="text-end text-nowrap fw-medium ${neg ? "text-danger" : ""}">${esc(w.available_text)}</td>
      <td class="text-nowrap"><button class="btn btn-sm btn-label-secondary" data-wal-ledger="${esc(dev.name)}"><i class="ti tabler-list-details me-1"></i>Sổ</button></td>
      <td class="text-end text-nowrap">
        <button class="btn btn-sm btn-label-primary" data-wal-money="${esc(dev.name)}" data-kind="topup"><i class="ti tabler-cash me-1"></i>Nạp tiền</button>
        <button class="btn btn-sm btn-label-secondary" data-wal-money="${esc(dev.name)}" data-kind="adjust" title="Chỉnh số dư (âm = bớt) — bắt buộc ghi lý do">Chỉnh</button>
        <button class="btn btn-sm btn-label-secondary" data-wal-edit="${esc(dev.name)}" title="Sửa tài khoản Apple / loại tiền / mật khẩu"><i class="ti tabler-pencil"></i></button>
        <button class="btn btn-sm btn-label-danger" data-wal-del="${esc(dev.name)}" title="Bỏ ví của máy (sổ vẫn giữ)"><i class="ti tabler-trash"></i></button>
      </td></tr>`;
  }).join("");
  box.innerHTML = `
    <div class="api-note mb-3">Loại tiền các pool đang bán — ${curNote}</div>
    <div class="table-responsive"><table class="table table-sm align-middle mb-2">
      <thead><tr><th>Máy</th><th>Tài khoản Apple</th><th class="text-end">Số dư</th><th class="text-end">Đang giữ</th><th class="text-end">Còn dùng được</th><th></th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="small">${walletSyncNote(d.sync)}</div>
    <div id="wal-ledger" class="mt-4"></div>`;
  $$("[data-wal-edit]", box).forEach(b => b.onclick = () => walletEdit(b.dataset.walEdit));
  $$("[data-wal-money]", box).forEach(b => b.onclick = () => walletMoney(b.dataset.walMoney, b.dataset.kind));
  $$("[data-wal-ledger]", box).forEach(b => b.onclick = () => walletLedger(b.dataset.walLedger));
  $$("[data-wal-del]", box).forEach(b => b.onclick = () => walletRemove(b.dataset.walDel));
}

async function walletEdit(name) {
  const d = WAL.data || {}, w = (d.wallets || {})[name];
  const curList = (d.currencies || []).slice();
  if (w && !curList.includes(w.currency)) curList.unshift(w.currency);
  const curField = curList.length
    ? { key: "currency", type: "select", label: "Loại tiền (vùng App Store của tài khoản Apple)", value: w ? w.currency : curList[0], options: curList.map(c => ({ value: c, label: c })) }
    : { key: "currency", label: "Loại tiền — mã ISO 3 chữ (vd JPY, CHF)", value: w ? w.currency : "", placeholder: "JPY" };
  const fields = [
    { key: "apple_account", label: "Tài khoản Apple đăng nhập trên máy", value: w ? w.apple_account : "", placeholder: "apple@example.com" },
    curField,
    { key: "password", type: "password", label: "Mật khẩu Apple ID (để tool gõ vào bảng mua — lưu mã hoá ở máy này, không gửi đi)",
      value: "", placeholder: w && w.has_password ? "Để trống = giữ mật khẩu đã lưu" : "Chưa lưu — để trống nếu chưa cần" },
    { key: "note", label: "Ghi chú (tuỳ chọn)", value: w ? w.note : "", placeholder: "vd: vùng Nhật, nạp bằng thẻ quà tặng" },
  ];
  if (w) {
    fields.push({ key: "active", type: "select", label: "Trạng thái", value: w.active ? "1" : "0",
                  options: [{ value: "1", label: "Đang dùng — máy chỉ nhận đơn ví đủ tiền" }, { value: "0", label: "Ngừng dùng — máy nhận đơn không kiểm tiền" }] });
    if (w.has_password) fields.push({ key: "clear", type: "select", label: "Mật khẩu đã lưu", value: "0", options: [{ value: "0", label: "Giữ" }, { value: "1", label: "Xoá mật khẩu đã lưu" }] });
  }
  const r = await askForm(w ? `Sửa ví — ${name}` : `Khai ví — ${name}`,
    "Máy có ví chỉ nhận đơn mà ví đủ tiền, theo giá gói ở đúng loại tiền của ví. Đổi loại tiền khi ví còn tiền thì phải chỉnh số dư về 0 trước.", fields);
  if (!r) return;
  const res = await API().wallet_save(name, { apple_account: r.apple_account, currency: r.currency, password: r.password || "", note: r.note,
                                              active: r.active === undefined ? true : r.active === "1", clear_password: r.clear === "1" });
  if (res && res.ok) { toast(w ? "Đã lưu ví" : "Đã khai ví cho " + name, "ok"); loadWallets(); }
  else toast((res && res.error) || "Không lưu được", "bad");
}

async function walletMoney(name, kind) {
  const w = ((WAL.data || {}).wallets || {})[name];
  if (!w) return;
  const eg = ["JPY", "KRW", "VND", "IDR", "CLP", "TWD", "HUF", "ISK"].includes(w.currency) ? "1500" : "63.50";
  const r = await askForm(kind === "topup" ? `Nạp tiền — ${name}` : `Chỉnh số dư — ${name}`,
    kind === "topup" ? `Ghi số tiền vừa nạp vào tài khoản Apple ${w.apple_account} (${w.currency}). Số dư hiện ${w.balance_text}.`
                     : `Âm = bớt, dương = thêm. Dùng khi đối chiếu số dư trên máy khác với sổ. Số dư hiện ${w.balance_text}.`, [
    { key: "amount", label: `Số tiền (${w.currency})`, value: "", placeholder: kind === "topup" ? eg : "-" + eg },
    { key: "note", label: kind === "topup" ? "Ghi chú (tuỳ chọn)" : "Lý do (bắt buộc)", value: "", placeholder: kind === "topup" ? "vd: thẻ quà tặng …1234" : "vd: đối chiếu số dư trên máy" },
  ]);
  if (!r) return;
  const res = kind === "topup" ? await API().wallet_topup(name, r.amount, r.note) : await API().wallet_adjust(name, r.amount, r.note);
  if (res && res.ok) { toast((kind === "topup" ? "Đã nạp — số dư " : "Đã chỉnh — số dư ") + res.wallet.balance_text, "ok"); loadWallets(); }
  else toast((res && res.error) || "Không ghi được", "bad");
}

async function walletLedger(name, keep) {
  const box = $("#wal-ledger");
  if (!box) return;
  if (WAL.open === name && !keep) { WAL.open = ""; box.innerHTML = ""; return; }
  WAL.open = name;
  let r;
  try { r = await API().wallet_ledger(name, 200); } catch (e) { box.innerHTML = `<div class="api-note">Không tải được sổ: ${esc(String(e))}</div>`; return; }
  const rows = (r && r.entries) || [];
  const t = (sec) => { try { return new Date(sec * 1000).toLocaleString("vi-VN"); } catch (e) { return ""; } };
  box.innerHTML = `<h6 class="mb-2">Sổ ví — ${esc(name)} <small class="text-muted">(mới nhất trước; «Tạm giữ» không đổi số dư, chỉ bớt phần còn dùng được)</small></h6>`
    + (rows.length ? `<div class="table-responsive"><table class="table table-sm mb-0"><thead><tr><th>Lúc</th><th>Loại</th><th class="text-end">Số dư</th><th class="text-end">Tạm giữ</th><th>Đơn</th><th>Ghi chú</th><th>Ai ghi</th></tr></thead><tbody>`
      + rows.map(e => `<tr><td class="small text-muted text-nowrap">${esc(t(e.t))}</td><td>${esc(e.kind_label || e.kind)}</td>
          <td class="text-end text-nowrap">${e.d_balance ? (e.d_balance > 0 ? "+" : "") + esc(e.d_balance_text) : "—"}</td>
          <td class="text-end text-nowrap">${e.d_held ? (e.d_held > 0 ? "+" : "") + esc(e.d_held_text) : "—"}</td>
          <td class="small mono">${esc(e.job || "—")}${e.package ? ` · ${esc(e.package)}${e.qty ? " ×" + Number(e.qty) : ""}` : ""}</td>
          <td class="small">${esc(e.note || "—")}</td><td class="small">${e.actor === "gateway" ? "gateway (tiền của đơn)" : "tool"}</td></tr>`).join("")
      + `</tbody></table></div>` : `<div class="api-note">Chưa có dòng nào.</div>`);
}

async function walletRemove(name) {
  if (!confirmBox(`Bỏ ví của máy ${name}?\n\nMáy sẽ nhận đơn mà KHÔNG kiểm tiền. Sổ ví vẫn giữ để tra.`)) return;
  const res = await API().wallet_remove(name);
  if (res && res.ok) { toast("Đã bỏ ví của " + name, "ok"); loadWallets(); }
  else toast((res && res.error) || "Không bỏ được", "bad");
}
