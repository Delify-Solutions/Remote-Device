<?php
declare(strict_types=1);

/**
 * Test đầu-cuối:  php bin/test-flow.php
 * Dựng gateway thật (php -S) trên CSDL SQLite tạm + một máy nhận webhook giả, rồi đóng vai
 * SHOP và TOOL gọi API qua HTTP. Không đụng dữ liệu thật, không gọi dịch vụ ngoài.
 *
 * Chạy trên MySQL/MariaDB (nơi collation từng gộp nhầm mã đơn khác hoa/thường) — dùng một CSDL RỖNG,
 * tên phải bắt đầu bằng «gwtest» (script sẽ XOÁ mọi bảng trong đó trước khi chạy):
 *   TEST_DB_DSN='mysql:host=127.0.0.1;port=3306;dbname=gwtest;charset=utf8mb4' TEST_DB_USER=root TEST_DB_PASS=… php bin/test-flow.php
 */
$tmp = sys_get_temp_dir() . '/gw-test-' . bin2hex(random_bytes(4));
mkdir($tmp . '/files', 0777, true);
$port = 18000 + random_int(0, 900);
$hookPort = $port + 1;
$env = [
    'APP_KEY' => 'test-key-' . bin2hex(random_bytes(12)), 'APP_URL' => "http://127.0.0.1:$port", 'APP_DEBUG' => 'true',
    'DB_DSN' => "sqlite:$tmp/gw.sqlite", 'STORAGE_DIR' => "$tmp/files", 'CRON_KEY' => 'cronkey123', 'DOCS_PUBLIC' => 'true',
    'TRUST_PROXY' => 'true',        // để thử giới hạn đăng nhập khi kẻ dò mật khẩu đổi IP liên tục
];
$extDsn = (string) getenv('TEST_DB_DSN');
if ($extDsn !== '') {
    if (preg_match('/dbname=gwtest[A-Za-z0-9_]*/', $extDsn) !== 1) {
        fwrite(STDERR, "TEST_DB_DSN phải trỏ vào CSDL có tên bắt đầu bằng «gwtest» (script xoá mọi bảng trong đó).\n");
        exit(2);
    }
    $env['DB_DSN'] = $extDsn;
    $env['DB_USER'] = (string) getenv('TEST_DB_USER');
    $env['DB_PASS'] = (string) getenv('TEST_DB_PASS');
}
foreach ($env as $k => $v) {
    putenv("$k=$v");
}
require dirname(__DIR__) . '/src/bootstrap.php';
if ($extDsn !== '') {
    foreach (Db::all('SHOW TABLES') as $row) {
        Db::pdo()->exec('DROP TABLE `' . str_replace('`', '', (string) array_values($row)[0]) . '`');
    }
}
echo 'CSDL: ' . Db::driver() . ($extDsn !== '' ? ' (' . Db::val('SELECT VERSION()') . ')' : ' tạm') . "\n";

$pass = 0;
$fail = 0;
function ok(bool $cond, string $name, mixed $ctx = null): void
{
    global $pass, $fail;
    if ($cond) {
        $pass++;
        echo "  ✓ $name\n";
    } else {
        $fail++;
        echo "  ✗ $name" . ($ctx !== null ? '   → ' . (is_string($ctx) ? $ctx : json_encode($ctx, JSON_UNESCAPED_UNICODE)) : '') . "\n";
    }
}
function http(string $method, string $path, ?string $key = null, mixed $body = null, array $headers = []): array
{
    global $port;
    $ch = curl_init("http://127.0.0.1:$port$path");
    $h = $headers;
    if ($key !== null) {
        $h[] = 'Authorization: Bearer ' . $key;
    }
    if (is_array($body)) {
        $body = json_encode($body);
        $h[] = 'Content-Type: application/json';
    }
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => $h, CURLOPT_TIMEOUT => 40, CURLOPT_HEADER => true]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
    }
    $raw = (string) curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $hs = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
    curl_close($ch);
    $text = substr($raw, $hs);
    return ['code' => $code, 'json' => json_decode($text, true) ?? [], 'text' => $text, 'head' => substr($raw, 0, $hs)];
}
function png(): string
{
    $im = imagecreatetruecolor(40, 60);
    imagefill($im, 0, 0, imagecolorallocate($im, 30, 120, 200));
    ob_start();
    imagepng($im);
    return (string) ob_get_clean();
}

/* ---------- dữ liệu mẫu ---------- */
Schema::migrate();
$cfg = Pools::defaults();
$cfg['otp'] = ['enabled' => true, 'timeout' => 120, 'max_requests' => 2, 'hint' => ''];
$cfg['rules'] = [['when' => 'login_success', 'value' => 'Trang chủ', 'note' => ''], ['when' => 'logged_out', 'value' => 'Konami ID', 'note' => '']];
$cfg['login_steps'] = [['type' => 'type', 'value' => '{{username}}', 'note' => '']];
// 'optional' đến từ form quản trị là chuỗi '1' / '0', từ JSON là true / false
$cfg['after_purchase_steps'] = [['type' => 'tap_text', 'value' => 'Đóng|OK', 'optional' => '1']];
$cfg['finish_steps'] = [['type' => 'tap_text', 'value' => 'Đăng xuất', 'optional' => '0'], ['type' => 'home', 'value' => '', 'optional' => true],
                        ['type' => 'khong_co_loai_nay', 'value' => 'x']];
$poolId = Pools::save(null, 'efootball-ios', 'eFootball iOS', 'eFootball', true, $cfg);
Pools::savePackages($poolId, [
    ['code' => 'coin_1050', 'name' => '1050 Coins', 'ocr_text' => '1050|1,050', 'price_text' => '249.000', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true],
    ['code' => 'starter', 'name' => 'Gói khởi đầu', 'ocr_text' => 'Starter', 'price_text' => '25.000', 'limit_type' => 'once', 'max_qty' => 0, 'active' => true],
    ['code' => 'off', 'name' => 'Gói tắt', 'limit_type' => 'multi', 'active' => false],
    ['code' => '1050', 'name' => 'Gói mã toàn số', 'limit_type' => 'multi', 'max_qty' => 3, 'active' => true],
]);
$shop = Keys::create('shop', 'Shop test', "http://127.0.0.1:$hookPort/hook");
$tool = Keys::create('tool', 'Farm test');
$shop2 = Keys::create('shop', 'Shop khác');
$SK = $shop['plain'];
$TK = $tool['plain'];
$secret = Keys::webhookSecret(Keys::find($shop['id']));

/* ---------- khởi động gateway + máy nhận webhook ---------- */
file_put_contents("$tmp/hook.php", '<?php file_put_contents(' . var_export("$tmp/hooks.log", true)
    . ', json_encode(["sig" => $_SERVER["HTTP_X_GATEWAY_SIGNATURE"] ?? "", "event" => $_SERVER["HTTP_X_GATEWAY_EVENT"] ?? "", "body" => file_get_contents("php://input")]) . "\n", FILE_APPEND | LOCK_EX); echo "ok";');
$spec = [0 => ['pipe', 'r'], 1 => ['file', "$tmp/server.log", 'a'], 2 => ['file', "$tmp/server.log", 'a']];
$procEnv = array_merge(getenv(), $env, ['PHP_CLI_SERVER_WORKERS' => '6']);
$root = dirname(__DIR__);
$srv = proc_open([PHP_BINARY, '-S', "127.0.0.1:$port", '-t', "$root/public", "$root/public/index.php"], $spec, $p1, $root, $procEnv);
$hook = proc_open([PHP_BINARY, '-S', "127.0.0.1:$hookPort", "$tmp/hook.php"], $spec, $p2, $tmp, getenv());
register_shutdown_function(static function () use ($srv, $hook, $tmp): void {
    foreach ([$srv, $hook] as $p) {
        if (is_resource($p)) {
            $pid = (int) (proc_get_status($p)['pid'] ?? 0);
            if ($pid > 0) {
                exec('pkill -P ' . $pid . ' 2>/dev/null');      // các worker con của `php -S` (không tự chết theo tiến trình chính)
            }
            proc_terminate($p);
        }
    }
    exec('rm -rf ' . escapeshellarg($tmp));
});
for ($i = 0; $i < 50; $i++) {
    usleep(100000);
    if ((http('GET', '/healthz')['json']['ok'] ?? false) === true) {
        break;
    }
}

echo "\n== Xác thực ==\n";
ok(http('GET', '/api/shop/ping')['code'] === 401, 'thiếu khoá → 401');
ok(http('GET', '/api/shop/ping', 'gws_sai')['code'] === 401, 'sai khoá → 401');
ok(http('GET', '/api/shop/ping', $TK)['code'] === 401, 'khoá tool gọi API shop → 401');
ok(http('GET', '/api/tool/ping', $SK)['code'] === 401, 'khoá shop gọi API tool → 401');
ok(http('GET', '/api/shop/ping', $SK)['code'] === 200 && http('GET', '/api/tool/ping', $TK)['code'] === 200, 'đúng khoá → 200');

