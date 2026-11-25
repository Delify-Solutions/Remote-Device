// Áp chế độ sáng/tối đã chọn TRƯỚC khi Vuexy khởi tạo (tránh nháy màu). Chưa chọn thì theo hệ điều hành.
(function () {
  var t = null;
  try { t = localStorage.getItem('gw-theme'); } catch (e) {}
  if (t !== 'light' && t !== 'dark') {
    t = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.setAttribute('data-bs-theme', t);
})();
