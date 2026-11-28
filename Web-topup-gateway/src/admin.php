<?php
declare(strict_types=1);

/**
 * admin.php — trang quản trị: đăng nhập · tổng quan · pool (trường đăng nhập, OTP, luật
 * nhận diện, các bước, gói nạp) · khoá API + webhook · đơn (đối soát, ảnh) · tài khoản.
 */
final class Admin
{
    public static function route(string $m, array $s): never
    {
        if (!Schema::ready()) {
            http_response_code(503);
            header('Content-Type: text/plain; charset=utf-8');
            echo "Gateway chưa cài đặt. Chạy:  php bin/setup.php";
            exit;
        }
        $a = $s[0] ?? '';
        if ($a === 'login') {
            $m === 'POST' ? self::loginPost() : self::loginForm();
        }
        $user = Auth::require();
        if ($m === 'POST') {
            Csrf::verify();
        }
        $id = isset($s[1]) && ctype_digit($s[1]) ? (int) $s[1] : 0;
        $act = $s[2] ?? '';

        if ($a === 'logout' && $m === 'POST') {
            Auth::logout();
            Res::redirect('/admin/login');
        }
        if ($a === '') {
            self::dashboard($user);
        }
        if ($a === 'scripts' && $m === 'GET' && !isset($s[1])) {
            view('scripts', ['user' => $user, 'nav' => 'scripts', 'title' => 'Kịch bản & máy', 'tools' => Tools::board(),
                             'migrated' => Schema::version() >= Schema::LATEST, 'pools' => array_column(Pools::all(), null, 'code'), 'hasToolKey' => (int) Db::val("SELECT COUNT(*) FROM api_keys WHERE kind='tool'") > 0]);
        }
        if ($a === 'pools') {
            if ($m === 'GET' && !isset($s[1])) {
                view('pools', ['user' => $user, 'nav' => 'pools', 'title' => 'Pool', 'pools' => Pools::all(), 'served' => Tools::scriptsByPool()]);
            }
            if ($m === 'GET' && ($s[1] ?? '') === 'new') {
                self::poolForm($user, null);
            }
            if ($m === 'GET' && $id) {
                self::poolForm($user, $id);
            }
            if ($m === 'POST' && ($s[1] ?? '') === 'save') {
                self::poolSave($user);
            }
            if ($m === 'POST' && $id && $act === 'toggle') {
                $p = Pools::find($id);
                if ($p) {
                    Db::update('pools', ['active' => (int) $p['active'] ? 0 : 1, 'updated_at' => time()], 'id=?', [$id]);
                    Flash::set((int) $p['active'] ? 'Đã TẠM DỪNG pool «' . $p['name'] . '» (không nhận đơn mới, không giao thêm).' : 'Đã BẬT lại pool «' . $p['name'] . '».');
                }
                Res::redirect('/admin/pools');
            }
            if ($m === 'POST' && $id && $act === 'delete') {
                Pools::delete($id) ? Flash::set('Đã xoá pool.') : Flash::set('Pool đã có đơn nên không xoá được — hãy tạm dừng.', 'bad');
                Res::redirect('/admin/pools');
            }
        }
        if ($a === 'keys') {
            self::keys($user, $m, $s, $id, $act);
        }
        if ($a === 'jobs') {
            if ($m === 'GET' && !isset($s[1])) {
                self::jobs($user);
            }
            if ($m === 'POST' && ($s[1] ?? '') === 'create') {           // modal «Tạo đơn thử» (gửi bằng fetch, trả JSON)
                [$code, $res] = Jobs::adminCreate(self::jobInput(true), $user['username']);
                if ($code === 201) {
                    Flash::set('Đã tạo đơn thử ' . $res['job']['ref'] . ' — máy nhận đơn của pool này sẽ nạp THẬT.');
                    Res::json(['ok' => true, 'url' => '/admin/jobs/' . (int) $res['job_row_id']]);
                }
                Res::json(['ok' => false, 'error' => !empty($res['duplicate']) ? 'Đã có đơn thử mã này — đổi mã đơn.' : (string) ($res['message'] ?? 'Không tạo được đơn.')], 200);
            }
            if ($m === 'POST' && $id && $act === 'login') {                // «Hiện» thông tin đăng nhập (ghi nhật ký đơn)
                $login = Jobs::adminLogin($id, $user['username']);
                Res::json($login === null ? ['ok' => false, 'error' => 'Đơn đã kết thúc — máy chủ đã xoá thông tin đăng nhập.'] : ['ok' => true, 'login' => (object) $login]);
            }
            if ($m === 'POST' && $id && $act === 'update') {               // modal «Sửa đơn» (fetch, JSON)
                $err = Jobs::adminUpdate($id, self::jobInput((string) Req::post('scope', '') === 'full'), $user['username']);
                if ($err === null) {
                    Flash::set('Đã lưu đơn.');
                }
                Res::json($err === null ? ['ok' => true] : ['ok' => false, 'error' => $err]);
            }
            if ($m === 'POST' && $id && $act === 'status') {
                $to = (string) Req::post('to', '');
                $job = Jobs::byId($id);
                $charge = null;
                if ($job && $to === 'done' && Wallets::enabled() && !empty($job['wallet_id']) && trim((string) Req::post('charge', '')) !== '') {
                    [$charge, $cerr] = Jobs::chargeInput($job, (string) Req::post('charge', ''));
                    if ($cerr !== null) {
                        Flash::set($cerr, 'bad');
                        Res::redirect('/admin/jobs/' . $id);
                    }
                }
                $err = Jobs::adminSetStatus($id, $to, $user['username'], $charge, (string) Req::post('note', ''));
                $err === null ? Flash::set('Đã đổi trạng thái đơn sang «' . (Jobs::LABEL[$to] ?? $to) . '».') : Flash::set($err, 'bad');
                Res::redirect('/admin/jobs/' . $id);
            }
            if ($m === 'POST' && $id && $act === 'delete') {
                $job = Jobs::byId($id);
                $err = Jobs::adminDelete($id, $user['username']);
                $err === null ? Flash::set('Đã xoá đơn ' . ($job['ref'] ?? '') . '.') : Flash::set($err, 'bad');
                Res::redirect($err === null || (string) Req::post('back', '') === 'list' ? '/admin/jobs' : '/admin/jobs/' . $id);
            }
            if ($m === 'GET' && $id) {
                self::job($user, $id);
            }
            if ($m === 'POST' && $id && $act === 'resolve') {
                $to = (string) Req::post('to', '');
                $job = Jobs::byId($id);
                $charge = null;
                if ($job && $to === 'done' && Wallets::enabled() && ($job['wallet_state'] ?? null) === 'held') {
                    // đơn đang tạm giữ ví: admin nhập số tiền THẬT đã bị trừ ở tài khoản Apple
                    [$charge, $err] = Jobs::chargeInput($job, (string) Req::post('charge', ''));
                    if ($err !== null) {
                        Flash::set($err, 'bad');
                        Res::redirect('/admin/jobs/' . $id);
                    }
                }
                Jobs::adminResolve($id, $to, $user['username'], $charge, (string) Req::post('note', ''))
                    ? Flash::set($to === 'done' ? 'Đã chốt: ĐÃ NẠP ĐỦ → hoàn tất đơn.' : 'Đã chốt: CHƯA NẠP → báo shop thất bại.')
                    : Flash::set('Không chốt được (đơn không còn ở trạng thái chờ đối soát).', 'bad');
                Res::redirect('/admin/jobs/' . $id);
            }
            if ($m === 'POST' && $id && $act === 'cancel') {
                $job = Jobs::byId($id);
                [$code] = $job ? Jobs::cancel($job, 'admin') : [404];
                $code === 200 ? Flash::set('Đã huỷ đơn.') : Flash::set('Đơn đã giao cho máy, không huỷ được.', 'bad');
                Res::redirect('/admin/jobs/' . $id);
            }
        }
        if ($a === 'wallets') {
            self::wallets($user, $m, $s, $id, $act);
        }
        if ($a === 'account') {
            if ($m === 'POST') {
                self::passwordSave($user);
            }
            view('account', ['user' => $user, 'nav' => 'account', 'title' => 'Tài khoản']);
        }
        Res::notFound();
    }

