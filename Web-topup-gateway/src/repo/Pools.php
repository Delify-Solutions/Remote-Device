<?php
declare(strict_types=1);

final class Pools
{
    public const FIELD_TYPES = ['text' => 'Chữ', 'password' => 'Mật khẩu', 'textarea' => 'Nhiều dòng', 'select' => 'Danh sách chọn'];
    public const ALWAYS_SECRET = ['password', 'pass', 'pin', 'cookie', 'cookies', 'token', 'otp', 'backup_code', 'secret'];
    /**
     * BƯỚC ĐỜI CŨ. Trước đây bước thao tác soạn được cả ở pool trên gateway; giờ bước CHỈ soạn ở tool (kịch bản nhận đơn) và gateway không
     * còn chỗ soạn bước. Gateway chỉ GIỮ NGUYÊN các danh sách đã lưu từ trước (và của tệp dữ liệu mặc định đời cũ) để tool đời mới chép về
     * kịch bản đúng một lần; chép xong thì xoá bằng nút ở trang sửa pool (dropLegacySteps).
     */
    public const LEGACY_STEP_TYPES = ['launch', 'tap_text', 'tap', 'type', 'key', 'combo', 'home', 'wait', 'wait_text', 'assert_text', 'swipe', 'hold', 'hold_text'];
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
    /** Sáu danh sách bước đời cũ, theo đúng thứ tự máy chạy (xem LEGACY_STEP_TYPES). */
    public const LEGACY_STEP_LISTS = [
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
    public static function defaults(): array
    {
        return [
            'login_fields' => [
                ['key' => 'username', 'label' => 'Tài khoản', 'type' => 'text', 'required' => true, 'secret' => false, 'hint' => '', 'options' => []],
                ['key' => 'password', 'label' => 'Mật khẩu', 'type' => 'password', 'required' => true, 'secret' => true, 'hint' => '', 'options' => []],
            ],
            'otp' => ['enabled' => true, 'timeout' => 300, 'max_requests' => 3, 'hint' => 'Mã xác thực gửi về email / số điện thoại của tài khoản game.'],
            'rules' => [],
            'require_image' => true,
            'queue_ttl' => 1800,
            'silent_timeout' => 900,
            // loại tiền (vùng App Store) mà máy của pool dùng để trả tiền → mỗi gói có giá + chữ giá theo từng loại (bảng package_prices)
            'currencies' => [],
        ];
    }

    /** CSDL đã có giá gói theo loại tiền + mã băm tài khoản game của đơn (migration 5). Mã mới chạy trên CSDL cũ hơn thì coi như chưa có. */
    public static function priced(): bool
    {
        return Schema::version() >= 5;
    }

    /** «JPY, chf  KRW» → [['JPY','CHF','KRW'], null]; có mã sai → [[], 'lỗi']. */
    public static function parseCurrencies(string $raw): array
    {
        $out = [];
        foreach (preg_split('/[\s,;]+/', trim($raw), -1, PREG_SPLIT_NO_EMPTY) ?: [] as $c) {
            $cur = Money::currency($c);
            if ($cur === null) {
                return [[], 'Loại tiền «' . clean($c, 20) . '» không hợp lệ — gõ ký hiệu hoặc tên như máy hiện (vd ¥, kr, CHF): tối đa 6 ký tự chữ / ký hiệu tiền, không số, không khoảng trắng.'];
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

        // bước đời cũ: giữ nguyên trạng cái đang có; danh sách rỗng thì không còn khoá nào (pool mới không bao giờ có)
        foreach (array_keys(self::LEGACY_STEP_LISTS) as $list) {
            $steps = [];
            foreach ((array) ($in[$list] ?? []) as $s) {
                if (!is_array($s) || !in_array($s['type'] ?? '', self::LEGACY_STEP_TYPES, true)) {
                    continue;
                }
                // optional = «bỏ qua nếu lỗi»: bước không làm được thì máy đi tiếp (vd đóng một hộp thoại có thể không hiện)
                $steps[] = ['type' => (string) $s['type'], 'value' => clean($s['value'] ?? '', 300), 'note' => clean($s['note'] ?? '', 200),
                            'optional' => self::flag($s['optional'] ?? false)];
                if (count($steps) >= 80) {
                    break;
                }
            }
            if ($steps) {
                $out[$list] = $steps;
            }
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
        if ($id && ($cur = self::find($id))) {
            // form sửa pool không còn gửi bước lên: bước đời cũ đang lưu được GIỮ NGUYÊN qua mọi lần lưu (chỉ dropLegacySteps mới xoá)
            foreach (array_keys(self::LEGACY_STEP_LISTS) as $list) {
                if (!array_key_exists($list, $config) && isset($cur['cfg'][$list])) {
                    $config[$list] = $cur['cfg'][$list];
                }
            }
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

    /** Bước đời cũ pool còn lưu: [tên danh sách => số bước] (chỉ danh sách có bước). */
    public static function legacySteps(array $cfg): array
    {
        $out = [];
        foreach (array_keys(self::LEGACY_STEP_LISTS) as $list) {
            if (!empty($cfg[$list])) {
                $out[$list] = count($cfg[$list]);
            }
        }
        return $out;
    }

    /** Xoá hẳn các bước đời cũ của pool (tool đã chép chúng về kịch bản). Trả số bước đã xoá. */
    public static function dropLegacySteps(int $id): int
    {
        $pool = self::find($id);
        $n = $pool ? array_sum(self::legacySteps($pool['cfg'])) : 0;
        if ($n > 0) {
            Db::update('pools', ['config' => jenc(array_diff_key($pool['cfg'], self::LEGACY_STEP_LISTS)), 'updated_at' => time()], 'id=?', [$id]);
        }
        return $n;
    }

    public static function delete(int $id): bool
    {
        if ((int) Db::val('SELECT COUNT(*) FROM jobs WHERE pool_id=?', [$id]) > 0) {
            return false;   // đã có đơn → chỉ cho tạm dừng, không xoá (giữ lịch sử đối soát)
        }
        if (self::priced()) {
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
        if (!self::priced()) {
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
        $wallets = self::priced();
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
        try {
          Db::tx(static function () use ($existing, $keep, $wallets, $clean, $poolId, $currencies): void {      // lồng được trong giao dịch ngoài (nạp seed)
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
          });
        } catch (Throwable $e) {
            if (Db::isDuplicate($e)) {
                return 'Mã gói bị trùng với một gói khác của pool (đổi chéo mã giữa hai gói thì lưu từng bước).';
            }
            throw $e;
        }
        return null;
    }

    /**
     * Pool còn thiếu gì để máy nạp tự chạy được? Trả danh sách câu mô tả (rỗng = đủ). Chỉ xét thứ pool quản: luật + gói.
     * Bước thao tác soạn ở tool (kịch bản nhận đơn) — tool tự kiểm đủ bước đăng nhập / mua / kết thúc trước khi nhận đơn.
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
        if ($forTool && self::priced()) {
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
            foreach (self::legacySteps($cfg) as $list => $n) {      // chỉ pool còn bước đời cũ mới có các khoá này (tool chép về kịch bản một lần)
                $out[$list] = $cfg[$list];
            }
            $out['require_image'] = $cfg['require_image'];
        }
        return $out;
    }
}