echo "\n== Lược đồ ==\n";
$my = implode("\n", array_merge(...array_values(Schema::migrations('mysql'))));
ok(substr_count($my, 'utf8mb4_bin') >= 22 && preg_match('/utf8mb4_[a-z0-9_]*_ci/', $my) !== 1,
    'MySQL/MariaDB: mọi bảng so khớp CHÍNH XÁC (utf8mb4_bin) — không gộp mã đơn / tên máy khác hoa-thường, khác dấu');
ok(Schema::migrations('sqlite')[2] === [] && count(Schema::migrations('mysql')[2]) === 11, 'migration 2 đổi collation cho bản cài MySQL cũ; SQLite không cần đổi');
ok((int) Db::val('SELECT COUNT(*) FROM schema_version') === Schema::LATEST, 'đã áp đủ ' . Schema::LATEST . ' migration');

echo "\n== Pool ==\n";
$r = http('GET', '/api/shop/pools', $SK);
$pv = $r['json']['pools'][0] ?? [];
ok(($pv['code'] ?? '') === 'efootball-ios' && count($pv['packages'] ?? []) === 3, 'shop thấy pool + 3 gói đang bật (gói tắt bị ẩn)', $pv);
ok(!isset($pv['rules']) && !isset($pv['packages'][0]['ocr_text']), 'shop KHÔNG thấy luật/chữ OCR');
ok(($pv['login_fields'][1]['secret'] ?? false) === true, 'trường password được đánh dấu bí mật');
$tv = http('GET', '/api/tool/pools/efootball-ios', $TK)['json']['pool'] ?? [];
ok(($tv['rules'][0]['when'] ?? '') === 'login_success' && ($tv['packages'][0]['ocr_text'] ?? '') === '1050|1,050' && ($tv['login_steps'][0]['value'] ?? '') === '{{username}}', 'tool thấy luật + chữ OCR + các bước', $tv);
$lists = ['login_steps', 'otp_steps', 'nav_steps', 'purchase_steps', 'after_purchase_steps', 'finish_steps'];
ok(array_keys(Pools::STEP_LISTS) === $lists && !array_diff($lists, array_keys($tv)) && $tv['otp_steps'] === [] && $tv['nav_steps'] === [],
    'tool nhận đủ 6 danh sách bước (đăng nhập, OTP, vào gói, mua, sau mua, kết thúc)', array_keys($tv));
ok(($tv['login_steps'][0]['optional'] ?? null) === false && ($tv['after_purchase_steps'][0]['optional'] ?? null) === true
    && array_column($tv['finish_steps'], 'optional') === [false, true], 'cờ «bỏ qua nếu lỗi» của từng bước được giữ đúng (mặc định tắt)', $tv['finish_steps'] ?? null);
ok(count($tv['finish_steps']) === 2, 'bước có loại lạ bị loại bỏ khi lưu');
ok(!isset($pv['login_steps']) && !isset($pv['finish_steps']), 'shop KHÔNG thấy các bước thao tác');
$tl = http('GET', '/api/tool/pools', $TK);
$t0 = $tl['json']['pools'][0] ?? [];
ok($tl['code'] === 200 && ($t0['code'] ?? '') === 'efootball-ios' && ($t0['active'] ?? null) === true && ($t0['packages'] ?? 0) === 3 && !isset($t0['rules']) && !isset($t0['login_fields']),
    'tool lấy danh sách pool gọn để chọn (không kèm cấu hình)', $tl['json']);
ok(http('GET', '/api/tool/pools', $SK)['code'] === 401, 'khoá shop không đọc được danh sách pool của tool');
ok(http('GET', '/api/tool/pools/khong-co', $TK)['code'] === 404, 'tool hỏi pool không có → 404');
$miss = Pools::missing(Pools::find($poolId));
ok(count($miss) === 2 && str_contains($miss[0], 'Nạp gói THÀNH CÔNG') && str_contains($miss[1], 'mua 1 gói'),
    'trang quản trị chỉ ra pool còn thiếu gì để máy tự chạy (luật «nạp thành công», bước mua)', $miss);
ok(isset(Pools::RULE_WHEN['logged_out']) && array_keys(Pools::RULES_REQUIRED) === ['logged_out', 'login_success', 'purchase_success'], 'ba luật bắt buộc: chưa đăng nhập / đăng nhập thành công / nạp thành công');

echo "\n== Tạo đơn ==\n";
$base = ['pool' => 'efootball-ios', 'ref' => 'ORD-1', 'login' => ['username' => 'khach@example.com', 'password' => ' Mật Khẩu#1 '], 'items' => [['code' => 'coin_1050', 'qty' => 2]]];
ok(http('POST', '/api/shop/jobs', $SK, ['pool' => 'khong-co'] + $base)['code'] === 404, 'sai pool → 404');
$r = http('POST', '/api/shop/jobs', $SK, ['login' => ['username' => 'a']] + $base);
ok($r['code'] === 422 && ($r['json']['field'] ?? '') === 'password', 'thiếu mật khẩu → 422 missing_field', $r['json']);
ok(http('POST', '/api/shop/jobs', $SK, ['items' => [['code' => 'off', 'qty' => 1]]] + $base)['code'] === 422, 'gói đang tắt → 422');
ok(http('POST', '/api/shop/jobs', $SK, ['items' => [['code' => 'starter', 'qty' => 2]]] + $base)['code'] === 422, 'gói 1-lần mà qty=2 → 422');
ok(http('POST', '/api/shop/jobs', $SK, ['items' => [['code' => 'coin_1050', 'qty' => 6]]] + $base)['code'] === 422, 'vượt max_qty → 422');
ok(http('POST', '/api/shop/jobs', $SK, ['ref' => 'có dấu cách'] + $base)['code'] === 422, 'ref sai định dạng → 422');
$r = http('POST', '/api/shop/jobs', $SK, $base);
$J1 = $r['json']['job']['id'] ?? '';
ok($r['code'] === 201 && ($r['json']['job']['status'] ?? '') === 'queued' && $J1 !== '', 'tạo đơn → 201 queued', $r['json']);
ok(!isset($r['json']['job']['login']), 'phản hồi cho shop không chứa thông tin đăng nhập');
$r2 = http('POST', '/api/shop/jobs', $SK, ['items' => [['code' => 'starter', 'qty' => 1]]] + $base);
ok($r2['code'] === 200 && ($r2['json']['duplicate'] ?? false) && ($r2['json']['job']['id'] ?? '') === $J1 && $r2['json']['job']['items'][0]['code'] === 'coin_1050', 'gửi lại cùng ref → đơn cũ, không đổi gì (idempotent)');
$rA = http('POST', '/api/shop/jobs', $SK, ['ref' => 'Ord-aB3x'] + $base);
$rB = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-Ab3X', 'items' => [['code' => 'starter', 'qty' => 1]]] + $base);
ok($rA['code'] === 201 && $rB['code'] === 201 && ($rA['json']['job']['id'] ?? 'a') !== ($rB['json']['job']['id'] ?? 'a') && ($rB['json']['job']['items'][0]['code'] ?? '') === 'starter',
    'hai mã đơn chỉ khác HOA/thường là HAI đơn riêng — không gộp làm một (đơn sau không bị «nuốt»)', [$rA['code'], $rB['code'], $rB['json']['duplicate'] ?? null]);
$rN = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-NUM', 'items' => [['code' => '1050', 'qty' => 2]]] + $base);
ok($rN['code'] === 201 && str_contains($rN['text'], '"code":"1050"') && ($rN['json']['job']['items'][0]['code'] ?? null) === '1050', 'mã gói toàn chữ số vẫn là CHUỖI trong JSON (không biến thành số)', $rN['text']);
foreach ([$rA, $rB, $rN] as $x) {       // dọn để không ảnh hưởng phần «giao đúng 1 lần» bên dưới
    http('POST', '/api/shop/jobs/' . ($x['json']['job']['id'] ?? '') . '/cancel', $SK);
}
$row = Db::one('SELECT * FROM jobs WHERE pid=?', [$J1]);
ok(!str_contains((string) $row['login_enc'], 'Khẩu') && !str_contains((string) $row['login_enc'], 'khach@'), 'thông tin đăng nhập được mã hoá trong DB');
ok(http('GET', "/api/shop/jobs/$J1", $shop2['plain'])['code'] === 404, 'shop khác không xem được đơn');

