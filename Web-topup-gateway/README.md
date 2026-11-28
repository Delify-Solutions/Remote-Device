# Topup Gateway — API trung gian nạp game

Đứng giữa **website bán hàng** (shop) và **máy nạp** (tool, vd iPhone farm):

```
SHOP ──đẩy đơn đã thanh toán──▶ GATEWAY ◀──máy trống xin việc── TOOL
SHOP ◀──webhook: cần OTP / xong──  GATEWAY ◀──xin OTP, gửi ảnh, báo kết quả── TOOL
SHOP ──OTP khách nhập──────────▶ GATEWAY ──(tool tự lấy OTP về)──▶ TOOL
```

- **Trang quản trị** `/admin`: tạo *pool* (trường đăng nhập · OTP · luật nhận diện thành công/thất bại · các bước · gói nạp), khoá API + webhook, theo dõi/đối soát đơn, xem & tải ảnh kết quả.
- **Tài liệu API 2 chiều** `/docs`: sơ đồ 3 bên, từng endpoint kèm ví dụ, webhook + cách kiểm chữ ký, lệnh curl chạy thử, giả mã vòng lặp của tool. Trang này dựng từ `src/spec.php` nên luôn khớp với mã.
- **PHP 8.2 thuần, không framework**, MySQL/MariaDB (chạy thật) hoặc SQLite (dev/test).
- **Giao diện Vuexy** (Bootstrap 5, menu dọc, sáng/tối) — cùng bộ với iPhone Farm Manager; mọi thứ nằm sẵn trong `public/assets/`, không gọi CDN ngoài.

## Cài đặt

```bash
cp .env.example .env
# sửa .env: APP_URL, APP_KEY (chuỗi ngẫu nhiên dài — KHÔNG đổi về sau), DB_DSN/DB_USER/DB_PASS, CRON_KEY
php bin/setup.php            # tạo bảng + tạo admin (mật khẩu hiện MỘT lần)
php bin/setup.php admin 'MatKhauMoi>=10kytu'   # đặt lại mật khẩu khi cần
```

**Dữ liệu mặc định (cài máy mới có sẵn pool + gói):** trên máy đang chạy, `php bin/export-seed.php` ghi `seed.json` (chỉ pool, gói, giá theo loại tiền — không có admin, khoá API, đơn hay thông tin khách). Đặt file đó vào thư mục gateway của máy mới (hoặc chỉ đường bằng `SEED_FILE=` trong `.env`): `php bin/setup.php` tự nạp **một lần** khi CSDL chưa có pool nào; chạy lại không nạp đè. Chuyển **toàn bộ** dữ liệu (cả đơn, khoá API, admin) sang máy khác thì dùng dump CSDL và giữ nguyên `APP_KEY`.

Cần PHP ≥ 8.2 với `pdo_mysql` (hoặc `pdo_sqlite`), `sodium`, `gd`, `curl`, `mbstring`, `fileinfo`.

**Web server**: trỏ document root vào `public/`.
- Apache: đã có `public/.htaccess` (rewrite + chuyển header `Authorization`).
- nginx:
  ```nginx
  root /duong/dan/Web-topup-gateway/public;
  location / { try_files $uri /index.php$is_args$args; }
  location ~ \.php$ { include fastcgi_params; fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name; fastcgi_pass unix:/run/php/php8.2-fpm.sock; }
  client_max_body_size 6m;      # ảnh bill tối đa 5 MB
  ```
- Chạy thử trên máy (từ thư mục `Web-topup-gateway/`): `PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:8765 -t public public/index.php`

**Cron (mỗi phút)** — dọn đơn quá hạn + gửi lại webhook:
```cron
* * * * * php /duong/dan/Web-topup-gateway/bin/cron.php >> /var/log/topup-gateway-cron.log 2>&1
```
Hosting không có crontab CLI thì gọi `GET /cron/tick?key=<CRON_KEY>` mỗi phút.

## Dùng thế nào (tóm tắt)

1. `/admin/pools` → tạo pool cho từng game/cách đăng nhập (có sẵn mẫu: `php bin/seed-demo.php`).
2. `/admin/keys` → tạo **khoá Shop** (kèm Webhook URL của shop) và **khoá Tool**.
3. Đấu nối theo `/docs`:
   - **Shop**: `POST /api/shop/jobs` khi đơn đã thanh toán → nhận webhook `job.need_otp` thì hiện ô nhập cho khách → `POST …/otp` → nhận `job.done` (có link ảnh) / `job.failed` / `job.review`.
   - **Tool**: mỗi máy trống gọi `POST /api/tool/claim` → đăng nhập theo `login` → cần OTP thì `otp/request` rồi `GET …/otp?wait=20` → gửi ảnh `…/images` → `…/result`.

