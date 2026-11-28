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
$creates = array_values(array_filter(array_merge(...array_values(Schema::migrations('mysql'))), static fn (string $s): bool => str_starts_with(trim($s), 'CREATE TABLE')));
$noBin = array_filter($creates, static fn (string $s): bool => !str_ends_with(trim($s), 'COLLATE=utf8mb4_bin'));
ok(count($creates) === 17 && !$noBin && substr_count($my, 'utf8mb4_bin') >= 28 && preg_match('/utf8mb4_[a-z0-9_]*_ci/', $my) !== 1,
    'MySQL/MariaDB: mọi bảng (cả 3 bảng ví / sổ cái / giá theo loại tiền) so khớp CHÍNH XÁC (utf8mb4_bin) — không gộp mã đơn / tên máy khác hoa-thường, khác dấu', [count($creates), array_map(static fn ($s) => substr(trim($s), 0, 40), $noBin)]);
ok(!str_contains(implode("\n", Schema::migrations('sqlite')[5]), 'ENGINE') && count(Schema::migrations('sqlite')[5]) === count(Schema::migrations('mysql')[5]),
    'migration 5 (ví) có cùng các câu lệnh cho SQLite và MySQL (SQLite không kèm ENGINE / COLLATE)');
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
    ['uid' => $U2, 'group' => 'Nhóm 1', 'name' => 'Đăng nhập', 'mode' => 'once', 'loops' => 1, 'step_count' => 0, 'vars' => [], 'outline' => [], 'pool' => 'efootball-ios'],
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
ok(Db::val('SELECT pool_code FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U2]) === null && Db::val('SELECT run_mode FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $U2]) === 'once',
    'kịch bản thường có gửi kèm `pool` → không được ghi là phục vụ pool nào (chỉ kịch bản nhận đơn mới gắn pool)');
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

// KỊCH BẢN NHẬN ĐƠN: tool khai kịch bản phục vụ pool nào → gateway lưu, hiện ở trang kịch bản và trang pool
$UO = 'g1:nhan-don';
$rev4 = hash('sha256', 'danh-muc-4');
$catO = [$cat2[0],
    ['uid' => $UO, 'group' => 'Nhóm 1', 'name' => 'Nạp eFootball theo đơn', 'mode' => 'orders', 'pool' => 'EFootball-iOS', 'step_count' => 3, 'vars' => ['username', 'otp'],
     'outline' => [['type' => 'launch', 'note' => '', 'optional' => false, 'phase' => 'login'], ['type' => 'type', 'note' => '', 'phase' => 'otp'], ['type' => 'tap_text', 'note' => '', 'phase' => 'giai-doan-la']]],
    ['uid' => 'g1:pool-ma', 'group' => 'Nhóm 1', 'name' => 'Đơn của pool không có', 'mode' => 'orders', 'pool' => 'pool-ma', 'step_count' => 0, 'vars' => [], 'outline' => []]];
$so = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev4, 'scripts' => $catO, 'devices' => [['name' => 'Farm-A', 'status' => 'idle', 'scripts' => [$U1, $UO]],
    ['name' => 'Farm-B', 'status' => 'orders', 'scripts' => [$UO], 'running' => ['uid' => $UO, 'group' => 'Nhóm 1', 'script' => 'Nạp eFootball theo đơn']]]]);
