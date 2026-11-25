<?php
declare(strict_types=1);

define('BASE', dirname(__DIR__));

require BASE . '/src/core.php';
require BASE . '/src/schema.php';
require BASE . '/src/repo.php';
require BASE . '/src/api.php';
require BASE . '/src/spec.php';
require BASE . '/src/admin.php';

Env::load(BASE . '/.env');
date_default_timezone_set('UTC');
mb_internal_encoding('UTF-8');
ini_set('display_errors', Env::bool('APP_DEBUG') ? '1' : '0');
