<?php
/** Tài liệu API 2 chiều — dựng từ Spec (một nguồn duy nhất với mã). Giao diện Vuexy. */
$base = app_url();
$slug = static fn (string $m, string $p): string => strtolower($m) . '-' . trim(preg_replace('/[^a-z0-9]+/i', '-', explode('?', $p)[0]), '-');
$n = 0;
$code = static function (string $cap, string $text, string $extra = '') use (&$n): string {
    $n++;
    return '<div class="codebox"><div class="cap"><span>' . $cap . $extra . '</span><button type="button" class="btn btn-xs btn-text-secondary" data-copy="#code' . $n . '"><i class="ti tabler-copy me-1"></i>Chép</button></div><pre id="code' . $n . '">' . e($text) . '</pre></div>';
};
$who = ['shop' => ['info', 'khoá gws_…'], 'tool' => ['success', 'khoá gwt_…'], 'gw' => ['primary', 'gateway gửi']];
$verb = ['GET' => 'success', 'POST' => 'info'];
$stateColor = ['queued' => 'secondary', 'claimed' => 'info', 'running' => 'info', 'need_otp' => 'warning', 'done' => 'success', 'failed' => 'danger', 'review' => 'primary', 'cancelled' => 'secondary', 'expired' => 'secondary'];
// sơ đồ tuần tự
$X = ['shop' => 150, 'gw' => 470, 'tool' => 790];
$name = ['shop' => 'SHOP (website)', 'gw' => 'GATEWAY', 'tool' => 'TOOL (máy nạp)'];
$rowH = 56;
$top = 86;
$H = $top + count($flow) * $rowH + 14;
?>
<!doctype html>
<html lang="vi" class="layout-wide" dir="ltr" data-skin="default" data-bs-theme="light" data-assets-path="/assets/vuexy/" data-template="vertical-menu-template-no-customizer">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tài liệu API · Topup Gateway</title>
<link rel="icon" href="/assets/vuexy/img/favicon/favicon.ico">
<link rel="stylesheet" href="/assets/vuexy/vendor/fonts/iconify-icons.css">
<link rel="stylesheet" href="/assets/vuexy/vendor/css/core.css">
<link rel="stylesheet" href="/assets/vuexy/css/demo.css">
<link rel="stylesheet" href="/assets/app.css?v=<?= (int) @filemtime(BASE . '/public/assets/app.css') ?>">
<script src="/assets/theme.js?v=<?= (int) @filemtime(BASE . '/public/assets/theme.js') ?>"></script>
</head>
<body class="docs-body">
<header class="docs-top">
  <a class="app-brand-link" href="/docs">
    <span class="app-brand-logo demo text-primary"><i class="ti tabler-arrows-exchange" style="font-size:26px"></i></span>
    <span class="app-brand-text demo text-heading fw-bold ms-2">Topup Gateway</span>
    <span class="text-body-secondary ms-3 d-none d-sm-inline">Tài liệu API</span>
  </a>
  <span class="d-flex align-items-center gap-2">
    <button type="button" class="btn btn-icon btn-sm btn-label-secondary" id="btn-theme" title="Sáng / Tối"><i class="ti tabler-sun icon-md"></i></button>
    <?php if ($user): ?><a class="btn btn-sm btn-label-primary" href="/admin"><i class="ti tabler-arrow-left me-1"></i>Trang quản trị</a>
    <?php else: ?><a class="btn btn-sm btn-label-primary" href="/admin/login"><i class="ti tabler-login me-1"></i>Đăng nhập quản trị</a><?php endif; ?>
  </span>
</header>

