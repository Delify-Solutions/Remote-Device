// Topup Gateway — JS nhỏ cho trang quản trị + tài liệu (không phụ thuộc thư viện).
document.addEventListener('click', (e) => {
  const add = e.target.closest('[data-add]');
  if (add) {
    const tpl = document.getElementById(add.dataset.add);
    const into = document.getElementById(add.dataset.into);
    into.appendChild(tpl.content.cloneNode(true));
    const first = into.lastElementChild && into.lastElementChild.querySelector('input:not([type=hidden]),select');
    if (first) first.focus();
    return;
  }
  const del = e.target.closest('.row-del');
  if (del) { del.closest('.rep-row').remove(); return; }
  const up = e.target.closest('.row-up');
  if (up) {
    const row = up.closest('.rep-row');
    if (row.previousElementSibling) row.parentNode.insertBefore(row, row.previousElementSibling);
    return;
  }
  const copy = e.target.closest('[data-copy]');
  if (copy) {
    const src = copy.dataset.copy ? document.querySelector(copy.dataset.copy) : null;
    const text = src ? src.textContent : (copy.dataset.text || '');
    const done = () => {
      if (copy.dataset.busy) return;
      const old = copy.innerHTML;                 // giữ lại cả icon của nút
      copy.dataset.busy = '1';
      copy.textContent = 'Đã chép ✓';
      setTimeout(() => { copy.innerHTML = old; delete copy.dataset.busy; }, 1300);
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
    else {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); done();
    }
    return;
  }
  const rev = e.target.closest('[data-reveal]');
  if (rev) {
    const el = document.querySelector(rev.dataset.reveal);
    if (el) { el.hidden = !el.hidden; rev.textContent = el.hidden ? 'Hiện' : 'Ẩn'; }
  }
});

