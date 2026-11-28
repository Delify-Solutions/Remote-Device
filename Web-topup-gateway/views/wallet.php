<?php
$cur = (string) $w['currency'];
$pages = max(1, (int) ceil($total / $per));
?>
<div class="page-head">
  <div><h4 class="mb-1 d-flex align-items-center flex-wrap gap-2"><?= e($w['apple_account']) ?> <span class="badge bg-label-secondary mono"><?= e($cur) ?></span>
      <?= (int) $w['active'] ? '<span class="badge bg-label-success">đang dùng</span>' : '<span class="badge bg-label-secondary">ngừng dùng</span>' ?></h4>
    <p class="mb-0 text-body-secondary">Máy <b><?= e($w['device']) ?></b> · <?= e($w['key_name'] ?? '—') ?><?= $w['note'] !== '' ? ' · ' . e($w['note']) : '' ?></p></div>
  <a class="btn btn-label-secondary" href="/admin/wallets"><i class="ti tabler-arrow-left me-1"></i>Các ví</a>
</div>

<div class="row g-6 mb-6">
  <?php foreach ([['Số dư', (int) $w['balance'], 'primary', 'tabler-wallet'], ['Đang tạm giữ', $w['held'], 'warning', 'tabler-lock'], ['Còn dùng được', $w['available'], $w['available'] < 0 ? 'danger' : 'success', 'tabler-circle-check']] as [$label, $v, $color, $icon]): ?>
  <div class="col-sm-4">
    <div class="card card-border-shadow-<?= $color ?> h-100"><div class="card-body">
      <div class="d-flex align-items-center mb-2">
        <div class="avatar me-3"><span class="avatar-initial rounded bg-label-<?= $color ?>"><i class="icon-base ti <?= $icon ?> icon-28px"></i></span></div>
        <h4 class="mb-0 text-nowrap"><?= e(Money::fmt($v, $cur)) ?></h4>
      </div>
      <p class="mb-0 text-body"><?= e($label) ?></p>
    </div></div>
  </div>
  <?php endforeach; ?>
</div>

<div class="alert alert-secondary mb-6">Ví cũ khai trên gateway (trước khi ví chuyển về tool) — chỉ để tra cứu sổ cái. Ví của máy giờ khai và nạp tiền ở app tool.</div>

<div class="card">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Sổ cái</h5><small class="text-body-secondary"><?= $total ?> dòng · mới nhất trước · «Tạm giữ» không đổi số dư, chỉ bớt phần còn dùng được</small>
  </div>
<?php if (!$entries): ?><div class="empty">Chưa có giao dịch nào.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table mb-0 align-middle"><thead><tr><th>Lúc</th><th>Loại</th><th class="text-end">Số tiền</th><th class="text-end">Số dư sau</th><th>Đơn</th><th>Gói</th><th>SL</th><th>Ghi chú</th><th>Ai ghi</th></tr></thead><tbody>
  <?php foreach ($entries as $en): [$kl, $kc] = Wallets::KINDS[$en['kind']] ?? [$en['kind'], 'secondary']; $amt = (int) $en['amount']; ?>
    <tr>
      <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $en['at'], 'd/m/Y H:i:s')) ?></td>
      <td><span class="badge bg-label-<?= $kc ?>"><?= e($kl) ?></span></td>
      <td class="text-end text-nowrap <?= $en['kind'] === 'hold' ? 'text-warning' : ($amt < 0 ? 'text-danger' : ($amt > 0 ? 'text-success' : '')) ?>"><?= e(($amt > 0 ? '+' : '') . Money::fmt($amt, $cur, false)) ?></td>
      <td class="text-end text-nowrap"><?= e(Money::fmt((int) $en['balance_after'], $cur, false)) ?></td>
      <td class="mono small"><?= $en['jid'] ? '<a href="/admin/jobs/' . (int) $en['jid'] . '">' . e($en['job_pid']) . '</a>' : e($en['job_pid'] ?: '—') ?></td>
      <td class="mono small"><?= e($en['package_code'] ?: '—') ?></td>
      <td><?= $en['qty'] !== null ? (int) $en['qty'] : '—' ?></td>
      <td class="small"><?= e($en['note'] ?: '—') ?></td>
      <td class="text-nowrap"><?= ledger_actor((string) $en['actor']) ?></td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
  <?php if ($pages > 1): ?>
  <div class="card-footer d-flex justify-content-between align-items-center">
    <span class="small text-body-secondary">Trang <?= $page ?> / <?= $pages ?></span>
    <span class="d-flex gap-2">
      <a class="btn btn-sm btn-label-secondary <?= $page > 1 ? '' : 'disabled' ?>" href="/admin/wallets/<?= (int) $w['id'] ?>?page=<?= max(1, $page - 1) ?>"><i class="ti tabler-chevron-left me-1"></i>Mới hơn</a>
      <a class="btn btn-sm btn-label-secondary <?= $page < $pages ? '' : 'disabled' ?>" href="/admin/wallets/<?= (int) $w['id'] ?>?page=<?= min($pages, $page + 1) ?>">Cũ hơn<i class="ti tabler-chevron-right ms-1"></i></a>
    </span>
  </div>
  <?php endif; ?>
<?php endif; ?>
</div>
