<?php
$qs = static function (array $over) use ($status, $pool, $q): string {
    $p = array_filter(array_merge(['status' => $status, 'pool' => $pool ?: null, 'q' => $q], $over), static fn ($v) => $v !== null && $v !== '');
    return '/admin/jobs' . ($p ? '?' . http_build_query($p) : '');
};
$pages = max(1, (int) ceil($total / $per));
$filtered = $status || $pool || $q !== '';
?>
<div class="page-head" data-live="20">
  <div><h4 class="mb-1">Đơn nạp</h4><p class="mb-0 text-body-secondary"><?= $total ?> đơn<?= $filtered ? ' khớp bộ lọc' : '' ?> · tự làm mới mỗi 20 giây.</p></div>
  <?php if ($poolForms): ?><button type="button" class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#m-create"><i class="ti tabler-test-pipe me-1"></i>Tạo đơn thử</button><?php endif; ?>
</div>

<div class="card">
  <div class="card-header">
    <form method="get" action="/admin/jobs" class="row g-3 align-items-center">
      <div class="col-sm-6 col-lg-3">
        <select class="form-select" name="status" onchange="this.form.submit()">
          <option value="">Mọi trạng thái</option>
          <option value="active" <?= $status === 'active' ? 'selected' : '' ?>>Đang xử lý (gồm chờ OTP)</option>
          <?php foreach (Jobs::LABEL as $k => $label): ?><option value="<?= e($k) ?>" <?= $status === $k ? 'selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?>
        </select></div>
      <div class="col-sm-6 col-lg-3">
        <select class="form-select" name="pool" onchange="this.form.submit()">
          <option value="">Mọi pool</option>
          <?php foreach ($pools as $p): ?><option value="<?= (int) $p['id'] ?>" <?= $pool === (int) $p['id'] ? 'selected' : '' ?>><?= e($p['name']) ?></option><?php endforeach; ?>
        </select></div>
      <div class="col-sm-8 col-lg-4">
        <div class="input-group input-group-merge">
          <span class="input-group-text"><i class="ti tabler-search"></i></span>
          <input class="form-control" type="search" name="q" value="<?= e($q) ?>" placeholder="Tìm mã đơn / id / máy…">
        </div></div>
      <div class="col-sm-4 col-lg-2 d-flex gap-2">
        <button class="btn btn-primary flex-grow-1"><i class="ti tabler-filter me-1"></i>Lọc</button>
        <?php if ($filtered): ?><a class="btn btn-icon btn-label-secondary" href="/admin/jobs" title="Bỏ lọc"><i class="ti tabler-x"></i></a><?php endif; ?>
      </div>
    </form>
  </div>
