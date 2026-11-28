<?php
/** Khung trang quản trị — giao diện Vuexy (menu dọc), cùng kiểu với iPhone Farm Manager. @var string $content */
$nav = $nav ?? '';
$cnt = nav_counts();
$item = static function (string $key, string $href, string $icon, string $label, int $badge = 0, string $badgeTitle = '', bool $blank = false) use ($nav): string {
    return '<li class="menu-item' . ($nav === $key ? ' active' : '') . '">'
        . '<a class="menu-link" href="' . e($href) . '"' . ($blank ? ' target="_blank" rel="noopener"' : '') . '>'
        . '<i class="menu-icon icon-base ti ' . $icon . '"></i><div>' . e($label) . '</div>'
        . ($badge ? '<span class="badge rounded-pill bg-primary ms-auto" title="' . e($badgeTitle) . '">' . $badge . '</span>' : '')
        . ($blank ? '<i class="icon-base ti tabler-external-link icon-xs ms-auto text-body-secondary"></i>' : '')
        . '</a></li>';
};
$initial = mb_strtoupper(mb_substr((string) ($user['username'] ?? 'A'), 0, 1));
?>
<!doctype html>
<html lang="vi" class="layout-navbar-fixed layout-menu-fixed layout-compact" dir="ltr" data-skin="default"
      data-bs-theme="light" data-assets-path="/assets/vuexy/" data-template="vertical-menu-template-no-customizer">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title><?= e($title ?? 'Quản trị') ?> · Topup Gateway</title>
