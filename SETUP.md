# Remote-Device: nhật ký cài đặt & việc cần làm

Mục tiêu: dùng 1 Mac điều khiển ~20 iPhone 8 (iOS 16) qua USB để tự động:
mở game → đăng nhập tài khoản khách → chọn gói → thanh toán (xác nhận bằng mật khẩu)
→ kiểm tra kết quả, đồng thời kiểm tra thông số từng máy có chuẩn không.

Cập nhật lần cuối: 2026-11-27

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
- [x] **Bàn phím phần cứng: tắt cả ba mục** — Cài đặt → Cài đặt chung → Bàn phím → Bàn phím thực → «Tự động viết hoa», «Tự động sửa»,
  «Phím tắt "."». Để bật thì iOS tự viết HOA chữ cái đầu của thứ tool gõ vào ô chữ (đo trên trang đăng nhập KONAMI: email của khách bị đổi
  chữ đầu thành chữ hoa) và có thể «sửa» / chèn dấu chấm vào tài khoản. Hai máy 01 và 002 đã tắt (26/11/2026).
- [ ] **Tắt «Tự động điền mật khẩu»** — Cài đặt → Mật khẩu → Tùy chọn mật khẩu (phải có Touch ID / mật mã của chủ máy nên tool không tự làm
  được). Để bật thì sau mỗi lần đăng nhập trên trang web iOS hỏi «Bạn có muốn lưu mật khẩu này…?»; hộp đó **không nhận cú bấm của con
  trỏ**, chỉ đóng được bằng phím Esc (kịch bản phải có bước «nếu thấy `lưu mật khẩu này` thì nhấn phím esc») — và tuyệt đối không được lưu
  mật khẩu của khách lên máy.
