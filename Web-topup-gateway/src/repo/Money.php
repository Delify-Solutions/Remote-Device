<?php
declare(strict_types=1);

/* ====================== Money: số tiền là SỐ NGUYÊN = số tiền × 100 ====================== */
final class Money
{
    /** Loại tiền không có phần lẻ khi hiển thị (cùng danh sách với notify.ZERO_DECIMAL của tool). */
    public const ZERO_DECIMAL = ['JPY', 'KRW', 'VND', 'IDR', 'CLP', 'TWD', 'HUF', 'ISK'];
    /** trần an toàn của một số tiền (×100) — xa giới hạn BIGINT, đủ cho mọi ví thật */
    public const MAX = 100000000000000;

    /** Ký hiệu / tên nước người dùng hay gõ → mã ISO (Nhật: «¥» hoặc «JP» → JPY). Lưu luôn là mã ISO để khớp giá.
     *  KHÔNG có «KR» (mã nước Hàn): «kr» là ký hiệu tiền Bắc Âu — gõ «kr» thì giữ nhãn «KR» riêng, không quy thành KRW. */
    public const ALIASES = [
        '¥' => 'JPY', '￥' => 'JPY', '円' => 'JPY', 'JP' => 'JPY', '$' => 'USD', 'US$' => 'USD', 'US' => 'USD', '€' => 'EUR', 'EU' => 'EUR',
        '£' => 'GBP', 'GB' => 'GBP', 'UK' => 'GBP', '₩' => 'KRW', '₫' => 'VND', 'Đ' => 'VND', 'VN' => 'VND', 'CH' => 'CHF',
        'DK' => 'DKK', 'SE' => 'SEK', 'NO' => 'NOK', 'CN' => 'CNY', 'RMB' => 'CNY', 'HK$' => 'HKD', 'HK' => 'HKD', 'S$' => 'SGD',
        'SG' => 'SGD', 'NT$' => 'TWD', 'TW' => 'TWD', '฿' => 'THB', 'TH' => 'THB', 'RP' => 'IDR', 'ID' => 'IDR', 'A$' => 'AUD', 'AU' => 'AUD',
        'C$' => 'CAD', 'CA' => 'CAD',
    ];
    /** Ký hiệu hiện kèm mã (nhãn giao diện). */
    public const SYMBOLS = ['JPY' => '¥', 'USD' => '$', 'EUR' => '€', 'GBP' => '£', 'KRW' => '₩', 'VND' => '₫', 'CHF' => 'Fr.', 'CNY' => '¥',
        'HKD' => 'HK$', 'SGD' => 'S$', 'TWD' => 'NT$', 'THB' => '฿', 'IDR' => 'Rp', 'AUD' => 'A$', 'CAD' => 'C$', 'DKK' => 'kr', 'SEK' => 'kr', 'NOK' => 'kr'];

    /**
     * Nhãn loại tiền → dạng lưu. Loại tiền chỉ là NHÃN để so khớp ví ⇄ giá gói và đối soát (tuỳ nước máy hiện ký hiệu hay tên): ký hiệu /
     * tên biết rõ quy về mã ISO (¥ / JP / 円 → JPY) để «¥» và «JPY» là một; mã 3 chữ giữ nguyên; nhãn khác (vd «kr») giữ nguyên dạng viết
     * hoa — 1–6 ký tự chữ / ký hiệu tiền, không số, không khoảng trắng. Dấu chấm bị BỎ («kr.» → «KR», «Rs.» → «RS»): nhãn nằm trong tên
     * ô của form giá (pp_<nhãn>_amount[]) mà PHP đổi «.» trong tên ô thành «_» — để dấu chấm thì giá của loại tiền đó mất khi lưu.
     * Không hợp lệ → null. Phải cho CÙNG kết quả với wallets.currency() của tool và ô loại tiền trong app.js.
     */
    public static function currency(mixed $v): ?string
    {
        $c = is_scalar($v) ? mb_strtoupper(trim((string) $v)) : '';
        $c = str_replace('.', '', $c);
        $c = self::ALIASES[$c] ?? $c;
        return preg_match('/^[\p{L}\p{Sc}]{1,6}$/uD', $c) === 1 ? $c : null;
    }

    /** «JPY ¥» — mã kèm ký hiệu để người dùng nhận ra ngay. */
    public static function label(string $cur): string
    {
        $cur = strtoupper($cur);
        return isset(self::SYMBOLS[$cur]) ? $cur . ' ' . self::SYMBOLS[$cur] : $cur;
    }

    public static function decimals(string $cur): int
    {
        return in_array(strtoupper($cur), self::ZERO_DECIMAL, true) ? 0 : 2;
    }

    /** Để hiện: 150000 JPY → «1.500 JPY»; 6350 CHF → «63,50 CHF» (cùng cách viết với thông báo của tool). */
    public static function fmt(?int $x100, string $cur): string
    {
        if ($x100 === null) {
            return '—';
        }
        $v = abs($x100);
        $s = number_format(intdiv($v, 100), 0, ',', '.');
        if (self::decimals($cur) > 0) {
            $s .= ',' . str_pad((string) ($v % 100), 2, '0', STR_PAD_LEFT);
        }
        return ($x100 < 0 ? '-' : '') . $s . ($cur !== '' ? ' ' . $cur : '');
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
