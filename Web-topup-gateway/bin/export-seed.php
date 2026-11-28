<?php
declare(strict_types=1);

/**
 * Xuất CẤU HÌNH gateway (pool + gói + giá theo loại tiền) ra tệp JSON để cài sang máy khác là có sẵn:
 *   php bin/export-seed.php [tệp-ra]        (mặc định: seed.json ở thư mục gateway)
 * Máy mới: đặt tệp ở <thư mục gateway>/seed.json rồi chạy php bin/setup.php — tự nạp khi CSDL chưa có pool nào.
 * Không có admin, khoá API, đơn, ảnh, ví (xem class Seed).
 */
require dirname(__DIR__) . '/src/bootstrap.php';

$out = $argv[1] ?? (dirname(__DIR__) . '/seed.json');
$data = Seed::export($skipped);
if (file_put_contents($out, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n") === false) {
    fwrite(STDERR, "✗ Không ghi được $out\n");
    exit(1);
}
$pk = array_sum(array_map(static fn ($p) => count($p['packages']), $data['pools']));
echo '✓ Đã xuất ' . count($data['pools']) . " pool, $pk gói → $out\n";
if ($skipped) {
    echo '  ! Bỏ qua ' . count($skipped) . ' giá thiếu «chữ giá hiện trên máy» (vào trang pool nhập đủ rồi xuất lại nếu cần): ' . implode(', ', $skipped) . "\n";
}
