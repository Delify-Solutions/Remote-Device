<div class="page-head">
  <div><h4 class="mb-1">Tài khoản</h4><p class="mb-0 text-body-secondary">Đổi mật khẩu đăng nhập trang quản trị.</p></div>
</div>
<div class="card" style="max-width:480px">
  <h5 class="card-header">Đổi mật khẩu</h5>
  <div class="card-body">
    <form method="post" action="/admin/account">
      <?= Csrf::field() ?>
      <div class="mb-5"><label class="form-label">Mật khẩu hiện tại</label>
        <input class="form-control" type="password" name="current" autocomplete="current-password" required></div>
      <div class="mb-5"><label class="form-label">Mật khẩu mới (≥ 10 ký tự)</label>
        <input class="form-control" type="password" name="new" autocomplete="new-password" minlength="10" required></div>
      <div class="mb-6"><label class="form-label">Nhập lại mật khẩu mới</label>
        <input class="form-control" type="password" name="confirm" autocomplete="new-password" minlength="10" required></div>
      <button class="btn btn-primary"><i class="ti tabler-lock me-1"></i>Đổi mật khẩu</button>
    </form>
  </div>
</div>
