<?php
declare(strict_types=1);

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
