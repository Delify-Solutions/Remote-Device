<?php
declare(strict_types=1);

/**
 * Front controller của Topup Gateway.
 *   /admin/*        trang quản trị (đăng nhập bằng tài khoản admin)
 *   /docs           tài liệu API 2 chiều
 *   /api/shop/*     API cho website bán hàng   (Bearer gws_…)
 *   /api/tool/*     API cho máy nạp            (Bearer gwt_…)
 *   /files/{token}  ảnh kết quả (URL không đoán được)
 *   /cron/tick      dọn đơn quá hạn + gửi lại webhook (?key=CRON_KEY)
 */
if (PHP_SAPI === 'cli-server') {
    $f = __DIR__ . parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
    if (is_file($f)) {
        return false;       // php -S: để máy chủ tự trả file tĩnh
    }
}

require dirname(__DIR__) . '/src/bootstrap.php';

$m = Req::method();
$seg = array_values(array_filter(explode('/', Req::path()), static fn ($s) => $s !== ''));
$head = $seg[0] ?? '';

try {
    if ($head === '') {
        Res::redirect('/admin');
    }
    if ($head === 'healthz') {
        Res::json(['ok' => true, 'ready' => Schema::ready()]);
    }
    if ($head === 'api' && ($seg[1] ?? '') === 'shop') {
        Api::shop($m, array_slice($seg, 2));
    }
    if ($head === 'api' && ($seg[1] ?? '') === 'tool') {
        Api::tool($m, array_slice($seg, 2));
    }
    if ($head === 'api') {
        Res::err(404, 'not_found', 'Không có API này.');
    }
    if ($head === 'files' && count($seg) === 2 && $m === 'GET') {
        Api::file($seg[1]);
    }
    if ($head === 'cron' && ($seg[1] ?? '') === 'tick') {
        Api::cron();
    }
    if ($head === 'docs' && $m === 'GET') {
        Admin::docs();
    }
    if ($head === 'admin') {
        Admin::route($m, array_slice($seg, 1));
    }
    Res::notFound();
} catch (Throwable $e) {
    error_log('[gateway] ' . $e::class . ': ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine());
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo Env::bool('APP_DEBUG') ? "Lỗi: {$e->getMessage()}\n{$e->getFile()}:{$e->getLine()}" : 'Lỗi máy chủ.';
}
