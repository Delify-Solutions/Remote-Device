<?php
declare(strict_types=1);

/**
 * repo.php — nghiệp vụ: Settings · Pools (+ gói nạp) · Keys · Devices · Jobs · Webhooks.
 *
 * NGUYÊN TẮC TIỀN (giống hợp đồng tool của shop, đừng nới):
 *  1. Một đơn (shop_key, ref) chỉ tạo MỘT job; một job chỉ giao cho tool ĐÚNG MỘT LẦN.
 *  2. Gateway không bao giờ tự "nạp lại" hay tự hoàn tiền.
 *  3. Mọi nghi ngờ (tool im lặng, báo xong thiếu ảnh, tool không chắc) → `review` cho admin chốt.
 */

final class Settings
{
    public static function get(string $k, ?string $d = null): ?string
    {
        $v = Db::val('SELECT v FROM settings WHERE k=?', [$k]);
        return $v === null ? $d : (string) $v;
    }

    public static function set(string $k, string $v): void
    {
        if (Db::run('UPDATE settings SET v=? WHERE k=?', [$v, $k])->rowCount() === 0) {
            try {
                Db::insert('settings', ['k' => $k, 'v' => $v]);
            } catch (Throwable $e) {
                if (!Db::isDuplicate($e)) {
                    throw $e;
                }
            }
        }
    }
}

/* ====================== Pools ====================== */
final class Pools
{
    public const FIELD_TYPES = ['text' => 'Chữ', 'password' => 'Mật khẩu', 'textarea' => 'Nhiều dòng', 'select' => 'Danh sách chọn'];
    public const ALWAYS_SECRET = ['password', 'pass', 'pin', 'cookie', 'cookies', 'token', 'otp', 'backup_code', 'secret'];
    public const STEP_TYPES = [
        'launch'      => 'Mở app',
        'tap_text'    => 'Tap vào chữ',
        'tap'         => 'Tap toạ độ (x,y)',
        'type'        => 'Gõ chữ',
        'key'         => 'Phím',
        'combo'       => 'Tổ hợp phím',
        'home'        => 'Về màn hình chính',
        'wait'        => 'Chờ (giây)',
        'wait_text'   => 'Chờ tới khi thấy chữ',
        'assert_text' => 'Kiểm có chữ',
        'swipe'       => 'Vuốt (left / right / up / down)',
        'hold'        => 'Bấm giữ toạ độ (x,y)',
        'hold_text'   => 'Bấm giữ vào chữ',
    ];
    public const RULE_WHEN = [
        'logged_out'          => 'Màn hình CHƯA đăng nhập (màn chào / form đăng nhập)',
        'login_success'       => 'Đăng nhập THÀNH CÔNG',
        'login_fail'          => 'Đăng nhập THẤT BẠI',
        'need_otp'            => 'Game đòi OTP',
        'otp_wrong'           => 'OTP SAI / hết hạn',
        'purchase_success'    => 'Nạp gói THÀNH CÔNG',
        'purchase_fail'       => 'Nạp gói THẤT BẠI',
        'package_unavailable' => 'Gói KHÔNG mua được (đã mua / hết lượt)',
    ];
    public const LIMIT_TYPES = [
        'multi'   => 'Mua nhiều lần',
        'once'    => 'Chỉ 1 lần / tài khoản',
        'daily'   => '1 lần / ngày',
        'weekly'  => '1 lần / tuần',
        'monthly' => '1 lần / tháng',
    ];
    /** Sáu giai đoạn thao tác của một đơn, theo đúng thứ tự máy chạy. */
    public const STEP_LISTS = [
        'login_steps'          => 'Đăng nhập',
        'otp_steps'            => 'Nhập OTP',
        'nav_steps'            => 'Vào danh sách gói nạp',
        'purchase_steps'       => 'Mua 1 gói',
        'after_purchase_steps' => 'Sau mỗi lần mua',
        'finish_steps'         => 'Kết thúc đơn',
    ];
    /** Luật mà tool BẮT BUỘC phải có mới dám tự chạy đơn (thiếu thì máy không nhận đơn). */
    public const RULES_REQUIRED = [
        'logged_out'       => 'tool chỉ gõ tài khoản khi THẤY màn hình chưa đăng nhập — chống nạp nhầm vào tài khoản của khách trước',
        'login_success'    => 'để biết đã vào được game',
        'purchase_success' => 'chỉ tính là đã nạp khi thấy chữ này xuất hiện SAU khi bấm mua',
    ];
    public const STEP_HELP = [
        'login_steps'          => 'Mở game và nhập tài khoản. Ngay trước bước gõ {{biến}} đầu tiên (tài khoản của khách) máy kiểm phải thấy luật «Màn hình CHƯA đăng nhập». Chạy xong thì máy đọc màn hình theo mục 3 để biết đăng nhập được, sai mật khẩu hay game đòi OTP.',
        'otp_steps'            => 'Chạy mỗi lần có mã khách gửi sang. Để trống = gõ {{otp}} rồi nhấn Enter.',
        'nav_steps'            => 'Từ màn hình sau đăng nhập đi tới trang bán gói. Chạy 1 lần cho mỗi đơn. Cần vuốt / cuộn để thấy gói thì đặt bước vuốt ở ĐÂY (hoặc ở «Sau mỗi lần mua»), đừng đặt đầu «Các bước mua».',
        'purchase_steps'       => 'Lặp lại cho từng gói × số lượng. Trước mỗi lần mua máy kiểm màn hình KHÔNG còn chữ «nạp thành công» của lần trước; chạy xong thì đọc màn hình theo mục 3 để biết mua được hay chưa. Từ bước ĐẦU TIÊN có chạm vào máy trong danh sách này, mọi trục trặc đều được coi là «không chắc đã mua» → đơn chuyển đối soát.',
        'after_purchase_steps' => 'Chạy sau mỗi lần mua ĐÃ chụp ảnh bill: đóng hộp thoại, quay lại danh sách gói.',
        'finish_steps'         => 'Đăng xuất, về màn hình chính. Chạy trước khi máy nhận đơn kế tiếp (kể cả sau đơn lỗi) — để đơn sau không nạp nhầm tài khoản này. Đơn phải đối soát thì máy dừng và giữ nguyên màn hình; bấm chạy lại mới đăng xuất.',
    ];

    public static function defaults(): array
    {
        return [
            'login_fields' => [
                ['key' => 'username', 'label' => 'Tài khoản', 'type' => 'text', 'required' => true, 'secret' => false, 'hint' => '', 'options' => []],
                ['key' => 'password', 'label' => 'Mật khẩu', 'type' => 'password', 'required' => true, 'secret' => true, 'hint' => '', 'options' => []],
            ],
            'otp' => ['enabled' => true, 'timeout' => 300, 'max_requests' => 3, 'hint' => 'Mã xác thực gửi về email / số điện thoại của tài khoản game.'],
            'rules' => [],
        ] + array_fill_keys(array_keys(self::STEP_LISTS), []) + [
            'require_image' => true,
            'queue_ttl' => 1800,
            'silent_timeout' => 900,
        ];
    }

    private static function int(mixed $v, int $min, int $max, int $def): int
    {
        return is_numeric($v) ? max($min, min($max, (int) $v)) : $def;
    }

    /** Cờ bật/tắt đến từ form ('1' / '0') lẫn JSON (true / false). */
    private static function flag(mixed $v): bool
    {
        return is_bool($v) ? $v : (is_scalar($v) && in_array(strtolower(trim((string) $v)), ['1', 'true', 'yes', 'on'], true));
    }

