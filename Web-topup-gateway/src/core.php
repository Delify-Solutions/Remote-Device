<?php
declare(strict_types=1);

/**
 * core.php — lõi nhỏ gọn của Topup Gateway (PHP thuần, không framework):
 * Env · Db · Crypto · Req/Res · view() · Auth/Csrf/Flash · RateLimit · Storage.
 */

/* ====================== Env ====================== */
final class Env
{
    private static array $vals = [];

    public static function load(string $file): void
    {
        if (!is_file($file)) {
            return;
        }
        foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
            $line = trim($line);
            if ($line === '' || $line[0] === '#' || !str_contains($line, '=')) {
                continue;
            }
            [$k, $v] = explode('=', $line, 2);
            $k = trim($k);
            $v = trim($v);
            if (strlen($v) >= 2 && ($v[0] === '"' || $v[0] === "'") && substr($v, -1) === $v[0]) {
                $v = substr($v, 1, -1);
            }
            self::$vals[$k] = $v;
        }
    }

    public static function get(string $key, ?string $default = null): ?string
    {
        $e = getenv($key);
        if ($e !== false && $e !== '') {
            return $e;
        }
        return self::$vals[$key] ?? $default;
    }

    public static function bool(string $key, bool $default = false): bool
    {
        $v = self::get($key);
        if ($v === null) {
            return $default;
        }
        return in_array(strtolower($v), ['1', 'true', 'yes', 'on'], true);
    }
}

/* ====================== Db ====================== */
final class Db
{
    private static ?PDO $pdo = null;

    public static function pdo(): PDO
    {
        if (self::$pdo !== null) {
            return self::$pdo;
        }
        $dsn = Env::get('DB_DSN', 'sqlite:' . BASE . '/storage/gateway.sqlite');
        $opts = [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ];
        if (str_starts_with($dsn, 'mysql:')) {
            // rowCount() = số dòng KHỚP (không phải số dòng đổi) → các UPDATE có điều kiện đáng tin.
            $opts[PDO::MYSQL_ATTR_FOUND_ROWS] = true;
        }
        $pdo = new PDO($dsn, Env::get('DB_USER'), Env::get('DB_PASS'), $opts);
        if (str_starts_with($dsn, 'sqlite:')) {
            $pdo->exec('PRAGMA journal_mode=WAL');
            $pdo->exec('PRAGMA busy_timeout=5000');
        } else {
            $pdo->exec('SET NAMES utf8mb4');
        }
        return self::$pdo = $pdo;
    }

    public static function driver(): string
    {
        return self::pdo()->getAttribute(PDO::ATTR_DRIVER_NAME);
    }

    public static function run(string $sql, array $params = []): PDOStatement
    {
        $st = self::pdo()->prepare($sql);
        $st->execute(array_values($params));
        return $st;
    }

    public static function one(string $sql, array $params = []): ?array
    {
        $row = self::run($sql, $params)->fetch();
        return $row === false ? null : $row;
    }

    public static function all(string $sql, array $params = []): array
    {
        return self::run($sql, $params)->fetchAll();
    }

    public static function val(string $sql, array $params = []): mixed
    {
        $v = self::run($sql, $params)->fetchColumn();
        return $v === false ? null : $v;
    }

    public static function insert(string $table, array $data): int
    {
        $cols = array_keys($data);
        $sql = 'INSERT INTO ' . $table . ' (' . implode(',', $cols) . ') VALUES (' . implode(',', array_fill(0, count($cols), '?')) . ')';
        self::run($sql, array_values($data));
        return (int) self::pdo()->lastInsertId();
    }

    public static function update(string $table, array $data, string $where, array $params = []): int
    {
        $set = implode(',', array_map(static fn ($c) => $c . '=?', array_keys($data)));
        return self::run('UPDATE ' . $table . ' SET ' . $set . ' WHERE ' . $where, array_merge(array_values($data), $params))->rowCount();
    }

    public static function isDuplicate(Throwable $e): bool
    {
        return $e instanceof PDOException && (string) $e->getCode() === '23000';
    }
}

/* ====================== tiện ích ====================== */
function jenc(mixed $v): string
{
    return json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
}

function jdec(?string $s): array
{
    if ($s === null || $s === '') {
        return [];
    }
    $d = json_decode($s, true);
    return is_array($d) ? $d : [];
}

