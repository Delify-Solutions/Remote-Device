<?php
// máy chọn được = máy tool đã báo, thuộc ít nhất một pool có khai loại tiền; gom theo pool
$byPool = [];
$noPool = [];
$noCur = [];
foreach ($machines as $mc) {
    if (!$mc['pools']) { $noPool[] = $mc; continue; }
    if (!$mc['currencies']) { $k = implode(', ', $mc['pools']); $noCur[$k]['pools'] = $mc['pools']; $noCur[$k]['names'][] = $mc['name']; continue; }
    foreach ($mc['pools'] as $pc) { $byPool[$pc][] = $mc; }
}
$multiKey = count(array_unique(array_column($machines, 'key_id'))) > 1;
$sel = null;                                   // máy được chọn sẵn (vừa gửi lỗi / link ?machine=) hoặc máy đầu tiên → điền sẵn loại tiền khi chưa có JS
foreach ($byPool as $list) {
    foreach ($list as $mc) {
        if ($mc['value'] === $pick) {
            $sel = $mc;
        }
        $sel ??= $mc;
    }
}
$label = static fn (array $mc): string => $mc['name'] . ($multiKey ? ' — ' . $mc['key_name'] : '') . ' · ' . $mc['state'] . ($mc['wallet'] ? ' · đang có ví ' . $mc['wallet'] : '');
?>
<div class="page-head">
  <div><h4 class="mb-1">Ví &amp; tài khoản Apple</h4>
    <p class="mb-0 text-body-secondary">Mỗi máy nạp trả tiền bằng một tài khoản Apple. Khai số dư ở đây thì máy <b>chỉ nhận đơn mà ví đủ tiền</b> (theo giá gói ở đúng loại tiền của ví) và gateway tự trừ theo đơn. Máy không có ví nhận đơn như bình thường.</p></div>
</div>

<div class="card mb-6">
  <h5 class="card-header">Thêm ví cho một máy</h5>
  <div class="card-body">
  <?php if (!$machines): ?>
    <div class="empty py-3">Gateway chưa thấy máy nào. Mở tool và cho máy chạy kịch bản nhận đơn — máy sẽ hiện ở trang <a href="/admin/scripts">Kịch bản &amp; máy</a> rồi mới gắn ví được.</div>
  <?php else: ?>
    <?php foreach ($noCur as $names => $nc): $pcs = $nc['pools']; ?>
    <div class="alert alert-warning">Pool <b><?= e($names) ?></b> chưa có <b>loại tiền + giá gói</b><?= count($pcs) > 1 ? ' chung cho cả các pool này' : '' ?> nên máy của pool này (<?= e(implode(', ', array_unique($nc['names']))) ?>) chưa gắn ví được — máy có ví mà pool không có giá thì không nhận được đơn nào.
      <?php foreach ($pcs as $pc): if (isset($pools[$pc])): ?><a href="/admin/pools/<?= (int) $pools[$pc]['id'] ?>" class="alert-link">Khai giá cho pool <?= e($pools[$pc]['name']) ?></a> <?php endif; endforeach; ?></div>
    <?php endforeach; ?>
    <?php if ($byPool): ?>
    <form method="post" action="/admin/wallets/create" class="row g-4 align-items-end">
      <?= Csrf::field() ?>
      <div class="col-sm-6 col-lg-4"><label class="form-label" for="w-machine">Máy</label>
        <select class="form-select" id="w-machine" name="machine" required data-wallet-machine>
          <?php foreach ($byPool as $pc => $list): ?>
          <optgroup label="Pool <?= e($pools[$pc]['name'] ?? $pc) ?>">
            <?php foreach ($list as $mc): ?><option value="<?= e($mc['value']) ?>" data-cur="<?= e(implode(',', $mc['currencies'])) ?>" <?= $pick === $mc['value'] ? 'selected' : '' ?>><?= e($label($mc)) ?></option><?php endforeach; ?>
          </optgroup>
          <?php endforeach; ?>
        </select></div>
      <div class="col-sm-6 col-lg-4"><label class="form-label" for="w-apple">Tài khoản Apple đăng nhập trên máy</label>
        <input class="form-control" id="w-apple" type="text" name="apple_account" maxlength="160" placeholder="apple@example.com" required autocomplete="off"></div>
      <div class="col-6 col-lg-2"><label class="form-label" for="w-cur">Loại tiền</label>
        <select class="form-select mono" id="w-cur" name="currency" required data-wallet-cur><?php foreach ($sel['currencies'] ?? [] as $c): ?><option><?= e($c) ?></option><?php endforeach; ?></select></div>
      <div class="col-6 col-lg-2"><label class="form-label" for="w-bal">Số dư ban đầu</label>
        <input class="form-control" id="w-bal" type="text" name="balance" inputmode="decimal" placeholder="0"></div>
      <div class="col-sm-8 col-lg-9"><label class="form-label" for="w-note">Ghi chú (tuỳ chọn)</label>
        <input class="form-control" id="w-note" type="text" name="note" maxlength="200" placeholder="vd: tài khoản vùng Nhật, nạp bằng thẻ quà tặng"></div>
      <div class="col-sm-4 col-lg-3"><button class="btn btn-primary w-100"><i class="ti tabler-plus me-1"></i>Thêm ví</button></div>
    </form>
    <p class="form-text mb-0 mt-3">Chỉ hiện máy đang chạy kịch bản nhận đơn của một pool (và pool đó đã khai giá). Loại tiền = các loại tiền pool của máy đang bán. Số tiền viết như trên máy: <code>1500</code> / <code>1.500</code> (JPY) · <code>63.50</code> / <code>63,50</code> (CHF). Thêm ví mới cho một máy thì ví cũ của máy đó <b>thôi dùng</b> (mỗi máy chỉ một ví đang dùng); các đơn đang tạm giữ ở ví cũ vẫn tính vào ví cũ.</p>
    <?php endif; ?>
    <?php if ($noPool): ?>
    <p class="form-text mb-0 mt-2">Máy chưa thuộc pool nào (tool chưa báo máy chạy kịch bản nhận đơn của một pool có trên gateway): <?= e(implode(', ', array_map(static fn ($mc) => $mc['name'] . ($multiKey ? ' (' . $mc['key_name'] . ')' : ''), $noPool))) ?>.</p>
    <?php endif; ?>
  <?php endif; ?>
  </div>
