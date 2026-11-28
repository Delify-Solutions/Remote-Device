<?php
$isActive = in_array($job['status'], Jobs::ACTIVE, true) || $job['status'] === 'queued';
$actor = ['shop' => ['Shop', 'info'], 'tool' => ['Tool', 'success'], 'admin' => ['Admin', 'primary'], 'system' => ['Hệ thống', 'secondary']];
$itemStatus = ['done' => ['success', 'đã nạp'], 'unavailable' => ['warning', 'không mua được'], 'failed' => ['danger', 'lỗi'], 'skipped' => ['secondary', 'bỏ qua']];
$held = !empty($job['wallet_id']) && ($job['wallet_state'] ?? null) === 'held';
?>
<div class="page-head" <?= $isActive ? 'data-live="6"' : '' ?>>
  <div><h4 class="mb-1 d-flex align-items-center flex-wrap gap-2">Đơn <?= e($job['ref']) ?> <?= status_badge($job['status']) ?></h4>
    <p class="mb-0 text-body-secondary mono"><?= e($job['pid']) ?><?= $isActive ? ' · đang theo dõi, tự làm mới mỗi 6 giây' : '' ?></p></div>
  <a class="btn btn-label-secondary" href="/admin/jobs"><i class="ti tabler-arrow-left me-1"></i>Danh sách đơn</a>
</div>

<?php if ($job['status'] === 'review'): ?>
<div class="card border border-primary mb-6"><div class="card-body">
  <h5 class="mb-2"><i class="ti tabler-eye-check text-primary me-1"></i>Chờ đối soát — <?= e(Jobs::REVIEW_REASON[$job['review_reason']] ?? 'cần kiểm tra') ?></h5>
  <p class="text-body-secondary">Kiểm tra trong game / lịch sử nạp của tài khoản rồi chốt. Shop chỉ nhận kết quả cuối sau khi bạn bấm. <b>Gateway không tự nạp lại và không tự hoàn tiền.</b></p>
  <?php if ($held): $cur = (string) $job['currency']; ?>
  <p class="text-body-secondary">Ví <b><?= e($wallet['apple_account'] ?? '') ?></b> đang <b>tạm giữ <?= e(Money::fmt((int) $job['cost'], $cur)) ?></b> cho đơn này. Chốt «đã nạp» thì nhập số tiền <b>thật</b> đã bị trừ ở tài khoản Apple (xem lịch sử mua của tài khoản); chốt «chưa nạp» thì nhả tạm giữ.</p>
  <?php endif; ?>
  <div class="d-flex flex-wrap gap-3 align-items-end">
    <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/resolve" class="d-flex flex-wrap gap-3 align-items-end" data-confirm="Chốt ĐÃ NẠP ĐỦ? Shop sẽ nhận job.done và hoàn tất đơn."><?= Csrf::field() ?><input type="hidden" name="to" value="done">
      <?php if ($held): ?>
      <div><label class="form-label" for="r-charge">Số tiền đã trừ (<?= e($cur) ?>)</label>
        <input class="form-control" id="r-charge" type="text" name="charge" inputmode="decimal" value="<?= e(Money::plain((int) $job['cost'], $cur)) ?>" required style="max-width:12rem"></div>
      <div><label class="form-label" for="r-note">Ghi chú (tuỳ chọn)</label>
        <input class="form-control" id="r-note" type="text" name="note" maxlength="300" placeholder="vd: mua được 1/2 gói"></div>
      <?php endif; ?>
      <button class="btn btn-success"><i class="ti tabler-check me-1"></i>Đã nạp đủ → hoàn tất</button></form>
    <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/resolve" data-confirm="Chốt CHƯA NẠP? Shop sẽ nhận job.failed để xử lý tay / hoàn tiền."><?= Csrf::field() ?><input type="hidden" name="to" value="failed">
      <button class="btn btn-label-danger"><i class="ti tabler-x me-1"></i>Chưa nạp → báo thất bại<?= $held ? ' (nhả tạm giữ)' : '' ?></button></form>
  </div>
</div></div>
<?php endif; ?>