$ro = Db::one('SELECT * FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $UO]);
ok($so['code'] === 200 && $ro && $ro['run_mode'] === 'orders' && $ro['pool_code'] === 'efootball-ios'
    && jdec($ro['outline']) === [['type' => 'launch', 'note' => '', 'optional' => false, 'phase' => 'login'], ['type' => 'type', 'note' => '', 'optional' => false, 'phase' => 'otp'], ['type' => 'tap_text', 'note' => '', 'optional' => false]],
    'kịch bản nhận đơn: lưu cách chạy «orders», mã pool (chữ thường), giai đoạn của từng bước (giai đoạn lạ bị bỏ)', $ro);
$byPool = Tools::scriptsByPool();
ok(array_column($byPool['efootball-ios'] ?? [], 'name') === ['Nạp eFootball theo đơn'] && ($byPool['efootball-ios'][0]['idle'] ?? -1) === 1 && isset($byPool['pool-ma']),
    'gateway biết kịch bản nào đang phục vụ pool nào, kèm số máy đang rảnh ở kịch bản đó', $byPool);
$page = http('GET', '/admin/scripts', null, null, ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50']);
ok(str_contains($page['text'], 'nhận đơn') && str_contains($page['text'], "/admin/pools/$poolId") && str_contains($page['text'], 'pool-ma') && str_contains($page['text'], 'không có')
    && str_contains($page['text'], 'đang nhận đơn') && str_contains($page['text'], 'Nhóm 1 · Nạp eFootball theo đơn'),
    'trang «Kịch bản & máy»: kịch bản nhận đơn kèm pool (có liên kết), báo rõ pool không tồn tại, máy đang nhận đơn bằng kịch bản nào', mb_substr(strip_tags($page['text']), 0, 300));
$pp = http('GET', '/admin/pools', null, null, ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50']);
ok($pp['code'] === 200 && str_contains($pp['text'], 'Nạp eFootball theo đơn') && str_contains($pp['text'], '1 máy rảnh'), 'trang Pool hiện kịch bản nhận đơn đang phục vụ pool + số máy rảnh', $pp['code']);
http('POST', '/api/tool/sync', $TK, ['scripts_rev' => $rev2, 'scripts' => $cat2]);            // trả danh mục về như cũ cho các kiểm tra sau

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
foreach ($all[3] as $sql) { Db::pdo()->exec($sql); }
Db::insert('schema_version', ['version' => 3, 'applied_at' => time()]);
$r3 = new ReflectionProperty(Schema::class, 'version'); $r3->setAccessible(true); $r3->setValue(null, null);     // (bỏ giá trị đã nhớ: bài thử vừa tự áp một phiên bản)
$out['v3'] = ['version' => Schema::version(), 'sync' => Tools::sync(Keys::find((int) $k['id']), ['devices' => []])[0], 'board' => Tools::board(), 'byPool' => Tools::scriptsByPool(),
              'devices' => array_column(Devices::all(), 'name')];
Db::insert('jobs', ['pid' => 'JCU', 'pool_id' => 1, 'shop_key_id' => 1, 'ref' => 'DON-CU', 'status' => 'done', 'created_at' => time(), 'updated_at' => time()]);
$out['applied'] = Schema::migrate();
$out['version_after'] = Schema::version();
$out['after'] = Tools::sync(Keys::find((int) $k['id']), ['devices' => [['name' => 'x', 'status' => 'idle']]]);
$out['again'] = Schema::migrate();
$old = Db::one("SELECT wallet_id, wallet_state, account_key FROM jobs WHERE pid='JCU'");
$out['v5'] = ['wallets' => (int) Db::val('SELECT COUNT(*) FROM wallets'), 'wallet_entries' => (int) Db::val('SELECT COUNT(*) FROM wallet_entries'),
              'package_prices' => (int) Db::val('SELECT COUNT(*) FROM package_prices'),
              'jobs_cols' => (bool) Db::one('SELECT wallet_id, currency, cost, wallet_state, account_key FROM jobs LIMIT 1'), 'old_job' => $old];
echo json_encode($out);
PHP);
$v2 = proc_open([PHP_BINARY, "$tmp/v2.php"], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pp, $tmp, array_merge(getenv(), $env, ['DB_DSN' => "sqlite:$tmp/v2.sqlite", 'DB_USER' => '', 'DB_PASS' => '', 'GW_ROOT' => dirname(__DIR__)]));
$v2out = stream_get_contents($pp[1]) . stream_get_contents($pp[2]);
proc_close($v2);
$v = json_decode($v2out, true) ?? [];
ok(($v['version'] ?? 0) === 2 && ($v['sync'][0] ?? 0) === 503 && ($v['sync'][1]['error'] ?? '') === 'needs_migration' && ($v['devices'] ?? null) === ['May-cu']
    && ($v['board'] ?? null) === [] && ($v['names'] ?? null) === [] && ($v['state'] ?? '') === 'free',
    'CSDL chưa áp migration 3: sync trả 503 needs_migration; bảng máy / trang kịch bản vẫn chạy (không lỗi SQL)', mb_substr($v2out, 0, 300));
ok(($v['v3']['version'] ?? 0) === 3 && ($v['v3']['sync'] ?? 0) === 503 && ($v['v3']['board'] ?? null) === [] && ($v['v3']['byPool'] ?? null) === [] && ($v['v3']['devices'] ?? null) === ['May-cu'],
    'CSDL ở bản 3 (chưa có cột pool của kịch bản): sync vẫn báo cần cập nhật, các trang vẫn chạy', $v['v3'] ?? null);
ok(($v['applied'] ?? null) === [4, 5, 6] && ($v['version_after'] ?? 0) === Schema::LATEST && ($v['after'][0] ?? 0) === 200 && ($v['again'] ?? null) === [],
    'chạy migrate trên CSDL cũ → lên bản mới nhất (4, 5 rồi 6), sync dùng được ngay; chạy lại lần nữa không làm gì', [$v['applied'] ?? null, $v['after'][0] ?? null]);
ok(($v['v5'] ?? null) === ['wallets' => 0, 'wallet_entries' => 0, 'package_prices' => 0, 'jobs_cols' => true, 'old_job' => ['wallet_id' => null, 'wallet_state' => null, 'account_key' => null]],
    'migration 5 trên CSDL cũ: có bảng ví / sổ cái / giá theo loại tiền + các cột mới của đơn; đơn cũ không bị gắn ví', $v['v5'] ?? null);

echo "\n== Ví tài khoản Apple: tiền (×100), giá gói theo loại tiền, sổ cái ==\n";
ok(Money::parse('1.500', 'JPY') === 150000 && Money::parse('1500', 'JPY') === 150000 && Money::parse('1,500', 'JPY') === 150000 && Money::parse('63.5', 'CHF') === 6350
    && Money::parse('63,50', 'CHF') === 6350 && Money::parse('1.234,56', 'CHF') === 123456 && Money::parse('1,234.56', 'CHF') === 123456 && Money::parse('0', 'JPY') === 0
    && Money::parse('1500.50', 'JPY') === null && Money::parse('-5', 'JPY') === null && Money::parse('-1.000', 'JPY', true) === -100000 && Money::parse('abc', 'JPY') === null
    && Money::parse('1.5.0', 'CHF') === null && Money::parse('', 'JPY') === null && Money::parse('12.', 'CHF') === null,
    'số tiền admin nhập → số nguyên ×100 (dấu nghìn / phần lẻ kiểu Việt lẫn kiểu Anh; JPY không có phần lẻ; âm chỉ khi chỉnh số dư)');
ok(Money::fmt(150000, 'JPY') === '1.500 JPY' && Money::fmt(6350, 'CHF') === '63,50 CHF' && Money::fmt(-100000, 'JPY') === '-1.000 JPY' && Money::plain(6300, 'CHF') === '63.00' && Money::plain(150000, 'JPY') === '1500',
    'hiện số tiền giống thông báo của tool (1.500 JPY · 63,50 CHF); ô nhập điền sẵn không dấu nghìn');
ok(Wallets::mask('apple01@example.com') === 'a***@example.com' && Wallets::mask('0912345678') === '09***78', 'tài khoản Apple gửi cho tool được che (a***@example.com)');
ok(Money::currency('¥') === 'JPY' && Money::currency('jp') === 'JPY' && Money::currency('円') === 'JPY' && Money::currency('₫') === 'VND' && Money::currency('$') === 'USD'
    && Money::currency('kr') === 'KR' && Money::currency('1kr') === null && Money::currency('a b') === null
    && Money::currency('kr.') === 'KR' && Money::currency('Rs.') === 'RS' && Money::currency('лв.') === 'ЛВ' && Money::currency('Fr.') === 'FR' && Money::currency('u.s.') === 'USD'
    && Money::currency('.') === null && Money::currency('₹') === '₹' && Money::currency('R$') === 'R$' && Money::currency('toolong') === null
    && Pools::parseCurrencies('¥, CHF, jp, kr') === [['JPY', 'CHF', 'KR'], null] && Money::label('JPY') === 'JPY ¥',
    'loại tiền là NHÃN để so khớp / đối soát: «¥», «JP», «円» → JPY; nhãn khác như «kr» giữ nguyên (không đoán thành tiền nước khác); nhãn hiện «JPY ¥»');
ok(Pools::parseCurrencies('jpy, CHF  usd;JPY') === [['JPY', 'CHF', 'USD'], null] && Pools::parseCurrencies('JPY, XX1')[1] !== null, 'loại tiền của pool: mã ISO 3 chữ, viết hoa, bỏ trùng; mã sai bị từ chối');

$wc = Pools::defaults();
$wc['rules'] = [['when' => 'logged_out', 'value' => 'Đăng nhập'], ['when' => 'login_success', 'value' => 'Trang chủ'], ['when' => 'purchase_success', 'value' => 'Thành công']];
$wc['login_steps'] = [['type' => 'launch', 'value' => 'game']];
$wc['purchase_steps'] = [['type' => 'tap_text', 'value' => '{{package.price_text}}']];
$wc['finish_steps'] = [['type' => 'home', 'value' => '']];
$wc['currencies'] = ['jpy', 'CHF', 'sai-ma'];
$wpId = Pools::save(null, 'wallet-pool', 'Pool ví', 'Game', true, $wc);
ok(Pools::find($wpId)['cfg']['currencies'] === ['JPY', 'CHF'], 'pool lưu danh sách loại tiền trong cấu hình (bỏ mã sai)');
$perr = Pools::savePackages($wpId, [['code' => 'x', 'name' => 'x', 'prices' => ['JPY' => ['amount' => '12.5', 'display' => '¥12.5']]]]);
ok(is_string($perr) && str_contains($perr, 'JPY') && Pools::packages($wpId) === [], 'giá JPY có phần lẻ → báo lỗi rõ ràng, không lưu gì', $perr);
$perr2 = Pools::savePackages($wpId, [['code' => 'x', 'name' => 'x', 'prices' => ['JPY' => ['amount' => '1500', 'display' => '']]]]);
ok(is_string($perr2) && str_contains($perr2, 'chữ hiện trên máy') && Pools::packages($wpId) === [],
    'giá theo loại tiền mà thiếu «chữ hiện trên máy» → báo lỗi (tool khớp chữ giá trên ô gói, thiếu chữ là không tìm được gói)', $perr2);
$pe = Pools::savePackages($wpId, [
    ['code' => 'gem_s', 'name' => 'Gói nhỏ', 'price_text' => '25.000', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true,
     'prices' => ['JPY' => ['amount' => '1.500', 'display' => '¥1,500'], 'CHF' => ['amount' => '9.00', 'display' => 'CHF 9.00']]],
    ['code' => 'gem_l', 'name' => 'Gói lớn', 'price_text' => '249.000', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true, 'prices' => ['JPY' => ['amount' => '12000', 'display' => '¥12,000']]],
    ['code' => 'pass', 'name' => 'Gói 1 lần', 'price_text' => '50.000', 'limit_type' => 'once', 'active' => true, 'prices' => ['JPY' => ['amount' => '3000', 'display' => '¥3,000']]],
    ['code' => 'noprice', 'name' => 'Gói chưa có giá JPY', 'limit_type' => 'multi', 'active' => true, 'prices' => ['CHF' => ['amount' => '1', 'display' => 'CHF 1.00'], 'USD' => ['amount' => '1', 'display' => '$1.00']]],
    ['code' => 'nodisp', 'name' => 'Gói giá cũ chưa có chữ', 'limit_type' => 'multi', 'active' => true],
]);
$pid = array_column(Pools::packages($wpId), 'id', 'code');
Db::insert('package_prices', ['package_id' => $pid['nodisp'], 'currency' => 'JPY', 'amount' => 100000, 'display' => '']);    // dữ liệu cũ (trước luật bắt buộc chữ giá)
$pr = Pools::prices($wpId);
ok($pe === null && ($pr[$pid['gem_s']]['JPY'] ?? null) === ['amount' => '1500', 'display' => '¥1,500'] && ($pr[$pid['gem_s']]['CHF']['amount'] ?? '') === '9.00'
    && (int) Db::val("SELECT amount FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['gem_s']]) === 150000
    && !isset($pr[$pid['noprice']]['JPY']) && !isset($pr[$pid['noprice']]['USD']),
    'giá gói theo từng loại tiền lưu ×100 kèm chữ giá trên máy; loại tiền không thuộc pool bị bỏ', $pr);
$tp = http('GET', '/api/tool/pools/wallet-pool', $TK)['json']['pool'] ?? [];
$tpk = array_column($tp['packages'] ?? [], null, 'code');
ok(($tp['currencies'] ?? null) === ['JPY', 'CHF'] && ($tpk['gem_s']['prices']['JPY'] ?? null) === ['amount' => 150000, 'display' => '¥1,500'] && ($tpk['gem_s']['prices']['CHF']['amount'] ?? 0) === 900
    && !isset($tpk['noprice']['prices']['USD']), 'tool đọc pool: các loại tiền pool bán + giá ×100 và chữ giá của từng gói theo từng loại tiền (để khai ví cho máy)', $tpk['gem_s'] ?? null);

// ---- trang quản trị: ví CHỈ XEM (ví do tool quản lý) ----
$ah = ['Cookie: ' . $cookie, 'X-Forwarded-For: 203.0.113.50'];
$wl = http('GET', '/admin/wallets', null, null, $ah);
preg_match('/name="_csrf" value="([^"]+)"/', $wl['text'], $cs);
$csrf = $cs[1] ?? '';
$post = static fn (string $path, array $f): array => http('POST', $path, null, http_build_query($f + ['_csrf' => $csrf]), array_merge($ah, ['Content-Type: application/x-www-form-urlencoded']));
ok($wl['code'] === 200 && str_contains($wl['text'], 'do <b>tool quản lý</b>') && str_contains($wl['text'], 'Ví &amp; tài khoản Apple') && str_contains($wl['text'], 'tabler-wallet')
    && !str_contains($wl['text'], 'action="/admin/wallets'), 'trang «Ví & tài khoản Apple» hiển thị, có trong menu, KHÔNG có form tạo / nạp ví (chỉ xem)', $wl['code']);
ok(http('GET', '/admin/wallets')['code'] === 302, '/admin/wallets chưa đăng nhập → chuyển về trang đăng nhập');
$kidT = (int) $tool['id'];
$tryCreate = $post('/admin/wallets/create', ['machine' => $kidT . '|Vi-01', 'apple_account' => 'apple01@example.com', 'currency' => 'JPY', 'balance' => '1000']);
ok($tryCreate['code'] === 302 && (int) Db::val('SELECT COUNT(*) FROM wallets') === 0 && str_contains(http('GET', '/admin/wallets', null, null, $ah)['text'], 'Ví giờ do TOOL quản lý'),
    'gửi thẳng lệnh tạo ví lên gateway → từ chối, nhắc khai ví ở tool, không tạo gì');

// ---- giao đơn theo VÍ CỦA TOOL (tool gửi «loại tiền + còn dùng được» khi xin đơn) ----
$wbase = ['pool' => 'wallet-pool', 'login' => ['username' => 'vi-khach@example.com', 'password' => 'pw']];
$mk = static function (string $ref, array $items, string $user = 'vi-khach@example.com') use ($SK, $wbase): array {
    return http('POST', '/api/shop/jobs', $SK, ['ref' => $ref, 'items' => $items, 'login' => ['username' => $user, 'password' => 'pw']] + $wbase);
};
$claimW = static fn (string $dev, ?array $wal = null): array => http('POST', '/api/tool/claim', $TK, ['device' => $dev, 'pool' => 'wallet-pool'] + ($wal ? ['wallet' => $wal] : []))['json'];
$JPY = static fn (int $x100): array => ['currency' => 'JPY', 'available' => $x100];
$evs = static fn (string $pid): array => Db::all('SELECT kind, d_balance, d_held, package_code, qty, actor, acked_at FROM tool_wallet_events WHERE job_pid=? ORDER BY id', [$pid]);
$WJ0 = $mk('W-0', [['code' => 'gem_s', 'qty' => 1]])['json']['job']['id'] ?? '';
$free = $claimW('Vi-free');
ok(($free['job']['id'] ?? '') === $WJ0 && !isset($free['job']['wallet']) && !isset($free['job']['items'][0]['price']) && ($free['job']['items'][0]['price_text'] ?? '') === '25.000' && !isset($free['wallet_short']),
    'máy KHÔNG có ví (tool không gửi ví) nhận đơn như cũ: không kiểm tiền, không có trường ví / giá, chữ giá mặc định', $free);
http('POST', "/api/tool/jobs/$WJ0/result", $TK, ['result' => 'failed', 'message' => 'thử']);
ok(Db::one('SELECT wallet_id, wallet_state, cost, currency FROM jobs WHERE pid=?', [$WJ0]) === ['wallet_id' => null, 'wallet_state' => null, 'cost' => null, 'currency' => null] && $evs($WJ0) === [],
    '…và đơn đó không tính tiền, không có sự kiện tiền nào');
$bad1 = http('POST', '/api/tool/claim', $TK, ['device' => 'Vi-01', 'pool' => 'wallet-pool', 'wallet' => ['currency' => '1J', 'available' => 1]]);
$bad2 = http('POST', '/api/tool/claim', $TK, ['device' => 'Vi-01', 'pool' => 'wallet-pool', 'wallet' => ['currency' => 'JPY', 'available' => '24000']]);
ok($bad1['code'] === 422 && $bad2['code'] === 422 && ($bad1['json']['error'] ?? '') === 'invalid_wallet', 'ví gửi kèm sai dạng (mã tiền sai / số tiền không phải số nguyên ×100) → 422');

$WJ1 = $mk('W-1', [['code' => 'gem_l', 'qty' => 3]])['json']['job']['id'] ?? '';
$s1 = $claimW('Vi-01', $JPY(2400000));
ok(array_key_exists('job', $s1) && $s1['job'] === null && ($s1['wallet_short'] ?? null) === ['reason' => 'insufficient', 'currency' => 'JPY', 'available' => 2400000, 'need' => 3600000, 'package_codes' => ['gem_l']]
    && Db::val('SELECT status FROM jobs WHERE pid=?', [$WJ1]) === 'queued',
    'ví 24.000 JPY không đủ cho đơn 36.000 JPY → không giao, trả wallet_short (thiếu tiền, cần bao nhiêu, gói nào); đơn vẫn chờ', $s1);
http('POST', "/api/shop/jobs/$WJ1/cancel", $SK);
$WJ2 = $mk('W-2', [['code' => 'noprice', 'qty' => 1]])['json']['job']['id'] ?? '';
$s2 = $claimW('Vi-01', $JPY(2400000));
ok($s2['job'] === null && ($s2['wallet_short']['reason'] ?? '') === 'no_price' && $s2['wallet_short']['package_codes'] === ['noprice'] && $s2['wallet_short']['need'] === null,
    'gói chưa có giá ở loại tiền của ví → bỏ qua đơn, wallet_short no_price kèm mã gói thiếu giá', $s2);
http('POST', "/api/shop/jobs/$WJ2/cancel", $SK);
$WJ2b = $mk('W-2b', [['code' => 'nodisp', 'qty' => 1]])['json']['job']['id'] ?? '';
$s2b = $claimW('Vi-01', $JPY(2400000));
ok($s2b['job'] === null && ($s2b['wallet_short']['package_codes'] ?? null) === ['nodisp'],
    'gói có giá JPY nhưng thiếu chữ giá (dữ liệu cũ) → máy có ví KHÔNG nhận (tool không khớp được giá trên ô gói)', $s2b);
http('POST', "/api/shop/jobs/$WJ2b/cancel", $SK);
$WJ3 = $mk('W-3', [['code' => 'gem_l', 'qty' => 3]])['json']['job']['id'] ?? '';               // quá giá, nằm ĐẦU hàng chờ suốt phần sau
$WJ4 = $mk('W-4', [['code' => 'gem_s', 'qty' => 2], ['code' => 'gem_l', 'qty' => 1]])['json']['job']['id'] ?? '';
$g4 = $claimW('Vi-01', $JPY(2400000));
$j4 = $g4['job'] ?? [];
$it4 = array_column($j4['items'] ?? [], null, 'code');
ok(($j4['id'] ?? '') === $WJ4 && ($it4['gem_s']['price'] ?? 0) === 150000 && ($it4['gem_s']['currency'] ?? '') === 'JPY' && ($it4['gem_s']['price_text'] ?? '') === '¥1,500'
    && ($it4['gem_l']['price'] ?? 0) === 1200000 && ($it4['gem_l']['price_text'] ?? '') === '¥12,000'
    && ($j4['wallet'] ?? null) === ['source' => 'tool', 'currency' => 'JPY', 'cost' => 1500000],
    'đơn đầu hàng quá giá bị bỏ qua, máy nhận đơn sau vừa ví: mỗi gói kèm đơn giá ×100 + loại tiền + CHỮ GIÁ đúng vùng (để khớp số tiền trên ô gói)', $j4);
$r4 = Db::one('SELECT wallet_id, currency, cost, wallet_state FROM jobs WHERE pid=?', [$WJ4]);
ok($r4['wallet_id'] === null && $r4['currency'] === 'JPY' && (int) $r4['cost'] === 1500000 && $r4['wallet_state'] === null && Db::val('SELECT status FROM jobs WHERE pid=?', [$WJ3]) === 'queued',
    'đơn ghi loại tiền + chi phí cả đơn (2×1.500 + 12.000 = 15.000 JPY) lúc giao, không gắn ví gateway; chưa tính tiền khi còn chạy', $r4);
$res4 = $claimW('Vi-01', $JPY(2400000));
ok(($res4['resumed'] ?? false) === true && ($res4['job']['id'] ?? '') === $WJ4 && array_column($res4['job']['items'], 'price') === [150000, 1200000],
    'máy hỏi lại khi đang giữ đơn → trả lại đúng đơn, KHÔNG tính lại giá', $res4['job']['items'] ?? null);

// sửa giá gói qua trang quản trị SAU khi đơn đã giao → đơn đó vẫn trừ theo giá lúc giao
$poolForm = static function (int $id): array {
    $p = Pools::find($id);
    $cfg = $p['cfg'];
    $f = ['id' => $id, 'code' => $p['code'], 'name' => $p['name'], 'game' => $p['game'], 'active' => (int) $p['active'] ? '1' : '0',
          'otp_enabled' => $cfg['otp']['enabled'] ? '1' : '0', 'otp_timeout' => $cfg['otp']['timeout'], 'otp_max' => $cfg['otp']['max_requests'], 'otp_hint' => $cfg['otp']['hint'],
          'require_image' => $cfg['require_image'] ? '1' : '0', 'queue_ttl_min' => intdiv($cfg['queue_ttl'], 60), 'silent_min' => intdiv($cfg['silent_timeout'], 60),
          'currencies' => implode(', ', $cfg['currencies']), 'pk_currencies' => implode(',', $cfg['currencies'])];
    foreach ($cfg['login_fields'] as $lf) {
        $f['lf_key'][] = $lf['key']; $f['lf_label'][] = $lf['label']; $f['lf_type'][] = $lf['type']; $f['lf_required'][] = $lf['required'] ? '1' : '0';
        $f['lf_secret'][] = $lf['secret'] ? '1' : '0'; $f['lf_hint'][] = $lf['hint']; $f['lf_options'][] = implode(', ', $lf['options']);
    }
    foreach ($cfg['rules'] as $r) {
        $f['ru_when'][] = $r['when']; $f['ru_value'][] = $r['value']; $f['ru_note'][] = $r['note'];
    }
    foreach (array_keys(Pools::STEP_LISTS) as $list) {
        foreach ($cfg[$list] as $s) {
            $f[$list . '_type'][] = $s['type']; $f[$list . '_value'][] = $s['value']; $f[$list . '_note'][] = $s['note']; $f[$list . '_optional'][] = $s['optional'] ? '1' : '0';
        }
    }
    $prices = Pools::prices($id);
    foreach (Pools::packages($id) as $k) {
        $f['pk_id'][] = $k['id']; $f['pk_code'][] = $k['code']; $f['pk_name'][] = $k['name']; $f['pk_ocr'][] = $k['ocr_text']; $f['pk_price'][] = $k['price_text'];
        $f['pk_limit'][] = $k['limit_type']; $f['pk_max'][] = $k['max_qty']; $f['pk_active'][] = $k['active'] ? '1' : '0';
        foreach ($cfg['currencies'] as $c) {
            $f['pp_' . $c . '_amount'][] = $prices[(int) $k['id']][$c]['amount'] ?? '';
            $f['pp_' . $c . '_display'][] = $prices[(int) $k['id']][$c]['display'] ?? '';
        }
    }
    return $f;
};
Db::run("DELETE FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['nodisp']]);       // bỏ dữ liệu cũ thiếu chữ giá (form lưu lại sẽ bị từ chối)
$pf = http('GET', "/admin/pools/$wpId", null, null, $ah)['text'];
ok(str_contains($pf, 'Loại tiền dùng trong pool') && str_contains($pf, 'JPY ¥ · giá') && str_contains($pf, 'JPY ¥ · chữ hiện trên máy') && str_contains($pf, 'CHF Fr. · giá')
    && str_contains($pf, 'name="pp_JPY_amount[]" value="1500"') && str_contains($pf, 'value="¥1,500"') && str_contains($pf, 'Chữ giá (mặc định, khi không có giá theo loại tiền)')
    && substr_count($pf, 'name="pp_JPY_amount[]"') === 6,
    'trang sửa pool: ô loại tiền + cột «giá» và «chữ hiện trên máy» cho từng loại tiền ở mỗi gói (cả dòng mẫu để thêm gói)', mb_substr(strip_tags($pf), 0, 120));
$f = $poolForm($wpId);
$f['currencies'] = 'JPY, XX1';
$pv = $post('/admin/pools/save', $f);
ok($pv['code'] === 200 && str_contains($pv['text'], 'XX1') && str_contains($pv['text'], 'không hợp lệ') && str_contains($pv['text'], 'value="¥1,500"')
    && Pools::find($wpId)['cfg']['currencies'] === ['JPY', 'CHF'], 'loại tiền gõ sai → báo lỗi, giữ nguyên các ô giá đang nhập, không lưu gì', $pv['code']);
// danh sách cột khai thiếu (vd trình duyệt cũ đã bỏ JPY khỏi pk_currencies khi ô loại tiền gõ dở) nhưng ô giá JPY vẫn gửi lên:
// trang báo lỗi vẫn dựng lại đủ ô giá JPY → sửa ô loại tiền rồi lưu lần nữa KHÔNG làm mất giá JPY
$f = $poolForm($wpId);
$f['currencies'] = 'JP1Y, CHF';
$f['pk_currencies'] = 'CHF';
$pv = $post('/admin/pools/save', $f);
$f2 = $poolForm($wpId);
$f2['currencies'] = 'USD JPY CHF EUR GBP AUD CAD SGD HKD THB KRW';     // 11 loại tiền → bị từ chối
$f2['pk_currencies'] = '';
$pv2 = $post('/admin/pools/save', $f2);
ok($pv['code'] === 200 && str_contains($pv['text'], 'name="pp_JPY_amount[]" value="1500"') && $pv2['code'] === 200 && str_contains($pv2['text'], 'name="pp_JPY_amount[]" value="1500"')
    && str_contains($pv2['text'], 'name="pk_currencies" value="JPY,CHF"') && (int) Db::val("SELECT amount FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['gem_s']]) === 150000,
    'ô loại tiền bị từ chối (gõ sai / quá 10 loại) mà danh sách cột khai thiếu → trang báo lỗi vẫn giữ đủ ô giá đã gửi; giá trong CSDL không mất', [$pv['code'], $pv2['code']]);
$f = $poolForm($wpId);
$f['pp_JPY_amount'][0] = 'mười';
$pv = $post('/admin/pools/save', $f);
ok($pv['code'] === 200 && str_contains($pv['text'], 'giá JPY') && (int) Db::val("SELECT amount FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['gem_s']]) === 150000,
    'giá gõ sai → báo lỗi rõ gói nào / loại tiền nào, giá cũ giữ nguyên', mb_substr(strip_tags($pv['text']), 0, 80));
$f = $poolForm($wpId);
$f['pp_JPY_amount'][0] = '2.000';
$f['pp_JPY_display'][0] = '¥2,000';
$pv = $post('/admin/pools/save', $f);
ok($pv['code'] === 302 && (int) Db::val("SELECT amount FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['gem_s']]) === 200000
    && Db::val("SELECT display FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['gem_s']]) === '¥2,000'
    && (int) Db::val("SELECT amount FROM package_prices WHERE package_id=? AND currency='CHF'", [$pid['gem_s']]) === 900,
    'admin sửa giá JPY của gói qua trang pool → lưu (giá loại tiền khác giữ nguyên)', $pv['code']);
// nhãn loại tiền KHÔNG phải mã 3 chữ (ký hiệu / tên, gõ kèm dấu chấm): lưu qua FORM thật — giá phải vào CSDL, không được mất lặng lẽ
$f = $poolForm($wpId);
$nRow = count($f['pk_id']);
$f['currencies'] = 'JPY, CHF, kr., ₹';
$f['pk_currencies'] = 'JPY,CHF,KR,₹';
foreach (['KR' => ['12.50', '12,50 kr.'], '₹' => ['99', '₹99.00']] as $lc => [$la, $ld]) {
    $f["pp_{$lc}_amount"] = array_fill(0, $nRow, '');
    $f["pp_{$lc}_display"] = array_fill(0, $nRow, '');
    $f["pp_{$lc}_amount"][0] = $la;
    $f["pp_{$lc}_display"][0] = $ld;
}
$pv = $post('/admin/pools/save', $f);
$labelPrice = static fn (string $c): array => Db::one('SELECT amount, display FROM package_prices WHERE package_id=? AND currency=?', [$pid['gem_s'], $c]) ?: [];
$pg = http('GET', "/admin/pools/$wpId", null, null, $ah)['text'];
ok($pv['code'] === 302 && Pools::find($wpId)['cfg']['currencies'] === ['JPY', 'CHF', 'KR', '₹']
    && (int) ($labelPrice('KR')['amount'] ?? 0) === 1250 && ($labelPrice('KR')['display'] ?? '') === '12,50 kr.' && (int) ($labelPrice('₹')['amount'] ?? 0) === 9900
    && (int) ($labelPrice('JPY')['amount'] ?? 0) === 200000 && str_contains($pg, 'name="pp_KR_amount[]" value="12.50"') && str_contains($pg, 'name="pp_₹_amount[]" value="99.00"'),
    'loại tiền là nhãn tự do («kr.» → KR, «₹»): lưu pool qua form → giá từng nhãn vào CSDL và hiện lại đúng; giá JPY giữ nguyên', [$pv['code'], $labelPrice('KR'), $labelPrice('₹')]);
// ô loại tiền bị từ chối + danh sách cột khai thiếu, với cột giá của NHÃN (không phải mã 3 chữ): trang báo lỗi vẫn dựng lại ô giá đã gửi
$f = $poolForm($wpId);
$f['currencies'] = 'JP1Y';
$f['pk_currencies'] = 'JPY';
$pv = $post('/admin/pools/save', $f);
ok($pv['code'] === 200 && str_contains($pv['text'], 'name="pp_KR_amount[]" value="12.50"') && str_contains($pv['text'], 'name="pp_₹_amount[]" value="99.00"')
    && (int) ($labelPrice('KR')['amount'] ?? 0) === 1250, 'ô loại tiền gõ sai + cột khai thiếu → ô giá của nhãn «KR» / «₹» vẫn còn trên trang báo lỗi, giá trong CSDL không mất', $pv['code']);
$f = $poolForm($wpId);
$f['currencies'] = 'JPY, CHF';
$pv = $post('/admin/pools/save', $f);
ok($pv['code'] === 302 && Pools::find($wpId)['cfg']['currencies'] === ['JPY', 'CHF'] && $labelPrice('KR') === [] && $labelPrice('₹') === []
    && (int) ($labelPrice('JPY')['amount'] ?? 0) === 200000, 'bỏ nhãn khỏi ô loại tiền rồi lưu → xoá giá của nhãn đó, giá còn lại giữ nguyên', $pv['code']);

// ---- tiền của đơn = SỰ KIỆN gửi cho tool; tool áp vào sổ rồi báo đã nhận ----
http('POST', "/api/tool/jobs/$WJ4/images?seq=1", $TK, png(), ['Content-Type: image/png']);
$d4 = http('POST', "/api/tool/jobs/$WJ4/result", $TK, ['result' => 'done', 'items' => [['code' => 'gem_s', 'qty_done' => 2, 'status' => 'done'], ['code' => 'gem_l', 'qty_done' => 1, 'status' => 'done']]]);
$p4 = $evs($WJ4);
ok(($d4['json']['status'] ?? '') === 'done' && array_column($p4, 'kind') === ['purchase', 'purchase'] && array_map('intval', array_column($p4, 'd_balance')) === [-300000, -1200000]
    && array_column($p4, 'package_code') === ['gem_s', 'gem_l'] && array_map('intval', array_column($p4, 'qty')) === [2, 1] && $p4[0]['actor'] === 'tool' && $p4[0]['acked_at'] === null
    && Db::val('SELECT wallet_state FROM jobs WHERE pid=?', [$WJ4]) === 'charged' && (int) Db::val('SELECT COUNT(*) FROM wallet_entries') === 0,
    'tool báo done → mỗi gói một sự kiện «mua gói» cho tool = số đã mua × đơn giá LÚC GIAO (1.500, không phải giá mới 2.000); gateway không ghi sổ ví riêng', $p4);
$again = http('POST', "/api/tool/jobs/$WJ4/result", $TK, ['result' => 'done', 'items' => [['code' => 'gem_s', 'qty_done' => 2, 'status' => 'done']]]);
ok($again['code'] === 200 && count($evs($WJ4)) === 2, 'tool gửi lại kết quả (mất phản hồi) → không trừ tiền lần hai');
ok(ToolWallets::pendingEffect($kidT, 'Vi-01', 'JPY') === -1500000, 'tiền của đơn tool chưa nhận = −15.000 JPY');
$WJ5x = $mk('W-5x', [['code' => 'gem_l', 'qty' => 1]])['json']['job']['id'] ?? '';
$s5x = $claimW('Vi-01', $JPY(2400000));                        // tool chưa kịp trừ đơn vừa xong, vẫn báo 24.000
ok($s5x['job'] === null && ($s5x['wallet_short']['available'] ?? null) === 900000 && ($s5x['wallet_short']['need'] ?? null) === 1200000,
    'tool chưa nhận tiền của đơn vừa xong mà vẫn báo số cũ → gateway tự trừ khoản chưa nhận (còn 9.000) → không giao đơn 12.000 vượt tiền', $s5x);
$evIds0 = array_map('intval', array_column(Db::all('SELECT id FROM tool_wallet_events WHERE job_pid=?', [$WJ4]), 'id'));
$s5y = $claimW('Vi-01', ['currency' => 'JPY', 'available' => 900000, 'applied' => $evIds0]);    // tool ĐÃ áp (còn 9.000) nhưng gateway chưa nhận lời «đã áp»
ok($s5y['job'] === null && ($s5y['wallet_short']['available'] ?? null) === 900000,
    'tool đã áp tiền của đơn (báo 9.000 + id các khoản đã áp) mà gateway chưa nhận lời «đã áp» → gateway KHÔNG trừ lần nữa (vẫn 9.000)', $s5y);
http('POST', "/api/shop/jobs/$WJ5x/cancel", $SK);
$sy = http('POST', '/api/tool/sync', $TK, ['scripts_rev' => str_repeat('a', 32)]);
$evIds = array_column(array_filter($sy['json']['wallet_events'] ?? [], static fn ($e) => $e['job'] === $WJ4), 'id');
$e0 = ($sy['json']['wallet_events'] ?? [])[0] ?? [];
ok($sy['code'] === 200 && count($evIds) === 2 && ($e0['device'] ?? '') === 'Vi-01' && ($e0['kind'] ?? '') === 'purchase' && ($e0['d_balance'] ?? 0) === -300000 && ($e0['currency'] ?? '') === 'JPY'
    && !isset($e0['login']) && !str_contains($sy['text'], 'vi-khach'),
    'tool đồng bộ → nhận các sự kiện tiền chưa áp (máy, đơn, loại, số tiền ×100) — không kèm thông tin khách', $sy['json']['wallet_events'] ?? null);
$other = Keys::create('tool', 'Farm khác');
http('POST', '/api/tool/sync', $other['plain'], ['wallet_acks' => $evIds]);
ok(ToolWallets::pendingEffect($kidT, 'Vi-01', 'JPY') === -1500000, 'khoá Tool khác báo «đã nhận» sự kiện của khoá này → không có tác dụng');
$sy2 = http('POST', '/api/tool/sync', $TK, ['wallet_acks' => $evIds,
    'wallets' => [['device' => 'Vi-01', 'apple_account' => 'apple01@example.com', 'currency' => 'jpy', 'balance' => 900000, 'held' => 0, 'note' => 'vùng Nhật']]]);
$tw = ToolWallets::reported($kidT, 'Vi-01');
ok($sy2['code'] === 200 && ToolWallets::pendingEffect($kidT, 'Vi-01', 'JPY') === 0 && !array_filter($sy2['json']['wallet_events'] ?? [], static fn ($e) => $e['job'] === $WJ4)
    && $tw && $tw['currency'] === 'JPY' && (int) $tw['balance'] === 900000 && $tw['apple_account'] === 'apple01@example.com'
    && !empty(jdec(Keys::find($kidT)['tool_info'])['wallets_by_tool']),
    'tool báo đã áp (wallet_acks) + gửi bản sao ví → sự kiện đóng lại, gateway lưu bản sao (tài khoản, loại tiền, số dư), đánh dấu ví do tool quản lý', $tw);
ok(http('POST', '/api/tool/sync', $TK, ['wallets' => 'x'])['code'] === 422, 'bản sao ví sai dạng → 422, không ghi gì');

$WJ5 = $mk('W-5', [['code' => 'gem_s', 'qty' => 1]])['json']['job']['id'] ?? '';
$g5 = $claimW('Vi-01', $JPY(900000));
$f5 = http('POST', "/api/tool/jobs/$WJ5/result", $TK, ['result' => 'failed', 'message' => 'Sai mật khẩu']);
ok(($g5['job']['id'] ?? '') === $WJ5 && ($g5['job']['items'][0]['price'] ?? 0) === 200000 && ($g5['job']['items'][0]['price_text'] ?? '') === '¥2,000' && ($f5['json']['status'] ?? '') === 'failed'
    && Db::val('SELECT wallet_state FROM jobs WHERE pid=?', [$WJ5]) === 'none' && $evs($WJ5) === [],
    'đơn mới giao sau khi sửa giá dùng giá mới (2.000); tool báo failed → không trừ tiền, không có sự kiện', $g5['job']['items'] ?? null);

$WJ6 = $mk('W-6', [['code' => 'gem_s', 'qty' => 2]])['json']['job']['id'] ?? '';
$claimW('Vi-01', $JPY(900000));
$rv6 = http('POST', "/api/tool/jobs/$WJ6/result", $TK, ['result' => 'review', 'message' => 'Không chắc đã mua']);
$id6 = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$WJ6]);
$h6 = $evs($WJ6);
ok(($rv6['json']['status'] ?? '') === 'review' && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id6]) === 'held'
    && count($h6) === 1 && $h6[0]['kind'] === 'hold' && (int) $h6[0]['d_held'] === 400000 && (int) $h6[0]['d_balance'] === 0 && ToolWallets::pendingEffect($kidT, 'Vi-01', 'JPY') === -400000,
    'tool báo review → sự kiện TẠM GIỮ cả chi phí đơn (4.000): số dư không đổi, còn dùng được giảm', $h6);
http('POST', "/api/tool/jobs/$WJ6/result", $TK, ['result' => 'done', 'message' => 'Thật ra mua rồi']);
ok(count($evs($WJ6)) === 1 && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id6]) === 'held', 'báo muộn sau khi đã sang đối soát → không trừ / giữ thêm gì');
$jp = http('GET', "/admin/jobs/$id6", null, null, $ah)['text'];
ok(str_contains($jp, 'Số tiền đã trừ (JPY)') && str_contains($jp, 'name="charge"') && str_contains($jp, 'value="4000"') && str_contains($jp, 'tạm giữ 4.000 JPY')
    && str_contains($jp, 'apple01@example.com') && str_contains($jp, 'ví do tool quản lý') && str_contains($jp, 'Tiền của đơn gửi cho tool') && str_contains($jp, 'Tạm giữ'),
    'trang đơn chờ đối soát: ô «Số tiền đã trừ» điền sẵn chi phí, tài khoản Apple (theo bản sao ví của tool), sự kiện tiền của đơn',
    array_filter(['charge' => str_contains($jp, 'Số tiền đã trừ (JPY)'), 'v4000' => str_contains($jp, 'value="4000"'), 'tg' => str_contains($jp, 'tạm giữ 4.000 JPY'), 'acc' => str_contains($jp, 'apple01@example.com'), 'tq' => str_contains($jp, 'ví do tool quản lý'), 'ev' => str_contains($jp, 'Tiền của đơn gửi cho tool')], static fn ($v) => !$v));
$big = $post("/admin/jobs/$id6/resolve", ['to' => 'done', 'charge' => '40001']);
$negc = $post("/admin/jobs/$id6/resolve", ['to' => 'done', 'charge' => '-1']);
ok($big['code'] === 302 && $negc['code'] === 302 && Db::val('SELECT status FROM jobs WHERE id=?', [$id6]) === 'review' && count($evs($WJ6)) === 1
    && str_contains(http('GET', "/admin/jobs/$id6", null, null, $ah)['text'], 'vượt quá 10 lần'), 'số tiền đã trừ > 10 lần chi phí / âm → từ chối, đơn vẫn chờ đối soát');
$ok6 = $post("/admin/jobs/$id6/resolve", ['to' => 'done', 'charge' => '2.500', 'note' => 'mua được 1/2 gói + phí']);
$c6 = Db::all('SELECT kind, d_balance, d_held, note, actor FROM tool_wallet_events WHERE job_id=? ORDER BY id', [$id6]);
ok($ok6['code'] === 302 && Db::val('SELECT status FROM jobs WHERE id=?', [$id6]) === 'done' && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id6]) === 'charged'
    && array_column($c6, 'kind') === ['hold', 'charge'] && (int) $c6[1]['d_balance'] === -250000 && (int) $c6[1]['d_held'] === -400000 && $c6[1]['note'] === 'mua được 1/2 gói + phí' && $c6[1]['actor'] === 'admin:chu'
    && ToolWallets::pendingEffect($kidT, 'Vi-01', 'JPY') === -250000,
    'admin chốt «đã nạp» với số tiền thật 2.500 → sự kiện «trừ khi đối soát» −2.500 và đóng tạm giữ 4.000', $c6);
