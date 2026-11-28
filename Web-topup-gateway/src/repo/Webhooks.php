<?php
declare(strict_types=1);

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