- **Không khởi động lại / respring máy đã bypass** để gỡ kẹt. Gặp cảnh «hộp thoại hệ thống hiện ra mà bấm không ăn, trong game thì bấm bình
  thường» (đo trên máy 01, sau lần iOS hỏi lưu mật khẩu): tắt riêng dịch vụ con trỏ trợ năng là hết —
  `pymobiledevice3 developer dvt proclist` tìm pid của `assistivetouchd` rồi `pymobiledevice3 developer dvt kill <pid>` (iOS tự mở lại sau vài giây).

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
./farm status ; ./farm groups ; ./farm start "Tên nhóm" --script "Tên kịch bản" ; ./farm stop iPhoneFarm-01
./farm --help                                # mọi lệnh;  thêm --json để lấy kết quả cho script
```

### Nhóm, máy và kịch bản (mô hình)
- **Nhóm** gom các máy cùng loại. Một máy có thể ở **nhiều nhóm** (thêm / bớt máy ngay trang của từng nhóm). Trang **Thiết bị** chỉ để xem
  thống kê (nhóm của máy, máy đang chạy gì) — không gán nhóm ở đó.
- Trong nhóm có **danh sách kịch bản**. **Cách chạy nằm trong từng kịch bản**: «Chạy 1 lần» hoặc «Lặp lại» (số vòng, 0 = vô hạn), và chạy trên
  những máy nào (ô «Chạy trên máy» + nút Chạy / Dừng trong trình sửa kịch bản). Nhóm không còn «chế độ chạy» / «số vòng» riêng.
- **Một máy chỉ chạy MỘT kịch bản một lúc**: máy hiện «đang chạy {nhóm} · {kịch bản}» (trang Nhóm, trang Thiết bị, `farm status`); chạy thêm kịch bản
  trên máy đang bận bị từ chối và nói rõ máy đang chạy gì. Dừng một nhóm / kịch bản chỉ dừng máy đang chạy đúng việc đó — không đụng việc của nhóm khác.
- **Dừng máy / Tiếp tục / Dừng từng máy** — cùng một bộ nút ở trang Thiết bị (bảng board, và bảng «iPhone cắm USB» với iPhone đã gán board), ở danh sách
  máy trong nhóm và trong kịch bản. «⏸ Dừng máy» (máy đang chạy thì ghi «⏸ Tạm dừng») cho máy đứng yên để **xử lý tay**:
  - máy đang chạy: không kết thúc việc đang chạy (kịch bản: dừng trước bước kế tiếp; máy nhận đơn: làm nốt đơn dở, không nhận đơn mới, và khi
    tiếp tục sẽ kiểm lại «game đã đăng xuất chưa»);
  - máy đang nghỉ: từ lúc đó không kịch bản / đơn nào chạy lên máy, không thử bước / «Dò máy» được, AI / dòng lệnh cũng không điều khiển được
    (AI vẫn XEM được màn hình máy đó như mọi máy đang nghỉ). Lệnh đang chạy dở lúc bấm (thử bước, AI) thì làm nốt — app báo rõ điều này;
  - các thao tác chỉ đụng tới BOARD vẫn làm được khi máy đang dừng: «BLE?», «Khởi động lại board», «Huỷ kết nối BT»;
  - trạng thái «đang dừng» là của MÁY: vẫn còn sau khi việc đang chạy kết thúc hay sau «Dừng tất cả», đi theo máy khi đổi tên board, cho tới khi
    bấm «▶ Tiếp tục». Nó chỉ nằm trong bộ nhớ — khởi động lại app thì máy trở lại bình thường;
  - máy đang «dừng chờ kiểm tra» hiện «Đã kiểm tra xong» (và thêm «Tiếp tục» nếu nó cũng đang dừng để xử lý tay); «Dừng máy» / «Tiếp tục» không bao giờ
    gỡ trạng thái chờ kiểm tra.
  «Dừng» kết thúc hẳn việc đang chạy. Nút **«Dừng tất cả»** ở thanh trên cùng dừng mọi máy đang chạy (có hỏi lại; không gỡ trạng thái «dừng chờ kiểm tra»).
- **Máy đang «dừng chờ kiểm tra» sau đơn của khách** (màn hình giữ nguyên, game có thể còn đăng nhập tài khoản khách): nhóm / kịch bản KHÁC không chạy đè lên được
  — bị bỏ qua và báo rõ; ô «Chạy trên máy» hiện «⚠ dừng chờ kiểm tra» và không tích được. Chỉ «Chạy lại» của chính nhóm nhận đơn đó (tự đăng xuất + kiểm game
  sạch trước; nếu lần chạy lại dừng sớm trước khi kiểm xong thì máy vẫn đang giữ), hoặc người vận hành bấm **«Đã kiểm tra xong»** trên máy đó, mới gỡ được.
  **Bấm Dừng không còn là lời xác nhận** (trước đây Dừng trên máy đã dừng = xác nhận); xoá nhóm còn máy đang giữ bị từ chối.
- **Kịch bản nhận đơn** (cách chạy thứ ba của kịch bản: «nhận đơn từ gateway»): lộ trình của nó là cả vòng đời một đơn —
  ① **Chờ đơn từ gateway** (chọn pool mà kịch bản phục vụ) → ② **Giữ chỗ cho máy** (tool xin đơn; gateway giao cho đúng một máy) → các giai đoạn
  **Đăng nhập · Nhập OTP · Vào danh sách gói · Mua một gói · Sau mỗi lần mua** → **Báo kết quả cho gateway** → **Kết thúc đơn**.
  Hai trạm đầu và trạm «báo kết quả» là việc tool tự làm với gateway (không sửa / xoá được); mỗi giai đoạn có danh sách bước riêng, nút
  «Thêm bước» và «Thử» riêng. Giai đoạn chưa có bước riêng thì máy chạy bước cấu hình ở pool trên gateway («dùng N bước của gateway»); luật nhận
  diện (chưa đăng nhập / đăng nhập thành công / nạp thành công…) và gói nạp vẫn lấy từ pool.
  - Nó chạy bằng **đúng bộ máy của chế độ nhận đơn** (`Runner._run_api`): cùng vòng xin đơn, sổ đơn, «dừng chờ kiểm tra», nhịp tim — nên **bản web
    không chạy được** (từ chối như nhóm nhận đơn), máy đang nhận đơn bằng kịch bản được coi là máy của khách, và máy đang giữ chỉ «Chạy lại» được
    bằng CHÍNH kịch bản đó (nút «Chạy lại» hiện cạnh máy ấy trong dải «Chạy» của trình sửa kịch bản, có hỏi lại). «Thử» một giai đoạn chưa có
    bước riêng chỉ dùng bước của gateway khi pool đang nạp trong trình sửa đúng là pool của kịch bản. Bấm «Chạy» ở app cửa sổ có hỏi lại vì máy sẽ nhận ĐƠN THẬT. `list_groups` (AI / dòng lệnh) ghi «NHẬN ĐƠN THẬT từ pool …».
  - Đổi kịch bản thường sang «nhận đơn»: các bước đang có thành giai đoạn «Đăng nhập». Đổi ngược lại: nếu chỉ «Đăng nhập» có bước thì chúng quay
    về làm danh sách bước thường; cấu hình nhận đơn đã soạn vẫn được giữ.
  - «Thử» giai đoạn «Mua một gói» có hỏi lại (bấm mua thật). Thời gian chờ đăng nhập / chờ kết quả mua hiện dùng mặc định (45 / 60 giây).
  - **Dữ liệu của đơn (tài khoản, mật khẩu, OTP, gói)** đi vào bước qua ô bấm **«Lấy từ đơn»** trong hộp thoại «Gõ chữ»: bấm «Email Konami ID» là
    bước gõ `{{username}}`, «Mật khẩu» là `{{password}}` — lúc chạy tool thay bằng giá trị trong đơn của khách (nhật ký chỉ ghi tên, không ghi giá
    trị). Các ô này chính là **«trường đăng nhập» của pool trên gateway** (trang quản trị → Pool); muốn thêm trường thì thêm ở đó. Chưa đọc được
    pool thì tool không đoán tên (bước dùng một trường mà đơn không có sẽ làm dừng đơn). Giai đoạn «Nhập OTP» có thêm `{{otp}}`; «Mua một gói» và
    «Sau mỗi lần mua» có thêm `{{package.ocr_text}}` / `{{package.price_text}}` / `{{package.name}}` — các bước «tìm chữ» ở hai giai đoạn đó cũng có ô
    bấm cho chữ của gói (không bao giờ gợi ý tài khoản / mật khẩu cho bước tìm chữ). «Thử» một bước / giai đoạn có dùng dữ liệu của đơn thì tool
    hỏi giá trị thử (không lưu).
- **«Bấm vào chữ» / «Bấm giữ vào chữ» chờ chữ hiện ra** (`"timeout": N` giây, tối đa 60): chữ chưa có thì máy nhìn lại mỗi giây tới hết N giây rồi
  mới báo không thấy; thấy ở lần nhìn lại thì chờ màn hình đứng yên rồi mới lấy vị trí. Bước **mới** thêm trong trình sửa mặc định chờ 5 giây; bước
  cũ không ghi gì vẫn nhìn đúng một lần (không tự đổi hành vi của kịch bản đang chạy đơn). Lý do — đo trên eFootball (iPhone 8):
  - màn hình game chuyển cảnh mất 1–3 giây: bấm «Data Transfer» xong, 0,9 giây sau màn kế chưa vẽ xong nên bước bấm chữ kế tiếp «không thấy chữ»;
  - khởi động mới, game mất **~24 giây** mới tới màn tiêu đề (màn đen → logo KONAMI → «THE PITCH IS OURS» → tiêu đề). Bước bấm theo **toạ độ** luôn
    báo ✓ dù bấm vào đâu, nên trước nó phải có «Chờ thấy chữ» của màn hình cần tới (vd `Konami Digital Entertainment`, tối đa 60 giây);
  - **«Mở app» bằng ô tìm kiếm chỉ đưa game ra trước, không khởi động lại**: game đang nằm ở màn nào từ lượt trước thì vẫn ở màn đó (vd «Data
    Transfer»), kịch bản chờ màn tiêu đề sẽ hết giờ → dùng «tắt hẳn rồi mở mới» (mục dưới).
- **«Mở app»: tắt hẳn rồi mở mới** (`"fresh": true`; bước mới trong trình sửa mặc định chọn kiểu này) — đi qua USB (`app/iosapp.py`, cùng kênh
  với chụp màn hình), không gõ phím nào, ~1 giây: app bị tắt hẳn rồi khởi động lại nên lần nào kịch bản cũng bắt đầu từ màn đầu. App được tìm theo
  tên hiển thị / tên gói / bundle id: đúng bằng tên gõ thì thắng app chỉ «có chứa»; app ẩn của hệ thống (máy thật có hơn trăm cái, ba cái cùng
  tên «Cài đặt») chỉ chọn được bằng đúng bundle id; không thấy / nhiều app cùng khớp → bước hỏng kèm lý do (không đoán, không lặng lẽ quay về
  cách mở cũ). Trong kịch bản nhận đơn, bước này thuộc «đoạn mở game» nên mỗi lần kiểm «game chưa đăng nhập» game cũng được mở mới.
- **«Bấm vào vùng ảnh»** (`tap_image`) — cho nút KHÔNG có chữ (biểu tượng menu, nút tròn…), thay cho bấm theo toạ độ cố định (toạ độ thì bấm
  bừa cả khi nút chưa hiện / đang ở màn hình khác). Trong trình sửa: «Thêm bước» → «Bấm vào vùng ảnh» → **kéo một khung** quanh nút trên ảnh
  màn hình (lúc bật «Bấm vào ảnh để thêm bước chạm»: bấm một điểm = toạ độ, kéo một khung = vùng ảnh). Hình vừa khoanh hiện ngay trong câu của
  bước. Lúc chạy máy tìm đúng hình đó ở BẤT KỲ chỗ nào trên màn hình rồi bấm vào giữa; có ghi thời gian chờ thì hình chưa hiện sẽ được chờ
  (bước mới mặc định 5 giây — đặt 60 giây cho nút ở màn tiêu đề thì khỏi cần bước «chờ game tải xong» riêng).
  - Điểm giống = độ khớp hình dạng × (1 − chênh lệch màu / độ sáng); mặc định phải ≥ 90% (sửa bước để đổi). Đo trên iPhone 8, nút menu ở màn
    tiêu đề eFootball: đúng hình 100% trên cả hai máy; nén ảnh / nhoè nhẹ 95–97%; **màn hình bị phủ mờ (hộp thoại che lên) 87%, mất màu 75%,
    ảnh lệch tỉ lệ 3% 79% → không bấm**; chỗ giống nhì trên cùng màn hình 33%. Tìm một lần ~30 ms.
  - Nhiều chỗ giống hệt nhau (dãy nút mua không chữ) → xét HẾT rồi bấm chỗ gần nơi hình được cắt ra nhất; quá 60 chỗ (hoa văn lặp kín màn
    hình) mà chỗ cắt không còn hình đó → không phân xử được, không bấm (báo «quá nhiều chỗ giống»); hình còn nằm đúng chỗ được cắt thì bấm
    luôn chỗ đó. Hình biến mất trước khi con trỏ tới nơi → không bấm. Trước khi tìm, con trỏ được cất về góc. Nên khoanh SÁT một nút — khoanh
    trùm nhiều nút giống nhau thì khi dãy nút xê dịch máy có thể chọn lệch một nút.
  - Phần giao diện của bước này gắn với trang (kéo khung, cắt ảnh, hộp sửa bước) chỉ được thử TAY trên trình sửa thật với hai iPhone 8; bài
    thử tự động (`test_ui_steps.py`) chỉ phủ các hàm thuần (đổi khung kéo ra toạ độ, kiểm ảnh, đọc ô «giống tối thiểu», lấy bước của gateway…).
  - Giới hạn: hình chỉ khớp với máy CÙNG độ phân giải với lúc cắt (chiều xoay thì không sao khi tool dò được chiều — ảnh chụp được quay thẳng, xem «Ảnh chụp bị xoay»); nền phía sau nút thay đổi nhiều (video, hiệu ứng)
    thì phải khoanh sát nút hoặc hạ độ giống. Ảnh mẫu (PNG) nằm trong chính dữ liệu của bước; không gửi lên gateway.
- **Đăng nhập eFootball (Data Transfer → KONAMI ID) — các trường hợp đã gặp trên máy thật** (chạy lặp ngày 27/11/2026 trên hai iPhone 8, có bộ
  ghi màn hình nền gom từng màn mới; luật của pool `efootball-ios` trên gateway dev đã đổi sang đúng các câu này):
  | Màn / câu trên màn | Nghĩa | Kịch bản xử lý |
  |---|---|---|
  | «Tính năng mới trong Game Center» / «Chào mừng đến Game Center» | iOS hỏi Game Center (máy mới) | «nếu thấy» → «Tiếp tục» / «Hủy» |
  | «"eFootball™" muốn sử dụng "konami.net" để đăng nhập» | hỏi mở trang đăng nhập | «Tiếp tục» (máy 01 có lúc phải bấm 2 lần) |
  | trang trống «KONAMI ID / E-mail address» | chưa từng đăng nhập trên máy | gõ email |
  | trang **còn nhớ email của lần trước** + «Password» + «Log In with Another KONAMI ID» | đã có đơn đăng nhập thành công trên máy | **bấm «Log In with Another KONAMI ID» trước** — không thì mật khẩu khách mới bị gõ vào tài khoản khách cũ → «sai mật khẩu» oan, lộ email khách cũ (bước đã thêm, CHƯA chạy thử trên máy) |
  | «Please enter a combination of alphanumeric characters of 10-32 characters in length.» | ô mật khẩu trống (gõ không vào ô) | lỗi của tool — bấm vào GIỮA ô rồi gõ |
  | «Unable to log in. Please check your login ID and password.» | sai email / mật khẩu | báo khách, hoàn |
  | «Bạn có muốn lưu mật khẩu này…» | iOS hỏi lưu mật khẩu | phím Esc (không nhận cú bấm) |
  | «Two-Step Verification — Please enter the 6-digit verification code…» | cần mã | giai đoạn «Nhập OTP»: bấm ô đầu, gõ từng số cách 0,4 giây, Enter |
  | (không hỏi mã, vào thẳng «Data Transferred») | tài khoản đã đăng nhập trên MÁY NÀY trong 180 ngày (ô «Skip two-factor … 180 days» bật sẵn) | — |
  | «Your verification code is incorrect.» | sai mã | xin lại mã |
  | «Data Transferred — You can transfer your data N more times. This number is reset monthly.» [To Title Screen] | **thành công**; mỗi lần tiêu 1 lượt / tháng | chụp lại |
  | «Cannot Transfer Data — Data transfer failed.» [OK] | tài khoản chưa liên kết với game — **hoặc** trang đăng nhập bị huỷ («Hủy») | báo khách (tool không tự huỷ giữa chừng) |
  | «Cannot Transfer Data — You have reached your data transfer limit…» | hết lượt tháng (theo tài liệu, chưa gặp) | báo khách |
  | «Download Latest Data?» [Cancel / Download] | sau khi vào game | «Download» |
  | «Login Bonus» (1–2 trang), «… Campaign» [Continue], «Sign Players» [OK — chữ OK không đọc được] | sau màn tiêu đề, hiện muộn | «nếu thấy» chờ 60 giây, xong khi thấy «Shop» liên tục 4 giây; «Sign Players» → bấm tại toạ độ |
  | «Purpose of Data Processing for Digital Advertising» | tài khoản mới vào game lần đầu | chưa có bước xử lý (gặp một lần, lướt hết thì qua) |
  - Thư mã xác minh của tài khoản test thứ hai **không về** hộp thư tạm sau 2 lần thử — chưa rõ do Konami hay do hộp thư.
  - **Ảnh chụp bị xoay (máy 01):** sau khi mở trang đăng nhập web, máy 01 có lúc chụp ra khung DỌC (750×1334) trong khi game vẫn NGANG — kéo dài cả
    khi mở lại game. **Tool tự quay THẲNG mọi ảnh chụp** theo chữ trên màn hình (`Eyes.screenshot` → `ocr.upright_turn`): ảnh trả ra luôn cùng
    chiều với giao diện, nên bước theo toạ độ, «bấm tại toạ độ», «bấm vào vùng ảnh», hướng lướt và «trong cùng ô» soạn trên ảnh thẳng dùng
    được nguyên vẹn; con trỏ tự dò hướng của ảnh so với trục chuột theo góc nó hiện ra (như game xoay ngang). Đã chạy thật trên máy 01 đang bị
    xoay: bấm (665,645) ở màn tiêu đề, «Sign Players» bấm tại (667,571), vào Shop, lướt trái tìm ô 15,000 — CHF 93.00, bấm nút menu bằng vùng
    ảnh 90×90 → đều đúng (trước đây «Tap (1257,682)» hỏng).
    - Cách quay được NHỚ theo từng máy; chỉ xét lại khi cỡ ảnh chụp đổi, màn hình đổi nhiều (sau ít nhất 2 giây), lần trước chưa chắc (màn
      hình ít chữ — đang tải, logo: giữ cách quay cũ), hoặc đã 30 giây. Lần xét lại dùng chung kết quả đọc chữ với bước đang chạy (không tốn
      thêm khi ảnh đã thẳng). Trong lúc đưa con trỏ KHÔNG xét lại; ảnh đổi cỡ / chiều giữa lúc đưa con trỏ → không bấm.
    - Chiều đúng (chứ không lộn ngược 180°) = chiều mà ký tự đầu của dòng nằm bên trái ký tự cuối (Vision đọc được cả chữ lộn ngược). Dòng
      một từ không cho biết chiều (Vision trả hộp cả từ cho từng ký tự) — bị bỏ qua khi đếm; màn hình CHỈ có dòng một từ thì «chưa biết»,
      giữ cách quay cũ (không đoán — đoán sai là ảnh lộn ngược, bấm toạ độ vào điểm đối xứng).
    - Ảnh nền đầu tiên của mỗi lần bấm được xét lại (bước bấm toạ độ không có lần nhìn nào trước); màn hình ít chữ («chưa chắc») hoặc có
      hoạt hình thì mỗi lần chụp ngoài lúc đưa con trỏ có thể tốn một lượt đọc chữ, cách nhau ít nhất 2 giây.
    - Cần Apple Vision: chạy với `IPF_OCR=tesseract` (không dùng Vision) thì KHÔNG quay thẳng được. Vùng ảnh / toạ độ đã ghi trên ảnh NGHIÊNG
      trước đây (nếu có) phải ghi lại trên ảnh thẳng.
    - Lần chạy thật đầu tiên, bước «nếu thấy chữ» (Sign Players → bấm tại (667,571)) báo «con trỏ không tới được…» một lần; chạy lại thì được.
      Chưa rõ nguyên nhân (không lặp lại).
    - Hộp thoại hệ thống không nhận cú bấm trên máy 01 cũng xảy ra trong trạng thái này (xem «assistivetouchd»).
  - Vision có lúc đọc chữ Latin thành chữ Kirin trông giống hệt («OK» → «ОK»): khi so khớp đã đổi về Latin.
- **Gói nạp — cấu hình và cách tool tìm đúng gói.** Mỗi gói khai ở gateway (trang quản trị → Pool → mục 5 «Gói nạp»): **Mã gói** (thứ shop gửi
  trong `items[].code`), **Tên**, **Chữ OCR để dò** = số coin in trên ô gói (nhiều cách viết ngăn bằng `|`, vd `1,000|1000`), **Giá hiển thị** = giá
  in trên CÙNG ô đó (vd `CHF 7.50`), **Giới hạn mua** (gói sale / Starter Set: «Chỉ 1 lần»). Lúc mua, giai đoạn «Mua một gói» của kịch bản dùng
  `{{package.ocr_text}}` / `{{package.price_text}}` của gói trong đơn.
  - Đo trên danh sách gói eFootball thật (iPhone 8 xoay ngang, tài khoản Apple vùng Thuỵ Sĩ → giá CHF), có **15 ô**: 3 ô Coin Sale có hạn
    (500 — 2.30 · 1,500 — 7.50 · 4,500 — 21.00), 3 ô Starter Set (10 — 0.60 · 50 — 0.60 · 100 — 1.80), 9 ô thường (100 — 0.80 · 300 — 2.30 ·
    500 — 3.80 · 1,000 — 7.50 · 2,000 — 15.00 · 3,000 — 21.00 · 5,000 — 34.00 · 10,000 — 63.00 · 15,000 — 93.00). **Cùng số coin có hai ô**
    (500 sale / 500 thường), **cùng giá có hai ô** (2.30 = sale 500 / thường 300; 7.50; 21.00; 0.60), chữ «100» còn nằm trong «Paid: 100» →
    tìm theo MỘT chữ là bấm nhầm. Phải khớp **số coin + giá trong cùng một ô** (bước dưới). Gateway dev đã có đúng 15 gói này (mã `coin_100` …
    `coin_15000`, `sale_500` / `sale_1500` / `sale_4500`, `starter_bambang` / `starter_suarez` / `starter_casillas`).
  - **Giá phụ thuộc vùng của tài khoản Apple trên MÁY** (không phải tài khoản game của khách): máy dùng Apple ID vùng khác thì giá in khác
    (₫, $…) → «Giá hiển thị» phải khớp với vùng của các máy đang chạy pool đó. Gói Coin Sale có hạn dùng (đếm ngược trên ô) — hết hạn thì
    tắt «Bán» của gói đó.
- **«Bấm vào chữ» / «Kiểm có chữ» trong CÙNG MỘT Ô** (`"near"`: chữ phải đi kèm, `"near_dir"`: nó nằm ngay dưới (mặc định) / bên phải / bên trái — không có «ngay trên»: bố cục có chữ đi kèm nằm trên thì tìm chữ phía trên, chữ đi kèm là chữ ngay dưới nó;
  `"scroll"`: chưa thấy thì lướt danh sách left / right / up / down, `"scrolls"`: tối đa mấy lần, mặc định 8). Bước mua gói của kịch bản
  «nạp Efootball»: `{"type":"tap_text","text":"{{package.ocr_text}}","near":"{{package.price_text}}","scroll":"left","timeout":5}`.
  - «Cùng ô» = chữ đi kèm thẳng cột (lệch ≤ 15% bề ngang) và cách ≤ 35% bề cao (bên trái / phải: cùng hàng, cách ≤ 25% bề ngang) theo hướng đã
    chọn, và **giữa hai chữ không có dòng nào CÙNG LOẠI với chữ cần tìm** — cùng loại = cùng là số thuần («300», «1,500»), hoặc cùng khung chữ khi
    coi mọi cụm số như nhau («500 Coins» / «1,500 Coins»): có một số coin khác nằm giữa = giá đó thuộc ô khác. Cả hai chữ phải khớp NGUYÊN DÒNG
    («500» không khớp «1,500», «100» không khớp «Paid: 100», «26.000đ» không khớp «126.000đ») — đọc chữ ra khác đi thì khai thêm cách viết
    bằng «|». Bỏ qua chữ chạm mép màn hình (ô bị cắt dở), và dòng toàn số nằm SÁT một mảnh số khác cùng hàng (bộ đọc chữ có lúc tách «1,500»
    thành «1,» + «500» — mảnh «500» không được tính là gói 500). **Từ hai ô trở lên cùng đủ điều kiện → không chọn** (nhập nhằng, không đoán).
    Lướt hết danh sách một chiều (lướt mà chữ không đổi) thì tự lướt ngược. Danh sách trôi trước khi con trỏ tới nơi → không bấm.
  - Lướt xong xuôi mà không thấy gói → bước hỏng, KHÔNG tính là «đã chạm luồng mua» (gói sale hết hạn = đơn «chưa nạp», không làm máy dừng
    chờ đối soát); chỉ cú lướt hỏng giữa chừng (không rõ đã nhả nút chưa) mới tính là đã chạm. Một bước tìm gói lướt tối đa 8 + 16 lần, mỗi
    lần vài giây — với danh sách eFootball (15 ô) tìm thấy trong khoảng 1 phút.
  - **Thử khô** việc tìm gói: dùng «Kiểm có chữ» với cùng chữ đi kèm + hướng lướt — chỉ lướt, KHÔNG bấm vào ô gói. Đã thử trên máy thật với
    dữ liệu gói của gateway: 15,000 — CHF 93.00, Starter 100 — CHF 1.80, sale 500 — CHF 2.30, thường 1,000 — CHF 7.50 đều tìm đúng ô.
  - **Chạy thử cả luồng (2026-11-27, máy 01, tài khoản test 1, gói 100 — CHF 0.80):** đăng nhập 17/17 (không hỏi mã — máy đã đăng nhập tài
    khoản này trong 180 ngày), vào Shop 8/8, bấm đúng ô 100 / CHF 0.80 → **bảng mua của App Store chỉ có «Thanh toán bằng Touch ID»** (không có
    nút Mua, không có ô mật khẩu). Board chuột / bàn phím KHÔNG đặt vân tay được → **tool chưa xác nhận mua được**. Đã đóng bảng (X): không
    trừ tiền, game không báo gì, chỉ quay về danh sách gói (đơn chạy thật sẽ hết `purchase_wait` → «không chắc» → máy dừng chờ đối soát).
    Chữ trên bảng: «App Store», «100Coins(PaidCoins97 + Free3)», «In-App-Kauf», «CHF 0.80», «Einmalige Gebühr», «Account: <Apple ID của
    máy>», «Thanh toán bằng Touch ID». Việc cần quyết: cách xác nhận mua không cần vân tay (vd tắt Touch ID cho iTunes & App Store trong
    Cài đặt → Touch ID & Mật mã, để bảng mua hỏi mật khẩu Apple ID — tool gõ được, nhưng phải lưu mật khẩu Apple ID của từng máy).
    Các bước sau bấm ô và luật «nạp thành công» / «thất bại» của pool vì thế vẫn chưa soạn.
  - **Máy 01 bị coi là đang cầm DỌC:** bảng mua của App Store (và trang đăng nhập web) hiện DỌC trong khi game NGANG; đóng bảng mua xong
    game chuyển sang bố cục dọc (khung 750×1334, nội dung thu nhỏ). Máy 002 không bị. Nên kiểm «Khoá hướng dọc» trong Trung tâm điều khiển
    của máy 01 và tư thế đặt máy. Ảnh vẫn được quay thẳng đúng (xem «Ảnh chụp bị xoay»).
- **«Gõ chữ» từng ký tự** (`"gap": giây`, 0 = gõ liền một mạch như trước). Đo trên trang đăng nhập KONAMI (iPhone 8):
  - ô mã «mỗi số một ô» tự nhảy sang ô kế bằng mã của trang — gõ liền 6 số chỉ vào được 2 số; gõ từng số cách nhau 0,4–0,6 giây thì đủ cả 6;
  - gõ liền một mạch email 24 ký tự vào ô KONAMI ID có lần **rơi mất 6 ký tự ở giữa** (trang báo «The email address you entered is invalid»);
    gõ từng ký tự thì đúng. Kịch bản «nạp Efootball» vì thế gõ tài khoản / mật khẩu với quãng nghỉ 0,12 giây.
  - **Tool chưa kiểm lại được chữ vừa gõ** (ô mật khẩu thì không thể): gõ sai tài khoản sẽ ra «sai tài khoản / mật khẩu» ở game chứ không phải
    lỗi của tool — luật «đăng nhập thất bại» của pool vì thế chưa đủ để kết luận khách đưa sai. Việc cần làm tiếp.
- **Bước có điều kiện «Nếu thấy chữ … thì bấm …»** (`tap_if`) — cho thứ lúc có lúc không ngay sau một bước (hộp thoại Game Center, hỏi mật khẩu,
  thông báo, quảng cáo). Một bước chứa được NHIỀU trường hợp, gõ mỗi dòng một cái: `thấy chữ gì => bấm chữ gì` (bỏ «=> …» thì bấm chính chữ đó;
  nhiều cách viết ngăn bằng `|`; **`=> phím esc`** = NHẤN PHÍM đó thay cho bấm — cho hộp thoại không nhận cú bấm của con trỏ, vd iOS hỏi lưu mật
  khẩu; phím dùng được: esc, enter, tab, back, space). Máy nhìn màn hình tối đa «chờ … giây»: không thấy trường hợp nào → bước XONG, kịch bản
  đi tiếp; thấy → bấm (hoặc nhấn phím) rồi **nhìn lại xem hộp thoại đã đóng chưa**: còn thì làm lại, hết thì xong (cú bấm lên hộp thoại hệ
  thống có lúc không «ăn» — trước đây bước một trường hợp báo ✓ ngay sau lần bấm đầu nên các bước sau trượt khó hiểu). Bước nhiều trường hợp
  còn chờ thêm xem hộp thoại khác có hiện nối theo không. Trước khi làm lại, bước chờ thêm 1,5 giây rồi nhìn lần nữa — hộp thoại đóng chậm
  không bị bấm / nhấn phím lần hai (phím esc thứ hai sẽ rơi vào màn hình bên dưới). Hộp thoại «lúc thấy lúc không» quá 4 lần nhìn lại → bước
  hỏng (không nhìn mãi).
  - **«Xong khi thấy chữ»** (`"until"`): chữ chỉ có khi KHÔNG còn hộp thoại nào che (vd tab «Shop» của màn chính eFootball) — thấy nó, không có
    trường hợp nào, LIÊN TỤC đủ 4 giây thì bước xong ngay, không chờ hết thời gian chờ. Nhờ vậy chờ được lâu (60 giây — các hộp thoại «Login Bonus»,
    «Campaign», «Sign Players» hiện muộn sau khi game tải) mà không tốn thời gian khi đã sạch. Phải «liên tục»: đo thật, tab «Shop» hiện thoáng
    qua vài giây TRƯỚC khi «Login Bonus» trượt vào.
  - **«Bấm tại toạ độ»** (`=> @667,571`, dữ liệu `{"text":"Sign Players","at":[667,571]}`): cho nút mà bộ đọc chữ không đọc được (đo thật: chữ «OK»
    xanh nhạt của hộp «Sign Players» không có trong kết quả đọc, phím Enter cũng không đóng được). Chỉ bấm khi chữ của hộp thoại đang hiện,
    kiểm lại ngay trước cú bấm (hộp thoại vừa đóng thì không bấm). Một trường hợp «bấm chữ» chỉ tính là «xảy ra» khi thấy **cả chữ của nó lẫn chữ cần
  bấm**: thấy chữ mà chưa có nút thì xét trường hợp kế và nhìn lại; hết thời gian chờ vẫn vậy, hoặc làm 2 lần vẫn còn → bước hỏng (màn hình
  đang bị chắn, đi tiếp là bấm nhầm). Trường hợp ĐÃ xử lý mà chữ còn, nút không còn: chữ ở CHỖ KHÁC chỗ lúc bấm (vd «konami.net» trên thanh
  địa chỉ của trang vừa mở) = hộp thoại đã đóng; chữ ở ĐÚNG CHỖ cũ = hộp thoại HIỆN LẠI → chờ nút thêm 3 giây, không có thì bước hỏng. Vì bước đòi hộp thoại phải ĐÓNG, đừng dùng nó cho thứ bấm xong vẫn còn trên màn hình (thẻ, nút bật / tắt)
  — dùng «bấm vào chữ». Trong giai đoạn mua, bước này bị bỏ qua (không thấy gì) thì KHÔNG tính là «đã chạm luồng mua»; đã bấm thì có tính. Vì thế **mỗi trang ghi một dòng với chữ riêng của trang đó** — đo trên iPhone 8: lần đầu mở eFootball, iOS hiện «Tính năng
  mới trong Game Center» (chỉ có «Tiếp tục») rồi mới tới «Chào mừng đến Game Center» (có «Hủy»); ghi chung một dòng «Game Center => Hủy» thì trang
  đầu không có gì để bấm. Dữ liệu: `{"type":"tap_if","cases":[{"text":"Tính năng mới","tap":"Tiếp tục"},{"text":"Chào mừng đến","tap":"Hủy"}],"timeout":8}`
  (một trường hợp thì ghi gọn `text` / `tap`). iOS thôi hỏi Game Center sau vài lần bấm «Hủy» cho cùng một game, nên máy đã chạy lâu sẽ không còn
  gặp — khi đó bước tốn trọn thời gian chờ rồi bỏ qua. (Vì vậy chuỗi «Tiếp tục» → «Hủy» của Game Center mới chỉ được kiểm bằng bài thử dựng lại
  đúng chữ đã đọc trên máy thật, CHƯA bấm lại được trên máy thật.) Trong kịch bản nhận đơn, bước này ở đầu giai đoạn «Đăng nhập» được coi là thuộc **đoạn mở game** —
  nó cũng chạy khi máy kiểm «game chưa đăng nhập» trước lúc nhận đơn (không dọn hộp thoại thì không nhìn thấy gì). Đừng dùng nó để bấm vào thứ đụng
  tới tài khoản của khách.
- **Tìm chữ: dòng khớp NGUYÊN DÒNG được chọn trước** dòng chỉ «có chứa» chữ đó (cùng loại thì lấy dòng đầu theo thứ tự đọc; dấu câu / ký
  hiệu quanh chữ không tính). Đo trên trang đăng nhập KONAMI: tìm «Login» từng khớp cả dòng «Log In with Another KONAMI ID» nằm phía trên nút
  «Login» (so chữ bỏ qua khoảng trắng) — bấm theo chỗ khớp đầu tiên là bấm nhầm sang nút đổi tài khoản. Kịch bản / luật pool cân chỉnh theo
  quy tắc cũ («chỗ khớp đầu tiên») nên được chạy thử lại trên máy thật; bộ đọc chữ Vision cũng đọc được nhiều chữ hơn tesseract trước đây.
- **Nút của trang web đổi màu khi con trỏ rê tới** (hover): bộ định vị con trỏ trước đây chỉ tách được con trỏ khỏi «nút được phủ sáng» cỡ nhỏ
  (≤ 60 lần diện tích con trỏ, và chữ trên nút không đổi màu) nên nút «Login» của trang KONAMI (932×92 px, đổi cả màu nền lẫn màu chữ) làm tool
  mất dấu con trỏ → không bấm. Nay nhận nút tới 140 lần diện tích con trỏ, cho phép chữ trên nút đổi màu theo (tối đa 8% diện tích nút) và bào bỏ
  nét chữ trước khi tìm chấm tròn — đo đúng ở 180/180 vị trí quét quanh chữ «Login» trên ảnh thật. Cỡ con trỏ nay tính theo CẠNH NGẮN của ảnh
  (ảnh chụp ngang của iPhone 8 từng bị coi là máy ×3).
- **Trang «Theo dõi»** (menu trái): (1) **Đang chạy** — mỗi máy một dòng: đang chạy gì (nhận đơn / kịch bản / chạy thử / AI), nhóm · kịch bản,
  đơn nào, giai đoạn, **bước thứ mấy / tổng số và là bước gì**, chạy được bao lâu; vừa xong thì hiện bước vừa xong kèm ✓ / ✗ và lý do. (2) **Lịch
  sử theo máy** — gom theo từng lượt chạy (mới nhất trên cùng), mỗi bước một dòng: giờ, kết quả, lý do khi hỏng, mất bao lâu; xen các mốc bắt đầu /
  kết thúc đơn và lời nhắn của bộ chạy. (3) **Lịch sử theo đơn** — mỗi đơn một dòng (lúc, mã, máy, gói, kết quả, số bước lỗi, mất bao lâu); bấm
  vào đơn để xem các bước của đúng đơn đó. Bấm một máy ở «Đang chạy» là mở lịch sử của máy đó.
  - Mọi bước chạy trên máy đều được ghi — kịch bản, đơn của khách, nút «Thử», AI / dòng lệnh `farm` — trong `app/data/history/` (không có trong git).
    Tệp của một máy quá ~3 MB thì bỏ nửa cũ; sổ đơn giữ 3000 đơn gần nhất.
  - **Không có thông tin đăng nhập của khách**: bước ghi bằng lời mô tả đã che (`{{username}}`, `{{password}}`, `{{otp}}` giữ nguyên tên biến), bước
    «gõ chữ» ghi TRỰC TIẾP (không qua biến — có thể là mật khẩu gõ tay) chỉ ghi số ký tự — cả trong lời báo lỗi của bước, lời nhắn và kết quả
    của đơn (bước hỏng / «không gõ được»), lỗi bất ngờ chỉ ghi tên loại lỗi; của đơn chỉ ghi mã
    đơn + gói. Thông tin gói (số coin, giá) thì hiện đúng giá trị. (Lời nhắn «Worker dừng vì lỗi không mong đợi: …» của bộ chạy vẫn chép nguyên
    lời lỗi như nhật ký chạy trước giờ.)
  - Ghi lịch sử hỏng (đĩa đầy, thư mục lỗi) không làm hỏng bước đang chạy.
- **Máy xoay NGANG (game)**: chuột Bluetooth luôn chạy theo trục DỌC của máy — «về góc» ghim con trỏ ở góc trên-phải (hoặc dưới-trái) của ảnh chụp
  ngang, di +x làm con trỏ đi xuống trên ảnh. `nav.tap_at` tự nhận ra hướng ở mỗi lần bấm (xem con trỏ rời góc nào), quay ảnh về hệ trục của chuột để
  đo, đổi điểm cần bấm và hướng vuốt sang hệ đó (`nav.Frame`). Không phân định được hướng → không bấm. Đo trên iPhone 8 đang mở eFootball: tới đích
  giữa màn hình ngang trong ~6 giây. Toạ độ trong kịch bản vẫn là toạ độ của ảnh chụp như người dùng thấy.
- Nhóm ở chế độ **nhận đơn API** (kiểu cũ: cả nhóm nhận đơn, bước chia 6 giai đoạn ở mức nhóm) vẫn hoạt động như trước; giao diện không còn chỗ
  tạo loại nhóm này — dùng «kịch bản nhận đơn» thay thế.
- **Tool tự báo cho gateway** (`app/presence.py` → `POST /api/tool/sync`; gateway ở ngoài mạng nên chỉ tool gọi lên được): cứ ~20 giây và ngay khi có
  thay đổi, tool gửi (a) **máy nào đang rảnh ở kịch bản nào** — trạng thái từng máy + các kịch bản của mọi nhóm máy đang ở — và (b) **danh mục kịch bản**
  (tên, nhóm, cách chạy, số bước, tên các `{{biến}}`, dàn ý loại bước + ghi chú; chỉ gửi khi đổi).
  - Máy chỉ báo **«rảnh»** khi: board còn cắm, iPhone đang cắm **USB**, lần đọc Bluetooth gần nhất là **đã nối**, không chạy gì, không bị «Dừng máy»,
    không «dừng chờ kiểm tra», sổ đơn (`api_state.json`) không còn đơn dở chưa báo xong, không ai điều khiển tay, không đang nạp firmware / dò máy.
    Tên khác trỏ vào cùng iPhone / board với một máy của khách cũng không rảnh. **Không chắc thì không báo rảnh.**
  - **Không rời khỏi máy**: chữ gõ / toạ độ / tên app trong các bước, UDID, cổng serial, lý do «dừng chờ kiểm tra».
  - Chạy ở cả app cửa sổ lẫn bản web (bản web báo kèm «không nhận đơn»), nhưng mỗi bản cài chỉ **một tiến trình** được báo (tệp khoá
    `app/data/presence.lock`): mở cả hai cùng lúc thì bên mở sau không báo và nói rõ ở dòng trạng thái.
  - Dòng trạng thái nằm ở đầu trang **Nhóm & Kịch bản** («Đã báo gateway lúc … · báo ngay»); phía gateway xem ở **Kịch bản & máy**.
    Lỗi mạng lùi 30 giây; sai khoá / gateway bản cũ / lời báo bị từ chối lùi 5 phút (gateway chặn IP sai khoá nhiều lần). Đang quét board thì bỏ nhịp;
    tệp máy / nhóm đọc lỗi thì không gửi gì (không bao giờ báo nhầm «hết máy / hết kịch bản»).
  - **Giới hạn đã biết** (phải xử lý trước khi gateway dùng «máy rảnh» để giao việc):
    - trạng thái Bluetooth lấy từ lần quét board / lần bấm «BLE?», «Khởi động lại», «Huỷ kết nối BT» gần nhất — Bluetooth rớt SAU đó mà chưa quét
      lại thì máy vẫn còn được báo rảnh cho tới lượt quét kế;
    - tiến trình đang báo chỉ biết việc của CHÍNH NÓ: mở bản web trước rồi mới mở app cửa sổ thì app cửa sổ không báo, và gateway không thấy máy nào
      app cửa sổ đang chạy kịch bản / đang dừng (chỉ đơn dở trong sổ là thấy). Khi chạy thật chỉ mở MỘT trong hai;
    - sổ đơn (`api_state.json`) bị hỏng: luồng tự báo đọc CHẶT (`Journal.peek`) nên báo máy đó «đang giữ» chứ không báo rảnh; các chỗ khác vẫn
      đọc nó như «không có đơn dở» (ghi sổ là ghi trọn nên hiếm; gateway vẫn tự chặn máy nó biết đang giữ đơn).
  - Kiểm bằng `app/tests/test_presence.py` (116 mục, có chạy với gateway thật). Hiện mới là BÁO TIN: gateway chưa giao việc theo kịch bản,
    và kịch bản chạy tay chưa thế `{{biến}}` bằng dữ liệu.
- MCP / CLI: `list_groups` liệt kê kịch bản (tên, số bước, cách chạy — không lộ nội dung bước); `start_run` nhận `script` (bỏ trống được khi nhóm
  chỉ có 1 kịch bản; nhóm nhiều kịch bản mà không nêu thì bị từ chối).
- Kiểm bằng `./.venv/bin/python app/tests/test_groups.py` (133 mục: lưu / chuẩn hoá kịch bản, kịch bản nhận đơn, máy nhiều nhóm, một máy một kịch bản, dừng máy / tiếp tục (cả lúc máy đang nghỉ), dừng đúng việc, dừng tất cả, máy đang giữ chờ kiểm tra). Bộ nút trên giao diện: `app/tests/test_ui_controls.py` (12 mục, chạy mã `app.js` bằng `node` trên mọi tổ hợp trạng thái).

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
  GIỮ NGUYÊN — AI/CLI không điều khiển, không chạy lại nhóm có máy đó, và **`stop_run` cũng bị từ chối**. Trạng thái này chỉ gỡ bằng nút **«Đã kiểm tra xong»**
  (lời xác nhận «đã đối soát xong» của người vận hành) hoặc «Chạy lại» của chính nhóm nhận đơn đó, trong app dạng cửa sổ. Bấm Dừng, Dừng nhóm, Dừng tất cả
  hay xoá nhóm đều KHÔNG gỡ; không nạp / xoá / đổi tên board, không gán lại hay xoá máy đó được khi đang giữ. «Dừng ngay» giữa một đơn — tính từ lúc tool bắt đầu
  gõ tài khoản của khách — cũng đưa máy vào trạng thái này, vì game có thể đã / còn đăng nhập tài khoản khách.
  **Giới hạn đã biết:** trạng thái giữ chỉ nằm trong bộ nhớ của app — tắt hoặc khởi động lại app là mất. Hãy đối soát và bấm «Đã kiểm tra xong» TRƯỚC khi tắt app.
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
| `app/history.py` | «máy nào đang chạy bước nào» + lịch sử theo MÁY (`app/data/history/may-<tên>.jsonl`) và theo ĐƠN (`don.jsonl`); xem ở trang **Theo dõi** |
| `app/iosapp.py` | tắt hẳn rồi mở mới một app qua USB (kênh công cụ nhà phát triển); chọn app theo tên hiển thị / tên gói / bundle id, bỏ qua app ẩn của hệ thống |
| `app/eyes.py` | chụp màn hình, tìm chữ / tìm hình, định vị con trỏ. Bộ đọc chữ của macOS (Vision) báo lỗi giữa chừng mà máy không cài tesseract → `read_text` / `find_text` BÁO LỖI, không lặng lẽ trả «màn hình trống» / «không thấy chữ» |
| `app/ocr.py` | đọc chữ bằng bộ có sẵn của macOS (Apple Vision, nạp bằng pyobjc-core, không cài thêm). Tesseract không đọc được chữ trên nền nhiều màu của game (màn hình tiêu đề eFootball: 0 dòng) còn Vision đọc được (~0,3–0,4s). `eyes.read_text` GHÉP hai bộ (riêng kiểu đọc một dòng `psm` — phép thử bàn phím — giữ tesseract); `find_text` / `ocr_lines` dùng Vision trước, không thấy thì hỏi tesseract. Vision không «sửa chính tả». Đặt `IPF_OCR=tesseract` để tắt Vision. |
| `app/web/ai.js` | trang «Kết nối AI» |

### Kiểm thử
```bash
./.venv/bin/python app/tests/test_mcp.py          # giao thức + lõi điều khiển + CLI (máy giả)
./.venv/bin/python app/tests/test_nav.py          # định vị con trỏ, bấm vòng kín, lệnh xuống board
./.venv/bin/python app/tests/test_api_mode.py     # chế độ nhận đơn (gateway tạm + iPhone giả)
./.venv/bin/python app/tests/test_presence.py     # tool tự báo gateway: máy rảnh ở kịch bản nào + danh mục kịch bản (gateway tạm nếu có php)
./.venv/bin/python app/tests/test_ocr.py          # bộ đọc chữ: Apple Vision (chữ trên nền màu của game) ghép với tesseract
./.venv/bin/python app/tests/test_history.py      # «máy nào đang chạy bước nào» + lịch sử theo máy / theo đơn; không lọt thông tin đăng nhập
./.venv/bin/python app/tests/test_ui_steps.py     # trình sửa kịch bản (chạy mã giao diện bằng node): câu của từng bước, ô «Lấy từ đơn», đổi cách chạy
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

