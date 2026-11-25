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
    if (document.querySelector('.dropdown-menu.show')) return;
    location.reload();
  }, Number(live.dataset.live) * 1000);
}
