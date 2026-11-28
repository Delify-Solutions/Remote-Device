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
        'once_left'           => 'Gói «1 lần» CÒN mua được (chữ in trong ô gói, vd «Remaining: 1»)',
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
            // loại tiền (vùng App Store) mà máy của pool dùng để trả tiền → mỗi gói có giá + chữ giá theo từng loại (bảng package_prices)
            'currencies' => [],
        ];
    }

    /** «JPY, chf  KRW» → [['JPY','CHF','KRW'], null]; có mã sai → [[], 'lỗi']. */
    public static function parseCurrencies(string $raw): array
    {
        $out = [];
        foreach (preg_split('/[\s,;]+/', trim($raw), -1, PREG_SPLIT_NO_EMPTY) ?: [] as $c) {
            $cur = Money::currency($c);
            if ($cur === null) {
                return [[], 'Loại tiền «' . clean($c, 20) . '» không hợp lệ (mã ISO 3 chữ cái, vd JPY, CHF, USD).'];
            }
            if (!in_array($cur, $out, true)) {
                $out[] = $cur;
            }
        }
        if (count($out) > 10) {
            return [[], 'Tối đa 10 loại tiền cho một pool.'];
        }
        return [$out, null];
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
        $cur = [];
        foreach ((array) ($in['currencies'] ?? []) as $c) {
            $c = Money::currency($c);
            if ($c !== null && !in_array($c, $cur, true) && count($cur) < 10) {
                $cur[] = $c;
            }
        }
        $out['currencies'] = $cur;
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
        if (Wallets::enabled()) {
            Db::run('DELETE FROM package_prices WHERE package_id IN (SELECT id FROM packages WHERE pool_id=?)', [$id]);
        }
        Db::run('DELETE FROM packages WHERE pool_id=?', [$id]);
        Db::run('DELETE FROM pools WHERE id=?', [$id]);
        return true;
    }

    public static function packages(int $poolId, bool $onlyActive = false): array
    {
        return Db::all('SELECT * FROM packages WHERE pool_id=?' . ($onlyActive ? ' AND active=1' : '') . ' ORDER BY sort, id', [$poolId]);
    }

    /**
     * Giá theo loại tiền của các gói trong pool, dạng để hiện trong form:
     * id gói → mã tiền → ['amount' => chữ số tiền (vd «1500», «63.00»), 'display' => chữ giá trên máy].
     */
    public static function prices(int $poolId): array
    {
        if (!Wallets::enabled()) {
            return [];
        }
        $out = [];
        foreach (Db::all('SELECT pp.* FROM package_prices pp JOIN packages p ON p.id=pp.package_id WHERE p.pool_id=? ORDER BY pp.currency', [$poolId]) as $r) {
            $out[(int) $r['package_id']][$r['currency']] = ['amount' => Money::plain((int) $r['amount'], $r['currency']), 'display' => $r['display']];
        }
        return $out;
    }

    /**
     * Lưu cả danh sách gói từ form (dòng có id → sửa; không id → thêm; id vắng mặt → xoá).
     * `prices` của một dòng (nếu có) = mã tiền → ['amount' => chữ admin nhập, 'display' => chữ giá trên máy]; chỉ những loại tiền
     * có cột trong form mới có mặt: ô số tiền để trống = bỏ giá loại tiền đó; loại tiền không có mặt thì giữ nguyên.
     * Giá của loại tiền không còn trong danh sách loại tiền của pool bị xoá. Tất cả trong MỘT giao dịch.
     */
    public static function savePackages(int $poolId, array $rows): ?string
    {
        $wallets = Wallets::enabled();
        $pool = $wallets ? self::find($poolId) : null;
        $currencies = $pool ? $pool['cfg']['currencies'] : [];
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
            $prices = [];                                        // mã tiền → [số tiền ×100 | null (bỏ giá), chữ giá]
            foreach ((array) ($r['prices'] ?? []) as $cur => $p) {
                $cur = Money::currency($cur);
                if ($cur === null || !in_array($cur, $currencies, true) || !is_array($p)) {
                    continue;
                }
                $raw = trim((string) (is_scalar($p['amount'] ?? null) ? $p['amount'] : ''));
                $display = clean($p['display'] ?? '', 80);
                if ($raw === '') {
                    if ($display !== '') {
                        return 'Gói «' . $code . '»: có chữ giá ' . $cur . ' nhưng chưa nhập số tiền ' . $cur . '.';
                    }
                    $prices[$cur] = [null, ''];
                    continue;
                }
                if ($display === '') {
                    // tool phải KHỚP chữ giá trên ô gói (máy có ví trả bằng loại tiền này) → giá không kèm chữ thì máy không tìm được gói
                    return 'Gói «' . $code . '»: có giá ' . $cur . ' nhưng chưa nhập «chữ hiện trên máy» ' . $cur . ' (vd ' . Money::example($cur) . ') — tool dò gói theo chữ giá này.';
                }
                $amount = Money::parse($raw, $cur);
                if ($amount === null) {
                    return 'Gói «' . $code . '»: giá ' . $cur . ' «' . clean($raw, 30) . '» không hợp lệ'
                        . (Money::decimals($cur) === 0 ? ' (' . $cur . ' không có phần lẻ, vd 1500).' : ' (vd 63.00).');
                }
                $prices[$cur] = [$amount, $display];
            }
            $clean[] = [(int) ($r['id'] ?? 0), $prices, [
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
                if ($wallets) {
                    Db::run('DELETE FROM package_prices WHERE package_id=?', [$gone]);
                }
            }
            foreach ($clean as [$id, $prices, $data]) {
                if ($id > 0 && in_array($id, $keep, true)) {
                    Db::update('packages', $data, 'id=?', [$id]);
                } else {
                    $id = Db::insert('packages', $data + ['pool_id' => $poolId]);
                }
                if (!$wallets) {
                    continue;
                }
                foreach ($prices as $cur => [$amount, $display]) {
                    if ($amount === null) {
                        Db::run('DELETE FROM package_prices WHERE package_id=? AND currency=?', [$id, $cur]);
                    } elseif (Db::update('package_prices', ['amount' => $amount, 'display' => $display], 'package_id=? AND currency=?', [$id, $cur]) === 0) {
                        Db::insert('package_prices', ['package_id' => $id, 'currency' => (string) $cur, 'amount' => $amount, 'display' => $display]);
                    }
                }
            }
            if ($wallets) {
                // loại tiền đã bỏ khỏi pool → giá theo loại tiền đó cũng thôi (máy dùng ví loại tiền ấy sẽ không nhận đơn của pool: no_price)
                $in = $currencies ? ' AND currency NOT IN (' . implode(',', array_fill(0, count($currencies), '?')) . ')' : '';
                Db::run('DELETE FROM package_prices WHERE package_id IN (SELECT id FROM packages WHERE pool_id=?)' . $in, array_merge([$poolId], $currencies));
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
                $row['prices'] = new stdClass();          // {mã tiền: {amount ×100, display}} — tool chọn loại tiền theo ví của máy
            }
            $pk[] = $row;
        }
        if ($forTool && Wallets::enabled()) {
            $byId = [];
            foreach (self::packages((int) $pool['id'], true) as $i => $p) {
                $byId[(int) $p['id']] = $i;
            }
            foreach (Db::all('SELECT pp.* FROM package_prices pp JOIN packages k ON k.id=pp.package_id WHERE k.pool_id=? AND k.active=1', [$pool['id']]) as $pp) {
                $i = $byId[(int) $pp['package_id']] ?? null;
                if ($i !== null && in_array($pp['currency'], $cfg['currencies'], true)) {
                    $pk[$i]['prices']->{$pp['currency']} = ['amount' => (int) $pp['amount'], 'display' => (string) $pp['display']];
                }
            }
        }
        $out = [
            'code' => $pool['code'], 'name' => $pool['name'], 'game' => $pool['game'], 'active' => (bool) $pool['active'],
            'login_fields' => $cfg['login_fields'],
            'otp' => $cfg['otp'],
            'packages' => $pk,
        ];
        if ($forTool) {
            $out['currencies'] = $cfg['currencies'];          // loại tiền pool bán (mỗi máy trả bằng MỘT loại — theo ví của máy ở tool)
        }
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
    /** giai đoạn của một đơn (kịch bản nhận đơn chia bước theo các giai đoạn này) → nhãn */
    public const PHASES = ['login', 'otp', 'nav', 'purchase', 'after', 'finish'];
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
        if (Schema::version() < Schema::LATEST) {
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

        $hasWallets = array_key_exists('wallets', $in);
        $wallets = [];
        if ($hasWallets) {
            [$wallets, $werr] = ToolWallets::parseReport($in['wallets']);
            if ($werr !== null) {
                return [422, self::err('invalid_wallets', $werr)];
            }
        }
        $acks = is_array($in['wallet_acks'] ?? null) ? array_slice(array_values($in['wallet_acks']), 0, 1000) : [];

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

        // ---- 2b) VÍ do tool quản lý: tool đã áp các sự kiện tiền nào (ack) + bản sao ví (ảnh chụp toàn bộ) ----
        if ($acks) {
            ToolWallets::ack($kid, $acks);
        }
        if ($hasWallets) {
            ToolWallets::saveReport($kid, $wallets, $now);
            $info['wallets_by_tool'] = true;          // từ giờ ví của khoá này do tool quản lý: ví cũ khai ở gateway không còn áp khi giao đơn
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
            // tiền của các đơn (mua / tạm giữ / admin chốt / hoàn) tool chưa áp vào sổ — áp theo `id` (mỗi id một lần) rồi gửi lại trong wallet_acks
            'wallet_events' => ToolWallets::pending($kid),
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
                $row = ['type' => $type, 'note' => clean($s['note'] ?? '', 120), 'optional' => !empty($s['optional'])];
                if (is_string($s['phase'] ?? null) && in_array($s['phase'], self::PHASES, true)) {
                    $row['phase'] = $s['phase'];                 // kịch bản nhận đơn: bước thuộc giai đoạn nào của đơn
                }
                $outline[] = $row;
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
                'run_mode' => in_array($r['mode'] ?? '', ['loop', 'orders'], true) ? $r['mode'] : 'once',
                // chỉ kịch bản NHẬN ĐƠN mới phục vụ một pool; mã pool lưu nguyên như tool khai (pool có thể chưa tồn tại — trang quản trị sẽ nói rõ)
                'pool_code' => ($r['mode'] ?? '') === 'orders' ? (strtolower(clean($r['pool'] ?? '', 40)) ?: null) : null,
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

    /**
     * mã pool → các kịch bản NHẬN ĐƠN (do tool khai) đang phục vụ pool đó, kèm số máy đang rảnh ở kịch bản ấy ngay lúc này.
     * @return array<string, list<array{name: string, tool: string, idle: int, fresh: bool}>>
     */
    public static function scriptsByPool(): array
    {
        if (Schema::version() < 4) {
            return [];
        }
        $out = [];
        foreach (self::board() as $t) {
            foreach ($t['scripts'] as $s) {
                if ($s['run_mode'] === 'orders' && (string) ($s['pool_code'] ?? '') !== '') {
                    $out[$s['pool_code']][] = ['name' => $s['name'], 'tool' => $t['key']['name'], 'idle' => count($s['idle']), 'fresh' => $t['fresh']];
                }
            }
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

/* ====================== Money: số tiền là SỐ NGUYÊN = số tiền × 100 ====================== */
final class Money
{
    /** Loại tiền không có phần lẻ khi hiển thị (cùng danh sách với notify.ZERO_DECIMAL của tool). */
    public const ZERO_DECIMAL = ['JPY', 'KRW', 'VND', 'IDR', 'CLP', 'TWD', 'HUF', 'ISK'];
    /** trần an toàn của một số tiền (×100) — xa giới hạn BIGINT, đủ cho mọi ví thật */
    public const MAX = 100000000000000;

    /** Mã tiền ISO-4217 viết hoa (vd «jpy » → «JPY»), sai → null. */
    public static function currency(mixed $v): ?string
    {
        $c = is_scalar($v) ? strtoupper(trim((string) $v)) : '';
        return preg_match('/^[A-Z]{3}$/D', $c) === 1 ? $c : null;
    }

    public static function decimals(string $cur): int
    {
        return in_array(strtoupper($cur), self::ZERO_DECIMAL, true) ? 0 : 2;
    }

    /** Để hiện: 150000 JPY → «1.500 JPY»; 6350 CHF → «63,50 CHF» (cùng cách viết với thông báo của tool). */
    public static function fmt(?int $x100, string $cur, bool $withCur = true): string
    {
        if ($x100 === null) {
            return '—';
        }
        $v = abs($x100);
        $s = number_format(intdiv($v, 100), 0, ',', '.');
        if (self::decimals($cur) > 0) {
            $s .= ',' . str_pad((string) ($v % 100), 2, '0', STR_PAD_LEFT);
        }
        return ($x100 < 0 ? '-' : '') . $s . ($withCur && $cur !== '' ? ' ' . $cur : '');
    }

    /** Để điền sẵn vào ô nhập (không dấu nghìn): 150000 JPY → «1500»; 6350 CHF → «63.50». */
    public static function plain(int $x100, string $cur): string
    {
        $v = abs($x100);
        $s = (string) intdiv($v, 100);
        if (self::decimals($cur) > 0) {
            $s .= '.' . str_pad((string) ($v % 100), 2, '0', STR_PAD_LEFT);
        }
        return ($x100 < 0 ? '-' : '') . $s;
    }

    /** Chữ giá MẪU như App Store vùng đó hiển thị (gợi ý cho ô «chữ hiện trên máy») — chỉ để gợi ý, không dùng để tính. */
    public static function example(string $cur): string
    {
        $map = ['JPY' => '¥1,500', 'CHF' => 'CHF 63.00', 'DKK' => '63,00 kr', 'SEK' => '63,00 kr', 'NOK' => 'kr 63,00', 'USD' => '$9.99',
                'EUR' => '9,99 €', 'GBP' => '£9.99', 'VND' => '249.000đ', 'KRW' => '₩12,000', 'AUD' => '$14.99', 'CAD' => '$12.99',
                'SGD' => 'S$13.98', 'HKD' => 'HK$78.00', 'TWD' => 'NT$300', 'THB' => '฿349.00', 'IDR' => 'Rp 159.000', 'CNY' => '¥68'];
        return $map[strtoupper($cur)] ?? ('vd: 9.99 ' . strtoupper($cur));
    }

    /**
     * Chữ admin nhập → số tiền ×100; sai → null. Nhận «1500», «1.500», «1,500.50», «1.500,50», «63.5», «63,50».
     * Chỉ MỘT dấu chấm / phẩy kèm 1–2 chữ số sau nó = phần lẻ; nhóm đúng 3 chữ số = dấu nghìn.
     * Loại tiền không có phần lẻ (JPY…) mà nhập phần lẻ khác 0 → sai. $signed: cho phép dấu − ở đầu (chỉnh số dư).
     */
    public static function parse(mixed $raw, string $cur, bool $signed = false): ?int
    {
        $s = is_scalar($raw) ? str_replace([' ', "\u{00A0}", "\u{202F}", "'", '_'], '', trim((string) $raw)) : '';
        $neg = false;
        if ($s !== '' && ($s[0] === '-' || $s[0] === '+')) {
            if (!$signed) {
                return null;                                  // số tiền không dấu (nạp thêm, giá gói): không nhận cả «+»
            }
            $neg = $s[0] === '-';
            $s = substr($s, 1);
        }
        if (preg_match('/^\d[\d.,]*\d$|^\d$/D', $s) !== 1) {
            return null;
        }
        $dot = strrpos($s, '.');
        $comma = strrpos($s, ',');
        $int = $s;
        $frac = '';
        if ($dot !== false && $comma !== false) {
            $pos = max($dot, $comma);                     // dấu đứng sau cùng là dấu thập phân, dấu kia là dấu nghìn
            $int = substr($s, 0, $pos);
            $frac = substr($s, $pos + 1);
            if (str_contains($int, $s[$pos])) {
                return null;
            }
        } elseif ($dot !== false || $comma !== false) {
            $parts = explode($dot !== false ? '.' : ',', $s);
            if (count($parts) === 2 && strlen($parts[1]) <= 2) {
                [$int, $frac] = $parts;
            } else {
                foreach (array_slice($parts, 1) as $g) {
                    if (strlen($g) !== 3) {
                        return null;
                    }
                }
            }
        }
        $int = str_replace(['.', ','], '', $int);
        if ($int === '' || strlen($int) > 13 || strlen($frac) > 2 || !ctype_digit($int) || ($frac !== '' && !ctype_digit($frac))) {
            return null;
        }
        $cents = (int) str_pad($frac, 2, '0');
        if ($cents !== 0 && self::decimals($cur) === 0) {
            return null;
        }
        $v = (int) $int * 100 + $cents;
        if ($v > self::MAX) {
            return null;
        }
        return $neg ? -$v : $v;
    }
}

/* ====================== Wallets: ví của tài khoản Apple trên từng máy ====================== */
/**
 * Mỗi máy nạp (khoá Tool + tên máy) đăng nhập MỘT tài khoản Apple để trả tiền mua gói; số dư của tài khoản đó do admin khai và
 * gateway tự trừ theo đơn. Máy CÓ ví đang dùng thì chỉ nhận đơn mà ví đủ tiền (theo giá gói ở đúng loại tiền của ví); máy không
 * có ví thì nhận đơn như cũ, không kiểm gì.
 *
 * SỔ CÁI (wallet_entries) chỉ ghi thêm, mỗi dòng là một việc:
 *   topup / adjust  — admin nạp thêm / chỉnh số dư (đổi số dư)
 *   purchase        — đơn xong: trừ đúng số gói đã mua × đơn giá LÚC GIAO ĐƠN (đổi số dư)
 *   hold            — đơn sang chờ đối soát: TẠM GIỮ cả chi phí đơn. amount âm nhưng KHÔNG đổi số dư (balance_after = số dư lúc đó)
 *   charge          — admin chốt «đã nạp»: trừ số tiền admin nhập (đổi số dư); tạm giữ đóng lại
 *   release         — admin chốt «chưa nạp»: nhả tạm giữ (amount 0, không đổi số dư)
 *   refund          — admin đổi đơn đã trừ tiền sang «thất bại»: cộng lại đúng số đã trừ của đơn (đổi số dư)
 * Tạm giữ ĐANG MỞ = các dòng hold của những đơn còn wallet_state='held' (chốt xong thì jobs.wallet_state đổi → tự đóng).
 *   Còn dùng được = số dư − tổng tạm giữ đang mở.
 * jobs.wallet_state: NULL (đang chạy, chưa tính tiền) → charged | none (failed, không trừ) | held → charged | released.
 * Mọi bước đổi wallet_state đều là UPDATE có điều kiện → báo muộn / bấm hai lần không bao giờ trừ tiền hai lần.
 */
final class Wallets
{
    public const KINDS = [
        'topup'    => ['Nạp tiền', 'success'],
        'purchase' => ['Mua gói', 'info'],
        'hold'     => ['Tạm giữ', 'warning'],
        'release'  => ['Nhả tạm giữ', 'secondary'],
        'charge'   => ['Trừ khi đối soát', 'primary'],
        'adjust'   => ['Chỉnh số dư', 'danger'],
        'refund'   => ['Hoàn tiền đơn', 'success'],
    ];
    /** các loại dòng sổ cái làm ĐỔI số dư (hold / release chỉ ghi lại việc giữ / nhả) */
    private const MOVES = ['topup', 'purchase', 'charge', 'adjust', 'refund'];
    public const STATE = [
        'held'     => ['đang tạm giữ', 'warning'],
        'charged'  => ['đã trừ tiền', 'success'],
        'released' => ['đã nhả tạm giữ', 'secondary'],
        'none'     => ['không trừ tiền', 'secondary'],
    ];

    /** CSDL đã có bảng ví (migration 5). Mã mới chạy trên CSDL cũ thì mọi thứ về ví coi như tắt. */
    public static function enabled(): bool
    {
        return Schema::version() >= 5;
    }

    /** a***@example.com — tài khoản Apple gửi cho tool / ghi vào nhật ký đơn. */
    public static function mask(string $acc): string
    {
        $acc = trim($acc);
        $at = mb_strrpos($acc, '@');
        if ($at !== false && $at > 0) {
            return mb_substr($acc, 0, 1) . '***' . mb_substr($acc, $at);
        }
        $len = mb_strlen($acc);
        return $len <= 4 ? str_repeat('*', $len) : mb_substr($acc, 0, 2) . '***' . mb_substr($acc, -2);
    }

    public static function find(int $id): ?array
    {
        return self::enabled() ? Db::one('SELECT w.*, k.name AS key_name FROM wallets w LEFT JOIN api_keys k ON k.id=w.tool_key_id WHERE w.id=?', [$id]) : null;
    }

    /** Ví đang dùng của một máy, hoặc null. */
    public static function active(int $keyId, string $device): ?array
    {
        return Db::one('SELECT * FROM wallets WHERE tool_key_id=? AND device=? AND active=1 ORDER BY id DESC LIMIT 1', [$keyId, $device]);
    }

    /** Tổng tạm giữ đang mở của ví (số dương, ×100). */
    public static function held(int $walletId): int
    {
        return -(int) Db::val("SELECT COALESCE(SUM(e.amount), 0) FROM wallet_entries e JOIN jobs j ON j.id=e.job_id
                               WHERE e.wallet_id=? AND e.kind='hold' AND j.wallet_id=e.wallet_id AND j.wallet_state='held'", [$walletId]);
    }

    public static function available(array $w): int
    {
        return (int) $w['balance'] - self::held((int) $w['id']);
    }

    /** Mọi ví (kèm tên khoá Tool, tạm giữ, còn dùng được, lần ghi sổ cuối), xếp theo máy. */
    public static function all(): array
    {
        if (!self::enabled()) {
            return [];
        }
        $rows = Db::all('SELECT w.*, k.name AS key_name, (SELECT MAX(e.at) FROM wallet_entries e WHERE e.wallet_id=w.id) AS last_at,
                                (SELECT COUNT(*) FROM devices d WHERE d.tool_key_id=w.tool_key_id AND d.name=w.device) AS device_seen
                         FROM wallets w LEFT JOIN api_keys k ON k.id=w.tool_key_id ORDER BY k.name, w.tool_key_id, w.device, w.active DESC, w.id DESC');
        foreach ($rows as &$r) {
            $r['held'] = self::held((int) $r['id']);
            $r['available'] = (int) $r['balance'] - $r['held'];
        }
        unset($r);
        return $rows;
    }

    /** Ví (do tool quản lý) đang dùng mà «còn dùng được» thấp hơn giá gói đắt nhất đang bán ở đúng loại tiền — cho trang Tổng quan. */
    public static function low(): array
    {
        $out = [];
        foreach (ToolWallets::all() as $w) {
            if (!(int) $w['active']) {
                continue;
            }
            $avail = (int) $w['balance'] - (int) $w['held'] + (int) $w['pending_effect'];
            $max = Db::val('SELECT MAX(pp.amount) FROM package_prices pp JOIN packages p ON p.id=pp.package_id JOIN pools o ON o.id=p.pool_id
                            WHERE pp.currency=? AND p.active=1 AND o.active=1', [$w['currency']]);
            if ($max !== null && $avail < (int) $max) {
                $out[] = $w + ['available' => $avail, 'need' => (int) $max];
            }
        }
        return $out;
    }

    /** Ghi MỘT dòng sổ cái (đổi số dư nếu là loại đổi số dư). Trả số dư sau đó. */
    public static function entry(int $walletId, string $kind, int $amount, string $actor, string $note = '', ?array $job = null, ?string $code = null, ?int $qty = null): int
    {
        if (!isset(self::KINDS[$kind])) {
            throw new InvalidArgumentException('kind');
        }
        return Db::tx(static function () use ($walletId, $kind, $amount, $actor, $note, $job, $code, $qty): int {
            $now = time();
            // ghi vào dòng ví TRƯỚC (giữ quyền ghi), rồi mới đọc số dư sau đó
            Db::run('UPDATE wallets SET balance=balance+?, updated_at=? WHERE id=?', [in_array($kind, self::MOVES, true) ? $amount : 0, $now, $walletId]);
            $bal = (int) Db::val('SELECT balance FROM wallets WHERE id=?', [$walletId]);
            Db::insert('wallet_entries', [
                'wallet_id' => $walletId, 'at' => $now, 'kind' => $kind, 'amount' => $amount, 'balance_after' => $bal,
                'job_id' => $job ? (int) $job['id'] : null, 'job_pid' => $job['pid'] ?? null, 'package_code' => $code, 'qty' => $qty,
                'note' => clean($note, 300), 'actor' => mb_substr($actor, 0, 40),
            ]);
            return $bal;
        });
    }

    public static function entries(int $walletId, int $limit, int $offset): array
    {
        return Db::all('SELECT e.*, j.id AS jid FROM wallet_entries e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.wallet_id=? ORDER BY e.id DESC LIMIT '
            . max(1, min(500, $limit)) . ' OFFSET ' . max(0, $offset), [$walletId]);
    }

    public static function forJob(int $jobId): array
    {
        return self::enabled() ? Db::all('SELECT * FROM wallet_entries WHERE job_id=? ORDER BY id', [$jobId]) : [];
    }

    /**
     * Chi phí của một đơn đang chờ nếu giao cho ví này, theo giá HIỆN TẠI của các gói ở loại tiền của ví.
     * Trả ['cost' => tổng ×100, 'items' => ảnh chụp gói kèm price / currency / price_display, 'missing' => mã gói chưa có giá loại tiền này].
     */
    public static function quote(array $job, array $w, bool $needDisplay = false): array
    {
        $cur = (string) $w['currency'];
        $items = jdec($job['items']);
        $cost = 0;
        $missing = [];
        foreach ($items as &$it) {
            $code = (string) ($it['code'] ?? '');
            $p = Db::one('SELECT pp.amount, pp.display FROM packages p JOIN package_prices pp ON pp.package_id=p.id AND pp.currency=? WHERE p.pool_id=? AND p.code=?',
                [$cur, $job['pool_id'], $code]);
            if (!$p || ($needDisplay && trim((string) $p['display']) === '')) {
                $missing[] = $code;                       // ví của tool: tool phải KHỚP chữ giá trên ô gói → thiếu chữ giá cũng là chưa có giá
                continue;
            }
            $it['price'] = (int) $p['amount'];
            $it['currency'] = $cur;
            $it['price_display'] = (string) $p['display'];
            $cost += (int) ($it['qty'] ?? 1) * (int) $p['amount'];
        }
        unset($it);
        return ['cost' => $cost, 'items' => $items, 'missing' => $missing];
    }

    /**
     * Có đơn nhưng không đơn nào giao được cho ví này → lời báo cho tool (`wallet_short`).
     * $skipped = ['insufficient' => [quote…], 'no_price' => [quote…]]. Ưu tiên báo thiếu tiền (nạp thêm là xử lý được ngay).
     */
    public static function short(array $w, int $available, array $skipped): array
    {
        if ((int) ($w['short_notified_at'] ?? 0) < time() - 600) {      // ghi tối đa 10 phút một lần (không ghi CSDL ở mỗi lần máy hỏi đơn)
            Db::run('UPDATE wallets SET short_notified_at=? WHERE id=?', [time(), $w['id']]);
        }
        return self::shortInfo(['account' => self::mask((string) $w['apple_account']), 'currency' => $w['currency'], 'available' => $available], $skipped);
    }

    /** Lời báo «ví không trả được đơn nào» từ các đơn bị bỏ qua (dùng cho cả ví gateway lẫn ví của tool). */
    public static function shortInfo(array $base, array $skipped): array
    {
        if (!empty($skipped['insufficient'])) {
            $list = $skipped['insufficient'];
            usort($list, static fn (array $a, array $b): int => $a['cost'] <=> $b['cost']);
            $codes = array_values(array_unique(array_map(static fn ($i) => (string) ($i['code'] ?? ''), $list[0]['items'])));
            return ['reason' => 'insufficient'] + $base + ['need' => $list[0]['cost'], 'package_codes' => $codes];
        }
        $codes = [];
        foreach ($skipped['no_price'] ?? [] as $q) {
            foreach ($q['missing'] as $c) {
                if (!in_array($c, $codes, true)) {
                    $codes[] = $c;
                }
            }
        }
        return ['reason' => 'no_price'] + $base + ['need' => null, 'package_codes' => $codes];
    }

    /** Ví của đơn nhìn từ tool (để ghi nhật ký máy): tài khoản đã che, số dư, còn dùng được. */
    public static function toolView(array $job): ?array
    {
        $w = !empty($job['wallet_id']) ? self::find((int) $job['wallet_id']) : null;
        if (!$w) {
            return null;
        }
        return ['account' => self::mask((string) $w['apple_account']), 'currency' => $w['currency'], 'balance' => (int) $w['balance'], 'available' => self::available($w)];
    }

    /**
     * Tool báo kết quả / hệ thống chuyển đơn sang đối soát → tính tiền của đơn (gọi TRONG giao dịch đổi trạng thái đơn).
     * $new: done | failed | review. $reported: kết quả từng gói tool gửi ({code, qty_done}); rỗng khi done = đã mua đủ.
     */
    public static function settle(array $job, string $new, array $reported, string $actor): void
    {
        if (ToolWallets::isToolJob($job)) {
            ToolWallets::settle($job, $new, $reported, $actor);
            return;
        }
        if (empty($job['wallet_id'])) {
            return;
        }
        $state = $new === 'done' ? 'charged' : ($new === 'failed' ? 'none' : 'held');
        if (Db::run('UPDATE jobs SET wallet_state=? WHERE id=? AND wallet_state IS NULL', [$state, $job['id']])->rowCount() !== 1) {
            return;                                             // đã tính rồi (báo muộn / gửi lại) → không ghi thêm gì
        }
        $wid = (int) $job['wallet_id'];
        if ($state === 'held') {
            self::entry($wid, 'hold', -(int) $job['cost'], $actor, 'Tạm giữ cả chi phí đơn trong lúc chờ đối soát', $job);
            return;
        }
        if ($state !== 'charged') {
            return;
        }
        $done = [];
        foreach ($reported as $r) {
            $c = (string) ($r['code'] ?? '');
            $done[$c] = ($done[$c] ?? 0) + max(0, (int) ($r['qty_done'] ?? 0));
        }
        foreach (jdec($job['items']) as $it) {
            $code = (string) ($it['code'] ?? '');
            $qty = (int) ($it['qty'] ?? 1);
            // gateway chỉ cho mua đúng số lượng của đơn → số tool báo vượt quá thì tính theo số lượng của đơn
            $n = $reported ? min($qty, $done[$code] ?? 0) : $qty;
            if ($n > 0 && isset($it['price'])) {
                self::entry($wid, 'purchase', -$n * (int) $it['price'], $actor, 'Mua ' . ($it['name'] ?? $code), $job, $code, $n);
            }
        }
    }

    /** Admin chốt đơn đang TẠM GIỮ ví (gọi TRONG giao dịch chốt đơn): done → trừ $charge; failed → nhả. */
    public static function resolve(array $job, string $to, int $charge, string $note, string $actor): void
    {
        if (ToolWallets::isToolJob($job)) {
            ToolWallets::resolve($job, $to, $charge, $note, $actor);
            return;
        }
        $state = $to === 'done' ? 'charged' : 'released';
        if (Db::run("UPDATE jobs SET wallet_state=? WHERE id=? AND wallet_state='held'", [$state, $job['id']])->rowCount() !== 1) {
            return;
        }
        if ($state === 'charged') {
            self::entry((int) $job['wallet_id'], 'charge', -$charge, $actor, $note !== '' ? $note : 'Admin chốt «đã nạp» — trừ tiền đơn', $job);
        } else {
            self::entry((int) $job['wallet_id'], 'release', 0, $actor, $note !== '' ? $note : 'Admin chốt «chưa nạp» — nhả tạm giữ', $job);
        }
    }
}

/* ====================== Ví do TOOL quản lý ====================== */
/**
 * Từ migration 6, ví của từng máy (tài khoản Apple + loại tiền + số dư + sổ) do TOOL giữ — nguồn gốc là tool. Gateway:
 *  - khi máy xin đơn, nhận «loại tiền + còn dùng được» tool gửi kèm, trừ đi các khoản tool CHƯA nhận (sự kiện chưa ack) rồi chỉ giao
 *    đơn vừa túi, định giá theo đúng loại tiền đó (đơn ghi currency + cost, wallet_id để trống = ví của tool);
 *  - tiền của đơn (mua / tạm giữ / admin chốt / hoàn) ghi thành SỰ KIỆN cho tool (tool_wallet_events); tool nhận qua /api/tool/sync,
 *    áp vào sổ của nó (mỗi sự kiện một lần, theo id) rồi báo đã nhận ở lần sync sau;
 *  - giữ BẢN SAO ví tool báo lên (tool_wallets) để admin xem — không sửa ở gateway.
 * Ví cũ khai ở gateway (bảng wallets, trước migration 6) không còn áp khi giao đơn mới — chỉ còn để tra sổ và cho các đơn đã giao theo nó.
 */
final class ToolWallets
{
    public const KINDS = [
        'purchase' => ['Mua gói', 'info'],
        'hold'     => ['Tạm giữ', 'warning'],
        'release'  => ['Nhả tạm giữ', 'secondary'],
        'charge'   => ['Trừ khi đối soát', 'primary'],
        'refund'   => ['Hoàn tiền đơn', 'success'],
    ];

    public static function enabled(): bool
    {
        return Schema::version() >= 6;
    }

    /** Đơn trả bằng ví của TOOL: có loại tiền + chi phí nhưng không gắn ví gateway. */
    public static function isToolJob(array $job): bool
    {
        return self::enabled() && empty($job['wallet_id']) && (string) ($job['currency'] ?? '') !== '' && !empty($job['tool_key_id'])
            && (string) ($job['device'] ?? '') !== '';
    }

    public static function event(array $job, string $kind, int $dBalance, int $dHeld, string $actor, string $note = '', ?string $code = null, ?int $qty = null): void
    {
        Db::insert('tool_wallet_events', [
            'tool_key_id' => (int) $job['tool_key_id'], 'device' => (string) $job['device'], 'job_id' => (int) $job['id'], 'job_pid' => $job['pid'],
            'kind' => $kind, 'currency' => (string) $job['currency'], 'd_balance' => $dBalance, 'd_held' => $dHeld,
            'package_code' => $code, 'qty' => $qty, 'note' => clean($note, 300), 'actor' => mb_substr($actor, 0, 40), 'created_at' => time(),
        ]);
    }

    /**
     * Ảnh hưởng tới «còn dùng được» của các sự kiện tool CHƯA áp vào sổ (âm = tool đang báo dư so với thật). `$applied` = id tool báo đã áp
     * (gửi kèm khi xin đơn): bỏ qua dù gateway chưa nhận lời «đã áp» — tool đã tính chúng trong con số nó gửi.
     */
    public static function pendingEffect(int $keyId, string $device, string $currency, array $applied = []): int
    {
        $sql = 'SELECT COALESCE(SUM(d_balance - d_held), 0) FROM tool_wallet_events WHERE tool_key_id=? AND device=? AND currency=? AND acked_at IS NULL';
        $args = [$keyId, $device, $currency];
        $ids = array_values(array_unique(array_filter($applied, static fn ($v) => is_int($v) && $v > 0)));
        if ($ids) {
            // lúc xin đơn (tool gửi kèm id đã áp): tính cả sự kiện VỪA được báo «đã áp» (2 phút) mà không có trong danh sách — tool chụp số dư
            // trước khi áp nó (lời xin đơn còn trên đường) → không bên nào tính thì giao đơn quá tiền
            $sql = 'SELECT COALESCE(SUM(d_balance - d_held), 0) FROM tool_wallet_events WHERE tool_key_id=? AND device=? AND currency=? AND (acked_at IS NULL OR acked_at>?)'
                 . ' AND id NOT IN (' . implode(',', array_fill(0, count($ids), '?')) . ')';
            $args = array_merge([$keyId, $device, $currency, time() - 120], $ids);
        }
        return (int) Db::val($sql, $args);
    }

    /** Sự kiện chưa nhận của một khoá Tool (gửi trong phản hồi sync), cũ trước. */
    public static function pending(int $keyId, int $limit = 200): array
    {
        $out = [];
        foreach (Db::all('SELECT * FROM tool_wallet_events WHERE tool_key_id=? AND acked_at IS NULL ORDER BY id LIMIT ' . max(1, min(500, $limit)), [$keyId]) as $e) {
            $out[] = ['id' => (int) $e['id'], 'device' => $e['device'], 'job' => $e['job_pid'], 'kind' => $e['kind'], 'currency' => $e['currency'],
                      'd_balance' => (int) $e['d_balance'], 'd_held' => (int) $e['d_held'], 'package_code' => $e['package_code'],
                      'qty' => $e['qty'] !== null ? (int) $e['qty'] : null, 'note' => $e['note'], 'at' => iso((int) $e['created_at'])];
        }
        return $out;
    }

    /** Tool báo đã áp các sự kiện này. Chỉ đánh dấu sự kiện của CHÍNH khoá đó. */
    public static function ack(int $keyId, array $ids): void
    {
        $ids = array_values(array_unique(array_filter(array_map(static fn ($v) => is_int($v) || (is_string($v) && ctype_digit($v)) ? (int) $v : 0, $ids))));
        foreach (array_chunk($ids, 200) as $chunk) {
            Db::run('UPDATE tool_wallet_events SET acked_at=? WHERE tool_key_id=? AND acked_at IS NULL AND id IN (' . implode(',', array_fill(0, count($chunk), '?')) . ')',
                array_merge([time(), $keyId], $chunk));
        }
    }

    /** Kiểm danh sách ví tool báo lên → [danh sách sạch, null] hoặc [[], câu lỗi]. */
    public static function parseReport(mixed $raw): array
    {
        if (!is_array($raw) || !array_is_list($raw)) {
            return [[], 'wallets phải là một danh sách.'];
        }
        if (count($raw) > Tools::MAX_DEVICES) {
            return [[], 'Tối đa ' . Tools::MAX_DEVICES . ' ví cho một khoá Tool.'];
        }
        $out = [];
        foreach ($raw as $w) {
            $dev = is_array($w) ? clean($w['device'] ?? '', 80) : '';
            $cur = is_array($w) ? Money::currency($w['currency'] ?? '') : null;
            if ($dev === '' || $cur === null || isset($out[$dev])) {
                continue;
            }
            $num = static fn ($v): int => is_int($v) ? max(-Money::MAX, min(Money::MAX, $v)) : 0;
            $out[$dev] = ['device' => $dev, 'apple_account' => clean($w['apple_account'] ?? '', 160), 'currency' => $cur,
                          'balance' => $num($w['balance'] ?? 0), 'held' => max(0, $num($w['held'] ?? 0)), 'active' => !array_key_exists('active', $w) || $w['active'] === true,
                          'note' => clean($w['note'] ?? '', 200)];
        }
        return [array_values($out), null];
    }

    /** Bản sao ví = ảnh chụp TOÀN BỘ tool báo: có thì ghi, không còn thì xoá. */
    public static function saveReport(int $keyId, array $wallets, int $now): void
    {
        $keep = [];
        foreach ($wallets as $w) {
            $data = ['apple_account' => $w['apple_account'], 'currency' => $w['currency'], 'balance' => $w['balance'], 'held' => $w['held'],
                     'active' => $w['active'] ? 1 : 0, 'note' => $w['note'], 'reported_at' => $now];
            if (Db::update('tool_wallets', $data, 'tool_key_id=? AND device=?', [$keyId, $w['device']]) === 0) {
                try {
                    Db::insert('tool_wallets', ['tool_key_id' => $keyId, 'device' => $w['device']] + $data);
                } catch (Throwable $e) {
                    if (!Db::isDuplicate($e)) {
                        throw $e;
                    }
                }
            }
            $keep[$w['device']] = true;
        }
        foreach (Db::all('SELECT id, device FROM tool_wallets WHERE tool_key_id=?', [$keyId]) as $r) {
            if (!isset($keep[$r['device']])) {
                Db::run('DELETE FROM tool_wallets WHERE id=?', [$r['id']]);
            }
        }
    }

    /** Ví đang dùng (bản sao) của một máy, hoặc null. */
    public static function reported(int $keyId, string $device): ?array
    {
        return self::enabled() ? Db::one('SELECT * FROM tool_wallets WHERE tool_key_id=? AND device=?', [$keyId, $device]) : null;
    }

    /** Mọi ví tool báo (kèm tên khoá, số sự kiện tool chưa nhận) — cho trang quản trị. */
    public static function all(): array
    {
        if (!self::enabled()) {
            return [];
        }
        $rows = Db::all('SELECT w.*, k.name AS key_name FROM tool_wallets w LEFT JOIN api_keys k ON k.id=w.tool_key_id ORDER BY k.name, w.tool_key_id, w.device');
        foreach ($rows as &$r) {
            $r['pending'] = (int) Db::val('SELECT COUNT(*) FROM tool_wallet_events WHERE tool_key_id=? AND device=? AND acked_at IS NULL', [$r['tool_key_id'], $r['device']]);
            $r['pending_effect'] = self::pendingEffect((int) $r['tool_key_id'], (string) $r['device'], (string) $r['currency']);
        }
        unset($r);
        return $rows;
    }

    public static function forJob(int $jobId): array
    {
        return self::enabled() ? Db::all('SELECT * FROM tool_wallet_events WHERE job_id=? ORDER BY id', [$jobId]) : [];
    }

    public static function recent(int $limit = 100): array
    {
        return self::enabled() ? Db::all('SELECT e.*, k.name AS key_name FROM tool_wallet_events e LEFT JOIN api_keys k ON k.id=e.tool_key_id ORDER BY e.id DESC LIMIT '
            . max(1, min(500, $limit))) : [];
    }

    /**
     * Tiền của đơn ví-tool khi đơn đổi trạng thái (gọi TRONG giao dịch đổi trạng thái — như Wallets::settle):
     * done → mua (trừ đúng số gói đã mua × đơn giá lúc giao); review → tạm giữ cả chi phí; failed → không trừ.
     */
    public static function settle(array $job, string $new, array $reported, string $actor): void
    {
        $state = $new === 'done' ? 'charged' : ($new === 'failed' ? 'none' : 'held');
        if (Db::run('UPDATE jobs SET wallet_state=? WHERE id=? AND wallet_state IS NULL', [$state, $job['id']])->rowCount() !== 1) {
            return;
        }
        if ($state === 'held') {
            self::event($job, 'hold', 0, (int) $job['cost'], $actor, 'Tạm giữ cả chi phí đơn trong lúc chờ đối soát');
            return;
        }
        if ($state !== 'charged') {
            return;
        }
        $done = [];
        foreach ($reported as $r) {
            $c = (string) ($r['code'] ?? '');
            $done[$c] = ($done[$c] ?? 0) + max(0, (int) ($r['qty_done'] ?? 0));
        }
        foreach (jdec($job['items']) as $it) {
            $code = (string) ($it['code'] ?? '');
            $qty = (int) ($it['qty'] ?? 1);
            $n = $reported ? min($qty, $done[$code] ?? 0) : $qty;
            if ($n > 0 && isset($it['price'])) {
                self::event($job, 'purchase', -$n * (int) $it['price'], 0, $actor, 'Mua ' . ($it['name'] ?? $code), $code, $n);
            }
        }
    }

    /** Admin chốt đơn đang tạm giữ (trong giao dịch chốt): done → trừ $charge + đóng tạm giữ; failed → nhả. */
    public static function resolve(array $job, string $to, int $charge, string $note, string $actor): void
    {
        $state = $to === 'done' ? 'charged' : 'released';
        if (Db::run("UPDATE jobs SET wallet_state=? WHERE id=? AND wallet_state='held'", [$state, $job['id']])->rowCount() !== 1) {
            return;
        }
        if ($state === 'charged') {
            self::event($job, 'charge', -$charge, -(int) $job['cost'], $actor, $note !== '' ? $note : 'Admin chốt «đã nạp» — trừ tiền đơn');
        } else {
            self::event($job, 'release', 0, -(int) $job['cost'], $actor, $note !== '' ? $note : 'Admin chốt «chưa nạp» — nhả tạm giữ');
        }
    }

    /** Tổng đã trừ khỏi số dư cho đơn (số dương) — để hoàn khi admin đổi đơn đã trừ sang thất bại. */
    public static function charged(int $jobId): int
    {
        return -(int) Db::val("SELECT COALESCE(SUM(d_balance), 0) FROM tool_wallet_events WHERE job_id=? AND kind IN ('purchase','charge','refund')", [$jobId]);
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
        'admin'   => 'Admin chuyển sang đối soát',
    ];
    /** Admin đổi trạng thái tay: từ trạng thái nào được sang trạng thái nào (đơn chờ máy → huỷ; chờ đối soát → chốt — xem adminSetStatus). */
    public const MANUAL = [
        'queued'    => ['cancelled'],
        'claimed'   => ['review'], 'running' => ['review'], 'need_otp' => ['review'],
        'review'    => ['done', 'failed'],
        'done'      => ['failed'],
        'failed'    => ['done'], 'expired' => ['done'], 'cancelled' => ['done'],
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
                // đơn giao cho máy có ví: chữ giá ĐÚNG vùng App Store của tài khoản Apple trên máy (chụp lúc giao đơn) để tool dò đúng ô gói
                $row['price_text'] = (string) ($it['price_display'] ?? '') !== '' ? (string) $it['price_display'] : ($it['price_text'] ?? '');
                $row['limit_type'] = $it['limit_type'] ?? 'multi';
                if (isset($it['price'])) {
                    $row['price'] = (int) $it['price'];                 // đơn giá ×100 theo loại tiền của ví
                    $row['currency'] = (string) ($it['currency'] ?? '');
                }
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
        if ($forTool && !empty($job['wallet_id']) && ($w = Wallets::toolView($job))) {
            $out['wallet'] = $w;
        } elseif ($forTool && ToolWallets::isToolJob($job)) {
            $out['wallet'] = ['source' => 'tool', 'currency' => (string) $job['currency'], 'cost' => (int) $job['cost']];     // tiền của đơn theo ví của tool
        }
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

    /** trạng thái tính là «tài khoản này đã / đang mua gói»: đơn thất bại / huỷ / quá hạn thì không tính (chưa mất tiền) */
    private const ONCE_LIVE = "('done','review','claimed','running','need_otp','queued')";

    /** Gói 1-lần nào trong $once mà tài khoản game ($accountKey, cùng pool) đã có ở một đơn khác còn hiệu lực. Trả dòng gói trùng hoặc null. */
    private static function boughtOnce(int $poolId, string $accountKey, array $once, int $exceptJob = 0): ?array
    {
        $want = [];
        foreach ($once as $it) {
            $want[(string) $it['code']] = $it;
        }
        foreach (Db::all('SELECT items FROM jobs WHERE pool_id=? AND account_key=? AND id<>? AND status IN ' . self::ONCE_LIVE, [$poolId, $accountKey, $exceptJob]) as $j) {
            foreach (jdec($j['items']) as $it) {
                $code = (string) ($it['code'] ?? '');
                if (isset($want[$code])) {
                    return $want[$code];
                }
            }
        }
        return null;
    }

    private static function alreadyBought(array $item): array
    {
        return self::err('already_bought', 'Tài khoản game này đã mua gói «' . $item['name'] . '» ở một đơn khác — gói chỉ mua được 1 lần / tài khoản.', ['code' => (string) $item['code']]);
    }

    /**
     * Kiểm + chuẩn hoá phần «khách gửi» của một đơn theo cấu hình pool: trường đăng nhập, gói nạp, định danh tài khoản game.
     * Dùng chung cho shop tạo đơn, admin tạo đơn thử và admin sửa đơn đang chờ.
     * @return array ['login','hint','items','account_key','once'] hoặc [mã HTTP, lỗi]
     */
    private static function prepare(array $pool, array $in): array
    {
        $cfg = $pool['cfg'];

        // --- trường đăng nhập theo cấu hình pool ---
        $loginIn = is_array($in['login'] ?? null) ? $in['login'] : [];
        $login = [];
        $hint = '';
        $identity = '';         // định danh tài khoản game (gói «1 lần / tài khoản») — xem dưới: ô chữ bắt buộc không bí mật đầu tiên
        $allIds = [];
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
            // Định danh TÀI KHOẢN GAME (cho gói «1 lần / tài khoản»): ô chữ BẮT BUỘC, không bí mật, không phải ô chọn (server / khu vực
            // là ô chọn — lấy nó làm định danh thì mọi khách cùng server bị coi là MỘT tài khoản và bị từ chối nhầm đơn đã trả tiền).
            if ($identity === '' && !$f['secret'] && $f['required'] && $f['type'] !== 'select' && trim($v) !== '') {
                $identity = mb_strtolower(trim($v));
            }
            if (!$f['secret'] && trim($v) !== '') {
                $allIds[] = $f['key'] . '=' . mb_strtolower(trim($v));
            }
        }
        if ($identity === '' && $allIds) {
            $identity = implode("\n", $allIds);        // pool không có ô chữ bắt buộc nào: dùng TẤT CẢ ô không bí mật (không gộp nhầm khách khác nhau)
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

        // --- gói «chỉ 1 lần / tài khoản»: mỗi tài khoản game của khách chỉ mua được MỘT lần (đơn thất bại / huỷ / quá hạn thì mua lại được) ---
        $accountKey = null;
        $once = array_values(array_filter($items, static fn (array $i): bool => $i['limit_type'] === 'once'));
        if (Wallets::enabled() && $identity !== '') {
            // chỉ lưu mã băm CÓ KHOÁ (HMAC bằng APP_KEY): CSDL lộ ra cũng không đoán ngược được email bằng cách thử từng email
            $accountKey = hash_hmac('sha256', $pool['id'] . ':' . $identity, 'account-key:' . (string) Env::get('APP_KEY', ''));
        }

        return ['login' => $login, 'hint' => $hint, 'items' => $items, 'account_key' => $accountKey, 'once' => $once];
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
        $prep = self::prepare($pool, $in);
        if (isset($prep[0])) {
            return $prep;
        }
        ['login' => $login, 'hint' => $hint, 'items' => $items, 'account_key' => $accountKey, 'once' => $once] = $prep;

        $now = time();
        $row = [
            'pid' => 'J' . strtoupper(Crypto::token(8)), 'pool_id' => $pool['id'], 'shop_key_id' => $key['id'], 'ref' => $ref,
            'status' => 'queued', 'stage' => 'queued', 'login_enc' => Crypto::enc(jenc($login)), 'account_hint' => $hint ?: null,
            'items' => jenc($items), 'note' => clean($in['note'] ?? '', 500) ?: null,
            'created_at' => $now, 'updated_at' => $now,
        ];
        if ($accountKey !== null) {
            $row['account_key'] = $accountKey;
        }
        try {
            if ($accountKey !== null && $once) {
                // Kiểm «đã mua gói 1 lần chưa» rồi ghi đơn trong MỘT giao dịch, sau khi khoá dòng pool (UPDATE không đổi gì nhưng giữ khoá ghi
                // — SQLite: khoá ghi cả CSDL; MySQL/InnoDB: khoá dòng tới khi chốt) → hai đơn khác ref cho cùng tài khoản + gói gửi cùng lúc
                // được xét LẦN LƯỢT: đúng một đơn được nhận. Chỉ đơn có gói 1-lần mới phải xếp hàng như vậy.
                $id = Db::tx(static function () use ($pool, $accountKey, $once, $row): int|array {
                    Db::run('UPDATE pools SET updated_at=updated_at WHERE id=?', [$pool['id']]);
                    $hit = self::boughtOnce((int) $pool['id'], $accountKey, $once);
                    return $hit ?? Db::insert('jobs', $row);
                });
                if (is_array($id)) {
                    return [422, self::alreadyBought($id)];
                }
            } else {
                $id = Db::insert('jobs', $row);
            }
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

        // VÍ của máy (tài khoản Apple trên máy) — chỉ giao đơn mà ví đủ tiền theo giá gói ở loại tiền của ví:
        //  (1) tool gửi kèm `wallet` {currency, available}: ví do TOOL quản lý. «Còn dùng được» trừ thêm các khoản tool CHƯA nhận (sự kiện
        //      chưa ack) — tool báo theo sổ của nó, có thể chưa kịp trừ đơn vừa xong. Gói phải có cả GIÁ lẫn CHỮ GIÁ ở loại tiền đó (tool
        //      khớp chữ giá trên ô gói).
        //  (2) không gửi: máy không có ví → không kiểm tiền. (Ví cũ khai ở gateway trước khi ví chuyển về tool chỉ còn để tra sổ — không áp
        //      nữa: gateway không còn nạp / chỉnh được chúng, áp tiếp thì máy kẹt «ví không đủ» mà không ai sửa được.)
        $toolWallet = null;
        if (ToolWallets::enabled() && array_key_exists('wallet', $in) && $in['wallet'] !== null) {
            $tw = is_array($in['wallet']) ? $in['wallet'] : [];
            $cur = Money::currency($tw['currency'] ?? '');
            $av = $tw['available'] ?? null;
            if ($cur === null || !is_int($av) || abs($av) > Money::MAX) {
                return [422, self::err('invalid_wallet', 'wallet phải là {currency: mã ISO 3 chữ, available: số nguyên ×100}.')];
            }
            $applied = is_array($tw['applied'] ?? null) ? array_slice(array_values($tw['applied']), -500) : [];
            $toolWallet = ['currency' => $cur, 'available' => $av + ToolWallets::pendingEffect((int) $key['id'], $device, $cur, $applied)];
        }
        $wallet = null;                                   // ví cũ của gateway: chỉ còn các đơn ĐÃ giao trước đó dùng (wallet_id), không giao đơn mới theo nó
        $priced = $toolWallet ?? $wallet;
        $available = $toolWallet ? $toolWallet['available'] : ($wallet ? Wallets::available($wallet) : 0);
        $since = $now - (int) $pool['cfg']['queue_ttl'];
        // có ví thì xét rộng hơn: đơn đầu hàng quá giá với ví này không được chặn mãi các đơn rẻ phía sau
        $cands = Db::all("SELECT id, pool_id, items FROM jobs WHERE pool_id=? AND status='queued' AND created_at>=? ORDER BY id LIMIT " . ($priced ? 300 : 5), [$pool['id'], $since]);   // máy có ví: xét cả hàng đợi (đơn đắt đứng đầu không chặn đơn rẻ phía sau)
        $skipped = [];
        foreach ($cands as $c) {
            $set = '';
            $args = [$device, $key['id'], $now, $now, $now];
            $q = null;
            if ($priced) {
                $q = Wallets::quote($c, $priced, $toolWallet !== null);
                if ($q['missing']) {
                    $skipped['no_price'][] = $q;          // gói chưa có giá ở loại tiền của ví → không biết có đủ tiền không
                    continue;
                }
                if ($q['cost'] > $available) {
                    $skipped['insufficient'][] = $q;
                    continue;
                }
                // chụp đơn giá lúc giao đơn vào items: admin sửa giá sau đó không làm đổi số tiền bị trừ của đơn này
                $set = ', wallet_id=?, currency=?, cost=?, items=?, wallet_state=NULL';
                array_push($args, $wallet ? $wallet['id'] : null, $priced['currency'], $q['cost'], jenc($q['items']));
            }
            $args[] = $c['id'];
            $cond = '';
            if ($priced) {
                // items vừa định giá phải CÒN NGUYÊN: admin sửa đơn (gói / số lượng) giữa lúc đọc và lúc ghi thì không ghi đè bản sửa bằng bản cũ —
                // bỏ qua đơn này ở lượt xin này, lượt sau định giá lại theo gói mới
                $cond = ' AND items=?';
                $args[] = $c['items'];
            }
            // UPDATE có điều kiện = khoá lạc quan: hai máy xin cùng lúc chỉ MỘT máy thắng
            $n = Db::run("UPDATE jobs SET status='claimed', stage='claimed', device=?, tool_key_id=?, claimed_at=?, seen_at=?, updated_at=?$set WHERE id=? AND status='queued'$cond",
                $args)->rowCount();
            if ($n === 1) {
                $job = self::byId((int) $c['id']);
                $acc = $wallet ? (string) $wallet['apple_account'] : (string) (ToolWallets::reported((int) $key['id'], $device)['apple_account'] ?? '');
                self::event((int) $job['id'], 'tool', 'claimed', 'Giao cho máy ' . $device . ' (' . $key['name'] . ')'
                    . ($priced ? ' — trả bằng ' . ($acc !== '' ? 'tài khoản Apple ' . Wallets::mask($acc) : 'ví của máy') . ($toolWallet ? ' (ví do tool quản lý)' : '')
                        . ', chi phí ' . Money::fmt($q['cost'], $priced['currency']) . ' (ví còn dùng được ' . Money::fmt($available, $priced['currency']) . ')' : ''));
                Devices::touch((int) $key['id'], $device, $pool['code'], 'busy', $job['pid']);
                Webhooks::enqueue($job, 'job.claimed');
                return [200, ['ok' => true, 'paused' => false, 'job' => self::view($job, true, true)]];
            }
        }
        if ($priced && $skipped) {
            // có đơn nhưng ví của máy này không trả được → đơn để máy khác nhận; tool báo admin nạp thêm tiền / khai giá
            return [200, ['ok' => true, 'paused' => false, 'job' => null,
                          'wallet_short' => $wallet ? Wallets::short($wallet, $available, $skipped) : Wallets::shortInfo(['currency' => $priced['currency'], 'available' => $available], $skipped)]];
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
            // kết thúc → XOÁ thông tin đăng nhập + OTP khỏi DB; đơn trả bằng ví thì tính tiền TRONG CÙNG giao dịch với việc đổi trạng thái
            $jid = (int) $job['id'];
            $n = Db::tx(static function () use ($new, $msg, $reason, $items, $now, $jid): int {
                $n = Db::run("UPDATE jobs SET status=?, stage=?, message=?, review_reason=?, result=?, login_enc=NULL, otp_enc=NULL, finished_at=?, seen_at=?, updated_at=?
                              WHERE id=? AND status IN " . self::IN_ACTIVE,
                    [$new, $new, $msg, $reason, $items ? jenc($items) : null, $new === 'review' ? null : $now, $now, $now, $jid])->rowCount();
                if ($n === 1 && Wallets::enabled()) {
                    Wallets::settle(self::byId($jid), $new, $items, 'tool');
                }
                return $n;
            });
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

    /**
     * Số tiền admin nhập khi chốt «đã nạp» một đơn đang TẠM GIỮ ví → [số tiền ×100, null] hoặc [null, câu lỗi].
     * Cho phép 0 (thực tế không mất tiền) tới 10 lần chi phí của đơn.
     */
    public static function chargeInput(array $job, string $raw): array
    {
        $cur = (string) $job['currency'];
        $cost = (int) $job['cost'];
        $v = Money::parse($raw, $cur);
        if ($v === null) {
            return [null, 'Số tiền đã trừ không hợp lệ — nhập số ≥ 0 theo ' . $cur . ' (vd ' . Money::plain($cost, $cur) . ').'];
        }
        if ($v > 10 * $cost) {
            return [null, 'Số tiền đã trừ (' . Money::fmt($v, $cur) . ') vượt quá 10 lần chi phí của đơn (' . Money::fmt($cost, $cur) . ').'];
        }
        return [$v, null];
    }

    /* ---------- ADMIN: chốt đơn chờ đối soát ---------- */
    /**
     * $charge: đơn đang tạm giữ ví mà chốt «đã nạp» → số tiền thật đã trừ (×100; null = đúng chi phí của đơn). Chốt «chưa nạp» → nhả tạm giữ.
     * $note: ghi vào sổ cái của ví (và nhật ký đơn).
     */
    public static function adminResolve(int $jobId, string $to, string $admin, ?int $charge = null, string $note = ''): bool
    {
        if (!in_array($to, ['done', 'failed'], true)) {
            return false;
        }
        $cur = self::byId($jobId);
        if (!$cur) {
            return false;
        }
        $held = Wallets::enabled() && ($cur['wallet_state'] ?? null) === 'held';
        if ($held && $to === 'done') {
            $charge ??= (int) $cur['cost'];
            if ($charge < 0 || $charge > 10 * (int) $cur['cost']) {
                return false;
            }
        }
        $note = clean($note, 300);
        $now = time();
        $n = Db::tx(static function () use ($to, $now, $jobId, $held, $charge, $note, $admin): int {
            $n = Db::run("UPDATE jobs SET status=?, stage=?, login_enc=NULL, otp_enc=NULL, finished_at=?, updated_at=? WHERE id=? AND status='review'",
                [$to, $to, $now, $now, $jobId])->rowCount();
            if ($n === 1 && $held) {
                Wallets::resolve(self::byId($jobId), $to, (int) $charge, $note, 'admin:' . $admin);
            }
            return $n;
        });
        if ($n !== 1) {
            return false;
        }
        $job = self::byId($jobId);
        $money = '';
        if ($held) {
            $money = $to === 'done' ? ' — trừ ví ' . Money::fmt((int) $charge, (string) $job['currency']) : ' — nhả tạm giữ của ví';
        }
        self::event($jobId, 'admin', 'resolved', $admin . ' chốt: ' . ($to === 'done' ? 'ĐÃ NẠP ĐỦ' : 'CHƯA NẠP') . $money . ($note !== '' ? ' (' . $note . ')' : ''));
        Devices::free($job['tool_key_id'] ? (int) $job['tool_key_id'] : null, $job['device']);
        Webhooks::enqueue($job, 'job.' . $to);
        return true;
    }

    /* ---------- ADMIN: đơn thử, xem / sửa / đổi trạng thái / xoá ---------- */

    /** Khoá «shop» nội bộ dùng cho đơn thử tạo từ trang quản trị (không có webhook → không báo cho shop thật nào). */
    public static function testKey(): array
    {
        $find = static function (): ?array {
            $id = (int) Settings::get('admin_test_key_id', '0');
            $k = $id ? Keys::find($id) : null;
            return $k && $k['kind'] === 'shop' ? $k : null;
        };
        $k = $find();
        if ($k) {
            return $k;
        }
        // hai admin tạo đơn thử ĐẦU TIÊN cùng lúc: khoá dòng cài đặt (tạo sẵn nếu chưa có) rồi xem lại trong giao dịch → chỉ MỘT khoá
        if (Settings::get('admin_test_key_id') === null) {
            Settings::set('admin_test_key_id', '0');
        }
        return Db::tx(static function () use ($find): array {
            Db::run("UPDATE settings SET v=v WHERE k='admin_test_key_id'");
            $k = $find();
            if ($k) {
                return $k;
            }
            $new = Keys::create('shop', 'Đơn thử (trang quản trị)');
            Settings::set('admin_test_key_id', (string) $new['id']);
            return Keys::find((int) $new['id']);
        });
    }

    /** Admin tạo đơn thử = một đơn THẬT (máy nhận đơn của pool sẽ nạp thật), mang khoá «Đơn thử». */
    public static function adminCreate(array $in, string $admin): array
    {
        $key = self::testKey();
        [$code, $res] = self::create($key, $in);
        if ($code === 201) {
            $job = self::forShop($key, (string) $res['job']['id']);
            $res['job_row_id'] = (int) $job['id'];
            self::event((int) $job['id'], 'admin', 'created', $admin . ' tạo đơn thử từ trang quản trị');
        }
        return [$code, $res];
    }

    /** Thông tin đăng nhập đã giải mã (null = đơn đã kết thúc, máy chủ đã xoá). Mỗi lần xem ghi nhật ký đơn (không ghi giá trị). */
    public static function adminLogin(int $id, string $admin): ?array
    {
        $job = self::byId($id);
        if (!$job || !$job['login_enc']) {
            return null;
        }
        $login = jdec(Crypto::dec($job['login_enc']));
        self::event($id, 'admin', 'login_viewed', $admin . ' xem thông tin đăng nhập của khách');
        return is_array($login) ? $login : [];
    }

    /**
     * Admin sửa đơn. Đơn CHỜ MÁY: sửa được mã đơn, thông tin đăng nhập (ô bí mật để trống = giữ nguyên), gói + số lượng, ghi chú.
     * Đơn đã giao máy / đã kết thúc: chỉ sửa ghi chú (máy đang làm theo dữ liệu cũ; tiền đã tính theo đơn cũ). Trả null hoặc câu lỗi.
     */
    public static function adminUpdate(int $id, array $in, string $admin): ?string
    {
        $job = self::byId($id);
        if (!$job) {
            return 'Không có đơn này.';
        }
        $note = clean($in['note'] ?? '', 500) ?: null;
        $full = array_key_exists('items', $in) || array_key_exists('login', $in) || array_key_exists('ref', $in);
        if (!$full) {
            if ($note !== $job['note']) {
                Db::run('UPDATE jobs SET note=?, updated_at=? WHERE id=?', [$note, time(), $id]);
                self::event($id, 'admin', 'edited', $admin . ' sửa ghi chú');
            }
            return null;
        }
        if ($job['status'] !== 'queued') {
            return 'Đơn đã giao cho máy / đã kết thúc — chỉ sửa được ghi chú.';
        }
        $pool = Pools::find((int) $job['pool_id']);
        if (!$pool) {
            return 'Pool của đơn không còn.';
        }
        $ref = is_scalar($in['ref'] ?? null) ? trim((string) $in['ref']) : (string) $job['ref'];
        if ($ref !== $job['ref'] && (int) $job['shop_key_id'] !== (int) Settings::get('admin_test_key_id', '0')) {
            // mã đơn là khoá chống tạo trùng của SHOP: đổi đi thì shop gửi lại (timeout → thử lại) sẽ tạo thêm một đơn thật
            return 'Chỉ đổi được mã của đơn thử — mã đơn của shop là khoá chống tạo trùng.';
        }
        if (preg_match('/^[A-Za-z0-9_.:\-]{1,80}$/', $ref) !== 1) {
            return 'Mã đơn gồm 1–80 ký tự chữ/số/_ . : -';
        }
        if ($ref !== $job['ref'] && Db::val('SELECT id FROM jobs WHERE shop_key_id=? AND ref=? AND id<>?', [$job['shop_key_id'], $ref, $id])) {
            return 'Shop này đã có đơn mã «' . $ref . '».';
        }
        // ô bí mật để trống = giữ giá trị cũ (form sửa không gửi lại mật khẩu cũ)
        $old = jdec(Crypto::dec($job['login_enc'])) ?: [];
        $loginIn = is_array($in['login'] ?? null) ? $in['login'] : $old;
        foreach ($pool['cfg']['login_fields'] as $f) {
            if ($f['secret'] && trim((string) ($loginIn[$f['key']] ?? '')) === '' && isset($old[$f['key']])) {
                $loginIn[$f['key']] = $old[$f['key']];
            }
        }
        $curItems = array_map(static fn (array $i): array => ['code' => (string) $i['code'], 'qty' => (int) $i['qty']], jdec($job['items']));
        $itemsIn = is_array($in['items'] ?? null) ? $in['items'] : $curItems;
        $norm = static function (array $list): array {
            $m = [];
            foreach ($list as $i) {
                if (is_array($i) && (int) ($i['qty'] ?? 0) > 0) {
                    $m[(string) ($i['code'] ?? '')] = ($m[(string) ($i['code'] ?? '')] ?? 0) + (int) $i['qty'];
                }
            }
            ksort($m);
            return $m;
        };
        if ($ref === $job['ref'] && $loginIn == $old && $norm($itemsIn) === $norm($curItems)) {
            // chỉ đổi ghi chú (vd gói của đơn vừa bị tắt nên không kiểm lại gói được) → không kiểm lại phần khác
            if ($note !== $job['note']) {
                Db::run("UPDATE jobs SET note=?, updated_at=? WHERE id=?", [$note, time(), $id]);
                self::event($id, 'admin', 'edited', $admin . ' sửa ghi chú');
            }
            return null;
        }
        $prep = self::prepare($pool, ['login' => $loginIn, 'items' => $itemsIn]);
        if (isset($prep[0])) {
            return (string) ($prep[1]['message'] ?? 'Dữ liệu đơn không hợp lệ.');
        }
        ['login' => $login, 'hint' => $hint, 'items' => $items, 'account_key' => $key, 'once' => $once] = $prep;
        $changed = [];
        if ($ref !== $job['ref']) { $changed[] = 'mã đơn ' . $job['ref'] . ' → ' . $ref; }
        if ($login != $old) { $changed[] = 'thông tin đăng nhập'; }
        if (jenc($items) !== (string) $job['items']) { $changed[] = 'gói nạp'; }
        if ($note !== $job['note']) { $changed[] = 'ghi chú'; }
        if (!$changed) {
            return null;
        }
        $row = ['ref' => $ref, 'login_enc' => Crypto::enc(jenc($login)), 'account_hint' => $hint ?: null, 'items' => jenc($items), 'note' => $note, 'updated_at' => time()];
        if (Wallets::enabled()) {
            $row['account_key'] = $key;
        }
        $res = Db::tx(static function () use ($id, $pool, $key, $once, $row): int|array {
            if ($key !== null && $once) {
                Db::run('UPDATE pools SET updated_at=updated_at WHERE id=?', [$pool['id']]);          // xếp hàng với shop đang tạo đơn (như create)
                $hit = self::boughtOnce((int) $pool['id'], $key, $once, $id);
                if ($hit) {
                    return $hit;
                }
            }
            $sets = implode(', ', array_map(static fn (string $c): string => $c . '=?', array_keys($row)));
            return Db::run('UPDATE jobs SET ' . $sets . " WHERE id=? AND status='queued'", array_merge(array_values($row), [$id]))->rowCount();
        });
        if (is_array($res)) {
            return 'Tài khoản game này đã mua gói «' . $res['name'] . '» ở một đơn khác — gói chỉ mua được 1 lần / tài khoản.';
        }
        if ($res !== 1) {
            return 'Đơn vừa được giao cho máy — không sửa được nữa (chỉ sửa ghi chú).';
        }
        self::event($id, 'admin', 'edited', $admin . ' sửa đơn: ' . implode(', ', $changed));
        return null;
    }

    /**
     * Admin đổi trạng thái tay (xem MANUAL). Tiền của ví tính theo trạng thái mới:
     *   đang chạy → chờ đối soát: tạm giữ cả chi phí (như tool im lặng); máy đang làm sẽ bị từ chối khi báo tiếp.
     *   chờ đối soát → hoàn tất / thất bại: như nút chốt đối soát ($charge = số tiền thật đã trừ).
     *   hoàn tất → thất bại: hoàn lại đúng số đã trừ của đơn.   thất bại / quá hạn / huỷ → hoàn tất: trừ $charge (đơn có ví).
     * Báo shop bằng webhook job.<trạng thái mới> (sửa trạng thái đã chốt thì kèm "corrected": true). Trả null hoặc câu lỗi.
     */
    public static function adminSetStatus(int $id, string $to, string $admin, ?int $charge = null, string $note = ''): ?string
    {
        $job = self::byId($id);
        if (!$job) {
            return 'Không có đơn này.';
        }
        $from = (string) $job['status'];
        if (!in_array($to, self::MANUAL[$from] ?? [], true)) {
            return 'Không đổi được từ «' . (self::LABEL[$from] ?? $from) . '» sang «' . (self::LABEL[$to] ?? $to) . '».';
        }
        if ($from === 'queued') {
            [$code] = self::cancel($job, 'admin');
            return $code === 200 ? null : 'Đơn vừa được giao cho máy, không huỷ được nữa.';
        }
        if ($from === 'review') {
            return self::adminResolve($id, $to, $admin, $charge, $note) ? null : 'Không chốt được (đơn không còn chờ đối soát, hoặc số tiền không hợp lệ).';
        }
        $note = clean($note, 300);
        $now = time();
        $tool = ToolWallets::isToolJob($job);                               // đơn trả bằng ví của TOOL → tiền đi thành sự kiện cho tool
        $wallet = (Wallets::enabled() && !empty($job['wallet_id'])) || $tool;
        $actor = 'admin:' . $admin;
        if ($to === 'review') {                                       // đang chạy → chờ đối soát
            $n = Db::tx(static function () use ($id, $now, $wallet): int {
                $n = Db::run("UPDATE jobs SET status='review', stage='review', review_reason='admin', login_enc=NULL, otp_enc=NULL, updated_at=? WHERE id=? AND status IN " . self::IN_ACTIVE,
                    [$now, $id])->rowCount();
                if ($n === 1 && $wallet) {
                    Wallets::settle(self::byId($id), 'review', [], 'system');
                }
                return $n;
            });
            if ($n !== 1) {
                return 'Đơn vừa đổi trạng thái — tải lại trang rồi thử lại.';
            }
            self::event($id, 'admin', 'status', $admin . ' chuyển đơn đang chạy sang CHỜ ĐỐI SOÁT' . ($note !== '' ? ' (' . $note . ')' : ''));
            Devices::free($job['tool_key_id'] ? (int) $job['tool_key_id'] : null, $job['device']);
            Webhooks::enqueue(self::byId($id), 'job.review');
            return null;
        }
        // sửa trạng thái ĐÃ CHỐT: hoàn tất ↔ thất bại
        $paid = $wallet && $to === 'done' && in_array($job['wallet_state'] ?? null, ['none', 'released'], true);
        if ($paid) {
            $charge ??= (int) $job['cost'];
            if ($charge < 0 || $charge > 10 * max(1, (int) $job['cost'])) {
                return 'Số tiền đã trừ không hợp lệ.';
            }
        }
        $refund = 0;
        $n = Db::tx(static function () use ($id, $from, $to, $now, $paid, $charge, &$refund, $wallet, $tool, $job, $note, $actor): int {
            $n = Db::run('UPDATE jobs SET status=?, stage=?, login_enc=NULL, otp_enc=NULL, finished_at=COALESCE(finished_at, ?), updated_at=? WHERE id=? AND status=?',
                [$to, $to, $now, $now, $id, $from])->rowCount();
            if ($n !== 1 || !$wallet) {
                return $n;
            }
            $cur = self::byId($id);
            if ($paid && Db::run("UPDATE jobs SET wallet_state='charged' WHERE id=? AND wallet_state IN ('none','released')", [$id])->rowCount() === 1) {
                $why = $note !== '' ? $note : 'Admin sửa đơn sang «hoàn tất» — trừ tiền đơn';
                $tool ? ToolWallets::event($cur, 'charge', -(int) $charge, 0, $actor, $why) : Wallets::entry((int) $job['wallet_id'], 'charge', -(int) $charge, $actor, $why, $cur);
            }
            if ($to === 'failed' && Db::run("UPDATE jobs SET wallet_state='none' WHERE id=? AND wallet_state='charged'", [$id])->rowCount() === 1) {
                // tính số đã trừ SAU khi giữ quyền ghi (trong cùng giao dịch) → không hoàn theo một con số đã cũ
                $refund = $tool ? ToolWallets::charged($id)
                    : -(int) Db::val("SELECT COALESCE(SUM(amount), 0) FROM wallet_entries WHERE job_id=? AND kind IN ('purchase','charge','refund')", [$id]);
                if ($refund > 0) {
                    $why = $note !== '' ? $note : 'Admin sửa đơn sang «thất bại» — hoàn lại tiền đã trừ';
                    $tool ? ToolWallets::event($cur, 'refund', $refund, 0, $actor, $why) : Wallets::entry((int) $job['wallet_id'], 'refund', $refund, $actor, $why, $cur);
                }
            }
            return $n;
        });
        if ($n !== 1) {
            return 'Đơn vừa đổi trạng thái — tải lại trang rồi thử lại.';
        }
        $money = $paid ? ' — trừ ví ' . Money::fmt((int) $charge, (string) $job['currency']) : ($refund > 0 ? ' — hoàn ví ' . Money::fmt($refund, (string) $job['currency']) : '');
        self::event($id, 'admin', 'status', $admin . ' sửa trạng thái: ' . self::LABEL[$from] . ' → ' . self::LABEL[$to] . $money . ($note !== '' ? ' (' . $note . ')' : ''));
        Webhooks::enqueue(self::byId($id), 'job.' . $to, ['corrected' => true, 'previous_status' => $from]);
        return null;
    }

    /**
     * Admin XOÁ HẲN đơn: đơn + ảnh (cả tệp) + nhật ký. Không xoá được đơn máy đang làm / chờ OTP, và đơn chờ đối soát còn tạm giữ ví.
     * Đơn còn chờ máy thì HUỶ trước (shop nhận job.cancelled — webhook đang chờ gửi được giữ lại). Dòng sổ cái của ví giữ nguyên
     * (còn mã đơn) để số dư không lệch. Trả null hoặc câu lỗi.
     */
    public static function adminDelete(int $id, string $admin): ?string
    {
        $job = self::byId($id);
        if (!$job) {
            return 'Không có đơn này.';
        }
        if (in_array($job['status'], self::ACTIVE, true)) {
            return 'Máy đang làm đơn này — chuyển sang «chờ đối soát» hoặc chờ máy báo kết quả rồi mới xoá.';
        }
        $walletOn = Wallets::enabled();
        if ($job['status'] === 'review') {
            // shop đang chờ kết quả cuối (được dặn không hoàn tiền trước job.done / job.failed) và ảnh là bằng chứng để đối soát
            return 'Đơn đang chờ đối soát — chốt «đã nạp» / «chưa nạp» trước (shop nhận kết quả cuối) rồi mới xoá.';
        }
        if ($job['status'] === 'queued') {
            [$code] = self::cancel($job, 'admin');
            if ($code !== 200) {
                return 'Đơn vừa được giao cho máy — không xoá được.';
            }
        }
        $images = [];
        $n = Db::tx(static function () use ($id, $walletOn, &$images): int {
            $n = Db::run('DELETE FROM jobs WHERE id=? AND status NOT IN ' . self::IN_ACTIVE . " AND status NOT IN ('queued','review')", [$id])->rowCount();
            if ($n !== 1) {
                return 0;
            }
            $images = Db::all('SELECT path FROM job_images WHERE job_id=?', [$id]);      // đọc SAU khi giữ quyền ghi: không sót ảnh vừa tải lên
            Db::run('DELETE FROM job_images WHERE job_id=?', [$id]);
            Db::run('DELETE FROM job_events WHERE job_id=?', [$id]);
            Db::run("DELETE FROM webhooks WHERE job_id=? AND status<>'pending'", [$id]);     // webhook chưa gửi (vd job.cancelled) vẫn gửi cho shop
            if ($walletOn) {
                Db::run('UPDATE wallet_entries SET job_id=NULL WHERE job_id=?', [$id]);       // còn job_pid → sổ cái vẫn biết của đơn nào
            }
            if (ToolWallets::enabled()) {
                Db::run('UPDATE tool_wallet_events SET job_id=NULL WHERE job_id=?', [$id]);   // sự kiện chưa gửi cho tool vẫn gửi (còn máy + mã đơn)
            }
            return 1;
        });
        if ($n !== 1) {
            return 'Đơn vừa đổi trạng thái — tải lại trang rồi thử lại.';
        }
        foreach ($images as $im) {
            Storage::delete((string) $im['path']);
        }
        return null;
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
                $jid = (int) $j['id'];
                $silent = $now - $cfg['silent_timeout'];
                // đơn trả bằng ví: chuyển sang đối soát = TẠM GIỮ cả chi phí đơn (cùng giao dịch)
                $n = Db::tx(static function () use ($now, $jid, $silent): int {
                    $n = Db::run("UPDATE jobs SET status='review', stage='review', review_reason='timeout', login_enc=NULL, otp_enc=NULL, updated_at=? WHERE id=? AND seen_at<? AND status IN " . self::IN_ACTIVE,
                        [$now, $jid, $silent])->rowCount();
                    if ($n === 1 && Wallets::enabled()) {
                        Wallets::settle(self::byId($jid), 'review', [], 'system');
                    }
                    return $n;
                });
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