### Chạy giao diện dạng WEB (dev) — để thao tác / chụp màn hình từ trình duyệt (kể cả trình duyệt nhúng của Orca)
```bash
./.venv/bin/python app/gui.py --web [--web-port 47822]     # thay cho `python app/gui.py` — KHÔNG chạy cùng lúc với app cửa sổ
```
Cùng một tiến trình, cùng cổng serial, cùng cầu nối MCP; chỉ khác là giao diện chạy trong trình duyệt thay vì cửa sổ pywebview. Địa chỉ + khoá in ra **stderr** một lần:
`http://127.0.0.1:47822/?t=<khoá>` (khoá lưu ở `app/data/webdev.json`, 0600, ngoài git). Mở địa chỉ đó một lần để nhận cookie, từ đó dùng `http://127.0.0.1:47822/`.
Với Orca: `orca goto --url "http://127.0.0.1:47822/?t=<khoá>"`, rồi `orca eval` / `orca screenshot`.
**Không chạy bản web cùng lúc với app cửa sổ**: hai tiến trình cùng giành cổng serial của board, và bản web không biết gì về máy đang làm đơn / đang giữ
ở tiến trình kia (các luật «không đụng máy của khách» chỉ có tác dụng trong cùng một tiến trình).
An toàn (giao diện điều khiển được iPhone thật, nạp / xoá board, chạy kịch bản — **trừ** chạy đơn của khách và đổi cấu hình gateway — nên **đừng** mở cổng
này ra mạng / đường hầm):
- chỉ nghe **127.0.0.1**; chặn Host lạ (DNS rebinding); POST phải cùng trang (Origin trùng, không phải yêu cầu chéo trang, `Content-Type: application/json`);
- **cookie là mã phiên ngẫu nhiên, không phải khoá** (HttpOnly, SameSite=Strict): đổi mỗi lần mở app, nên lộ cookie cũng không lộ khoá và hết hạn khi tắt app.
  Nút «Khởi động lại» trong app giữ nguyên phiên (trang không bị văng; mã phiên chỉ trao cho tiến trình mới, không nằm trong môi trường của tiến trình con);
  tắt hẳn rồi chạy lại thì mở lại địa chỉ có `?t=<khoá>`. Tệp khoá được tạo sẵn quyền 0600; tệp khoá cũ mà người khác đọc được thì bị thay khoá mới;