echo "\n== Máy xin việc (giao đúng 1 lần) ==\n";
// 8 máy hỏi cùng lúc cho 1 đơn → đúng 1 máy nhận
$mh = curl_multi_init();
$hs = [];
for ($i = 1; $i <= 8; $i++) {
    $ch = curl_init("http://127.0.0.1:$port/api/tool/claim");
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_POSTFIELDS => json_encode(['device' => "may-$i", 'pool' => 'efootball-ios']),
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $TK, 'Content-Type: application/json']]);
    curl_multi_add_handle($mh, $ch);
    $hs[$i] = $ch;
}
do {
    curl_multi_exec($mh, $running);
    curl_multi_select($mh, 0.2);
} while ($running > 0);
$winners = [];
foreach ($hs as $i => $ch) {
    $j = json_decode((string) curl_multi_getcontent($ch), true);
    if (!empty($j['job'])) {
        $winners[$i] = $j['job'];
    }
}
ok(count($winners) === 1, '8 máy xin cùng lúc → đúng 1 máy nhận đơn', array_keys($winners));
$dev = 'may-' . array_key_first($winners);
$wj = reset($winners) ?: [];
ok(($wj['login']['password'] ?? '') === ' Mật Khẩu#1 ' && ($wj['login']['username'] ?? '') === 'khach@example.com', 'máy nhận đúng tài khoản/mật khẩu (giữ nguyên khoảng trắng)', $wj['login'] ?? null);
ok(($wj['items'][0]['ocr_text'] ?? '') === '1050|1,050' && $wj['items'][0]['qty'] === 2, 'máy nhận gói kèm chữ OCR + số lượng');
$r = http('POST', '/api/tool/claim', $TK, ['device' => $dev, 'pool' => 'efootball-ios']);
ok(($r['json']['resumed'] ?? false) === true && ($r['json']['job']['id'] ?? '') === $J1, 'máy đang giữ đơn hỏi lại → trả lại chính đơn đó (resumed)');
ok(http('POST', '/api/tool/claim', $TK, ['device' => 'may-khac', 'pool' => 'efootball-ios'])['json']['job'] === null, 'máy khác không nhận lại đơn đã giao');
$near = http('POST', '/api/tool/claim', $TK, ['device' => strtoupper($dev), 'pool' => 'efootball-ios'])['json'];
$near2 = http('POST', '/api/tool/claim', $TK, ['device' => str_replace('may', 'máy', $dev), 'pool' => 'efootball-ios'])['json'];
ok(array_key_exists('job', $near) && $near['job'] === null && empty($near['resumed']) && array_key_exists('job', $near2) && $near2['job'] === null && empty($near2['resumed']),
    'máy có tên chỉ khác HOA/thường hoặc khác DẤU không nhận lại đơn (kèm mật khẩu) của máy kia', [$near, $near2]);
ok(http('POST', "/api/shop/jobs/$J1/cancel", $SK)['code'] === 409, 'đơn đã giao → shop không huỷ được');

echo "\n== Tiến độ + OTP ==\n";
ok(http('POST', "/api/tool/jobs/$J1/progress", $TK, ['stage' => 'login'])['json']['status'] === 'running', 'báo tiến độ → running');
ok(http('POST', "/api/shop/jobs/$J1/otp", $SK, ['otp' => '123456'])['code'] === 409, 'chưa xin OTP mà shop gửi → 409');
$r = http('POST', "/api/tool/jobs/$J1/otp/request", $TK, ['message' => 'Mã gửi về email']);
ok($r['code'] === 200 && $r['json']['otp']['seq'] === 1, 'tool xin OTP → need_otp lần 1', $r['json']);
$rp = http('POST', "/api/tool/jobs/$J1/otp/request", $TK, ['attempt' => 1, 'message' => 'Mã gửi về email']);
ok($rp['code'] === 200 && ($rp['json']['replayed'] ?? false) === true && $rp['json']['otp']['seq'] === 1 && $rp['json']['otp']['state'] === 'waiting',
    'tool gửi LẠI lần xin thứ 1 (mất phản hồi) → trả lại trạng thái cũ, không tốn thêm lượt', $rp['json']);
$g = http('GET', "/api/shop/jobs/$J1", $SK)['json']['job'];
ok($g['status'] === 'need_otp' && $g['otp']['state'] === 'waiting' && $g['otp']['message'] === 'Mã gửi về email' && $g['otp']['seq'] === 1, 'shop thấy need_otp + lời nhắn (vẫn là lần xin 1)');
ok(http('GET', "/api/tool/jobs/$J1/otp", $TK)['json']['state'] === 'waiting', 'khách chưa nhập → tool nhận waiting');
ok(http('POST', "/api/shop/jobs/$J1/otp", $SK, ['otp' => '12'])['code'] === 422, 'OTP sai định dạng → 422');
ok(http('POST', "/api/shop/jobs/$J1/otp", $SK, ['otp' => '48 29 13'])['code'] === 200, 'shop gửi OTP khách nhập → 200');
$t0 = microtime(true);
$r = http('GET', "/api/tool/jobs/$J1/otp?wait=10", $TK);
ok($r['json']['state'] === 'ready' && $r['json']['otp'] === '482913' && microtime(true) - $t0 < 3, 'tool lấy được OTP ngay (đã bỏ khoảng trắng)', $r['json']);
ok(http('GET', "/api/tool/jobs/$J1/otp", $TK)['json']['otp'] === '482913', 'hỏi lại vẫn trả cùng mã (phòng mất phản hồi)');
ok(http('GET', "/api/shop/jobs/$J1", $SK)['json']['job']['status'] === 'running', 'tool lấy OTP xong → đơn quay lại running');
$r = http('POST', "/api/tool/jobs/$J1/otp/request", $TK, ['reason' => 'wrong', 'attempt' => 2]);
ok($r['json']['otp']['seq'] === 2 && empty($r['json']['replayed']) && http('GET', "/api/tool/jobs/$J1/otp", $TK)['json']['state'] === 'waiting', 'OTP sai → xin lại lần 2 (attempt mới = lượt mới), mã cũ bị xoá');
ok(http('POST', "/api/tool/jobs/$J1/otp/request", $TK, ['reason' => 'wrong'])['code'] === 409, 'quá số lần xin OTP của pool → 409 otp_limit');
// long-poll: OTP tới sau 2 giây thì tool nhận ngay khi có
$pid = pcntl_fork_safe(static function () use ($J1, $SK): void {
    sleep(2);
    http('POST', "/api/shop/jobs/$J1/otp", $SK, ['otp' => '777888']);
});
$t0 = microtime(true);
$r = http('GET', "/api/tool/jobs/$J1/otp?wait=15", $TK);
$dt = microtime(true) - $t0;
ok($r['json']['state'] === 'ready' && $r['json']['otp'] === '777888' && $dt >= 1.5 && $dt < 8, sprintf('tool CHỜ (long-poll) và nhận OTP sau %.1fs', $dt), $r['json']);

echo "\n== Ảnh + kết quả ==\n";
ok(http('POST', "/api/tool/jobs/$J1/images?seq=1", $TK, 'day khong phai anh')['code'] === 415, 'không phải ảnh → 415');
ok(http('POST', "/api/tool/jobs/$J1/images?seq=99", $TK, png())['code'] === 422, 'seq ngoài 1..30 → 422');
$r = http('POST', "/api/tool/jobs/$J1/images?seq=1&kind=bill", $TK, png(), ['Content-Type: image/png']);
ok($r['code'] === 200 && str_contains($r['json']['url'] ?? '', '/files/'), 'gửi ảnh PNG → 200 + url', $r['json']);
$r = http('POST', "/api/tool/jobs/$J1/result", $TK, ['result' => 'done', 'message' => 'Nạp đủ', 'items' => [['code' => 'coin_1050', 'qty_done' => 2, 'status' => 'done']]]);
ok($r['code'] === 200 && $r['json']['status'] === 'done', 'báo done (có ảnh) → done', $r['json']);
ok(http('POST', "/api/tool/jobs/$J1/result", $TK, ['result' => 'done'])['code'] === 200, 'báo done lần 2 → 200 (idempotent)');
ok(http('POST', "/api/tool/jobs/$J1/result", $TK, ['result' => 'failed'])['code'] === 409, 'báo failed sau khi đã done → 409');
ok(http('POST', "/api/tool/jobs/$J1/images?seq=2", $TK, png())['code'] === 409, 'gửi ảnh sau khi kết thúc → 409');
$g = http('GET', "/api/shop/jobs/$J1", $SK)['json']['job'];
ok($g['status'] === 'done' && count($g['images']) === 1 && ($g['result'][0]['qty_done'] ?? 0) === 2 && $g['finished_at'] !== null, 'shop đọc được kết quả + ảnh', $g);
$imgUrl = parse_url($g['images'][0]['url'], PHP_URL_PATH);
$f = http('GET', $imgUrl);
ok($f['code'] === 200 && str_contains($f['head'], 'image/png') && strlen($f['text']) > 50, 'link ảnh công khai mở được');
ok(str_contains(http('GET', $imgUrl . '?download=1')['head'], 'attachment; filename="ORD-1-1.png"'), 'link tải về có tên file theo mã đơn');
ok(http('GET', '/files/' . str_repeat('0', 32) . '.png')['code'] === 404, 'token ảnh sai → 404');
$row = Db::one('SELECT * FROM jobs WHERE pid=?', [$J1]);
ok($row['login_enc'] === null && $row['otp_enc'] === null, 'đơn kết thúc → thông tin đăng nhập + OTP bị XOÁ khỏi DB');
ok(!isset(http('GET', "/api/tool/jobs/$J1", $TK)['json']['job']['login']), 'tool đọc lại đơn đã xong không còn thông tin đăng nhập');