    /* ---------- đăng nhập ---------- */
    private static function loginForm(?string $error = null): never
    {
        if (Auth::user()) {
            Res::redirect('/admin');
        }
        view('login', ['error' => $error, 'title' => 'Đăng nhập'], null);
    }

    private static function loginPost(): never
    {
        Csrf::verify();
        $u = trim((string) Req::post('username', ''));
        $p = (string) Req::post('password', '');
        // Hai lớp: theo IP (8 lần / 10 phút) và theo TÊN ĐĂNG NHẬP (20 lần / 10 phút, bất kể từ IP nào —
        // dò mật khẩu bằng nhiều IP vẫn bị chặn).
        $ip = Req::ip();
        $byIp = 'login:' . $ip;
        $byUser = 'login-user:' . mb_strtolower(mb_substr($u, 0, 200));
        // IP mà admin này đã từng đăng nhập ĐÚNG gần đây. Lớp chặn theo tên đăng nhập KHÔNG áp cho các IP đó —
        // nếu không, người ngoài chỉ cần cố tình nhập sai 20 lần mỗi 10 phút là khoá được admin thật.
        $known = jdec(Settings::get('login_known_ips', '[]'));
        $tag = hash('sha256', mb_strtolower($u) . '|' . $ip);
        $trusted = in_array($tag, $known, true);
        if (RateLimit::count($byIp, 600) >= 8 || (!$trusted && $u !== '' && RateLimit::count($byUser, 600) >= 20)) {
            self::loginForm('Sai quá nhiều lần. Thử lại sau 10 phút.');
        }
        if ($u === '' || $p === '' || !Auth::attempt($u, $p)) {
            RateLimit::hit($byIp);
            if ($u !== '') {
                RateLimit::hit($byUser);
            }
            self::loginForm('Sai tài khoản hoặc mật khẩu.');
        }
        RateLimit::clear($byIp);
        RateLimit::clear($byUser);
        Settings::set('login_known_ips', jenc(array_slice(array_values(array_unique(array_merge([$tag], $known))), 0, 20)));
        Res::redirect('/admin');
    }

