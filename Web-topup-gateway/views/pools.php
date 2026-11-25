<div class="page-head">
  <div><h4 class="mb-1">Pool &amp; gói nạp</h4><p class="mb-0 text-body-secondary">Mỗi pool = một loại việc nạp: game + cách đăng nhập + OTP + luật nhận diện + các bước + danh sách gói.</p></div>
  <a class="btn btn-primary" href="/admin/pools/new"><i class="ti tabler-plus me-1"></i>Tạo pool</a>
</div>
<div class="card">
<?php if (!$pools): ?><div class="empty">Chưa có pool nào. Bấm <b>«Tạo pool»</b> để bắt đầu.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table table-hover mb-0"><thead><tr><th>Pool</th><th>Mã (dùng trong API)</th><th>Đăng nhập</th><th>OTP</th><th>Gói</th><th>Hàng đợi</th><th>Trạng thái</th><th></th></tr></thead><tbody>
  <?php foreach ($pools as $p): ?>
    <tr>
      <td><a class="fw-medium" href="/admin/pools/<?= (int) $p['id'] ?>"><?= e($p['name']) ?></a><div class="small text-body-secondary"><?= e($p['game']) ?></div></td>
      <td class="mono"><?= e($p['code']) ?></td>
      <td class="small"><?= e(implode(', ', array_column($p['cfg']['login_fields'], 'label')) ?: '—') ?></td>
      <td><?= $p['cfg']['otp']['enabled'] ? '<span class="badge bg-label-warning">có · ' . (int) $p['cfg']['otp']['timeout'] . 's</span>' : '<span class="badge bg-label-secondary">không</span>' ?></td>
      <td><?= (int) $p['packages'] ?></td>
      <td class="small text-nowrap"><?= (int) $p['queued'] ?> chờ · <?= (int) $p['running'] ?> đang chạy</td>
      <td><?= (int) $p['active'] ? '<span class="badge bg-label-success">đang nhận đơn</span>' : '<span class="badge bg-label-danger">tạm dừng</span>' ?>
        <?php $miss = Pools::missing($p); if ($miss): ?><div class="mt-1"><a class="badge bg-label-warning" href="/admin/pools/<?= (int) $p['id'] ?>" title="<?= e(implode(' ', $miss)) ?>"><i class="ti tabler-alert-triangle me-1"></i>thiếu cấu hình</a></div><?php endif; ?></td>
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-label-primary" href="/admin/pools/<?= (int) $p['id'] ?>"><i class="ti tabler-pencil me-1"></i>Sửa</a>
        <form method="post" action="/admin/pools/<?= (int) $p['id'] ?>/toggle" class="d-inline"><?= Csrf::field() ?>
          <button class="btn btn-sm btn-label-secondary"><i class="ti <?= (int) $p['active'] ? 'tabler-player-pause' : 'tabler-player-play' ?> me-1"></i><?= (int) $p['active'] ? 'Tạm dừng' : 'Bật lại' ?></button></form>
        <form method="post" action="/admin/pools/<?= (int) $p['id'] ?>/delete" class="d-inline" data-confirm="Xoá pool «<?= e($p['name']) ?>»? Chỉ xoá được khi pool chưa có đơn nào."><?= Csrf::field() ?>
          <button class="btn btn-sm btn-icon btn-label-danger" title="Xoá pool"><i class="ti tabler-trash"></i></button></form>
      </td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
<?php endif; ?>
</div>