<div class="container-xxl docs">
  <nav class="toc">
    <div class="grp">Bắt đầu</div>
    <a href="#overview">Tổng quan &amp; sơ đồ</a>
    <a href="#auth">Xác thực &amp; quy ước</a>
    <a href="#status">Trạng thái đơn</a>
    <a href="#rules">Nguyên tắc tiền</a>
    <?php foreach ($groups as $g): ?>
      <div class="grp"><?= e($g['title']) ?></div>
      <?php if ($g['id'] === 'webhook'): ?><a href="#webhook">Sự kiện &amp; chữ ký</a><?php endif; ?>
      <?php foreach ($g['endpoints'] as $ep): ?><a href="#<?= e($slug($ep['m'], $ep['p'])) ?>"><span class="m text-<?= $verb[$ep['m']] ?? 'secondary' ?>"><?= e($ep['m']) ?></span><?= e($ep['t']) ?></a><?php endforeach; ?>
    <?php endforeach; ?>
    <div class="grp">Thực hành</div>
    <a href="#quick">Chạy thử bằng curl</a>
    <a href="#toolloop">Vòng lặp mẫu của tool</a>
  </nav>

  <div class="docs-main">
    <section id="overview">
      <h3 class="mb-2">API trung gian nạp game</h3>
      <p>Gateway đứng giữa <b>website bán hàng</b> và <b>máy nạp</b>. Shop đẩy đơn đã thanh toán (tài khoản game + gói cần mua); máy nào <b>trống</b> thì tự xin việc, đăng nhập, mua gói; nếu game đòi <b>OTP</b> thì gateway chuyển yêu cầu về shop để khách nhập, rồi chuyển mã lại cho máy; xong thì máy gửi <b>ảnh + kết quả</b> để shop hiển thị cho khách xem và tải về.</p>
      <div class="card mb-4"><div class="card-body">
        <svg class="seq" viewBox="0 0 940 <?= $H ?>" role="img" aria-label="Sơ đồ luồng giữa Shop, Gateway và Tool">
          <?php foreach ($X as $k => $x): ?>
            <line class="lane" x1="<?= $x ?>" y1="52" x2="<?= $x ?>" y2="<?= $H - 6 ?>"/>
            <rect class="box" x="<?= $x - 95 ?>" y="8" width="190" height="40" rx="10"/>
            <text class="t-<?= $k ?>" x="<?= $x ?>" y="33" text-anchor="middle" font-size="14" font-weight="700"><?= e($name[$k]) ?></text>
          <?php endforeach; ?>
          <?php foreach ($flow as $i => [$from, $to, $label, $note]):
              $y = $top + $i * $rowH; $x1 = $X[$from]; $x2 = $X[$to]; $dir = $x2 > $x1 ? 1 : -1; $mid = ($x1 + $x2) / 2; ?>
            <text class="lbl t-<?= $from ?>" x="<?= $mid ?>" y="<?= $y - 8 ?>" text-anchor="middle"><?= e($label) ?></text>
            <line class="a-<?= $from ?>" x1="<?= $x1 ?>" y1="<?= $y ?>" x2="<?= $x2 - 9 * $dir ?>" y2="<?= $y ?>" stroke-width="2"/>
            <polygon class="a-<?= $from ?>" points="<?= $x2 ?>,<?= $y ?> <?= $x2 - 11 * $dir ?>,<?= $y - 5 ?> <?= $x2 - 11 * $dir ?>,<?= $y + 5 ?>"/>
            <circle class="a-<?= $from ?>" cx="<?= $x1 ?>" cy="<?= $y ?>" r="3.5"/>
            <text class="note" x="<?= $mid ?>" y="<?= $y + 17 ?>" text-anchor="middle"><?= e($note) ?></text>
          <?php endforeach; ?>
        </svg>
      </div></div>
      <p class="text-body-secondary small">Mũi tên <b class="text-info">xanh dương</b> = shop gọi · <b class="text-success">xanh lá</b> = tool gọi · <b class="text-primary">tím</b> = gateway gọi về shop (webhook). Gateway <b>không bao giờ gọi ra tool</b>.</p>
    </section>

    <section id="auth">
      <h4>Xác thực &amp; quy ước</h4>
      <div class="card"><div class="card-body">
        <ul class="mb-0 ps-4">
          <li>Địa chỉ gốc: <code><?= e($base) ?></code></li>
          <li>Mọi request kèm header <code>Authorization: Bearer &lt;khoá&gt;</code>. Khoá shop bắt đầu bằng <code>gws_</code>, khoá tool bằng <code>gwt_</code> — tạo ở <i>Trang quản trị → Khoá API</i>. Khoá chỉ hiện một lần; lộ khoá thì bấm «Đổi khoá» (khoá cũ chết ngay).</li>
          <li>Thân và phản hồi là <b>JSON UTF-8</b> (riêng API gửi ảnh thì thân là ảnh thô). Thời gian dạng ISO 8601 UTC, vd <code>2026-12-05T03:04:05Z</code>.</li>
          <li>Thành công: <code>{"ok": true, …}</code>. Lỗi: <code>{"ok": false, "error": "ma_loi", "message": "giải thích tiếng Việt"}</code> kèm mã HTTP tương ứng.</li>
          <li><code>401</code> sai/thiếu khoá · <code>404</code> không tìm thấy · <code>409</code> mâu thuẫn trạng thái (<b>không có gì thay đổi</b>, đừng gửi lại) · <code>422</code> dữ liệu sai · <code>429</code> sai khoá quá nhiều · <code>5xx</code> lỗi tạm thời (<b>gửi lại y nguyên</b> được).</li>
          <li><code>{id}</code> trong đường dẫn là <code>job.id</code> gateway cấp (vd <code>J9F2C4A7B1D3E5F60</code>), không phải mã đơn của shop (<code>ref</code>).</li>
        </ul>
      </div></div>
    </section>

    <section id="status">
      <h4>Trạng thái đơn</h4>
      <div class="states">
        <span class="badge bg-label-secondary">queued</span><span class="arrow">→</span><span class="badge bg-label-info">claimed</span><span class="arrow">→</span><span class="badge bg-label-info">running</span>
        <span class="arrow">⇄</span><span class="badge bg-label-warning">need_otp</span><span class="arrow">→</span><span class="badge bg-label-success">done</span><span class="arrow">/</span><span class="badge bg-label-danger">failed</span><span class="arrow">/</span><span class="badge bg-label-primary">review</span>
      </div>
      <div class="card mb-3"><div class="table-responsive"><table class="table mb-0">
        <thead><tr><th>status</th><th>Tên</th><th>Ý nghĩa &amp; việc cần làm</th></tr></thead><tbody>
        <?php foreach ($statuses as [$s, $label, $desc]): ?>
          <tr><td><span class="badge bg-label-<?= $stateColor[$s] ?? 'secondary' ?> mono"><?= e($s) ?></span></td><td class="text-nowrap fw-medium text-heading"><?= e($label) ?></td><td><?= preg_replace('/`([^`]+)`/', '<code>$1</code>', e($desc)) ?></td></tr>
        <?php endforeach; ?></tbody></table></div></div>
      <p class="text-body-secondary small">Ngoài <code>status</code> còn có <code>stage</code> (bước chi tiết do tool tự đặt: <code>login</code>, <code>logged_in</code>, <code>purchasing</code>…) và khối <code>otp</code> (<code>state</code>: none · waiting · submitted · read).</p>
    </section>

    <section id="rules">
      <h4>Nguyên tắc tiền (đừng nới)</h4>
      <div class="card"><div class="card-body"><ol class="mb-0 ps-4">
        <li><b>Một <code>ref</code> = một đơn.</b> Shop gửi lại cùng <code>ref</code> bao nhiêu lần cũng chỉ có một đơn → mất mạng cứ gửi lại.</li>
        <li><b>Một đơn chỉ giao cho máy đúng một lần.</b> Không có lệnh «giao lại»; đơn hỏng muốn nạp lại thì shop tạo đơn mới với <code>ref</code> mới.</li>
        <li><b><code>failed</code> nghĩa là CHƯA mất tiền.</b> Tool chỉ báo <code>failed</code> khi chắc chắn chưa gửi lệnh mua nào. Không chắc → <code>review</code>.</li>
        <li><b>Gateway không tự hoàn tiền, không tự nạp lại.</b> Đơn <code>review</code> do admin gateway chốt thành <code>done</code>/<code>failed</code>; shop chỉ hoàn tiền khi nhận <code>failed</code>/<code>expired</code>/<code>cancelled</code>.</li>
        <li><b>Thông tin đăng nhập + OTP</b> được mã hoá khi lưu, chỉ giao cho máy nhận đơn, và <b>bị xoá ngay khi đơn kết thúc</b>. Webhook và API shop không bao giờ trả lại chúng.</li>
      </ol></div></div>
    </section>

    <?php foreach ($groups as $g): [$wc, $wl] = $who[$g['badge']] ?? ['secondary', '']; ?>
    <section id="<?= e($g['id']) ?>">
      <h4 class="d-flex align-items-center flex-wrap gap-2"><?= e($g['title']) ?> <span class="badge bg-label-<?= $wc ?>"><?= e($wl) ?></span></h4>
      <p><?= $g['intro'] ?></p>

      <?php if ($g['id'] === 'webhook'): ?>
        <div class="card mb-6"><h5 class="card-header">Sự kiện</h5><div class="table-responsive"><table class="table mb-0 params"><tbody>
          <?php foreach ($g['events'] as [$ev, $desc]): ?><tr><td><?= e($ev) ?></td><td><?= $desc ?></td></tr><?php endforeach; ?>
        </tbody></table></div></div>
        <div class="card mb-6"><h5 class="card-header">Header gửi kèm</h5><div class="table-responsive"><table class="table mb-0 params"><tbody>
          <?php foreach ($g['headers'] as [$h, $desc]): ?><tr><td><?= e($h) ?></td><td><?= $desc ?></td></tr><?php endforeach; ?>
        </tbody></table></div></div>
        <div class="two">
          <?= $code('Thân webhook (ví dụ job.need_otp)', $g['payload']) ?>
          <?= $code('Kiểm chữ ký phía shop (PHP)', $g['verify']) ?>
        </div>
      <?php endif; ?>

      <?php foreach ($g['endpoints'] as $ep): ?>
      <div class="card mb-6 ep" id="<?= e($slug($ep['m'], $ep['p'])) ?>">
        <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <div class="d-flex align-items-center flex-wrap gap-2"><span class="badge bg-label-<?= $verb[$ep['m']] ?? 'secondary' ?> mono"><?= e($ep['m']) ?></span><span class="path"><?= e($ep['p']) ?></span></div>
          <span class="fw-medium text-heading"><?= e($ep['t']) ?></span>
        </div>
        <div class="card-body">
          <p class="mt-0"><?= $ep['d'] ?></p>
          <?php if (!empty($ep['body'])): ?>
          <div class="table-responsive border rounded mb-4"><table class="table table-sm mb-0 params"><thead><tr><th>Trường</th><th>Kiểu</th><th>Mô tả</th></tr></thead><tbody>
            <?php foreach ($ep['body'] as [$f, $type, $req, $desc]): ?>
              <tr><td><?= e($f) ?><?= $req ? '<span class="req">bắt buộc</span>' : '' ?></td><td class="text-body-secondary"><?= e($type) ?></td><td><?= $desc ?></td></tr>
            <?php endforeach; ?></tbody></table></div>
          <?php endif; ?>
          <div class="two">
            <?php if (!empty($ep['req'])): ?><?= $code(($ep['reqLang'] ?? '') === 'bash' ? 'Lệnh gọi' : 'Thân gửi lên', $ep['req']) ?><?php endif; ?>
            <?php if (!empty($ep['res'])): ?><?= $code('Phản hồi ' . ($ep['resCode'] ?? 200), $ep['res']) ?><?php endif; ?>
            <?php if (!empty($ep['res2'])): ?><?= $code($ep['res2'][0], $ep['res2'][1]) ?><?php endif; ?>
          </div>
          <?php if (!empty($ep['errors'])): ?>
          <p class="small text-body-secondary mt-4 mb-0"><b>Lỗi riêng:</b>
            <?php foreach ($ep['errors'] as $i => [$c, $err, $desc]): ?><?= $i ? ' · ' : '' ?><code><?= (int) $c ?> <?= e($err) ?></code> <?= $desc ?><?php endforeach; ?></p>
          <?php endif; ?>
        </div>
      </div>
      <?php endforeach; ?>
    </section>
    <?php endforeach; ?>

    <section id="quick">
      <h4>Chạy thử bằng curl</h4>
      <p>Đóng vai cả shop lẫn tool trên cùng một máy để thấy trọn luồng (thay 2 khoá và mã pool/gói của bạn):</p>
      <?= $code('Một lượt đầy đủ: tạo đơn → nhận việc → OTP → ảnh → xong', <<<SH
API={$base}
SHOP=gws_xxx        # khoá Shop
TOOL=gwt_xxx        # khoá Tool

# 1) SHOP đẩy đơn đã thanh toán
curl -s -H "Authorization: Bearer \$SHOP" -H 'Content-Type: application/json' \$API/api/shop/jobs -d '{
  "pool":"efootball-ios", "ref":"TEST-001",
  "login":{"username":"khach@example.com","password":"MatKhau#123"},
  "items":[{"code":"coin_1050","qty":1}] }'

