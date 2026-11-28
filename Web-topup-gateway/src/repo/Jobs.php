<?php
declare(strict_types=1);

/**
 * Jobs — vòng đời của đơn nạp (shop tạo → tool nhận → kết quả / đối soát).
 *
 * NGUYÊN TẮC TIỀN (giống hợp đồng tool của shop, đừng nới):
 *  1. Một đơn (shop_key, ref) chỉ tạo MỘT job; một job chỉ giao cho tool ĐÚNG MỘT LẦN.
 *  2. Gateway không bao giờ tự "nạp lại" hay tự hoàn tiền.
 *  3. Mọi nghi ngờ (tool im lặng, báo xong thiếu ảnh, tool không chắc) → `review` cho admin chốt.
 */
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
        if ($forTool && Wallets::isWalletJob($job)) {
            $out['wallet'] = ['source' => 'tool', 'currency' => (string) $job['currency'], 'cost' => (int) $job['cost']];     // tiền của đơn theo ví của máy (tool giữ sổ)
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
        if (Pools::priced() && $identity !== '') {
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
        //  (2) không gửi: máy không có ví → không kiểm tiền.
        $wallet = null;                                   // ví của máy đang xin đơn: {currency, available} — null = máy không khai ví
        if (Wallets::enabled() && array_key_exists('wallet', $in) && $in['wallet'] !== null) {
            $tw = is_array($in['wallet']) ? $in['wallet'] : [];
            $cur = Money::currency($tw['currency'] ?? '');
            $av = $tw['available'] ?? null;
            if ($cur === null || !is_int($av) || abs($av) > Money::MAX) {
                return [422, self::err('invalid_wallet', 'wallet phải là {currency: nhãn loại tiền (vd JPY, ¥, kr), available: số nguyên ×100}.')];
            }
            $applied = is_array($tw['applied'] ?? null) ? array_slice(array_values($tw['applied']), -500) : [];
            $wallet = ['currency' => $cur, 'available' => $av + Wallets::pendingEffect((int) $key['id'], $device, $cur, $applied)];
        }
        $available = $wallet ? $wallet['available'] : 0;
        $since = $now - (int) $pool['cfg']['queue_ttl'];
        // có ví thì xét rộng hơn: đơn đầu hàng quá giá với ví này không được chặn mãi các đơn rẻ phía sau
        $cands = Db::all("SELECT id, pool_id, items FROM jobs WHERE pool_id=? AND status='queued' AND created_at>=? ORDER BY id LIMIT " . ($wallet ? 300 : 5), [$pool['id'], $since]);   // máy có ví: xét cả hàng đợi (đơn đắt đứng đầu không chặn đơn rẻ phía sau)
        $skipped = [];
        foreach ($cands as $c) {
            $set = '';
            $args = [$device, $key['id'], $now, $now, $now];
            $q = null;
            if ($wallet) {
                $q = Wallets::quote($c, $wallet['currency']);
                if ($q['missing']) {
                    $skipped['no_price'][] = $q;          // gói chưa có giá ở loại tiền của ví → không biết có đủ tiền không
                    continue;
                }
                if ($q['cost'] > $available) {
                    $skipped['insufficient'][] = $q;
                    continue;
                }
                // chụp đơn giá lúc giao đơn vào items: admin sửa giá sau đó không làm đổi số tiền bị trừ của đơn này
                $set = ', wallet_id=NULL, currency=?, cost=?, items=?, wallet_state=NULL';
                array_push($args, $wallet['currency'], $q['cost'], jenc($q['items']));
            }
            $args[] = $c['id'];
            $cond = '';
            if ($wallet) {
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
                $acc = $wallet ? (string) (Wallets::reported((int) $key['id'], $device)['apple_account'] ?? '') : '';
                self::event((int) $job['id'], 'tool', 'claimed', 'Giao cho máy ' . $device . ' (' . $key['name'] . ')'
                    . ($wallet ? ' — trả bằng ' . ($acc !== '' ? 'tài khoản Apple ' . Wallets::mask($acc) : 'ví của máy')
                        . ', chi phí ' . Money::fmt($q['cost'], $wallet['currency']) . ' (ví còn dùng được ' . Money::fmt($available, $wallet['currency']) . ')' : ''));
                Devices::touch((int) $key['id'], $device, $pool['code'], 'busy', $job['pid']);
                Webhooks::enqueue($job, 'job.claimed');
                return [200, ['ok' => true, 'paused' => false, 'job' => self::view($job, true, true)]];
            }
        }
        if ($wallet && $skipped) {
            // có đơn nhưng ví của máy này không trả được → đơn để máy khác nhận; tool báo admin nạp thêm tiền / khai giá
            return [200, ['ok' => true, 'paused' => false, 'job' => null,
                          'wallet_short' => Wallets::shortInfo(['currency' => $wallet['currency'], 'available' => $available], $skipped)]];
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
        $held = Wallets::isWalletJob($cur) && ($cur['wallet_state'] ?? null) === 'held';
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
        if (Pools::priced()) {
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
        $wallet = Wallets::isWalletJob($job);                             // đơn có tính tiền ví → tiền đi thành sự kiện cho tool
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
        $n = Db::tx(static function () use ($id, $from, $to, $now, $paid, $charge, &$refund, $wallet, $note, $actor): int {
            $n = Db::run('UPDATE jobs SET status=?, stage=?, login_enc=NULL, otp_enc=NULL, finished_at=COALESCE(finished_at, ?), updated_at=? WHERE id=? AND status=?',
                [$to, $to, $now, $now, $id, $from])->rowCount();
            if ($n !== 1 || !$wallet) {
                return $n;
            }
            $cur = self::byId($id);
            if ($paid && Db::run("UPDATE jobs SET wallet_state='charged' WHERE id=? AND wallet_state IN ('none','released')", [$id])->rowCount() === 1) {
                $why = $note !== '' ? $note : 'Admin sửa đơn sang «hoàn tất» — trừ tiền đơn';
                Wallets::event($cur, 'charge', -(int) $charge, 0, $actor, $why);
            }
            if ($to === 'failed' && Db::run("UPDATE jobs SET wallet_state='none' WHERE id=? AND wallet_state='charged'", [$id])->rowCount() === 1) {
                // tính số đã trừ SAU khi giữ quyền ghi (trong cùng giao dịch) → không hoàn theo một con số đã cũ
                $refund = Wallets::charged($id);
                if ($refund > 0) {
                    $why = $note !== '' ? $note : 'Admin sửa đơn sang «thất bại» — hoàn lại tiền đã trừ';
                    Wallets::event($cur, 'refund', $refund, 0, $actor, $why);
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
        $n = Db::tx(static function () use ($id, &$images): int {
            $n = Db::run('DELETE FROM jobs WHERE id=? AND status NOT IN ' . self::IN_ACTIVE . " AND status NOT IN ('queued','review')", [$id])->rowCount();
            if ($n !== 1) {
                return 0;
            }
            $images = Db::all('SELECT path FROM job_images WHERE job_id=?', [$id]);      // đọc SAU khi giữ quyền ghi: không sót ảnh vừa tải lên
            Db::run('DELETE FROM job_images WHERE job_id=?', [$id]);
            Db::run('DELETE FROM job_events WHERE job_id=?', [$id]);
            Db::run("DELETE FROM webhooks WHERE job_id=? AND status<>'pending'", [$id]);     // webhook chưa gửi (vd job.cancelled) vẫn gửi cho shop
            if (Wallets::enabled()) {
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