    /** Chuẩn hoá cấu hình pool (dùng cả khi lưu lẫn khi đọc). */
    public static function sanitize(array $in): array
    {
        $def = self::defaults();
        $out = $def;

        $fields = [];
        $seen = [];
        foreach ((array) ($in['login_fields'] ?? $def['login_fields']) as $f) {
            if (!is_array($f)) {
                continue;
            }
            $key = strtolower(clean($f['key'] ?? '', 40));
            if (preg_match('/^[a-z][a-z0-9_]{0,39}$/', $key) !== 1 || isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $type = isset(self::FIELD_TYPES[$f['type'] ?? '']) ? (string) $f['type'] : 'text';
            $options = [];
            foreach ((array) ($f['options'] ?? []) as $o) {
                $o = clean($o, 80);
                if ($o !== '') {
                    $options[] = $o;
                }
            }
            $fields[] = [
                'key'      => $key,
                'label'    => clean($f['label'] ?? '', 80) ?: $key,
                'type'     => $type,
                'required' => !empty($f['required']),
                'secret'   => $type === 'password' || in_array($key, self::ALWAYS_SECRET, true) || !empty($f['secret']),
                'hint'     => clean($f['hint'] ?? '', 200),
                'options'  => $type === 'select' ? array_values(array_unique($options)) : [],
            ];
            if (count($fields) >= 12) {
                break;
            }
        }
        $out['login_fields'] = $fields;

        $otp = (array) ($in['otp'] ?? []);
        $out['otp'] = [
            'enabled'      => array_key_exists('enabled', $otp) ? !empty($otp['enabled']) : $def['otp']['enabled'],
            'timeout'      => self::int($otp['timeout'] ?? null, 30, 1800, $def['otp']['timeout']),
            'max_requests' => self::int($otp['max_requests'] ?? null, 1, 10, $def['otp']['max_requests']),
            'hint'         => array_key_exists('hint', $otp) ? clean($otp['hint'], 200) : $def['otp']['hint'],
        ];

        $rules = [];
        foreach ((array) ($in['rules'] ?? []) as $r) {
            if (!is_array($r) || !isset(self::RULE_WHEN[$r['when'] ?? ''])) {
                continue;
            }
            $value = clean($r['value'] ?? '', 200);
            if ($value === '') {
                continue;
            }
            $rules[] = ['when' => (string) $r['when'], 'value' => $value, 'note' => clean($r['note'] ?? '', 200)];
            if (count($rules) >= 60) {
                break;
            }
        }
        $out['rules'] = $rules;

        foreach (array_keys(self::STEP_LISTS) as $list) {
            $steps = [];
            foreach ((array) ($in[$list] ?? []) as $s) {
                if (!is_array($s) || !isset(self::STEP_TYPES[$s['type'] ?? ''])) {
                    continue;
                }
                // optional = «bỏ qua nếu lỗi»: bước không làm được thì máy đi tiếp (vd đóng một hộp thoại có thể không hiện)
                $steps[] = ['type' => (string) $s['type'], 'value' => clean($s['value'] ?? '', 300), 'note' => clean($s['note'] ?? '', 200),
                            'optional' => self::flag($s['optional'] ?? false)];
                if (count($steps) >= 80) {
                    break;
                }
            }
            $out[$list] = $steps;
        }

        $out['require_image']  = array_key_exists('require_image', $in) ? !empty($in['require_image']) : $def['require_image'];
        $out['queue_ttl']      = self::int($in['queue_ttl'] ?? null, 60, 86400, $def['queue_ttl']);
        $out['silent_timeout'] = self::int($in['silent_timeout'] ?? null, 60, 7200, $def['silent_timeout']);
        return $out;
    }

    private static function hydrate(?array $row): ?array
    {
        if ($row === null) {
            return null;
        }
        $row['cfg'] = self::sanitize(jdec($row['config'] ?? ''));
        return $row;
    }

    public static function all(): array
    {
        $rows = Db::all('SELECT * FROM pools ORDER BY id');
        foreach ($rows as &$r) {
            $r = self::hydrate($r);
            $r['packages'] = (int) Db::val('SELECT COUNT(*) FROM packages WHERE pool_id=? AND active=1', [$r['id']]);
            $r['queued']   = (int) Db::val("SELECT COUNT(*) FROM jobs WHERE pool_id=? AND status='queued'", [$r['id']]);
            $r['running']  = (int) Db::val("SELECT COUNT(*) FROM jobs WHERE pool_id=? AND status IN ('claimed','running','need_otp')", [$r['id']]);
        }
        return $rows;
    }

    public static function find(int $id): ?array
    {
        return self::hydrate(Db::one('SELECT * FROM pools WHERE id=?', [$id]));
    }

    public static function byCode(string $code): ?array
    {
        return self::hydrate(Db::one('SELECT * FROM pools WHERE code=?', [$code]));
    }

    /** @return int|string id khi thành công, chuỗi lỗi khi sai */
    public static function save(?int $id, string $code, string $name, string $game, bool $active, array $config): int|string
    {
        $code = strtolower(trim($code));
        if (preg_match('/^[a-z0-9][a-z0-9_-]{1,39}$/', $code) !== 1) {
            return 'Mã pool chỉ gồm chữ thường, số, gạch (2–40 ký tự).';
        }
        $name = clean($name, 160);
        if ($name === '') {
            return 'Chưa nhập tên pool.';
        }
        $data = [
            'code' => $code, 'name' => $name, 'game' => clean($game, 120), 'active' => $active ? 1 : 0,
            'config' => jenc(self::sanitize($config)), 'updated_at' => time(),
        ];
        try {
            if ($id) {
                Db::update('pools', $data, 'id=?', [$id]);
                return $id;
            }
            $data['created_at'] = time();
            return Db::insert('pools', $data);
        } catch (Throwable $e) {
            if (Db::isDuplicate($e)) {
                return 'Mã pool «' . $code . '» đã tồn tại.';
            }
            throw $e;
        }
    }

    public static function delete(int $id): bool
    {
        if ((int) Db::val('SELECT COUNT(*) FROM jobs WHERE pool_id=?', [$id]) > 0) {
            return false;   // đã có đơn → chỉ cho tạm dừng, không xoá (giữ lịch sử đối soát)
        }
        Db::run('DELETE FROM packages WHERE pool_id=?', [$id]);
        Db::run('DELETE FROM pools WHERE id=?', [$id]);
        return true;
    }

    public static function packages(int $poolId, bool $onlyActive = false): array
    {
        return Db::all('SELECT * FROM packages WHERE pool_id=?' . ($onlyActive ? ' AND active=1' : '') . ' ORDER BY sort, id', [$poolId]);
    }

    /** Lưu cả danh sách gói từ form (dòng có id → sửa; không id → thêm; id vắng mặt → xoá). */
    public static function savePackages(int $poolId, array $rows): ?string
    {
        $codes = [];
        $clean = [];
        $sort = 0;
        foreach ($rows as $r) {
            $code = clean($r['code'] ?? '', 60);
            $name = clean($r['name'] ?? '', 200);
            if ($code === '' && $name === '') {
                continue;
            }
            if (preg_match('/^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$/', $code) !== 1) {
                return 'Mã gói «' . $code . '» không hợp lệ (chữ/số/gạch/chấm, tối đa 60).';
            }
            if (isset($codes[$code])) {
                return 'Mã gói «' . $code . '» bị trùng.';
            }
            $codes[$code] = true;
            $clean[] = [(int) ($r['id'] ?? 0), [
                'code'       => $code,
                'name'       => $name ?: $code,
                'ocr_text'   => clean($r['ocr_text'] ?? '', 500),
                'price_text' => clean($r['price_text'] ?? '', 80),
                'limit_type' => isset(self::LIMIT_TYPES[$r['limit_type'] ?? '']) ? (string) $r['limit_type'] : 'multi',
                'max_qty'    => max(0, min(99, (int) ($r['max_qty'] ?? 0))),
                'active'     => !empty($r['active']) ? 1 : 0,
                'sort'       => $sort++,
            ]];
        }
        $existing = array_map('intval', array_column(Db::all('SELECT id FROM packages WHERE pool_id=?', [$poolId]), 'id'));
        $keep = array_values(array_intersect($existing, array_column($clean, 0)));
        $pdo = Db::pdo();
        $pdo->beginTransaction();
        try {
            // xoá dòng bị bỏ TRƯỚC khi thêm: «xoá gói X rồi thêm lại gói X» không được vướng khoá UNIQUE
            foreach (array_diff($existing, $keep) as $gone) {
                Db::run('DELETE FROM packages WHERE id=?', [$gone]);
            }
            foreach ($clean as [$id, $data]) {
                if ($id > 0 && in_array($id, $keep, true)) {
                    Db::update('packages', $data, 'id=?', [$id]);
                } else {
                    Db::insert('packages', $data + ['pool_id' => $poolId]);
                }
            }
            $pdo->commit();
        } catch (Throwable $e) {
            $pdo->rollBack();
            if (Db::isDuplicate($e)) {
                return 'Mã gói bị trùng với một gói khác của pool (đổi chéo mã giữa hai gói thì lưu từng bước).';
            }
            throw $e;
        }
        return null;
    }

    /**
     * Pool còn thiếu gì để máy nạp tự chạy được? Trả danh sách câu mô tả (rỗng = đủ).
     * Tool kiểm lại y như vậy trước khi nhận đơn (và tính cả bước ghi đè của nhóm máy).
     */
    public static function missing(array $pool): array
    {
        $cfg = $pool['cfg'];
        $out = [];
        $has = array_column($cfg['rules'], 'when');
        foreach (self::RULES_REQUIRED as $when => $why) {
            if (!in_array($when, $has, true)) {
                $out[] = 'Thiếu luật «' . self::RULE_WHEN[$when] . '» — ' . $why . '.';
            }
        }
        foreach (['login_steps' => 'đăng nhập', 'purchase_steps' => 'mua 1 gói', 'finish_steps' => 'kết thúc đơn (đăng xuất)'] as $list => $label) {
            if (!$cfg[$list]) {
                $out[] = 'Chưa có bước «' . $label . '».';
            }
        }
        if (isset($pool['id']) && (int) $pool['id'] > 0 && !self::packages((int) $pool['id'], true)) {
            $out[] = 'Chưa có gói nạp nào đang bán.';
        }
        return $out;
    }

    /** Danh sách gọn cho tool chọn pool (không kèm cấu hình). */
    public static function brief(): array
    {
        $out = [];
        foreach (self::all() as $p) {
            $out[] = ['code' => $p['code'], 'name' => $p['name'], 'game' => $p['game'], 'active' => (bool) $p['active'],
                      'packages' => $p['packages'], 'queued' => $p['queued']];
        }
        return $out;
    }

    /** Pool nhìn từ API. Shop chỉ cần trường đăng nhập + gói; tool cần thêm luật nhận diện + các bước. */
    public static function publicView(array $pool, bool $forTool): array
    {
        $cfg = $pool['cfg'];
        $pk = [];
        foreach (self::packages((int) $pool['id'], true) as $p) {
            $row = ['code' => $p['code'], 'name' => $p['name'], 'limit_type' => $p['limit_type'], 'max_qty' => (int) $p['max_qty']];
            if ($forTool) {
                $row['ocr_text'] = $p['ocr_text'];
                $row['price_text'] = $p['price_text'];
            }
            $pk[] = $row;
        }
        $out = [
            'code' => $pool['code'], 'name' => $pool['name'], 'game' => $pool['game'], 'active' => (bool) $pool['active'],
            'login_fields' => $cfg['login_fields'],
            'otp' => $cfg['otp'],
            'packages' => $pk,
        ];
        if ($forTool) {
            $out['rules'] = $cfg['rules'];
            foreach (array_keys(self::STEP_LISTS) as $list) {
                $out[$list] = $cfg[$list];
            }
            $out['require_image'] = $cfg['require_image'];
        }
        return $out;
    }
}

/* ====================== Keys ====================== */
final class Keys
{
    public const KINDS = ['shop' => 'Shop (website bán hàng)', 'tool' => 'Tool (máy nạp)'];

    private static function generate(string $kind): string
    {
        return ($kind === 'shop' ? 'gws_' : 'gwt_') . Crypto::token(24);
    }

