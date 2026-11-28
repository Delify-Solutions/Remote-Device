<?php
declare(strict_types=1);

final class Devices
{
    public static function touch(int $keyId, string $name, ?string $pool, string $state, ?string $jobPid): void
    {
        $n = Db::run(
            'UPDATE devices SET pool_code=?, state=?, job_pid=?, last_seen_at=? WHERE tool_key_id=? AND name=?',
            [$pool, $state, $jobPid, time(), $keyId, $name]
        )->rowCount();
        if ($n === 0) {
            try {
                Db::insert('devices', ['tool_key_id' => $keyId, 'name' => $name, 'pool_code' => $pool, 'state' => $state, 'job_pid' => $jobPid, 'last_seen_at' => time()]);
            } catch (Throwable $e) {
                if (!Db::isDuplicate($e)) {
                    throw $e;
                }
            }
        }
    }

    public static function free(?int $keyId, ?string $name): void
    {
        if ($keyId && $name) {
            Db::run("UPDATE devices SET state='free', job_pid=NULL WHERE tool_key_id=? AND name=?", [$keyId, $name]);
        }
    }

    public static function all(): array
    {
        // máy tool đã gỡ (status=removed) thì thôi không hiện nữa — trừ khi còn đang đứng tên một đơn
        $live = Schema::version() >= 3 ? "WHERE (d.status IS NULL OR d.status<>'removed' OR d.job_pid IS NOT NULL) " : '';
        return Db::all('SELECT d.*, k.name AS key_name FROM devices d LEFT JOIN api_keys k ON k.id=d.tool_key_id ' . $live . 'ORDER BY d.last_seen_at DESC, d.name LIMIT 300');
    }
}