ok(!Jobs::adminResolve($id6, 'failed', 'chu') && count($evs($WJ6)) === 2, 'chốt lần hai bị từ chối, không thêm sự kiện');

$WJ7 = $mk('W-7', [['code' => 'gem_s', 'qty' => 1]])['json']['job']['id'] ?? '';
$claimW('Vi-01', $JPY(900000));
$nb = http('POST', "/api/tool/jobs/$WJ7/result", $TK, ['result' => 'done', 'items' => [['code' => 'gem_s', 'qty_done' => 1, 'status' => 'done']]]);
$id7 = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$WJ7]);
ok(($nb['json']['status'] ?? '') === 'review' && Db::val('SELECT review_reason FROM jobs WHERE id=?', [$id7]) === 'no_bill' && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id7]) === 'held'
    && array_column($evs($WJ7), 'kind') === ['hold'], 'báo done mà thiếu ảnh → đối soát (no_bill) → TẠM GIỮ như review, chưa trừ tiền');
$rel = $post("/admin/jobs/$id7/resolve", ['to' => 'failed', 'note' => 'lịch sử Apple không có giao dịch']);
$e7 = $evs($WJ7);
ok($rel['code'] === 302 && Db::val('SELECT status FROM jobs WHERE id=?', [$id7]) === 'failed' && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id7]) === 'released'
    && array_column($e7, 'kind') === ['hold', 'release'] && (int) $e7[1]['d_held'] === -200000 && (int) $e7[1]['d_balance'] === 0,
    'admin chốt «chưa nạp» → sự kiện «nhả tạm giữ» (số dư không đổi)', $e7);