    /** Tạo khoá. Khoá rõ chỉ trả về MỘT lần; DB chỉ lưu SHA-256. */
    public static function create(string $kind, string $name, string $webhookUrl = ''): array
    {
        if (!isset(self::KINDS[$kind])) {
            throw new InvalidArgumentException('kind');
        }
        $plain = self::generate($kind);
        $id = Db::insert('api_keys', [
            'kind' => $kind, 'name' => clean($name, 120) ?: ucfirst($kind),
            'key_hash' => hash('sha256', $plain), 'key_prefix' => substr($plain, 0, 10),
            'webhook_url' => $kind === 'shop' ? (self::validUrl($webhookUrl) ?: null) : null,
            'webhook_secret_enc' => $kind === 'shop' ? Crypto::enc('whsec_' . Crypto::token(24)) : null,
            'active' => 1, 'created_at' => time(),
        ]);
        return ['id' => $id, 'plain' => $plain];
    }

    public static function validUrl(string $url): string
    {
        $url = trim($url);
        if ($url === '' || strlen($url) > 500 || preg_match('#^https?://[^\s/]+#i', $url) !== 1 || filter_var($url, FILTER_VALIDATE_URL) === false) {
            return '';
        }
        return $url;
    }

    public static function rotate(int $id): ?string
    {
        $row = self::find($id);
        if (!$row) {
            return null;
        }
        $plain = self::generate($row['kind']);
        Db::update('api_keys', ['key_hash' => hash('sha256', $plain), 'key_prefix' => substr($plain, 0, 10)], 'id=?', [$id]);
        return $plain;
    }

    public static function find(int $id): ?array
    {
        return Db::one('SELECT * FROM api_keys WHERE id=?', [$id]);
    }

    public static function all(): array
    {
        return Db::all('SELECT * FROM api_keys ORDER BY kind, id');
    }

    public static function webhookSecret(array $key): string
    {
        return (string) Crypto::dec($key['webhook_secret_enc'] ?? null);
    }

    /** Xác thực Bearer cho API. Sai khoá → 401; sai ≥ 30 lần/10 phút từ 1 IP → 429 (khoá đúng luôn qua). */
    public static function auth(string $kind): array
    {
        $tok = Req::bearer();
        $row = $tok === '' ? null : Db::one('SELECT * FROM api_keys WHERE key_hash=? AND kind=? AND active=1', [hash('sha256', $tok), $kind]);
        if ($row) {
            Db::run('UPDATE api_keys SET last_seen_at=? WHERE id=?', [time(), $row['id']]);
            return $row;
        }
        $bucket = 'apifail:' . Req::ip();
        if (RateLimit::count($bucket, 600) >= 30) {
            Res::err(429, 'too_many', 'Sai khoá quá nhiều lần, thử lại sau 10 phút.');
        }
        RateLimit::hit($bucket);
        Res::err(401, 'unauthorized', 'Thiếu hoặc sai khoá API (header Authorization: Bearer <khoá>).');
    }
}

/* ====================== Devices ====================== */
final class Devices
{
    public static function touch(int $keyId, string $name, ?string $pool, string $state, ?string $jobPid): void
    {
        $n = Db::run(
            'UPDATE devices SET pool_code=?, state=?, job_pid=?, last_seen_at=? WHERE tool_key_id=? AND name=?',
            [$pool, $state, $jobPid, time(), $keyId, $name]
        )->rowCount();
        if ($n === 0) {
            try {
                Db::insert('devices', ['tool_key_id' => $keyId, 'name' => $name, 'pool_code' => $pool, 'state' => $state, 'job_pid' => $jobPid, 'last_seen_at' => time()]);
            } catch (Throwable $e) {
                if (!Db::isDuplicate($e)) {
                    throw $e;
                }
            }
        }
    }

    public static function free(?int $keyId, ?string $name): void
    {
        if ($keyId && $name) {
            Db::run("UPDATE devices SET state='free', job_pid=NULL WHERE tool_key_id=? AND name=?", [$keyId, $name]);
        }
    }

    public static function all(): array
    {
        // máy tool đã gỡ (status=removed) thì thôi không hiện nữa — trừ khi còn đang đứng tên một đơn
        $live = Schema::version() >= 3 ? "WHERE (d.status IS NULL OR d.status<>'removed' OR d.job_pid IS NOT NULL) " : '';
        return Db::all('SELECT d.*, k.name AS key_name FROM devices d LEFT JOIN api_keys k ON k.id=d.tool_key_id ' . $live . 'ORDER BY d.last_seen_at DESC, d.name LIMIT 300');
    }
}

/* ====================== Tools: máy rảnh + danh mục kịch bản do TOOL TỰ BÁO ====================== */
/**
 * Gateway nằm ngoài Internet, tool nằm trong mạng nội bộ → gateway KHÔNG gọi được vào tool. Mọi thứ gateway biết về
 * máy và kịch bản đều do tool tự gửi lên qua POST /api/tool/sync:
 *   - devices : ảnh chụp TOÀN BỘ máy của tool lúc này — trạng thái từng máy + máy đó chạy được những kịch bản nào;
 *   - scripts : danh mục kịch bản soạn ở tool (tên, nhóm, cách chạy, số bước, biến cần dữ liệu, dàn ý các bước).
 * Danh mục chỉ gửi khi đổi: tool gửi kèm `scripts_rev`, gateway trả `need_scripts` nếu bản mình đang giữ khác.
 * API này KHÔNG đụng tới đơn nạp (devices.state / job_pid / jobs.seen_at vẫn do claim + heartbeat ghi).
 */
final class Tools
{
    /** trạng thái máy do tool báo → [nhãn, màu badge] */
    public const STATUS = [
        'idle'    => ['rảnh', 'success'],
        'running' => ['đang chạy kịch bản', 'info'],
        'orders'  => ['đang nhận đơn', 'info'],
        'paused'  => ['đang dừng · xử lý tay', 'warning'],
        'hold'    => ['dừng chờ kiểm tra', 'danger'],
        'manual'  => ['đang điều khiển tay', 'warning'],
        'offline' => ['chưa sẵn sàng', 'secondary'],
    ];
    public const FRESH = 90;            // giây: tool im quá chừng này thì lời báo cũ không còn đáng tin
    public const MAX_BODY = 1048576;
    public const MAX_DEVICES = 200;
    public const MAX_SCRIPTS = 300;
    public const MAX_OUTLINE = 80;
    private const ID = '[A-Za-z0-9_.-]{1,40}';

    private static function err(string $error, string $message = ''): array
    {
        return ['ok' => false, 'error' => $error, 'message' => $message];
    }

    /** «mã nhóm:mã kịch bản» hợp lệ, hoặc '' */
    private static function uid(mixed $v): string
    {
        $v = is_scalar($v) ? trim((string) $v) : '';
        return preg_match('/^' . self::ID . ':' . self::ID . '$/D', $v) === 1 ? $v : '';
    }

    public static function sync(array $key, array $in): array
    {
        if (Schema::version() < 3) {
            return [503, self::err('needs_migration', 'Gateway cần cập nhật CSDL: chạy php bin/setup.php')];
        }
        $kid = (int) $key['id'];
        $now = time();
        $info = jdec($key['tool_info'] ?? null);

        $rev = is_scalar($in['scripts_rev'] ?? null) ? strtolower(trim((string) $in['scripts_rev'])) : '';
        if (preg_match('/^[a-f0-9]{16,64}$/D', $rev) !== 1) {
            $rev = '';
        }

        // ---- kiểm HẾT trước, rồi mới ghi: lời báo bị từ chối thì không ghi dở dang gì ----
        $hasScripts = array_key_exists('scripts', $in);
        $hasDevices = array_key_exists('devices', $in);
        if ($hasScripts) {
            if (!is_array($in['scripts']) || !array_is_list($in['scripts'])) {
                return [422, self::err('invalid_scripts', 'scripts phải là một danh sách.')];
            }
            if ($rev === '') {
                return [422, self::err('missing_rev', 'Gửi scripts thì phải kèm scripts_rev (mã băm của danh mục, 16–64 ký tự hex).')];
            }
            if (count($in['scripts']) > self::MAX_SCRIPTS) {
                return [422, self::err('too_many_scripts', 'Tối đa ' . self::MAX_SCRIPTS . ' kịch bản cho một khoá Tool.')];
            }
        }
        if ($hasDevices) {
            if (!is_array($in['devices']) || !array_is_list($in['devices'])) {
                return [422, self::err('invalid_devices', 'devices phải là một danh sách.')];
            }
            if (count($in['devices']) > self::MAX_DEVICES) {
                return [422, self::err('too_many_devices', 'Tối đa ' . self::MAX_DEVICES . ' máy cho một khoá Tool.')];
            }
        }

        // ---- 1) danh mục kịch bản (chỉ khi tool gửi kèm) ----
        if ($hasScripts) {
            self::saveCatalog($kid, $in['scripts'], $now);
            $info['scripts_rev'] = $rev;
        }

        // ---- 2) máy: ảnh chụp toàn bộ ----
        $count = null;
        if ($hasDevices) {
            $seen = [];
            foreach ($in['devices'] as $d) {
                $name = is_array($d) ? clean($d['name'] ?? '', 80) : '';
                if ($name === '' || isset($seen[$name])) {
                    continue;
                }
                $seen[$name] = true;
                self::saveDevice($kid, $name, $d, $now);
            }
            // Máy trước đây tool có khai mà lần này không còn → đã bị gỡ khỏi tool: xoá dòng (bảng không phình theo số tên máy từng được khai).
            // Riêng máy còn đang đứng tên một đơn thì giữ lại, đánh dấu «removed», để người đối soát vẫn thấy.
            foreach (Db::all("SELECT id, name FROM devices WHERE tool_key_id=? AND synced_at IS NOT NULL AND (status IS NULL OR status<>'removed')", [$kid]) as $row) {
                if (!isset($seen[$row['name']])) {
                    if (Db::run('DELETE FROM devices WHERE id=? AND job_pid IS NULL', [$row['id']])->rowCount() === 0) {
                        Db::update('devices', ['status' => 'removed', 'status_note' => null, 'scripts' => null, 'running' => null], 'id=?', [$row['id']]);
                    }
                }
            }
            // máy đã gỡ mà đơn nó đứng tên đã xong (job_pid trống) thì không còn lý do giữ dòng
            Db::run("DELETE FROM devices WHERE tool_key_id=? AND status='removed' AND job_pid IS NULL", [$kid]);
            $count = count($seen);
        }

        // ---- 3) thông tin về chính tool ----
        $tool = is_array($in['tool'] ?? null) ? $in['tool'] : [];
        $info['app'] = clean($tool['app'] ?? '', 40);
        $info['mode'] = in_array($tool['mode'] ?? '', ['desktop', 'web'], true) ? $tool['mode'] : '';
        // tool có đang nhận đơn của khách không (bản web dev của tool thì KHÔNG). Thiếu = KHÔNG RÕ (null) — không tự coi là đang nhận đơn.
        $info['accepting'] = array_key_exists('accepting', $tool) ? ($tool['accepting'] === true) : null;
        $info['synced_at'] = $now;
        if ($count !== null) {
            $info['devices'] = $count;
        }
        Db::update('api_keys', ['tool_info' => jenc($info)], 'id=?', [$kid]);

        $have = (string) ($info['scripts_rev'] ?? '');
        return [200, [
            'ok' => true, 'server_time' => iso($now),
            'scripts_rev' => $have !== '' ? $have : null,
            'need_scripts' => $rev !== '' && $have !== $rev,       // bản gateway đang giữ khác bản của tool → gửi lại kèm `scripts`
            'devices' => (int) Db::val("SELECT COUNT(*) FROM devices WHERE tool_key_id=? AND synced_at IS NOT NULL AND status<>'removed'", [$kid]),
            'scripts' => (int) Db::val('SELECT COUNT(*) FROM tool_scripts WHERE tool_key_id=?', [$kid]),
        ]];
    }