echo "\n== Huỷ / thiếu ảnh / đối soát ==\n";
$J2 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-2'] + $base)['json']['job']['id'];
ok(http('POST', "/api/shop/jobs/$J2/cancel", $SK)['json']['status'] === 'cancelled', 'huỷ đơn còn chờ → cancelled');
ok(http('POST', '/api/tool/claim', $TK, ['device' => 'may-a', 'pool' => 'efootball-ios'])['json']['job'] === null, 'đơn đã huỷ không được giao');
$J3 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-3'] + $base)['json']['job']['id'];
http('POST', '/api/tool/claim', $TK, ['device' => 'may-a', 'pool' => 'efootball-ios']);
$r = http('POST', "/api/tool/jobs/$J3/result", $TK, ['result' => 'done']);
ok($r['json']['status'] === 'review', 'báo done mà KHÔNG có ảnh → review (no_bill)', $r['json']);
ok(http('POST', "/api/tool/jobs/$J3/result", $TK, ['result' => 'failed', 'message' => 'Thật ra chưa bấm mua'])['code'] === 409, 'đang đối soát mà báo failed → 409');
$id3 = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$J3]);
$late = static fn (): array => array_column(Db::all("SELECT message FROM job_events WHERE job_id=? AND type='late_report' ORDER BY id", [$id3]), 'message');
ok(Db::val('SELECT status FROM jobs WHERE id=?', [$id3]) === 'review' && count($late()) === 1 && str_contains($late()[0], 'failed') && str_contains($late()[0], 'chưa bấm mua'),
    'lời báo failed muộn KHÔNG đổi trạng thái nhưng được ghi vào dòng thời gian cho người đối soát', $late());
http('POST', "/api/tool/jobs/$J3/result", $TK, ['result' => 'failed', 'message' => 'Thật ra chưa bấm mua']);
ok(count($late()) === 1, 'tool gửi lại y nguyên lời báo muộn → không ghi trùng');
$lr = http('POST', "/api/tool/jobs/$J3/result", $TK, ['result' => 'review', 'message' => 'Đã mua 1 trước khi đơn bị đóng', 'items' => [['code' => 'coin_1050', 'qty_done' => 1, 'status' => 'skipped']]]);
ok($lr['code'] === 200 && $lr['json']['status'] === 'review' && count($late()) === 2 && str_contains($late()[1], '[coin_1050 skipped 1]'), 'lời báo muộn ghi cả số đã mua của từng gói', $late());
ok(Jobs::adminResolve($id3, 'done', 'admin') && Db::val('SELECT status FROM jobs WHERE id=?', [$id3]) === 'done', 'admin chốt «đã nạp đủ» → done');
ok(!Jobs::adminResolve($id3, 'failed', 'admin'), 'chốt lần 2 bị từ chối');
$JA = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-ADM'] + $base)['json']['job']['id'];
$rowA = Db::one('SELECT * FROM jobs WHERE pid=?', [$JA]);
[$cc] = Jobs::cancel($rowA, 'admin');
$whA = Db::one("SELECT payload FROM webhooks WHERE event='job.cancelled' AND job_id=?", [$rowA['id']]);
ok($cc === 200 && $whA && (jdec($whA['payload'])['by'] ?? '') === 'admin' && (jdec($whA['payload'])['job']['status'] ?? '') === 'cancelled',
    'ADMIN huỷ đơn → shop được báo bằng webhook job.cancelled (by: admin)', $whA);
$J4 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-4'] + $base)['json']['job']['id'];
http('POST', '/api/tool/claim', $TK, ['device' => 'may-a', 'pool' => 'efootball-ios']);
ok(http('POST', "/api/tool/jobs/$J4/result", $TK, ['result' => 'failed', 'message' => 'Sai mật khẩu'])['json']['status'] === 'failed', 'tool báo failed → failed');
ok(http('POST', "/api/shop/jobs/$J4/cancel", $SK)['code'] === 409, 'đơn failed không huỷ được nữa');

echo "\n== Quá hạn ==\n";
$J5 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-5'] + $base)['json']['job']['id'];
http('POST', '/api/tool/claim', $TK, ['device' => 'may-b', 'pool' => 'efootball-ios']);
Db::run('UPDATE jobs SET seen_at=? WHERE pid=?', [time() - 3600, $J5]);
ok(http('GET', '/cron/tick?key=sai')['code'] === 401, 'cron sai khoá → 401');
$c = http('GET', '/cron/tick?key=cronkey123');
ok(($c['json']['sweep']['timeout'] ?? 0) === 1, 'tool im lặng quá lâu → review (timeout)', $c['json']);
ok(http('POST', "/api/tool/jobs/$J5/images?seq=1", $TK, png())['code'] === 200, 'ảnh gửi MUỘN của đơn quá hạn vẫn được nhận (bằng chứng đối soát)');
ok(http('POST', "/api/tool/jobs/$J5/result", $TK, ['result' => 'done'])['json']['status'] === 'review', 'tool báo muộn → vẫn review, chờ admin');
$J6 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-6'] + $base)['json']['job']['id'];
Db::run('UPDATE jobs SET created_at=? WHERE pid=?', [time() - 7200, $J6]);
ok((http('GET', '/cron/tick?key=cronkey123')['json']['sweep']['expired'] ?? 0) === 1, 'đơn chờ quá lâu không máy nhận → expired');
ok(http('POST', '/api/tool/claim', $TK, ['device' => 'may-c', 'pool' => 'efootball-ios'])['json']['job'] === null, 'đơn expired không được giao');
Db::update('pools', ['active' => 0], 'id=?', [$poolId]);
ok(http('POST', '/api/shop/jobs', $SK, ['ref' => 'ORD-7'] + $base)['code'] === 409, 'pool tạm dừng → không nhận đơn mới (409)');
ok(http('POST', '/api/tool/claim', $TK, ['device' => 'may-c', 'pool' => 'efootball-ios'])['json']['paused'] === true, 'pool tạm dừng → claim trả paused');

echo "\n== Webhook về shop ==\n";
http('GET', '/cron/tick?key=cronkey123');
usleep(600000);
$events = [];
$sigOk = true;
foreach (file("$tmp/hooks.log", FILE_IGNORE_NEW_LINES) ?: [] as $line) {
    $h = json_decode($line, true);
    $events[] = $h['event'];
    $sigOk = $sigOk && hash_equals('sha256=' . hash_hmac('sha256', $h['body'], $secret), $h['sig']);
    $payload = json_decode($h['body'], true);
    $sigOk = $sigOk && ($payload['event'] ?? '') === $h['event'] && !isset($payload['job']['login']);
}
foreach (['job.claimed', 'job.progress', 'job.need_otp', 'job.done', 'job.failed', 'job.review', 'job.expired', 'job.cancelled'] as $ev) {
    ok(in_array($ev, $events, true), "shop nhận webhook $ev");
}
ok($sigOk && count($events) > 0, 'mọi webhook có chữ ký HMAC đúng + không lộ thông tin đăng nhập');

echo "\n== Lưu gói nạp ==\n";
$pk = Pools::packages($poolId);
$rows = [];
foreach ($pk as $p) {
    if ($p['code'] !== 'off') {
        $rows[] = $p;
    }
}
$rows[] = ['code' => 'off', 'name' => 'Gói tắt (tạo lại)', 'limit_type' => 'multi', 'active' => false];     // xoá dòng cũ, thêm dòng mới CÙNG mã
ok(Pools::savePackages($poolId, $rows) === null && count(Pools::packages($poolId)) === 4 && Db::val("SELECT name FROM packages WHERE pool_id=? AND code='off'", [$poolId]) === 'Gói tắt (tạo lại)',
    'xoá một gói rồi thêm lại gói cùng mã trong một lần lưu → được (trước đây lỗi 500)');
$pk = Pools::packages($poolId);
$swap = $pk;
[$swap[0]['code'], $swap[1]['code']] = [$pk[1]['code'], $pk[0]['code']];
$err = Pools::savePackages($poolId, $swap);
ok(is_string($err) && str_contains($err, 'trùng') && array_column(Pools::packages($poolId), 'code') === array_column($pk, 'code'), 'đổi chéo mã giữa hai gói → báo lỗi rõ ràng, dữ liệu giữ nguyên (không lưu dở)', $err);

