<?php
$cfg = $pool['cfg'];
$sel = static function (array $opts, string $cur): string {
    $h = '';
    foreach ($opts as $v => $label) {
        $h .= '<option value="' . e((string) $v) . '"' . ((string) $v === $cur ? ' selected' : '') . '>' . e($label) . '</option>';
    }
    return $h;
};
$yn = ['1' => 'Có', '0' => 'Không'];
// ô nhập / ô chọn cỡ nhỏ cho các dòng lặp
$in = static fn (string $name, mixed $value, string $ph = '', string $extra = ''): string
    => '<input class="form-control form-control-sm" type="text" name="' . $name . '" value="' . e((string) $value) . '" placeholder="' . e($ph) . '"' . ($extra !== '' ? ' ' . $extra : '') . '>';
$dd = static fn (string $name, array $opts, string $cur, string $title = ''): string
    => '<select class="form-select form-select-sm" name="' . $name . '"' . ($title !== '' ? ' title="' . e($title) . '"' : '') . '>' . $sel($opts, $cur) . '</select>';
$tools = '<span class="row-tools">'
    . '<button type="button" class="btn btn-sm btn-icon btn-text-secondary row-up" title="Đưa lên"><i class="ti tabler-arrow-up"></i></button>'
    . '<button type="button" class="btn btn-sm btn-icon btn-text-danger row-del" title="Xoá dòng"><i class="ti tabler-x"></i></button></span>';

$rowField = static function (array $f) use ($in, $dd, $yn, $tools): string {
    return '<div class="rep-row cols-lf">'
        . $in('lf_key[]', $f['key'] ?? '', 'username', 'pattern="[a-z][a-z0-9_]*" title="chữ thường, số, gạch dưới"')
        . $in('lf_label[]', $f['label'] ?? '', 'Tài khoản')
        . $dd('lf_type[]', Pools::FIELD_TYPES, (string) ($f['type'] ?? 'text'))
        . $dd('lf_required[]', $yn, !empty($f['required']) ? '1' : '0')
        . $dd('lf_secret[]', $yn, !empty($f['secret']) ? '1' : '0')
        . $in('lf_hint[]', $f['hint'] ?? '', 'Gợi ý cho khách')
        . $in('lf_options[]', implode(', ', (array) ($f['options'] ?? [])), 'A, B, C (nếu là danh sách)')
        . $tools . '</div>';
};
$rowRule = static function (array $r) use ($in, $dd, $tools): string {
    return '<div class="rep-row cols-ru">'
        . $dd('ru_when[]', Pools::RULE_WHEN, (string) ($r['when'] ?? 'login_success'))
        . $in('ru_value[]', $r['value'] ?? '', 'Chữ thấy trên màn hình (OCR)')
        . $in('ru_note[]', $r['note'] ?? '', 'Ghi chú')
        . $tools . '</div>';
};
// các loại tiền đang có cột giá trong form (ví tài khoản Apple trả bằng loại tiền nào thì đơn lấy giá ở cột đó)
$curCols = !empty($wallets) ? array_values((array) ($pool['pk_cols'] ?? $cfg['currencies'])) : [];
// ô giá của MỘT loại tiền trong một dòng gói (JS dựng y hệt khi gõ thêm loại tiền — xem khối «POOL: loại tiền» trong app.js)
$priceCell = static function (string $c, array $pp) use ($in): string {
    return '<span class="pp-cur" data-cur="' . e($c) . '">'
        . '<label class="pp"><span class="pp-cap">' . e(Money::label($c)) . ' · giá</span>'
        . $in('pp_' . $c . '_amount[]', $pp['amount'] ?? '', Money::decimals($c) === 0 ? '1500' : '63.00', 'inputmode="decimal"') . '</label>'
        . '<label class="pp"><span class="pp-cap">' . e(Money::label($c)) . ' · chữ hiện trên máy</span>'
        . $in('pp_' . $c . '_display[]', $pp['display'] ?? '', Money::example($c)) . '</label></span>';
};
$rowPk = static function (array $p) use ($in, $dd, $tools, $curCols, $priceCell, $wallets): string {
    $prices = '';
    foreach ($curCols as $c) {
        $prices .= $priceCell($c, (array) ($p['prices'][$c] ?? []));
    }
    return '<div class="rep-row cols-pk">'
        . '<input type="hidden" name="pk_id[]" value="' . e((string) ($p['id'] ?? '')) . '">'
        . $in('pk_code[]', $p['code'] ?? '', 'coin_1050')
        . $in('pk_name[]', $p['name'] ?? '', '1050 eFootball Coins')
        . $in('pk_ocr[]', $p['ocr_text'] ?? '', '1050|1,050')
        . $in('pk_price[]', $p['price_text'] ?? '', '249.000', 'title="Chữ giá (mặc định, khi không có giá theo loại tiền)"')
        . $dd('pk_limit[]', Pools::LIMIT_TYPES, (string) ($p['limit_type'] ?? 'multi'))
        . '<input class="form-control form-control-sm" type="number" name="pk_max[]" value="' . e((string) ($p['max_qty'] ?? 0)) . '" min="0" max="99" title="0 = không giới hạn (tối đa 99)">'
        . $dd('pk_active[]', ['1' => 'Bán', '0' => 'Tắt'], !isset($p['active']) || !empty($p['active']) ? '1' : '0')
        . $tools
        . (!empty($wallets) ? '<div class="pk-prices">' . $prices . '</div>' : '')
        . '</div>';
};
$addBtn = static fn (string $tpl, string $into, string $label): string
    => '<button type="button" class="btn btn-sm btn-label-primary mt-3" data-add="' . $tpl . '" data-into="' . $into . '"><i class="ti tabler-plus me-1"></i>' . e($label) . '</button>';