    private static function passwordSave(array $user): never
    {
        $cur = (string) Req::post('current', '');
        $new = (string) Req::post('new', '');
        $row = Db::one('SELECT * FROM admins WHERE id=?', [$user['id']]);
        if (!$row || !password_verify($cur, $row['password_hash'])) {
            Flash::set('Mật khẩu hiện tại không đúng.', 'bad');
        } elseif (strlen($new) < 10) {
            Flash::set('Mật khẩu mới cần ít nhất 10 ký tự.', 'bad');
        } elseif ($new !== (string) Req::post('confirm', '')) {
            Flash::set('Hai lần nhập mật khẩu mới không khớp.', 'bad');
        } else {
            Db::update('admins', ['password_hash' => password_hash($new, PASSWORD_DEFAULT)], 'id=?', [$user['id']]);
            Flash::set('Đã đổi mật khẩu.');
        }
        Res::redirect('/admin/account');
    }

    /* ---------- tổng quan ---------- */
    private static function dashboard(array $user): never
    {
        Jobs::sweep();
        $by = [];
        foreach (Db::all('SELECT status, COUNT(*) AS n FROM jobs GROUP BY status') as $r) {
            $by[$r['status']] = (int) $r['n'];
        }
        $tz = new DateTimeZone(Env::get('APP_TZ', 'Asia/Ho_Chi_Minh'));
        $today = (new DateTime('today', $tz))->getTimestamp();
        view('dashboard', [
            'user' => $user, 'nav' => 'home', 'title' => 'Tổng quan', 'by' => $by,
            'doneToday'   => (int) Db::val("SELECT COUNT(*) FROM jobs WHERE status='done' AND finished_at>=?", [$today]),
            'failedToday' => (int) Db::val("SELECT COUNT(*) FROM jobs WHERE status='failed' AND finished_at>=?", [$today]),
            'devices'     => Devices::all(),
            'scriptNames' => Tools::scriptNames(),
            'recent'      => Db::all('SELECT j.*, p.name AS pool_name FROM jobs j LEFT JOIN pools p ON p.id=j.pool_id ORDER BY j.id DESC LIMIT 12'),
            'whFailed'    => (int) Db::val("SELECT COUNT(*) FROM webhooks WHERE status='failed' AND created_at>?", [time() - 86400]),
            'whPending'   => (int) Db::val("SELECT COUNT(*) FROM webhooks WHERE status='pending'"),
            'hasShopKey'  => (int) Db::val("SELECT COUNT(*) FROM api_keys WHERE kind='shop' AND id<>?", [(int) Settings::get('admin_test_key_id', '0')]) > 0,   // khoá «Đơn thử» không tính
            'hasToolKey'  => (int) Db::val("SELECT COUNT(*) FROM api_keys WHERE kind='tool'") > 0,
            'hasPool'     => (int) Db::val('SELECT COUNT(*) FROM pools') > 0,
            'lowWallets'  => Wallets::low(),
        ]);
    }