echo "\n== Chống dò mật khẩu ==\n";
$_SERVER['REMOTE_ADDR'] = '10.0.0.9';
$_SERVER['HTTP_X_FORWARDED_FOR'] = '6.6.6.6, 203.0.113.7';
ok(Req::ip() === '203.0.113.7', 'sau proxy: lấy IP CUỐI trong X-Forwarded-For (do proxy của mình ghi), không tin phần bên gọi tự khai', Req::ip());
$_SERVER['HTTP_X_FORWARDED_FOR'] = 'khong-phai-ip';
ok(Req::ip() === '10.0.0.9', 'X-Forwarded-For rác → dùng địa chỉ kết nối thật');
putenv('TRUST_PROXY=false');
$_SERVER['HTTP_X_FORWARDED_FOR'] = '6.6.6.6';
ok(Req::ip() === '10.0.0.9', 'không bật TRUST_PROXY → bỏ qua X-Forwarded-For');
putenv('TRUST_PROXY=true');
unset($_SERVER['HTTP_X_FORWARDED_FOR']);
$long = 'thu:' . str_repeat('x', 400);
RateLimit::hit($long);
ok(RateLimit::count($long, 60) === 1, 'tên thùng đếm dài quá cỡ vẫn ghi được (không lỗi 500)');
// tên thùng có tiếng Việt / emoji / UTF-8 hỏng / rất dài: tên LƯU xuống CSDL phải là ASCII ≤ 120 ký tự (MySQL từ chối chuỗi cắt giữa ký tự)
$odd = ['login-user:nguyễn văn ánh', 'login-user:' . str_repeat('ế', 150), "login-user:\u{1F600}\u{1F600}", "login-user:\xC3\x28hỏng", 'login-user:' . str_repeat('a', 300)];
Db::run('DELETE FROM rate_hits');
foreach ($odd as $b) {
    RateLimit::hit($b);
    RateLimit::hit($b);
}
$stored = array_column(Db::all('SELECT bucket, COUNT(*) AS c FROM rate_hits GROUP BY bucket'), 'c', 'bucket');
$asciiOk = array_filter(array_keys($stored), fn ($k) => strlen((string) $k) <= 120 && preg_match('/^[\x20-\x7E]+$/', (string) $k) === 1);
ok(count($stored) === count($odd) && count($asciiOk) === count($odd) && array_values(array_unique($stored)) === [2]
    && RateLimit::count($odd[0], 60) === 2 && RateLimit::count('login-user:nguyen van anh', 60) === 0,
    'tên thùng tiếng Việt / emoji / UTF-8 hỏng / quá dài → lưu thành chuỗi ASCII ≤ 120 ký tự, mỗi tên một thùng riêng, đếm đúng', array_keys($stored));
$lg = http('GET', '/admin/login');
preg_match('/Set-Cookie:\s*([^;\r\n]+)/i', $lg['head'], $ck);
$blocked = 0;
$wrong = 0;
$text = $lg['text'];
for ($i = 1; $i <= 23; $i++) {
    preg_match('/name="_csrf" value="([^"]+)"/', $text, $tk);
    $rr = http('POST', '/admin/login', null, http_build_query(['_csrf' => $tk[1] ?? '', 'username' => 'Admin', 'password' => 'sai-' . $i]),
        ['Cookie: ' . ($ck[1] ?? ''), 'Content-Type: application/x-www-form-urlencoded', "X-Forwarded-For: 198.51.100.$i"]);
    $text = $rr['text'];
    $blocked += str_contains($text, 'Sai quá nhiều lần') ? 1 : 0;
    $wrong += str_contains($text, 'Sai tài khoản hoặc mật khẩu') ? 1 : 0;
}
ok($wrong === 20 && $blocked === 3, 'dò mật khẩu admin bằng 23 IP khác nhau → sau 20 lần sai bị chặn theo TÊN ĐĂNG NHẬP', ['sai' => $wrong, 'chặn' => $blocked]);

// Chủ thật đã từng đăng nhập ĐÚNG từ một IP → kẻ ngoài cố tình nhập sai 20 lần KHÔNG khoá được chủ ở IP đó.
Db::insert('admins', ['username' => 'chu', 'password_hash' => password_hash('MatKhau-Dung#2026', PASSWORD_DEFAULT), 'created_at' => time()]);
$login = function (string $user, string $pass, string $ip): array {
    $g = http('GET', '/admin/login', null, null, ["X-Forwarded-For: $ip"]);
    preg_match('/Set-Cookie:\s*([^;\r\n]+)/i', $g['head'], $c);
    preg_match('/name="_csrf" value="([^"]+)"/', $g['text'], $t);
    return http('POST', '/admin/login', null, http_build_query(['_csrf' => $t[1] ?? '', 'username' => $user, 'password' => $pass]),
        ['Cookie: ' . ($c[1] ?? ''), 'Content-Type: application/x-www-form-urlencoded', "X-Forwarded-For: $ip"]);
};
$first = $login('chu', 'MatKhau-Dung#2026', '203.0.113.50');
ok($first['code'] === 302 && str_contains($first['head'], '/admin'), 'chủ đăng nhập đúng từ IP quen → vào được', $first['code']);
$stopped = 0;
for ($i = 1; $i <= 22; $i++) {
    $stopped += str_contains($login('chu', 'do-mat-khau-' . $i, "198.51.100." . (100 + $i))['text'], 'Sai quá nhiều lần') ? 1 : 0;
}
ok($stopped === 2, 'kẻ ngoài nhập sai tên «chu» 22 lần từ 22 IP → tên đăng nhập bị chặn với IP lạ sau 20 lần', $stopped);
$stranger = $login('chu', 'MatKhau-Dung#2026', '198.51.100.250');
ok($stranger['code'] !== 302 && str_contains($stranger['text'], 'Sai quá nhiều lần'), 'IP lạ (kể cả nhập đúng mật khẩu) vẫn bị chặn trong 10 phút đó', $stranger['code']);
$again = $login('chu', 'MatKhau-Dung#2026', '203.0.113.50');
ok($again['code'] === 302, 'chủ thật ở IP quen VẪN đăng nhập được — không bị người ngoài khoá tài khoản', [$again['code'], mb_substr(strip_tags($again['text']), 0, 80)]);
$known = jdec(Settings::get('login_known_ips', '[]'));
ok(count($known) === 1 && !str_contains(json_encode($known), '203.0.113.50'), 'danh sách IP quen chỉ lưu dạng băm (không lưu IP thật), không trùng lặp', $known);

echo "\n== Loại bước mới: vuốt, bấm giữ ==\n";
$gc = Pools::defaults();
$gc['rules'] = [['when' => 'login_success', 'value' => 'Trang chủ'], ['when' => 'logged_out', 'value' => 'Konami ID'], ['when' => 'purchase_success', 'value' => 'Thành công']];
$gc['login_steps'] = [['type' => 'launch', 'value' => 'game']];
$gc['nav_steps'] = [['type' => 'swipe', 'value' => 'left'], ['type' => 'swipe', 'value' => '375,1000 > 375,400'],
                    ['type' => 'hold', 'value' => '636,468 @1.5s'], ['type' => 'hold_text', 'value' => 'Sách @2s', 'optional' => true]];
$gid = Pools::save(null, 'gesture-pool', 'Pool cử chỉ', 'Game', true, $gc);
ok(is_int($gid), 'lưu được pool có bước vuốt / bấm giữ', $gid);
$gv = http('GET', '/api/tool/pools/gesture-pool', $TK)['json']['pool']['nav_steps'] ?? [];
ok(array_column($gv, 'type') === ['swipe', 'swipe', 'hold', 'hold_text'] && array_column($gv, 'value') === ['left', '375,1000 > 375,400', '636,468 @1.5s', 'Sách @2s']
    && array_column($gv, 'optional') === [false, false, false, true], 'tool nhận lại đúng loại bước, giá trị và cờ «bỏ qua nếu lỗi»', $gv);
ok(!array_diff(['swipe', 'hold', 'hold_text'], array_keys(Pools::STEP_TYPES)), 'ba loại bước mới có trong danh sách chọn của trang quản trị');

echo "\n== Tool tự báo: máy rảnh ở kịch bản nào + danh mục kịch bản (/api/tool/sync) ==\n";
ok(Schema::version() === Schema::LATEST && Schema::LATEST >= 3, 'CSDL ở phiên bản mới nhất (có bảng tool_scripts)', Schema::version());
ok(http('POST', '/api/tool/sync', null, ['devices' => []])['code'] === 401, 'sync không có khoá → 401');
ok(http('POST', '/api/tool/sync', $SK, ['devices' => []])['code'] === 401, 'sync bằng khoá SHOP → 401 (chỉ khoá Tool)');
$kid = (int) $tool['id'];
$rev1 = hash('sha256', 'danh-muc-1');
$U1 = 'g1:nap';
$U2 = 'g1:dang-nhap';
$devs = [
    ['name' => 'Farm-A', 'label' => 'iPhone 8 số 1', 'status' => 'idle', 'scripts' => [$U1, $U2, 'sai uid', $U1, 'x:' . str_repeat('y', 41)]],
    ['name' => 'Farm-B', 'status' => 'running', 'scripts' => [$U1], 'running' => ['uid' => $U1, 'group' => 'Nhóm 1', 'script' => 'Nạp', 'iter' => 2, 'job' => 'J-KHONG-LUU']],
    ['name' => 'Farm-C', 'status' => 'bay-len-troi', 'note' => 'ghi chú của tool', 'scripts' => [$U2]],
    ['name' => 'Farm-A', 'status' => 'offline'],                      // trùng tên → bỏ dòng sau
    ['status' => 'idle'],                                             // thiếu tên → bỏ
    'khong-phai-may',
];
$s1 = http('POST', '/api/tool/sync', $TK, ['tool' => ['app' => 'iphone-farm', 'mode' => 'web', 'accepting' => false], 'scripts_rev' => $rev1, 'devices' => $devs]);
ok($s1['code'] === 200 && $s1['json']['need_scripts'] === true && $s1['json']['scripts_rev'] === null && $s1['json']['devices'] === 3 && $s1['json']['scripts'] === 0,
    'lần báo đầu chỉ có máy + mã băm → gateway nhận máy và đòi danh mục (need_scripts)', $s1['json']);
