<?php
declare(strict_types=1);

/**
 * api.php — hai mặt API của gateway:
 *   /api/shop/*  : website bán hàng (tạo đơn, gửi OTP khách nhập, xem kết quả)
 *   /api/tool/*  : máy nạp (xin việc khi trống, xin/lấy OTP, gửi ảnh, báo kết quả)
 * Xác thực: Authorization: Bearer <khoá>. Thân & phản hồi JSON UTF-8 (trừ thân ảnh).
 */
final class Api
{
    private static function out(array $r): never
    {
        Res::json($r[1], $r[0]);
    }

    private static function guard(callable $fn): never
    {
        try {
            if (!Schema::ready()) {
                Res::err(503, 'not_ready', 'Gateway chưa cài đặt (chạy php bin/setup.php).');
            }
            $fn();
            Res::err(404, 'not_found', 'Không có API này.');
        } catch (Throwable $e) {
            error_log('[gateway] ' . $e::class . ': ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine());
            Res::err(500, 'server_error', Env::bool('APP_DEBUG') ? $e->getMessage() : 'Lỗi máy chủ, thử gửi lại.');
        }
    }

    /* ====================== SHOP ====================== */
    public static function shop(string $m, array $s): never
    {
        self::guard(static function () use ($m, $s): void {
            $key = Keys::auth('shop');
            $n = count($s);

            if ($m === 'GET' && $s === ['ping']) {
                Res::json(['ok' => true, 'key' => $key['name'], 'server_time' => iso(time())]);
            }
            if ($m === 'GET' && $s === ['pools']) {
                $pools = [];
                foreach (Pools::all() as $p) {
                    $pools[] = Pools::publicView($p, false);
                }
                Res::json(['ok' => true, 'pools' => $pools]);
            }
            if ($m === 'GET' && $n === 2 && $s[0] === 'pools') {
                $p = Pools::byCode(strtolower($s[1]));
                $p ? Res::json(['ok' => true, 'pool' => Pools::publicView($p, false)]) : Res::err(404, 'pool_not_found', 'Không có pool này.');
            }
            if ($m === 'POST' && $s === ['jobs']) {
                self::out(Jobs::create($key, Req::json()));
            }
            if ($n >= 2 && $s[0] === 'jobs') {
                $job = Jobs::forShop($key, $s[1]);
                if (!$job) {
                    Res::err(404, 'job_not_found', 'Không có đơn này.');
                }
                if ($m === 'GET' && $n === 2) {
                    Jobs::sweep();
                    Res::json(['ok' => true, 'job' => Jobs::view(Jobs::byId((int) $job['id']))]);
                }
                if ($m === 'POST' && $n === 3 && $s[2] === 'otp') {
                    self::out(Jobs::otpSubmit($job, Req::json()));
                }
                if ($m === 'POST' && $n === 3 && $s[2] === 'cancel') {
                    self::out(Jobs::cancel($job));
                }
            }
        });
    }

    /* ====================== TOOL ====================== */
    public static function tool(string $m, array $s): never
    {
        self::guard(static function () use ($m, $s): void {
            $key = Keys::auth('tool');
            $n = count($s);

            if ($m === 'GET' && $s === ['ping']) {
                Res::json(['ok' => true, 'key' => $key['name'], 'server_time' => iso(time())]);
            }
            if ($m === 'POST' && $s === ['heartbeat']) {
                self::out(Jobs::heartbeat($key, Req::json()));
            }
            if ($m === 'POST' && $s === ['sync']) {                      // tool tự báo: máy nào rảnh ở kịch bản nào + danh mục kịch bản
                if (strlen(Req::raw()) > Tools::MAX_BODY) {
                    Res::err(413, 'too_large', 'Thân yêu cầu quá 1 MB.');
                }
                self::out(Tools::sync($key, Req::json()));
            }
            if ($m === 'GET' && $s === ['pools']) {                      // danh sách gọn để người vận hành chọn pool cho nhóm máy
                Res::json(['ok' => true, 'pools' => Pools::brief()]);
            }
            if ($m === 'GET' && $n === 2 && $s[0] === 'pools') {
                $p = Pools::byCode(strtolower($s[1]));
                $p ? Res::json(['ok' => true, 'pool' => Pools::publicView($p, true)]) : Res::err(404, 'pool_not_found', 'Không có pool này.');
            }
            if ($m === 'POST' && $s === ['claim']) {
                self::out(Jobs::claim($key, Req::json()));
            }
            if ($n >= 2 && $s[0] === 'jobs') {
                $pid = $s[1];
                if ($m === 'GET' && $n === 3 && $s[2] === 'otp') {       // tự nạp lại job trong vòng chờ
                    self::out(Jobs::otpRead($key, $pid, (int) (Req::q('wait') ?? 0)));
                }
                $job = Jobs::forTool($key, $pid);
                if (!$job) {
                    Res::err(404, 'job_not_found', 'Không có đơn này (hoặc không do khoá này giữ).');
                }
                if ($m === 'GET' && $n === 2) {
                    $active = in_array($job['status'], Jobs::ACTIVE, true);
                    Res::json(['ok' => true, 'job' => Jobs::view($job, true, $active)]);
                }
                if ($m === 'POST' && $n === 3 && $s[2] === 'progress') {
                    self::out(Jobs::progress($key, $job, Req::json()));
                }
                if ($m === 'POST' && $n === 4 && $s[2] === 'otp' && $s[3] === 'request') {
                    self::out(Jobs::otpRequest($key, $job, Req::json()));
                }
                if ($m === 'POST' && $n === 3 && $s[2] === 'images') {
                    self::out(Jobs::addImage($key, $job, (int) (Req::q('seq') ?? 0), (string) (Req::q('kind') ?? 'bill'), Req::raw()));
                }
                if ($m === 'POST' && $n === 3 && $s[2] === 'result') {
                    self::out(Jobs::result($key, $job, Req::json()));
                }
            }
        });
    }

    /* ====================== file ảnh công khai (URL không đoán được, 128 bit) ====================== */
    public static function file(string $name): never
    {
        if (preg_match('/^([a-f0-9]{32})\.(png|jpg|webp)$/', $name, $mm) !== 1) {
            Res::notFound();
        }
        $im = Db::one('SELECT * FROM job_images WHERE token=?', [$mm[1]]);
        $abs = $im ? Storage::abs((string) $im['path']) : '';
        if (!$im || !is_file($abs)) {
            Res::notFound();
        }
        header('Content-Type: ' . $im['mime']);
        header('Content-Length: ' . filesize($abs));
        header('Cache-Control: private, max-age=86400');
        header('X-Content-Type-Options: nosniff');
        if (Req::q('download')) {
            $job = Jobs::byId((int) $im['job_id']);
            $fn = preg_replace('/[^A-Za-z0-9_.-]/', '_', ($job['ref'] ?? 'bill') . '-' . $im['seq'] . '.' . $mm[2]);
            header('Content-Disposition: attachment; filename="' . $fn . '"');
        }
        readfile($abs);
        exit;
    }

    /* ====================== cron qua HTTP (hosting không có crontab CLI) ====================== */
    public static function cron(): never
    {
        $want = (string) Env::get('CRON_KEY', '');
        if ($want === '' || !hash_equals($want, (string) (Req::q('key') ?? ''))) {
            Res::err(401, 'unauthorized', 'Sai CRON_KEY.');
        }
        $sweep = Jobs::sweep(true);
        $sent = Webhooks::deliverDue(50);
        Res::json(['ok' => true, 'sweep' => $sweep, 'webhooks_sent' => $sent]);
    }
}