<div class="row g-6 mb-6">
  <div class="col-xl-6">
    <div class="card h-100">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="card-title mb-0">Thông tin</h5>
        <?php if ($job['status'] === 'queued'): ?><form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/cancel" data-confirm="Huỷ đơn này?"><?= Csrf::field() ?><button class="btn btn-sm btn-label-danger"><i class="ti tabler-x me-1"></i>Huỷ đơn</button></form><?php endif; ?>
      </div>
      <div class="card-body"><dl class="kv">
        <dt>Pool</dt><dd><a href="/admin/pools/<?= (int) $pool['id'] ?>"><?= e($pool['name']) ?></a> <span class="mono small text-body-secondary"><?= e($pool['code']) ?></span></dd>
        <dt>Shop</dt><dd><?= e($shop['name'] ?? '—') ?></dd>
        <dt>Tài khoản</dt><dd><span class="mono"><?= e($job['account_hint'] ?: '—') ?></span> <span class="text-body-secondary small">(<?= $job['login_enc'] ? 'thông tin đăng nhập đang được mã hoá' : 'đã xoá khỏi máy chủ' ?>)</span></dd>
        <dt>Máy nạp</dt><dd><?= e($job['device'] ?: 'chưa giao') ?><?= $tool ? ' <span class="text-body-secondary small">(' . e($tool['name']) . ')</span>' : '' ?></dd>
        <?php if (!empty($job['wallet_id'])): ?>
        <dt>Tài khoản Apple</dt><dd><?= $wallet ? '<a href="/admin/wallets/' . (int) $wallet['id'] . '">' . e($wallet['apple_account']) . '</a>' : '—' ?> <span class="badge bg-label-secondary mono"><?= e($job['currency']) ?></span></dd>
        <dt>Chi phí đơn</dt><dd><?= e(Money::fmt((int) $job['cost'], (string) $job['currency'])) ?> <span class="text-body-secondary small">(giá lúc giao máy)</span> <?= wallet_state_badge($job['wallet_state']) ?></dd>
        <?php endif; ?>
        <dt>Bước hiện tại</dt><dd class="mono"><?= e($job['stage'] ?: '—') ?></dd>
        <dt>Lời nhắn</dt><dd><?= e($job['message'] ?: '—') ?></dd>
        <?php if ($job['note']): ?><dt>Ghi chú shop</dt><dd><?= e($job['note']) ?></dd><?php endif; ?>
        <dt>Tạo lúc</dt><dd><?= e(vntime((int) $job['created_at'], 'd/m/Y H:i:s')) ?></dd>
        <dt>Giao máy lúc</dt><dd><?= e(vntime($job['claimed_at'] ? (int) $job['claimed_at'] : null, 'd/m/Y H:i:s')) ?></dd>
        <dt>Tool gọi lần cuối</dt><dd><?= e(ago($job['seen_at'] ? (int) $job['seen_at'] : null)) ?></dd>
        <dt>Kết thúc lúc</dt><dd><?= e(vntime($job['finished_at'] ? (int) $job['finished_at'] : null, 'd/m/Y H:i:s')) ?></dd>
      </dl></div>
    </div>
  </div>

  <div class="col-xl-6 d-flex flex-column gap-6">
    <div class="card">
      <h5 class="card-header">Gói cần nạp</h5>
      <div class="table-responsive">
        <table class="table mb-0"><thead><tr><th>Mã</th><th>Tên gói</th><th>SL</th><th>Kết quả</th></tr></thead><tbody>
        <?php foreach ($items as $it): $r = null; foreach ($result as $x) { if ((string) ($x['code'] ?? '') === (string) $it['code']) { $r = $x; } } ?>
          <tr><td class="mono"><?= e($it['code']) ?></td><td><?= e($it['name']) ?><?php if (($it['limit_type'] ?? 'multi') !== 'multi'): ?> <span class="badge bg-label-secondary"><?= e(Pools::LIMIT_TYPES[$it['limit_type']] ?? '') ?></span><?php endif; ?>
            <?php if (isset($it['price'])): ?><div class="small text-body-secondary"><?= e(Money::fmt((int) $it['price'], (string) ($it['currency'] ?? ''))) ?> / gói<?= ($it['price_display'] ?? '') !== '' ? ' · trên máy: «' . e($it['price_display']) . '»' : '' ?></div><?php endif; ?></td>
            <td><?= (int) $it['qty'] ?></td>
            <td><?php if ($r): [$c, $t] = $itemStatus[$r['status']] ?? ['secondary', $r['status']]; ?><span class="badge bg-label-<?= $c ?>"><?= e($t) ?> <?= (int) $r['qty_done'] ?>/<?= (int) $it['qty'] ?></span><?php if ($r['message']): ?><div class="small text-body-secondary mt-1"><?= e($r['message']) ?></div><?php endif; ?><?php else: ?><span class="text-body-secondary">—</span><?php endif; ?></td></tr>
        <?php endforeach; ?></tbody></table>
      </div>
    </div>

    <div class="card flex-grow-1">
      <h5 class="card-header">OTP</h5>
      <div class="card-body"><dl class="kv">
        <dt>Trạng thái</dt><dd><?php $os = ['none' => 'Chưa cần', 'waiting' => 'Đang chờ khách nhập', 'submitted' => 'Khách đã nhập, chờ tool lấy', 'read' => 'Tool đã lấy mã']; echo e($os[$job['otp_state']] ?? $job['otp_state']); ?></dd>
        <dt>Số lần xin</dt><dd><?= (int) $job['otp_seq'] ?> / <?= (int) $pool['cfg']['otp']['max_requests'] ?></dd>
        <?php if ($job['otp_state'] === 'waiting' && $job['otp_deadline']): ?><dt>Hạn nhập</dt><dd><?= e(vntime((int) $job['otp_deadline'], 'H:i:s')) ?> (còn <?= max(0, (int) $job['otp_deadline'] - time()) ?> giây)</dd><?php endif; ?>
        <?php if ($job['otp_message']): ?><dt>Lời nhắn của tool</dt><dd><?= e($job['otp_message']) ?></dd><?php endif; ?>
      </dl><p class="form-text mb-0 mt-3">Mã OTP không hiển thị ở đây và bị xoá khi đơn kết thúc.</p></div>
    </div>
  </div>