?>
<div class="page-head">
  <div><h4 class="mb-1"><?= $pool['id'] ? 'Sửa pool: ' . e($pool['name']) : 'Tạo pool' ?></h4>
    <p class="mb-0 text-body-secondary">Cấu hình ở đây là <b>nguồn duy nhất</b>: shop đọc để biết bắt khách nhập gì, tool đọc để biết đăng nhập / nhận diện / mua gói thế nào.</p></div>
  <a class="btn btn-label-secondary" href="/admin/pools"><i class="ti tabler-arrow-left me-1"></i>Danh sách pool</a>
</div>
<?php if (!empty($error)): ?><div class="alert alert-danger d-flex align-items-center" role="alert"><i class="ti tabler-alert-triangle me-2"></i><div><?= e($error) ?></div></div><?php endif; ?>
<?php if (!empty($missing)): ?>
<div class="alert alert-warning" role="alert">
  <div class="fw-medium mb-1"><i class="ti tabler-alert-triangle me-1"></i>Pool chưa đủ cấu hình — máy nạp sẽ KHÔNG nhận đơn của pool này cho tới khi bổ sung:</div>
  <ul class="mb-0 ps-4"><?php foreach ($missing as $m): ?><li><?= e($m) ?></li><?php endforeach; ?></ul>
</div>
<?php endif; ?>

