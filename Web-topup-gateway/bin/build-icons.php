<?php
declare(strict_types=1);

/**
 * Dựng lại bộ icon RÚT GỌN cho trang quản trị:   php bin/build-icons.php
 *
 * Bộ icon Tabler đầy đủ của Vuexy nặng ~2.6 MB (gần 6000 icon). Trang quản trị chỉ dùng vài chục icon,
 * nên script này quét `views/` + `public/assets/app.js` tìm các class `tabler-…` đang dùng và chỉ chép
 * đúng những icon đó sang `public/assets/vuexy/vendor/fonts/iconify-icons.css`.
 * Chạy lại mỗi khi thêm một icon mới vào giao diện. Nguồn: bộ Vuexy đầy đủ của iPhone Farm Manager.
 */
$base = dirname(__DIR__);
$full = $argv[1] ?? dirname($base) . '/app/web/vuexy/assets/vendor/fonts/iconify-icons.css';
$out = $base . '/public/assets/vuexy/vendor/fonts/iconify-icons.css';
if (!is_file($full)) {
    fwrite(STDERR, "Không thấy bộ icon đầy đủ: $full\nTruyền đường dẫn tới iconify-icons.css của Vuexy làm tham số.\n");
    exit(1);
}
$used = ['tabler-eye' => 1, 'tabler-eye-off' => 1, 'tabler-x' => 1];     // Vuexy tự gắn bằng JS
$files = array_merge(glob($base . '/views/*.php') ?: [], [$base . '/public/assets/app.js', $base . '/src/admin.php']);
foreach ($files as $f) {
    if (preg_match_all('/\btabler-[a-z0-9]+(?:-[a-z0-9]+)*/', (string) file_get_contents($f), $m)) {
        foreach ($m[0] as $name) {
            $used[$name] = 1;
        }
    }
}
$css = (string) file_get_contents($full);
if (preg_match('/\.ti\s*\{[^}]*\}/', $css, $m) !== 1) {
    fwrite(STDERR, "Không tìm thấy lớp nền .ti trong $full\n");
    exit(1);
}
$parts = ["/* Bộ icon Tabler RÚT GỌN — sinh bởi bin/build-icons.php, đừng sửa tay. */\n" . $m[0]];
$missing = [];
ksort($used);
foreach (array_keys($used) as $name) {
    if (preg_match('/\.' . preg_quote($name, '/') . '\s*\{[^}]*\}/', $css, $r) === 1) {
        $parts[] = $r[0];
    } else {
        $missing[] = $name;
    }
}
file_put_contents($out, implode("\n\n", $parts) . "\n");
printf("✓ %d icon → %s (%.1f KB)\n", count($parts) - 1, substr($out, strlen($base) + 1), filesize($out) / 1024);
if ($missing) {
    fwrite(STDERR, '✗ Không có trong bộ Tabler: ' . implode(', ', $missing) . "\n");
    exit(1);
}