<link rel="icon" href="/assets/vuexy/img/favicon/favicon.ico">
<link rel="stylesheet" href="/assets/vuexy/vendor/fonts/iconify-icons.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/libs/node-waves/node-waves.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/css/core.css">
<link rel="stylesheet" href="/assets/vuexy/css/demo.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/libs/perfect-scrollbar/perfect-scrollbar.css">
<link rel="stylesheet" href="/assets/app.css">
<script src="/assets/theme.js"></script>
<script src="/assets/vuexy/vendor/js/helpers.js"></script>
<script src="/assets/vuexy/js/config.js"></script>
</head>
<body>
<div class="layout-wrapper layout-content-navbar">
  <div class="layout-container">

    <aside id="layout-menu" class="layout-menu menu-vertical menu">
      <div class="app-brand demo">
        <a href="/admin" class="app-brand-link">
          <span class="app-brand-logo demo text-primary"><i class="ti tabler-arrows-exchange" style="font-size:28px"></i></span>
          <span class="app-brand-text demo menu-text fw-bold ms-2">Topup Gateway</span>
        </a>
        <a href="javascript:void(0);" class="layout-menu-toggle menu-link text-large ms-auto">
          <i class="icon-base ti menu-toggle-icon d-none d-xl-block"></i>
          <i class="icon-base ti tabler-x d-block d-xl-none"></i>
        </a>
      </div>
      <div class="menu-inner-shadow"></div>
      <ul class="menu-inner py-1">
        <li class="menu-header small"><span class="menu-header-text">Vận hành</span></li>
        <?= $item('home', '/admin', 'tabler-layout-dashboard', 'Tổng quan') ?>
        <?= $item('jobs', '/admin/jobs', 'tabler-receipt', 'Đơn nạp', $cnt['review'], 'Đơn chờ đối soát') ?>
        <?= $item('scripts', '/admin/scripts', 'tabler-device-mobile-code', 'Kịch bản & máy') ?>
        <?= $item('wallets', '/admin/wallets', 'tabler-wallet', 'Ví & tài khoản Apple') ?>
        <li class="menu-header small"><span class="menu-header-text">Cấu hình</span></li>
        <?= $item('pools', '/admin/pools', 'tabler-packages', 'Pool & gói nạp') ?>
        <?= $item('keys', '/admin/keys', 'tabler-key', 'Khoá API & webhook') ?>
        <?= $item('docs', '/docs', 'tabler-book-2', 'Tài liệu API', 0, '', true) ?>
        <li class="menu-header small"><span class="menu-header-text">Hệ thống</span></li>
        <?= $item('account', '/admin/account', 'tabler-user-circle', 'Tài khoản') ?>
      </ul>
    </aside>

    <div class="layout-page">
      <nav class="layout-navbar container-xxl navbar-detached navbar navbar-expand-xl align-items-center bg-navbar-theme" id="layout-navbar">
        <div class="layout-menu-toggle navbar-nav align-items-xl-center me-3 me-xl-0 d-xl-none">
          <a class="nav-item nav-link px-0 me-xl-6" href="javascript:void(0)"><i class="icon-base ti tabler-menu-2 icon-md"></i></a>
        </div>
        <div class="navbar-nav-right d-flex align-items-center justify-content-between w-100" id="navbar-collapse">
          <span class="fw-medium text-heading text-truncate"><?= e($title ?? 'Quản trị') ?></span>
          <div class="d-flex align-items-center gap-2 flex-shrink-0">
            <?php if ($cnt['review']): ?>
              <a class="btn btn-sm btn-label-primary d-none d-md-inline-flex" href="/admin/jobs?status=review"><i class="ti tabler-eye-check me-1"></i><?= $cnt['review'] ?> đơn chờ đối soát</a>
            <?php endif; ?>
            <?php if ($cnt['otp']): ?>
              <a class="btn btn-sm btn-label-warning d-none d-md-inline-flex" href="/admin/jobs?status=need_otp"><i class="ti tabler-message-2 me-1"></i><?= $cnt['otp'] ?> chờ OTP</a>
            <?php endif; ?>
            <button type="button" class="btn btn-icon btn-sm btn-label-secondary" id="btn-theme" title="Sáng / Tối"><i class="ti tabler-sun icon-md"></i></button>
            <div class="dropdown">
              <a class="d-flex align-items-center gap-2 text-body" href="javascript:void(0)" data-bs-toggle="dropdown" aria-expanded="false">
                <span class="avatar avatar-sm"><span class="avatar-initial rounded-circle bg-label-primary"><?= e($initial) ?></span></span>
                <span class="d-none d-sm-inline fw-medium"><?= e($user['username'] ?? '') ?></span>
              </a>
              <ul class="dropdown-menu dropdown-menu-end">
                <li><a class="dropdown-item" href="/admin/account"><i class="ti tabler-lock me-2"></i>Đổi mật khẩu</a></li>
                <li><div class="dropdown-divider my-1"></div></li>
                <li><form method="post" action="/admin/logout"><?= Csrf::field() ?>
                  <button class="dropdown-item"><i class="ti tabler-logout me-2"></i>Đăng xuất</button></form></li>
              </ul>
            </div>
          </div>
        </div>
      </nav>

      <div class="content-wrapper">
        <div class="container-xxl flex-grow-1 container-p-y">
          <?php foreach (Flash::pull() as $f): $bad = $f['kind'] === 'bad'; ?>
            <div class="alert alert-<?= $bad ? 'danger' : 'success' ?> alert-dismissible d-flex align-items-center" role="alert">
              <i class="ti <?= $bad ? 'tabler-alert-triangle' : 'tabler-circle-check' ?> me-2"></i><div><?= e($f['msg']) ?></div>
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Đóng"></button>
            </div>
          <?php endforeach; ?>
          <?= $content ?>
        </div>
        <div class="content-backdrop fade"></div>
      </div>
    </div>
  </div>
  <div class="layout-overlay layout-menu-toggle"></div>
  <div class="drag-target"></div>
</div>

<script src="/assets/vuexy/vendor/libs/jquery/jquery.js"></script>
<script src="/assets/vuexy/vendor/libs/popper/popper.js"></script>
<script src="/assets/vuexy/vendor/js/bootstrap.js"></script>
<script src="/assets/vuexy/vendor/libs/node-waves/node-waves.js"></script>
<script src="/assets/vuexy/vendor/libs/perfect-scrollbar/perfect-scrollbar.js"></script>
<script src="/assets/vuexy/vendor/libs/hammer/hammer.js"></script>
<script src="/assets/vuexy/vendor/js/menu.js"></script>
<script src="/assets/vuexy/js/main.js"></script>
<script src="/assets/app.js"></script>
</body>
</html>