    private static function saveDevice(int $kid, string $name, array $d, int $now): void
    {
        $status = is_string($d['status'] ?? null) && isset(self::STATUS[$d['status']]) ? $d['status'] : 'offline';
        $note = clean($d['note'] ?? '', 200);
        if (!is_string($d['status'] ?? null) || !isset(self::STATUS[$d['status']])) {
            $note = 'tool báo trạng thái lạ';              // không đoán: trạng thái không hiểu được thì KHÔNG coi là rảnh
        }
        $uids = [];
        foreach ((array) ($d['scripts'] ?? []) as $u) {
            $u = self::uid($u);
            if ($u !== '' && !in_array($u, $uids, true)) {
                $uids[] = $u;
                if (count($uids) >= 100) {
                    break;
                }
            }
        }
        $run = null;
        if (is_array($d['running'] ?? null)) {
            $r = $d['running'];
            $run = array_filter([
                'uid' => self::uid($r['uid'] ?? ''), 'group' => clean($r['group'] ?? '', 160), 'script' => clean($r['script'] ?? '', 160),
                'iter' => max(0, min(100000000, (int) (is_numeric($r['iter'] ?? null) ? $r['iter'] : 0))),
            ], static fn ($v) => $v !== '' && $v !== 0);
        }
        $data = [
            'label' => clean($d['label'] ?? '', 120) ?: null, 'status' => $status, 'status_note' => $note ?: null,
            'scripts' => jenc($uids), 'running' => $run ? jenc($run) : null, 'synced_at' => $now, 'last_seen_at' => $now,
        ];
        if (Db::update('devices', $data, 'tool_key_id=? AND name=?', [$kid, $name]) === 0) {
            try {
                Db::insert('devices', ['tool_key_id' => $kid, 'name' => $name, 'state' => 'free'] + $data);
            } catch (Throwable $e) {
                if (!Db::isDuplicate($e)) {
                    throw $e;
                }
                Db::update('devices', $data, 'tool_key_id=? AND name=?', [$kid, $name]);      // hai lời báo cùng lúc: bên kia vừa tạo dòng
            }
        }
    }

    /** Danh mục là ảnh chụp TOÀN BỘ: có thì thêm / sửa, tool không còn khai thì xoá. */
    private static function saveCatalog(int $kid, array $rows, int $now): void
    {
        $keep = [];
        foreach ($rows as $r) {
            $uid = is_array($r) ? self::uid($r['uid'] ?? '') : '';
            if ($uid === '' || isset($keep[$uid])) {
                continue;
            }
            [$gid, $sid] = explode(':', $uid, 2);
            $outline = [];
            foreach ((array) ($r['outline'] ?? []) as $s) {
                $type = is_array($s) && is_string($s['type'] ?? null) ? $s['type'] : '';
                if (preg_match('/^[a-z][a-z_]{0,19}$/D', $type) !== 1) {
                    continue;
                }
                $outline[] = ['type' => $type, 'note' => clean($s['note'] ?? '', 120), 'optional' => !empty($s['optional'])];
                if (count($outline) >= self::MAX_OUTLINE) {
                    break;
                }
            }
            $vars = [];
            foreach ((array) ($r['vars'] ?? []) as $v) {
                $v = is_scalar($v) ? trim((string) $v) : '';
                if (preg_match('/^[A-Za-z][A-Za-z0-9_.]{0,59}$/D', $v) === 1 && !in_array($v, $vars, true)) {
                    $vars[] = $v;
                    if (count($vars) >= 40) {
                        break;
                    }
                }
            }
            $data = [
                'group_id' => $gid, 'group_name' => clean($r['group'] ?? '', 160), 'script_id' => $sid,
                'name' => clean($r['name'] ?? '', 160) ?: $sid,
                'run_mode' => ($r['mode'] ?? '') === 'loop' ? 'loop' : 'once',
                'loops' => max(0, min(1000000, (int) (is_numeric($r['loops'] ?? null) ? $r['loops'] : 1))),
                'step_count' => max(0, min(100000, (int) (is_numeric($r['step_count'] ?? null) ? $r['step_count'] : count($outline)))),
                'vars' => jenc($vars), 'outline' => jenc($outline),
            ];
            $old = Db::one('SELECT * FROM tool_scripts WHERE tool_key_id=? AND uid=?', [$kid, $uid]);
            if ($old) {
                $changed = false;
                foreach ($data as $k => $v) {
                    $changed = $changed || (string) $old[$k] !== (string) $v;
                }
                if ($changed) {
                    Db::update('tool_scripts', $data + ['updated_at' => $now], 'id=?', [$old['id']]);
                }
            } else {
                try {
                    Db::insert('tool_scripts', ['tool_key_id' => $kid, 'uid' => $uid, 'first_seen_at' => $now, 'updated_at' => $now] + $data);
                } catch (Throwable $e) {
                    if (!Db::isDuplicate($e)) {
                        throw $e;
                    }
                }
            }
            $keep[$uid] = true;
        }
        foreach (Db::all('SELECT id, uid FROM tool_scripts WHERE tool_key_id=?', [$kid]) as $row) {
            if (!isset($keep[$row['uid']])) {
                Db::run('DELETE FROM tool_scripts WHERE id=?', [$row['id']]);
            }
        }
    }

    /** Lời báo của tool về máy này còn mới không. */
    public static function fresh(array $d, ?int $now = null): bool
    {
        return (int) ($d['synced_at'] ?? 0) > ($now ?? time()) - self::FRESH;
    }

    /**
     * Trạng thái để HIỆN của một máy: ưu tiên lời tool vừa báo (sync); không có / đã cũ thì theo heartbeat + claim như trước.
     * Trả [key, nhãn, màu, ghi chú].
     */
    public static function state(array $d, ?int $now = null): array
    {
        $now ??= time();
        $st = (string) ($d['status'] ?? '');
        if (self::fresh($d, $now) && isset(self::STATUS[$st])) {
            if ($st === 'idle' && self::holdsJob($d)) {
                // Tool báo rảnh nhưng gateway còn ghi máy này đang đứng tên một đơn (vd tool vừa bị tắt giữa đơn rồi mở lại) → KHÔNG rảnh.
                return ['busy', 'còn giữ đơn', 'danger', 'tool báo rảnh nhưng gateway còn ghi máy này đang giữ một đơn — kiểm tra đơn đó'];
            }
            return [$st, self::STATUS[$st][0], self::STATUS[$st][1], (string) ($d['status_note'] ?? '')];
        }
        $seen = (int) $d['last_seen_at'];
        $synced = (int) ($d['synced_at'] ?? 0);
        // im quá 2 phút, hoặc lần liên lạc cuối chính là lời báo sync đã cũ → không còn biết máy đang làm gì
        if ($seen <= $now - 120 || ($synced > 0 && $seen <= $synced)) {
            return ['lost', 'mất kết nối', 'secondary', ''];
        }
        return $d['state'] === 'busy' ? ['busy', 'đang nạp', 'info', ''] : ['free', 'trống', 'success', ''];
    }

    /** Gateway còn ghi máy này đang đứng tên một đơn (do claim / heartbeat ghi). */
    public static function holdsJob(array $d): bool
    {
        return ($d['state'] ?? '') === 'busy' || (string) ($d['job_pid'] ?? '') !== '';
    }

    /**
     * Máy này đang RẢNH và chạy được kịch bản `uid` ngay lúc này: tool vừa báo idle (chưa quá FRESH giây), kịch bản nằm trong danh sách
     * của máy, VÀ gateway không còn ghi máy đang giữ đơn nào. Mọi quyết định «giao việc cho máy rảnh» sau này phải đi qua hàm này.
     */
    public static function idleFor(array $d, string $uid, ?int $now = null): bool
    {
        return self::fresh($d, $now) && ($d['status'] ?? '') === 'idle' && !self::holdsJob($d)
            && in_array($uid, jdec($d['scripts'] ?? null), true);
    }

