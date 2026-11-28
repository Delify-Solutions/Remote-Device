<?php
$active = ($by['claimed'] ?? 0) + ($by['running'] ?? 0);
$stats = [
    ['queued',   'secondary', 'tabler-hourglass',       (int) ($by['queued'] ?? 0),   'Chờ máy trống'],
    ['active',   'info',      'tabler-player-play',     $active,                      'Đang xử lý'],
    ['need_otp', 'warning',   'tabler-message-2',       (int) ($by['need_otp'] ?? 0), 'Chờ khách nhập OTP'],
    ['review',   'primary',   'tabler-eye-check',       (int) ($by['review'] ?? 0),   'Chờ đối soát'],
    ['done',     'success',   'tabler-circle-check',    $doneToday,                   'Hoàn tất hôm nay'],
    ['failed',   'danger',    'tabler-circle-x',        $failedToday,                 'Thất bại hôm nay'],
];
?>
<div class="page-head" data-live="15">
  <div><h4 class="mb-1">Tổng quan</h4><p class="mb-0 text-body-secondary">Trạng thái hàng đợi, máy nạp và các đơn gần đây (tự làm mới mỗi 15 giây).</p></div>
</div>

<?php if (!$hasPool || !$hasShopKey || !$hasToolKey): ?>
<div class="alert alert-warning" role="alert"><b>Bắt đầu nhanh:</b>
  <?= $hasPool ? '✓' : '①' ?> <a class="alert-link" href="/admin/pools/new">tạo pool</a> (trường đăng nhập, OTP, gói nạp) →
  <?= $hasShopKey ? '✓' : '②' ?> <a class="alert-link" href="/admin/keys">tạo khoá Shop</a> cho website →
  <?= $hasToolKey ? '✓' : '③' ?> <a class="alert-link" href="/admin/keys">tạo khoá Tool</a> cho máy nạp →
  ④ đấu nối theo <a class="alert-link" href="/docs" target="_blank">tài liệu API</a>.</div>
<?php endif; ?>

<div class="row g-6 mb-6">
  <?php foreach ($stats as [$key, $color, $icon, $n, $label]): ?>
  <div class="col-6 col-md-4 col-xxl-2">
    <a class="card card-border-shadow-<?= $color ?> h-100 stat-card" href="/admin/jobs?status=<?= $key ?>">
      <div class="card-body">
        <div class="d-flex align-items-center mb-2">
          <div class="avatar me-3"><span class="avatar-initial rounded bg-label-<?= $color ?>"><i class="icon-base ti <?= $icon ?> icon-28px"></i></span></div>
          <h4 class="mb-0"><?= $n ?></h4>
        </div>
        <p class="mb-0 text-body"><?= e($label) ?></p>
      </div>
    </a>
  </div>
  <?php endforeach; ?>
</div>

<?php if ($whFailed): ?><div class="alert alert-warning" role="alert"><i class="ti tabler-alert-triangle me-1"></i>Có <b><?= $whFailed ?></b> webhook gửi về shop THẤT BẠI trong 24 giờ qua — kiểm tra Webhook URL ở trang <a class="alert-link" href="/admin/keys">Khoá API</a>. Shop vẫn đọc được trạng thái bằng <code>GET /api/shop/jobs/{id}</code>.</div><?php endif; ?>

<?php if ($lowWallets): ?>
<div class="card border border-warning mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0"><i class="ti tabler-wallet text-warning me-1"></i>Ví sắp hết tiền</h5><a href="/admin/wallets" class="small">Ví &amp; tài khoản Apple <i class="ti tabler-chevron-right icon-xs"></i></a>
  </div>
  <div class="table-responsive">
    <table class="table mb-0"><thead><tr><th>Máy</th><th>Tài khoản Apple</th><th class="text-end">Còn dùng được</th><th class="text-end">Gói đắt nhất</th></tr></thead><tbody>
    <?php foreach ($lowWallets as $w): ?>
      <tr><td><span class="fw-medium text-heading"><?= e($w['device']) ?></span><div class="small text-body-secondary"><?= e($w['key_name'] ?? '') ?></div></td>
        <td><?= e($w['apple_account'] ?: '—') ?></td>
        <td class="text-end text-nowrap fw-medium text-warning"><?= e(Money::fmt($w['available'], (string) $w['currency'])) ?></td>
        <td class="text-end text-nowrap"><?= e(Money::fmt($w['need'], (string) $w['currency'])) ?></td></tr>
    <?php endforeach; ?></tbody></table>
  </div>
  <div class="card-body pt-3 pb-4"><p class="small text-body-secondary mb-0">Các máy này không nhận được đơn có gói đắt hơn số tiền còn dùng được — nạp thêm tiền cho tài khoản Apple rồi ghi vào ví ở app tool.</p></div>
