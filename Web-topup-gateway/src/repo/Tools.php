<?php
declare(strict_types=1);

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
            [$wallets, $werr] = Wallets::parseReport($in['wallets']);
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
            Wallets::ack($kid, $acks);
        }
        if ($hasWallets) {
            Wallets::saveReport($kid, $wallets, $now);
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
            'wallet_events' => Wallets::pending($kid),
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
