<?php
$isActive = in_array($job['status'], Jobs::ACTIVE, true) || $job['status'] === 'queued';
$actor = ['shop' => ['Shop', 'info'], 'tool' => ['Tool', 'success'], 'admin' => ['Admin', 'primary'], 'system' => ['Hệ thống', 'secondary']];
$itemStatus = ['done' => ['success', 'đã nạp'], 'unavailable' => ['warning', 'không mua được'], 'failed' => ['danger', 'lỗi'], 'skipped' => ['secondary', 'bỏ qua']];
$toolJob = ToolWallets::isToolJob($job);                       // đơn trả bằng ví của TOOL (tool giữ sổ, gateway gửi sự kiện tiền)
$held = (!empty($job['wallet_id']) || $toolJob) && ($job['wallet_state'] ?? null) === 'held';
$appleAcc = $wallet['apple_account'] ?? ($toolJob ? (string) (ToolWallets::reported((int) $job['tool_key_id'], (string) $job['device'])['apple_account'] ?? '') : '');
$queued = $job['status'] === 'queued';
$canDelete = !in_array($job['status'], Jobs::ACTIVE, true) && !($job['status'] === 'review' && $held);
// đổi trạng thái tay: đơn chờ đối soát đã có thẻ chốt riêng ở dưới, đơn chờ máy đã có nút «Huỷ đơn»
$manual = in_array($job['status'], ['queued', 'review'], true) ? [] : (Jobs::MANUAL[$job['status']] ?? []);
$walletJob = (Wallets::enabled() && !empty($job['wallet_id'])) || $toolJob;
$manualHelp = [
    'review' => 'Máy đang làm sẽ bị từ chối khi báo tiếp. Tạm giữ cả chi phí đơn trong ví; sau đó chốt «đã nạp» / «chưa nạp» như đơn chờ đối soát.',
    'failed' => 'Báo shop đơn THẤT BẠI (sửa kết quả đã chốt).' . ($walletJob ? ' Hoàn lại vào ví đúng số tiền đơn này đã trừ.' : ''),
    'done'   => 'Báo shop đơn HOÀN TẤT (sửa kết quả đã chốt).' . ($walletJob ? ' Trừ ví số tiền nhập dưới đây (nếu đơn chưa bị trừ).' : '') . ' Không kiểm lại giới hạn gói «1 lần / tài khoản».',
];
$isTest = (int) $job['shop_key_id'] === (int) ($testKeyId ?? 0);
?>
<div class="page-head" <?= $isActive ? 'data-live="6"' : '' ?>>
  <div><h4 class="mb-1 d-flex align-items-center flex-wrap gap-2">Đơn <?= e($job['ref']) ?> <?= status_badge($job['status']) ?><?= $isTest ? ' <span class="badge bg-label-warning">đơn thử</span>' : '' ?></h4>
    <p class="mb-0 text-body-secondary mono"><?= e($job['pid']) ?><?= $isActive ? ' · đang theo dõi, tự làm mới mỗi 6 giây' : '' ?></p></div>
  <div class="d-flex flex-wrap gap-2">
    <button type="button" class="btn btn-label-primary" data-bs-toggle="modal" data-bs-target="#m-edit"><i class="ti tabler-pencil me-1"></i>Sửa</button>
    <?php if ($manual): ?><button type="button" class="btn btn-label-warning" data-bs-toggle="modal" data-bs-target="#m-status"><i class="ti tabler-arrows-exchange me-1"></i>Đổi trạng thái</button><?php endif; ?>
    <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/delete" data-confirm="XOÁ HẲN đơn <?= e($job['ref']) ?>? Xoá cả ảnh và nhật ký, không lấy lại được.<?= $queued ? ' Đơn đang chờ máy sẽ bị huỷ trước (shop nhận job.cancelled).' : '' ?><?= $job['status'] === 'done' ? ' Gói «1 lần» của tài khoản này sẽ mua lại được.' : '' ?>"><?= Csrf::field() ?>
      <button class="btn btn-label-danger" <?= $canDelete ? '' : 'disabled title="Máy đang làm / đơn đang tạm giữ ví — không xoá được"' ?>><i class="ti tabler-trash me-1"></i>Xoá</button></form>
    <a class="btn btn-label-secondary" href="/admin/jobs"><i class="ti tabler-arrow-left me-1"></i>Danh sách đơn</a>
  </div>
</div>