# 2) TOOL: máy trống xin việc  → lấy job.id trong phản hồi
curl -s -H "Authorization: Bearer \$TOOL" -H 'Content-Type: application/json' \$API/api/tool/claim \\
     -d '{"device":"iPhoneFarm-01","pool":"efootball-ios"}'
ID=J................

# 3) TOOL: game đòi OTP
curl -s -H "Authorization: Bearer \$TOOL" -H 'Content-Type: application/json' \$API/api/tool/jobs/\$ID/otp/request \\
     -d '{"message":"Mã đã gửi về email của bạn"}'

# 4) SHOP: khách nhập mã → chuyển sang
curl -s -H "Authorization: Bearer \$SHOP" -H 'Content-Type: application/json' \$API/api/shop/jobs/\$ID/otp -d '{"otp":"482913"}'

# 5) TOOL: lấy mã (chờ tối đa 20 giây)
curl -s -H "Authorization: Bearer \$TOOL" "\$API/api/tool/jobs/\$ID/otp?wait=20"

# 6) TOOL: gửi ảnh bill rồi báo xong
curl -s -H "Authorization: Bearer \$TOOL" -H 'Content-Type: image/png' --data-binary @bill.png "\$API/api/tool/jobs/\$ID/images?seq=1"
curl -s -H "Authorization: Bearer \$TOOL" -H 'Content-Type: application/json' \$API/api/tool/jobs/\$ID/result \\
     -d '{"result":"done","items":[{"code":"coin_1050","qty_done":1,"status":"done"}]}'