- chỉ gọi được hàm công khai của lớp `Api`; tệp tĩnh chỉ trong `app/web` (bỏ mọi tệp / thư mục bắt đầu bằng `_` hoặc `.`, và liên kết trỏ ra ngoài);
- yêu cầu bị từ chối thì đóng kết nối; không nhận `Transfer-Encoding` hay tiêu đề lặp (Host / Origin / Content-Length); kết nối im quá 30 giây bị đóng; trang không cho nhúng vào khung;
- **chế độ web KHÔNG chạy đơn của khách.** Nhóm nhận đơn từ gateway (chế độ API) bị từ chối ở bản web — cả từ giao diện, từ cầu nối AI, lẫn trong bộ chạy
  (`Runner.allow_api = False`) — vì trình duyệt có thể đang do AI điều khiển. Nhận đơn thật chỉ chạy ở app dạng cửa sổ (`python app/gui.py`, không `--web`).
  Nhờ vậy trong bản web không bao giờ có «máy đang làm đơn của khách» hay «máy đang dừng chờ đối soát»;
- phòng thủ thêm, phòng khi quy tắc trên bị nới sau này: nếu trong tiến trình có máy của khách thì (a) máy đó được nhận ra theo **máy thật** — iPhone + cổng board
  của phiên đang dùng, UDID so ở dạng chuẩn (bỏ dấu gạch, không phân biệt hoa-thường), kể cả qua một phiên đã mở sẵn dưới tên khác — và không chụp / không thử bước
  / không chạy kịch bản lên nó; (b) trang web chỉ gọi được một **danh sách lệnh an toàn** (`WEB_SAFE_WITH_CUSTOMERS` trong `app/gui.py`), mọi lệnh khác — kể cả
  lệnh thêm mới sau này — bị khoá; (c) không nhận lời xác nhận «Đã kiểm tra xong», không «Chạy lại» máy đang giữ. Đây là lớp chặn dự phòng, không phải bảo đảm
  tuyệt đối trước một trang web cố tình chuẩn bị bảng gán từ trước — bảo đảm chính là «bản web không chạy đơn».