    /* ---------- pool ---------- */
    private static function poolForm(array $user, ?int $id, ?array $posted = null, ?string $error = null): never
    {
        if ($posted !== null) {
            $pool = $posted;
        } elseif ($id) {
            $pool = Pools::find($id);
            if (!$pool) {
                Res::notFound();
            }
            $prices = Pools::prices($id);
            $pool['pk'] = Pools::packages($id);
            foreach ($pool['pk'] as &$p) {
                $p['prices'] = $prices[(int) $p['id']] ?? [];
            }
            unset($p);
        } else {
            $pool = ['id' => 0, 'code' => '', 'name' => '', 'game' => '', 'active' => 1, 'cfg' => Pools::defaults(), 'pk' => []];
        }
        view('pool-edit', ['user' => $user, 'nav' => 'pools', 'title' => $pool['id'] ? 'Sửa pool' : 'Tạo pool', 'pool' => $pool, 'error' => $error,
                           'missing' => $pool['id'] ? Pools::missing($pool) : [], 'wallets' => Wallets::enabled()]);
    }

    /** Ghép các cột lf_key[], lf_label[]… của form lặp thành danh sách dòng. */
    private static function rows(array $map): array
    {
        $cols = [];
        $n = 0;
        foreach ($map as $field => $post) {
            $cols[$field] = Req::postArr($post);
            $n = max($n, count($cols[$field]));
        }
        $rows = [];
        for ($i = 0; $i < $n; $i++) {
            $row = [];
            foreach ($cols as $field => $vals) {
                $row[$field] = is_scalar($vals[$i] ?? null) ? (string) $vals[$i] : '';
            }
            $rows[] = $row;
        }
        return $rows;
    }

    private static function poolSave(array $user): never
    {
        $id = (int) Req::post('id', '0');
        $fields = [];
        foreach (self::rows(['key' => 'lf_key', 'label' => 'lf_label', 'type' => 'lf_type', 'required' => 'lf_required', 'secret' => 'lf_secret', 'hint' => 'lf_hint', 'options' => 'lf_options']) as $r) {
            $r['required'] = $r['required'] === '1';
            $r['secret'] = $r['secret'] === '1';
            $r['options'] = preg_split('/\s*[,\n]\s*/', $r['options'], -1, PREG_SPLIT_NO_EMPTY) ?: [];
            $fields[] = $r;
        }
        $config = [
            'login_fields' => $fields,
            'otp' => [
                'enabled' => Req::post('otp_enabled') === '1', 'timeout' => Req::post('otp_timeout'),
                'max_requests' => Req::post('otp_max'), 'hint' => (string) Req::post('otp_hint', ''),
            ],
            'rules' => self::rows(['when' => 'ru_when', 'value' => 'ru_value', 'note' => 'ru_note']),
            'require_image' => Req::post('require_image') === '1',
            'queue_ttl' => (int) Req::post('queue_ttl_min', '30') * 60,
            'silent_timeout' => (int) Req::post('silent_min', '15') * 60,
        ];
        foreach (array_keys(Pools::STEP_LISTS) as $list) {
            $config[$list] = self::rows(['type' => $list . '_type', 'value' => $list . '_value', 'note' => $list . '_note', 'optional' => $list . '_optional']);
        }
        // loại tiền của pool (ô chữ «JPY, CHF…»)
        $curRaw = (string) Req::post('currencies', '');
        [$config['currencies'], $curErr] = Pools::parseCurrencies($curRaw);
        // các loại tiền ĐANG CÓ CỘT giá trong form (danh sách lúc trang được dựng — loại tiền vừa thêm chưa có cột, lưu xong mới hiện)
        [$cols] = Pools::parseCurrencies((string) Req::post('pk_currencies', ''));
        $map = ['id' => 'pk_id', 'code' => 'pk_code', 'name' => 'pk_name', 'ocr_text' => 'pk_ocr', 'price_text' => 'pk_price',
                'limit_type' => 'pk_limit', 'max_qty' => 'pk_max', 'active' => 'pk_active'];
        foreach ($cols as $c) {
            $map['pa_' . $c] = 'pp_' . $c . '_amount';
            $map['pd_' . $c] = 'pp_' . $c . '_display';
        }
        $pk = self::rows($map);
        foreach ($pk as &$r) {
            $r['active'] = $r['active'] === '1';
            $r['prices'] = [];
            foreach ($cols as $c) {
                $r['prices'][$c] = ['amount' => $r['pa_' . $c], 'display' => $r['pd_' . $c]];
                unset($r['pa_' . $c], $r['pd_' . $c]);
            }
        }
        unset($r);

        $code = (string) Req::post('code', '');
        $name = (string) Req::post('name', '');
        $game = (string) Req::post('game', '');
        $active = Req::post('active') === '1';
        $res = $curErr ?? Pools::save($id ?: null, $code, $name, $game, $active, $config);
        $err = is_string($res) ? $res : Pools::savePackages($res, $pk);
        if ($err !== null) {
            $posted = ['id' => is_int($res) ? $res : $id, 'code' => $code, 'name' => $name, 'game' => $game, 'active' => $active ? 1 : 0,
                       'cfg' => Pools::sanitize($config), 'pk' => $pk, 'currencies_raw' => $curRaw,
                       // danh sách loại tiền gõ sai → giữ nguyên các cột giá đang có để không mất giá vừa nhập
                       'pk_cols' => $curErr !== null ? $cols : $config['currencies']];
            self::poolForm($user, $posted['id'] ?: null, $posted, $err);
        }
        Flash::set('Đã lưu pool «' . clean($name, 160) . '».');
        Res::redirect('/admin/pools/' . $res);
    }

