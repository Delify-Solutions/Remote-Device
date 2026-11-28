<?php
declare(strict_types=1);

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
