<?php
declare(strict_types=1);

/**
 * schema.php — migration có đánh số, chạy được trên MySQL/MariaDB (prod) và SQLite (dev/test).
 * Mọi mốc thời gian lưu INT (UNIX giây, UTC). Áp bằng `php bin/setup.php`.
 */
final class Schema
{
    /** @return array<int, list<string>> phiên bản => danh sách câu lệnh */
    public static function migrations(string $driver): array
    {
        $sqlite = $driver === 'sqlite';
        $pk  = $sqlite ? 'INTEGER PRIMARY KEY AUTOINCREMENT' : 'BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY';
        $ref = $sqlite ? 'INTEGER' : 'BIGINT UNSIGNED';
        $txt = $sqlite ? 'TEXT' : 'MEDIUMTEXT';
        // COLLATE utf8mb4_bin: so khớp CHÍNH XÁC từng ký tự (phân biệt hoa/thường và dấu), giống SQLite.
        // Với collation *_ci mặc định, mã đơn «Ord-aB3x» và «ORD-Ab3X» bị coi là MỘT → đơn thứ hai đã thu
        // tiền không bao giờ được nạp; tên máy «May-1» và «Máy-1» cũng bị coi là một.
        $opt = $sqlite ? '' : ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin';
        $tables = ['admins', 'settings', 'rate_hits', 'api_keys', 'pools', 'packages', 'jobs', 'job_events', 'job_images', 'devices', 'webhooks'];

        return [
            1 => [
                "CREATE TABLE admins (
                    id $pk,
                    username VARCHAR(60) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at INT NOT NULL,
                    last_login_at INT NULL
                )$opt",
                "CREATE TABLE settings (k VARCHAR(80) NOT NULL PRIMARY KEY, v $txt NULL)$opt",
                "CREATE TABLE rate_hits (id $pk, bucket VARCHAR(120) NOT NULL, at INT NOT NULL)$opt",
                "CREATE INDEX rate_hits_bucket ON rate_hits (bucket, at)",

                // khoá API: kind = shop (website bán hàng) | tool (máy nạp)
                "CREATE TABLE api_keys (
                    id $pk,
                    kind VARCHAR(10) NOT NULL,
                    name VARCHAR(120) NOT NULL,
                    key_hash CHAR(64) NOT NULL UNIQUE,
                    key_prefix VARCHAR(20) NOT NULL,
                    webhook_url VARCHAR(500) NULL,
                    webhook_secret_enc TEXT NULL,
                    active INT NOT NULL DEFAULT 1,
                    last_seen_at INT NULL,
                    created_at INT NOT NULL
                )$opt",

                // pool = 1 loại việc nạp (game + cách đăng nhập + OTP + gói nạp); config là JSON
                "CREATE TABLE pools (
                    id $pk,
                    code VARCHAR(40) NOT NULL UNIQUE,
                    name VARCHAR(160) NOT NULL,
                    game VARCHAR(120) NOT NULL DEFAULT '',
                    active INT NOT NULL DEFAULT 1,
                    config $txt NULL,
                    created_at INT NOT NULL,
                    updated_at INT NOT NULL
                )$opt",
                "CREATE TABLE packages (
                    id $pk,
                    pool_id $ref NOT NULL,
                    code VARCHAR(60) NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    ocr_text VARCHAR(500) NOT NULL DEFAULT '',
                    price_text VARCHAR(80) NOT NULL DEFAULT '',
                    limit_type VARCHAR(12) NOT NULL DEFAULT 'multi',
                    max_qty INT NOT NULL DEFAULT 0,
                    sort INT NOT NULL DEFAULT 0,
                    active INT NOT NULL DEFAULT 1,
                    UNIQUE (pool_id, code)
                )$opt",

                // job = 1 đơn nạp. Một (shop_key_id, ref) chỉ tạo được MỘT job → chống nạp trùng.
                "CREATE TABLE jobs (
                    id $pk,
                    pid VARCHAR(24) NOT NULL UNIQUE,
                    pool_id $ref NOT NULL,
                    shop_key_id $ref NOT NULL,
                    ref VARCHAR(80) NOT NULL,
                    status VARCHAR(12) NOT NULL,
                    stage VARCHAR(40) NULL,
                    login_enc $txt NULL,
                    account_hint VARCHAR(120) NULL,
                    items $txt NULL,
                    note VARCHAR(500) NULL,
                    device VARCHAR(80) NULL,
                    tool_key_id $ref NULL,
                    otp_state VARCHAR(12) NOT NULL DEFAULT 'none',
                    otp_seq INT NOT NULL DEFAULT 0,
                    otp_enc TEXT NULL,
                    otp_deadline INT NULL,
                    otp_message VARCHAR(300) NULL,
                    message VARCHAR(500) NULL,
                    review_reason VARCHAR(20) NULL,
                    result $txt NULL,
                    created_at INT NOT NULL,
                    claimed_at INT NULL,
                    seen_at INT NULL,
                    finished_at INT NULL,
                    updated_at INT NOT NULL,
                    UNIQUE (shop_key_id, ref)
                )$opt",
                "CREATE INDEX jobs_queue ON jobs (pool_id, status, id)",
                "CREATE INDEX jobs_status_seen ON jobs (status, seen_at)",

                "CREATE TABLE job_events (
                    id $pk,
                    job_id $ref NOT NULL,
                    at INT NOT NULL,
                    actor VARCHAR(10) NOT NULL,
                    type VARCHAR(40) NOT NULL,
                    message VARCHAR(500) NULL
                )$opt",
                "CREATE INDEX job_events_job ON job_events (job_id, id)",

                "CREATE TABLE job_images (
                    id $pk,
                    job_id $ref NOT NULL,
                    seq INT NOT NULL,
                    kind VARCHAR(12) NOT NULL DEFAULT 'bill',
                    token CHAR(32) NOT NULL UNIQUE,
                    path VARCHAR(200) NOT NULL,
                    mime VARCHAR(40) NOT NULL,
                    size INT NOT NULL,
                    created_at INT NOT NULL,
                    UNIQUE (job_id, seq)
                )$opt",

                // máy (slot) do tool khai báo qua heartbeat/claim
                "CREATE TABLE devices (
                    id $pk,
                    tool_key_id $ref NOT NULL,
                    name VARCHAR(80) NOT NULL,
                    pool_code VARCHAR(40) NULL,
                    state VARCHAR(10) NOT NULL DEFAULT 'free',
                    job_pid VARCHAR(24) NULL,
                    last_seen_at INT NOT NULL,
                    UNIQUE (tool_key_id, name)
                )$opt",

                // hàng đợi webhook gửi về shop (có thử lại)
                "CREATE TABLE webhooks (
                    id $pk,
                    key_id $ref NOT NULL,
                    job_id $ref NOT NULL,
                    event VARCHAR(40) NOT NULL,
                    payload $txt NOT NULL,
                    attempts INT NOT NULL DEFAULT 0,
                    next_at INT NOT NULL,
                    status VARCHAR(10) NOT NULL DEFAULT 'pending',
                    last_error VARCHAR(300) NULL,
                    created_at INT NOT NULL
                )$opt",
                "CREATE INDEX webhooks_due ON webhooks (status, next_at)",
            ],
            // Bản cài MySQL/MariaDB tạo bằng migration 1 cũ (collation *_ci) → chuyển sang so khớp chính xác.
            // Bản cài mới (bảng đã là utf8mb4_bin) và SQLite: không đổi gì.
            2 => $sqlite ? [] : array_map(static fn (string $t): string => "ALTER TABLE $t CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_bin", $tables),

            // Tool TỰ BÁO qua POST /api/tool/sync: danh mục kịch bản (soạn ở tool) + máy nào đang rảnh ở kịch bản nào.
            // Gateway nằm ngoài mạng, tool nằm trong mạng nội bộ → chỉ tool gọi lên được; gateway chỉ nạp những gì tool gửi.
            3 => [
                "CREATE TABLE tool_scripts (
                    id $pk,
                    tool_key_id $ref NOT NULL,
                    uid VARCHAR(100) NOT NULL,
                    group_id VARCHAR(40) NOT NULL DEFAULT '',
                    group_name VARCHAR(160) NOT NULL DEFAULT '',
                    script_id VARCHAR(40) NOT NULL DEFAULT '',
                    name VARCHAR(160) NOT NULL,
                    run_mode VARCHAR(10) NOT NULL DEFAULT 'once',
                    loops INT NOT NULL DEFAULT 1,
                    step_count INT NOT NULL DEFAULT 0,
                    vars $txt NULL,
                    outline $txt NULL,
                    first_seen_at INT NOT NULL,
                    updated_at INT NOT NULL,
                    UNIQUE (tool_key_id, uid)
                )$opt",
                // devices.state / job_pid / pool_code vẫn do heartbeat + claim ghi (việc của ĐƠN). Các cột dưới đây do sync ghi (việc của MÁY).
                'ALTER TABLE devices ADD COLUMN label VARCHAR(120) NULL',
                'ALTER TABLE devices ADD COLUMN status VARCHAR(12) NULL',
                'ALTER TABLE devices ADD COLUMN status_note VARCHAR(200) NULL',
                "ALTER TABLE devices ADD COLUMN scripts $txt NULL",
                "ALTER TABLE devices ADD COLUMN running $txt NULL",
                'ALTER TABLE devices ADD COLUMN synced_at INT NULL',
                "ALTER TABLE api_keys ADD COLUMN tool_info $txt NULL",
            ],

            // Kịch bản NHẬN ĐƠN (soạn ở tool, cách chạy «orders»): tool khai nó phục vụ pool nào → gateway hiện «kịch bản nào phục vụ pool nào».
            4 => [
                'ALTER TABLE tool_scripts ADD COLUMN pool_code VARCHAR(40) NULL',
            ],
        ];
    }

    /** Phiên bản migration mới nhất mà mã này cần. */
    public const LATEST = 4;

    private static ?int $version = null;

    /** Phiên bản CSDL đang có (0 = chưa cài). Mã mới chạy trên CSDL cũ phải tự nhận ra thay vì lỗi SQL. */
    public static function version(): int
    {
        if (self::$version === null) {
            try {
                self::$version = (int) Db::val('SELECT MAX(version) FROM schema_version');
            } catch (Throwable) {
                self::$version = 0;
            }
        }
        return self::$version;
    }

    /** Áp các migration chưa chạy. Trả danh sách phiên bản vừa áp. */
    public static function migrate(): array
    {
        $driver = Db::driver();
        Db::pdo()->exec('CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL PRIMARY KEY, applied_at INT NOT NULL)');
        $done = array_map('intval', array_column(Db::all('SELECT version FROM schema_version'), 'version'));
        $applied = [];
        foreach (self::migrations($driver) as $version => $statements) {
            if (in_array($version, $done, true)) {
                continue;
            }
            // SQLite cho phép đặt cả lệnh tạo / sửa bảng trong giao dịch → một phiên bản áp TRỌN hoặc không áp gì (chạy dở vẫn chạy lại được).
            // MySQL / MariaDB tự chốt sau mỗi lệnh DDL nên không bọc được.
            $tx = $driver === 'sqlite';
            if ($tx) {
                Db::pdo()->beginTransaction();
            }
            try {
                foreach ($statements as $sql) {
                    Db::pdo()->exec($sql);
                }
                Db::insert('schema_version', ['version' => $version, 'applied_at' => time()]);
                if ($tx) {
                    Db::pdo()->commit();
                }
            } catch (Throwable $e) {
                if ($tx && Db::pdo()->inTransaction()) {
                    Db::pdo()->rollBack();
                }
                throw $e;
            }
            $applied[] = $version;
        }
        self::$version = null;
        return $applied;
    }

    public static function ready(): bool
    {
        try {
            return (int) Db::val('SELECT COUNT(*) FROM schema_version') > 0;
        } catch (Throwable) {
            return false;
        }
    }
}