// hộp xác nhận cho thao tác khó đảo ngược
document.addEventListener('submit', (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// sáng / tối: đổi ngay tại chỗ (không tải lại trang → không mất nội dung đang gõ dở), nhớ cho lần sau
const themeBtn = document.getElementById('btn-theme');
if (themeBtn) {
  const root = document.documentElement;
  const paint = () => {
    const ic = themeBtn.querySelector('i');
    if (ic) ic.className = 'ti ' + (root.getAttribute('data-bs-theme') === 'dark' ? 'tabler-sun' : 'tabler-moon') + ' icon-md';
  };
  paint();
  themeBtn.addEventListener('click', () => {
    const next = root.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-bs-theme', next);
    try { localStorage.setItem('gw-theme', next); } catch (err) {}
    paint();
  });
}

// trang đang theo dõi đơn chạy: tự tải lại (dừng khi người dùng đang gõ hoặc đang mở menu)
const live = document.querySelector('[data-live]');
if (live) {
  setInterval(() => {
    const a = document.activeElement;
    if (a && ['INPUT', 'TEXTAREA', 'SELECT'].includes(a.tagName)) return;
    // đang mở hộp sửa / tạo đơn (body.modal-open có ngay lúc bấm mở, trước cả hiệu ứng hiện hộp): không tải lại (mất chữ đang gõ)
    if (document.querySelector('.dropdown-menu.show, .modal.show') || document.body.classList.contains('modal-open')) return;
    location.reload();
  }, Number(live.dataset.live) * 1000);
}


// ---- FORM ĐƠN (modal «Tạo đơn thử» / «Sửa đơn»): ô đăng nhập + gói nạp dựng theo cấu hình pool ----
const escHtml = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function renderJobFields(form) {
  const box = form.querySelector('[data-job-fields]');
  if (!box) return;
  let pools = [];
  try { pools = JSON.parse(form.dataset.jobForm || '[]'); } catch (err) { pools = []; }
  const sel = form.querySelector('[data-pool-select]');
  const pool = pools.find((p) => !sel || p.code === sel.value) || pools[0];
  if (!pool) { box.innerHTML = ''; return; }
  let vals = {};
  try { vals = JSON.parse(form.dataset.jobValues || '{}'); } catch (err) { vals = {}; }
  const edit = form.dataset.jobEdit === '1';
  const uid = (form.id || 'f') + '-' + Math.random().toString(36).slice(2, 7);
  const field = (f, i) => {
    const id = uid + '-lf' + i, name = 'login[' + escHtml(f.key) + ']';
    const req = f.required && !(edit && f.secret) ? ' required' : '';
    const hint = f.hint ? '<div class="form-text">' + escHtml(f.hint) + '</div>' : '';
    const ph = edit && f.secret ? ' placeholder="Để trống = giữ nguyên"' : '';
    let input;
    if (f.type === 'select') {
      input = '<select class="form-select" id="' + id + '" name="' + name + '"' + req + '><option value="">— chọn —</option>'
        + (f.options || []).map((o) => '<option>' + escHtml(o) + '</option>').join('') + '</select>';
    } else if (f.type === 'textarea') {
      input = '<textarea class="form-control" id="' + id + '" name="' + name + '" rows="3"' + (f.secret ? ' data-secret="1"' : '') + req + ph + '></textarea>';
    } else {
      input = '<input class="form-control' + (f.secret ? ' mono' : '') + '" id="' + id + '" name="' + name + '" type="' + (f.secret ? 'password' : 'text')
        + '" autocomplete="' + (f.secret ? 'new-password' : 'off') + '"' + req + ph + '>';
    }
    return '<div class="col-sm-6"><label class="form-label" for="' + id + '">' + escHtml(f.label) + (f.required ? ' <span class="text-danger">*</span>' : '') + '</label>'
      + input + hint + '</div>';
  };
  const pk = (k, i) => {
    const id = uid + '-pk' + i, q = (vals.items || {})[k.code] || 0;
    return '<tr><td><label for="' + id + '" class="mb-0">' + escHtml(k.name) + '</label> <span class="mono small text-body-secondary">' + escHtml(k.code) + '</span>'
      + (k.limit_type !== 'multi' ? ' <span class="badge bg-label-secondary">' + (k.limit_type === 'once' ? '1 lần / tài khoản' : 'tối đa 1') + '</span>' : '') + '</td>'
      + '<td style="width:7rem"><input type="hidden" name="pk_code[]" value="' + escHtml(k.code) + '">'
      + '<input class="form-control form-control-sm" id="' + id + '" type="number" name="pk_qty[]" min="0" max="' + k.max + '" value="' + q + '" aria-label="Số lượng ' + escHtml(k.name) + '"></td></tr>';
  };
  box.innerHTML = (pool.fields.length ? '<h6 class="mt-4 mb-2">Tài khoản game của khách</h6><div class="row g-3">' + pool.fields.map(field).join('') + '</div>' : '')
    + '<h6 class="mt-4 mb-2">Gói cần nạp <span class="small text-body-secondary fw-normal">— nhập số lượng, 0 = không mua</span></h6>'
    + (pool.packages.length ? '<div class="table-responsive"><table class="table table-sm mb-0"><tbody>' + pool.packages.map(pk).join('') + '</tbody></table></div>'
                            : '<div class="text-danger small">Pool chưa có gói nào đang bán.</div>');
  fillLogin(form, form._login);
}
// đổ thông tin đăng nhập đã «Hiện» vào ô KHÔNG bí mật của form sửa (ô mật khẩu luôn để trống = giữ nguyên)
function fillLogin(form, login) {
  if (!login) return;
  form.querySelectorAll('[name^="login["]').forEach((el) => {
    const k = el.name.slice(6, -1);
    if (el.type !== 'password' && !el.dataset.secret && login[k] !== undefined && el.value === '') el.value = login[k];
  });
}
document.querySelectorAll('form[data-job-form]').forEach((form) => {
  renderJobFields(form);
  const sel = form.querySelector('[data-pool-select]');
  if (sel) sel.addEventListener('change', () => renderJobFields(form));
});

async function postForm(form) {
  const r = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' }, credentials: 'same-origin' });
  try { return await r.json(); } catch (err) { return { ok: false, error: 'Máy chủ trả lỗi (' + r.status + ') — tải lại trang rồi thử lại.' }; }
}
async function revealLogin() {
  const f = document.getElementById('f-login');
  if (!f) return null;
  if (f._login) return f._login;
  const d = await postForm(f);
  if (!d.ok) { alert(d.error || 'Không xem được.'); return null; }
  f._login = d.login || {};
  document.querySelectorAll('[data-login-key]').forEach((el) => {
    const v = f._login[el.dataset.loginKey];
    el.textContent = v === undefined || v === '' ? '—' : v;
  });
  const b = f.querySelector('button');
  if (b) { b.disabled = true; b.innerHTML = '<i class="ti tabler-eye-off me-1"></i>Đang hiện'; }
  return f._login;
}
// form gửi bằng fetch (modal): lỗi hiện ngay trong modal, không mất chữ đã nhập; xong thì sang trang đơn / tải lại
document.addEventListener('submit', async (e) => {
  const form = e.target.closest('form[data-ajax]');
  if (!form || e.defaultPrevented) return;
  e.preventDefault();
  if (form.dataset.ajax === 'login') { revealLogin(); return; }
  const err = form.querySelector('.ajax-error'), btn = form.querySelector('button:not([type=button])');
  if (err) err.hidden = true;
  if (btn) btn.disabled = true;
  const d = await postForm(form);
  if (d.ok) { if (d.url) location.href = d.url; else location.reload(); return; }
  if (btn) btn.disabled = false;
  if (err) { err.textContent = d.error || 'Không lưu được.'; err.hidden = false; err.scrollIntoView({ block: 'nearest' }); }
});
// mở hộp «Sửa» của đơn chờ máy: lấy thông tin đăng nhập hiện tại để sửa (ghi nhật ký «xem»); /admin/jobs/{id}#edit mở sẵn hộp sửa
const editModal = document.getElementById('m-edit');
if (editModal) {
  editModal.addEventListener('show.bs.modal', async () => {
    const form = editModal.querySelector('form[data-job-edit]');
    if (!form) return;
    const login = await revealLogin();
    if (login) { form._login = login; fillLogin(form, login); }
  });
  if (location.hash === '#edit' && window.bootstrap) {
    history.replaceState(null, '', location.pathname + location.search);
    window.bootstrap.Modal.getOrCreateInstance(editModal).show();
  }
}


// ---- POOL: loại tiền → ô giá của từng gói hiện NGAY (không phải lưu rồi mới thấy cột giá) ----
// Loại tiền bị xoá khỏi ô chỉ bị ẨN + tắt (không gửi đi), gõ lại thì hiện lại với giá cũ — gõ dở («JP») không làm mất giá đã nhập.
const curSync = document.querySelector('[data-cur-sync]');
if (curSync) {
  const zero = JSON.parse(curSync.dataset.zero || '[]'), examples = JSON.parse(curSync.dataset.examples || '{}');
  const alias = JSON.parse(curSync.dataset.alias || '{}'), sym = JSON.parse(curSync.dataset.sym || '{}');
  const label = (c) => sym[c] ? c + ' ' + sym[c] : c;
  const colsInput = curSync.form.querySelector('[name=pk_currencies]');
  const cell = (c) => {
    const span = document.createElement('span');
    span.className = 'pp-cur'; span.dataset.cur = c;
    const box = (cap, name, ph, extra) => '<label class="pp"><span class="pp-cap">' + label(c) + ' · ' + cap + '</span><input class="form-control form-control-sm" type="text" name="pp_' + c + '_' + name + '[]" value="" placeholder="' + ph + '"' + extra + '></label>';
    span.innerHTML = box('giá', 'amount', zero.includes(c) ? '1500' : '63.00', ' inputmode="decimal"') + box('chữ hiện trên máy', 'display', examples[c] || ('vd: 9.99 ' + c), '');
    return span;
  };
  const rows = () => [...document.querySelectorAll('#rep-pk .cols-pk')].concat([...((document.getElementById('tpl-pk') || {}).content || document.createDocumentFragment()).querySelectorAll('.cols-pk')]);
  // đọc ô loại tiền ĐÚNG như gateway (Pools::parseCurrencies): tách theo khoảng trắng / phẩy / chấm phẩy, mỗi nhãn 1–6 chữ / ký hiệu tiền (bỏ dấu chấm), tối đa 10.
  // Gõ sai / gõ dở → null: GIỮ NGUYÊN các ô giá đang có (không ẩn, không đổi danh sách cột gửi đi) để không bao giờ làm mất giá đã nhập.
  const parse = (raw) => {
    const toks = raw.replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, '').split(/[ \t\n\r\f\v,;]+/).filter(Boolean), out = [];     // đúng các dấu cách PHP \s nhận
    for (const t0 of toks) {
      let c = t0.toUpperCase().replace(/\./g, '');              // bỏ dấu chấm («kr.» → KR): nhãn nằm trong tên ô giá, PHP đổi «.» thành «_»
      c = alias[c] || c;                                        // giống Money::currency: «¥», «JP» → JPY; nhãn khác («kr») giữ nguyên, viết hoa
      if (!/^[\p{L}\p{Sc}]{1,6}$/u.test(c)) return null;
      if (!out.includes(c)) out.push(c);
    }
    return out.length <= 10 ? out : null;
  };
  const sync = () => {
    const want = parse(curSync.value);
    curSync.classList.toggle('is-invalid', want === null);
    if (want === null) return;
    rows().forEach((row) => {
      const box = row.querySelector('.pk-prices');
      if (!box) return;
      want.forEach((c) => { if (![...box.querySelectorAll('.pp-cur')].some((x) => x.dataset.cur === c)) box.appendChild(cell(c)); });
      box.querySelectorAll('.pp-cur').forEach((sp) => {
        const on = want.includes(sp.dataset.cur);
        sp.hidden = !on;
        sp.querySelectorAll('input').forEach((i) => { i.disabled = !on; });
      });
    });
    colsInput.value = want.join(',');              // cột giá gửi đi = đúng các loại tiền đang có trong ô
  };
  curSync.addEventListener('input', sync);
  sync();
}