<?php if ($job['status'] === 'review'): ?>
<div class="card border border-primary mb-6"><div class="card-body">
  <h5 class="mb-2"><i class="ti tabler-eye-check text-primary me-1"></i>Chờ đối soát — <?= e(Jobs::REVIEW_REASON[$job['review_reason']] ?? 'cần kiểm tra') ?></h5>
  <p class="text-body-secondary">Kiểm tra trong game / lịch sử nạp của tài khoản rồi chốt. Shop chỉ nhận kết quả cuối sau khi bạn bấm. <b>Gateway không tự nạp lại và không tự hoàn tiền.</b></p>
  <?php if ($held): $cur = (string) $job['currency']; ?>
  <p class="text-body-secondary">Ví <b><?= e($appleAcc !== '' ? $appleAcc : 'của máy ' . $job['device']) ?></b><?= $toolJob ? ' (tool quản lý — tool nhận kết quả chốt ở lần đồng bộ sau)' : '' ?> đang <b>tạm giữ <?= e(Money::fmt((int) $job['cost'], $cur)) ?></b> cho đơn này. Chốt «đã nạp» thì nhập số tiền <b>thật</b> đã bị trừ ở tài khoản Apple (xem lịch sử mua của tài khoản); chốt «chưa nạp» thì nhả tạm giữ.</p>
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
        <?php if (!empty($job['wallet_id']) || $toolJob): ?>
        <dt>Tài khoản Apple</dt><dd><?= $wallet ? '<a href="/admin/wallets/' . (int) $wallet['id'] . '">' . e($wallet['apple_account']) . '</a>' : e($appleAcc !== '' ? $appleAcc : '—') ?> <span class="badge bg-label-secondary mono"><?= e($job['currency']) ?></span><?= $toolJob ? ' <span class="small text-body-secondary">(ví do tool quản lý)</span>' : '' ?></dd>
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

    <div class="card">
      <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
        <h5 class="card-title mb-0">Thông tin đăng nhập của khách</h5>
        <?php if ($job['login_enc'] && $poolForm): ?>
        <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/login" data-ajax="login" id="f-login"><?= Csrf::field() ?>
          <button class="btn btn-sm btn-label-secondary"><i class="ti tabler-eye me-1"></i>Hiện</button></form>
        <?php endif; ?>
      </div>
      <div class="card-body">
      <?php if (!$job['login_enc']): ?><p class="mb-0 text-body-secondary">Đơn đã kết thúc — máy chủ đã xoá thông tin đăng nhập.</p>
      <?php elseif (!$poolForm): ?><p class="mb-0 text-body-secondary">Pool của đơn không còn.</p>
      <?php else: ?>
        <dl class="kv mb-0"><?php foreach ($poolForm['fields'] as $f): ?>
          <dt><?= e($f['label']) ?></dt><dd class="mono" data-login-key="<?= e($f['key']) ?>">••••••</dd>
        <?php endforeach; ?></dl>
        <p class="form-text mb-0 mt-3">Đang che. Bấm «Hiện» để xem — mỗi lần xem được ghi vào nhật ký đơn.</p>
      <?php endif; ?>
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

<?php if (!empty($toolEvents)): $tc = (string) $job['currency']; ?>
<div class="card mb-6">
  <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
    <h5 class="card-title mb-0">Tiền của đơn gửi cho tool</h5><a class="small" href="/admin/wallets">Ví &amp; tài khoản Apple <i class="ti tabler-chevron-right icon-xs"></i></a>
  </div>
  <div class="table-responsive">
  <table class="table mb-0 align-middle"><thead><tr><th>Lúc</th><th>Loại</th><th class="text-end">Số dư</th><th class="text-end">Tạm giữ</th><th>Gói</th><th>SL</th><th>Ghi chú</th><th>Ai ghi</th><th>Tool</th></tr></thead><tbody>
  <?php foreach ($toolEvents as $ev): [$kl, $kc] = ToolWallets::KINDS[$ev['kind']] ?? [$ev['kind'], 'secondary'];
      $sg = static fn (int $v): string => $v === 0 ? '—' : (($v > 0 ? '+' : '') . Money::fmt($v, $tc)); ?>
    <tr>
      <td class="small text-body-secondary text-nowrap"><?= e(vntime((int) $ev['created_at'])) ?></td>
      <td><span class="badge bg-label-<?= $kc ?>"><?= e($kl) ?></span></td>
      <td class="text-end text-nowrap"><?= e($sg((int) $ev['d_balance'])) ?></td>
      <td class="text-end text-nowrap"><?= e($sg((int) $ev['d_held'])) ?></td>
      <td class="mono small"><?= e($ev['package_code'] ?: '—') ?></td>
      <td><?= $ev['qty'] !== null ? (int) $ev['qty'] : '—' ?></td>
      <td class="small"><?= e($ev['note'] ?: '—') ?></td>
      <td class="text-nowrap"><?= ledger_actor((string) $ev['actor']) ?></td>
      <td><?= $ev['acked_at'] ? '<span class="badge bg-label-success">đã nhận</span>' : '<span class="badge bg-label-warning">chưa nhận</span>' ?></td>
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

