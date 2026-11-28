<?php
declare(strict_types=1);

/* ====================== Ví (tool quản lý — gateway giữ bản sao + tiền của từng đơn) ====================== */
/**
 * Ví của từng máy (tài khoản Apple + loại tiền + số dư + sổ) do TOOL giữ — nguồn gốc là tool. Gateway:
 *  - khi máy xin đơn, nhận «loại tiền + còn dùng được» tool gửi kèm, trừ đi các khoản tool CHƯA nhận (sự kiện chưa ack) rồi chỉ giao
 *    đơn vừa túi, định giá theo đúng loại tiền đó (đơn ghi currency + cost);
 *  - tiền của đơn (mua / tạm giữ / admin chốt / hoàn) ghi thành SỰ KIỆN cho tool (tool_wallet_events); tool nhận qua /api/tool/sync,
 *    áp vào sổ của nó (mỗi sự kiện một lần, theo id) rồi báo đã nhận ở lần sync sau;
 *  - giữ BẢN SAO ví tool báo lên (tool_wallets) để admin xem — không sửa ở gateway.
 * Sự kiện tiền của một đơn:
 *   purchase — đơn xong: trừ đúng số gói đã mua × đơn giá LÚC GIAO ĐƠN
 *   hold     — đơn sang chờ đối soát: TẠM GIỮ cả chi phí đơn (không đổi số dư)
 *   charge   — admin chốt «đã nạp»: trừ số tiền admin nhập; tạm giữ đóng lại
 *   release  — admin chốt «chưa nạp»: nhả tạm giữ
 *   refund   — admin đổi đơn đã trừ tiền sang «thất bại»: cộng lại đúng số đã trừ của đơn
 * jobs.wallet_state: NULL (đang chạy, chưa tính tiền) → charged | none (failed, không trừ) | held → charged | released.
 * Mọi bước đổi wallet_state đều là UPDATE có điều kiện → báo muộn / bấm hai lần không bao giờ tính tiền hai lần.
 * (Ví khai ở gateway của migration 5 — bảng wallets / wallet_entries, cột jobs.wallet_id — không còn mã nào đọc / ghi; để nguyên trong CSDL.)
 */
final class Wallets
{
    public const KINDS = [
        'purchase' => ['Mua gói', 'info'],
        'hold'     => ['Tạm giữ', 'warning'],
        'release'  => ['Nhả tạm giữ', 'secondary'],
        'charge'   => ['Trừ khi đối soát', 'primary'],
        'refund'   => ['Hoàn tiền đơn', 'success'],
    ];
    public const STATE = [
        'held'     => ['đang tạm giữ', 'warning'],
        'charged'  => ['đã trừ tiền', 'success'],
        'released' => ['đã nhả tạm giữ', 'secondary'],
        'none'     => ['không trừ tiền', 'secondary'],
    ];

    /** CSDL đã có bảng ví của tool (migration 6). Mã mới chạy trên CSDL cũ thì mọi thứ về ví coi như tắt. */
    public static function enabled(): bool
    {
        return Schema::version() >= 6;
    }

    /** a***@example.com — tài khoản Apple ghi vào nhật ký đơn / hiện ở danh sách. */
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

    /** Đơn có tính tiền ví: lúc giao đã ghi loại tiền + chi phí theo ví của máy nhận. (wallet_id khác rỗng = đơn đời cũ gắn ví gateway — không tính.) */
    public static function isWalletJob(array $job): bool
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

    /** Ví đang dùng mà «còn dùng được» thấp hơn giá gói đắt nhất đang bán ở đúng loại tiền — cho trang Tổng quan. */
    public static function low(): array
    {
        $out = [];
        foreach (self::all() as $w) {
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

    /** Sự kiện tiền của một đơn. */
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
     * Chi phí của một đơn đang chờ nếu giao cho máy trả bằng loại tiền `$currency`, theo giá HIỆN TẠI của các gói ở loại tiền đó.
     * Trả ['cost' => tổng ×100, 'items' => ảnh chụp gói kèm price / currency / price_display, 'missing' => mã gói chưa có giá loại tiền này].
     * Tool phải KHỚP chữ giá trên ô gói → gói thiếu «chữ giá hiện trên máy» cũng coi là chưa có giá.
     */
    public static function quote(array $job, string $currency): array
    {
        $items = jdec($job['items']);
        $cost = 0;
        $missing = [];
        foreach ($items as &$it) {
            $code = (string) ($it['code'] ?? '');
            $p = Db::one('SELECT pp.amount, pp.display FROM packages p JOIN package_prices pp ON pp.package_id=p.id AND pp.currency=? WHERE p.pool_id=? AND p.code=?',
                [$currency, $job['pool_id'], $code]);
            if (!$p || trim((string) $p['display']) === '') {
                $missing[] = $code;
                continue;
            }
            $it['price'] = (int) $p['amount'];
            $it['currency'] = $currency;
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

    /**
     * Tool báo kết quả / hệ thống chuyển đơn sang đối soát → tính tiền của đơn (gọi TRONG giao dịch đổi trạng thái đơn).
     * $new: done → mua (trừ đúng số gói đã mua × đơn giá lúc giao); review → tạm giữ cả chi phí; failed → không trừ.
     * $reported: kết quả từng gói tool gửi ({code, qty_done}); rỗng khi done = đã mua đủ. Đơn không tính tiền ví thì không làm gì.
     */
    public static function settle(array $job, string $new, array $reported, string $actor): void
    {
        if (!self::isWalletJob($job)) {
            return;
        }
        $state = $new === 'done' ? 'charged' : ($new === 'failed' ? 'none' : 'held');
        if (Db::run('UPDATE jobs SET wallet_state=? WHERE id=? AND wallet_state IS NULL', [$state, $job['id']])->rowCount() !== 1) {
            return;                                             // đã tính rồi (báo muộn / gửi lại) → không ghi thêm gì
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
            // gateway chỉ cho mua đúng số lượng của đơn → số tool báo vượt quá thì tính theo số lượng của đơn
            $n = $reported ? min($qty, $done[$code] ?? 0) : $qty;
            if ($n > 0 && isset($it['price'])) {
                self::event($job, 'purchase', -$n * (int) $it['price'], 0, $actor, 'Mua ' . ($it['name'] ?? $code), $code, $n);
            }
        }
    }

    /** Admin chốt đơn đang TẠM GIỮ (gọi TRONG giao dịch chốt đơn): done → trừ $charge + đóng tạm giữ; failed → nhả. */
    public static function resolve(array $job, string $to, int $charge, string $note, string $actor): void
    {
        if (!self::isWalletJob($job)) {
            return;
        }
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
