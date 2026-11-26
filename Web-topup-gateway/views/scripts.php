<?php
/**
 * Kịch bản & máy — mọi thứ ở trang này do TOOL TỰ BÁO lên qua POST /api/tool/sync (gateway không gọi được vào tool).
 * @var list<array> $tools  Tools::board()
 * @var bool $migrated
 * @var bool $hasToolKey
 */
$now = time();
$machine = static function (array $d): string {
    $label = (string) ($d['label'] ?? '');
    return '<span class="fw-medium text-heading">' . e($d['name']) . '</span>' . ($label !== '' ? ' <span class="small text-body-secondary">' . e($label) . '</span>' : '');
};
?>
<div class="page-head" data-live="15">
  <div><h4 class="mb-1">Kịch bản &amp; máy</h4>
    <p class="mb-0 text-body-secondary">Tool tự báo lên: <b>máy nào đang rảnh ở kịch bản nào</b> và <b>danh mục kịch bản</b> soạn trong tool. Gateway chỉ nạp những gì tool gửi (tự làm mới mỗi 15 giây).</p></div>
  <a class="btn btn-label-secondary" href="/docs#tool" target="_blank" rel="noopener"><i class="ti tabler-book-2 me-1"></i>API <span class="mono ms-1">/api/tool/sync</span></a>
</div>

<?php if (!$migrated): ?>
  <div class="alert alert-warning" role="alert"><i class="ti tabler-alert-triangle me-1"></i>CSDL của gateway chưa có bảng cho phần này. Chạy <code>php bin/setup.php</code> trên máy chủ (chỉ thêm bảng / cột, không đổi dữ liệu cũ) rồi tải lại trang.</div>
<?php elseif (!$tools): ?>
  <div class="card"><div class="empty">
    <?php if (!$hasToolKey): ?>Chưa có khoá Tool nào. Tạo ở trang <a href="/admin/keys">Khoá API</a>, nhập vào tool (<b>Nhóm &amp; Kịch bản → ⚙ Gateway</b>) — tool sẽ tự báo máy và kịch bản lên đây.
    <?php else: ?>Chưa có tool nào báo lên. Mở tool, nhập địa chỉ gateway + khoá Tool ở <b>Nhóm &amp; Kịch bản → ⚙ Gateway</b>; cứ ~20 giây tool tự báo một lần.<?php endif; ?>
  </div></div>
<?php endif; ?>