## Nối với iPhone Farm Manager (thư mục `app/` cùng repo)

Tool đã cài sẵn vòng lặp ở mục «Vòng lặp mẫu của tool» của `/docs`:

1. Trong tool: **Nhóm & Kịch bản → ⚙ Gateway** → nhập địa chỉ gateway + **khoá Tool** (`gwt_…`).
2. Tạo nhóm máy, thêm một kịch bản và chọn cách chạy **«nhận đơn từ gateway»**, chọn pool → bấm Chạy. Máy nào trống (Bluetooth nối, chụp được màn hình) sẽ tự xin việc.
3. Các bước thao tác soạn **ngay trong kịch bản đó của tool** (gateway không giữ bước), gồm 6 giai đoạn theo thứ tự chạy:

   | Giai đoạn | Khi nào chạy |
   |---|---|
   | Đăng nhập | đầu mỗi đơn; xong thì tool đọc màn hình theo luật ở mục 3 của pool |
   | Nhập OTP | mỗi lần khách gửi mã (để trống = gõ mã rồi Enter) |
   | Vào danh sách gói | 1 lần sau khi đăng nhập được |
   | Mua 1 gói | lặp theo gói × số lượng; xong thì đọc màn hình theo luật |
   | Sau mỗi lần mua | sau khi đã chụp ảnh bill |
   | Kết thúc đơn | đăng xuất — chạy trước khi máy nhận đơn kế tiếp, kể cả sau đơn lỗi (đơn phải đối soát: máy dừng, giữ nguyên màn hình; bấm Chạy lại mới đăng xuất) |

   Bước nào đặt «bỏ qua nếu lỗi» thì không làm được cũng đi tiếp (vd đóng hộp thoại lúc có lúc không). Pool lưu từ bản cũ còn bước soạn ở gateway: tool tự chép về kịch bản ở lần chạy đầu, sau đó xoá bằng nút «Xoá bước cũ» ở trang sửa pool.
4. Pool phải có **ba luật bắt buộc** ở mục 3 — «Màn hình CHƯA đăng nhập», «Đăng nhập THÀNH CÔNG», «Nạp gói THÀNH CÔNG» (thiếu thì trang Pool hiện nhãn «thiếu cấu hình») — và kịch bản phải đủ bước đăng nhập / mua / kết thúc; thiếu thì máy không nhận đơn.
5. Trước mỗi lần xin đơn, máy mở game và kiểm là **chưa ai đăng nhập** (còn thì tự đăng xuất). Tool tự dừng máy và chờ người khi: có đơn cần đối soát, không đăng xuất được, pool thiếu cấu hình, bàn phím iPhone đang ở Telex/VNI, hoặc 2 đơn liên tiếp lỗi do máy.

## Tool tự báo: máy nào rảnh ở kịch bản nào + danh mục kịch bản (`POST /api/tool/sync`)

Gateway đặt ngoài Internet, tool nằm trong mạng nội bộ → **gateway không gọi được vào tool**; mọi thứ gateway biết về máy và kịch bản đều do tool tự gửi lên.

