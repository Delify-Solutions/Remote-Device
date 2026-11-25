<?php
declare(strict_types=1);

/**
 * Cài đặt / cập nhật:  php bin/setup.php [tên-admin] [mật-khẩu]
 *  - áp migration còn thiếu (an toàn khi chạy lại)
 *  - nếu CHƯA có admin nào: tạo admin (không đưa mật khẩu thì sinh ngẫu nhiên, hiện MỘT lần)
 *  - đã có admin + truyền tên + mật khẩu: đặt lại mật khẩu cho tài khoản đó
 */
require dirname(__DIR__) . '/src/bootstrap.php';

if (strlen((string) Env::get('APP_KEY', '')) < 16) {
    fwrite(STDERR, "✗ Chưa đặt APP_KEY trong .env (cần chuỗi ngẫu nhiên >= 16 ký tự).\n  Gợi ý: APP_KEY=" . bin2hex(random_bytes(24)) . "\n");
    exit(1);
}
$applied = Schema::migrate();
echo $applied ? '✓ Đã áp migration: ' . implode(', ', $applied) . "\n" : "✓ CSDL đã mới nhất.\n";

$name = $argv[1] ?? null;
$pass = $argv[2] ?? null;
$count = (int) Db::val('SELECT COUNT(*) FROM admins');
if ($count === 0 || ($name !== null && $pass !== null)) {
    $name = $name ?: 'admin';
    $generated = $pass === null;
    $pass = $pass ?? rtrim(strtr(base64_encode(random_bytes(12)), '+/', '-_'), '=');
    if (strlen($pass) < 10) {
        fwrite(STDERR, "✗ Mật khẩu cần >= 10 ký tự.\n");
        exit(1);
    }
    $hash = password_hash($pass, PASSWORD_DEFAULT);
    if (Db::one('SELECT id FROM admins WHERE username=?', [$name])) {
        Db::update('admins', ['password_hash' => $hash], 'username=?', [$name]);
        echo "✓ Đã đặt lại mật khẩu cho «{$name}».\n";
    } else {
        Db::insert('admins', ['username' => $name, 'password_hash' => $hash, 'created_at' => time()]);
        echo "✓ Đã tạo admin «{$name}».\n";
    }
    if ($generated) {
        echo "  Mật khẩu (chỉ hiện lần này): {$pass}\n  → đăng nhập ở /admin rồi đổi tại mục Tài khoản.\n";
    }
}