</div>

<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Ảnh kết quả</h5><small class="text-body-secondary"><?= count($images) ?> ảnh · link công khai không đoán được, đưa thẳng cho khách được</small>
  </div>
  <div class="card-body">
  <?php if (!$images): ?><div class="empty py-4">Chưa có ảnh nào.</div><?php else: ?>
  <div class="gallery"><?php foreach ($images as $im): ?>
    <div class="shot"><a href="<?= e($im['url']) ?>" target="_blank"><img src="<?= e($im['url']) ?>" alt="Ảnh #<?= (int) $im['seq'] ?>" loading="lazy"></a>
      <div><span>#<?= (int) $im['seq'] ?> · <?= e($im['kind']) ?></span><a href="<?= e($im['download_url']) ?>"><i class="ti tabler-download me-1"></i>Tải về</a></div></div>
  <?php endforeach; ?></div>
  <?php endif; ?>
  </div>
</div>

<?php if ($ledger): $lc = (string) $job['currency']; ?>
<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Tiền của đơn trong ví</h5><?php if ($wallet): ?><a class="small" href="/admin/wallets/<?= (int) $wallet['id'] ?>">Sổ cái của ví <i class="ti tabler-chevron-right icon-xs"></i></a><?php endif; ?>
  </div>
  <div class="table-responsive">
  <table class="table mb-0 align-middle"><thead><tr><th>Lúc</th><th>Loại</th><th class="text-end">Số tiền</th><th class="text-end">Số dư sau</th><th>Gói</th><th>SL</th><th>Ghi chú</th><th>Ai ghi</th></tr></thead><tbody>
  <?php foreach ($ledger as $en): [$kl, $kc] = Wallets::KINDS[$en['kind']] ?? [$en['kind'], 'secondary']; $amt = (int) $en['amount']; ?>
    <tr>
      <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $en['at'])) ?></td>
      <td><span class="badge bg-label-<?= $kc ?>"><?= e($kl) ?></span></td>
      <td class="text-end text-nowrap"><?= e(($amt > 0 ? '+' : '') . Money::fmt($amt, $lc)) ?></td>
      <td class="text-end text-nowrap"><?= e(Money::fmt((int) $en['balance_after'], $lc)) ?></td>
      <td class="mono small"><?= e($en['package_code'] ?: '—') ?></td>
      <td><?= $en['qty'] !== null ? (int) $en['qty'] : '—' ?></td>
      <td class="small"><?= e($en['note'] ?: '—') ?></td>
      <td class="text-nowrap"><?= ledger_actor((string) $en['actor']) ?></td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
</div>
<?php endif; ?>

<div class="row g-6">
  <div class="col-xl-6">
    <div class="card h-100">
      <h5 class="card-header">Nhật ký đơn</h5>
      <div class="card-body"><ul class="events">
        <?php foreach ($events as $ev): [$who, $color] = $actor[$ev['actor']] ?? [$ev['actor'], 'secondary']; ?>
          <li><span class="text-body-secondary mono small"><?= e(vntime((int) $ev['at'])) ?></span><span><span class="badge bg-label-<?= $color ?>"><?= e($who) ?></span></span><span><span class="mono small fw-medium text-heading"><?= e($ev['type']) ?></span> <?= e($ev['message']) ?></span></li>
        <?php endforeach; ?>
      </ul></div>
    </div>
  </div>

  <div class="col-xl-6">
    <div class="card h-100">
      <h5 class="card-header">Webhook gửi về shop</h5>
      <?php if (!$hooks): ?><div class="empty">Chưa gửi webhook nào<?= empty($shop['webhook_url']) ? ' (khoá shop chưa đặt Webhook URL)' : '' ?>.</div><?php else: ?>
      <div class="table-responsive">
      <table class="table mb-0"><thead><tr><th>Sự kiện</th><th>Trạng thái</th><th>Lần thử</th><th>Lỗi gần nhất</th></tr></thead><tbody>
      <?php foreach ($hooks as $h): $hc = ['sent' => 'success', 'failed' => 'danger', 'pending' => 'warning'][$h['status']] ?? 'secondary'; ?>
        <tr><td class="mono small"><?= e($h['event']) ?></td><td><span class="badge bg-label-<?= $hc ?>"><?= e(['sent' => 'đã gửi', 'failed' => 'bỏ cuộc', 'pending' => 'đang chờ'][$h['status']] ?? $h['status']) ?></span></td>
          <td><?= (int) $h['attempts'] ?></td><td class="small text-body-secondary"><?= e($h['last_error'] ?: '—') ?></td></tr>
      <?php endforeach; ?></tbody></table>
      </div>
      <?php endif; ?>
    </div>
  </div>
</div>
