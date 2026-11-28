<?php
$multiKey = count(array_unique(array_column($wallets, 'tool_key_id'))) > 1;
?>
<div class="page-head">
  <div><h4 class="mb-1">Ví &amp; tài khoản Apple</h4>
    <p class="mb-0 text-body-secondary">Ví của từng máy (tài khoản Apple, loại tiền, số dư) do <b>tool quản lý</b> — khai và nạp tiền ở trang «Ví &amp; tài khoản Apple» của app tool. Gateway chỉ hiện bản sao tool báo lên, và chỉ giao cho máy những đơn mà ví đủ tiền (theo giá gói ở đúng loại tiền của ví).</p></div>
</div>

<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Ví của các máy</h5><small class="text-body-secondary">«Còn dùng được» = số dư − tiền tạm giữ − tiền của đơn tool chưa kịp nhận</small>
  </div>
<?php if (!$wallets): ?>
  <div class="empty">Chưa có máy nào có ví — khai ở app tool (trang «Ví &amp; tài khoản Apple»). Máy không có ví nhận đơn mà không kiểm tiền.</div>
<?php else: ?>
  <div class="table-responsive">
  <table class="table table-hover mb-0 align-middle"><thead><tr><th>Máy</th><th>Tài khoản Apple</th><th class="text-end">Số dư</th><th class="text-end">Đang giữ</th><th class="text-end">Còn dùng được</th><th>Trạng thái</th><th>Tool báo lúc</th></tr></thead><tbody>
  <?php foreach ($wallets as $w): $cur = (string) $w['currency']; $avail = (int) $w['balance'] - (int) $w['held'] + (int) $w['pending_effect']; ?>
    <tr class="<?= (int) $w['active'] ? '' : 'text-body-secondary' ?>">
      <td><span class="fw-medium text-heading"><?= e($w['device']) ?></span><?= $multiKey ? '<div class="small text-body-secondary">' . e($w['key_name'] ?? '—') . '</div>' : '' ?></td>
      <td><?= e($w['apple_account'] ?: '—') ?> <span class="badge bg-label-secondary mono"><?= e($cur) ?></span>
        <?php if ($w['note'] !== ''): ?><div class="small text-body-secondary"><?= e($w['note']) ?></div><?php endif; ?></td>
      <td class="text-end text-nowrap"><?= e(Money::fmt((int) $w['balance'], $cur)) ?></td>
      <td class="text-end text-nowrap"><?= (int) $w['held'] ? e(Money::fmt((int) $w['held'], $cur)) : '<span class="text-body-secondary">—</span>' ?></td>
      <td class="text-end text-nowrap fw-medium <?= $avail < 0 ? 'text-danger' : 'text-heading' ?>"><?= e(Money::fmt($avail, $cur)) ?>
        <?php if ((int) $w['pending']): ?><div class="small text-body-secondary fw-normal" title="Tiền của đơn gateway đã tính nhưng tool chưa nhận (nhận ở lần đồng bộ tới)"><?= (int) $w['pending'] ?> khoản tool chưa nhận (<?= e(Money::fmt((int) $w['pending_effect'], $cur)) ?>)</div><?php endif; ?></td>
      <td><?= (int) $w['active'] ? '<span class="badge bg-label-success">đang dùng</span>' : '<span class="badge bg-label-secondary">ngừng dùng</span>' ?></td>
      <td class="small text-body-secondary text-nowrap"><?= e(ago((int) $w['reported_at'])) ?></td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
<?php endif; ?>
</div>

<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Tiền của các đơn gửi cho tool</h5><small class="text-body-secondary">Gateway tính tiền từng đơn (mua, tạm giữ, admin chốt / hoàn); tool áp vào sổ của nó ở lần đồng bộ sau</small>
  </div>
<?php if (!$events): ?><div class="empty">Chưa có đơn nào trả bằng ví của tool.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table mb-0 align-middle"><thead><tr><th>Lúc</th><th>Máy</th><th>Đơn</th><th>Loại</th><th class="text-end">Số dư</th><th class="text-end">Tạm giữ</th><th>Ghi chú</th><th>Tool</th></tr></thead><tbody>
  <?php foreach ($events as $ev): [$kl, $kc] = Wallets::KINDS[$ev['kind']] ?? [$ev['kind'], 'secondary']; $cur = (string) $ev['currency'];
      $sign = static fn (int $v): string => $v === 0 ? '—' : (($v > 0 ? '+' : '') . Money::fmt($v, $cur)); ?>
    <tr>
      <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $ev['created_at'])) ?></td>
      <td class="small"><?= e($ev['device']) ?></td>
      <td class="small"><?= $ev['job_id'] ? '<a href="/admin/jobs/' . (int) $ev['job_id'] . '" class="mono">' . e((string) $ev['job_pid']) . '</a>' : '<span class="mono text-body-secondary">' . e((string) $ev['job_pid']) . '</span>' ?></td>
      <td><span class="badge bg-label-<?= $kc ?>"><?= e($kl) ?></span><?= $ev['package_code'] ? ' <span class="mono small">' . e($ev['package_code']) . ($ev['qty'] !== null ? ' ×' . (int) $ev['qty'] : '') . '</span>' : '' ?></td>
      <td class="text-end text-nowrap"><?= e($sign((int) $ev['d_balance'])) ?></td>
      <td class="text-end text-nowrap"><?= e($sign((int) $ev['d_held'])) ?></td>
      <td class="small"><?= e($ev['note'] ?: '—') ?></td>
      <td><?= $ev['acked_at'] ? '<span class="badge bg-label-success">đã nhận</span>' : '<span class="badge bg-label-warning">chưa nhận</span>' ?></td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
<?php endif; ?>
</div>