    /**
     * Cho trang quản trị: từng khoá Tool → thông tin tool, danh mục kịch bản (kèm máy nào đang rảnh / đang bận ở kịch bản đó), và các máy.
     * @return list<array{key: array, info: array, fresh: bool, scripts: list<array>, devices: list<array>}>
     */
    public static function board(): array
    {
        if (Schema::version() < 3) {
            return [];
        }
        $now = time();
        $out = [];
        foreach (Db::all("SELECT * FROM api_keys WHERE kind='tool' ORDER BY id") as $k) {
            $info = jdec($k['tool_info'] ?? null);
            $devices = Db::all("SELECT * FROM devices WHERE tool_key_id=? AND synced_at IS NOT NULL AND status<>'removed' ORDER BY name", [$k['id']]);
            $scripts = [];
            foreach (Db::all('SELECT * FROM tool_scripts WHERE tool_key_id=? ORDER BY group_name, name, uid', [$k['id']]) as $s) {
                $s['vars'] = jdec($s['vars']);
                $s['outline'] = jdec($s['outline']);
                $s['idle'] = [];
                $s['others'] = [];
                foreach ($devices as $d) {
                    if (!in_array($s['uid'], jdec($d['scripts'] ?? null), true)) {
                        continue;
                    }
                    if (self::idleFor($d, $s['uid'], $now)) {
                        $s['idle'][] = $d;
                    } else {
                        $s['others'][] = $d;
                    }
                }
                $scripts[] = $s;
            }
            if (!$scripts && !$devices && !$info) {
                continue;                               // khoá Tool chưa từng gọi sync
            }
            $out[] = ['key' => $k, 'info' => $info, 'fresh' => (int) ($info['synced_at'] ?? 0) > $now - self::FRESH, 'scripts' => $scripts, 'devices' => $devices];
        }
        return $out;
    }

    /** uid → tên kịch bản (mọi khoá Tool) để ghi tên thay cho mã ở bảng máy. */
    public static function scriptNames(): array
    {
        if (Schema::version() < 3) {
            return [];
        }
        $out = [];
        foreach (Db::all('SELECT tool_key_id, uid, name, step_count FROM tool_scripts') as $r) {
            $out[$r['tool_key_id'] . '|' . $r['uid']] = ['name' => $r['name'], 'steps' => (int) $r['step_count']];
        }
        return $out;
    }
}

/* ====================== Jobs ====================== */
final class Jobs
{
    public const ACTIVE = ['claimed', 'running', 'need_otp'];
    public const LABEL = [
        'queued'    => 'Chờ máy trống',
        'claimed'   => 'Đã giao máy',
        'running'   => 'Đang xử lý',
        'need_otp'  => 'Chờ OTP',
        'done'      => 'Hoàn tất',
        'failed'    => 'Thất bại (chưa nạp)',
        'review'    => 'Chờ đối soát',
        'cancelled' => 'Đã huỷ',
        'expired'   => 'Quá hạn chờ',
    ];
    public const REVIEW_REASON = [
        'timeout' => 'Tool im lặng quá lâu',
        'tool'    => 'Tool báo không chắc',
        'no_bill' => 'Báo xong nhưng thiếu ảnh',
    ];
    private const IN_ACTIVE = "('claimed','running','need_otp')";

    private static function err(string $error, string $message = '', array $extra = []): array
    {
        return array_merge(['ok' => false, 'error' => $error, 'message' => $message], $extra);
    }

    public static function event(int $jobId, string $actor, string $type, string $message = ''): void
    {
        Db::insert('job_events', ['job_id' => $jobId, 'at' => time(), 'actor' => $actor, 'type' => $type, 'message' => clean($message, 500) ?: null]);
    }

    public static function byId(int $id): ?array
    {
        return Db::one('SELECT * FROM jobs WHERE id=?', [$id]);
    }

    public static function forShop(array $key, string $pid): ?array
    {
        return Db::one('SELECT * FROM jobs WHERE pid=? AND shop_key_id=?', [$pid, $key['id']]);
    }

    public static function forTool(array $key, string $pid): ?array
    {
        return Db::one('SELECT * FROM jobs WHERE pid=? AND tool_key_id=?', [$pid, $key['id']]);
    }

    private static function seen(array $job): void
    {
        Db::run('UPDATE jobs SET seen_at=? WHERE id=? AND status IN ' . self::IN_ACTIVE, [time(), $job['id']]);
    }

    public static function images(int $jobId): array
    {
        $out = [];
        foreach (Db::all('SELECT * FROM job_images WHERE job_id=? ORDER BY seq', [$jobId]) as $im) {
            $ext = pathinfo((string) $im['path'], PATHINFO_EXTENSION);
            $url = app_url('/files/' . $im['token'] . '.' . $ext);
            $out[] = ['seq' => (int) $im['seq'], 'kind' => $im['kind'], 'mime' => $im['mime'], 'size' => (int) $im['size'],
                      'url' => $url, 'download_url' => $url . '?download=1', 'created_at' => iso((int) $im['created_at'])];
        }
        return $out;
    }

    /** Job nhìn từ API. $forTool: kèm chi tiết gói (chữ OCR); $withLogin: kèm thông tin đăng nhập đã giải mã. */
    public static function view(array $job, bool $forTool = false, bool $withLogin = false): array
    {
        static $poolCodes = [];
        $pid = (int) $job['pool_id'];
        $poolCodes[$pid] ??= (string) Db::val('SELECT code FROM pools WHERE id=?', [$pid]);
        $items = [];
        foreach (jdec($job['items']) as $it) {
            $row = ['code' => (string) ($it['code'] ?? ''), 'name' => $it['name'] ?? '', 'qty' => (int) ($it['qty'] ?? 1)];
            if ($forTool) {
                $row['ocr_text'] = $it['ocr_text'] ?? '';
                $row['price_text'] = $it['price_text'] ?? '';
                $row['limit_type'] = $it['limit_type'] ?? 'multi';
            }
            $items[] = $row;
        }
        $out = [
            'id' => $job['pid'], 'ref' => $job['ref'], 'pool' => $poolCodes[$pid],
            'status' => $job['status'], 'status_label' => self::LABEL[$job['status']] ?? $job['status'],
            'stage' => $job['stage'], 'message' => $job['message'], 'review_reason' => $job['review_reason'],
            'device' => $job['device'],
            'otp' => [
                'state' => $job['otp_state'], 'seq' => (int) $job['otp_seq'],
                'deadline' => iso($job['otp_deadline'] ? (int) $job['otp_deadline'] : null), 'message' => $job['otp_message'],
            ],
            'items' => $items,
            'result' => array_map(static fn ($r) => is_array($r) ? ['code' => (string) ($r['code'] ?? '')] + $r : $r, jdec($job['result'])) ?: null,
            'images' => self::images((int) $job['id']),
            'note' => $job['note'],
            'created_at' => iso((int) $job['created_at']),
            'claimed_at' => iso($job['claimed_at'] ? (int) $job['claimed_at'] : null),
            'finished_at' => iso($job['finished_at'] ? (int) $job['finished_at'] : null),
            'updated_at' => iso((int) $job['updated_at']),
        ];
        if ($withLogin) {
            $out['login'] = jdec(Crypto::dec($job['login_enc'])) ?: new stdClass();
        }
        return $out;
    }

    private static function hint(string $v): string
    {
        $len = mb_strlen($v);
        if ($len <= 4) {
            return str_repeat('*', $len);
        }
        return mb_substr($v, 0, 2) . str_repeat('*', min(8, $len - 4)) . mb_substr($v, -2);
    }