$WJ8 = $mk('W-8', [['code' => 'gem_s', 'qty' => 1]])['json']['job']['id'] ?? '';
$claimW('Vi-01', $JPY(900000));
$id8 = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$WJ8]);
Db::run('UPDATE jobs SET seen_at=? WHERE id=?', [time() - 7200, $id8]);
$sw = http('GET', '/cron/tick?key=cronkey123')['json'];
$e8 = $evs($WJ8);
ok(($sw['sweep']['timeout'] ?? 0) >= 1 && Db::val('SELECT status FROM jobs WHERE id=?', [$id8]) === 'review' && Db::val('SELECT wallet_state FROM jobs WHERE id=?', [$id8]) === 'held'
    && count($e8) === 1 && $e8[0]['kind'] === 'hold' && (int) $e8[0]['d_held'] === 200000 && $e8[0]['actor'] === 'system',
    'tool im lặng quá lâu → đối soát (timeout) → hệ thống TẠM GIỮ chi phí đơn', [$sw, $e8]);
http('POST', "/api/tool/jobs/$WJ8/result", $TK, ['result' => 'done']);
ok(count($evs($WJ8)) === 1, 'tool báo done muộn sau timeout → không trừ thêm');
ok(Jobs::adminResolve($id8, 'done', 'chu') && array_column($evs($WJ8), 'kind') === ['hold', 'charge'] && (int) $evs($WJ8)[1]['d_balance'] === -200000,
    'chốt «đã nạp» không nhập số tiền (gọi trong mã) → trừ đúng chi phí đơn (2.000)');
