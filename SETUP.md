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