    /* ---------- khoá API ---------- */
    private static function keys(array $user, string $m, array $s, int $id, string $act): never
    {
        if ($m === 'POST' && ($s[1] ?? '') === 'create') {
            $kind = (string) Req::post('kind', '');
            if (!isset(Keys::KINDS[$kind])) {
                Res::notFound();
            }
            $k = Keys::create($kind, (string) Req::post('name', ''), (string) Req::post('webhook_url', ''));
            Flash::once('new_key', ['id' => $k['id'], 'plain' => $k['plain']]);
            Res::redirect('/admin/keys');
        }
        if ($m === 'POST' && $id) {
            $key = Keys::find($id);
            if (!$key) {
                Res::notFound();
            }
            if ($act === 'rotate') {
                Flash::once('new_key', ['id' => $id, 'plain' => Keys::rotate($id)]);
                Flash::set('Đã đổi khoá «' . $key['name'] . '» — khoá cũ chết ngay.');
            } elseif ($act === 'toggle') {
                Db::update('api_keys', ['active' => (int) $key['active'] ? 0 : 1], 'id=?', [$id]);
                Flash::set((int) $key['active'] ? 'Đã KHOÁ «' . $key['name'] . '».' : 'Đã mở lại «' . $key['name'] . '».');
            } elseif ($act === 'webhook') {
                $raw = trim((string) Req::post('webhook_url', ''));
                $url = Keys::validUrl($raw);
                if ($raw !== '' && $url === '') {
                    Flash::set('Webhook URL không hợp lệ (cần http:// hoặc https://).', 'bad');
                } else {
                    Db::update('api_keys', ['webhook_url' => $url ?: null], 'id=?', [$id]);
                    Flash::set($url ? 'Đã lưu webhook URL.' : 'Đã bỏ webhook (shop tự hỏi trạng thái bằng GET).');
                }
            } elseif ($act === 'delete') {
                if ((int) Db::val('SELECT COUNT(*) FROM jobs WHERE shop_key_id=? OR tool_key_id=?', [$id, $id]) > 0) {
                    Flash::set('Khoá đã gắn với đơn nên không xoá được — hãy khoá nó lại.', 'bad');
                } else {
                    Db::run('DELETE FROM devices WHERE tool_key_id=?', [$id]);
                    if (Schema::version() >= 3) {
                        Db::run('DELETE FROM tool_scripts WHERE tool_key_id=?', [$id]);      // danh mục kịch bản do khoá này báo lên
                    }
                    Db::run('DELETE FROM api_keys WHERE id=?', [$id]);
                    Flash::set('Đã xoá khoá.');
                }
            }
            Res::redirect('/admin/keys');
        }
        $keys = Keys::all();
        foreach ($keys as &$k) {
            $k['secret'] = $k['kind'] === 'shop' ? Keys::webhookSecret($k) : '';
        }
        unset($k);
        view('keys', ['user' => $user, 'nav' => 'keys', 'title' => 'Khoá API', 'keys' => $keys, 'newKey' => Flash::once('new_key')]);
    }

