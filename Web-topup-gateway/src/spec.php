<?php
declare(strict_types=1);

/**
 * spec.php — MÔ TẢ API (một nguồn duy nhất). Trang /docs dựng từ đây nên tài liệu
 * luôn khớp với hợp đồng. Sửa API thì sửa ở đây cùng lúc.
 */
final class Spec
{
    /** Luồng 3 bên cho sơ đồ tuần tự: [từ, tới, nhãn, ghi chú]. Bên: shop | gw | tool */
    public static function flow(): array
    {
        return [
            ['shop', 'gw',   'POST /api/shop/jobs',                 'Khách thanh toán xong → shop đẩy đơn (tài khoản + gói)'],
            ['tool', 'gw',   'POST /api/tool/claim',                'Máy trống báo "tôi rảnh" → nhận 1 đơn + thông tin đăng nhập'],
            ['gw',   'shop', 'webhook job.claimed',                 'Shop biết đơn đã có máy nhận'],
            ['tool', 'gw',   'POST …/progress {stage: login}',      'Máy đang đăng nhập game'],
            ['tool', 'gw',   'POST …/otp/request',                  'Game đòi OTP → máy xin OTP'],
            ['gw',   'shop', 'webhook job.need_otp',                'Shop hiện ô nhập OTP cho khách'],
            ['shop', 'gw',   'POST …/otp {otp}',                    'Khách nhập OTP → shop chuyển sang'],
            ['tool', 'gw',   'GET …/otp?wait=20',                   'Máy lấy OTP về, nhập vào game'],
            ['tool', 'gw',   'POST …/progress {stage: purchasing}', 'Đăng nhập xong, đang mua gói'],
            ['tool', 'gw',   'POST …/images?seq=1',                 'Gửi ảnh bill / ảnh màn hình'],
            ['tool', 'gw',   'POST …/result {result: done}',        'Báo kết quả cuối'],
            ['gw',   'shop', 'webhook job.done (+ link ảnh)',       'Shop hoàn tất đơn, khách xem & tải ảnh'],
        ];
    }

    public static function statuses(): array
    {
        return [
            ['queued',    'Chờ máy trống',        'Đơn nằm trong hàng đợi của pool. Shop còn huỷ được.'],
            ['claimed',   'Đã giao máy',          'Một máy đã nhận (chỉ giao ĐÚNG MỘT LẦN). Từ đây shop không huỷ được.'],
            ['running',   'Đang xử lý',           'Máy đang đăng nhập / mua gói. Xem `stage` để biết bước.'],
            ['need_otp',  'Chờ OTP',              'Game đòi OTP. Shop phải lấy OTP từ khách và gọi …/otp trước `otp.deadline`.'],
            ['done',      'Hoàn tất',             'Đã nạp xong, có ảnh. KẾT THÚC.'],
            ['failed',    'Thất bại (chưa nạp)',  'Máy CAM KẾT chưa gửi lệnh trả tiền nào (sai mật khẩu, hết hạn OTP…). Shop xử lý tay / hoàn tiền. KẾT THÚC.'],
            ['review',    'Chờ đối soát',         'Không chắc đã nạp hay chưa (tool im lặng, báo xong thiếu ảnh, tool không chắc). Admin gateway chốt → done/failed.'],
            ['cancelled', 'Đã huỷ',               'Shop huỷ khi còn `queued`. KẾT THÚC.'],
            ['expired',   'Quá hạn chờ',          'Không máy nào nhận trong thời gian chờ của pool. Shop xử lý tay. KẾT THÚC.'],
        ];
    }