$cat = [
    ['uid' => $U1, 'group' => 'Nhóm 1', 'name' => 'Nạp <b>gói</b>', 'mode' => 'loop', 'loops' => 3, 'step_count' => 3,
     'vars' => ['username', 'package.name', 'co dau cach', 'username', '9batdau'],
     'outline' => [['type' => 'launch', 'note' => 'mở game', 'optional' => false, 'app' => 'TEN-APP-BI-MAT'],
                   ['type' => 'type', 'note' => '', 'optional' => true, 'text' => 'MAT-KHAU-GO-THANG'], ['type' => 'DROP TABLE', 'note' => 'x'], ['type' => "tap\n", 'note' => 'xuống dòng thừa'], 'rac']],
    ['uid' => $U2, 'group' => 'Nhóm 1', 'name' => 'Đăng nhập', 'mode' => 'once', 'loops' => 1, 'step_count' => 0, 'vars' => [], 'outline' => []],
    ['uid' => 'thieu-dau-hai-cham', 'name' => 'bỏ'],
    ['uid' => $U1, 'name' => 'trùng uid → bỏ'],
];
$s2 = http('POST', '/api/tool/sync', $TK, ['tool' => ['app' => 'iphone-farm', 'mode' => 'web', 'accepting' => false], 'scripts_rev' => $rev1, 'scripts' => $cat, 'devices' => $devs]);
ok($s2['code'] === 200 && $s2['json']['need_scripts'] === false && $s2['json']['scripts_rev'] === $rev1 && $s2['json']['scripts'] === 2, 'gửi kèm danh mục → gateway nạp 2 kịch bản hợp lệ, hết đòi', $s2['json']);
$r1 = Db::one('SELECT * FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U1]);
ok($r1 && $r1['group_id'] === 'g1' && $r1['script_id'] === 'nap' && $r1['run_mode'] === 'loop' && (int) $r1['loops'] === 3 && (int) $r1['step_count'] === 3
    && jdec($r1['vars']) === ['username', 'package.name']
    && jdec($r1['outline']) === [['type' => 'launch', 'note' => 'mở game', 'optional' => false], ['type' => 'type', 'note' => '', 'optional' => true]],
    'kịch bản lưu đúng: nhóm, cách chạy, số bước, biến hợp lệ, dàn ý chỉ gồm loại bước + ghi chú', $r1);
ok(!str_contains(json_encode(Db::all('SELECT * FROM tool_scripts')), 'MAT-KHAU-GO-THANG') && !str_contains(json_encode(Db::all('SELECT * FROM tool_scripts')), 'TEN-APP-BI-MAT'),
    'nội dung gõ / tên app trong bước KHÔNG được lưu ở gateway (chỉ nhận dàn ý)');
$dA = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-A']);
$dB = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']);
$dC = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-C']);
ok($dA && $dA['status'] === 'idle' && $dA['label'] === 'iPhone 8 số 1' && jdec($dA['scripts']) === [$U1, $U2], 'máy rảnh: lưu trạng thái, nhãn, và đúng các kịch bản hợp lệ (bỏ uid sai / trùng)', $dA);
ok($dB && $dB['status'] === 'running' && jdec($dB['running']) === ['uid' => $U1, 'group' => 'Nhóm 1', 'script' => 'Nạp', 'iter' => 2], 'máy đang chạy: lưu đang chạy kịch bản nào, vòng mấy (không lưu trường lạ)', $dB);
ok($dC && $dC['status'] === 'offline' && $dC['status_note'] === 'tool báo trạng thái lạ', 'trạng thái lạ → «chưa sẵn sàng», không bao giờ thành rảnh', $dC);
ok(Tools::idleFor($dA, $U1) && Tools::idleFor($dA, $U2) && !Tools::idleFor($dB, $U1) && !Tools::idleFor($dC, $U2) && !Tools::idleFor($dA, 'g9:khac'),
    'máy rảnh Ở KỊCH BẢN NÀO: chỉ máy idle và có kịch bản đó trong danh sách của nó');
$board = Tools::board();
$mine = array_values(array_filter($board, static fn ($t) => (int) $t['key']['id'] === $kid))[0] ?? null;
$byUid = $mine ? array_column($mine['scripts'], null, 'uid') : [];
ok($mine && $mine['fresh'] && $mine['info']['mode'] === 'web' && $mine['info']['accepting'] === false
    && array_column($byUid[$U1]['idle'], 'name') === ['Farm-A'] && array_column($byUid[$U1]['others'], 'name') === ['Farm-B']
    && array_column($byUid[$U2]['idle'], 'name') === ['Farm-A'] && array_column($byUid[$U2]['others'], 'name') === ['Farm-C'],
    'bảng «Kịch bản & máy»: mỗi kịch bản liệt kê máy đang rảnh và máy khác; ghi nhận tool bản web không nhận đơn', $mine ? [$mine['info'], array_map(static fn ($s) => [array_column($s['idle'], 'name'), array_column($s['others'], 'name')], $mine['scripts'])] : null);

// sync là việc của MÁY — không đụng tới việc của ĐƠN (state / job / pool do heartbeat + claim ghi)
http('POST', '/api/tool/heartbeat', $TK, ['devices' => [['name' => 'Farm-B', 'pool' => 'efootball-ios', 'state' => 'busy', 'job' => 'JGIUNGUYEN']], 'active' => []]);
$s3 = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'note' => 'người vận hành bấm Dừng máy', 'scripts' => [$U1]],
                                                                                ['name' => 'Farm-B', 'status' => 'orders', 'scripts' => []]]]);
$dB = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']);
$dA = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-A']);
$dC = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-C']);
ok($s3['code'] === 200 && $s3['json']['need_scripts'] === false && $s3['json']['devices'] === 2, 'báo lại không kèm danh mục (mã băm khớp) → không đòi; đếm đúng số máy còn khai', $s3['json']);
ok($dB['state'] === 'busy' && $dB['job_pid'] === 'JGIUNGUYEN' && $dB['pool_code'] === 'efootball-ios' && $dB['status'] === 'orders', 'sync KHÔNG ghi đè state / job / pool của heartbeat', $dB);
ok($dA['status'] === 'paused' && !Tools::idleFor($dA, $U1) && Tools::state($dA)[1] === Tools::STATUS['paused'][0] && Tools::state($dA)[3] === 'người vận hành bấm Dừng máy',
    'máy bị người vận hành dừng → không còn tính là rảnh, hiện đúng nhãn + ghi chú', Tools::state($dA));
ok($dC === null && count(array_filter(Devices::all(), static fn ($d) => $d['name'] === 'Farm-C')) === 0, 'máy tool không còn khai → xoá khỏi bảng máy', $dC);
ok(Tools::board()[0]['info']['accepting'] === null, 'tool không gửi `accepting` → KHÔNG RÕ (không tự coi là đang nhận đơn)', Tools::board()[0]['info']);

// máy mà gateway còn ghi đang ĐỨNG TÊN MỘT ĐƠN thì không rảnh, dù tool báo idle; và sync không làm mới «còn sống» của đơn
$seenAt = time() - 50;
Db::insert('jobs', ['pid' => 'JGIUNGUYEN', 'pool_id' => $poolId, 'shop_key_id' => (int) $shop['id'], 'ref' => 'SYNC-GIU-DON', 'status' => 'running', 'stage' => 'purchasing',
    'device' => 'Farm-B', 'tool_key_id' => $kid, 'created_at' => time(), 'claimed_at' => time(), 'seen_at' => $seenAt, 'updated_at' => $seenAt]);
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'scripts' => [$U1]], ['name' => 'Farm-B', 'status' => 'idle', 'scripts' => [$U1]]]]);
$dB = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']);
$jb = Db::one('SELECT * FROM jobs WHERE pid=?', ['JGIUNGUYEN']);
ok($dB['status'] === 'idle' && $dB['job_pid'] === 'JGIUNGUYEN' && !Tools::idleFor($dB, $U1) && Tools::state($dB)[0] === 'busy' && Tools::state($dB)[1] === 'còn giữ đơn',
    'tool báo RẢNH nhưng gateway còn ghi máy đang giữ một đơn → KHÔNG tính là rảnh, hiện «còn giữ đơn»', Tools::state($dB));