- Tool (cả app cửa sổ lẫn bản web dev) gọi `POST /api/tool/sync` **mỗi ~20 giây và ngay khi có thay đổi** (máy bắt đầu / xong việc, bị «Dừng máy», sửa kịch bản). Xem ở trang **Kịch bản & máy** (`/admin/scripts`) và cột «Kịch bản / pool» của trang Tổng quan.
- `devices` = ảnh chụp **toàn bộ** máy: trạng thái (`idle` rảnh · `running` đang chạy kịch bản · `orders` đang nhận đơn · `paused` người vận hành dừng · `hold` dừng chờ kiểm tra · `manual` đang điều khiển tay · `offline` chưa sẵn sàng + lý do) và **các kịch bản máy đó chạy được** (kịch bản của mọi nhóm máy đang ở). Máy chỉ được tính là rảnh khi tool báo `idle`, lời báo chưa quá 90 giây, **và** gateway không còn ghi máy đó đang đứng tên một đơn (`Tools::idleFor()` — mọi việc «giao cho máy rảnh» sau này phải đi qua hàm này).
- `scripts` = danh mục kịch bản soạn ở tool (**Nhóm & Kịch bản**): tên, nhóm, cách chạy, số bước, tên các `{{biến}}` cần dữ liệu, và **dàn ý** (loại từng bước + ghi chú). Chỉ gửi khi đổi (`scripts_rev` / `need_scripts`). **Nội dung gõ, toạ độ, tên app của các bước không rời khỏi tool.**
- **Kịch bản nhận đơn** (soạn ở tool, cách chạy `orders`): tool khai kèm `pool` nó phục vụ → trang **Kịch bản & máy** ghi «nhận đơn · pool …» (báo rõ nếu pool không có / đang tạm dừng), trang **Pool & gói nạp** ghi kịch bản nào đang phục vụ pool + số máy đang rảnh. Tool vẫn xin đơn bằng `POST /api/tool/claim` theo pool như trước — API của shop không đổi.
- Bản web dev của tool báo `accepting: false` → trang hiện «tool không nhận đơn (bản web dev)». Không gửi `accepting` = không rõ (gateway không tự coi là đang nhận đơn).
- Lời báo bị từ chối (4xx) thì không ghi gì. Máy tool thôi không khai nữa bị xoá khỏi bảng (trừ khi còn đứng tên một đơn — giữ lại tới khi đơn đó xong). Xoá một khoá Tool thì kịch bản + máy của khoá đó cũng bị xoá.
- API này chỉ **báo tin**: không giao đơn, không đụng tới đơn đang chạy (`claim` / `heartbeat` / `result` vẫn như cũ).
- Bản cài cũ: chạy lại `php bin/setup.php` để áp migration 3–4 (thêm bảng `tool_scripts` + vài cột cho `devices`, `api_keys`, `tool_scripts.pool_code`; không đổi dữ liệu cũ). Chưa áp đủ thì `/api/tool/sync` trả `503 needs_migration`, các phần khác vẫn chạy.
- **Mỗi bản cài tool dùng một khoá Tool riêng**: hai tool chung một khoá sẽ ghi đè danh sách máy / kịch bản của nhau. (Trong MỘT bản cài, app cửa sổ và bản web mở cùng lúc thì chỉ một bên báo — tool tự khoá.)

## Ví tài khoản Apple (TOOL quản lý) + giá gói theo loại tiền

Mỗi máy nạp trả tiền bằng **một** tài khoản Apple, ở **một** loại tiền (vùng App Store). Ví của từng máy — tài khoản Apple, mật khẩu Apple ID (mã hoá, chỉ để tool gõ vào bảng mua, không bao giờ rời máy tính chạy tool), loại tiền, số dư, sổ nạp / trừ — **khai và nạp tiền ở app tool** (trang «Ví & Apple»). Gateway chỉ giữ **bản sao** để admin xem (`/admin/wallets`, không sửa được) và tính tiền của từng đơn. Mọi số tiền là **số nguyên = số tiền × 100** (1.500 JPY → `150000`, 63,00 CHF → `6300`).

