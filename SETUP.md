# Remote-Device: nhật ký cài đặt & việc cần làm

Mục tiêu: dùng 1 Mac điều khiển ~20 iPhone 8 (iOS 16) qua USB để tự động:
mở game → đăng nhập tài khoản khách → chọn gói → thanh toán (xác nhận bằng mật khẩu)
→ kiểm tra kết quả, đồng thời kiểm tra thông số từng máy có chuẩn không.

Cập nhật lần cuối: 2026-11-18

---

## 1. Môi trường

| Thành phần | Giá trị |
|---|---|
| Mac | Apple Silicon, macOS Tahoe 26.5.1 (không update được) |
| Máy test | iPhone 8 (`iPhone10,1`), iOS 16.7.9, tên `HoangAnhEfootball`, UDID `68b6f24f432ffa7c5beac3de43e0a79b4a792dd6` |

### Lưu ý quan trọng về phiên bản
- **Xcode 27.x KHÔNG hỗ trợ iPhone iOS 16** (chỉ từ iOS 17), lại còn cần macOS 26.6.
- **Xcode 26.6 là bản cuối cùng hỗ trợ iOS 15–16** → dùng bản này. Nó chạy trên macOS 26.2 trở lên.
- Không cài Xcode từ App Store (App Store luôn đưa bản mới nhất là 27.x).
- Nguồn: https://developer.apple.com/support/xcode/ và
  https://appium.github.io/appium-xcuitest-driver/latest/getting-started/system-requirements/

---

## 2. Đã làm

### Trên iPhone test
- [x] Máy đã "Tin cậy" Mac này (paired).
- [x] Bật **Chế độ nhà phát triển**: Cài đặt → Quyền riêng tư & Bảo mật → kéo xuống cuối.
  - Nếu không thấy mục này, chạy lệnh dưới, tắt hẳn app Cài đặt rồi mở lại:
    `.venv/bin/pymobiledevice3 amfi reveal-developer-mode`
  - Bật xong máy khởi động lại → mở khoá → xác nhận "Bật" → nhập mật khẩu.
- [x] Developer Disk Image đã mount (`pymobiledevice3 mounter auto-mount`).

### Trên Mac
| Đã cài | Cách cài | Dùng để |
|---|---|---|
| Python venv `.venv/` + `pymobiledevice3` 11.59.0 | `python3 -m venv .venv && .venv/bin/pip install pymobiledevice3` | Liệt kê máy, đọc thông số, chụp màn hình, mount DDI |
| `mas` 7.0.0 | `brew install mas` | (Không dùng nữa: App Store chỉ có Xcode 27) |
| `xcodes` 2.2.0, `aria2` | `brew install xcodes aria2` | Cài Xcode theo phiên bản cụ thể |
| **Xcode 26.6** (17F113) | `xcodes install 26.6 --path ~/Downloads/Xcode_26.6_Apple_silicon.xip --experimental-unxip --no-superuser` | Build/ký WebDriverAgent lên iPhone |
| Appium 4.0.0 | `npm install -g appium` (Node 22 qua nvm) | Server điều khiển giao diện |
| Driver XCUITest 13.1.3 | `appium driver install xcuitest` | Điều khiển iOS. Nếu lỗi với iOS 16 → hạ xuống `7.26.3` |

Xcode nằm ở: `/Applications/Xcode-26.6.0.app`.
File `.xip` gốc đã bị `xcodes` chuyển vào Thùng rác.

### Code trong repo
- `devices.py`: quét tất cả iPhone đang cắm, in tên, iOS, vùng, múi giờ, ngôn ngữ, pin
  và báo **OK/SAI** theo bảng `EXPECTED` ở đầu file.
  Chạy: `.venv/bin/python devices.py`
- `.gitignore`: bỏ qua `.venv/`, `shots/`, `.env`.
- `shots/`: ảnh chụp màn hình và log cài đặt (không commit).

---

### WebDriverAgent (WDA): đã build được, nhưng iPhone chặn không cho chạy
- Đã tạo chứng chỉ "Apple Development" (Team ID `X2P4FFC6G2`, Apple ID miễn phí) và cài chứng chỉ trung gian
  Apple WWDR G3 (thiếu cái này thì chứng chỉ bị báo không hợp lệ).
- Đã tải thành phần iOS 26.5 cho Xcode: `xcodebuild -downloadPlatform iOS` (8,5 GB).
- Build: `xcodebuild build-for-testing ... DEVELOPMENT_TEAM=X2P4FFC6G2 PRODUCT_BUNDLE_IDENTIFIER=com.x2p4ffc6g2.WebDriverAgentRunner`
  → thành công, output ở `.wda-build/`.