- **cấu hình gateway không đổi được ở bản web** (khoá Tool là chìa vào đơn của khách). Ở app cửa sổ, đổi sang máy chủ khác thì phải nhập lại khoá —
  khoá đang lưu không tự gửi sang máy chủ mới;
- `pip install` từ trang Tổng quan chỉ nhận các gói app cần.
- Còn lại đã biết: cookie của `127.0.0.1` được trình duyệt gửi cho MỌI cổng trên máy này (trình duyệt không tách theo cổng) — đừng chạy dịch vụ lạ trên máy khi mở chế độ web;
  khoá nằm trong địa chỉ `?t=` lúc đăng nhập (lịch sử trình duyệt, `ps`); trang «Kết nối AI» vẫn hiện khoá MCP như cửa sổ thật.

Phần xử lý đẩy cập nhật về trang qua luồng SSE (`/events`); «Tải lại GD» là tải lại trang; «Khởi động lại» chạy lại tiến trình với đúng các cờ (giữ `--web`).
`--web-port` nhận 1024–65515. Kiểm thử: `app/tests/test_webdev.py` (102 mục).

### Board ESP32: sức khoẻ, tự reset, nút Khởi động lại / Huỷ kết nối BT, kiểm thử (firmware v3)
Firmware (`app/firmware/esp32_hid/esp32_hid.ino`, `FW_VERSION 3`) nay báo được và tự bảo vệ:
- `status` → `OK ble=… fw=3 up=<giây> heap=<RAM trống> tot=<TỔNG RAM heap> min=<đáy RAM> blk=<mảng liền lớn nhất> rst=<lý do reset lần trước> rxerr=… ovf=… drop=<số lần BLE rớt> cmds=… [bthold=<giây còn lại>]`;
  `info` → chip, lõi, xung nhịp, flash; `reset` → khởi động lại (chạy được cả khi chưa nối BLE);
  `disconnect [giây]` → **huỷ kết nối Bluetooth** với iPhone đang nối và NGỪNG quảng bá `giây` giây (mặc định 30; 0 = quảng bá lại ngay) — nếu không giữ thì
  iPhone đã ghép nối lại trong <1 s. Hết hạn giữ, iPhone tự nối lại. (Làm bằng cách ghi đè `onDisconnect`: tắt quảng bá ngay trong cùng callback với lúc thư viện bật lại.)
