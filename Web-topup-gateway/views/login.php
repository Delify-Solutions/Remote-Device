<!doctype html>
<html lang="vi" class="layout-wide" dir="ltr" data-skin="default" data-bs-theme="light" data-assets-path="/assets/vuexy/" data-template="vertical-menu-template-no-customizer">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Đăng nhập · Topup Gateway</title>
<link rel="icon" href="/assets/vuexy/img/favicon/favicon.ico">
<link rel="stylesheet" href="/assets/vuexy/vendor/fonts/iconify-icons.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/libs/node-waves/node-waves.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/css/core.css">
<link rel="stylesheet" href="/assets/vuexy/css/demo.css">
<link rel="stylesheet" href="/assets/app.css">
<script src="/assets/theme.js"></script>
</head>
<body>
<div class="auth-wrap">
  <div class="auth-box">
    <div class="card">
      <div class="card-body p-6 p-sm-8">
        <div class="app-brand justify-content-center mb-6">
          <span class="app-brand-logo demo text-primary"><i class="ti tabler-arrows-exchange" style="font-size:30px"></i></span>
          <span class="app-brand-text demo text-heading fw-bold ms-2">Topup Gateway</span>
        </div>
        <h4 class="mb-1">Đăng nhập quản trị</h4>
        <p class="mb-6 text-body-secondary">API trung gian giữa shop và máy nạp.</p>
        <?php if (!empty($error)): ?>
          <div class="alert alert-danger d-flex align-items-center" role="alert"><i class="ti tabler-alert-triangle me-2"></i><div><?= e($error) ?></div></div>
        <?php endif; ?>
        <form method="post" action="/admin/login">
          <?= Csrf::field() ?>
          <div class="mb-5">
            <label class="form-label" for="username">Tài khoản</label>
            <input class="form-control" type="text" id="username" name="username" autocomplete="username" autofocus required>
          </div>
          <div class="mb-6">
            <label class="form-label" for="password">Mật khẩu</label>
            <input class="form-control" type="password" id="password" name="password" autocomplete="current-password" required>
          </div>
          <button class="btn btn-primary d-grid w-100">Đăng nhập</button>
        </form>
      </div>
    </div>
  </div>
</div>
</body>
</html>