$j4p = http('GET', '/admin/jobs/' . Db::val('SELECT id FROM jobs WHERE pid=?', [$WJ4]), null, null, $ah)['text'];
ok(str_contains($j4p, 'Tiền của đơn gửi cho tool') && str_contains($j4p, 'Mua gói') && str_contains($j4p, '15.000 JPY') && str_contains($j4p, 'đã trừ tiền') && str_contains($j4p, '1.500 JPY / gói'),
    'trang đơn: tài khoản Apple, chi phí, trạng thái tiền và các sự kiện tiền của đơn');
http('POST', '/api/tool/sync', $TK, ['wallets' => [['device' => 'Vi-01', 'apple_account' => 'apple01@example.com', 'currency' => 'JPY', 'balance' => 650000, 'held' => 0]]]);
$wlist = http('GET', '/admin/wallets', null, null, $ah)['text'];
ok(str_contains($wlist, 'apple01@example.com') && str_contains($wlist, 'Vi-01') && str_contains($wlist, 'Trừ khi đối soát') && str_contains($wlist, 'chưa nhận') && str_contains($wlist, 'đã nhận'),
    'trang ví: bản sao ví tool báo + các sự kiện tiền của đơn (tool đã nhận / chưa nhận)');
$dash = http('GET', '/admin', null, null, $ah)['text'];
ok(str_contains($dash, 'Ví sắp hết tiền') && str_contains($dash, 'apple01@example.com') && str_contains($dash, '12.000 JPY'), 'Tổng quan: ví còn dùng được thấp hơn gói đắt nhất (12.000 JPY) được nêu ra');
http('POST', '/api/tool/sync', $TK, ['wallets' => []]);
ok(ToolWallets::reported($kidT, 'Vi-01') === null, 'tool bỏ ví của máy (bản sao không còn máy đó) → gateway xoá bản sao');
// ví cũ khai ở gateway (trước khi ví chuyển về tool): KHÔNG còn áp khi giao đơn mới — chỉ để tra
Db::insert('wallets', ['tool_key_id' => $kidT, 'device' => 'Vi-01', 'apple_account' => 'cu@example.com', 'currency' => 'JPY', 'balance' => 100, 'active' => 1, 'note' => '', 'created_at' => time(), 'updated_at' => time()]);
$g3 = $claimW('Vi-01');
ok(($g3['job']['id'] ?? '') === $WJ3 && !isset($g3['job']['wallet']) && !isset($g3['job']['items'][0]['price']) && Db::val('SELECT currency FROM jobs WHERE pid=?', [$WJ3]) === null,
    'máy không gửi ví khi xin đơn → nhận đơn như máy không có ví (ví cũ khai trên gateway KHÔNG áp nữa, dù còn «đang dùng»)', $g3);
http('POST', "/api/tool/jobs/$WJ3/result", $TK, ['result' => 'failed']);

// ---- gói «chỉ 1 lần / tài khoản game» ----
$o1 = $mk('O-1', [['code' => 'pass', 'qty' => 1]], 'Khach.Once@Example.com');
$o2 = $mk('O-2', [['code' => 'pass', 'qty' => 1], ['code' => 'gem_s', 'qty' => 1]], '  khach.once@example.com ');
$o3 = $mk('O-3', [['code' => 'gem_s', 'qty' => 1]], 'khach.once@example.com');
$o1row = Db::one('SELECT account_key, login_enc FROM jobs WHERE pid=?', [$o1['json']['job']['id'] ?? '']);
ok($o1['code'] === 201 && $o2['code'] === 422 && ($o2['json']['error'] ?? '') === 'already_bought' && ($o2['json']['code'] ?? '') === 'pass' && str_contains($o2['json']['message'] ?? '', 'Gói 1 lần')
    && $o3['code'] === 201, 'gói «1 lần / tài khoản»: cùng tài khoản game (khác hoa/thường, khoảng trắng) đặt lại → 422 already_bought; gói thường vẫn đặt được', [$o2['code'], $o2['json']]);
ok($o1row && $o1row['account_key'] === hash_hmac('sha256', $wpId . ':khach.once@example.com', 'account-key:' . (string) Env::get('APP_KEY', ''))
    && $o1row['account_key'] !== hash('sha256', $wpId . ':khach.once@example.com')
    && !str_contains(json_encode(Db::all('SELECT account_key, account_hint, items, note FROM jobs')), 'khach.once'),
    'đơn chỉ lưu MÃ BĂM CÓ KHOÁ (HMAC bằng APP_KEY) của pool:tài khoản — không lưu định danh thô, không đoán ngược được bằng cách thử email');
http('POST', '/api/shop/jobs/' . ($o1['json']['job']['id'] ?? '') . '/cancel', $SK);
$o4 = $mk('O-4', [['code' => 'pass', 'qty' => 1]], 'khach.once@example.com');
ok($o4['code'] === 201, 'đơn trước bị huỷ (chưa mất tiền) → tài khoản đó mua lại được gói 1 lần', $o4['json']);
Pools::savePackages($wpId2 = Pools::save(null, 'wallet-pool-2', 'Pool ví 2', 'Game', true, $wc), [['code' => 'pass', 'name' => 'Gói 1 lần (pool 2)', 'limit_type' => 'once', 'active' => true]]);
$o5 = http('POST', '/api/shop/jobs', $SK, ['ref' => 'O-5', 'pool' => 'wallet-pool-2', 'login' => ['username' => 'khach.once@example.com', 'password' => 'x'], 'items' => [['code' => 'pass', 'qty' => 1]]]);
ok($o5['code'] === 201, 'giới hạn tính theo TỪNG pool: cùng tài khoản, cùng mã gói ở pool khác vẫn đặt được', $o5['json']);
http('POST', '/api/shop/jobs/' . ($o5['json']['job']['id'] ?? '') . '/cancel', $SK);
// pool có ô CHỌN server đứng trước ô tài khoản: định danh là ô CHỮ bắt buộc (tài khoản), không phải server — khách khác cùng server không bị chặn nhầm
$wc3 = $wc;
$wc3['login_fields'] = [['key' => 'server', 'label' => 'Server', 'type' => 'select', 'required' => true, 'options' => ['Asia', 'EU']],
                        ['key' => 'username', 'label' => 'Tài khoản', 'type' => 'text', 'required' => true],
                        ['key' => 'password', 'label' => 'Mật khẩu', 'type' => 'password', 'required' => true]];
Pools::savePackages(Pools::save(null, 'wallet-pool-3', 'Pool ví 3', 'Game', true, $wc3), [['code' => 'pass', 'name' => 'Gói 1 lần (pool 3)', 'limit_type' => 'once', 'active' => true]]);
$sv = static fn (string $ref, string $u) => http('POST', '/api/shop/jobs', $SK, ['ref' => $ref, 'pool' => 'wallet-pool-3', 'login' => ['server' => 'Asia', 'username' => $u, 'password' => 'x'], 'items' => [['code' => 'pass', 'qty' => 1]]]);
$s1 = $sv('S-1', 'nguoi.a@example.com'); $s2 = $sv('S-2', 'nguoi.b@example.com'); $s3 = $sv('S-3', 'Nguoi.A@example.com');
ok($s1['code'] === 201 && $s2['code'] === 201 && $s3['code'] === 422 && ($s3['json']['error'] ?? '') === 'already_bought',
    'ô chọn server đứng đầu: hai khách khác nhau cùng server đều đặt được; đúng tài khoản cũ đặt lại thì bị chặn', [$s1['code'], $s2['code'], $s3['code']]);