    private static function job(string $status, array $over = []): string
    {
        $job = array_merge([
            'id' => 'J9F2C4A7B1D3E5F60', 'ref' => 'NG261205A1B2C', 'pool' => 'efootball-ios',
            'status' => $status, 'status_label' => Jobs::LABEL[$status] ?? $status, 'stage' => $status, 'message' => null,
            'review_reason' => null, 'device' => $status === 'queued' ? null : 'iPhoneFarm-01',
            'otp' => ['state' => 'none', 'seq' => 0, 'deadline' => null, 'message' => null],
            'items' => [['code' => 'coin_1050', 'name' => '1050 eFootball Coins', 'qty' => 1]],
            'result' => null, 'images' => [], 'note' => null,
            'created_at' => '2026-12-05T03:04:05Z', 'claimed_at' => $status === 'queued' ? null : '2026-12-05T03:04:40Z',
            'finished_at' => null, 'updated_at' => '2026-12-05T03:04:40Z',
        ], $over);
        return json_encode($job, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    private static function wrap(string $key, string $json, array $extra = []): string
    {
        $pre = ['ok' => true] + $extra;
        $head = rtrim(json_encode($pre, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), "}\n");
        return $head . ",\n    \"$key\": " . str_replace("\n", "\n    ", $json) . "\n}";
    }

    public static function groups(): array
    {
        $img = [['seq' => 1, 'kind' => 'bill', 'mime' => 'image/png', 'size' => 184220,
                 'url' => 'https://gateway.example.com/files/3f9a…c21.png', 'download_url' => 'https://gateway.example.com/files/3f9a…c21.png?download=1', 'created_at' => '2026-12-05T03:09:10Z']];
        $doneJob = self::job('done', ['stage' => 'done', 'finished_at' => '2026-12-05T03:09:20Z', 'images' => $img,
                    'result' => [['code' => 'coin_1050', 'qty_done' => 1, 'status' => 'done', 'message' => '']]]);
        $otpJob = self::job('need_otp', ['stage' => 'otp', 'otp' => ['state' => 'waiting', 'seq' => 1, 'deadline' => '2026-12-05T03:10:00Z', 'message' => 'Mã đã gửi về email k***@gmail.com']]);
        $authErr = [[401, 'unauthorized', 'Thiếu/sai khoá'], [429, 'too_many', 'Sai khoá ≥ 30 lần/10 phút từ một IP (khoá đúng vẫn luôn qua)']];

        return [
            [
                'id' => 'shop', 'title' => 'Shop → Gateway', 'badge' => 'shop',
                'intro' => 'Website bán hàng gọi các API này bằng khoá <code>gws_…</code>. Shop <b>đẩy đơn đã thanh toán</b> sang, chuyển <b>OTP khách nhập</b>, và đọc <b>kết quả + ảnh</b>.',
                'endpoints' => [
                    ['m' => 'GET', 'p' => '/api/shop/ping', 't' => 'Kiểm tra khoá', 'd' => 'Dùng để thử kết nối + khoá.',
                     'res' => "{\n    \"ok\": true,\n    \"key\": \"Shop ABC\",\n    \"server_time\": \"2026-12-05T03:04:05Z\"\n}", 'errors' => $authErr],
                    ['m' => 'GET', 'p' => '/api/shop/pools', 't' => 'Danh sách pool + trường đăng nhập + gói nạp',
                     'd' => 'Shop đọc để biết mỗi pool cần khách nhập <b>những trường gì</b> (<code>login_fields</code>), có OTP không, và <b>mã gói</b> nào bán được. Có cả <code>GET /api/shop/pools/{code}</code> cho một pool.',
                     'res' => "{\n    \"ok\": true,\n    \"pools\": [\n        {\n            \"code\": \"efootball-ios\",\n            \"name\": \"eFootball (iOS) — đăng nhập Konami ID\",\n            \"game\": \"eFootball\",\n            \"active\": true,\n            \"login_fields\": [\n                {\"key\": \"username\", \"label\": \"Email Konami ID\", \"type\": \"text\", \"required\": true, \"secret\": false, \"hint\": \"\", \"options\": []},\n                {\"key\": \"password\", \"label\": \"Mật khẩu\", \"type\": \"password\", \"required\": true, \"secret\": true, \"hint\": \"\", \"options\": []}\n            ],\n            \"otp\": {\"enabled\": true, \"timeout\": 300, \"max_requests\": 3, \"hint\": \"Mã gửi về email của tài khoản.\"},\n            \"packages\": [\n                {\"code\": \"coin_1050\", \"name\": \"1050 eFootball Coins\", \"limit_type\": \"multi\", \"max_qty\": 0},\n                {\"code\": \"starter_pack\", \"name\": \"Gói khởi đầu\", \"limit_type\": \"once\", \"max_qty\": 0}\n            ]\n        }\n    ]\n}"],
                    ['m' => 'POST', 'p' => '/api/shop/jobs', 't' => 'Tạo đơn nạp (đẩy đơn đã thanh toán)',
                     'd' => 'Gọi khi đơn <b>đã thanh toán</b>. <b>Idempotent theo <code>ref</code></b>: gửi lại cùng <code>ref</code> trả về đơn cũ (<code>"duplicate": true</code>, HTTP 200), không bao giờ tạo đơn thứ hai → mất mạng cứ gửi lại y nguyên. Thông tin đăng nhập được <b>mã hoá khi lưu</b> và <b>xoá ngay khi đơn kết thúc</b>.',
                     'body' => [
                         ['pool', 'string', true, 'Mã pool (vd <code>efootball-ios</code>).'],
                         ['ref', 'string', true, 'Mã đơn của shop, 1–80 ký tự <code>A-Z a-z 0-9 _ . : -</code>. Khoá chống trùng.'],
                         ['login', 'object', true, 'Các trường đăng nhập đúng theo <code>login_fields</code> của pool.'],
                         ['items', 'array', true, '1–30 dòng <code>{code, qty}</code>. Gói <code>limit_type ≠ multi</code> chỉ nhận <code>qty = 1</code>.'],
                         ['note', 'string', false, 'Ghi chú cho người vận hành (≤ 500 ký tự).'],
                     ],
                     'req' => "{\n    \"pool\": \"efootball-ios\",\n    \"ref\": \"NG261205A1B2C\",\n    \"login\": {\"username\": \"khach@example.com\", \"password\": \"MatKhau#123\"},\n    \"items\": [{\"code\": \"coin_1050\", \"qty\": 1}],\n    \"note\": \"Khách VIP\"\n}",
                     'res' => self::wrap('job', self::job('queued')),
                     'resCode' => 201,
                     'errors' => [[404, 'pool_not_found', 'Sai mã pool'], [409, 'pool_paused', 'Pool đang tạm dừng → shop xử lý tay'],
                                  [422, 'invalid_ref', 'ref sai định dạng'], [422, 'missing_field', 'Thiếu trường bắt buộc (xem <code>field</code>)'],
                                  [422, 'unknown_package', 'Mã gói không có / đang tắt'], [422, 'qty_limit', 'Vượt số lượng cho phép của gói'],
                                  [422, 'already_bought', 'Gói <code>limit_type: once</code> mà <b>tài khoản game này</b> (ô chữ <b>bắt buộc</b>, không bí mật đầu tiên của <code>login</code>, vd email — không phân biệt hoa/thường; pool không có ô như vậy thì dùng tất cả ô không bí mật) đã có một đơn khác của cùng pool mua gói đó và đơn ấy chưa thất bại / huỷ / quá hạn. Có thêm <code>code</code> = mã gói. Đơn trước <code>failed</code> / <code>cancelled</code> / <code>expired</code> thì mua lại được.']]],
                    ['m' => 'GET', 'p' => '/api/shop/jobs/{id}', 't' => 'Xem trạng thái + kết quả + ảnh',
                     'd' => 'Đọc bất cứ lúc nào (dự phòng khi lỡ webhook). <code>images[].url</code> là link ảnh <b>công khai không đoán được</b> — đưa thẳng cho khách xem; <code>download_url</code> để tải về.',
                     'res' => self::wrap('job', $doneJob), 'errors' => [[404, 'job_not_found', 'Sai id hoặc đơn của khoá khác']]],
                    ['m' => 'POST', 'p' => '/api/shop/jobs/{id}/otp', 't' => 'Gửi OTP khách vừa nhập',
                     'd' => 'Chỉ nhận khi đơn đang <code>need_otp</code> và chưa quá <code>otp.deadline</code>. Gửi lại (khách nhập nhầm) được cho tới khi máy lấy mã. Nếu mã sai, máy sẽ xin lại → shop nhận webhook <code>job.need_otp</code> mới với <code>reason: "wrong"</code>.',
                     'body' => [['otp', 'string', true, '3–12 ký tự chữ/số (khoảng trắng bị bỏ).']],
                     'req' => "{\"otp\": \"482913\"}",
                     'res' => "{\n    \"ok\": true,\n    \"otp\": {\"state\": \"submitted\", \"seq\": 1}\n}",
                     'errors' => [[409, 'not_waiting_otp', 'Đơn không chờ OTP'], [409, 'otp_expired', 'Quá hạn lần xin này'], [422, 'invalid_otp', 'OTP sai định dạng']]],
                    ['m' => 'POST', 'p' => '/api/shop/jobs/{id}/cancel', 't' => 'Huỷ đơn còn trong hàng chờ',
                     'd' => 'Chỉ huỷ được khi còn <code>queued</code>. Đã giao máy thì trả 409 (tránh vừa huỷ vừa nạp).',
                     'res' => "{\n    \"ok\": true,\n    \"status\": \"cancelled\"\n}",
                     'errors' => [[409, 'not_cancellable', 'Đơn đã giao cho máy']]],
                ],
            ],
            [
                'id' => 'webhook', 'title' => 'Gateway → Shop (webhook)', 'badge' => 'gw',
                'intro' => 'Mỗi khi đơn đổi trạng thái, gateway <b>POST JSON</b> tới <i>Webhook URL</i> của khoá shop (đặt ở trang Khoá API). Trả HTTP <b>2xx</b> thật nhanh (nên dưới <b>2 giây</b> — lần gửi đầu trên máy chủ không phải PHP-FPM chỉ chờ 2 giây, các lần sau 6 giây) là nhận xong; không thì gateway thử lại sau 30s → 2′ → 10′ → 30′ → 1h → 2h. Vì có thử lại nên shop có thể nhận <b>trùng</b> một sự kiện: xử lý theo trạng thái của <code>job</code>, đừng theo số lần nhận. Webhook chỉ là <b>tín hiệu</b>: luôn có thể đọc lại bằng <code>GET /api/shop/jobs/{id}</code>.',
                'events' => [
                    ['job.claimed',  'Đã có máy nhận đơn.'],
                    ['job.progress', 'Máy đổi bước (<code>job.stage</code>: login, logged_in, purchasing…).'],
                    ['job.need_otp', 'Cần OTP. Có thêm <code>reason</code>: first | wrong | expired | resend. Hiện ô nhập cho khách, hạn ở <code>job.otp.deadline</code>.'],
                    ['job.done',     'Nạp xong. <code>job.images</code> có link ảnh, <code>job.result</code> có kết quả từng gói. Có thêm <code>corrected: true</code> + <code>previous_status</code> khi admin gateway <b>sửa kết quả đã chốt</b> (vd đơn đã báo thất bại nhưng kiểm lại thấy đã nạp) → cập nhật đơn theo trạng thái mới.'],
                    ['job.failed',   'Thất bại, CHƯA nạp gì. Lý do ở <code>job.message</code>. Có thêm <code>corrected: true</code> + <code>previous_status: "done"</code> khi admin gateway sửa một đơn đã báo hoàn tất thành thất bại → shop xử lý tay / hoàn tiền cho khách.'],
                    ['job.review',   'Chờ admin gateway đối soát (tool báo không chắc, tool im lặng, hoặc admin tự chuyển đơn đang chạy sang đối soát). ĐỪNG hoàn tiền cho tới khi nhận <code>job.done</code>/<code>job.failed</code>.'],
                    ['job.expired',  'Không máy nào nhận trong thời gian chờ → shop xử lý tay.'],
                    ['job.cancelled', 'Đơn bị huỷ khi còn chờ máy. Có thêm <code>by</code>: <code>shop</code> (chính shop gọi …/cancel) | <code>admin</code> (admin gateway huỷ) → shop xử lý tay / hoàn tiền.'],
                ],
                'headers' => [
                    ['X-Gateway-Event', 'Tên sự kiện, vd <code>job.need_otp</code>'],
                    ['X-Gateway-Delivery', 'Số thứ tự lần gửi (dùng để bỏ trùng)'],
                    ['X-Gateway-Signature', '<code>sha256=</code> + HMAC-SHA256 của <b>thân thô</b> với <i>Webhook secret</i>'],
                ],
                'payload' => "{\n    \"event\": \"job.need_otp\",\n    \"sent_at\": \"2026-12-05T03:05:00Z\",\n    \"reason\": \"first\",\n    \"job\": " . str_replace("\n", "\n    ", $otpJob) . "\n}",
                'verify' => "<?php // phía shop: kiểm chữ ký TRƯỚC khi tin nội dung\n\$body = file_get_contents('php://input');\n\$sig  = \$_SERVER['HTTP_X_GATEWAY_SIGNATURE'] ?? '';\n\$want = 'sha256=' . hash_hmac('sha256', \$body, \$WEBHOOK_SECRET);\nif (!hash_equals(\$want, \$sig)) { http_response_code(401); exit; }\n\$data = json_decode(\$body, true);\n// \$data['event'], \$data['job']['ref'], \$data['job']['status'] …\nhttp_response_code(200);",
                'endpoints' => [],
            ],
            [
                'id' => 'tool', 'title' => 'Tool → Gateway', 'badge' => 'tool',
                'intro' => 'Máy nạp (iPhone farm…) gọi các API này bằng khoá <code>gwt_…</code>. Gateway <b>không gọi ra tool</b>: tool tự <b>xin việc khi máy trống</b>, tự hỏi OTP, tự báo kết quả.',
                'endpoints' => [
                    ['m' => 'POST', 'p' => '/api/tool/heartbeat', 't' => 'Nhịp tim + khai máy',
                     'd' => 'Gọi mỗi ~30–60 giây. <code>active</code> = các đơn tool đang giữ → được làm mới "còn sống". Đơn đang chạy mà tool <b>im lặng quá thời gian của pool</b> (mặc định 15 phút) sẽ sang <code>review</code>.',
                     'body' => [['devices', 'array', false, 'Danh sách máy <code>{name, pool, state: free|busy, job}</code> để hiện ở trang quản trị.'],
                                ['active', 'array', false, 'Các <code>job id</code> đang giữ.']],
                     'req' => "{\n    \"devices\": [\n        {\"name\": \"iPhoneFarm-01\", \"pool\": \"efootball-ios\", \"state\": \"busy\", \"job\": \"J9F2C4A7B1D3E5F60\"},\n        {\"name\": \"iPhoneFarm-02\", \"pool\": \"efootball-ios\", \"state\": \"free\"}\n    ],\n    \"active\": [\"J9F2C4A7B1D3E5F60\"]\n}",
                     'res' => "{\n    \"ok\": true,\n    \"server_time\": \"2026-12-05T03:04:05Z\"\n}", 'errors' => $authErr],
                    ['m' => 'POST', 'p' => '/api/tool/sync', 't' => 'Tool tự báo: máy nào rảnh ở kịch bản nào + danh mục kịch bản',
                     'd' => 'Gateway nằm ngoài Internet còn tool nằm trong mạng nội bộ, nên <b>chỉ tool gọi lên được</b>: mọi thứ gateway biết về máy và kịch bản đều đến từ API này. Gọi <b>mỗi ~20 giây</b> và <b>ngay khi có thay đổi</b> (máy bắt đầu / xong việc, bị dừng, sửa kịch bản). Xem kết quả ở trang <b>Kịch bản &amp; máy</b>.'
                          . '<br>• <code>devices</code> là <b>ảnh chụp toàn bộ</b> máy của tool lúc này: máy không còn trong danh sách bị coi là đã gỡ khỏi tool. Tool im quá <b>90 giây</b> thì lời báo cũ không còn được tin (máy hiện «mất kết nối», không máy nào được tính là rảnh). Máy mà gateway còn ghi đang <b>đứng tên một đơn</b> cũng không được tính là rảnh, dù tool báo <code>idle</code>. Lời báo bị từ chối (4xx) thì <b>không ghi gì</b>.'
                          . '<br>• <code>status</code> của máy: <code>idle</code> rảnh, sẵn sàng chạy · <code>running</code> đang chạy kịch bản · <code>orders</code> đang nhận đơn (chế độ API) · <code>paused</code> người vận hành bấm Dừng máy · <code>hold</code> dừng chờ kiểm tra sau đơn của khách · <code>manual</code> đang được điều khiển tay · <code>offline</code> chưa sẵn sàng (lý do ở <code>note</code>). Giá trị lạ bị coi là <code>offline</code> — <b>không bao giờ</b> thành rảnh.'
                          . '<br>• <b>Danh mục kịch bản chỉ gửi khi đổi</b>: tool luôn gửi <code>scripts_rev</code> (mã băm của danh mục); phản hồi có <code>"need_scripts": true</code> nghĩa là bản gateway đang giữ khác bản của tool → gửi lại ngay kèm <code>scripts</code>. <code>scripts</code> cũng là ảnh chụp toàn bộ: kịch bản không còn trong đó bị xoá khỏi danh mục.'
                          . '<br>• Gateway chỉ nhận <b>dàn ý</b> của kịch bản (<code>outline</code>: loại từng bước + ghi chú) và tên các <code>{{biến}}</code> kịch bản cần dữ liệu — <b>không nhận nội dung gõ / toạ độ</b>; các bước thật nằm ở tool.'
                          . '<br>• API này <b>không đụng tới đơn nạp</b>: đơn đang chạy vẫn phải được giữ «còn sống» bằng <code>heartbeat</code> / <code>progress</code>.'
                          . '<br>• <b>Ví do tool quản lý</b>: tool giữ tài khoản Apple + loại tiền + số dư + sổ của từng máy. Tool gửi <code>wallets</code> (ảnh chụp toàn bộ ví — gateway lưu bản sao để admin xem, không sửa ở gateway; ví cũ khai ở gateway trước đây không còn áp khi giao đơn). Phản hồi có <code>wallet_events</code> = tiền của các đơn gateway đã tính mà tool chưa áp: <code>{id, device, job, kind: purchase | hold | release | charge | refund, currency, d_balance, d_held, package_code, qty, note, at}</code> — <code>d_balance</code> đổi số dư, <code>d_held</code> đổi tiền tạm giữ (×100). Tool áp <b>mỗi <code>id</code> một lần</b> rồi gửi lại các <code>id</code> đã áp trong <code>wallet_acks</code> ở lần đồng bộ sau.',
                     'body' => [['devices', 'array', false, 'Toàn bộ máy: <code>{name, label, status, note, scripts: [uid…], running: {uid, group, script, iter}}</code> (≤ 200). <code>scripts</code> = các kịch bản máy này chạy được.'],
                                ['scripts_rev', 'string', false, 'Mã băm của danh mục kịch bản (16–64 ký tự hex). Bắt buộc khi gửi <code>scripts</code>.'],
                                ['scripts', 'array', false, 'Danh mục: <code>{uid, group, name, mode: once|loop|orders, loops, pool, step_count, vars: [tên biến…], outline: [{type, note, optional, phase}…]}</code> (≤ 300). <code>mode: orders</code> = <b>kịch bản nhận đơn</b>: tool sẽ xin đơn của pool <code>pool</code> (bằng <code>/claim</code>) cho máy rảnh rồi chạy kịch bản; <code>phase</code> của từng bước ∈ login · otp · nav · purchase · after · finish. <code>uid</code> = <code>mã-nhóm:mã-kịch-bản</code>, mỗi nửa 1–40 ký tự <code>A-Z a-z 0-9 _ . -</code>.'],
                                ['tool', 'object', false, '<code>{app, mode: desktop|web, accepting}</code>. <code>accepting: false</code> = tool đang chạy nhưng <b>không nhận đơn của khách</b> (bản web dev); không gửi = không rõ (gateway <b>không</b> tự coi là đang nhận đơn).'],
                                ['wallets', 'array', false, 'Toàn bộ ví của các máy: <code>{device, apple_account, currency, balance, held, active, note}</code> (số tiền ×100, số nguyên). <b>Không bao giờ</b> gửi mật khẩu Apple ID.'],
                                ['wallet_acks', 'array', false, 'Các <code>id</code> trong <code>wallet_events</code> tool đã áp vào sổ.']],
                     'req' => "{\n    \"tool\": {\"app\": \"iphone-farm\", \"mode\": \"desktop\", \"accepting\": true},\n    \"scripts_rev\": \"9f2c4a7b1d3e5f60a1b2c3d4e5f60718\",\n    \"scripts\": [\n        {\"uid\": \"a1b2c3d4:nap01\", \"group\": \"Nhóm iPhone 8\", \"name\": \"Nạp gói\", \"mode\": \"once\", \"loops\": 1,\n         \"step_count\": 3, \"vars\": [\"username\", \"password\"],\n         \"outline\": [{\"type\": \"launch\", \"note\": \"mở game\", \"optional\": false},\n                     {\"type\": \"tap_text\", \"note\": \"\", \"optional\": false},\n                     {\"type\": \"type\", \"note\": \"tài khoản\", \"optional\": false}]}\n    ],\n    \"devices\": [\n        {\"name\": \"iPhoneFarm-01\", \"label\": \"iPhone 8 số 1\", \"status\": \"idle\", \"scripts\": [\"a1b2c3d4:nap01\"]},\n        {\"name\": \"iPhoneFarm-02\", \"status\": \"running\", \"scripts\": [\"a1b2c3d4:nap01\"],\n         \"running\": {\"uid\": \"a1b2c3d4:nap01\", \"group\": \"Nhóm iPhone 8\", \"script\": \"Nạp gói\", \"iter\": 2}},\n        {\"name\": \"iPhoneFarm-03\", \"status\": \"offline\", \"note\": \"iPhone chưa cắm USB\", \"scripts\": []}\n    ]\n}",
                     'res' => "{\n    \"ok\": true,\n    \"server_time\": \"2026-12-05T03:04:05Z\",\n    \"scripts_rev\": \"9f2c4a7b1d3e5f60a1b2c3d4e5f60718\",\n    \"need_scripts\": false,\n    \"devices\": 3,\n    \"scripts\": 1,\n    \"wallet_events\": [\n        {\"id\": 41, \"device\": \"iPhoneFarm-01\", \"job\": \"J9F2C4A7B1D3E5F60\", \"kind\": \"purchase\", \"currency\": \"JPY\",\n         \"d_balance\": -150000, \"d_held\": 0, \"package_code\": \"coin_1050\", \"qty\": 1, \"note\": \"Mua 1050 eFootball Coins\", \"at\": \"2026-12-05T03:04:00Z\"}\n    ]\n}",
                     'errors' => array_merge($authErr, [[413, 'too_large', 'Thân yêu cầu quá 1 MB'], [422, 'missing_rev', 'Gửi <code>scripts</code> mà thiếu <code>scripts_rev</code>'],
                                  [422, 'invalid_devices', '<code>devices</code> không phải danh sách'], [422, 'invalid_scripts', '<code>scripts</code> không phải danh sách'],
                                  [422, 'too_many_devices', 'Quá 200 máy'], [422, 'too_many_scripts', 'Quá 300 kịch bản'], [422, 'invalid_wallets', '<code>wallets</code> không phải danh sách / quá 200 ví'], [503, 'needs_migration', 'Gateway chưa cập nhật CSDL (chạy <code>php bin/setup.php</code>)']])],
                    ['m' => 'GET', 'p' => '/api/tool/pools', 't' => 'Danh sách pool (gọn)',
                     'd' => 'Để người vận hành <b>chọn pool cho nhóm máy</b> ngay trong tool. Chỉ có thông tin nhận diện + số gói đang bán + số đơn đang chờ; cấu hình đầy đủ lấy ở API bên dưới.',
                     'res' => "{\n    \"ok\": true,\n    \"pools\": [\n        {\"code\": \"efootball-ios\", \"name\": \"eFootball (iOS) — đăng nhập Konami ID\", \"game\": \"eFootball\",\n         \"active\": true, \"packages\": 4, \"queued\": 2}\n    ]\n}", 'errors' => $authErr],
                    ['m' => 'GET', 'p' => '/api/tool/pools/{code}', 't' => 'Cấu hình pool cho tool',
                     'd' => 'Tool tải về (rồi làm mới định kỳ) để biết: trường đăng nhập, <b>luật nhận diện</b> (<code>rules</code>: thấy chữ nào là chưa đăng nhập / đăng nhập thành công / thất bại / đòi OTP / nạp xong…), <b>gói nạp kèm chữ OCR</b> (<code>ocr_text</code>, <code>price_text</code>) để dò đúng gói trên màn hình, <b>các loại tiền pool bán</b> (<code>currencies</code>) và <b>giá từng gói theo loại tiền</b> (<code>packages[].prices</code> = <code>{JPY: {amount, display}}</code>, <code>amount</code> ×100, <code>display</code> = chữ giá đúng như máy hiện ở vùng đó — tool dùng để khai ví cho máy), <b>Bước thao tác KHÔNG nằm ở đây</b>: sáu giai đoạn của một đơn (đăng nhập · nhập OTP · vào danh sách gói · mua 1 gói · sau mỗi lần mua · kết thúc đơn) soạn trong <b>kịch bản nhận đơn của tool</b>. Riêng pool lưu từ bản cũ có thể còn kèm <code>login_steps</code>, <code>otp_steps</code>, <code>nav_steps</code>, <code>purchase_steps</code>, <code>after_purchase_steps</code>, <code>finish_steps</code> (mỗi bước <code>{type, value, note, optional}</code>): tool đời mới chép chúng về kịch bản đúng một lần rồi không đọc nữa; pool mới không có các khoá này.'
                          . '<br><b>Luật</b> = <code>{when, value, note}</code>, <code>when</code> ∈ <code>logged_out</code> · <code>login_success</code> · <code>login_fail</code> · <code>need_otp</code> · <code>otp_wrong</code> · <code>purchase_success</code> · <code>purchase_fail</code> · <code>package_unavailable</code> · <code>once_left</code> (chữ «còn 1 lượt» in trong ô của gói «1 lần», mặc định «Remaining: 1»: trước khi mua gói 1 lần tool kiểm ô gói còn hiện VÀ có chữ này trong cùng ô — không có thì báo gói đã mua, không bấm gì). Tool <b>không nhận đơn</b> nếu pool thiếu một trong ba luật <code>logged_out</code>, <code>login_success</code>, <code>purchase_success</code>, hoặc kịch bản của tool thiếu bước đăng nhập / mua / kết thúc.'
                          . '<br><b>Biến</b> dùng trong các bước của tool: <code>{{username}}</code> <code>{{password}}</code> (mọi key của login) · <code>{{otp}}</code> · <code>{{package.ocr_text}}</code> <code>{{package.price_text}}</code> <code>{{package.name}}</code> <code>{{package.code}}</code> · <code>{{apple.account}}</code> <code>{{apple.password}}</code> = tài khoản / mật khẩu Apple ID của MÁY (khai ở ví của máy trong tool, gõ vào bảng mua của App Store; mật khẩu không bao giờ rời tool — máy chưa lưu thì không nhận đơn).',
                     'res' => "{\n    \"ok\": true,\n    \"pool\": {\n        \"code\": \"efootball-ios\",\n        \"name\": \"eFootball (iOS) — đăng nhập Konami ID\",\n        \"active\": true,\n        \"login_fields\": [ … ],\n        \"otp\": {\"enabled\": true, \"timeout\": 300, \"max_requests\": 3, \"hint\": \"…\"},\n        \"packages\": [\n            {\"code\": \"coin_1050\", \"name\": \"1050 eFootball Coins\", \"limit_type\": \"multi\", \"max_qty\": 0,\n             \"ocr_text\": \"1050|1,050\", \"price_text\": \"249.000\"}\n        ],\n        \"rules\": [\n            {\"when\": \"logged_out\", \"value\": \"Konami ID|Đăng nhập\", \"note\": \"\"},\n            {\"when\": \"login_success\", \"value\": \"Trang chủ\", \"note\": \"\"},\n            {\"when\": \"login_fail\", \"value\": \"Sai mật khẩu\", \"note\": \"\"},\n            {\"when\": \"need_otp\", \"value\": \"Nhập mã xác minh\", \"note\": \"\"}\n        ],\n        \"require_image\": true\n    }\n}",
                     'errors' => [[404, 'pool_not_found', 'Sai mã pool']]],
                    ['m' => 'POST', 'p' => '/api/tool/claim', 't' => 'Máy trống xin việc',
                     'd' => 'Gọi khi <b>một máy rảnh</b>. Có đơn → trả đơn kèm <code>login</code> (đã giải mã) và gói cần mua; không có → <code>"job": null</code> (đợi vài giây rồi hỏi lại). Một đơn chỉ giao cho <b>đúng một máy</b>; hai máy hỏi cùng lúc không bao giờ nhận trùng. Nếu máy này còn giữ đơn dở (tool vừa khởi động lại) → trả lại chính đơn đó với <code>"resumed": true</code> (đơn giữ nguyên giá lúc giao, không tính lại).'
                          . '<br><b>Ví tài khoản Apple</b> (do TOOL quản lý — mỗi máy một tài khoản Apple, một loại tiền): <b>Loại tiền chỉ là NHÃN</b> để so khớp ví ⇄ giá gói và đối soát — ký hiệu hay tên đều được, tuỳ nước (<code>¥</code>, <code>kr</code>, <code>CHF</code>): 1–6 ký tự chữ / ký hiệu tiền, không số, không khoảng trắng, không phân biệt hoa thường; ký hiệu / tên biết rõ quy về mã 3 chữ (<code>¥</code> / <code>JP</code> / <code>円</code> → <code>JPY</code>, <code>$</code> → <code>USD</code>…), nhãn khác giữ nguyên viết hoa (<code>kr</code> → <code>KR</code>). máy có ví thì gửi kèm <code>wallet</code> = <code>{currency, available, applied}</code> (còn dùng được theo sổ của tool ×100 + id các <code>wallet_events</code> tool ĐÃ áp vào sổ). Gateway cộng thêm các sự kiện tool <b>chưa áp</b> (chưa ack và không có trong <code>applied</code> — xem <code>/api/tool/sync</code>) rồi chỉ giao đơn mà <code>chi phí ≤ còn dùng được</code>, với chi phí = Σ <code>qty</code> × giá gói <b>ở loại tiền đó</b> (giá hiện tại lúc giao). Đơn có gói chưa có giá — hoặc chưa có <b>chữ giá</b> — ở loại tiền đó bị bỏ qua (tool khớp cả số tiền trên ô gói). Không gửi <code>wallet</code> = máy không có ví (không kiểm tiền). Khi có ví, đơn có thêm:'
                          . '<br>• <code>items[].price</code> — đơn giá (số nguyên = số tiền × 100, vd <code>150000</code> = 1.500 JPY, <code>6300</code> = 63,00 CHF), <code>items[].currency</code>; <code>items[].price_text</code> là <b>chữ giá đúng như máy hiện</b> ở vùng App Store của ví (dùng để dò ô gói).'
                          . '<br>• <code>job.wallet</code> = <code>{source: "tool", currency, cost}</code> — loại tiền + chi phí cả đơn (×100). (Ví cũ khai ở gateway: <code>{account, currency, balance, available}</code>, tài khoản đã che.)'
                          . '<br>Có đơn nhưng ví không trả được đơn nào → <code>"job": null</code> kèm <code>wallet_short</code> = <code>{reason: insufficient | no_price, currency, available, need, package_codes}</code> (ví cũ khai ở gateway có thêm <code>account</code> đã che): <code>insufficient</code> = thiếu tiền, <code>need</code> = chi phí của đơn rẻ nhất bị bỏ qua, <code>package_codes</code> = các gói của đơn đó; <code>no_price</code> = gói chưa có giá loại tiền này (<code>need: null</code>, <code>package_codes</code> = các gói thiếu giá). Đơn để máy khác nhận; tool nên báo admin nạp thêm tiền / khai giá.'
                          . '<br>Tiền của đơn tính khi báo kết quả (gửi cho tool thành <code>wallet_events</code>): <code>done</code> → <code>purchase</code> = <code>qty_done</code> × đơn giá lúc giao của từng gói (không gửi <code>items</code> = mua đủ); <code>failed</code> → không trừ; <code>review</code> (kể cả <code>done</code> thiếu ảnh, tool im lặng quá lâu) → <code>hold</code> cả chi phí cho tới khi admin chốt (<code>charge</code> số tiền thật / <code>release</code>). Admin sửa kết quả đã chốt → <code>refund</code> / <code>charge</code>. Báo muộn / gửi lại không bao giờ trừ hai lần.',
                     'body' => [['device', 'string', true, 'Tên máy (vd <code>iPhoneFarm-01</code>).'], ['pool', 'string', true, 'Mã pool máy này phục vụ.'],
                                ['wallet', 'object', false, 'Ví của máy (tool quản lý): <code>{currency: "JPY", available: 2400000, applied: [41, 42]}</code> — còn dùng được ×100 (số nguyên) tính đủ mọi dòng sổ; <code>applied</code> = id các sự kiện tiền tool đã áp (gần nhất, ≤ 300).']],
                     'req' => "{\"device\": \"iPhoneFarm-01\", \"pool\": \"efootball-ios\", \"wallet\": {\"currency\": \"JPY\", \"available\": 3850000}}",
                     'res' => "{\n    \"ok\": true,\n    \"paused\": false,\n    \"job\": {\n        \"id\": \"J9F2C4A7B1D3E5F60\",\n        \"ref\": \"NG261205A1B2C\",\n        \"pool\": \"efootball-ios\",\n        \"status\": \"claimed\",\n        \"login\": {\"username\": \"khach@example.com\", \"password\": \"MatKhau#123\"},\n        \"items\": [\n            {\"code\": \"coin_1050\", \"name\": \"1050 eFootball Coins\", \"qty\": 1,\n             \"ocr_text\": \"1050|1,050\", \"price_text\": \"¥1,500\", \"limit_type\": \"multi\",\n             \"price\": 150000, \"currency\": \"JPY\"}\n        ],\n        \"wallet\": {\"source\": \"tool\", \"currency\": \"JPY\", \"cost\": 150000},\n        \"otp\": {\"state\": \"none\", \"seq\": 0, \"deadline\": null, \"message\": null}\n    }\n}",
                     'res2' => ['Phản hồi 200 — ví không đủ tiền', "{\n    \"ok\": true,\n    \"paused\": false,\n    \"job\": null,\n    \"wallet_short\": {\n        \"reason\": \"insufficient\",\n        \"currency\": \"JPY\",\n        \"available\": 120000,\n        \"need\": 150000,\n        \"package_codes\": [\"coin_1050\"]\n    }\n}"],
                     'errors' => [[404, 'pool_not_found', 'Sai mã pool'], [422, 'missing_device', 'Thiếu tên máy'], [422, 'invalid_wallet', '<code>wallet</code> sai dạng (nhãn loại tiền không hợp lệ — xem «Loại tiền» ở phần mô tả / <code>available</code> không phải số nguyên ×100)']]],
                    ['m' => 'POST', 'p' => '/api/tool/jobs/{id}/progress', 't' => 'Báo đang ở bước nào',
                     'd' => 'Tuỳ chọn nhưng nên gọi: shop/khách thấy tiến độ, và gateway biết tool còn sống. <code>stage</code> gợi ý: <code>login</code> → <code>logged_in</code> → <code>navigating</code> → <code>purchasing</code> → <code>verifying</code>.',
                     'body' => [['stage', 'string', true, 'Chữ thường/số/_ (≤ 40).'], ['message', 'string', false, 'Mô tả ngắn (≤ 300).']],
                     'req' => "{\"stage\": \"logged_in\", \"message\": \"Đăng nhập thành công\"}",
                     'res' => "{\n    \"ok\": true,\n    \"status\": \"running\"\n}", 'errors' => [[409, 'conflict', 'Đơn đã kết thúc']]],
                    ['m' => 'POST', 'p' => '/api/tool/jobs/{id}/otp/request', 't' => 'Game đòi OTP → xin khách nhập',
                     'd' => 'Đơn sang <code>need_otp</code>, shop nhận webhook <code>job.need_otp</code>. Gọi lại với <code>reason: "wrong"</code> khi mã khách nhập bị sai (tối đa <code>otp.max_requests</code> lần / đơn).',
                     'body' => [['reason', 'string', false, '<code>first</code> (mặc định) | <code>wrong</code> | <code>expired</code> | <code>resend</code>.'],
                                ['attempt', 'number', false, 'Đây là lần xin thứ mấy <b>theo tool</b> (1, 2, 3…). Nên gửi: nếu gateway đã ghi nhận lần đó rồi (tool gửi lại vì mất phản hồi) thì trả lại trạng thái hiện tại kèm <code>"replayed": true</code>, <b>không tốn thêm lượt</b>. Tool khởi động lại giữa chừng thì đếm tiếp từ <code>job.otp.seq</code>.'],
                                ['message', 'string', false, 'Lời nhắn cho khách, vd nơi mã được gửi tới (≤ 300).']],
                     'req' => "{\"reason\": \"first\", \"attempt\": 1, \"message\": \"Mã đã gửi về email k***@gmail.com\"}",
                     'res' => "{\n    \"ok\": true,\n    \"otp\": {\"state\": \"waiting\", \"seq\": 1, \"deadline\": \"2026-12-05T03:10:00Z\", \"timeout\": 300}\n}",
                     'errors' => [[409, 'otp_disabled', 'Pool không bật OTP'], [409, 'otp_limit', 'Hết số lần xin OTP → báo <code>failed</code>']]],
                    ['m' => 'GET', 'p' => '/api/tool/jobs/{id}/otp?wait=20', 't' => 'Lấy OTP khách đã nhập',
                     'd' => '<code>wait</code> (0–25 giây) = giữ kết nối chờ mã thay vì hỏi liên tục. Kết quả ở <code>state</code>:<br>• <code>ready</code> → có <code>otp</code>, nhập vào game (hỏi lại vẫn trả cùng mã cho tới lần xin kế tiếp);<br>• <code>waiting</code> → khách chưa nhập, hỏi tiếp;<br>• <code>expired</code> → quá hạn: xin lại (<code>reason: "expired"</code>) hoặc báo <code>failed</code>;<br>• <code>none</code> → đơn không chờ OTP.',
                     'res' => "{\n    \"ok\": true,\n    \"state\": \"ready\",\n    \"otp\": \"482913\",\n    \"seq\": 1\n}"],
                    ['m' => 'POST', 'p' => '/api/tool/jobs/{id}/images?seq=1&kind=bill', 't' => 'Gửi ảnh kết quả',
                     'd' => 'Thân request = <b>ảnh thô</b> (PNG / JPEG / WEBP, ≤ 5 MB) — máy chủ kiểm theo nội dung. <code>seq</code> 1–30; cùng <code>seq</code> gửi lại thì ghi đè. <code>kind</code>: <code>bill</code> (mặc định) | <code>screenshot</code> | <code>error</code>. <b>Gửi hết ảnh TRƯỚC khi báo kết quả.</b>',
                     'req' => "curl -H \"Authorization: Bearer \$KEY\" -H \"Content-Type: image/png\" \\\n     --data-binary @bill1.png \"\$API/api/tool/jobs/\$ID/images?seq=1&kind=bill\"",
                     'reqLang' => 'bash',
                     'res' => "{\n    \"ok\": true,\n    \"seq\": 1,\n    \"url\": \"https://gateway.example.com/files/3f9a…c21.png\"\n}",
                     'errors' => [[409, 'conflict', 'Đơn không còn nhận ảnh'], [413, 'too_large', 'Rỗng / quá 5 MB'], [415, 'not_image', 'Không phải PNG/JPEG/WEBP']]],
                    ['m' => 'POST', 'p' => '/api/tool/jobs/{id}/result', 't' => 'Báo kết quả cuối',
                     'd' => '<b>Idempotent</b>: lỗi mạng/5xx thì gửi lại y nguyên; nhận <b>409</b> thì dừng (admin xử lý).<br>• <code>done</code> — đã nạp xong (pool bắt buộc ảnh mà chưa có ảnh nào → tự sang <code>review</code>).<br>• <code>failed</code> — CHỈ khi chắc chắn <b>chưa gửi lệnh trả tiền nào</b> (sai mật khẩu, hết OTP, không vào được game).<br>• <code>review</code> — không chắc đã nạp hay chưa.<br>Đơn <b>đã sang <code>review</code></b> (vd tool im lặng quá lâu) mà tool báo muộn thì trạng thái <b>không đổi</b> — <code>done</code>/<code>review</code> nhận 200, <code>failed</code> nhận 409 — nhưng lời báo luôn được ghi vào dòng thời gian của đơn cho người đối soát.',
                     'body' => [['result', 'string', true, '<code>done</code> | <code>failed</code> | <code>review</code>.'], ['message', 'string', false, 'Lý do / ghi chú (≤ 500).'],
                                ['items', 'array', false, 'Kết quả từng gói: <code>{code, qty_done, status: done|unavailable|failed|skipped, message}</code>. <code>unavailable</code> = gói 1-lần đã mua trước đó.']],
                     'req' => "{\n    \"result\": \"done\",\n    \"message\": \"Nạp đủ 1 gói\",\n    \"items\": [{\"code\": \"coin_1050\", \"qty_done\": 1, \"status\": \"done\"}]\n}",
                     'res' => "{\n    \"ok\": true,\n    \"status\": \"done\"\n}",
                     'errors' => [[409, 'conflict', 'Mâu thuẫn với trạng thái đã chốt (không đổi gì)'], [422, 'invalid_result', 'result lạ']]],
                    ['m' => 'GET', 'p' => '/api/tool/jobs/{id}', 't' => 'Đọc lại đơn đang giữ',
                     'd' => 'Kèm <code>login</code> khi đơn còn đang chạy (phòng khi tool mất dữ liệu giữa chừng). Đơn đã kết thúc thì không còn thông tin đăng nhập.',
                     'res' => "{\n    \"ok\": true,\n    \"job\": { … như phản hồi của /claim … }\n}"],
                ],
            ],
        ];
    }
}