    /* ---------- SHOP: tạo đơn ---------- */
    public static function create(array $key, array $in): array
    {
        $pool = Pools::byCode(strtolower(clean($in['pool'] ?? '', 40)));
        if (!$pool) {
            return [404, self::err('pool_not_found', 'Không có pool này.')];
        }
        $ref = is_scalar($in['ref'] ?? null) ? trim((string) $in['ref']) : '';
        if (preg_match('/^[A-Za-z0-9_.:\-]{1,80}$/', $ref) !== 1) {
            return [422, self::err('invalid_ref', 'ref (mã đơn của shop) gồm 1–80 ký tự chữ/số/_ . : -')];
        }
        // idempotent: cùng (khoá shop, ref) → trả job cũ, KHÔNG tạo mới, không sửa gì
        $ex = Db::one('SELECT * FROM jobs WHERE shop_key_id=? AND ref=?', [$key['id'], $ref]);
        if ($ex) {
            return [200, ['ok' => true, 'duplicate' => true, 'job' => self::view($ex)]];
        }
        if (!(int) $pool['active']) {
            return [409, self::err('pool_paused', 'Pool đang tạm dừng, không nhận đơn mới.')];
        }
        $cfg = $pool['cfg'];

        // --- trường đăng nhập theo cấu hình pool ---
        $loginIn = is_array($in['login'] ?? null) ? $in['login'] : [];
        $login = [];
        $hint = '';
        foreach ($cfg['login_fields'] as $f) {
            $raw = $loginIn[$f['key']] ?? '';
            if ($f['secret']) {
                $v = is_scalar($raw) ? mb_substr((string) $raw, 0, 5000) : '';     // bí mật: giữ nguyên, không trim
            } else {
                $v = clean($raw, $f['type'] === 'textarea' ? 5000 : 500, $f['type'] === 'textarea');
            }
            if ($f['required'] && trim($v) === '') {
                return [422, self::err('missing_field', 'Thiếu trường «' . $f['label'] . '».', ['field' => $f['key']])];
            }
            if ($f['type'] === 'select' && $v !== '' && !in_array($v, $f['options'], true)) {
                return [422, self::err('invalid_field', 'Giá trị «' . $f['label'] . '» không nằm trong danh sách.', ['field' => $f['key']])];
            }
            $login[$f['key']] = $v;
            if ($hint === '' && !$f['secret'] && $v !== '') {
                $hint = self::hint($v);
            }
        }

        // --- gói nạp ---
        $pk = [];
        foreach (Pools::packages((int) $pool['id'], true) as $p) {
            $pk[$p['code']] = $p;
        }
        $rawItems = is_array($in['items'] ?? null) ? $in['items'] : [];
        if (!$rawItems || count($rawItems) > 30) {
            return [422, self::err('invalid_items', 'items phải có 1–30 dòng {code, qty}.')];
        }
        $qty = [];
        foreach ($rawItems as $it) {
            $code = is_array($it) ? clean($it['code'] ?? '', 60) : '';
            $q = is_array($it) ? (int) ($it['qty'] ?? 1) : 0;
            if (!isset($pk[$code])) {
                return [422, self::err('unknown_package', 'Pool không có gói «' . $code . '» (hoặc gói đang tắt).', ['code' => $code])];
            }
            if ($q < 1) {
                return [422, self::err('invalid_qty', 'qty phải ≥ 1.', ['code' => $code])];
            }
            $qty[$code] = ($qty[$code] ?? 0) + $q;
        }
        $items = [];
        foreach ($qty as $code => $q) {
            $code = (string) $code;         // mã toàn chữ số («1050») bị PHP đổi thành số khi làm khoá mảng
            $p = $pk[$code];
            $max = $p['limit_type'] !== 'multi' ? 1 : ((int) $p['max_qty'] > 0 ? (int) $p['max_qty'] : 99);
            if ($q > $max) {
                return [422, self::err('qty_limit', 'Gói «' . $p['name'] . '» chỉ mua được tối đa ' . $max . ' trong một đơn.', ['code' => $code, 'max' => $max])];
            }
            $items[] = ['code' => $code, 'name' => $p['name'], 'qty' => $q, 'ocr_text' => $p['ocr_text'], 'price_text' => $p['price_text'], 'limit_type' => $p['limit_type']];
        }

        $now = time();
        try {
            $id = Db::insert('jobs', [
                'pid' => 'J' . strtoupper(Crypto::token(8)), 'pool_id' => $pool['id'], 'shop_key_id' => $key['id'], 'ref' => $ref,
                'status' => 'queued', 'stage' => 'queued', 'login_enc' => Crypto::enc(jenc($login)), 'account_hint' => $hint ?: null,
                'items' => jenc($items), 'note' => clean($in['note'] ?? '', 500) ?: null,
                'created_at' => $now, 'updated_at' => $now,
            ]);
        } catch (Throwable $e) {
            if (Db::isDuplicate($e)) {   // hai request cùng ref chạy đua → trả job của bên thắng
                $ex = Db::one('SELECT * FROM jobs WHERE shop_key_id=? AND ref=?', [$key['id'], $ref]);
                if ($ex) {
                    return [200, ['ok' => true, 'duplicate' => true, 'job' => self::view($ex)]];
                }
            }
            throw $e;
        }
        self::event($id, 'shop', 'created', 'Shop «' . $key['name'] . '» tạo đơn ' . $ref);
        return [201, ['ok' => true, 'job' => self::view(self::byId($id))]];
    }

    /* ---------- SHOP: huỷ khi còn trong hàng chờ ---------- */
    public static function cancel(array $job, string $actor = 'shop'): array
    {
        $n = Db::run("UPDATE jobs SET status='cancelled', stage='cancelled', login_enc=NULL, otp_enc=NULL, finished_at=?, updated_at=? WHERE id=? AND status='queued'",
            [time(), time(), $job['id']])->rowCount();
        if ($n !== 1) {
            $cur = self::byId((int) $job['id']);
            return [409, self::err('not_cancellable', 'Đơn đã giao cho máy nạp, không huỷ được nữa.', ['status' => $cur['status'] ?? null])];
        }
        self::event((int) $job['id'], $actor, 'cancelled', 'Huỷ khi còn chờ máy');
        Webhooks::enqueue(self::byId((int) $job['id']), 'job.cancelled', ['by' => $actor === 'admin' ? 'admin' : 'shop']);
        return [200, ['ok' => true, 'status' => 'cancelled']];
    }

    /* ---------- SHOP: gửi OTP khách nhập ---------- */
    public static function otpSubmit(array $job, array $in): array
    {
        $otp = is_scalar($in['otp'] ?? null) ? preg_replace('/\s+/', '', (string) $in['otp']) : '';
        if (preg_match('/^[A-Za-z0-9]{3,12}$/', (string) $otp) !== 1) {
            return [422, self::err('invalid_otp', 'OTP gồm 3–12 ký tự chữ/số.')];
        }
        if ($job['status'] !== 'need_otp') {
            return [409, self::err('not_waiting_otp', 'Đơn không ở trạng thái chờ OTP.', ['status' => $job['status']])];
        }
        if ($job['otp_deadline'] && time() > (int) $job['otp_deadline']) {
            return [409, self::err('otp_expired', 'Đã quá hạn nhập OTP của lần yêu cầu này.')];
        }
        $n = Db::run("UPDATE jobs SET otp_enc=?, otp_state='submitted', updated_at=? WHERE id=? AND status='need_otp' AND otp_seq=?",
            [Crypto::enc((string) $otp), time(), $job['id'], $job['otp_seq']])->rowCount();
        if ($n !== 1) {
            return [409, self::err('not_waiting_otp', 'Trạng thái đơn vừa thay đổi, tải lại rồi thử lại.')];
        }
        self::event((int) $job['id'], 'shop', 'otp_submitted', 'Khách đã gửi OTP (lần ' . $job['otp_seq'] . ')');
        return [200, ['ok' => true, 'otp' => ['state' => 'submitted', 'seq' => (int) $job['otp_seq']]]];
    }

    /* ---------- TOOL: máy trống xin việc ---------- */
    public static function claim(array $key, array $in): array
    {
        $device = clean($in['device'] ?? '', 80);
        if ($device === '') {
            return [422, self::err('missing_device', 'Thiếu device (tên máy).')];
        }
        $pool = Pools::byCode(strtolower(clean($in['pool'] ?? '', 40)));
        if (!$pool) {
            return [404, self::err('pool_not_found', 'Không có pool này.')];
        }
        self::sweep();
        $now = time();

        // máy còn giữ 1 job chưa xong (tool vừa khởi động lại / mất phản hồi) → trả lại đúng job đó
        $held = Db::one('SELECT * FROM jobs WHERE tool_key_id=? AND device=? AND status IN ' . self::IN_ACTIVE . ' ORDER BY id LIMIT 1', [$key['id'], $device]);
        if ($held) {
            self::seen($held);
            Devices::touch((int) $key['id'], $device, $pool['code'], 'busy', $held['pid']);
            return [200, ['ok' => true, 'paused' => false, 'resumed' => true, 'job' => self::view($held, true, true)]];
        }
        Devices::touch((int) $key['id'], $device, $pool['code'], 'free', null);
        if (!(int) $pool['active']) {
            return [200, ['ok' => true, 'paused' => true, 'job' => null]];
        }

        $since = $now - (int) $pool['cfg']['queue_ttl'];
        $cands = Db::all("SELECT id FROM jobs WHERE pool_id=? AND status='queued' AND created_at>=? ORDER BY id LIMIT 5", [$pool['id'], $since]);
        foreach ($cands as $c) {
            // UPDATE có điều kiện = khoá lạc quan: hai máy xin cùng lúc chỉ MỘT máy thắng
            $n = Db::run("UPDATE jobs SET status='claimed', stage='claimed', device=?, tool_key_id=?, claimed_at=?, seen_at=?, updated_at=? WHERE id=? AND status='queued'",
                [$device, $key['id'], $now, $now, $now, $c['id']])->rowCount();
            if ($n === 1) {
                $job = self::byId((int) $c['id']);
                self::event((int) $job['id'], 'tool', 'claimed', 'Giao cho máy ' . $device . ' (' . $key['name'] . ')');
                Devices::touch((int) $key['id'], $device, $pool['code'], 'busy', $job['pid']);
                Webhooks::enqueue($job, 'job.claimed');
                return [200, ['ok' => true, 'paused' => false, 'job' => self::view($job, true, true)]];
            }
        }
        return [200, ['ok' => true, 'paused' => false, 'job' => null]];
    }

    /* ---------- TOOL: nhịp tim ---------- */
    public static function heartbeat(array $key, array $in): array
    {
        $n = 0;
        foreach ((array) ($in['devices'] ?? []) as $d) {
            if (!is_array($d) || ++$n > 100) {
                continue;
            }
            $name = clean($d['name'] ?? '', 80);
            if ($name === '') {
                continue;
            }
            $state = ($d['state'] ?? 'free') === 'busy' ? 'busy' : 'free';
            Devices::touch((int) $key['id'], $name, clean($d['pool'] ?? '', 40) ?: null, $state, clean($d['job'] ?? '', 24) ?: null);
        }
        $pids = array_slice(array_values(array_filter(array_map(static fn ($p) => clean($p, 24), (array) ($in['active'] ?? [])))), 0, 100);
        foreach ($pids as $pid) {
            Db::run('UPDATE jobs SET seen_at=? WHERE pid=? AND tool_key_id=? AND status IN ' . self::IN_ACTIVE, [time(), $pid, $key['id']]);
        }
        self::sweep();
        return [200, ['ok' => true, 'server_time' => iso(time())]];
    }

    /* ---------- TOOL: báo tiến độ ---------- */
    public static function progress(array $key, array $job, array $in): array
    {
        $stage = strtolower(clean($in['stage'] ?? '', 40));
        if (preg_match('/^[a-z][a-z0-9_]{0,39}$/', $stage) !== 1) {
            return [422, self::err('invalid_stage', 'stage gồm chữ thường/số/_ (vd login, logged_in, purchasing).')];
        }
        $msg = clean($in['message'] ?? '', 300) ?: null;
        $now = time();
        $n = Db::run("UPDATE jobs SET status='running', stage=?, message=?, seen_at=?, updated_at=? WHERE id=? AND status IN ('claimed','running')",
            [$stage, $msg, $now, $now, $job['id']])->rowCount();
        if ($n !== 1) {
            $cur = self::byId((int) $job['id']);
            if ($cur && $cur['status'] === 'need_otp') {     // đang chờ OTP: chỉ ghi nhận còn sống
                self::seen($cur);
                return [200, ['ok' => true, 'status' => 'need_otp']];
            }
            return [409, self::err('conflict', 'Đơn đã kết thúc hoặc không còn do máy này giữ.', ['status' => $cur['status'] ?? null])];
        }
        if ($stage !== $job['stage']) {
            self::event((int) $job['id'], 'tool', 'progress', $stage . ($msg ? ' — ' . $msg : ''));
            Webhooks::enqueue(self::byId((int) $job['id']), 'job.progress');
        }
        return [200, ['ok' => true, 'status' => 'running']];
    }