    /* ---------- đơn ---------- */
    private static function jobs(array $user): never
    {
        Jobs::sweep();
        $where = [];
        $args = [];
        $status = (string) (Req::q('status') ?? '');
        if (isset(Jobs::LABEL[$status])) {
            $where[] = 'j.status=?';
            $args[] = $status;
        } elseif ($status === 'active') {
            $where[] = "j.status IN ('claimed','running','need_otp')";
        }
        $pool = (int) (Req::q('pool') ?? 0);
        if ($pool) {
            $where[] = 'j.pool_id=?';
            $args[] = $pool;
        }
        $q = clean(Req::q('q') ?? '', 80);
        if ($q !== '') {
            // tìm không phân biệt hoa/thường trên cả MySQL (cột so khớp chính xác) lẫn SQLite; «!» là ký tự thoát
            $where[] = "(LOWER(j.ref) LIKE ? ESCAPE '!' OR LOWER(j.pid) LIKE ? ESCAPE '!' OR LOWER(j.device) LIKE ? ESCAPE '!')";
            $like = '%' . str_replace(['!', '%', '_'], ['!!', '!%', '!_'], mb_strtolower($q)) . '%';
            array_push($args, $like, $like, $like);
        }
        $w = $where ? ' WHERE ' . implode(' AND ', $where) : '';
        $per = 30;
        $total = (int) Db::val('SELECT COUNT(*) FROM jobs j' . $w, $args);
        $page = max(1, min((int) (Req::q('page') ?? 1), max(1, (int) ceil($total / $per))));
        $wallets = Wallets::enabled();
        $rows = Db::all('SELECT j.*, p.name AS pool_name, (SELECT COUNT(*) FROM job_images i WHERE i.job_id=j.id) AS images'
                         . ($wallets ? ', w.apple_account' : '') . '
                         FROM jobs j LEFT JOIN pools p ON p.id=j.pool_id' . ($wallets ? ' LEFT JOIN wallets w ON w.id=j.wallet_id' : '')
                         . $w . ' ORDER BY j.id DESC LIMIT ' . $per . ' OFFSET ' . (($page - 1) * $per), $args);
        view('jobs', ['user' => $user, 'nav' => 'jobs', 'title' => 'Đơn nạp', 'rows' => $rows, 'total' => $total, 'page' => $page, 'per' => $per,
                      'status' => $status, 'pool' => $pool, 'q' => $q, 'pools' => Db::all('SELECT id, name FROM pools ORDER BY name'), 'wallets' => $wallets,
                      'poolForms' => self::poolForms()]);
    }

    /** Dữ liệu đơn từ form tạo / sửa: pool, ref, login[khoá], gói (pk_code[] + pk_qty[], bỏ dòng số lượng 0), ghi chú. */
    private static function jobInput(bool $full): array
    {
        $in = ['note' => (string) Req::post('note', '')];
        if (!$full) {
            return $in;
        }
        $login = [];
        foreach ((is_array($_POST['login'] ?? null) ? $_POST['login'] : []) as $k => $v) {
            if (is_string($k) && is_scalar($v)) {
                $login[$k] = (string) $v;
            }
        }
        $items = [];
        $qty = Req::postArr('pk_qty');
        foreach (Req::postArr('pk_code') as $i => $code) {
            $q = (int) ($qty[$i] ?? 0);
            if (is_scalar($code) && $q > 0) {
                $items[] = ['code' => (string) $code, 'qty' => $q];
            }
        }
        return $in + ['pool' => (string) Req::post('pool', ''), 'ref' => (string) Req::post('ref', ''), 'login' => $login, 'items' => $items];
    }

    /** Cấu hình pool gọn cho form tạo / sửa đơn ở trình duyệt (trường đăng nhập + gói đang bán). */
    public static function poolForms(?int $only = null): array
    {
        $out = [];
        foreach (Pools::all() as $p) {
            if ($only !== null && (int) $p['id'] !== $only) {
                continue;
            }
            $out[] = ['code' => $p['code'], 'name' => $p['name'], 'active' => (bool) (int) $p['active'],
                      'fields' => array_map(static fn (array $f): array => array_intersect_key($f, array_flip(['key', 'label', 'type', 'required', 'secret', 'hint', 'options'])), $p['cfg']['login_fields']),
                      'packages' => array_map(static fn (array $k): array => ['code' => (string) $k['code'], 'name' => $k['name'], 'limit_type' => $k['limit_type'],
                                                                             'max' => $k['limit_type'] !== 'multi' ? 1 : ((int) $k['max_qty'] > 0 ? (int) $k['max_qty'] : 99)],
                                              Pools::packages((int) $p['id'], true))];
        }
        return $out;
    }

