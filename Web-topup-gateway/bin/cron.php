<?php
declare(strict_types=1);

/** Chạy mỗi phút (crontab):  * * * * * php /duong/dan/bin/cron.php  — dọn đơn quá hạn + gửi lại webhook. */
require dirname(__DIR__) . '/src/bootstrap.php';

$sweep = Jobs::sweep(true);
$sent = Webhooks::deliverDue(50);
echo gmdate('c') . " expired={$sweep['expired']} timeout={$sweep['timeout']} webhooks_sent={$sent}\n";