    /* ---------- TOOL: game đòi OTP → nhờ khách nhập ---------- */
    public static function otpRequest(array $key, array $job, array $in): array
    {
        $pool = Pools::find((int) $job['pool_id']);
        $otpCfg = $pool['cfg']['otp'];
        if (!$otpCfg['enabled']) {
            return [409, self::err('otp_disabled', 'Pool này không bật OTP.')];
        }
        if (!in_array($job['status'], self::ACTIVE, true)) {
            return [409, self::err('conflict', 'Đơn đã kết thúc.', ['status' => $job['status']])];
        }
        // `attempt` = lần xin thứ mấy THEO TOOL. Gateway đã ghi nhận lần đó rồi (tool gửi lại vì mất phản hồi)
        // → trả lại đúng trạng thái hiện tại, KHÔNG tính thêm lượt, không bắt khách nhập lại.
        $attempt = isset($in['attempt']) && is_numeric($in['attempt']) ? (int) $in['attempt'] : 0;
        if ($attempt >= 1 && $attempt <= (int) $job['otp_seq'] && $job['status'] === 'need_otp') {
            self::seen($job);
            return [200, ['ok' => true, 'replayed' => true, 'otp' => ['state' => $job['otp_state'], 'seq' => (int) $job['otp_seq'],
                          'deadline' => iso($job['otp_deadline'] ? (int) $job['otp_deadline'] : null), 'timeout' => (int) $otpCfg['timeout']]]];
        }
        if ((int) $job['otp_seq'] >= (int) $otpCfg['max_requests']) {
            return [409, self::err('otp_limit', 'Đã xin OTP đủ ' . $otpCfg['max_requests'] . ' lần cho đơn này.', ['max' => (int) $otpCfg['max_requests']])];
        }
        $reason = in_array($in['reason'] ?? '', ['first', 'wrong', 'expired', 'resend'], true) ? (string) $in['reason'] : 'first';
        $msg = clean($in['message'] ?? '', 300) ?: null;
        $now = time();
        $deadline = $now + (int) $otpCfg['timeout'];
        $n = Db::run("UPDATE jobs SET status='need_otp', stage='otp', otp_state='waiting', otp_seq=otp_seq+1, otp_enc=NULL, otp_deadline=?, otp_message=?, seen_at=?, updated_at=?
                      WHERE id=? AND otp_seq=? AND status IN " . self::IN_ACTIVE,
            [$deadline, $msg, $now, $now, $job['id'], $job['otp_seq']])->rowCount();
        if ($n !== 1) {
            return [409, self::err('conflict', 'Trạng thái đơn vừa thay đổi.')];
        }
        $job = self::byId((int) $job['id']);
        $why = ['first' => 'game đòi OTP', 'wrong' => 'OTP trước SAI', 'expired' => 'OTP trước hết hạn', 'resend' => 'xin gửi lại'][$reason];
        self::event((int) $job['id'], 'tool', 'otp_requested', 'Xin OTP lần ' . $job['otp_seq'] . ' (' . $why . ')' . ($msg ? ' — ' . $msg : ''));
        Webhooks::enqueue($job, 'job.need_otp', ['reason' => $reason]);
        return [200, ['ok' => true, 'otp' => ['state' => 'waiting', 'seq' => (int) $job['otp_seq'], 'deadline' => iso($deadline), 'timeout' => (int) $otpCfg['timeout']]]];
    }

    /* ---------- TOOL: lấy OTP khách vừa nhập (có thể chờ tối đa $wait giây) ---------- */
    public static function otpRead(array $key, string $pid, int $wait): array
    {
        $wait = max(0, min(25, $wait));
        $until = time() + $wait;
        while (true) {
            $job = self::forTool($key, $pid);
            if (!$job) {
                return [404, self::err('job_not_found', 'Không có đơn này (hoặc không do khoá này giữ).')];
            }
            self::seen($job);
            if ($job['otp_enc'] && in_array($job['otp_state'], ['submitted', 'read'], true)) {
                if ($job['otp_state'] === 'submitted') {
                    Db::run("UPDATE jobs SET otp_state='read', status='running', stage='otp_entered', updated_at=? WHERE id=? AND status='need_otp'", [time(), $job['id']]);
                    self::event((int) $job['id'], 'tool', 'otp_read', 'Tool đã lấy OTP lần ' . $job['otp_seq']);
                }
                return [200, ['ok' => true, 'state' => 'ready', 'otp' => (string) Crypto::dec($job['otp_enc']), 'seq' => (int) $job['otp_seq']]];
            }
            if ($job['status'] !== 'need_otp') {
                return [200, ['ok' => true, 'state' => 'none', 'status' => $job['status']]];
            }
            if ($job['otp_deadline'] && time() > (int) $job['otp_deadline']) {
                return [200, ['ok' => true, 'state' => 'expired', 'seq' => (int) $job['otp_seq']]];
            }
            if (time() >= $until) {
                return [200, ['ok' => true, 'state' => 'waiting', 'seq' => (int) $job['otp_seq'], 'deadline' => iso((int) $job['otp_deadline'])]];
            }
            sleep(1);
        }
    }

    /* ---------- TOOL: gửi ảnh (bill / ảnh màn hình / ảnh lỗi) ---------- */
    public static function addImage(array $key, array $job, int $seq, string $kind, string $bytes): array
    {
        if ($seq < 1 || $seq > 30) {
            return [422, self::err('invalid_seq', 'seq phải trong 1..30.')];
        }
        $kind = in_array($kind, ['bill', 'screenshot', 'error'], true) ? $kind : 'bill';
        $late = $job['status'] === 'review' && $job['review_reason'] === 'timeout';     // ảnh muộn = bằng chứng đối soát
        if (!in_array($job['status'], self::ACTIVE, true) && !$late) {
            return [409, self::err('conflict', 'Đơn không còn nhận ảnh (gửi ảnh TRƯỚC khi báo kết quả).', ['status' => $job['status']])];
        }
        try {
            $f = Storage::saveImage($bytes);
        } catch (InvalidArgumentException $e) {
            $code = $e->getCode() === 413 ? 413 : 415;
            return [$code, self::err($code === 413 ? 'too_large' : 'not_image', $e->getMessage())];
        }
        $old = Db::one('SELECT * FROM job_images WHERE job_id=? AND seq=?', [$job['id'], $seq]);
        $data = ['kind' => $kind, 'token' => $f['token'], 'path' => $f['path'], 'mime' => $f['mime'], 'size' => $f['size'], 'created_at' => time()];
        if ($old) {     // cùng (job, seq) gửi lại → ghi đè
            Db::update('job_images', $data, 'id=?', [$old['id']]);
            Storage::delete((string) $old['path']);
        } else {
            Db::insert('job_images', $data + ['job_id' => $job['id'], 'seq' => $seq]);
        }
        self::seen($job);
        self::event((int) $job['id'], 'tool', 'image', 'Ảnh #' . $seq . ' (' . $kind . ')' . ($late ? ' — gửi muộn' : ''));
        $ext = $f['ext'];
        return [200, ['ok' => true, 'seq' => $seq, 'url' => app_url('/files/' . $f['token'] . '.' . $ext)]];
    }

    /* ---------- TOOL: báo kết quả cuối ---------- */
    public static function result(array $key, array $job, array $in): array
    {
        $res = (string) ($in['result'] ?? '');
        if (!in_array($res, ['done', 'failed', 'review'], true)) {
            return [422, self::err('invalid_result', 'result phải là done | failed | review.')];
        }
        $msg = clean($in['message'] ?? '', 500) ?: null;
        $items = [];
        foreach ((array) ($in['items'] ?? []) as $it) {
            if (!is_array($it) || count($items) >= 30) {
                continue;
            }
            $items[] = [
                'code' => clean($it['code'] ?? '', 60), 'qty_done' => max(0, (int) ($it['qty_done'] ?? 0)),
                'status' => in_array($it['status'] ?? '', ['done', 'unavailable', 'failed', 'skipped'], true) ? (string) $it['status'] : 'done',
                'message' => clean($it['message'] ?? '', 200),
            ];
        }
        $now = time();
        if (in_array($job['status'], self::ACTIVE, true)) {
            $reason = null;
            if ($res === 'done') {
                $pool = Pools::find((int) $job['pool_id']);
                $hasImg = (int) Db::val('SELECT COUNT(*) FROM job_images WHERE job_id=?', [$job['id']]) > 0;
                $new = ($pool['cfg']['require_image'] && !$hasImg) ? 'review' : 'done';
                $reason = $new === 'review' ? 'no_bill' : null;
            } elseif ($res === 'failed') {
                $new = 'failed';
            } else {
                $new = 'review';
                $reason = 'tool';
            }
            // kết thúc → XOÁ thông tin đăng nhập + OTP khỏi DB
            $n = Db::run("UPDATE jobs SET status=?, stage=?, message=?, review_reason=?, result=?, login_enc=NULL, otp_enc=NULL, finished_at=?, seen_at=?, updated_at=?
                          WHERE id=? AND status IN " . self::IN_ACTIVE,
                [$new, $new, $msg, $reason, $items ? jenc($items) : null, $new === 'review' ? null : $now, $now, $now, $job['id']])->rowCount();
            if ($n === 1) {
                $job = self::byId((int) $job['id']);
                self::event((int) $job['id'], 'tool', 'result', 'Tool báo ' . $res . ' → ' . self::LABEL[$new] . ($msg ? ' — ' . $msg : ''));
                Devices::free((int) $job['tool_key_id'], $job['device']);
                Webhooks::enqueue($job, 'job.' . $new);
                return [200, ['ok' => true, 'status' => $new]];
            }
            $job = self::byId((int) $job['id']);    // thua chạy đua → xét theo trạng thái mới
        }
        $st = $job['status'];
        if ($st === 'done' || $st === 'failed') {
            return $res === $st ? [200, ['ok' => true, 'status' => $st]]                                    // idempotent
                                : [409, self::err('conflict', 'Mâu thuẫn với kết quả đã chốt.', ['status' => $st])];
        }
        if ($st === 'review') {
            // Đơn đã sang đối soát thì lời báo muộn KHÔNG tự chốt được gì (kể cả «failed»), nhưng luôn được
            // ghi vào dòng thời gian — đó là thông tin quý nhất cho người đối soát.
            $last = Db::one("SELECT message FROM job_events WHERE job_id=? AND type='late_report' ORDER BY id DESC LIMIT 1", [$job['id']]);
            $per = implode(', ', array_map(static fn (array $i): string => $i['code'] . ' ' . $i['status'] . ' ' . $i['qty_done'], $items));
            $line = clean('Tool báo muộn: ' . $res . ($msg ? ' — ' . $msg : '') . ($per !== '' ? ' [' . $per . ']' : ''), 500);
            if (($last['message'] ?? null) !== $line) {          // tool gửi lại y nguyên thì không ghi trùng
                self::event((int) $job['id'], 'tool', 'late_report', $line);
            }
            if ($res === 'failed') {
                return [409, self::err('conflict', 'Đơn đang chờ đối soát.', ['status' => $st])];
            }
            return [200, ['ok' => true, 'status' => 'review']];
        }
        return [409, self::err('conflict', 'Đơn không ở trạng thái nhận kết quả.', ['status' => $st])];
    }