<?php if (!$rows): ?><div class="empty">Không có đơn nào.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table table-hover mb-0"><thead><tr><th>Mã đơn (shop)</th><th>Pool</th><th>Tài khoản</th><?php if ($wallets): ?><th title="Tài khoản đang khai ở ví của máy nhận đơn (theo bản tool báo gần nhất)">Tài khoản Apple</th><?php endif; ?><th>Trạng thái</th><th>Máy</th><th>Ảnh</th><th>Tạo lúc</th><th>Cập nhật</th><th class="text-end">Thao tác</th></tr></thead><tbody>
  <?php foreach ($rows as $j):
      $busy = in_array($j['status'], Jobs::ACTIVE, true) || ($j['status'] === 'review' && Wallets::isWalletJob($j) && ($j['wallet_state'] ?? null) === 'held'); ?>
    <tr>
      <td><a class="fw-medium" href="/admin/jobs/<?= (int) $j['id'] ?>"><?= e($j['ref']) ?></a><div class="mono small text-body-secondary"><?= e($j['pid']) ?></div></td>
      <td class="small"><?= e($j['pool_name']) ?></td>
      <td class="mono small"><?= e($j['account_hint'] ?: '—') ?></td>
      <?php if ($wallets): ?><td class="small"><?= !empty($j['apple_account']) ? e(Wallets::mask((string) $j['apple_account'])) . ' <span class="text-body-secondary mono">' . e($j['currency']) . '</span>' : '<span class="text-body-secondary">—</span>' ?></td><?php endif; ?>
      <td><?= status_badge($j['status']) ?>
        <?php if ($j['status'] === 'review' && $j['review_reason']): ?><div class="small text-body-secondary"><?= e(Jobs::REVIEW_REASON[$j['review_reason']] ?? $j['review_reason']) ?></div>
        <?php elseif (in_array($j['status'], ['running', 'claimed'], true) && $j['stage']): ?><div class="small text-body-secondary mono"><?= e($j['stage']) ?></div><?php endif; ?></td>
      <td class="small"><?= e($j['device'] ?: '—') ?></td>
      <td><?= (int) $j['images'] ? '<span class="badge bg-label-secondary"><i class="ti tabler-photo me-1"></i>' . (int) $j['images'] . '</span>' : '<span class="text-body-secondary">—</span>' ?></td>
      <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $j['created_at'])) ?></td>
      <td class="small text-body-secondary text-nowrap"><?= e(ago((int) $j['updated_at'])) ?></td>
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/jobs/<?= (int) $j['id'] ?>" title="Xem đơn" aria-label="Xem đơn <?= e($j['ref']) ?>"><i class="ti tabler-eye"></i></a>
        <a class="btn btn-sm btn-icon btn-text-secondary" href="/admin/jobs/<?= (int) $j['id'] ?>#edit" title="Sửa đơn" aria-label="Sửa đơn <?= e($j['ref']) ?>"><i class="ti tabler-pencil"></i></a>
        <form method="post" action="/admin/jobs/<?= (int) $j['id'] ?>/delete" class="d-inline" data-confirm="XOÁ HẲN đơn <?= e($j['ref']) ?>? Xoá cả ảnh và nhật ký, không lấy lại được.<?= $j['status'] === 'queued' ? ' Đơn đang chờ máy sẽ bị huỷ trước (shop nhận job.cancelled).' : '' ?>"><?= Csrf::field() ?><input type="hidden" name="back" value="list">
          <button class="btn btn-sm btn-icon btn-text-danger" <?= $busy ? 'disabled title="Máy đang làm / đơn đang tạm giữ ví — không xoá được"' : 'title="Xoá đơn"' ?> aria-label="Xoá đơn <?= e($j['ref']) ?>"><i class="ti tabler-trash"></i></button></form>
      </td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
  <?php if ($pages > 1): ?>
  <div class="card-footer d-flex justify-content-between align-items-center">
    <span class="small text-body-secondary">Trang <?= $page ?> / <?= $pages ?></span>
    <span class="d-flex gap-2">
      <a class="btn btn-sm btn-label-secondary <?= $page > 1 ? '' : 'disabled' ?>" href="<?= e($qs(['page' => max(1, $page - 1)])) ?>"><i class="ti tabler-chevron-left me-1"></i>Trước</a>
      <a class="btn btn-sm btn-label-secondary <?= $page < $pages ? '' : 'disabled' ?>" href="<?= e($qs(['page' => min($pages, $page + 1)])) ?>">Sau<i class="ti tabler-chevron-right ms-1"></i></a>
    </span>
  </div>
  <?php endif; ?>
<?php endif; ?>
</div>

<?php if ($poolForms): ?>
<div class="modal fade" id="m-create" tabindex="-1" aria-labelledby="m-create-title" aria-hidden="true">
  <div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">
    <form method="post" action="/admin/jobs/create" data-ajax="go" data-job-form="<?= e(jenc($poolForms)) ?>" autocomplete="off">
      <?= Csrf::field() ?>
      <div class="modal-header"><h5 class="modal-title" id="m-create-title">Tạo đơn thử</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button></div>
      <div class="modal-body">
        <div class="alert alert-warning mb-4"><b>Đây là đơn THẬT.</b> Máy đang nhận đơn của pool sẽ đăng nhập tài khoản dưới đây và <b>mua thật</b> bằng tài khoản Apple của máy (trừ ví). Đơn mang khoá «Đơn thử (trang quản trị)» nên không báo về shop nào. Muốn thử mà không mua: tạo đơn khi chưa máy nào nhận đơn rồi xoá.</div>
        <div class="row g-3">
          <div class="col-sm-7"><label class="form-label" for="c-pool">Pool</label>
            <select class="form-select" id="c-pool" name="pool" data-pool-select required>
              <?php foreach ($poolForms as $pf): ?><option value="<?= e($pf['code']) ?>"><?= e($pf['name']) ?><?= $pf['active'] ? '' : ' (đang tạm dừng)' ?></option><?php endforeach; ?>
            </select></div>
          <div class="col-sm-5"><label class="form-label" for="c-ref">Mã đơn</label>
            <input class="form-control mono" id="c-ref" name="ref" value="TEST-<?= e(vntime(time(), 'ymd-His')) ?>" maxlength="80" pattern="[A-Za-z0-9_.:\-]{1,80}" required></div>
        </div>
        <div data-job-fields></div>
        <div class="mt-4"><label class="form-label" for="c-note">Ghi chú (tuỳ chọn)</label><input class="form-control" id="c-note" name="note" maxlength="500"></div>
        <div class="alert alert-danger mt-4 mb-0 ajax-error" role="alert" hidden></div>
      </div>
      <div class="modal-footer"><button type="button" class="btn btn-label-secondary" data-bs-dismiss="modal">Đóng</button><button class="btn btn-primary"><i class="ti tabler-plus me-1"></i>Tạo đơn</button></div>
    </form>
  </div></div>
</div>
<?php endif; ?>