foreach ([$s1, $s2] as $sj) { http('POST', '/api/shop/jobs/' . ($sj['json']['job']['id'] ?? '') . '/cancel', $SK); }
ok(Money::parse('+5', 'JPY') === null && Money::parse('+5', 'JPY', true) === 500, 'số tiền không dấu không nhận «+»; chỉnh số dư (có dấu) thì nhận');
ok(Money::example('DKK') === '63,00 kr' && Money::example('JPY') === '¥1,500' && str_contains(Money::example('XYZ'), 'XYZ'), 'chữ giá mẫu theo ĐÚNG loại tiền (không gợi ý «CHF» cho ô DKK)');
// nhiều đơn khác ref cho cùng tài khoản + gói 1 lần gửi CÙNG LÚC → đúng MỘT đơn được nhận
$mh = curl_multi_init();
$hs = [];
for ($i = 1; $i <= 6; $i++) {
    $ch = curl_init("http://127.0.0.1:$port/api/shop/jobs");
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $SK, 'Content-Type: application/json'],
        CURLOPT_POSTFIELDS => json_encode(['pool' => 'wallet-pool', 'ref' => "RACE-$i", 'login' => ['username' => 'dua@example.com', 'password' => 'x'], 'items' => [['code' => 'pass', 'qty' => 1]]])]);
    curl_multi_add_handle($mh, $ch);
    $hs[$i] = $ch;
}
do {
    curl_multi_exec($mh, $running);
    curl_multi_select($mh, 0.2);
} while ($running > 0);
$codes = [];
foreach ($hs as $ch) {
    $codes[] = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
}
sort($codes);
ok($codes === [201, 422, 422, 422, 422, 422] && (int) Db::val("SELECT COUNT(*) FROM jobs WHERE ref LIKE 'RACE-%'") === 1,
    '6 đơn khác ref, cùng tài khoản + gói 1 lần gửi cùng lúc → đúng 1 đơn được nhận, 5 đơn 422', $codes);
foreach (Db::all("SELECT pid FROM jobs WHERE pool_id=? AND status='queued'", [$wpId]) as $q) {
    http('POST', '/api/shop/jobs/' . $q['pid'] . '/cancel', $SK);
}

echo "\n== Quản lý đơn: tạo đơn thử, xem / sửa / đổi trạng thái / xoá ==\n";
$ac = $wc;
$ac['currencies'] = ['JPY'];
$ac['require_image'] = false;
$apId = Pools::save(null, 'admin-pool', 'Pool quản trị', 'Game', true, $ac);
Pools::savePackages($apId, [
    ['code' => 'g1', 'name' => 'Gói A', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true, 'prices' => ['JPY' => ['amount' => '1000', 'display' => '¥1,000']]],
    ['code' => 'one', 'name' => 'Gói 1 lần', 'limit_type' => 'once', 'active' => true, 'prices' => ['JPY' => ['amount' => '500', 'display' => '¥500']]],
]);
$jl = http('GET', '/admin/jobs', null, null, $ah);
ok($jl['code'] === 200 && str_contains($jl['text'], 'Tạo đơn thử') && str_contains($jl['text'], 'admin-pool') && str_contains($jl['text'], 'tabler-pencil') && str_contains($jl['text'], 'tabler-trash'),
    'danh sách đơn: nút «Tạo đơn thử» (modal mang cấu hình pool) + nút xem / sửa / xoá từng đơn', $jl['code']);
$form = static fn (string $path, array $f): array => json_decode($post($path, $f)['text'], true) ?? [];
$tf = ['pool' => 'admin-pool', 'ref' => 'TEST-1', 'login' => ['username' => 'thu@example.com', 'password' => 'MK cu#1'], 'pk_code' => ['g1', 'one'], 'pk_qty' => ['2', '0'], 'note' => 'thử'];
$noC = http('POST', '/admin/jobs/create', null, http_build_query($tf), array_merge($ah, ['Content-Type: application/x-www-form-urlencoded']));
ok($noC['code'] === 419 && (int) Db::val("SELECT COUNT(*) FROM jobs WHERE ref='TEST-1'") === 0, 'tạo đơn thử không có mã CSRF → 419, không tạo gì');
$c0 = $form('/admin/jobs/create', ['pk_qty' => ['0', '0']] + $tf);
ok(($c0['ok'] ?? null) === false && str_contains((string) ($c0['error'] ?? ''), 'items'), 'không chọn gói nào → báo lỗi ngay trong modal', $c0);
$c1 = $form('/admin/jobs/create', $tf);
$T1 = Db::one("SELECT * FROM jobs WHERE ref='TEST-1'");
$tkey = Keys::find((int) Settings::get('admin_test_key_id', '0'));
ok(($c1['ok'] ?? false) === true && $T1 && ($c1['url'] ?? '') === '/admin/jobs/' . $T1['id'] && $T1['status'] === 'queued' && $tkey && (int) $T1['shop_key_id'] === (int) $tkey['id']
    && $tkey['kind'] === 'shop' && empty($tkey['webhook_url']) && array_column(jdec($T1['items']), 'qty', 'code') === ['g1' => 2] && !str_contains((string) $T1['login_enc'], 'thu@'),
    'tạo đơn thử → đơn THẬT chờ máy, mang khoá «Đơn thử» (không có webhook), đúng gói, thông tin đăng nhập được mã hoá', [$c1, $T1['status'] ?? null]);
$c2 = $form('/admin/jobs/create', $tf);
ok(($c2['ok'] ?? null) === false && str_contains((string) ($c2['error'] ?? ''), 'đổi mã') && (int) Db::val("SELECT COUNT(*) FROM jobs WHERE ref='TEST-1'") === 1, 'mã đơn thử trùng → báo đổi mã, không tạo thêm', $c2);
$jp = http('GET', '/admin/jobs/' . $T1['id'], null, null, $ah)['text'];
ok(str_contains($jp, 'đơn thử') && str_contains($jp, '••••••') && !str_contains($jp, 'thu@example.com') && !str_contains($jp, 'MK cu#1') && str_contains($jp, 'id="m-edit"') && str_contains($jp, 'data-job-edit'),
    'trang đơn: thông tin đăng nhập bị che (không nằm trong HTML), có hộp Sửa đầy đủ cho đơn chờ máy');
$lv = $form('/admin/jobs/' . $T1['id'] . '/login', []);
$evs = Db::all('SELECT type, message FROM job_events WHERE job_id=?', [$T1['id']]);
ok(($lv['login']['username'] ?? '') === 'thu@example.com' && ($lv['login']['password'] ?? '') === 'MK cu#1' && in_array('login_viewed', array_column($evs, 'type'), true)
    && !str_contains(json_encode($evs, JSON_UNESCAPED_UNICODE), 'MK cu') && !str_contains(json_encode($evs, JSON_UNESCAPED_UNICODE), 'thu@'),
    'bấm «Hiện» → trả thông tin đăng nhập, ghi nhật ký đơn «đã xem» (không ghi giá trị)', $lv);

// ---- sửa đơn chờ máy ----
$u1 = $form('/admin/jobs/' . $T1['id'] . '/update', ['scope' => 'full', 'ref' => 'TEST-1b', 'login' => ['username' => 'moi@example.com', 'password' => ''],
    'pk_code' => ['g1', 'one'], 'pk_qty' => ['1', '1'], 'note' => 'đã sửa']);
$T1b = Jobs::byId((int) $T1['id']);
$lg = jdec(Crypto::dec($T1b['login_enc']));
$ev = (string) Db::val("SELECT message FROM job_events WHERE job_id=? AND type='edited' ORDER BY id DESC LIMIT 1", [$T1['id']]);
ok(($u1['ok'] ?? false) === true && $T1b['ref'] === 'TEST-1b' && $lg === ['username' => 'moi@example.com', 'password' => 'MK cu#1'] && array_column(jdec($T1b['items']), 'qty', 'code') === ['g1' => 1, 'one' => 1]
    && $T1b['note'] === 'đã sửa' && str_contains($ev, 'mã đơn') && str_contains($ev, 'thông tin đăng nhập') && str_contains($ev, 'gói nạp') && !str_contains($ev, 'moi@'),
    'sửa đơn chờ máy: mã đơn, tài khoản (ô mật khẩu trống = giữ nguyên), gói + số lượng, ghi chú; nhật ký ghi đã sửa phần nào (không ghi giá trị)', [$u1, $lg, $ev]);
$u2 = $form('/admin/jobs/' . $T1['id'] . '/update', ['scope' => 'full', 'ref' => 'TEST-1b', 'login' => ['username' => 'moi@example.com'], 'pk_code' => ['g1'], 'pk_qty' => ['9']]);
ok(($u2['ok'] ?? null) === false && str_contains((string) ($u2['error'] ?? ''), 'tối đa') && Jobs::byId((int) $T1['id'])['items'] === $T1b['items'], 'sửa số lượng vượt giới hạn gói → báo lỗi, đơn giữ nguyên', $u2);
$c3 = $form('/admin/jobs/create', ['ref' => 'TEST-2', 'login' => ['username' => 'khac@example.com', 'password' => 'x'], 'pk_code' => ['one'], 'pk_qty' => ['1']] + $tf);
$T2 = (int) Db::val("SELECT id FROM jobs WHERE ref='TEST-2'");
$u3 = $form("/admin/jobs/$T2/update", ['scope' => 'full', 'ref' => 'TEST-2', 'login' => ['username' => 'MOI@example.com', 'password' => ''], 'pk_code' => ['one'], 'pk_qty' => ['1']]);
ok(($c3['ok'] ?? false) === true && ($u3['ok'] ?? null) === false && str_contains((string) ($u3['error'] ?? ''), '1 lần') && jdec(Crypto::dec(Jobs::byId($T2)['login_enc']))['username'] === 'khac@example.com',
    'sửa tài khoản thành một tài khoản đã có đơn gói «1 lần» → từ chối (không lách được giới hạn bằng cách sửa đơn)', $u3);
$u3b = $form("/admin/jobs/$T2/update", ['scope' => 'full', 'ref' => 'TEST-1b', 'login' => ['username' => 'khac@example.com', 'password' => ''], 'pk_code' => ['one'], 'pk_qty' => ['1']]);
ok(($u3b['ok'] ?? null) === false && str_contains((string) ($u3b['error'] ?? ''), 'TEST-1b'), 'đổi mã đơn trùng với đơn khác của cùng shop → từ chối', $u3b);
$d2 = $post("/admin/jobs/$T2/delete", ['back' => 'list']);
ok($d2['code'] === 302 && str_contains($d2['head'], 'Location: /admin/jobs') && Jobs::byId($T2) === null && (int) Db::val('SELECT COUNT(*) FROM job_events WHERE job_id=?', [$T2]) === 0,
    'xoá đơn chờ máy → huỷ rồi xoá hẳn (cả nhật ký)', $d2['code']);

// ---- đơn đã giao máy ----
$cl = http('POST', '/api/tool/claim', $TK, ['device' => 'Adm-1', 'pool' => 'admin-pool'])['json'];
ok(($cl['job']['ref'] ?? '') === 'TEST-1b' && ($cl['job']['login']['password'] ?? '') === 'MK cu#1', 'máy nhận đơn thử như đơn thường (đúng dữ liệu đã sửa)', $cl['job']['ref'] ?? null);
$u4 = $form('/admin/jobs/' . $T1['id'] . '/update', ['scope' => 'full', 'ref' => 'X', 'pk_code' => ['g1'], 'pk_qty' => ['1']]);
$u5 = $form('/admin/jobs/' . $T1['id'] . '/update', ['scope' => 'note', 'note' => 'máy đang làm']);
ok(($u4['ok'] ?? null) === false && str_contains((string) ($u4['error'] ?? ''), 'chỉ sửa được ghi chú') && ($u5['ok'] ?? false) === true
    && Jobs::byId((int) $T1['id'])['note'] === 'máy đang làm' && Jobs::byId((int) $T1['id'])['ref'] === 'TEST-1b', 'đơn đã giao máy: chỉ sửa được ghi chú', [$u4, $u5]);
$post('/admin/jobs/' . $T1['id'] . '/delete', []);
ok(Jobs::byId((int) $T1['id']) !== null, 'đơn máy đang làm → KHÔNG xoá được');
$st = static fn (int $id, array $f): array => $post("/admin/jobs/$id/status", $f);
$st((int) $T1['id'], ['to' => 'done']);
ok(Jobs::byId((int) $T1['id'])['status'] === 'claimed', 'đơn đang chạy không đổi thẳng sang «hoàn tất» được (phải qua đối soát)');
$st((int) $T1['id'], ['to' => 'review', 'note' => 'máy treo']);
$T1r = Jobs::byId((int) $T1['id']);
$late = http('POST', '/api/tool/jobs/' . $T1['pid'] . '/result', $TK, ['result' => 'failed']);
ok($T1r['status'] === 'review' && $T1r['review_reason'] === 'admin' && $T1r['login_enc'] === null && $late['code'] === 409,
    'admin chuyển đơn đang chạy sang CHỜ ĐỐI SOÁT (xoá thông tin đăng nhập); máy báo muộn «failed» bị từ chối', [$T1r['status'], $late['code']]);