# 7) SHOP: đọc kết quả + link ảnh cho khách
curl -s -H "Authorization: Bearer \$SHOP" \$API/api/shop/jobs/\$ID
SH) ?>
    </section>

    <section id="toolloop">
      <h4>Vòng lặp mẫu của tool</h4>
      <p>Khung xử lý cho <b>mỗi máy</b> (giả mã). Điểm mấu chốt: <b>chỉ xin việc khi máy trống và game đã đăng xuất</b>, luôn báo kết quả, chỉ tính một lần mua khi chữ «nạp thành công» <b>xuất hiện mới</b> sau khi bấm, và phân biệt rõ <code>failed</code> (chắc chắn chưa mua gì) với <code>review</code> (không chắc). <b>iPhone Farm Manager</b> đã cài đúng vòng lặp này: tạo một kịch bản có cách chạy «nhận đơn từ gateway», chọn pool, soạn bước cho từng giai đoạn rồi bấm Chạy.</p>
      <?= $code('Giả mã — một máy', <<<'PY'
pool = GET /api/tool/pools/efootball-ios          # luật nhận diện + gói (tải 1 lần, làm mới định kỳ). Sáu danh sách bước dưới đây (login_steps … finish_steps) là của TOOL: soạn trong kịch bản nhận đơn
pool thiếu luật logged_out / login_success / purchase_success, hoặc kịch bản thiếu bước đăng nhập / mua / kết thúc → KHÔNG chạy

while True:
    if máy chưa sẵn sàng (mất Bluetooth / không chụp được màn hình): sleep(15); continue   # KHÔNG xin việc
    # game phải đang ở trạng thái CHƯA đăng nhập thì mới được xin việc (đừng để đơn của khách phát hiện hộ)
    mở game → đọc màn hình:  khớp rules.logged_out → được;  khớp rules.login_success → chạy finish_steps rồi kiểm lại;
                             vẫn không ra logged_out → DỪNG MÁY chờ người

    r = POST /api/tool/claim {device, pool}       # máy trống → xin việc
    if not r.job: sleep(5); continue
    job = r.job
    if r.resumed:                                 # gateway nói máy này ĐANG giữ đơn dở
        if tool có ghi chép là đã chạm bước mua, hoặc job.status != "claimed" mà tool không có ghi chép:
            result("review", "Tool bị gián đoạn — cần đối soát");  DỪNG MÁY       # tuyệt đối không chạy lại từ đầu
        # còn lại (tool tắt trước khi mua / phản hồi claim bị mất, job.status vẫn "claimed") → làm từ đầu là an toàn
    ghi sổ cục bộ (bền qua khởi động lại): máy này giữ job.id, giai đoạn "claimed"

    đã_chạm_mua = False;  lần_xin = job.otp.seq
    try:
        progress("login");  chạy login_steps với job.login
            # NGAY TRƯỚC bước gõ đầu tiên: phải THẤY rules.logged_out. Thấy rules.login_success = phiên khách trước
            # còn sót → không gõ, result("failed"), DỪNG MÁY.
        chờ tới khi OCR(màn hình) khớp một trong: rules.login_fail | rules.need_otp | rules.login_success
        if login_fail:  result("failed", "Sai tài khoản/mật khẩu");  → finally

        if need_otp:
            reason = "first"
            while True:
                lần_xin += 1
                r = POST …/otp/request {reason, attempt: lần_xin}     # mất phản hồi → gửi lại CÙNG attempt (không tốn lượt)
                if r.error == "otp_limit": result("failed", "Hết lượt OTP");  → finally
                otp = chờ GET …/otp?wait=20  cho tới khi state = ready | expired
                if state == "expired": reason = "expired"; continue
                chạy otp_steps với {{otp}}               # rỗng = gõ mã rồi Enter
                if khớp(OCR(), rules.otp_wrong): reason = "wrong"; continue
                break

        progress("logged_in");  chạy nav_steps
        for gói in job.items (lặp theo qty):
            progress("purchasing")                       # 409 = gateway đã đóng đơn → dừng (đã mua gì thì vẫn báo "review")
            # màn hình phải SẠCH chữ rules.purchase_success trước khi mua (hộp thoại lần trước chưa đóng thì không thể
            # biết chữ đó là của lần nào) → còn chữ: dừng mua, báo số đã mua thật.
            if khớp(OCR(), rules.purchase_success): result("review" nếu đã mua vài gói, ngược lại "failed");  → finally
            ghi sổ cục bộ: giai đoạn "purchasing"        # TRƯỚC khi bấm
            #  ↓↓↓  từ lệnh bấm/gõ đầu tiên của bước mua (kể cả khi lệnh ném lỗi giữa chừng), KHÔNG được báo failed nữa  ↓↓↓
            đã_chạm_mua = True
            chạy purchase_steps                          # dò ô có chữ gói.ocr_text rồi bấm mua
            chờ tới khi XUẤT HIỆN MỚI: rules.purchase_success | rules.package_unavailable | rules.purchase_fail
            if purchase_success:    đã_chạm_mua = False;  chụp bill → POST …/images?seq=n;  chạy after_purchase_steps;  continue
            if package_unavailable | purchase_fail:      # game báo RÕ là không trừ tiền (gói 1-lần đã mua / thanh toán bị từ chối)
                ghi nhận "unavailable" | "failed" cho gói này;  dừng mua
                result("failed" nếu chưa mua được gói nào,  ngược lại "review" kèm chi tiết từng gói);  → finally
            result("review", "Không xác nhận được kết quả mua");  → finally     # không thấy gì rõ ràng → dừng, không mua tiếp

        result("done", items=[…])                  # mua đủ mọi gói, đã gửi đủ ảnh trước đó
    except lỗi bất ngờ:
        result("review" nếu đã_chạm_mua,  ngược lại "failed")
    finally:
        if kết quả là "review": DỪNG MÁY, giữ nguyên màn hình cho người đối soát (lần chạy lại sẽ tự đăng xuất)
        else: chạy finish_steps                    # đăng xuất — hỏng thì DỪNG MÁY
PY) ?>
      <p class="text-body-secondary small mt-3">Trong lúc chạy, cứ ~30–60 giây gọi <code>POST /api/tool/heartbeat</code> với <code>active</code> = các đơn đang giữ để gateway biết tool còn sống. Mất mạng lúc báo kết quả thì <b>gửi lại y nguyên</b> cho tới khi nhận 200 hoặc 409 — đừng nhận đơn mới khi đơn cũ chưa báo xong.</p>
      <p class="text-body-secondary small mb-0">Song song với vòng lặp trên, tool gọi <code>POST /api/tool/sync</code> mỗi ~20 giây (và ngay khi có thay đổi) để báo <b>máy nào đang rảnh ở kịch bản nào</b> cùng <b>danh mục kịch bản</b> soạn trong tool. Gateway không gọi được vào tool (tool nằm trong mạng nội bộ) nên đây là nguồn duy nhất của trang <b>Kịch bản &amp; máy</b>.</p>
    </section>
  </div>
</div>
<script src="/assets/app.js?v=<?= (int) @filemtime(BASE . '/public/assets/app.js') ?>"></script>
</body>
</html>
