iPhone Farm — cài trên macOS @MINOS@ trở lên (máy Apple Silicon: M1 trở lên)

1. Kéo «iPhone Farm» vào thư mục «Applications».

2. Mở lần đầu: app chưa có chữ ký của Apple nên macOS sẽ chặn.
   Cách A: mở Terminal, chạy một lần:
       xattr -dr com.apple.quarantine "/Applications/iPhone Farm.app"
   rồi bấm đúp app như bình thường.
   Cách B: bấm đúp app → bấm «Done / Xong» ở hộp cảnh báo → System Settings → Privacy & Security
   → kéo xuống bấm «Open Anyway» cạnh dòng iPhone Farm.

3. Lần mở đầu app tự cài phần còn lại (1–3 phút, không cần mạng), xong cửa sổ app tự hiện.

Dữ liệu của bạn (nhóm, kịch bản, ví, cài đặt) nằm ở:  ~/Library/iPhoneFarm/app/data
Cài bản mới: kéo bản mới đè lên bản cũ — dữ liệu được giữ nguyên.
Lệnh điều khiển:  ~/Library/iPhoneFarm/farm --help
Gỡ hẳn: xoá app trong Applications và thư mục ~/Library/iPhoneFarm (mất cả dữ liệu).
Cài lỗi: xem tệp ~/Library/iPhoneFarm/install.log