- Chống tràn: dòng lệnh đọc vào bộ đệm CỐ ĐỊNH 512 byte (dài hơn → `ERR line-too-long`, không ăn dần RAM như `String` nối cũ), bộ đệm nhận serial
  2048 byte (mặc định 256 → gửi dồn nhiều lệnh khi board đang bận thì rớt lệnh), watchdog (`loop()` kẹt quá ~5 s → tự reset, lý do báo là `panic` hoặc `task_wdt` tuỳ cấu hình core),
  RAM < 24 KB lúc rảnh → tự khởi động lại sớm.
- **Nhiệt độ đã BỎ**: ESP32 gốc (D0WD) luôn trả đúng 53,3 °C — không có cảm biến thật nên không hiển thị. Số đáng tin: RAM, lý do reset (`brownout` = nguồn USB yếu: đổi cáp / hub có nguồn), BLE rớt, lỗi serial.
- Nạp firmware mới: trang **Thiết bị → Nạp** (hoặc `esp.flash`). Firmware cũ vẫn chạy bình thường, chỉ không có số liệu sức khoẻ.

Ghi chú: «tổng RAM» là vùng **heap** của ESP32 (~256 KB khi đã bật BLE), không phải toàn bộ 520 KB SRAM của chip. `disconnect` giữ tối đa 600 s và **cần firmware v3**
(board chạy firmware cũ báo «nạp lại firmware»); lệnh dùng thư viện ESP32-BLE-Combo (bản nằm trong `.arduino-user`, không vào git) qua hook `onStarted`. Nút **Khởi động lại**
tự chuyển sang reset cứng (chân EN) nếu board đơ không nghe lệnh `reset`; cả hai nút dùng được cả với board CHƯA gán iPhone (tự mở cổng riêng, không đòi UDID).