- **Pool → «Loại tiền dùng trong pool»**: một pool bán được nhiều loại tiền; mỗi gói có **giá** + **chữ giá hiện trên máy** cho từng loại (bắt buộc đủ cả hai — tool khớp cả số tiền trên ô gói). Gõ thêm loại tiền là hiện ngay ô giá ở từng gói. Loại tiền chỉ là **nhãn** để khớp ví của máy với giá gói và để đối soát: gõ ký hiệu hay tên đúng như máy hiện (`¥`, `kr`, `CHF` — tối đa 6 ký tự, không số); `¥` / `JP` / `円` tự quy về `JPY`, `$` về `USD`…, nhãn khác giữ nguyên (viết hoa). Ví ở tool phải khai **cùng nhãn** với pool.
- **Xin đơn**: tool gửi kèm `wallet` = «loại tiền + còn dùng được» của máy. Gateway trừ thêm các khoản tool chưa kịp nhận rồi chỉ giao đơn mà *chi phí ≤ còn dùng được* (giá hiện tại ở đúng loại tiền đó). Đơn quá giá / gói chưa có giá hoặc chữ giá loại tiền đó thì bỏ qua cho máy khác; không đơn nào giao được thì `claim` trả `wallet_short` để tool báo admin. **Máy không có ví** nhận đơn y như trước.
- **Tiền của đơn → tool**: `done` → «mua gói» = số đã mua × đơn giá lúc giao · `failed` → không trừ · `review` (tool không chắc, thiếu ảnh, tool im lặng) → **tạm giữ** cả chi phí; admin chốt «đã nạp» (nhập số tiền thật) / «chưa nạp» (nhả); admin sửa kết quả đã chốt → hoàn / trừ. Mỗi khoản là một **sự kiện** (`tool_wallet_events`) gửi về tool khi đồng bộ (`/api/tool/sync` → `wallet_events`); tool áp mỗi sự kiện một lần rồi báo lại (`wallet_acks`). Báo muộn / bấm hai lần không bao giờ trừ hai lần.
- **Ví cũ khai ở gateway** (bảng `wallets`, trước khi chuyển về tool) không còn áp khi giao đơn mới; chỉ còn để tra sổ cái (và cho các đơn đã giao theo chúng).
- Trang Tổng quan nêu ví (bản sao) còn ít hơn giá gói đắt nhất đang bán.
- **Quản lý đơn** (trang Đơn nạp): mỗi đơn có nút Xem / Sửa / Xoá.
  - **Sửa**: đơn còn chờ máy sửa được hết (mã đơn, tài khoản + mật khẩu — ô mật khẩu để trống = giữ nguyên, gói, số lượng, ghi chú); đơn đã giao máy / đã kết thúc chỉ sửa ghi chú.
  - **Đổi trạng thái tay**: đang chạy → chờ đối soát (tạm giữ ví); hoàn tất → thất bại (hoàn lại tiền ví đã trừ); thất bại / quá hạn / huỷ → hoàn tất (trừ ví số tiền admin nhập). Shop nhận webhook trạng thái mới, kèm `corrected: true` khi sửa kết quả đã chốt.
  - **Thông tin đăng nhập** của khách bị che, bấm «Hiện» mới thấy — mỗi lần xem ghi vào nhật ký đơn.
  - **Xoá hẳn** đơn + ảnh + nhật ký; không xoá được đơn máy đang làm / chờ OTP / chờ đối soát (chốt trước). Đơn chờ máy bị huỷ trước (shop nhận `job.cancelled`). Sổ cái ví giữ nguyên các dòng của đơn (bỏ liên kết tới đơn, còn mã đơn) nên số dư không lệch.
  - Mã đơn chỉ đổi được ở **đơn thử** — mã đơn của shop là khoá chống tạo trùng khi shop gửi lại.
  - **Tạo đơn thử** (modal): đơn THẬT mang khoá shop nội bộ «Đơn thử (trang quản trị)» (không có webhook) — máy nhận đơn của pool sẽ nạp thật.
- **Gói «chỉ 1 lần / tài khoản»** giờ được chặn thật: mỗi tài khoản game của khách (ô chữ bắt buộc, không bí mật đầu tiên — vd email, không phân biệt hoa/thường; pool không có ô như vậy thì gộp tất cả ô không bí mật) chỉ mua được một lần trong một pool — đơn sau trả `422 already_bought` (đơn trước thất bại / huỷ / quá hạn thì mua lại được). Gateway chỉ lưu mã băm có khoá `HMAC-SHA256(pool:tài khoản, APP_KEY)`, không lưu email thô. **Đổi `APP_KEY` thì mọi giới hạn «1 lần» cũ coi như xoá** (các tài khoản đã mua lại mua được).
- Bản cài cũ: chạy lại `php bin/setup.php` để áp migration 5 (3 bảng mới + vài cột cho `jobs`; không đổi dữ liệu cũ).

## Nguyên tắc tiền (đã cài cứng trong mã, có test)

1. Một `ref` của shop = đúng **một** đơn (gửi lại không tạo đơn mới).
2. Một đơn chỉ giao cho máy **đúng một lần** (8 máy xin cùng lúc chỉ 1 máy nhận).
3. `failed` = tool cam kết **chưa** gửi lệnh mua nào. Không chắc → `review` cho admin chốt.
4. Gateway **không tự nạp lại, không tự hoàn tiền**.
5. Tài khoản/mật khẩu/OTP: mã hoá khi lưu (libsodium), chỉ giao cho máy nhận đơn, **xoá ngay khi đơn kết thúc**; không bao giờ xuất hiện trong webhook, API shop, hay nhật ký.

## Test

```bash
php bin/test-flow.php     # dựng gateway + máy nhận webhook giả trên SQLite tạm, đóng vai shop & tool qua HTTP
```
Kiểm: xác thực, cấu hình pool (6 danh sách bước, cờ bỏ qua nếu lỗi), tạo đơn/idempotent, chạy đua nhận việc, OTP (kể cả chờ long-poll, sai mã, hết lượt), ảnh, kết quả + xung đột 409, báo muộn, huỷ, đối soát, quá hạn, webhook có chữ ký, trang quản trị, ví do tool quản lý (giao đơn theo «loại tiền + còn dùng được» tool gửi, trừ khoản tool chưa nhận, sự kiện tiền của đơn + báo đã nhận qua sync, mua / tạm giữ / chốt đối soát / hoàn, không trừ hai lần, gói 1 lần / tài khoản kể cả khi gửi cùng lúc), và `POST /api/tool/sync` (máy rảnh ở kịch bản nào, danh mục chỉ gửi khi đổi, lời báo cũ không còn được tin, không đụng tới đơn, hai khoá Tool không lẫn dữ liệu).