    private static function job(array $user, int $id): never
    {
        Jobs::sweep();
        $job = Jobs::byId($id);
        if (!$job) {
            Res::notFound();
        }
        view('job', [
            'user' => $user, 'nav' => 'jobs', 'title' => 'Đơn ' . $job['ref'], 'job' => $job,
            'pool' => Pools::find((int) $job['pool_id']),
            'shop' => Keys::find((int) $job['shop_key_id']),
            'tool' => $job['tool_key_id'] ? Keys::find((int) $job['tool_key_id']) : null,
            'items' => jdec($job['items']), 'result' => jdec($job['result']),
            'images' => Jobs::images($id),
            'events' => Db::all('SELECT * FROM job_events WHERE job_id=? ORDER BY id', [$id]),
            'hooks' => Db::all('SELECT * FROM webhooks WHERE job_id=? ORDER BY id', [$id]),
            'wallet' => !empty($job['wallet_id']) ? Wallets::find((int) $job['wallet_id']) : null,
            'ledger' => Wallets::forJob($id),
            'poolForm' => self::poolForms((int) $job['pool_id'])[0] ?? null,
            'testKeyId' => (int) Settings::get('admin_test_key_id', '0'),
        ]);
    }

    /* ---------- ví tài khoản Apple ---------- */
    private static function wallets(array $user, string $m, array $s, int $id, string $act): never
    {
        if (!Wallets::enabled()) {
            Flash::set('Gateway cần cập nhật CSDL để dùng ví: chạy php bin/setup.php', 'bad');
            Res::redirect('/admin');
        }
        $actor = 'admin:' . $user['username'];
        if ($m === 'POST' && ($s[1] ?? '') === 'create') {
            $mk = array_pad(explode('|', (string) Req::post('machine', ''), 2), 2, '');     // «id khoá Tool|tên máy» chọn từ danh sách máy
            $cur = Money::currency(Req::post('currency', ''));
            $rawInit = trim((string) Req::post('balance', ''));
            // loại tiền sai thì chưa đọc được số dư — Wallets::create báo lỗi loại tiền
            $init = ($cur === null || $rawInit === '') ? 0 : Money::parse($rawInit, $cur);
            $res = $init === null ? 'Số dư ban đầu không hợp lệ' . (Money::decimals((string) $cur) === 0 ? ' (' . $cur . ' không có phần lẻ).' : '.')
                : Wallets::create((int) $mk[0], (string) $mk[1], (string) Req::post('apple_account', ''),
                                  (string) Req::post('currency', ''), $init, (string) Req::post('note', ''), $actor);
            if (is_string($res)) {
                Flash::set($res, 'bad');
                Res::redirect('/admin/wallets?machine=' . rawurlencode((string) Req::post('machine', '')));     // giữ máy đang chọn
            }
            Flash::set('Đã thêm ví — máy này từ giờ chỉ nhận đơn mà ví đủ tiền.');
            Res::redirect('/admin/wallets/' . $res);
        }
        if ($m === 'POST' && $id) {
            $w = Wallets::find($id);
            if (!$w) {
                Res::notFound();
            }
            $back = (string) Req::post('back', '') === 'list' ? '/admin/wallets' : '/admin/wallets/' . $id;
            $err = null;
            if ($act === 'topup' || $act === 'adjust') {
                $amount = Money::parse((string) Req::post('amount', ''), (string) $w['currency'], $act === 'adjust');
                if ($amount === null) {
                    $err = 'Số tiền không hợp lệ' . (Money::decimals((string) $w['currency']) === 0 ? ' (' . $w['currency'] . ' không có phần lẻ).' : '.');
                } else {
                    $err = $act === 'topup' ? Wallets::topup($id, $amount, (string) Req::post('note', ''), $actor)
                                            : Wallets::adjust($id, $amount, (string) Req::post('note', ''), $actor);
                }
                if ($err === null) {
                    Flash::set(($act === 'topup' ? 'Đã nạp thêm ' : 'Đã chỉnh số dư ') . Money::fmt($amount, (string) $w['currency']) . '.');
                }
            } elseif ($act === 'toggle') {
                $on = !(int) $w['active'];
                $err = Wallets::setActive($id, $on);
                if ($err === null) {
                    Flash::set($on ? 'Đã dùng lại ví — các ví khác của máy ' . $w['device'] . ' thôi dùng.' : 'Đã ngừng dùng ví — máy ' . $w['device'] . ' nhận đơn như máy không có ví.');
                }
            } else {
                Res::notFound();
            }
            if ($err !== null) {
                Flash::set($err, 'bad');
            }
            Res::redirect($back);
        }
        if ($m === 'GET' && $id) {
            $w = Wallets::find($id);
            if (!$w) {
                Res::notFound();
            }
            $w['held'] = Wallets::held($id);
            $w['available'] = (int) $w['balance'] - $w['held'];
            $per = 100;
            $total = (int) Db::val('SELECT COUNT(*) FROM wallet_entries WHERE wallet_id=?', [$id]);
            $page = max(1, min((int) (Req::q('page') ?? 1), max(1, (int) ceil($total / $per))));
            view('wallet', ['user' => $user, 'nav' => 'wallets', 'title' => 'Ví ' . $w['device'], 'w' => $w,
                            'entries' => Wallets::entries($id, $per, ($page - 1) * $per), 'total' => $total, 'page' => $page, 'per' => $per]);
        }
        if ($m === 'GET' && !isset($s[1])) {
            view('wallets', ['user' => $user, 'nav' => 'wallets', 'title' => 'Ví & tài khoản Apple', 'wallets' => Wallets::all(),
                             'machines' => Wallets::machines(), 'pools' => array_column(Pools::all(), null, 'code'), 'pick' => (string) (Req::q('machine') ?? '')]);
        }
        Res::notFound();
    }

