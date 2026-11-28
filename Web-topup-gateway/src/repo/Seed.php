<?php
declare(strict_types=1);

/* ====================== Dữ liệu mặc định (seed) ====================== */
/**
 * Xuất / nạp CẤU HÌNH của gateway để cài sang máy khác là có sẵn: pool (trường đăng nhập, OTP, luật, các bước, loại tiền) + gói + giá theo
 * loại tiền. KHÔNG có: admin (máy mới tự tạo bằng setup.php), khoá API (bí mật webhook mã hoá theo APP_KEY — phải tạo mới), đơn, ảnh, ví,
 * máy / kịch bản tool báo (tool tự đồng bộ lại). Nạp chỉ khi CSDL chưa có pool nào (không bao giờ ghi đè cấu hình đang dùng).
 */
final class Seed
{
    public const VERSION = 1;

    /**
     * @param list<string>|null $skipped nhận danh sách «pool/gói/loại tiền» của các giá KHÔNG xuất: giá cũ thiếu «chữ giá hiện trên máy»
     *                                   (form lưu bây giờ bắt buộc đủ cả hai) — xuất ra thì máy mới sẽ từ chối cả tệp.
     */
    public static function export(?array &$skipped = null): array
    {
        $pools = [];
        $skipped = [];
        foreach (Db::all('SELECT * FROM pools ORDER BY id') as $row) {
            $p = Pools::find((int) $row['id']);
            $prices = Pools::prices((int) $p['id']);
            $pk = [];
            foreach (Pools::packages((int) $p['id']) as $k) {
                $pp = [];
                foreach ($prices[(int) $k['id']] ?? [] as $cur => $pr) {
                    if (trim((string) $pr['display']) === '' || trim((string) $pr['amount']) === '') {
                        $skipped[] = $p['code'] . '/' . $k['code'] . '/' . $cur;
                        continue;
                    }
                    $pp[$cur] = $pr;
                }
                $pk[] = ['code' => $k['code'], 'name' => $k['name'], 'ocr_text' => $k['ocr_text'], 'price_text' => $k['price_text'], 'limit_type' => $k['limit_type'],
                         'max_qty' => (int) $k['max_qty'], 'active' => (bool) (int) $k['active'], 'prices' => (object) $pp];
            }
            $pools[] = ['code' => $p['code'], 'name' => $p['name'], 'game' => $p['game'], 'active' => (bool) (int) $p['active'], 'config' => $p['cfg'], 'packages' => $pk];
        }
        return ['seed' => self::VERSION, 'exported_at' => iso(time()), 'pools' => $pools];
    }

    /** @return string câu báo kết quả, hoặc ném RuntimeException */
    public static function import(array $seed): string
    {
        if ((int) ($seed['seed'] ?? 0) !== self::VERSION || !is_array($seed['pools'] ?? null)) {
            throw new RuntimeException('Tệp dữ liệu mặc định sai dạng (không phải seed bản ' . self::VERSION . ').');
        }
        if (Settings::get('seed_imported_at') !== null) {
            return 'Dữ liệu mặc định đã nạp từ trước — bỏ qua (xoá pool rồi chạy lại setup cũng không nạp lại).';
        }
        if ((int) Db::val('SELECT COUNT(*) FROM pools') > 0) {
            return 'CSDL đã có pool — bỏ qua dữ liệu mặc định (không ghi đè cấu hình đang dùng).';
        }
        if ($seed['pools'] === []) {
            return 'Tệp dữ liệu mặc định không có pool nào — bỏ qua (chưa đánh dấu «đã nạp»: đặt tệp đúng rồi chạy lại setup vẫn nạp được).';
        }
        // MỘT giao dịch: hỏng ở đâu cũng không để lại pool dở (lần chạy sau vẫn nạp được)
        return Db::tx(static function () use ($seed): string {
            $np = $nk = 0;
            foreach ($seed['pools'] as $p) {
                if (!is_array($p) || !is_string($p['code'] ?? null)) {
                    throw new RuntimeException('Có pool sai dạng (thiếu mã pool).');
                }
                $cfg = is_array($p['config'] ?? null) ? $p['config'] : [];
                $id = Pools::save(null, (string) ($p['code'] ?? ''), (string) ($p['name'] ?? ''), (string) ($p['game'] ?? ''), !empty($p['active']), $cfg);
                if (is_string($id)) {
                    throw new RuntimeException('Pool «' . ($p['code'] ?? '?') . '»: ' . $id);
                }
                $rows = [];
                foreach ((array) ($p['packages'] ?? []) as $k) {
                    if (!is_array($k) || !is_string($k['code'] ?? null)) {
                        throw new RuntimeException('Pool «' . ($p['code'] ?? '?') . '»: có gói sai dạng (thiếu mã gói).');
                    }
                    $rows[] = ['code' => (string) ($k['code'] ?? ''), 'name' => (string) ($k['name'] ?? ''), 'ocr_text' => (string) ($k['ocr_text'] ?? ''),
                               'price_text' => (string) ($k['price_text'] ?? ''), 'limit_type' => (string) ($k['limit_type'] ?? 'multi'),
                               'max_qty' => (int) ($k['max_qty'] ?? 0), 'active' => !empty($k['active']), 'prices' => (array) ($k['prices'] ?? [])];
                }
                $err = Pools::savePackages($id, $rows);
                if ($err !== null) {
                    throw new RuntimeException('Gói của pool «' . $p['code'] . '»: ' . $err);
                }
                $np++;
                $nk += (int) Db::val('SELECT COUNT(*) FROM packages WHERE pool_id=?', [$id]);
            }
            Settings::set('seed_imported_at', (string) time());
            return "Đã nạp dữ liệu mặc định: $np pool, $nk gói.";
        });
    }
}
