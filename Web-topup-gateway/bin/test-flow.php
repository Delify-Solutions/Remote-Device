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
ok((int) Db::val('SELECT COUNT(*) FROM schema_version') === 2, 'đã áp đủ 2 migration');

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

echo "\n== Trang quản trị + tài liệu ==\n";
$docs = http('GET', '/docs');
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