$st((int) $T1['id'], ['to' => 'done']);
ok(Jobs::byId((int) $T1['id'])['status'] === 'done', 'chờ đối soát → hoàn tất (như nút chốt)');

// ---- tiền ví khi đổi trạng thái ----
// máy Adm-W có ví ở TOOL: 100.000 JPY. Số dư theo sổ của tool = 100.000 + tổng «đổi số dư» của các sự kiện gateway gửi cho máy này
$bal = static fn (): int => 10000000 + (int) Db::val("SELECT COALESCE(SUM(d_balance), 0) FROM tool_wallet_events WHERE tool_key_id=? AND device='Adm-W'", [$kidT]);
$heldAW = static fn (): int => (int) Db::val("SELECT COALESCE(SUM(d_held), 0) FROM tool_wallet_events WHERE tool_key_id=? AND device='Adm-W'", [$kidT]);
$walAW = ['currency' => 'JPY', 'available' => 10000000];
$mkA = static fn (string $ref, int $qty): string => (string) (http('POST', '/api/shop/jobs', $SK, ['pool' => 'admin-pool', 'ref' => $ref, 'login' => ['username' => strtolower($ref) . '@example.com', 'password' => 'x'],
    'items' => [['code' => 'g1', 'qty' => $qty]]])['json']['job']['id'] ?? '');
$S1 = $mkA('ADM-S1', 3);
http('POST', '/api/tool/claim', $TK, ['device' => 'Adm-W', 'pool' => 'admin-pool', 'wallet' => $walAW]);
http('POST', "/api/tool/jobs/$S1/result", $TK, ['result' => 'done']);
$S1id = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$S1]);
ok(Jobs::byId($S1id)['status'] === 'done' && Jobs::byId($S1id)['wallet_state'] === 'charged' && $bal() === 9700000, 'đơn trả bằng ví xong → trừ 3.000 JPY', $bal());
$st($S1id, ['to' => 'failed', 'note' => 'kiểm lại: chưa nạp']);
$S1f = Jobs::byId($S1id);
$pl = jdec((string) Db::val("SELECT payload FROM webhooks WHERE job_id=? AND event='job.failed' ORDER BY id DESC LIMIT 1", [$S1id]));
ok($S1f['status'] === 'failed' && $S1f['wallet_state'] === 'none' && $bal() === 10000000 && ($pl['corrected'] ?? null) === true && ($pl['previous_status'] ?? '') === 'done'
    && Db::val('SELECT kind FROM tool_wallet_events WHERE job_id=? ORDER BY id DESC LIMIT 1', [$S1id]) === 'refund',
    'hoàn tất → thất bại: hoàn đúng 3.000 JPY vào ví (dòng «Hoàn tiền đơn»), shop nhận job.failed kèm corrected + previous_status', [$S1f['status'], $bal(), $pl['corrected'] ?? null]);
$st($S1id, ['to' => 'done', 'charge' => 'abc']);
ok(Jobs::byId($S1id)['status'] === 'failed' && $bal() === 10000000, 'số tiền đã trừ nhập sai → không đổi gì');
$st($S1id, ['to' => 'done', 'charge' => '2500', 'note' => 'đã nạp thật']);
$pl2 = jdec((string) Db::val("SELECT payload FROM webhooks WHERE job_id=? AND event='job.done' ORDER BY id DESC LIMIT 1", [$S1id]));
ok(Jobs::byId($S1id)['status'] === 'done' && Jobs::byId($S1id)['wallet_state'] === 'charged' && $bal() === 9750000 && ($pl2['previous_status'] ?? '') === 'failed',
    'thất bại → hoàn tất: trừ ví đúng số tiền admin nhập (2.500 JPY), shop nhận job.done kèm corrected', $bal());
$st($S1id, ['to' => 'failed']);
ok($bal() === 10000000, 'đổi lại sang thất bại → hoàn đúng 2.500 JPY vừa trừ (không hoàn thừa / thiếu)', $bal());
$nE = (int) Db::val('SELECT COUNT(*) FROM tool_wallet_events WHERE job_id=?', [$S1id]);
$post("/admin/jobs/$S1id/delete", []);
ok(Jobs::byId($S1id) === null && (int) Db::val('SELECT COUNT(*) FROM tool_wallet_events WHERE job_pid=? AND job_id IS NULL', [$S1]) === $nE && $nE >= 4 && $bal() === 10000000,
    'xoá đơn đã kết thúc: các sự kiện tiền của đơn (gửi cho tool) giữ nguyên (còn mã đơn), số dư không đổi', [$nE, $bal()]);
$S2 = $mkA('ADM-S2', 1);
http('POST', '/api/tool/claim', $TK, ['device' => 'Adm-W', 'pool' => 'admin-pool', 'wallet' => $walAW]);
http('POST', "/api/tool/jobs/$S2/result", $TK, ['result' => 'review', 'message' => 'không chắc']);
$S2id = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$S2]);
$post("/admin/jobs/$S2id/delete", []);
ok(Jobs::byId($S2id) !== null && Jobs::byId($S2id)['wallet_state'] === 'held', 'đơn chờ đối soát còn TẠM GIỮ ví → không xoá được');
$st($S2id, ['to' => 'failed']);
$post("/admin/jobs/$S2id/delete", []);
ok(Jobs::byId($S2id) === null && $heldAW() === 0 && $bal() === 10000000, 'chốt «chưa nạp» (nhả tạm giữ) rồi xoá được');
$S3 = $mkA('ADM-S3', 1);
$S3id = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$S3]);
$post("/admin/jobs/$S3id/delete", []);
Webhooks::deliverDue();
$hooked = false;
foreach (file("$tmp/hooks.log", FILE_IGNORE_NEW_LINES) ?: [] as $line) {
    $b = json_decode((string) (json_decode($line, true)['body'] ?? ''), true) ?: [];
    $hooked = $hooked || (($b['event'] ?? '') === 'job.cancelled' && ($b['job']['ref'] ?? '') === 'ADM-S3' && ($b['by'] ?? '') === 'admin');
}
ok(Jobs::byId($S3id) === null && $hooked, 'xoá đơn của shop đang chờ máy → shop vẫn nhận webhook job.cancelled (by: admin)');
ok(str_contains(http('GET', '/docs')['text'], 'corrected'), 'tài liệu webhook có corrected / previous_status');
// đơn của SHOP: không đổi được mã đơn (khoá chống tạo trùng của shop), vẫn sửa được phần khác
$S4 = $mkA('ADM-S4', 1);
$S4id = (int) Db::val('SELECT id FROM jobs WHERE pid=?', [$S4]);
$r4a = $form("/admin/jobs/$S4id/update", ['scope' => 'full', 'ref' => 'ADM-S4-moi', 'login' => ['username' => 'adm-s4@example.com', 'password' => ''], 'pk_code' => ['g1'], 'pk_qty' => ['1']]);
$r4b = $form("/admin/jobs/$S4id/update", ['scope' => 'full', 'ref' => 'ADM-S4', 'login' => ['username' => 'adm-s4@example.com', 'password' => ''], 'pk_code' => ['g1'], 'pk_qty' => ['2']]);
$retry = http('POST', '/api/shop/jobs', $SK, ['pool' => 'admin-pool', 'ref' => 'ADM-S4', 'login' => ['username' => 'x@example.com', 'password' => 'x'], 'items' => [['code' => 'g1', 'qty' => 1]]]);
ok(($r4a['ok'] ?? null) === false && str_contains((string) ($r4a['error'] ?? ''), 'đơn thử') && ($r4b['ok'] ?? false) === true && Jobs::byId($S4id)['ref'] === 'ADM-S4'
    && ($retry['json']['duplicate'] ?? false) === true, 'đơn của shop: không đổi được mã đơn (shop gửi lại vẫn ra đúng đơn cũ, không tạo đơn thật thứ hai); sửa gói vẫn được', [$r4a, $r4b, $retry['code']]);
// gói của đơn vừa bị TẮT: vẫn sửa được ghi chú (không bị kẹt vì kiểm lại gói)
Db::run("UPDATE packages SET active=0 WHERE pool_id=? AND code='g1'", [$apId]);
$r4c = $form("/admin/jobs/$S4id/update", ['scope' => 'full', 'ref' => 'ADM-S4', 'login' => ['username' => 'adm-s4@example.com', 'password' => ''], 'pk_code' => ['g1'], 'pk_qty' => ['2'], 'note' => 'gói tắt']);
$r4d = $form("/admin/jobs/$S4id/update", ['scope' => 'full', 'ref' => 'ADM-S4', 'login' => ['username' => 'adm-s4@example.com', 'password' => ''], 'pk_code' => ['g1'], 'pk_qty' => ['3']]);
Db::run("UPDATE packages SET active=1 WHERE pool_id=? AND code='g1'", [$apId]);
ok(($r4c['ok'] ?? false) === true && Jobs::byId($S4id)['note'] === 'gói tắt' && ($r4d['ok'] ?? null) === false && str_contains((string) ($r4d['error'] ?? ''), 'g1'),
    'gói của đơn bị tắt: sửa ghi chú vẫn được; đổi số lượng gói đã tắt thì báo rõ', [$r4c, $r4d]);
// máy có ví nhận đơn vừa được sửa gói → định giá theo gói MỚI; lệnh giao đơn chỉ ghi đè gói khi gói chưa bị sửa giữa chừng
$cl4 = http('POST', '/api/tool/claim', $TK, ['device' => 'Adm-W', 'pool' => 'admin-pool', 'wallet' => $walAW])['json'];
ok(($cl4['job']['ref'] ?? '') === 'ADM-S4' && ($cl4['job']['items'][0]['qty'] ?? 0) === 2 && (int) Jobs::byId($S4id)['cost'] === 200000
    && preg_match('/status=\'queued\'\$cond",/', (string) file_get_contents(dirname(__DIR__) . '/src/repo.php')) === 1,
    'máy có ví nhận đơn đã sửa: định giá theo số lượng mới (2 × 1.000 JPY); lệnh giao đơn kèm điều kiện «gói chưa đổi» (không đè bản admin vừa sửa)', $cl4['job']['items'] ?? null);
// đơn chờ đối soát (kể cả máy không ví) → không xoá được: shop còn chờ kết quả cuối
http('POST', "/api/tool/jobs/$S4/result", $TK, ['result' => 'review', 'message' => 'không chắc']);
Db::run("UPDATE jobs SET wallet_state='released' WHERE id=?", [$S4id]);       // giả như không còn tạm giữ tiền
$post("/admin/jobs/$S4id/delete", []);
ok(Jobs::byId($S4id) !== null, 'đơn chờ đối soát (dù không tạm giữ tiền) → không xoá được, phải chốt trước');
$dash = http('GET', '/admin', null, null, $ah)['text'];
ok($dash !== '', 'trang tổng quan vẫn hiển thị khi có khoá «Đơn thử»');