<!-- Sửa đơn: đơn chờ máy sửa được hết; đơn đã giao máy / kết thúc chỉ sửa ghi chú -->
<div class="modal fade" id="m-edit" tabindex="-1" aria-labelledby="m-edit-title" aria-hidden="true">
  <div class="modal-dialog <?= $queued ? 'modal-lg modal-dialog-scrollable' : '' ?>"><div class="modal-content">
    <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/update" data-ajax="go" autocomplete="off"
      <?php if ($queued && $poolForm): ?>data-job-form="<?= e(jenc([$poolForm])) ?>" data-job-values="<?= e(jenc(['items' => array_column(array_map(static fn ($i) => ['c' => (string) $i['code'], 'q' => (int) $i['qty']], $items), 'q', 'c')])) ?>" data-job-edit="1"<?php endif; ?>>
      <?= Csrf::field() ?><input type="hidden" name="scope" value="<?= $queued && $poolForm ? 'full' : 'note' ?>">
      <div class="modal-header"><h5 class="modal-title" id="m-edit-title">Sửa đơn <?= e($job['ref']) ?></h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button></div>
      <div class="modal-body">
        <?php if ($queued && $poolForm): ?>
          <p class="text-body-secondary">Đơn còn chờ máy nên sửa được tài khoản, gói, số lượng, ghi chú<?= $isTest ? ', mã đơn' : '' ?>. Ô bí mật (mật khẩu…) để trống = giữ nguyên. Shop không được báo khi đơn bị sửa.</p>
          <div><label class="form-label" for="e-ref">Mã đơn</label><input class="form-control mono" id="e-ref" name="ref" value="<?= e($job['ref']) ?>" maxlength="80" pattern="[A-Za-z0-9_.:\-]{1,80}" required<?= $isTest ? '' : ' readonly' ?>>
            <?php if (!$isTest): ?><div class="form-text">Mã đơn của shop không đổi được — shop dùng nó để không tạo trùng đơn khi gửi lại.</div><?php endif; ?></div>
          <div data-job-fields></div>
        <?php else: ?>
          <p class="text-body-secondary">Đơn <?= $isActive ? 'đang được máy làm' : 'đã kết thúc' ?> nên chỉ sửa ghi chú.<?= $manual ? ' Muốn đổi kết quả: dùng «Đổi trạng thái».' : '' ?></p>
        <?php endif; ?>
        <div class="mt-4"><label class="form-label" for="e-note">Ghi chú</label><input class="form-control" id="e-note" name="note" maxlength="500" value="<?= e($job['note'] ?? '') ?>"></div>
        <div class="alert alert-danger mt-4 mb-0 ajax-error" role="alert" hidden></div>
      </div>
      <div class="modal-footer"><button type="button" class="btn btn-label-secondary" data-bs-dismiss="modal">Đóng</button><button class="btn btn-primary"><i class="ti tabler-check me-1"></i>Lưu</button></div>
    </form>
  </div></div>
</div>

<?php if ($manual): ?>
<div class="modal fade" id="m-status" tabindex="-1" aria-labelledby="m-status-title" aria-hidden="true">
  <div class="modal-dialog"><div class="modal-content">
    <form method="post" action="/admin/jobs/<?= (int) $job['id'] ?>/status" data-confirm="Đổi trạng thái đơn <?= e($job['ref']) ?>? Shop sẽ nhận webhook trạng thái mới.">
      <?= Csrf::field() ?>
      <div class="modal-header"><h5 class="modal-title" id="m-status-title">Đổi trạng thái đơn</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Đóng"></button></div>
      <div class="modal-body">
        <p>Hiện tại: <?= status_badge($job['status']) ?></p>
        <?php foreach ($manual as $k => $to): ?>
        <div class="form-check mb-3">
          <input class="form-check-input" type="radio" name="to" id="st-<?= e($to) ?>" value="<?= e($to) ?>" <?= $k === 0 ? 'checked' : '' ?> required>
          <label class="form-check-label" for="st-<?= e($to) ?>"><b><?= e(Jobs::LABEL[$to] ?? $to) ?></b><div class="small text-body-secondary"><?= e($manualHelp[$to] ?? '') ?></div></label>
        </div>
        <?php endforeach; ?>
        <?php if ($walletJob && in_array('done', $manual, true) && in_array($job['wallet_state'] ?? null, ['none', 'released'], true)): $cur = (string) $job['currency']; ?>
        <div class="mb-3"><label class="form-label" for="st-charge">Số tiền đã trừ ở tài khoản Apple (<?= e($cur) ?>) — chỉ dùng khi chọn «Hoàn tất»</label>
          <input class="form-control" id="st-charge" name="charge" inputmode="decimal" value="<?= e(Money::plain((int) $job['cost'], $cur)) ?>" style="max-width:12rem"></div>
        <?php endif; ?>
        <div><label class="form-label" for="st-note">Lý do (ghi vào nhật ký đơn<?= $walletJob ? ' và sổ cái ví' : '' ?>)</label><input class="form-control" id="st-note" name="note" maxlength="300"></div>
      </div>
      <div class="modal-footer"><button type="button" class="btn btn-label-secondary" data-bs-dismiss="modal">Đóng</button><button class="btn btn-warning"><i class="ti tabler-arrows-exchange me-1"></i>Đổi trạng thái</button></div>
    </form>
  </div></div>
</div>
<?php endif; ?>