ok(count(array_filter(array_column(Tools::board()[0]['scripts'], 'idle', 'uid')[$U1], static fn ($d) => $d['name'] === 'Farm-B')) === 0, '…và không nằm trong «máy đang rảnh» của kịch bản');
ok((int) $jb['seen_at'] === $seenAt && $jb['status'] === 'running' && (int) $jb['updated_at'] === $seenAt, 'sync KHÔNG làm mới «còn sống» của đơn (việc của heartbeat / progress), không đổi gì ở đơn', $jb);
$noJob = $dB; $noJob['job_pid'] = null; $noJob['state'] = 'free';
ok(Tools::idleFor($noJob, $U1) && Tools::state($noJob)[0] === 'idle', '(cùng máy đó, hết đứng tên đơn thì lại tính là rảnh)');
$busyOnly = $dB; $busyOnly['job_pid'] = null;                     // heartbeat báo «busy» nhưng không kèm mã đơn
ok($busyOnly['state'] === 'busy' && !Tools::idleFor($busyOnly, $U1) && Tools::state($busyOnly)[0] === 'busy', 'gateway ghi máy «bận» (dù không kèm mã đơn) → cũng không tính là rảnh');
$s3b = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'scripts' => [$U1]]]]);
$dB = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']);
ok($s3b['json']['devices'] === 1 && $dB && $dB['status'] === 'removed' && $dB['job_pid'] === 'JGIUNGUYEN' && $dB['scripts'] === null
    && count(array_filter(Devices::all(), static fn ($d) => $d['name'] === 'Farm-B')) === 1 && !Tools::idleFor($dB, $U1),
    'máy bị gỡ khỏi tool nhưng CÒN ĐỨNG TÊN một đơn → giữ lại (đánh dấu đã gỡ) cho người đối soát thấy, không tính là rảnh', $dB);
Devices::free($kid, 'Farm-B');                                    // đơn của máy đã gỡ kết thúc
ok(count(array_filter(Devices::all(), static fn ($d) => $d['name'] === 'Farm-B')) === 0, '…đơn đó xong thì máy đã gỡ thôi không hiện ở bảng máy nữa');
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'scripts' => [$U1]]]]);
ok(Db::one('SELECT id FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']) === null, '…và lần báo kế tiếp dọn hẳn dòng của máy đã gỡ (bảng không giữ rác)');
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'scripts' => [$U1]], ['name' => 'Farm-B', 'status' => 'orders', 'scripts' => []]]]);
ok(Db::val('SELECT status FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-B']) === 'orders', 'máy được khai lại → có lại trong bảng máy');

// máy chỉ do heartbeat / claim tạo ra (tool bản cũ chưa biết sync, dùng chung khoá) không thuộc ảnh chụp của sync → sync không được xoá
http('POST', '/api/tool/heartbeat', $TK, ['devices' => [['name' => 'Chi-Heartbeat', 'pool' => 'efootball-ios', 'state' => 'free']], 'active' => []]);
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev1, 'devices' => [['name' => 'Farm-A', 'status' => 'paused', 'scripts' => [$U1]], ['name' => 'Farm-B', 'status' => 'orders', 'scripts' => []]]]);
$hb = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Chi-Heartbeat']);
ok($hb && $hb['status'] === null && $hb['synced_at'] === null && $hb['pool_code'] === 'efootball-ios' && Tools::state($hb)[0] === 'free',
    'máy chỉ khai qua heartbeat (chưa từng sync) → sync không xoá, vẫn hiện «trống» như trước', $hb);

// danh mục là ảnh chụp toàn bộ + chỉ đổi updated_at khi nội dung đổi
Db::run('UPDATE tool_scripts SET updated_at=1000, first_seen_at=1000 WHERE tool_key_id=?', [$kid]);
$rev2 = hash('sha256', 'danh-muc-2');
$s4 = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2]);
ok($s4['json']['need_scripts'] === true && $s4['json']['scripts_rev'] === $rev1, 'tool đổi kịch bản (mã băm mới) → gateway đòi danh mục mới', $s4['json']);
$cat2 = [$cat[0]];
$cat2[0]['name'] = 'Nạp gói (đã sửa)';
$s5 = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'scripts' => $cat2]);
$r1 = Db::one('SELECT * FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U1]);
ok($s5['json']['scripts'] === 1 && $s5['json']['scripts_rev'] === $rev2 && Db::one('SELECT id FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U2]) === null
    && $r1['name'] === 'Nạp gói (đã sửa)' && (int) $r1['first_seen_at'] === 1000 && (int) $r1['updated_at'] > 1000,
    'danh mục mới: kịch bản bị xoá ở tool thì xoá ở gateway; kịch bản sửa thì cập nhật (giữ ngày thấy lần đầu)', [$s5['json'], $r1]);
Db::run('UPDATE tool_scripts SET updated_at=1000 WHERE tool_key_id=?', [$kid]);
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'scripts' => $cat2]);
ok((int) Db::val('SELECT updated_at FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U1]) === 1000, 'gửi lại y nguyên danh mục → không tính là «vừa sửa»');
ok((int) Db::val('SELECT COUNT(*) FROM devices WHERE tool_key_id=? AND synced_at IS NOT NULL AND status<>?', [$kid, 'removed']) === 2, 'lời báo không kèm `devices` → giữ nguyên danh sách máy');

// lời báo cũ không còn đáng tin
Db::run('UPDATE devices SET status=?, synced_at=?, last_seen_at=? WHERE tool_key_id=? AND name=?', ['idle', time() - 200, time() - 200, $kid, 'Farm-A']);
$dA = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-A']);
ok(!Tools::idleFor($dA, $U1) && Tools::state($dA)[0] === 'lost', 'tool im quá 90 giây → máy «rảnh» cũ KHÔNG còn được tính là rảnh, hiện mất kết nối', Tools::state($dA));
Db::run('UPDATE devices SET synced_at=?, last_seen_at=? WHERE tool_key_id=? AND name=?', [time() - 100, time() - 100, $kid, 'Farm-A']);
ok(Tools::state(Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-A']))[0] === 'lost', 'khoảng 90–120 giây cũng là mất kết nối (không rơi về «trống» của heartbeat)');

// thân sai / quá cỡ
ok(http('POST', '/api/tool/sync', $TK, ['scripts' => $cat2])['json']['error'] === 'missing_rev', 'gửi danh mục mà thiếu mã băm → 422 missing_rev');
ok(http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'scripts' => ['a' => 1]])['json']['error'] === 'invalid_scripts', 'scripts không phải danh sách → 422');
ok(http('POST', '/api/tool/sync', $TK, ['devices' => 'x'])['json']['error'] === 'invalid_devices', 'devices không phải danh sách → 422');
$many = [];
for ($i = 0; $i < Tools::MAX_DEVICES + 1; $i++) {
    $many[] = ['name' => "QuaNhieu-$i", 'status' => 'idle'];
}
ok(http('POST', '/api/tool/sync', $TK, ['devices' => $many])['json']['error'] === 'too_many_devices' && (int) Db::val("SELECT COUNT(*) FROM devices WHERE name LIKE 'QuaNhieu-%' AND tool_key_id=?", [$kid]) === 0,
    'quá 200 máy → từ chối cả lời báo, không ghi dở dang');
$rev3 = hash('sha256', 'danh-muc-3');
$half = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev3, 'scripts' => [], 'devices' => $many]);
ok($half['json']['error'] === 'too_many_devices' && (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$kid]) === 1
    && (jdec(Db::val('SELECT tool_info FROM api_keys WHERE id=?', [$kid]))['scripts_rev'] ?? '') === $rev2,
    'lời báo bị từ chối (quá số máy) có kèm danh mục mới → danh mục cũ GIỮ NGUYÊN: kiểm hết rồi mới ghi', $half['json']);
ok(http('POST', '/api/tool/sync', $TK, str_repeat(' ', Tools::MAX_BODY + 1), ['Content-Type: application/json'])['code'] === 413, 'thân quá 1 MB → 413');
$nl = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'devices' => [['name' => 'Farm-A', 'status' => "idle\n", 'scripts' => ["g1:na\np", "g1:nap\n\n:x"]], ['name' => 'Farm-B', 'status' => 'orders', 'scripts' => []]]]);
$dA = Db::one('SELECT * FROM devices WHERE tool_key_id=? AND name=?', [$kid, 'Farm-A']);
ok($nl['code'] === 200 && $dA['status'] === 'offline' && jdec($dA['scripts']) === [], 'trạng thái có dấu xuống dòng thừa / mã kịch bản chứa xuống dòng → không được nhận (không thành rảnh)', $dA);

// hai khoá Tool không đụng dữ liệu của nhau
$tool2 = Keys::create('tool', 'Farm Thuỷ');
$o = http('POST', '/api/tool/sync', $tool2['plain'], ['scripts_rev' => $rev1, 'scripts' => [], 'devices' => [['name' => 'Farm-A', 'status' => 'idle', 'scripts' => [$U1]]]]);
ok($o['code'] === 200 && (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$kid]) === 1
    && (int) Db::val("SELECT COUNT(*) FROM devices WHERE tool_key_id=? AND synced_at IS NOT NULL AND status<>'removed'", [$kid]) === 2
    && (int) Db::val('SELECT COUNT(*) FROM devices WHERE tool_key_id=?', [(int) $tool2['id']]) === 1,
    'khoá Tool khác báo danh mục rỗng + máy trùng tên → dữ liệu của khoá này không bị xoá / gộp', $o['json']);