</div>
<?php endif; ?>

<div class="row g-6">
  <div class="col-xl-6">
    <div class="card h-100">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="card-title mb-0">Máy nạp</h5><a href="/admin/scripts" class="small">Kịch bản &amp; máy <i class="ti tabler-chevron-right icon-xs"></i></a>
      </div>
      <?php if (!$devices): ?><div class="empty">Chưa có máy nào gọi vào.</div><?php else: ?>
      <div class="table-responsive">
        <table class="table table-hover mb-0"><thead><tr><th>Máy</th><th>Kịch bản / pool</th><th>Trạng thái</th><th>Gọi lần cuối</th></tr></thead><tbody>
        <?php foreach ($devices as $d): [$st, , , $note] = Tools::state($d); $uids = jdec($d['scripts'] ?? null); ?>
          <tr>
            <td><span class="live-dot <?= $st !== 'lost' ? 'on' : '' ?>"></span><span class="fw-medium text-heading"><?= e($d['name']) ?></span>
              <div class="small text-body-secondary"><?= e(implode(' · ', array_filter([(string) ($d['label'] ?? ''), (string) $d['key_name']], 'strlen'))) ?></div></td>
            <td class="small"><?php foreach ($uids as $u): $sc = $scriptNames[$d['tool_key_id'] . '|' . $u] ?? null; ?><span class="badge <?= $sc && $sc['steps'] > 0 ? 'bg-label-primary' : 'bg-label-secondary' ?> me-1"><?= e($sc ? $sc['name'] : $u) ?></span><?php endforeach; ?>
                <?php if ($d['pool_code']): ?><span class="mono"><?= e($d['pool_code']) ?></span><?php elseif (!$uids): ?>—<?php endif; ?></td>
            <td><?= device_badge($d) ?>
                <?php if ($note !== ''): ?><div class="small text-body-secondary"><?= e($note) ?></div><?php endif; ?>
                <?php if ($d['job_pid']): ?><div class="mono small text-body-secondary"><?= e($d['job_pid']) ?></div><?php endif; ?></td>
            <td class="small text-body-secondary text-nowrap"><?= e(ago((int) $d['last_seen_at'])) ?></td>
          </tr>
        <?php endforeach; ?></tbody></table>
      </div>
      <?php endif; ?>
    </div>
  </div>

  <div class="col-xl-6">
    <div class="card h-100">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="card-title mb-0">Đơn gần đây</h5><a href="/admin/jobs" class="small">Xem tất cả <i class="ti tabler-chevron-right icon-xs"></i></a>
      </div>
      <?php if (!$recent): ?><div class="empty">Chưa có đơn nào.</div><?php else: ?>
      <div class="table-responsive">
        <table class="table table-hover mb-0"><thead><tr><th>Mã đơn</th><th>Trạng thái</th><th>Máy</th><th>Tạo lúc</th></tr></thead><tbody>
        <?php foreach ($recent as $j): ?>
          <tr>
            <td><a class="fw-medium" href="/admin/jobs/<?= (int) $j['id'] ?>"><?= e($j['ref']) ?></a><div class="small text-body-secondary"><?= e($j['pool_name']) ?></div></td>
            <td><?= status_badge($j['status']) ?></td>
            <td class="small"><?= e($j['device'] ?: '—') ?></td>
            <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $j['created_at'])) ?></td>
          </tr>
        <?php endforeach; ?></tbody></table>
      </div>
      <?php endif; ?>
    </div>
  </div>
</div>
<?php if ($whPending): ?><p class="small text-body-secondary mt-4 mb-0">Webhook đang chờ gửi: <?= $whPending ?>. Nhớ đặt cron <code>php bin/cron.php</code> mỗi phút để gửi lại + dọn đơn quá hạn.</p><?php endif; ?>