- `xcodebuild test-without-building` lỗi "Logic Testing Unavailable" → cài bằng
  `pymobiledevice3 apps install .wda-build/Build/Products/Debug-iphoneos/WebDriverAgentRunner-Runner.app`
  và chạy bằng `pymobiledevice3 developer dvt xcuitest com.x2p4ffc6g2.WebDriverAgentRunner.xctrunner`.
- **iPhone chặn chạy app**: log báo `Profile Needs Network Validation` và
  `Couldn't get device identity — Failed to copy UCRT (UCRT is unavailable)`.
  → Máy đã **bypass iCloud** nên thiếu chứng chỉ định danh thiết bị (UCRT). Không bao giờ xác minh được
  app ký bằng Apple ID miễn phí, dù đổi mạng hay khởi động lại.
- Đã kiểm tra: **thanh toán tay trong eFootball trên máy bypass vẫn chạy bình thường**.

**Đã chọn: hướng A** (2026-11-18).
**2026-11-22: đã đăng ký Apple Developer Program ($99), đang chờ Apple duyệt (tối đa 2 ngày làm việc).**
Khi duyệt xong: thêm UDID máy test iPhone 8 (68b6f24f432ffa7c5beac3de43e0a79b4a792dd6) vào tài khoản →
ký lại WDA bằng team trả phí → đổi WDA_BUNDLE_ID trong farm.conf → chạy ./start_wda_farm.sh để biết
máy bypass có qua được không (câu hỏi 50/50 còn mở).
Ghi chú thiết bị: có 1 iPhone XS Max (A12, iOS 18.7, CHÍNH CHỦ - chạy được chắc chắn, cần tunnel cho iOS 17+)
và 20 iPhone 8 bypass (iOS 16, còn kẹt tới khi test trả phí).
**Phạm vi (2026-11-19): chỉ dùng nội bộ, ~20 máy bypass, KHÔNG bán tool cho khách.**
→ Không phân phối app cho người ngoài nên rủi ro PPQ thấp. 20 máy nằm trong giới hạn 100 máy/năm.
**Đã bỏ hướng C (ESP32 giả chuột)** (2026-11-19). Chỉ điều khiển qua 1 máy tính: Mac + USB + WDA.

Kết quả research về hướng A (khả năng cao là chạy được, chưa kiểm chứng trên máy thật):
- Hồ sơ của Apple ID miễn phí có cờ `LocalProvision = true` (đã kiểm tra file `.mobileprovision` trên máy, hạn 7 ngày).
  Loại hồ sơ này bắt iPhone xác minh online (online-auth-agent), mà bước xác minh cần định danh thiết bị (UCRT),
  thứ máy bypass không có.
- Hồ sơ của team trả phí liệt kê UDID máy trong `ProvisionedDevices` và **không bị đánh dấu cần xác minh online**:
  iPhone chỉ so UDID ngay trên máy.
  Nguồn: https://github.com/adm1n007/vphone-cli/pull/24 ("A paid team's profile is not marked as needing online
  authorization") và https://lakr233.github.io/vphone-cli/research/Guest/xcode_install_signature_gate.html