<?php foreach ($tools as $t): $info = $t['info']; $names = array_column($t['scripts'], null, 'uid'); ?>
<div class="card mb-6">
  <div class="card-header d-flex flex-wrap gap-2 justify-content-between align-items-center">
    <h5 class="card-title mb-0"><span class="live-dot <?= $t['fresh'] ? 'on' : '' ?>"></span><?= e($t['key']['name']) ?>
      <span class="mono small text-body-secondary ms-1"><?= e($t['key']['key_prefix']) ?>…</span></h5>
    <div class="d-flex flex-wrap gap-2 align-items-center">
      <?php if (!$t['fresh']): ?><span class="badge bg-label-secondary">tool mất kết nối</span>
      <?php elseif (($info['accepting'] ?? null) === false): ?><span class="badge bg-label-warning" title="Tool đang chạy bản web dev: báo máy và kịch bản nhưng KHÔNG nhận đơn của khách.">tool không nhận đơn<?= ($info['mode'] ?? '') === 'web' ? ' (bản web dev)' : '' ?></span>
      <?php else: ?><span class="badge bg-label-success">tool đang báo</span><?php endif; ?>
      <small class="text-body-secondary text-nowrap">báo lần cuối: <?= e(ago((int) ($info['synced_at'] ?? 0))) ?></small>
    </div>
  </div>

  <div class="card-body pb-2"><h6 class="mb-0">Kịch bản <span class="text-body-secondary fw-normal">(<?= count($t['scripts']) ?>)</span></h6></div>
  <?php if (!$t['scripts']): ?><div class="empty pt-2">Tool chưa có kịch bản nào.</div><?php else: ?>
  <div class="table-responsive">
    <table class="table table-hover mb-0"><thead><tr><th>Kịch bản</th><th>Cách chạy</th><th>Bước</th><th>Biến cần dữ liệu</th><th>Máy đang rảnh</th><th>Máy khác</th></tr></thead><tbody>
    <?php foreach ($t['scripts'] as $s): $ready = (int) $s['step_count'] > 0; ?>
      <tr>
        <td><span class="fw-medium text-heading"><?= e($s['name']) ?></span>
          <div class="small text-body-secondary">nhóm <?= e($s['group_name'] ?: $s['group_id']) ?> · <span class="mono"><?= e($s['uid']) ?></span></div></td>
        <td class="small text-nowrap"><?= $s['run_mode'] === 'loop' ? 'lặp ' . ((int) $s['loops'] > 0 ? (int) $s['loops'] . ' vòng' : 'vô hạn') : '1 lần' ?></td>
        <td><?php if ($ready): ?><span title="<?= e(implode(' → ', array_column($s['outline'], 'type'))) ?>"><?= (int) $s['step_count'] ?></span>
            <?php else: ?><span class="badge bg-label-warning" title="Kịch bản chưa có bước nào nên chưa chạy được.">chưa có bước</span><?php endif; ?></td>
        <td class="small"><?php if ($s['vars']): foreach ($s['vars'] as $v): ?><span class="badge bg-label-secondary mono me-1">{{<?= e($v) ?>}}</span><?php endforeach; else: ?><span class="text-body-secondary">—</span><?php endif; ?></td>
        <td><?php if (!$t['fresh']): ?><span class="text-body-secondary small">không rõ (tool mất kết nối)</span>
            <?php elseif (!$s['idle']): ?><span class="text-body-secondary small">không có</span>
            <?php else: foreach ($s['idle'] as $d): ?><span class="badge bg-label-success me-1" title="<?= e((string) ($d['label'] ?? '')) ?>"><?= e($d['name']) ?></span><?php endforeach; endif; ?></td>
        <td class="small"><?php if (!$s['others']): ?><span class="text-body-secondary">—</span>
            <?php else: foreach ($s['others'] as $d): [, $lb] = Tools::state($d, $now); ?><span class="text-nowrap me-2"><?= e($d['name']) ?> <span class="text-body-secondary">(<?= e($lb) ?>)</span></span><?php endforeach; endif; ?></td>
      </tr>
    <?php endforeach; ?></tbody></table>
  </div>
  <?php endif; ?>

  <div class="card-body pb-2 pt-5"><h6 class="mb-0">Máy <span class="text-body-secondary fw-normal">(<?= count($t['devices']) ?>)</span></h6></div>
  <?php if (!$t['devices']): ?><div class="empty pt-2">Tool chưa khai máy nào.</div><?php else: ?>
  <div class="table-responsive">
    <table class="table table-hover mb-0"><thead><tr><th>Máy</th><th>Trạng thái</th><th>Chạy được kịch bản</th><th>Đang chạy</th><th>Báo lần cuối</th></tr></thead><tbody>
    <?php foreach ($t['devices'] as $d): [$st, , , $note] = Tools::state($d, $now); $run = jdec($d['running'] ?? null); ?>
      <tr>
        <td><span class="live-dot <?= Tools::fresh($d, $now) ? 'on' : '' ?>"></span><?= $machine($d) ?></td>
        <td><?= device_badge($d) ?><?php if ($note !== ''): ?><div class="small text-body-secondary"><?= e($note) ?></div><?php endif; ?></td>
        <td class="small"><?php $uids = jdec($d['scripts'] ?? null); if (!$uids): ?><span class="text-body-secondary">chưa ở nhóm nào có kịch bản</span>
            <?php else: foreach ($uids as $u): $sc = $names[$u] ?? null; ?><span class="badge <?= $sc && (int) $sc['step_count'] > 0 ? 'bg-label-primary' : 'bg-label-secondary' ?> me-1"<?= $sc && (int) $sc['step_count'] === 0 ? ' title="chưa có bước"' : '' ?>><?= e($sc ? $sc['name'] : $u) ?></span><?php endforeach; endif; ?></td>
        <td class="small"><?php if ($run): ?><?= e(implode(' · ', array_filter([(string) ($run['group'] ?? ''), (string) ($run['script'] ?? '')], 'strlen'))) ?><?= !empty($run['iter']) ? ' <span class="text-body-secondary">(vòng ' . (int) $run['iter'] . ')</span>' : '' ?>
            <?php elseif ($d['job_pid']): ?><span class="mono"><?= e($d['job_pid']) ?></span><?php else: ?><span class="text-body-secondary">—</span><?php endif; ?></td>
        <td class="small text-body-secondary text-nowrap"><?= e(ago((int) $d['synced_at'])) ?></td>
      </tr>
    <?php endforeach; ?></tbody></table>
  </div>
  <?php endif; ?>
</div>
<?php endforeach; ?>