</div>

<div class="card">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Các ví</h5><small class="text-body-secondary">«Còn dùng được» = số dư − tiền đang tạm giữ cho đơn chờ đối soát</small>
  </div>
<?php if (!$wallets): ?><div class="empty">Chưa có ví nào — mọi máy nhận đơn mà không kiểm tiền.</div><?php else: ?>
  <div class="table-responsive">
  <table class="table table-hover mb-0 align-middle"><thead><tr><th>Máy</th><th>Tài khoản Apple</th><th class="text-end">Số dư</th><th class="text-end">Đang giữ</th><th class="text-end">Còn dùng được</th><th>Trạng thái</th><th>Ghi sổ lần cuối</th><th></th></tr></thead><tbody>
  <?php $prev = null; foreach ($wallets as $w): $grp = $w['tool_key_id'] . '|' . $w['device']; $cur = (string) $w['currency']; ?>
    <tr class="<?= (int) $w['active'] ? '' : 'text-body-secondary' ?>">
      <td><?php if ($grp !== $prev): ?><span class="fw-medium text-heading"><?= e($w['device']) ?></span><div class="small text-body-secondary"><?= e($w['key_name'] ?? '—') ?></div><?php if (!(int) ($w['device_seen'] ?? 1)): ?><span class="badge bg-label-warning mt-1" title="Tool chưa từng báo máy có tên này dưới khoá Tool đó — gõ nhầm tên thì ví không có tác dụng và máy vẫn nhận đơn không kiểm tiền">chưa thấy máy này</span><?php endif; ?><?php endif; ?></td>
      <td><a class="fw-medium" href="/admin/wallets/<?= (int) $w['id'] ?>"><?= e($w['apple_account']) ?></a> <span class="badge bg-label-secondary mono"><?= e($cur) ?></span>
        <?php if ($w['note'] !== ''): ?><div class="small text-body-secondary"><?= e($w['note']) ?></div><?php endif; ?></td>
      <td class="text-end text-nowrap"><?= e(Money::fmt((int) $w['balance'], $cur)) ?></td>
      <td class="text-end text-nowrap"><?= $w['held'] ? e(Money::fmt($w['held'], $cur)) : '<span class="text-body-secondary">—</span>' ?></td>
      <td class="text-end text-nowrap fw-medium <?= $w['available'] < 0 ? 'text-danger' : 'text-heading' ?>"><?= e(Money::fmt($w['available'], $cur)) ?></td>
      <td><?= (int) $w['active'] ? '<span class="badge bg-label-success">đang dùng</span>' : '<span class="badge bg-label-secondary">ngừng dùng</span>' ?></td>
      <td class="small text-body-secondary text-nowrap"><?= e(ago($w['last_at'] ? (int) $w['last_at'] : null)) ?></td>
      <td class="text-end text-nowrap">
        <a class="btn btn-sm btn-label-primary" href="/admin/wallets/<?= (int) $w['id'] ?>"><i class="ti tabler-cash me-1"></i>Nạp / sổ cái</a>
        <form method="post" action="/admin/wallets/<?= (int) $w['id'] ?>/toggle" class="d-inline"<?= (int) $w['active'] ? ' data-confirm="Ngừng dùng ví này? Máy ' . e($w['device']) . ' sẽ nhận đơn mà không kiểm tiền."' : '' ?>><?= Csrf::field() ?><input type="hidden" name="back" value="list">
          <button class="btn btn-sm btn-label-secondary"><i class="ti <?= (int) $w['active'] ? 'tabler-player-pause' : 'tabler-player-play' ?> me-1"></i><?= (int) $w['active'] ? 'Ngừng dùng' : 'Dùng lại' ?></button></form>
      </td>
    </tr>
  <?php $prev = $grp; endforeach; ?></tbody></table>
  </div>
<?php endif; ?>
</div>