Test **cả hai đầu** (tool thật ↔ gateway thật, iPhone giả lập) nằm ở phía tool — chạy từ gốc repo:

```bash
./.venv/bin/python app/tests/test_api_mode.py    # đơn thường, OTP sai/đúng, sai mật khẩu, mua 1 phần, treo sau khi bấm mua, tắt tool giữa chừng…
./.venv/bin/python app/tests/test_presence.py    # tool tự báo máy rảnh + danh mục kịch bản (có chạy với gateway thật nếu có lệnh php)
./.venv/bin/python app/tests/test_nav.py         # định vị con trỏ + bấm vòng kín + kiểm bàn phím Telex/VNI (không cần iPhone)
./.venv/bin/python app/tests/smoke_device.py <tên máy>   # thử trên iPhone THẬT bằng thao tác vô hại trong app Cài đặt (tắt app trước)
```

## Cấu trúc

| Việc | Ở đâu |
|---|---|
| Lõi: env, DB, mã hoá, request/response, phiên admin, CSRF, giới hạn tần suất, lưu ảnh | `src/core.php` |
| Bảng & migration (MySQL + SQLite) | `src/schema.php` |
| Nghiệp vụ: pool/gói, khoá, máy, **máy rảnh + danh mục kịch bản do tool tự báo** (`Tools`), **ví tài khoản Apple** (`Money`, `ToolWallets` — ví do tool quản lý; `Wallets` — ví cũ), **vòng đời đơn**, OTP, webhook | `src/repo.php` |
| API shop / tool, file ảnh, cron HTTP | `src/api.php` |
| **Mô tả API cho /docs** (sửa API thì sửa ở đây cùng lúc) | `src/spec.php` |
| Trang quản trị | `src/admin.php`, `views/` (khung trang: `views/layout.php`) |
| Giao diện: bộ Vuexy (chỉ phần dùng tới) · phần riêng của gateway | `public/assets/vuexy/` · `public/assets/app.css`, `app.js`, `theme.js` |
| Định tuyến | `public/index.php` |

**Thêm icon mới vào giao diện**: dùng class `ti tabler-<tên>` trong view rồi chạy `php bin/build-icons.php` — script chỉ chép những icon đang dùng từ bộ Tabler đầy đủ của Vuexy (`app/web/vuexy/…`, ~2.6 MB) sang `public/assets/vuexy/vendor/fonts/iconify-icons.css` (~16 KB).

## Lưu ý vận hành

- `GET …/otp?wait=N` giữ một tiến trình PHP tối đa N giây (≤ 25). Với PHP-FPM hãy để `pm.max_children` lớn hơn số máy nạp có thể cùng chờ OTP, hoặc cho tool dùng `wait=0` và hỏi lại mỗi 2–3 giây.
- Link ảnh `/files/<token>` là công khai nhưng không đoán được (128 bit) — dùng để đưa cho khách xem/tải.
- Đặt gateway sau HTTPS. Chạy sau proxy/CDN thì bật `TRUST_PROXY=true` để giới hạn tần suất theo IP thật — gateway lấy địa chỉ **cuối cùng** trong `X-Forwarded-For` (cái do proxy của bạn ghi thêm), nên chỉ bật khi mọi kết nối đều đi qua proxy đó. Đăng nhập admin còn bị giới hạn theo tên đăng nhập (20 lần sai / 10 phút) bất kể IP.
- **Webhook**: với PHP-FPM / LiteSpeed gateway gửi ngay sau khi trả lời request. Với máy chủ khác (mod_php…) nó chỉ gửi nhanh tối đa 2 cái × 2 giây rồi để phần còn lại cho cron — nên **bắt buộc đặt cron mỗi phút**, nếu không webhook «cần OTP» sẽ tới shop chậm.
- **MySQL/MariaDB**: các bảng dùng collation `utf8mb4_bin` (mã đơn, tên máy, mã gói so khớp chính xác từng ký tự). Bản cài cũ được `php bin/setup.php` tự chuyển (migration 2).
- Sao lưu: CSDL + thư mục `storage/files` (ảnh) + file `.env` (mất `APP_KEY` là không giải mã được đơn đang chạy).