<form method="post" action="/admin/pools/save">
  <?= Csrf::field() ?><input type="hidden" name="id" value="<?= (int) $pool['id'] ?>">

  <div class="card mb-6">
    <h5 class="card-header">Thông tin chung</h5>
    <div class="card-body">
      <div class="row g-5">
        <div class="col-md-6 col-xl-3"><label class="form-label">Tên pool</label>
          <input class="form-control" type="text" name="name" value="<?= e($pool['name']) ?>" placeholder="eFootball (iOS) — Konami ID" required></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Mã pool (dùng trong API)</label>
          <input class="form-control mono" type="text" name="code" value="<?= e($pool['code']) ?>" placeholder="efootball-ios" pattern="[a-z0-9][a-z0-9_-]+" required></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Game</label>
          <input class="form-control" type="text" name="game" value="<?= e($pool['game']) ?>" placeholder="eFootball"></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Trạng thái</label>
          <select class="form-select" name="active"><?= $sel(['1' => 'Đang nhận đơn', '0' => 'Tạm dừng'], (int) $pool['active'] ? '1' : '0') ?></select></div>
        <div class="col-md-4"><label class="form-label">Đơn chờ máy tối đa (phút)</label>
          <input class="form-control" type="number" name="queue_ttl_min" min="1" max="1440" value="<?= (int) round($cfg['queue_ttl'] / 60) ?>">
          <div class="form-text">Quá thời gian này không máy nào nhận → đơn <code>expired</code>, shop xử lý tay.</div></div>
        <div class="col-md-4"><label class="form-label">Tool im lặng tối đa (phút)</label>
          <input class="form-control" type="number" name="silent_min" min="1" max="120" value="<?= (int) round($cfg['silent_timeout'] / 60) ?>">
          <div class="form-text">Đơn đang chạy mà tool không gọi vào quá lâu → <code>review</code> (chờ đối soát).</div></div>
        <div class="col-md-4"><label class="form-label">Báo «xong» bắt buộc có ảnh</label>
          <select class="form-select" name="require_image"><?= $sel($yn, $cfg['require_image'] ? '1' : '0') ?></select>
          <div class="form-text">Bật: tool báo done mà chưa gửi ảnh nào → tự sang <code>review</code>.</div></div>
      </div>
      <?php if ($pool['id']): ?><div class="alert alert-warning mt-5 mb-0" role="alert"><i class="ti tabler-alert-triangle me-1"></i>Đổi <b>mã pool</b> sẽ làm shop/tool đang dùng mã cũ gọi sai — chỉ đổi khi chưa đấu nối.</div><?php endif; ?>
    </div>
  </div>

  <div class="card mb-6">
    <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
      <h5 class="card-title mb-0"><span class="sec-no">1</span>Trường đăng nhập</h5><small class="text-body-secondary">Shop phải gửi đúng các trường này khi tạo đơn</small></div>
    <div class="card-body">
      <div class="rep-head cols-lf"><span>Key (API)</span><span>Nhãn hiển thị</span><span>Kiểu</span><span>Bắt buộc</span><span>Bí mật</span><span>Gợi ý</span><span>Lựa chọn</span><span></span></div>
      <div class="rep" id="rep-lf"><?php foreach ($cfg['login_fields'] as $f) { echo $rowField($f); } ?></div>
      <?= $addBtn('tpl-lf', 'rep-lf', 'Thêm trường') ?>
      <div class="form-text mt-3">Trường <b>bí mật</b> (mật khẩu, mã dự phòng 2FA, cookie…) được mã hoá khi lưu, chỉ giao cho đúng máy nhận đơn, và <b>xoá ngay khi đơn kết thúc</b>. Kiểu «Mật khẩu» luôn là bí mật.</div>
    </div>
  </div>

  <div class="card mb-6">
    <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
      <h5 class="card-title mb-0"><span class="sec-no">2</span>OTP</h5><small class="text-body-secondary">Game đòi mã xác thực sau khi đăng nhập</small></div>
    <div class="card-body">
      <div class="row g-5">
        <div class="col-md-6 col-xl-3"><label class="form-label">Cho phép xin OTP</label>
          <select class="form-select" name="otp_enabled"><?= $sel($yn, $cfg['otp']['enabled'] ? '1' : '0') ?></select></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Hạn khách nhập (giây)</label>
          <input class="form-control" type="number" name="otp_timeout" min="30" max="1800" value="<?= (int) $cfg['otp']['timeout'] ?>"></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Số lần xin tối đa / đơn</label>
          <input class="form-control" type="number" name="otp_max" min="1" max="10" value="<?= (int) $cfg['otp']['max_requests'] ?>"></div>
        <div class="col-md-6 col-xl-3"><label class="form-label">Lời nhắn mặc định cho khách</label>
          <input class="form-control" type="text" name="otp_hint" value="<?= e($cfg['otp']['hint']) ?>"></div>
      </div>
      <div class="form-text mt-4">Luồng: tool gọi <code>otp/request</code> → shop nhận webhook <code>job.need_otp</code> và hiện ô nhập cho khách → shop gọi <code>…/otp</code> → tool lấy mã bằng <code>GET …/otp</code>. Mã sai thì tool xin lại (<code>reason: wrong</code>) cho tới hết số lần.</div>
    </div>
  </div>

  <div class="card mb-6">
    <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
      <h5 class="card-title mb-0"><span class="sec-no">3</span>Nhận diện trạng thái</h5><small class="text-body-secondary">Thấy chữ nào trên màn hình thì kết luận gì</small></div>
    <div class="card-body">
      <div class="rep-head cols-ru"><span>Kết luận</span><span>Khi màn hình có chữ</span><span>Ghi chú</span><span></span></div>
      <div class="rep" id="rep-ru"><?php foreach ($cfg['rules'] as $r) { echo $rowRule($r); } ?></div>
      <?= $addBtn('tpl-ru', 'rep-ru', 'Thêm luật') ?>
      <div class="form-text mt-3">Tool chụp màn hình → OCR → so với các luật này để biết <b>đăng nhập thành công hay thất bại</b>, có <b>đòi OTP</b> không, <b>nạp xong</b> chưa, gói <b>đã mua rồi</b> (không mua được nữa)… Một kết luận có thể có nhiều dòng (thấy <i>bất kỳ</i> chữ nào là khớp); một dòng có nhiều cách viết thì ngăn bằng <code>|</code>. So khớp không phân biệt hoa thường và dấu tiếng Việt.</div>
      <div class="alert alert-secondary small mt-3 mb-0" role="alert">
        <p class="mb-2"><b>Ba luật bắt buộc</b> (thiếu là máy không nhận đơn):</p>
        <ul class="mb-2 ps-4">
          <li><b>Màn hình CHƯA đăng nhập</b> — chữ chỉ có khi chưa ai đăng nhập (màn chào và form nhập tài khoản). Tool chỉ gõ tài khoản của khách khi thấy chữ này, nên không bao giờ nạp nhầm vào tài khoản của khách trước còn đăng nhập sót.</li>
          <li><b>Đăng nhập THÀNH CÔNG</b> — chữ chỉ có sau khi đã vào game.</li>
          <li><b>Nạp gói THÀNH CÔNG</b> — chữ của hộp thoại báo mua xong.</li>
        </ul>
        <p class="mb-0">Chữ của các luật về <b>kết quả mua</b> phải là chữ chỉ hiện ra <b>SAU khi bấm mua</b>. Nếu trước khi bấm mua màn hình đã có sẵn chữ «nạp thành công» (hộp thoại lần trước chưa đóng) thì tool dừng, không mua tiếp — vì không thể phân biệt lần mua mới với lần cũ.</p>
      </div>
    </div>
  </div>

  <div class="card mb-6">
    <div class="card-header"><h5 class="card-title mb-0"><span class="sec-no">4</span>Các bước thao tác</h5></div>
    <div class="card-body">
      <p class="mb-0">Bước bấm / gõ của một đơn (đăng nhập, nhập OTP, vào danh sách gói, mua, kết thúc đơn) soạn <b>trong tool</b>: iPhone Farm → <b>Nhóm &amp; Kịch bản</b> → kịch bản có cách chạy <b>«nhận đơn»</b> phục vụ pool này. Gateway chỉ giữ luật nhận diện màn hình (mục 3) và gói nạp (mục 5).</p>
      <?php if (!empty($legacy)): $parts = []; foreach ($legacy as $list => $n) { $parts[] = Pools::LEGACY_STEP_LISTS[$list] . ': ' . $n; } ?>
      <div class="alert alert-warning mt-4 mb-0 d-flex justify-content-between align-items-center flex-wrap gap-3" role="alert">
        <span>Pool này còn lưu <b><?= array_sum($legacy) ?> bước soạn ở gateway từ bản cũ</b> (<?= e(implode(' · ', $parts)) ?>). Tool tự chép chúng về kịch bản nhận đơn ở lần chạy đầu; khi kịch bản trong tool đã đủ bước thì xoá ở đây.</span>
        <button type="submit" form="drop-steps" class="btn btn-sm btn-outline-danger"><i class="ti tabler-trash me-1"></i>Xoá bước cũ</button>
      </div>
      <?php endif; ?>
    </div>
  </div>

  <div class="card mb-6">
    <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
      <h5 class="card-title mb-0"><span class="sec-no">5</span>Gói nạp</h5><small class="text-body-secondary">Mã gói là thứ shop gửi sang trong <code>items[].code</code></small></div>
    <div class="card-body">
      <?php if (!empty($wallets)): ?>
      <div class="row g-4 mb-5">
        <div class="col-md-6 col-xl-4"><label class="form-label" for="pool-cur">Loại tiền dùng trong pool</label>
          <input class="form-control mono" id="pool-cur" type="text" name="currencies" value="<?= e($pool['currencies_raw'] ?? implode(', ', $cfg['currencies'])) ?>" placeholder="JPY, CHF, USD" autocomplete="off"
            data-cur-sync data-zero="<?= e(jenc(Money::ZERO_DECIMAL)) ?>" data-alias="<?= e(jenc(Money::ALIASES)) ?>" data-sym="<?= e(jenc(Money::SYMBOLS)) ?>" data-examples="<?= e(jenc(array_combine(['JPY','CHF','DKK','SEK','NOK','USD','EUR','GBP','VND','KRW','AUD','CAD','SGD','HKD','TWD','THB','IDR','CNY'], array_map([Money::class, 'example'], ['JPY','CHF','DKK','SEK','NOK','USD','EUR','GBP','VND','KRW','AUD','CAD','SGD','HKD','TWD','THB','IDR','CNY'])))) ?>">
          <input type="hidden" name="pk_currencies" value="<?= e(implode(',', $curCols)) ?>"></div>
        <div class="col-md-6 col-xl-8 d-flex align-items-end"><div class="form-text mb-md-2">Mỗi máy trả bằng <b>một</b> loại tiền (loại tiền của ví tài khoản Apple trên máy); pool thì bán được <b>nhiều</b> loại tiền. Gõ ký hiệu hoặc tên đúng như máy hiện, ngăn bằng dấu phẩy (vd <code>¥, kr, CHF</code>) — loại tiền chỉ là nhãn để khớp ví với giá và đối soát; «¥» / «JP» tự hiểu là <code>JPY</code> — mỗi gói bên dưới hiện ngay ô <b>giá</b> + <b>chữ giá hiện trên máy</b> cho từng loại tiền. Máy có ví chỉ nhận đơn khi mọi gói của đơn có giá ở loại tiền của ví. Bỏ một loại tiền rồi lưu là xoá giá loại đó.</div></div>
      </div>
      <?php endif; ?>
      <div class="rep-head cols-pk"><span>Mã gói</span><span>Tên gói</span><span>Chữ OCR để dò</span><span>Chữ giá (mặc định, khi không có giá theo loại tiền)</span><span>Giới hạn mua</span><span>SL tối đa</span><span>Bán</span><span></span></div>
      <div class="rep" id="rep-pk"><?php foreach ($pool['pk'] as $p) { echo $rowPk($p); } ?></div>
      <?= $addBtn('tpl-pk', 'rep-pk', 'Thêm gói') ?>
      <div class="form-text mt-3"><b>Chữ OCR</b>: chữ in trên ô gói trong game để tool dò đúng gói — nhiều cách viết thì ngăn bằng <code>|</code> (vd <code>1050|1,050</code>). <b>Chữ giá</b> giúp phân biệt khi hai gói trùng tên; máy có ví thì dùng <b>chữ hiện trên máy</b> của đúng loại tiền (để trống thì dùng chữ giá mặc định).
        <b>Giá theo loại tiền</b>: số tiền một gói trừ vào ví (viết <code>1500</code> / <code>1.500</code> cho JPY, <code>63.00</code> / <code>63,00</code> cho CHF; để trống = chưa có giá loại đó). Đơn đã giao máy giữ giá lúc giao — sửa giá không đổi tiền của đơn đó.
        <b>Giới hạn mua</b>: gói «chỉ 1 lần» thì một đơn chỉ đặt được số lượng 1, và <b>mỗi tài khoản game của khách chỉ mua được một lần</b> (đơn thứ hai bị từ chối <code>already_bought</code>; đơn trước thất bại / huỷ / quá hạn thì mua lại được). <b>SL tối đa</b> = 0 là không giới hạn.</div>
    </div>
  </div>

  <div class="sticky-bar card">
    <div class="card-body d-flex justify-content-end justify-content-md-between align-items-center flex-wrap gap-3 py-3">
      <span class="small text-body-secondary d-none d-md-inline">Lưu xong là có hiệu lực ngay với đơn MỚI (đơn đã tạo giữ nguyên gói lúc tạo).</span>
      <span class="d-flex gap-2"><a class="btn btn-label-secondary" href="/admin/pools">Huỷ</a> <button class="btn btn-primary"><i class="ti tabler-device-floppy me-1"></i>Lưu pool</button></span>
    </div>
  </div>
</form>

<template id="tpl-lf"><?= $rowField([]) ?></template>
<template id="tpl-ru"><?= $rowRule([]) ?></template>
<?php if (!empty($legacy)): ?>
<form method="post" action="/admin/pools/<?= (int) $pool['id'] ?>/drop-steps" id="drop-steps" data-confirm="Xoá <?= array_sum($legacy) ?> bước cũ lưu ở gateway của pool này? Chỉ xoá khi kịch bản nhận đơn trong tool đã có đủ bước — tool đời cũ (còn lấy bước từ gateway) sẽ không nhận đơn của pool này nữa."><?= Csrf::field() ?></form>
<?php endif; ?>
<template id="tpl-pk"><?= $rowPk([]) ?></template>