Trong app / AI: thẻ board ở tab **ESP32** hiện **RAM đang dùng / tổng** (vd `129 / 256 KB (51%)`), thời gian chạy, lý do reset, cảnh báo, và hai nút **Khởi động lại** (lệnh `reset`, rồi chờ iPhone nối lại)
và **Huỷ kết nối BT** (giữ 30 s; chỉ hiện khi đang nối iPhone) — cả hai bị từ chối khi máy đang chạy / đang được điều khiển; nút «BLE?» ở trình dựng kịch bản hiện sức khoẻ; công cụ MCP/CLI `board_health` (`./farm health [máy]`, chỉ xem) và
`board_recover` (`./farm recover [máy]`: board im → reset cứng bằng chân EN qua RTS; thiếu RAM / phân mảnh → reset mềm; rồi chờ iPhone nối lại BLE — bị từ chối khi máy đang chạy).
Bộ chạy nhận đơn tự kiểm board **lúc rảnh** (đầu phiên, rồi mỗi 5 phút, và khi máy báo «chưa sẵn sàng»); **bộ chạy** không bao giờ chủ động reset giữa lúc đang xử lý đơn. (Firmware thì tự khởi động lại khi RAM < 24 KB và 30 s không nhận byte nào — có thể trúng lúc chờ OTP; reset chỉ làm rớt BLE vài giây, không gây thao tác nào lên iPhone.)

Kiểm thử ESP32 (ngoài iPhone):
```bash
./.venv/bin/python app/tests/test_firmware.py            # biên dịch thật firmware (arduino-cli, core esp32 2.0.17) + soi mã: đủ lệnh, giới hạn dòng, watchdog, reset
./.venv/bin/python app/tests/test_board.py               # đọc/đánh giá status, quyết định reset, chuỗi phục hồi — board giả, không cần phần cứng
./.venv/bin/python app/tests/smoke_board.py iPhoneFarm-03        # board THẬT (tắt app trước): độ trễ, giao thức, gửi dồn, rò RAM, reset mềm/cứng, BLE nối lại
```
Huỷ kết nối BT đo trên 2 board có iPhone: iPhone rớt sau ~0,1 s, KHÔNG nối lại trong lúc giữ (còn rớt sau 1,5 s), tự nối lại ~3,8 s sau lệnh `disconnect 3`.
Đo trên board thật (ESP32-D0WD-V3, firmware v3; RAM heap tổng ≈ 256 KB, đang dùng ≈ 129 KB): ping p50 ≈ 67 ms; 300 lệnh gửi dồn trong một lần ghi không rớt lệnh nào; 500 lệnh ping/status mất 0 byte RAM;
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
