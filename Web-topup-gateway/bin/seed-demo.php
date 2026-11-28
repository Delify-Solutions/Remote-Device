<?php
declare(strict_types=1);

/** Dữ liệu mẫu cho máy dev:  php bin/seed-demo.php  — tạo 1 pool eFootball mẫu để sửa lại theo game thật. */
require dirname(__DIR__) . '/src/bootstrap.php';

if (Pools::byCode('efootball-ios')) {
    echo "Pool mẫu «efootball-ios» đã có, bỏ qua.\n";
    exit;
}
$cfg = Pools::defaults();
$cfg['login_fields'] = [
    ['key' => 'username', 'label' => 'Email Konami ID', 'type' => 'text', 'required' => true, 'hint' => 'Email đăng nhập game'],
    ['key' => 'password', 'label' => 'Mật khẩu', 'type' => 'password', 'required' => true],
];
$cfg['otp'] = ['enabled' => true, 'timeout' => 300, 'max_requests' => 3, 'hint' => 'Mã xác minh gửi về email của tài khoản Konami ID.'];
$cfg['rules'] = [
    ['when' => 'logged_out', 'value' => 'Konami ID|Đăng nhập', 'note' => 'Chữ CHỈ có khi chưa ai đăng nhập (màn chào + form nhập tài khoản)'],
    ['when' => 'login_success', 'value' => 'Trang chủ', 'note' => 'Sửa theo chữ thật trên màn hình sau khi vào game'],
    ['when' => 'login_fail', 'value' => 'không chính xác', 'note' => 'Sai email / mật khẩu'],
    ['when' => 'need_otp', 'value' => 'mã xác minh', 'note' => ''],
    ['when' => 'otp_wrong', 'value' => 'Mã không hợp lệ', 'note' => ''],
    ['when' => 'purchase_success', 'value' => 'Mua thành công', 'note' => ''],
    ['when' => 'purchase_fail', 'value' => 'Thanh toán thất bại', 'note' => 'Game báo rõ là không trừ tiền'],
    ['when' => 'package_unavailable', 'value' => 'Đã mua', 'note' => 'Gói 1 lần đã mua từ trước'],
];
// Bước thao tác (đăng nhập, mua, đăng xuất…) soạn trong kịch bản nhận đơn của tool — pool chỉ có trường đăng nhập, luật và gói.
$id = Pools::save(null, 'efootball-ios', 'eFootball (iOS) — Konami ID', 'eFootball', true, $cfg);
Pools::savePackages((int) $id, [
    ['code' => 'coin_130', 'name' => '130 eFootball Coins', 'ocr_text' => '130', 'price_text' => '25.000', 'limit_type' => 'multi', 'max_qty' => 10, 'active' => true],
    ['code' => 'coin_1050', 'name' => '1050 eFootball Coins', 'ocr_text' => '1050|1,050', 'price_text' => '249.000', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true],
    ['code' => 'coin_2150', 'name' => '2150 eFootball Coins', 'ocr_text' => '2150|2,150', 'price_text' => '499.000', 'limit_type' => 'multi', 'max_qty' => 5, 'active' => true],
    ['code' => 'starter_pack', 'name' => 'Gói khởi đầu (1 lần)', 'ocr_text' => 'Starter|Khởi đầu', 'price_text' => '25.000', 'limit_type' => 'once', 'max_qty' => 0, 'active' => true],
]);
echo "✓ Đã tạo pool mẫu «efootball-ios» (4 gói). Sửa lại theo game thật ở /admin/pools.\n";