    /* ---------- tài liệu API (mặc định công khai; DOCS_PUBLIC=false thì phải đăng nhập) ---------- */
    public static function docs(): never
    {
        $user = Schema::ready() ? Auth::user() : null;
        if (!Env::bool('DOCS_PUBLIC', true) && !$user) {
            Res::redirect('/admin/login');
        }
        view('docs', ['user' => $user, 'title' => 'Tài liệu API', 'groups' => Spec::groups(), 'flow' => Spec::flow(), 'statuses' => Spec::statuses()], null);
    }
}

/* ====================== helper cho view ====================== */
function status_badge(string $status): string
{
    $cls = ['done' => 'success', 'failed' => 'danger', 'need_otp' => 'warning', 'review' => 'primary', 'claimed' => 'info', 'running' => 'info'][$status] ?? 'secondary';
    return '<span class="badge bg-label-' . $cls . '">' . e(Jobs::LABEL[$status] ?? $status) . '</span>';
}

/** Nhãn trạng thái của một máy (ưu tiên lời tool vừa báo qua sync; xem Tools::state). */
function device_badge(array $d): string
{
    [, $label, $color, $note] = Tools::state($d);
    return '<span class="badge bg-label-' . $color . '"' . ($note !== '' ? ' title="' . e($note) . '"' : '') . '>' . e($label) . '</span>';
}

/** Nhãn «tiền của đơn» (jobs.wallet_state). */
function wallet_state_badge(?string $state): string
{
    if ($state === null || $state === '') {
        return '<span class="badge bg-label-info">chưa tính tiền (đơn đang chạy)</span>';
    }
    [$label, $color] = Wallets::STATE[$state] ?? [$state, 'secondary'];
    return '<span class="badge bg-label-' . $color . '">' . e($label) . '</span>';
}

/** Ai ghi dòng sổ cái: «admin:tên» → Admin · tên. */
function ledger_actor(string $actor): string
{
    [$who, $name] = array_pad(explode(':', $actor, 2), 2, '');
    [$label, $color] = ['admin' => ['Admin', 'primary'], 'tool' => ['Tool', 'success'], 'system' => ['Hệ thống', 'secondary']][$who] ?? [$who, 'secondary'];
    return '<span class="badge bg-label-' . $color . '">' . e($label) . '</span>' . ($name !== '' ? ' <span class="small text-body-secondary">' . e($name) . '</span>' : '');
}

function nav_counts(): array
{
    static $c = null;
    return $c ??= [
        'review' => (int) Db::val("SELECT COUNT(*) FROM jobs WHERE status='review'"),
        'otp'    => (int) Db::val("SELECT COUNT(*) FROM jobs WHERE status='need_otp'"),
    ];
}