function e(mixed $s): string
{
    return htmlspecialchars((string) ($s ?? ''), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function iso(?int $ts): ?string
{
    return $ts ? gmdate('Y-m-d\TH:i:s\Z', $ts) : null;
}

/** Giờ hiển thị trong admin (múi giờ APP_TZ, mặc định Việt Nam). */
function vntime(?int $ts, string $fmt = 'd/m H:i:s'): string
{
    if (!$ts) {
        return '—';
    }
    $d = new DateTime('@' . $ts);
    $d->setTimezone(new DateTimeZone(Env::get('APP_TZ', 'Asia/Ho_Chi_Minh')));
    return $d->format($fmt);
}

function ago(?int $ts): string
{
    if (!$ts) {
        return 'chưa từng';
    }
    $s = time() - $ts;
    if ($s < 60) {
        return $s . ' giây trước';
    }
    if ($s < 3600) {
        return intdiv($s, 60) . ' phút trước';
    }
    if ($s < 86400) {
        return intdiv($s, 3600) . ' giờ trước';
    }
    return intdiv($s, 86400) . ' ngày trước';
}

/** Cắt chuỗi, bỏ ký tự điều khiển (trừ xuống dòng khi $multiline). */
function clean(mixed $v, int $max = 500, bool $multiline = false): string
{
    if (!is_scalar($v)) {
        return '';
    }
    $s = (string) $v;
    $s = preg_replace($multiline ? '/[^\P{C}\n\t]+/u' : '/\p{C}+/u', '', $s) ?? '';
    return mb_substr(trim($s), 0, $max);
}

function app_url(string $path = ''): string
{
    $base = rtrim((string) Env::get('APP_URL', ''), '/');
    if ($base === '') {
        $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https';
        $base = ($https ? 'https' : 'http') . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost');
    }
    return $base . $path;
}

/* ====================== Crypto ====================== */
final class Crypto
{
    private static function key(): string
    {
        $k = (string) Env::get('APP_KEY', '');
        if (strlen($k) < 16) {
            throw new RuntimeException('APP_KEY chưa đặt hoặc quá ngắn (cần >= 16 ký tự) trong .env');
        }
        return sodium_crypto_generichash($k, '', SODIUM_CRYPTO_SECRETBOX_KEYBYTES);
    }

    public static function enc(string $plain): string
    {
        $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        return base64_encode($nonce . sodium_crypto_secretbox($plain, $nonce, self::key()));
    }

    public static function dec(?string $b64): ?string
    {
        if ($b64 === null || $b64 === '') {
            return null;
        }
        $raw = base64_decode($b64, true);
        if ($raw === false || strlen($raw) <= SODIUM_CRYPTO_SECRETBOX_NONCEBYTES) {
            return null;
        }
        $plain = sodium_crypto_secretbox_open(
            substr($raw, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES),
            substr($raw, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES),
            self::key()
        );
        return $plain === false ? null : $plain;
    }

    public static function token(int $bytes = 16): string
    {
        return bin2hex(random_bytes($bytes));
    }
}

/* ====================== Req / Res ====================== */
final class Req
{
    private static ?string $raw = null;

    public static function method(): string
    {
        return strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
    }

    public static function path(): string
    {
        $p = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
        $p = '/' . trim($p, '/');
        return $p;
    }

    public static function raw(): string
    {
        return self::$raw ??= (string) file_get_contents('php://input');
    }

    public static function json(): array
    {
        $d = json_decode(self::raw(), true);
        return is_array($d) ? $d : [];
    }

    public static function bearer(): string
    {
        $h = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
        if ($h === '' && function_exists('apache_request_headers')) {
            foreach (apache_request_headers() ?: [] as $k => $v) {
                if (strtolower((string) $k) === 'authorization') {
                    $h = (string) $v;
                }
            }
        }
        return stripos($h, 'Bearer ') === 0 ? trim(substr($h, 7)) : '';
    }

    /**
     * IP của bên gọi (dùng cho giới hạn tần suất). Với TRUST_PROXY=true lấy địa chỉ CUỐI CÙNG trong
     * X-Forwarded-For — đó là địa chỉ do chính proxy của ta ghi thêm vào. Các phần đứng trước là do
     * bên gọi tự khai, tin chúng thì kẻ dò mật khẩu chỉ cần đổi header mỗi lần là qua mặt được giới hạn.
     */
    public static function ip(): string
    {
        $remote = (string) ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
        if (Env::bool('TRUST_PROXY') && !empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
            $hops = array_map('trim', explode(',', (string) $_SERVER['HTTP_X_FORWARDED_FOR']));
            $last = (string) end($hops);
            if (filter_var($last, FILTER_VALIDATE_IP) !== false) {
                return $last;
            }
        }
        return $remote;
    }

    public static function q(string $k, ?string $d = null): ?string
    {
        return isset($_GET[$k]) && is_scalar($_GET[$k]) ? (string) $_GET[$k] : $d;
    }

    public static function post(string $k, ?string $d = null): ?string
    {
        return isset($_POST[$k]) && is_scalar($_POST[$k]) ? (string) $_POST[$k] : $d;
    }

    /** Mảng cột của form lặp (vd lf_key[]). */
    public static function postArr(string $k): array
    {
        return isset($_POST[$k]) && is_array($_POST[$k]) ? array_values($_POST[$k]) : [];
    }
}

final class Res
{
    public static function json(array $data, int $code = 200): never
    {
        $body = jenc($data);
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        // Content-Length cho phép bên gọi coi phản hồi là XONG ngay khi nhận đủ byte, kể cả khi máy chủ
        // còn làm việc nền sau đó (gửi webhook) — xem Webhooks::kick().
        if (!headers_sent() && !ini_get('zlib.output_compression')) {
            header('Content-Length: ' . strlen($body));
        }
        echo $body;
        exit;
    }

    public static function err(int $code, string $error, string $message = '', array $extra = []): never
    {
        self::json(array_merge(['ok' => false, 'error' => $error, 'message' => $message], $extra), $code);
    }

    public static function redirect(string $to): never
    {
        header('Location: ' . $to, true, 302);
        exit;
    }

    public static function notFound(): never
    {
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        echo '404 Not Found';
        exit;
    }
}

/* ====================== View ====================== */
function view(string $name, array $vars = [], ?string $layout = 'layout'): never
{
    extract($vars, EXTR_SKIP);
    ob_start();
    require BASE . '/views/' . $name . '.php';
    $content = ob_get_clean();
    header('Content-Type: text/html; charset=utf-8');
    header('X-Frame-Options: DENY');
    header('X-Content-Type-Options: nosniff');
    header('Referrer-Policy: same-origin');
    if ($layout === null) {
        echo $content;
    } else {
        require BASE . '/views/' . $layout . '.php';
    }
    exit;
}

/* ====================== Auth (admin) ====================== */
final class Auth
{
    public static function start(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            return;
        }
        $secure = str_starts_with(app_url(), 'https://');
        session_name('gwsess');
        session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax', 'secure' => $secure]);
        session_start();
    }

    public static function user(): ?array
    {
        self::start();
        $id = (int) ($_SESSION['admin_id'] ?? 0);
        if ($id <= 0) {
            return null;
        }
        return Db::one('SELECT id, username, last_login_at FROM admins WHERE id=?', [$id]);
    }

    public static function attempt(string $username, string $password): bool
    {
        self::start();
        $row = Db::one('SELECT * FROM admins WHERE username=?', [$username]);
        // luôn chạy password_verify để thời gian trả lời không lộ username có tồn tại hay không
        $hash = $row['password_hash'] ?? password_hash(Crypto::token(8), PASSWORD_DEFAULT);
        $ok = password_verify($password, $hash);
        if (!$row || !$ok) {
            return false;
        }
        session_regenerate_id(true);
        $_SESSION['admin_id'] = (int) $row['id'];
        $_SESSION['csrf'] = Crypto::token(16);
        Db::run('UPDATE admins SET last_login_at=? WHERE id=?', [time(), $row['id']]);
        return true;
    }

    public static function logout(): void
    {
        self::start();
        $_SESSION = [];
        session_destroy();
    }

    public static function require(): array
    {
        $u = self::user();
        if (!$u) {
            Res::redirect('/admin/login');
        }
        return $u;
    }
}

final class Csrf
{
    public static function token(): string
    {
        Auth::start();
        return $_SESSION['csrf'] ??= Crypto::token(16);
    }

    public static function field(): string
    {
        return '<input type="hidden" name="_csrf" value="' . e(self::token()) . '">';
    }

    public static function verify(): void
    {
        Auth::start();
        $sent = (string) ($_POST['_csrf'] ?? '');
        if ($sent === '' || !hash_equals((string) ($_SESSION['csrf'] ?? ''), $sent)) {
            http_response_code(419);
            echo 'Phiên đã hết hạn (CSRF). Quay lại và thử lại.';
            exit;
        }
    }
}

final class Flash
{
    public static function set(string $msg, string $kind = 'ok'): void
    {
        Auth::start();
        $_SESSION['flash'][] = ['msg' => $msg, 'kind' => $kind];
    }

    /** Dữ liệu chỉ hiện MỘT lần (vd khoá API vừa tạo). */
    public static function once(string $key, mixed $value = null): mixed
    {
        Auth::start();
        if ($value !== null) {
            $_SESSION['once'][$key] = $value;
            return $value;
        }
        $v = $_SESSION['once'][$key] ?? null;
        unset($_SESSION['once'][$key]);
        return $v;
    }

    public static function pull(): array
    {
        Auth::start();
        $f = $_SESSION['flash'] ?? [];
        unset($_SESSION['flash']);
        return $f;
    }
}

/* ====================== RateLimit ====================== */
final class RateLimit
{
    /** Tên thùng luôn ≤ 120 ký tự (cột bucket): phần dài (tên đăng nhập, IP lạ…) được băm. */
    private static function key(string $bucket): string
    {
        if (strlen($bucket) <= 120 && preg_match('/^[\x20-\x7E]*$/', $bucket) === 1) {
            return $bucket;
        }
        // dài quá, hoặc có ký tự ngoài ASCII (cắt giữa một ký tự nhiều byte thì MySQL từ chối) → băm cả tên
        $head = preg_replace('/[^\x21-\x7E]/', '', substr($bucket, 0, 40));
        return $head . ':' . hash('sha256', $bucket);
    }

    public static function count(string $bucket, int $window): int
    {
        return (int) Db::val('SELECT COUNT(*) FROM rate_hits WHERE bucket=? AND at>?', [self::key($bucket), time() - $window]);
    }

    public static function hit(string $bucket): void
    {
        Db::insert('rate_hits', ['bucket' => self::key($bucket), 'at' => time()]);
        if (random_int(1, 50) === 1) {
            Db::run('DELETE FROM rate_hits WHERE at<?', [time() - 86400]);
        }
    }

    public static function clear(string $bucket): void
    {
        Db::run('DELETE FROM rate_hits WHERE bucket=?', [self::key($bucket)]);
    }
}

/* ====================== Storage (ảnh kết quả) ====================== */
final class Storage
{
    public const MAX_IMAGE = 5 * 1024 * 1024;

    public static function dir(): string
    {
        $d = rtrim((string) Env::get('STORAGE_DIR', BASE . '/storage/files'), '/');
        if (!is_dir($d)) {
            @mkdir($d, 0775, true);
        }
        return $d;
    }

    /** Kiểm ảnh theo NỘI DUNG (không tin Content-Type) rồi lưu với tên ngẫu nhiên 128 bit. */
    public static function saveImage(string $bytes): array
    {
        if ($bytes === '' || strlen($bytes) > self::MAX_IMAGE) {
            throw new InvalidArgumentException('Ảnh rỗng hoặc quá ' . (self::MAX_IMAGE / 1048576) . ' MB', 413);
        }
        $info = @getimagesizefromstring($bytes);
        $ext = match ($info[2] ?? 0) {
            IMAGETYPE_PNG  => 'png',
            IMAGETYPE_JPEG => 'jpg',
            IMAGETYPE_WEBP => 'webp',
            default        => '',
        };
        if ($ext === '') {
            throw new InvalidArgumentException('Chỉ nhận ảnh PNG / JPEG / WEBP', 415);
        }
        $token = Crypto::token(16);
        $rel = gmdate('Y/m') . '/' . $token . '.' . $ext;
        $abs = self::dir() . '/' . $rel;
        if (!is_dir(dirname($abs))) {
            @mkdir(dirname($abs), 0775, true);
        }
        if (file_put_contents($abs, $bytes, LOCK_EX) === false) {
            throw new RuntimeException('Không ghi được file ảnh (kiểm quyền thư mục storage)');
        }
        return ['token' => $token, 'path' => $rel, 'mime' => (string) $info['mime'], 'size' => strlen($bytes), 'ext' => $ext];
    }

    public static function abs(string $rel): string
    {
        return self::dir() . '/' . ltrim($rel, '/');
    }

    public static function delete(string $rel): void
    {
        $p = self::abs($rel);
        if (is_file($p)) {
            @unlink($p);
        }
    }
}