- Hồ sơ Enterprise vẫn cần xác minh online (https://developer.apple.com/forums/thread/736905), nên không dùng.
- ⚠️ Bằng chứng ngược chiều: có báo cáo tài khoản trả phí vẫn bị "Verify App"
  (https://developer.apple.com/forums/thread/732495), và Apple có cơ chế PPQ ép xác minh online lên chứng chỉ
  developer bị nghi dùng để phân phối app (https://helpcenter.apptesters.org/en/articles/10693800-how-to-fix-unable-to-verify-app).
  → Ký WDA bán cho nhiều khách có thể bị PPQ, khi đó máy bypass sẽ lại bị chặn. Phải thử thật trước khi làm hàng loạt.
- ⚠️ Sự cố ppq.apple.com ngày 10/03/2026 (https://developer.apple.com/forums/thread/818403,
  https://appleinsider.com/articles/26/03/10/a-now-resolved-apple-server-outage-stopped-developers-from-verifying-apps):
  có người báo **app Ad Hoc (chỉ tài khoản trả phí mới tạo được) và build Xcode** cũng không chạy được.
  → App ký bằng tài khoản trả phí **có thể vẫn phải xác minh online trong một số trường hợp**.
  Apple (Quinn, DTS) chỉ nói ppq "on the critical path ... in some situations", không nói rõ trường hợp nào.
  **Đánh giá lại khả năng hướng A chạy được trên máy bypass: khoảng 50/50.** Nên thử bằng team trả phí có sẵn
  (ví dụ của công ty) trước khi tự mua.

### Dự án tương tự (tham khảo)
- GADS (farm iOS/Android, điều khiển trên web, dùng WDA + go-ios): https://github.com/shamanec/GADS
- iOS Farm / prod-FARM-IOS-Core (farm iPhone chạy từ Mac, có lịch chạy tự động, Appium + WDA): https://github.com/kevinbadi/prod-FARM-IOS-Core
- Đã clone vào `tmp/` để tham khảo, xem `tmp/README.md`.

**Hướng xử lý (chọn 1):**
- A. Tài khoản Apple Developer trả phí ($99/năm): đăng ký UDID từng máy, ký WDA bằng hồ sơ trả phí.
  Chưa kiểm chứng trên máy thiếu UCRT, nên thử 1 máy trước.
- B. Jailbreak palera1n (tethered) + AppSync Unified: cài WDA không cần xác minh.
  Rủi ro: game phát hiện jailbreak; mỗi lần khởi động lại phải jailbreak lại qua Mac.

## 3. Việc còn phải làm

### Bạn tự làm (cần mật khẩu / tài khoản)
- [ ] Chọn Xcode 26.6 làm mặc định & chạy lần đầu (gõ trong Claude Code với dấu `!`, hoặc trong Terminal):
  ```
  sudo xcode-select -s /Applications/Xcode-26.6.0.app
  sudo xcodebuild -license accept
  sudo xcodebuild -runFirstLaunch
  ```
  Kiểm tra: `xcode-select -p` phải ra `/Applications/Xcode-26.6.0.app/Contents/Developer`.
- [ ] Mở Xcode → Settings → Accounts → **+** → thêm Apple ID (để ký WebDriverAgent).
  - Tài khoản miễn phí: thử được, nhưng phải ký lại mỗi 7 ngày, giới hạn số máy.
  - 20 máy: nên mua **Apple Developer Program ($99/năm)**.
- [ ] Mở game trên máy test tới **màn hình xác nhận thanh toán** (chưa bấm) → để chụp xem là
  cửa sổ App Store (mật khẩu Apple ID) hay Apple Pay (mật khẩu máy).
- [ ] Gửi danh sách **thông số cần kiểm tra** + giá trị đúng (vùng, múi giờ, ngôn ngữ, Apple ID…).
  Máy test hiện: vùng `J/A` (Nhật), múi giờ `America/Los_Angeles`, ngôn ngữ `vi-VN`. Cần xác nhận có đúng ý không.
- [ ] Cho biết game cụ thể và khách đăng nhập bằng gì (Konami ID / Google / Apple / Facebook…).

### Claude làm tiếp
- [ ] Build & cài WebDriverAgent lên máy test, chạy thử Appium: bấm, gõ, đọc màn hình.
- [ ] Nhận diện màn hình game bằng ảnh/OCR (game vẽ thẳng lên màn hình nên không có phần tử UI).
- [ ] Viết kịch bản nạp: đăng nhập → chọn gói → thanh toán → xác nhận → chụp bằng chứng.
  Mật khẩu xác nhận lưu trong **Keychain của macOS**, không ghi trong code.
- [ ] Dashboard web: xem 20 máy, hàng đợi đơn, log, ảnh từng đơn.
- [ ] Giới hạn tốc độ giao dịch để tránh Apple khoá Apple ID/thẻ.

### Phần cứng cho 20 máy
- Hub USB **có nguồn riêng**. 20 máy trên 1 Mac có thể quá tải, cân nhắc chia 2 Mac.

---

## 4. Script vận hành farm WDA

| File | Việc |
|---|---|
| `farm.conf` | Cấu hình: bundle ID WDA, đường dẫn gói WDA, port gốc, thời gian chờ |
| `./scan_devices.sh` | Quét máy USB, kiểm tra Trust / Developer Mode / DDI → ghi `devices.txt`. In UDID máy cần làm tay |
| `./start_wda_farm.sh` | Với mỗi máy: mount DDI → cài WDA nếu thiếu → `iproxy` → khởi chạy WDA → kiểm tra `/status`. Máy i dùng port Mac `8100+i` (WDA) và `9100+i` (MJPEG); trong iPhone luôn là 8100/9100. Log: `logs/wda_<UDID>.log`. Bảng port: `run/ports.tsv` |
| `./stop_wda_farm.sh` | Dừng mọi WDA + iproxy của farm |

- Dùng `pymobiledevice3 developer dvt xcuitest` thay cho `xcodebuild test-without-building`,
  vì xcodebuild báo "Logic Testing Unavailable" với Xcode 26.6 + iOS 16.
- Đã cài `libimobiledevice` 1.4.0 (`brew install libimobiledevice`) để có `idevice_id`, `ideviceinfo`, `iproxy`.
- Kết quả chạy thử 2026-11-19 trên máy test: scan OK, start chạy đúng tới bước khởi chạy thì
  **iPhone chặn WDA (chữ ký miễn phí + máy bypass)**, đúng như dự kiến. Có tài khoản trả phí thì chỉ cần
  build lại WDA, đổi `WDA_BUNDLE_ID` trong `farm.conf`, rồi chạy lại.
- Khởi chạy WDA qua USB **không** bỏ qua được bước xác minh: iPhone tự kiểm tra chữ ký lúc mở app.

## 5. Lệnh hay dùng

```bash
# Liệt kê máy đang cắm
.venv/bin/pymobiledevice3 usbmux list

# Kiểm tra thông số tất cả máy
.venv/bin/python devices.py

# Chụp màn hình (máy đầu tiên)
.venv/bin/pymobiledevice3 developer dvt screenshot shots/test.png

# Kiểm tra Developer Mode
.venv/bin/pymobiledevice3 amfi developer-mode-status

# Mount Developer Disk Image (cần sau mỗi lần iPhone khởi động lại)
.venv/bin/pymobiledevice3 mounter auto-mount
```

---

## 6. Lỗi đã gặp & cách xử lý

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| Không thấy "Chế độ nhà phát triển" trong Cài đặt | Mục bị ẩn mặc định | `pymobiledevice3 amfi reveal-developer-mode`, tắt hẳn app Cài đặt rồi mở lại |
| `Developer Mode is disabled` khi chụp màn hình | Chưa bật Developer Mode | Bật như mục 2 |
| `usbmuxd closed the connection` sau khi iPhone khởi động lại | Máy chưa mở khoá lần đầu / chưa tin cậy lại | Mở khoá iPhone, rút cáp cắm lại, bấm "Tin cậy". Nếu vẫn lỗi: `sudo killall usbmuxd` |
| `mas install` báo `sudo: a password is required` | `mas` 7.x bắt buộc chạy với sudo | Bỏ, dùng `xcodes` + file `.xip` |
| Chứng chỉ có nhưng `0 valid identities found` | Thiếu chứng chỉ trung gian Apple WWDR G3 | Tải https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer rồi `security import` vào login keychain |
| Build WDA báo `iOS 26.5 is not installed` | Bộ `.xip` không kèm thành phần iOS | `xcodebuild -downloadPlatform iOS` |
| `xcodebuild test-without-building`: Logic Testing Unavailable | Xcode 26 + iOS 16 qua CoreDevice | Cài và chạy WDA bằng pymobiledevice3 (xem mục WDA) |
| Bấm "Xác minh ứng dụng" báo cần internet dù có Wi-Fi | Máy bypass iCloud, thiếu UCRT | Không sửa được bằng mạng. Xem hướng A/B ở mục WDA |
| App Store chỉ có Xcode 27.2, báo cần macOS 26.6 | Xcode 27 cần macOS 26.6 và không hỗ trợ iOS 16 | Tải Xcode 26.6 `.xip` từ https://developer.apple.com/download/all/ |

---

## 7. KẾT LUẬN QUYẾT ĐỊNH (2026-11-22) — máy bypass không tự động hoá input được

Đã test đến tận cùng với **tài khoản Apple Developer TRẢ PHÍ thật** (`contact@delify.vn`, team `82BTLA9574`, Individual).

### Đã làm
- Đăng ký UDID máy test (`68b6f24f…`) trong developer.apple.com.
- Build + ký WDA bằng team trả phí → profile chuẩn: nhúng UDID, `get-task-allow=true`, **hạn 1 năm** (không phải 7 ngày như free).
- Cài WDA lên iPhone 8 bypass: **CÀI THÀNH CÔNG** (installd chấp nhận chữ ký trả phí).
- `farm.conf`: `WDA_BUNDLE_ID=com.delify.WebDriverAgent.xctrunner`.

### Kết quả test trên máy bypass
| Khả năng | Kết quả |
|---|---|
| Cài app ký trả phí | ✅ được |
| **Chạy** app ký mới (WDA) | ❌ chặn — popup "Phải có kết nối internet để xác minh" (dù có Wi-Fi). Thiếu UCRT do bypass → không qua được xác minh online. **Tài khoản trả phí KHÔNG cứu được.** |
| `dvt launch` app hệ thống / app đã cài sẵn | ✅ được (vd mở Settings) |
| Đọc màn hình qua Accessibility (AX) — caption/nút/giá trị/screenshot | ✅ được, **không cần ký app** |
| **Tap/gõ** qua AX `perform_press` | ❌ không tác dụng trên app thường (cần entitlement `task_for_pid-allow` = chỉ app debug mới có, mà app đó không chạy được) |

### Chốt
- **20 iPhone 8 bypass: KHÔNG tự động hoá được input** (không WDA, không inject tap/gõ). Jailbreak palera1n thì tắt Apple Pay → vô nghĩa cho mục đích thanh toán.
- Máy bypass **chỉ** làm được: đọc thông số (`ideviceinfo`, `devices.py`) + đọc màn hình AX (giám sát), không điều khiển.
- **Tự động hoá login + Apple Pay CHỈ chạy trên máy SẠCH/đã kích hoạt + tài khoản trả phí** (như XS Max). Tài khoản `contact@delify.vn` vẫn dùng tốt cho máy sạch.

## 8. Điều khiển bằng AI (MCP) và dòng lệnh `farm` (2026-11-24)

App có thêm một **cầu nối điều khiển**: AI (Claude Code, Claude Desktop, Cursor… qua giao thức MCP) hoặc lệnh `./farm`
đọc được màn hình iPhone (ảnh + chữ kèm toạ độ) và bấm / gõ / vuốt / bấm giữ / mở app / chạy-dừng nhóm.

### Kết nối AI (3 cách — xem luôn trong app: mục «Kết nối AI»)
1. **Claude Code**: mở Claude Code trong thư mục dự án và đồng ý với máy chủ `iphone-farm` (khai sẵn trong `.mcp.json`),
   hoặc chạy một lần `claude mcp add iphone-farm -- /đường/dẫn/Remote-Device/farm mcp`.
2. **Claude Desktop / Cursor / client MCP khác**: thêm `{"mcpServers": {"iphone-farm": {"command": "/đường/dẫn/Remote-Device/farm", "args": ["mcp"]}}}`.
3. **HTTP** (khi app đang mở): `http://127.0.0.1:47821/mcp` + tiêu đề `Authorization: Bearer <khoá>`. Khoá xem / đổi ở mục «Kết nối AI»;
   lưu trong `app/data/control.json` (không vào git). Chỉ nghe trên 127.0.0.1.

`./farm mcp-config` in sẵn cả ba cách.

### Dòng lệnh
```bash
./farm devices                               # danh sách máy
./farm screen iPhoneFarm-01                  # chụp + đọc chữ kèm toạ độ (ảnh lưu vào shots/)
./farm tap iPhoneFarm-01 462 820             # bấm toạ độ (pixel của ảnh chụp)
./farm tap iPhoneFarm-01 --text "Wi-Fi"      # bấm vào chữ
./farm type iPhoneFarm-01 "hello" --enter    # gõ (chỉ ASCII) rồi Enter
./farm swipe iPhoneFarm-01 left              # lật trang; up/down = cuộn
./farm hold iPhoneFarm-01 636 468 --seconds 1.5
./farm run iPhoneFarm-01 @steps.json         # chạy một chuỗi bước (cùng dạng bước với kịch bản của app)
./farm status ; ./farm groups ; ./farm start "Tên nhóm" ; ./farm stop iPhoneFarm-01
./farm --help                                # mọi lệnh;  thêm --json để lấy kết quả cho script
```

### Cách hoạt động
- **App đang mở** → mọi lệnh của AI/CLI được chuyển cho app thực hiện (app là nơi DUY NHẤT giữ cổng serial của board).
  **App chưa mở** → `farm` tự dò board và tự mở cổng (chỉ điều khiển trực tiếp; chạy/dừng nhóm thì cần app).
- Cổng serial được mở **độc quyền**: hai chương trình không thể cùng điều khiển một board (bên mở sau nhận lỗi rõ ràng).
- **Một máy, một người dùng tại một thời điểm** (sổ dùng chung giữa AI/CLI, các nút thử trong giao diện và bộ chạy): máy **đang
  chạy kịch bản / nhận đơn** thì AI/CLI không chen vào bấm được; máy đang được AI/CLI điều khiển thì app không quét / không chạy
  nhóm / không thử bước trên máy đó cho tới khi lệnh xong; hai nút «Chạy thử» trên giao diện cũng không chạy chồng lên cùng một
  máy. Tắt app / tắt cầu nối, bấm Esc ở client MCP (kể cả khi đi qua `farm mcp`) hoặc Ctrl-C ở `farm` thì lệnh đang chạy dở trên
  điện thoại được huỷ.
- **Máy đang nhận đơn của khách** (chế độ nhận đơn), hoặc vừa **dừng giữa chừng một đơn của khách** và đang được giữ nguyên màn hình:
  AI/CLI **không xem được màn hình** (ảnh + chữ có thể lộ tài khoản / OTP của khách) — chỉ xem tiến độ bằng `farm status`.
  Máy chạy kịch bản thường của chủ thì vẫn xem được.
- **Máy dừng chờ người kiểm tra** (đơn gián đoạn giữa lúc mua, đơn cần đối soát, lỗi phiên đăng nhập, lỗi lặp lại…): màn hình được
  GIỮ NGUYÊN — AI/CLI không điều khiển, không chạy lại nhóm có máy đó, và **`stop_run` cũng bị từ chối** (Dừng trong app là lời xác
  nhận «đã đối soát xong», chỉ người vận hành đưa ra được). Trạng thái này chỉ gỡ bằng nút Dừng / Chạy lại trong app.
- Mọi cú bấm đều ĐO vị trí con trỏ trên ảnh chụp rồi mới bấm; không đo được thì không bấm. Con trỏ chỉ được nhận bằng **bằng chứng
  chuyển động**: vệt duy nhất vừa dời đi đúng hướng, đúng quãng theo lệnh di, ở hai nhịp liền nhau. Đến đích rồi vẫn chưa bấm: tool làm
  **phép thử «đi – đứng yên – về»** (nhích con trỏ ra một chỗ TRỐNG của màn hình, hướng chọn ngẫu nhiên; nhìn thêm một lần không ra lệnh
  gì — con trỏ thật đứng yên tuyệt đối; rồi quay lại đích bằng một nhịp ngắn) và chỉ bấm khi con trỏ làm đúng cả ba. Vật tự chạy / bay
  vào đích / nhảy lung tung rất khó làm theo (không phải không thể — xem «Còn mở»). Chỗ trống được chọn theo ảnh nền (tránh nhãn chữ, icon, mép màn hình — đo thật: nhích
  lên nhãn chữ làm con trỏ biến mất khỏi ảnh). Ảnh chụp trúng lúc con trỏ còn đang lướt (~0,4 s sau lệnh di) thì chờ nhìn lại, không ra
  lệnh thừa. Tool tự đo «tốc độ con trỏ» của từng máy (pixel cho mỗi đơn vị lệnh — hai iPhone 8 đang có: ~0,9–1,1 và ~1,15–1,4) và chỉ
  dùng số đo để siết phép kiểm khi hai lần đo liên tiếp khớp nhau; đổi tốc độ con trỏ trong Cài đặt của iPhone thì tool tự đo lại.
- Khoá của cầu nối HTTP không in ra màn hình trừ khi yêu cầu rõ (`./farm mcp-config --show-token`).
- Chỉ có một máy sẵn sàng thì bỏ được tên máy: `./farm find Safari`, `./farm tap 288 468`, `./farm type hello`.
- Máy chủ MCP viết tay (`app/mcpserver.py`, không cần SDK, chạy trên Python 3.9), hỗ trợ cả giao thức đời cũ (bắt tay
  `initialize`, 2024-11-05 … 2025-11-25) lẫn đời mới 2026-07-28 (không bắt tay, có `server/discover`).

### Tệp
| Tệp | Việc |
|---|---|
| `app/mcpserver.py` | giao thức MCP: stdio + HTTP, khách gọi sang app |
| `app/control.py` | bộ công cụ dùng chung (đọc màn hình, bấm, gõ, vuốt, chạy nhóm…), máy chủ trong app, chế độ tự mở cổng |
| `app/cli.py`, `farm` | dòng lệnh |
| `app/fastshot.py` | chụp màn hình qua một kết nối giữ mở (~0,33s/ảnh thay vì ~1,3s) |
| `app/web/ai.js` | trang «Kết nối AI» |

### Kiểm thử
```bash
./.venv/bin/python app/tests/test_mcp.py          # giao thức + lõi điều khiển + CLI (máy giả)
./.venv/bin/python app/tests/test_nav.py          # định vị con trỏ, bấm vòng kín, lệnh xuống board
./.venv/bin/python app/tests/test_api_mode.py     # chế độ nhận đơn (gateway tạm + iPhone giả)
uv run --python 3.12 --with mcp app/tests/interop_sdk.py     # kiểm chéo với client của SDK MCP chính thức
./.venv/bin/python app/tests/smoke_device.py iPhoneFarm-01   # máy THẬT (tắt app trước): các bước của chế độ nhận đơn
./.venv/bin/python app/tests/device_gestures.py iPhoneFarm-01  # máy THẬT (tắt app trước): bấm, lật trang, cuộn, bấm giữ
```

### Tốc độ đo trên iPhone 8 (sau khi chụp nhanh + đọc phản hồi board ngay)
| Thao tác | Trước | Nay |
|---|---|---|
| chụp màn hình | ~1,3s | ~0,33s |
| bấm vào toạ độ | 7–17s | ~8s (trung vị; gồm phép thử «đi – đứng yên – về»; đo trên 2 iPhone 8). Màn hình chính có icon Đồng hồ (kim chạy) thì thỉnh thoảng 15–30s |
| dò chữ + bấm | ~18s | ~6s |
| đọc màn hình (ảnh + chữ) qua MCP | — | ~1s |
| lật trang (vuốt) | — | ~8s (thỉnh thoảng ~20s khi phải đo lại con trỏ) |

Soak qua đường `farm` → app → board → iPhone: 8 vòng (mở Cài đặt, về home, lật trang, lật lại) trên từng máy, 0 lỗi.

Nhịp của **bàn phím** (gõ, phím, mở app qua Spotlight) được giữ như cũ có chủ đích: nhấn Enter sớm thì Spotlight chưa kịp chọn app.

### Board ESP32: sức khoẻ, tự reset, kiểm thử (firmware v2)
Firmware (`app/firmware/esp32_hid/esp32_hid.ino`, `FW_VERSION 2`) nay báo được và tự bảo vệ:
- `status` → `OK ble=… fw=2 up=<giây> heap=<RAM trống> min=<đáy RAM> blk=<mảng liền lớn nhất> rst=<lý do reset lần trước> rxerr=… ovf=… drop=<số lần BLE rớt> cmds=… temp=…`;
  `info` → chip, lõi, xung nhịp, flash; `reset` → khởi động lại (chạy được cả khi chưa nối BLE).
- Chống tràn: dòng lệnh đọc vào bộ đệm CỐ ĐỊNH 512 byte (dài hơn → `ERR line-too-long`, không ăn dần RAM như `String` nối cũ), bộ đệm nhận serial
  2048 byte (mặc định 256 → gửi dồn nhiều lệnh khi board đang bận thì rớt lệnh), watchdog (`loop()` kẹt quá ~5 s → tự reset, lý do báo là `panic` hoặc `task_wdt` tuỳ cấu hình core),
  RAM < 24 KB lúc rảnh → tự khởi động lại sớm.
- **Nhiệt độ**: ESP32 gốc (D0WD) luôn trả đúng 53,3 °C — không có cảm biến thật, tool bỏ qua. Số đáng tin: RAM, lý do reset (`brownout` = nguồn USB yếu: đổi cáp / hub có nguồn), BLE rớt, lỗi serial.
- Nạp firmware mới: trang **Thiết bị → Nạp** (hoặc `esp.flash`). Firmware cũ vẫn chạy bình thường, chỉ không có số liệu sức khoẻ.

Trong app / AI: thẻ board ở trang Thiết bị hiện một dòng tóm tắt + cảnh báo; nút «BLE?» ở trình dựng kịch bản hiện sức khoẻ; công cụ MCP/CLI `board_health` (`./farm health [máy]`, chỉ xem) và
`board_recover` (`./farm recover [máy]`: board im → reset cứng bằng chân EN qua RTS; thiếu RAM / phân mảnh → reset mềm; rồi chờ iPhone nối lại BLE — bị từ chối khi máy đang chạy).
Bộ chạy nhận đơn tự kiểm board **lúc rảnh** (đầu phiên, rồi mỗi 5 phút, và khi máy báo «chưa sẵn sàng»); **bộ chạy** không bao giờ chủ động reset giữa lúc đang xử lý đơn. (Firmware thì tự khởi động lại khi RAM < 24 KB và 30 s không nhận byte nào — có thể trúng lúc chờ OTP; reset chỉ làm rớt BLE vài giây, không gây thao tác nào lên iPhone.)

Kiểm thử ESP32 (ngoài iPhone):
```bash
./.venv/bin/python app/tests/test_firmware.py            # biên dịch thật firmware (arduino-cli, core esp32 2.0.17) + soi mã: đủ lệnh, giới hạn dòng, watchdog, reset
./.venv/bin/python app/tests/test_board.py               # đọc/đánh giá status, quyết định reset, chuỗi phục hồi — board giả, không cần phần cứng
./.venv/bin/python app/tests/smoke_board.py iPhoneFarm-03        # board THẬT (tắt app trước): độ trễ, giao thức, gửi dồn, rò RAM, reset mềm/cứng, BLE nối lại
```
Đo trên board thật (iPhoneFarm-03, ESP32-D0WD-V3, firmware v2): ping p50 ≈ 67 ms; 300 lệnh gửi dồn trong một lần ghi không rớt lệnh nào; 500 lệnh ping/status mất 0 byte RAM;
dòng 700 ký tự bị chặn đúng; reset mềm ≈ 1,7 s, reset cứng qua RTS ≈ 1,7 s.

### Còn mở
- Trạng thái «dừng chờ người kiểm tra» chỉ nằm trong bộ nhớ của app: tắt / khởi động lại app giữa lúc đang xử lý một đơn thì AI/CLI
  lại điều khiển được máy đó. Đơn vẫn được ghi trong sổ (journal) nên bộ chạy xử lý đúng khi chạy lại; hãy tự kiểm tra máy sau khi
  app bị tắt đột ngột.
- Vật tròn cỡ con trỏ **tự chuyển động** gần đích (hoạt ảnh, băng chuyền, huy hiệu nảy) thì bấm có thể chậm hơn / báo «không tới được».
  Giả lập: dừng-đi, giữ-rồi-nhảy, lướt-rồi-đỗ, bay thẳng/chéo vào đích rồi đỗ, bắt chước lệnh di rồi trôi → 0 cú bấm lệch trong hàng nghìn lượt.
  Còn lại là **xác suất thấp, không bằng 0**, kể cả khi con trỏ thật hiện được: vật nhảy ngẫu nhiên quanh đích ±120px (~0,5–1%/cú bấm trong
  mô hình giả lập cực đoan đó), và vật «biết» đúng các chỗ trống mà tool dùng để nhích thử (~1/số chỗ trống). Đòi hỏi một vật cỡ con trỏ nhấp nháy
  đúng quanh đích — hiếm khi gặp thật. Bước mua tiền luôn có thêm kiểm chữ trên màn hình trước và sau khi bấm.
- Icon **Đồng hồ** có kim chạy trên màn hình chính tạo ra «vật mới» liên tục nên mỗi cú bấm ở đó có thể phải chụp lại ảnh nền vài lần
  (chậm 15–30s). Bên trong app / game thì không gặp.
- Kết quả «thất bại» / «không mua được» chỉ được kết luận khi chữ báo lỗi đã hiện ỔN ĐỊNH ít nhất 30 s mà vẫn không thấy «thành công»
  (game chậm có thể hiện «thành công» muộn tới 15–25 s; báo sai «chưa nạp» cho đơn đã trừ tiền là lỗi đắt nhất). Hệ quả: `purchase_wait`
  ngắn (≲ 40 s) thì kết quả lỗi hay chuyển ĐỐI SOÁT hơn là kết luận; mặc định 60 s thì kết luận được. Giới hạn thiết kế: nếu «thành công»
  chỉ hiện sau hơn 30 s kể từ lúc chữ lỗi bắt đầu hiện, đơn vẫn bị báo lỗi.
- Nút rộng của **hộp thoại hệ thống** (vd «Xác minh ID Apple → Để sau»): cú bấm đầu tiên từng bị iOS bỏ qua 1 lần, bấm lần hai mới ăn.
  Chưa tái hiện lại được nên chưa sửa; tạm dùng 2 bước «bấm chữ» (đánh dấu «bỏ qua nếu lỗi») liên tiếp.
- Màn hình nền động hẳn (video) thì không định vị được con trỏ → không bấm (an toàn nhưng bước sẽ hỏng).
