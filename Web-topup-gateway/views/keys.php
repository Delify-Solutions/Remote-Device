<div class="page-head">
  <div><h4 class="mb-1">Khoá API &amp; webhook</h4><p class="mb-0 text-body-secondary">Khoá <b>Shop</b> cho website bán hàng, khoá <b>Tool</b> cho máy nạp. Máy chủ chỉ lưu bản băm — khoá rõ hiện <b>một lần</b> khi tạo/đổi.</p></div>
</div>

<?php if (!empty($newKey['plain'])): ?>
<div class="card border border-primary mb-6"><div class="card-body">
  <h5 class="mb-3"><i class="ti tabler-key text-primary me-1"></i>Khoá mới — chép ngay, sẽ không hiện lại</h5>
  <div class="secret"><span id="newkey"><?= e($newKey['plain']) ?></span><button type="button" class="btn btn-sm btn-primary" data-copy="#newkey"><i class="ti tabler-copy me-1"></i>Chép</button></div>
  <p class="form-text mb-0 mt-2">Dùng trong header: <code>Authorization: Bearer &lt;khoá&gt;</code></p>
</div></div>
<?php endif; ?>

<div class="card mb-6">
  <h5 class="card-header">Tạo khoá</h5>
  <div class="card-body">
    <form method="post" action="/admin/keys/create" class="row g-4 align-items-end">
      <?= Csrf::field() ?>
      <div class="col-md-3"><label class="form-label">Loại</label>
        <select class="form-select" name="kind"><?php foreach (Keys::KINDS as $k => $label): ?><option value="<?= e($k) ?>"><?= e($label) ?></option><?php endforeach; ?></select></div>
      <div class="col-md-3"><label class="form-label">Tên gợi nhớ</label>
        <input class="form-control" type="text" name="name" placeholder="vd: Shop ABC" required></div>
      <div class="col-md-4"><label class="form-label">Webhook URL (chỉ khoá Shop, tuỳ chọn)</label>
        <input class="form-control" type="url" name="webhook_url" placeholder="https://shop.example.com/api/gateway/webhook"></div>
      <div class="col-md-2"><button class="btn btn-primary w-100"><i class="ti tabler-plus me-1"></i>Tạo khoá</button></div>
    </form>
  </div>
</div>

<?php foreach (Keys::KINDS as $kind => $kindLabel): $list = array_values(array_filter($keys, static fn ($k) => $k['kind'] === $kind)); ?>
<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center">
    <h5 class="card-title mb-0"><i class="ti <?= $kind === 'shop' ? 'tabler-building-store' : 'tabler-device-mobile' ?> me-1 text-body-secondary"></i><?= e($kindLabel) ?></h5>
    <small class="text-body-secondary"><?= count($list) ?> khoá</small>
  </div>
<?php if (!$list): ?><div class="empty">Chưa có khoá loại này.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table mb-0 align-middle"><thead><tr><th>Tên</th><th>Khoá</th><?php if ($kind === 'shop'): ?><th>Webhook</th><?php endif; ?><th>Gọi lần cuối</th><th>Trạng thái</th><th></th></tr></thead><tbody>
  <?php foreach ($list as $k): $online = $k['last_seen_at'] && (int) $k['last_seen_at'] > time() - 120; ?>
    <tr>
      <td><span class="fw-medium text-heading"><?= e($k['name']) ?></span><div class="small text-body-secondary">tạo <?= e(vntime((int) $k['created_at'], 'd/m/Y')) ?></div></td>
      <td class="mono text-nowrap"><?= e($k['key_prefix']) ?>…</td>
      <?php if ($kind === 'shop'): ?>
      <td style="min-width:340px">
        <form method="post" action="/admin/keys/<?= (int) $k['id'] ?>/webhook" class="input-group input-group-sm"><?= Csrf::field() ?>
          <input class="form-control" type="url" name="webhook_url" value="<?= e($k['webhook_url']) ?>" placeholder="https://… (để trống = không gửi)"><button class="btn btn-label-secondary">Lưu</button></form>
        <div class="small text-body-secondary mt-2">Secret ký webhook:
          <code id="sec<?= (int) $k['id'] ?>" hidden><?= e($k['secret']) ?></code>
          <button type="button" class="btn btn-xs btn-text-secondary" data-reveal="#sec<?= (int) $k['id'] ?>">Hiện</button>
          <button type="button" class="btn btn-xs btn-text-secondary" data-copy="#sec<?= (int) $k['id'] ?>">Chép</button></div>
      </td>
      <?php endif; ?>
      <td class="small text-nowrap"><span class="live-dot <?= $online ? 'on' : '' ?>"></span><?= e(ago($k['last_seen_at'] ? (int) $k['last_seen_at'] : null)) ?></td>
      <td><?= (int) $k['active'] ? '<span class="badge bg-label-success">hoạt động</span>' : '<span class="badge bg-label-danger">đã khoá</span>' ?></td>
      <td class="text-end text-nowrap">
        <form method="post" action="/admin/keys/<?= (int) $k['id'] ?>/rotate" class="d-inline" data-confirm="Đổi khoá «<?= e($k['name']) ?>»? Khoá cũ CHẾT NGAY — bên đang dùng phải cập nhật khoá mới."><?= Csrf::field() ?><button class="btn btn-sm btn-label-secondary"><i class="ti tabler-refresh me-1"></i>Đổi khoá</button></form>
        <form method="post" action="/admin/keys/<?= (int) $k['id'] ?>/toggle" class="d-inline"><?= Csrf::field() ?><button class="btn btn-sm btn-label-secondary"><i class="ti <?= (int) $k['active'] ? 'tabler-lock' : 'tabler-lock-open' ?> me-1"></i><?= (int) $k['active'] ? 'Khoá lại' : 'Mở lại' ?></button></form>
        <form method="post" action="/admin/keys/<?= (int) $k['id'] ?>/delete" class="d-inline" data-confirm="Xoá khoá «<?= e($k['name']) ?>»?"><?= Csrf::field() ?><button class="btn btn-sm btn-icon btn-label-danger" title="Xoá khoá"><i class="ti tabler-trash"></i></button></form>
      </td>
    </tr>
  <?php endforeach; ?></tbody></table>
  </div>
<?php endif; ?>
</div>
<?php endforeach; ?>