// trang quản trị
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'devices' => [['name' => 'Farm-A', 'label' => '<i>nhãn</i>', 'status' => 'idle', 'scripts' => [$U1]], ['name' => 'Farm-B', 'status' => 'running', 'scripts' => [$U1], 'running' => ['uid' => $U1, 'group' => 'Nhóm VIP', 'script' => 'Mua gói 1 tỷ', 'iter' => 2]]]]);
$g = http('GET', '/admin/login', null, null, ['X-Forwarded-For: 203.0.113.50']);
preg_match('/Set-Cookie:\s*([^;\r\n]+)/i', $g['head'], $c0);
preg_match('/name="_csrf" value="([^"]+)"/', $g['text'], $t0);
$in = http('POST', '/admin/login', null, http_build_query(['_csrf' => $t0[1] ?? '', 'username' => 'chu', 'password' => 'MatKhau-Dung#2026']),
    ['Cookie: ' . ($c0[1] ?? ''), 'Content-Type: application/x-www-form-urlencoded', 'X-Forwarded-For: 203.0.113.50']);
$cookie = preg_match('/Set-Cookie:\s*([^;\r\n]+)/i', $in['head'], $c1) === 1 ? $c1[1] : ($c0[1] ?? '');
$page = http('GET', '/admin/scripts', null, null, ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50']);
ok($page['code'] === 200 && str_contains($page['text'], 'Nạp gói (đã sửa)') && str_contains($page['text'], 'Farm-A') && str_contains($page['text'], 'đang chạy kịch bản')
    && str_contains($page['text'], '{{username}}') && str_contains($page['text'], 'Nhóm VIP · Mua gói 1 tỷ'),
    'trang «Kịch bản & máy» hiện kịch bản, biến cần dữ liệu, máy rảnh, máy đang chạy gì', [$page['code'], mb_substr(strip_tags($page['text']), 0, 200)]);
ok(str_contains($page['text'], '&lt;i&gt;nhãn&lt;/i&gt;') && !str_contains($page['text'], '<i>nhãn</i>'), 'chữ do tool gửi lên được thoát HTML khi hiện');
$dash = http('GET', '/admin', null, null, ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50']);
ok($dash['code'] === 200 && str_contains($dash['text'], 'Farm-A') && str_contains($dash['text'], 'Nạp gói (đã sửa)') && str_contains($dash['text'], '/admin/scripts'),
    'trang Tổng quan hiện máy kèm kịch bản chạy được', $dash['code']);
ok(!str_contains($page['text'], "\u{FFFD}") && !str_contains($dash['text'], "\u{FFFD}") && str_contains($dash['text'], 'Farm Thuỷ') && str_contains($page['text'], 'Farm Thuỷ'),
    'tên tiếng Việt (nhóm «…VIP», kịch bản «…tỷ», khoá «…Thuỷ») hiện nguyên vẹn — không bị cắt nhầm byte khi ghép bằng dấu «·»');
ok(http('GET', '/admin/scripts')['code'] === 302, '/admin/scripts chưa đăng nhập → chuyển về trang đăng nhập');

// xoá một khoá Tool → danh mục kịch bản + máy do khoá đó báo cũng đi theo
http('POST', '/api/tool/sync', $tool2['plain'], ['scripts_rev' => $rev2, 'scripts' => $cat2]);
$t2 = (int) $tool2['id'];
$kp = http('GET', '/admin/keys', null, null, ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50']);
preg_match('/name="_csrf" value="([^"]+)"/', $kp['text'], $tk2);
$had = (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$t2]);
$del = http('POST', "/admin/keys/$t2/delete", null, http_build_query(['_csrf' => $tk2[1] ?? '']), ['Cookie: ' . $cookie, 'Content-Type: application/x-www-form-urlencoded', 'X-Forwarded-For: 203.0.113.50']);
ok($had === 1 && $del['code'] === 302 && Keys::find($t2) === null && (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$t2]) === 0
    && (int) Db::val('SELECT COUNT(*) FROM devices WHERE tool_key_id=?', [$t2]) === 0 && (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$kid]) === 1,
    'xoá khoá Tool → kịch bản + máy của khoá đó bị xoá theo; khoá khác không ảnh hưởng', [$had, $del['code']]);

// mã mới chạy trên CSDL CŨ (chưa áp migration 3): sync báo rõ cần cập nhật, phần còn lại vẫn chạy; áp migration xong thì dùng được
file_put_contents("$tmp/v2.php", <<<'PHP'
<?php
require getenv('GW_ROOT') . '/src/bootstrap.php';
set_error_handler(static function ($no, $str, $file, $line) { throw new ErrorException($str, 0, $no, $file, $line); });
$all = Schema::migrations(Db::driver());
Db::pdo()->exec('CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL PRIMARY KEY, applied_at INT NOT NULL)');
foreach ([1, 2] as $v) {
    foreach ($all[$v] as $sql) { Db::pdo()->exec($sql); }
    Db::insert('schema_version', ['version' => $v, 'applied_at' => time()]);
}
$k = Keys::create('tool', 'Farm cũ');
$key = Keys::find((int) $k['id']);
Devices::touch((int) $k['id'], 'May-cu', 'p', 'free', null);
$out = ['version' => Schema::version(), 'sync' => Tools::sync($key, ['devices' => [['name' => 'x', 'status' => 'idle']]]),
        'devices' => array_column(Devices::all(), 'name'), 'board' => Tools::board(), 'names' => Tools::scriptNames(), 'state' => Tools::state(Devices::all()[0])[0]];
$out['applied'] = Schema::migrate();
$out['version_after'] = Schema::version();
$out['after'] = Tools::sync(Keys::find((int) $k['id']), ['devices' => [['name' => 'x', 'status' => 'idle']]]);
$out['again'] = Schema::migrate();
echo json_encode($out);
PHP);
$v2 = proc_open([PHP_BINARY, "$tmp/v2.php"], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pp, $tmp, array_merge(getenv(), $env, ['DB_DSN' => "sqlite:$tmp/v2.sqlite", 'DB_USER' => '', 'DB_PASS' => '', 'GW_ROOT' => dirname(__DIR__)]));
$v2out = stream_get_contents($pp[1]) . stream_get_contents($pp[2]);
proc_close($v2);
$v = json_decode($v2out, true) ?? [];
ok(($v['version'] ?? 0) === 2 && ($v['sync'][0] ?? 0) === 503 && ($v['sync'][1]['error'] ?? '') === 'needs_migration' && ($v['devices'] ?? null) === ['May-cu']
    && ($v['board'] ?? null) === [] && ($v['names'] ?? null) === [] && ($v['state'] ?? '') === 'free',
    'CSDL chưa áp migration 3: sync trả 503 needs_migration; bảng máy / trang kịch bản vẫn chạy (không lỗi SQL)', mb_substr($v2out, 0, 300));
ok(($v['applied'] ?? null) === [3] && ($v['version_after'] ?? 0) === Schema::LATEST && ($v['after'][0] ?? 0) === 200 && ($v['again'] ?? null) === [],
    'chạy migrate trên CSDL cũ → lên bản mới nhất, sync dùng được ngay; chạy lại lần nữa không làm gì', [$v['applied'] ?? null, $v['after'][0] ?? null]);

echo "\n== Trang quản trị + tài liệu ==\n";
$docs = http('GET', '/docs');
ok(str_contains($docs['text'], '/api/tool/sync') && str_contains($docs['text'], 'need_scripts'), 'tài liệu có API /api/tool/sync');
ok($docs['code'] === 200 && str_contains($docs['text'], '/api/tool/claim'), 'trang /docs hiển thị');
ok(str_contains($docs['text'], 'job.cancelled') && str_contains($docs['text'], 'attempt') && str_contains($docs['text'], 'logged_out') && str_contains($docs['text'], 'resumed'),
    'tài liệu có đủ: webhook job.cancelled, tham số attempt, luật logged_out, cách xử lý đơn resumed');
ok(http('GET', '/admin')['code'] === 302, '/admin chưa đăng nhập → chuyển về trang đăng nhập');
ok(http('GET', '/admin/login')['code'] === 200, 'trang đăng nhập hiển thị');

echo "\n" . ($fail === 0 ? "✅ TẤT CẢ $pass kiểm tra đều đạt.\n" : "❌ $fail lỗi / " . ($pass + $fail) . " kiểm tra.\n");
exit($fail === 0 ? 0 : 1);

/** Chạy $fn ở tiến trình con (không chặn tiến trình chính). */
function pcntl_fork_safe(callable $fn): int
{
    if (!function_exists('pcntl_fork')) {
        // không có pcntl: chạy nền bằng một tiến trình php riêng là quá cồng kềnh → gửi ngay
        $fn();
        return 0;
    }
    $pid = pcntl_fork();
    if ($pid === 0) {
        $fn();
        posix_kill(getmypid(), SIGKILL);   // thoát cứng: không chạy shutdown function của cha
    }
    return $pid;
}