// ---- sửa pool: gõ thêm loại tiền là có ô giá ngay → lưu MỘT lần thì giá của loại tiền mới cũng được lưu ----
$cpId = Pools::save(null, 'pool-cur', 'Pool loại tiền', 'Game', true, array_merge($wc, ['currencies' => ['JPY']]));
Pools::savePackages($cpId, [['code' => 'k1', 'name' => 'Gói 1', 'limit_type' => 'multi', 'active' => true, 'prices' => ['JPY' => ['amount' => '1500', 'display' => '¥1,500']]]]);
$pe = http('GET', "/admin/pools/$cpId", null, null, $ah)['text'];
ok(str_contains($pe, 'data-cur-sync') && str_contains($pe, 'class="pp-cur" data-cur="JPY"') && str_contains($pe, 'name="pk_currencies" value="JPY"'),
    'trang sửa pool: ô loại tiền điều khiển ô giá từng gói (mỗi loại tiền một cặp giá + chữ trên máy)');
$k1 = (int) Db::val("SELECT id FROM packages WHERE pool_id=? AND code='k1'", [$cpId]);
$post('/admin/pools/save', ['id' => $cpId, 'code' => 'pool-cur', 'name' => 'Pool loại tiền', 'game' => 'Game', 'active' => '1', 'queue_ttl_min' => '30', 'silent_min' => '15',
    'currencies' => 'JPY, USD', 'pk_currencies' => 'JPY,USD',
    'pk_id' => [$k1], 'pk_code' => ['k1'], 'pk_name' => ['Gói 1'], 'pk_ocr' => [''], 'pk_price' => [''], 'pk_limit' => ['multi'], 'pk_max' => ['0'], 'pk_active' => ['1'],
    'pp_JPY_amount' => ['1500'], 'pp_JPY_display' => ['¥1,500'], 'pp_USD_amount' => ['9.99'], 'pp_USD_display' => ['$9.99']]);
$pr2 = Pools::prices($cpId)[$k1] ?? [];
ok(Pools::find($cpId)['cfg']['currencies'] === ['JPY', 'USD'] && ($pr2['USD'] ?? null) === ['amount' => '9.99', 'display' => '$9.99'] && ($pr2['JPY']['amount'] ?? '') === '1500',
    'thêm loại tiền USD + nhập giá USD rồi lưu MỘT lần → lưu cả loại tiền lẫn giá (không phải lưu hai lần)', $pr2);

echo "\n== Dữ liệu mặc định (seed): xuất cấu hình → cài máy mới bằng setup.php là có sẵn ==\n";
$seed = Seed::export();
$sp = array_column($seed['pools'], null, 'code');
$sjs = json_encode($seed, JSON_UNESCAPED_UNICODE);
ok(($seed['seed'] ?? 0) === 1 && isset($sp['wallet-pool']) && count($sp['wallet-pool']['packages']) >= 4 && ($sp['wallet-pool']['config']['currencies'] ?? null) === ['JPY', 'CHF']
    && !str_contains($sjs, 'key_hash') && !str_contains($sjs, 'password_hash') && !str_contains($sjs, 'login_enc') && !str_contains($sjs, 'khach@example.com'),
    'xuất seed: pool + gói + giá theo loại tiền; KHÔNG có admin, khoá API, đơn / thông tin khách', array_keys($sp));
$seedKeys = [];
foreach ($seed['pools'] as $spool) {
    $seedKeys = array_merge($seedKeys, array_keys($spool));
    foreach ($spool['packages'] as $spk) {
        $seedKeys = array_merge($seedKeys, array_map(static fn ($k) => "pk.$k", array_keys($spk)));
    }
}
$seedKeys = array_values(array_unique($seedKeys));
sort($seedKeys);
ok($seedKeys === ['active', 'code', 'config', 'game', 'name', 'packages', 'pk.active', 'pk.code', 'pk.limit_type', 'pk.max_qty', 'pk.name', 'pk.ocr_text', 'pk.price_text', 'pk.prices']
    && array_keys($seed) === ['seed', 'exported_at', 'pools'], 'seed chỉ gồm ĐÚNG các khoá cấu hình pool / gói (không ví, tài khoản Apple, máy, đơn, khoá)', $seedKeys);
Db::insert('package_prices', ['package_id' => $pid['nodisp'], 'currency' => 'JPY', 'amount' => 100000, 'display' => '']);      // giá cũ thiếu chữ giá
$seedSk = Seed::export($skipped);
$nd = array_column(array_column($seedSk['pools'], null, 'code')['wallet-pool']['packages'], null, 'code')['nodisp'];
ok($skipped === ['wallet-pool/nodisp/JPY'] && (array) $nd['prices'] === [], 'giá cũ thiếu «chữ giá hiện trên máy» KHÔNG xuất vào seed (máy mới sẽ từ chối cả tệp) và được nêu tên', $skipped);
Db::run("DELETE FROM package_prices WHERE package_id=? AND currency='JPY'", [$pid['nodisp']]);
$sf = "$tmp/seed.json";
file_put_contents($sf, json_encode($seed, JSON_UNESCAPED_UNICODE));
$fresh = "$tmp/fresh.sqlite";
$envFresh = array_merge(getenv(), $env, ['DB_DSN' => "sqlite:$fresh", 'SEED_FILE' => $sf]);
unset($envFresh['DB_USER'], $envFresh['DB_PASS']);
$runSetup = static function (array $over = []) use ($envFresh, $root): array {
    $pr = proc_open([PHP_BINARY, "$root/bin/setup.php"], [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pp, $root, array_merge($envFresh, $over));
    $o = stream_get_contents($pp[1]) . stream_get_contents($pp[2]);
    return [proc_close($pr), $o];
};
// các tệp seed hỏng trên một CSDL trống KHÁC: báo lỗi rõ, không để lại pool dở, không khoá lần nạp sau
$fresh2 = "$tmp/fresh2.sqlite";
$e2 = ['DB_DSN' => "sqlite:$fresh2"];
$pools2 = static fn (): int => is_file($fresh2) ? (int) (new PDO("sqlite:$fresh2"))->query('SELECT COUNT(*) FROM pools')->fetchColumn() : -1;
[$rcM, $oM] = $runSetup($e2 + ['SEED_FILE' => "$tmp/khong-co.json"]);
file_put_contents("$tmp/seed-hong.json", '{oops');
[$rcJ, $oJ] = $runSetup($e2 + ['SEED_FILE' => "$tmp/seed-hong.json"]);
ok($rcM === 1 && str_contains($oM, 'không có tệp') && $rcJ === 1 && str_contains($oJ, 'không phải JSON') && $pools2() === 0,
    'SEED_FILE trỏ tới tệp không có / tệp không phải JSON → setup dừng với lỗi rõ (không coi như cài xong), không tạo pool', [$rcM, $rcJ]);
file_put_contents("$tmp/seed-rong.json", json_encode(['seed' => 1, 'pools' => []]));
[$rcE, $oE] = $runSetup($e2 + ['SEED_FILE' => "$tmp/seed-rong.json"]);
$half = $seed;
$half['pools'][] = ['code' => 'pool-hong', 'name' => 'Hỏng', 'game' => 'x', 'active' => true, 'config' => $half['pools'][0]['config'],
                    'packages' => [['code' => 'a', 'name' => 'A', 'limit_type' => 'multi', 'active' => true], ['code' => 'a', 'name' => 'trùng mã', 'limit_type' => 'multi', 'active' => true]]];
file_put_contents("$tmp/seed-do.json", json_encode($half, JSON_UNESCAPED_UNICODE));
[$rcH, $oH] = $runSetup($e2 + ['SEED_FILE' => "$tmp/seed-do.json"]);
$poolsAfterHalf = $pools2();
[$rcG, $oG] = $runSetup($e2);
ok($rcE === 0 && str_contains($oE, 'không có pool nào') && $rcH === 1 && str_contains($oH, 'pool-hong') && $poolsAfterHalf === 0
    && $rcG === 0 && str_contains($oG, 'Đã nạp dữ liệu mặc định') && $pools2() === count($seed['pools']),
    'seed rỗng → bỏ qua mà KHÔNG khoá lần nạp sau; seed hỏng ở pool thứ N → không để lại pool nào (một giao dịch); sau đó seed đúng vẫn nạp được', [$rcE, $rcH, $poolsAfterHalf, $rcG, mb_substr($oH, -120)]);
[$rc1, $o1] = $runSetup();
$fdb = new PDO("sqlite:$fresh");
$cnt = static fn (string $t): int => (int) $fdb->query("SELECT COUNT(*) FROM $t")->fetchColumn();
$wp = $fdb->query("SELECT id, config FROM pools WHERE code='wallet-pool'")->fetch(PDO::FETCH_ASSOC);
$gem = $wp ? $fdb->query("SELECT pp.amount, pp.display FROM package_prices pp JOIN packages k ON k.id=pp.package_id WHERE k.pool_id={$wp['id']} AND k.code='gem_s' AND pp.currency='JPY'")->fetch(PDO::FETCH_ASSOC) : null;
ok($rc1 === 0 && str_contains($o1, 'Đã nạp dữ liệu mặc định') && $cnt('pools') === count($seed['pools']) && $cnt('admins') === 1 && $cnt('api_keys') === 0 && $cnt('jobs') === 0
    && $gem && (int) $gem['amount'] === 200000 && $gem['display'] === '¥2,000' && json_decode($wp['config'], true)['currencies'] === ['JPY', 'CHF'],
    'máy mới: php bin/setup.php → tạo bảng + admin, tự nạp seed (pool, gói, giá, loại tiền); không có khoá / đơn cũ', [$rc1, mb_substr($o1, -160)]);
[$rc2, $o2] = $runSetup();
ok($rc2 === 0 && str_contains($o2, 'bỏ qua') && $cnt('pools') === count($seed['pools']), 'chạy setup lần nữa → không nạp lại (không ghi đè cấu hình đang dùng)', mb_substr($o2, -120));
$fdb->exec('DELETE FROM package_prices'); $fdb->exec('DELETE FROM packages'); $fdb->exec('DELETE FROM pools');
[$rc3, $o3] = $runSetup();
ok($rc3 === 0 && str_contains($o3, 'đã nạp từ trước') && $cnt('pools') === 0, 'admin xoá hết pool rồi chạy setup (cập nhật) → dữ liệu mặc định KHÔNG tự sinh lại', mb_substr($o3, -120));

echo "\n== Trang quản trị + tài liệu ==\n";
$docs = http('GET', '/docs');
ok(str_contains($docs['text'], '/api/tool/sync') && str_contains($docs['text'], 'need_scripts'), 'tài liệu có API /api/tool/sync');
ok($docs['code'] === 200 && str_contains($docs['text'], '/api/tool/claim'), 'trang /docs hiển thị');
ok(str_contains($docs['text'], 'job.cancelled') && str_contains($docs['text'], 'attempt') && str_contains($docs['text'], 'logged_out') && str_contains($docs['text'], 'resumed'),
    'tài liệu có đủ: webhook job.cancelled, tham số attempt, luật logged_out, cách xử lý đơn resumed');
ok(str_contains($docs['text'], 'wallet_short') && str_contains($docs['text'], 'already_bought') && str_contains($docs['text'], 'package_codes') && str_contains($docs['text'], 'wallet_events') && str_contains($docs['text'], 'wallet_acks') && str_contains($docs['text'], 'd_balance'),
    'tài liệu có phần ví do tool quản lý: wallet gửi kèm khi xin đơn, wallet_short, wallet_events / wallet_acks khi đồng bộ, lỗi 422 already_bought');
ok(http('GET', '/admin')['code'] === 302, '/admin chưa đăng nhập → chuyển về trang đăng nhập');
ok(http('GET', '/admin/login')['code'] === 200, 'trang đăng nhập hiển thị');
$lp = http('GET', '/admin/login')['text'];
ok(preg_match('#/assets/app\.css\?v=[1-9]\d*"#', $lp) === 1 && preg_match('#/assets/theme\.js\?v=[1-9]\d*"#', $lp) === 1,
    'đường dẫn CSS / JS kèm số phiên bản (sửa giao diện xong trình duyệt tự tải bản mới, không dùng bản cũ trong bộ nhớ đệm)');

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