    /* ---------- ADMIN: chốt đơn chờ đối soát ---------- */
    public static function adminResolve(int $jobId, string $to, string $admin): bool
    {
        if (!in_array($to, ['done', 'failed'], true)) {
            return false;
        }
        $now = time();
        $n = Db::run("UPDATE jobs SET status=?, stage=?, login_enc=NULL, otp_enc=NULL, finished_at=?, updated_at=? WHERE id=? AND status='review'",
            [$to, $to, $now, $now, $jobId])->rowCount();
        if ($n !== 1) {
            return false;
        }
        $job = self::byId($jobId);
        self::event($jobId, 'admin', 'resolved', $admin . ' chốt: ' . ($to === 'done' ? 'ĐÃ NẠP ĐỦ' : 'CHƯA NẠP'));
        Devices::free($job['tool_key_id'] ? (int) $job['tool_key_id'] : null, $job['device']);
        Webhooks::enqueue($job, 'job.' . $to);
        return true;
    }

    /* ---------- dọn: đơn chờ quá lâu → expired; tool im lặng → review ---------- */
    public static function sweep(bool $force = false): array
    {
        $now = time();
        if (!$force && (int) Settings::get('sweep_at', '0') > $now - 20) {
            return ['expired' => 0, 'timeout' => 0];
        }
        Settings::set('sweep_at', (string) $now);
        $stat = ['expired' => 0, 'timeout' => 0];
        foreach (Db::all('SELECT * FROM pools') as $p) {
            $cfg = Pools::sanitize(jdec($p['config']));
            foreach (Db::all("SELECT id FROM jobs WHERE pool_id=? AND status='queued' AND created_at<?", [$p['id'], $now - $cfg['queue_ttl']]) as $j) {
                $n = Db::run("UPDATE jobs SET status='expired', stage='expired', message='Không có máy nhận trong thời gian chờ', login_enc=NULL, otp_enc=NULL, finished_at=?, updated_at=? WHERE id=? AND status='queued'",
                    [$now, $now, $j['id']])->rowCount();
                if ($n === 1) {
                    $stat['expired']++;
                    self::event((int) $j['id'], 'system', 'expired', 'Quá ' . intdiv($cfg['queue_ttl'], 60) . ' phút không có máy nhận');
                    Webhooks::enqueue(self::byId((int) $j['id']), 'job.expired');
                }
            }
            foreach (Db::all('SELECT id, tool_key_id, device FROM jobs WHERE pool_id=? AND seen_at<? AND status IN ' . self::IN_ACTIVE, [$p['id'], $now - $cfg['silent_timeout']]) as $j) {
                $n = Db::run("UPDATE jobs SET status='review', stage='review', review_reason='timeout', login_enc=NULL, otp_enc=NULL, updated_at=? WHERE id=? AND seen_at<? AND status IN " . self::IN_ACTIVE,
                    [$now, $j['id'], $now - $cfg['silent_timeout']])->rowCount();
                if ($n === 1) {
                    $stat['timeout']++;
                    self::event((int) $j['id'], 'system', 'timeout', 'Tool im lặng quá ' . intdiv($cfg['silent_timeout'], 60) . ' phút → chờ đối soát');
                    Devices::free($j['tool_key_id'] ? (int) $j['tool_key_id'] : null, $j['device']);
                    Webhooks::enqueue(self::byId((int) $j['id']), 'job.review');
                }
            }
        }
        return $stat;
    }
}

/* ====================== Webhooks (gateway → shop) ====================== */
final class Webhooks
{
    private const BACKOFF = [30, 120, 600, 1800, 3600, 7200];
    private static bool $kicked = false;

    public static function enqueue(array $job, string $event, array $extra = []): void
    {
        $key = Keys::find((int) $job['shop_key_id']);
        if (!$key || !$key['webhook_url'] || !(int) $key['active']) {
            return;
        }
        $payload = jenc(['event' => $event, 'sent_at' => iso(time()), 'job' => Jobs::view($job)] + $extra);
        Db::insert('webhooks', ['key_id' => $key['id'], 'job_id' => $job['id'], 'event' => $event, 'payload' => $payload, 'next_at' => time(), 'created_at' => time()]);
        self::kick();
    }

    /**
     * Gửi webhook SAU khi đã trả lời xong request hiện tại — tool/shop không bao giờ phải chờ webhook.
     *  - PHP-FPM / LiteSpeed: đóng phản hồi trước (finish_request) rồi mới gửi, đủ thời gian cho mỗi webhook.
     *  - Máy chủ khác (mod_php, `php -S`): không chắc đóng được phản hồi sớm → chỉ gửi rất nhanh
     *    (tối đa 2 cái, mỗi cái 2 giây); phần còn lại để cron (`php bin/cron.php`) gửi.
     * Trước đây gửi tới 5 webhook × 6 giây ngay trong request: shop chậm là tool mất phản hồi «nhận đơn».
     */
    private static function kick(): void
    {
        if (self::$kicked) {
            return;
        }
        self::$kicked = true;
        register_shutdown_function(static function (): void {
            $detached = false;
            if (function_exists('fastcgi_finish_request')) {
                $detached = fastcgi_finish_request();
            } elseif (function_exists('litespeed_finish_request')) {
                $detached = litespeed_finish_request();
            } else {
                while (ob_get_level() > 0) {
                    @ob_end_flush();
                }
                @flush();       // phản hồi đã có Content-Length → bên gọi nhận đủ là đi tiếp
            }
            try {
                $detached ? self::deliverDue(5, 6) : self::deliverDue(2, 2);
            } catch (Throwable) {
            }
        });
    }

    public static function deliverDue(int $limit = 20, int $timeout = 6): int
    {
        $now = time();
        $sent = 0;
        foreach (Db::all("SELECT * FROM webhooks WHERE status='pending' AND next_at<=? ORDER BY id LIMIT " . max(1, min(100, $limit)), [$now]) as $w) {
            // giữ chỗ nguyên tử: hai tiến trình không gửi cùng một dòng
            $n = Db::run("UPDATE webhooks SET attempts=attempts+1, next_at=? WHERE id=? AND status='pending' AND attempts=?", [$now + 60, $w['id'], $w['attempts']])->rowCount();
            if ($n !== 1) {
                continue;
            }
            $attempt = (int) $w['attempts'] + 1;
            $key = Keys::find((int) $w['key_id']);
            if (!$key || !$key['webhook_url']) {
                Db::update('webhooks', ['status' => 'failed', 'last_error' => 'Khoá không còn webhook URL'], 'id=?', [$w['id']]);
                continue;
            }
            [$ok, $err] = self::post((string) $key['webhook_url'], (string) $w['payload'], Keys::webhookSecret($key), (string) $w['event'], (int) $w['id'], $timeout);
            if ($ok) {
                Db::update('webhooks', ['status' => 'sent', 'last_error' => null], 'id=?', [$w['id']]);
                $sent++;
            } elseif ($attempt > count(self::BACKOFF)) {
                Db::update('webhooks', ['status' => 'failed', 'last_error' => $err], 'id=?', [$w['id']]);
            } else {
                Db::update('webhooks', ['next_at' => time() + self::BACKOFF[$attempt - 1], 'last_error' => $err], 'id=?', [$w['id']]);
            }
        }
        return $sent;
    }

    /** POST JSON kèm chữ ký HMAC-SHA256 của thân. 2xx = thành công. */
    private static function post(string $url, string $body, string $secret, string $event, int $id, int $timeout = 6): array
    {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body, CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => max(1, $timeout), CURLOPT_CONNECTTIMEOUT => max(1, min(4, $timeout)), CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json; charset=utf-8',
                'User-Agent: topup-gateway/1.0',
                'X-Gateway-Event: ' . $event,
                'X-Gateway-Delivery: ' . $id,
                'X-Gateway-Signature: sha256=' . hash_hmac('sha256', $body, $secret),
            ],
        ]);
        curl_exec($ch);
        $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($code >= 200 && $code < 300) {
            return [true, null];
        }
        return [false, mb_substr($err !== '' ? $err : 'HTTP ' . $code, 0, 300)];
    }
}
