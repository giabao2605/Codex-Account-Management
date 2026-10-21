# OTP Codex Local

Ứng dụng Windows chạy cục bộ để quản lý nhiều tài khoản Codex, hiển thị OTP,
quota và thống kê sử dụng. Dịch vụ chỉ lắng nghe tại `127.0.0.1:8765`; dữ liệu
tài khoản được mã hóa theo người dùng Windows hiện tại.

## Tính năng chính

- Hiển thị OTP theo thời gian chuẩn, tự cập nhật bộ đếm tại frontend.
- Theo dõi quota, token, streak và heatmap sử dụng 12 tháng.
- Lọc tài khoản theo gói và trạng thái trong một danh sách chung.
  Ưu tiên tài khoản dùng được và quota còn nhiều ở tất cả cửa sổ.
- Cô lập mỗi tài khoản trong một `CODEX_HOME` riêng.
- Xếp hàng tài khoản nên dùng và hiển thị failover dạng chỉ đọc; không tự chuyển tài khoản.
- Thêm, đổi email đã lưu, cập nhật mật khẩu, liên kết, ngắt liên kết và xóa tài khoản qua giao diện sáng/tối.
- Đổi email chỉ thay thông tin trong ứng dụng, không thay email đăng nhập OpenAI. ID, profile và lịch sử Codex được giữ nguyên; nếu danh tính Codex không khớp thì cần liên kết lại.
- Ngắt liên kết chỉ gỡ phiên đăng nhập Codex; giữ tài khoản, OTP, lịch sử và cấu hình để liên kết lại. Xóa tài khoản là thao tác riêng.

## Yêu cầu

- Windows 10 hoặc Windows 11.
- Python 3.11 trở lên.
- Git và Codex CLI trong `PATH`.

## Cài đặt và chạy

Mở PowerShell:

```powershell
git clone https://github.com/giabao2605/Codex-Account-Management.git
Set-Location .\Codex-Account-Management
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pyotp pywin32
.\.venv\Scripts\python.exe run_local_web.py
```

Ứng dụng tự mở tại `http://127.0.0.1:8765`. Nếu dịch vụ đang chạy từ bản cũ,
launcher sẽ yêu cầu tiến trình cũ thoát an toàn rồi khởi động lại.

## Thêm tài khoản

Nhập từng tài khoản theo định dạng:

```text
email|password|secret
```

Ứng dụng kiểm tra sau 300 ms ngừng nhập để tránh gửi request ở mỗi phím. Email
và secret phải hợp lệ, chưa được dùng bởi tài khoản khác.

## Đổi email đã lưu

Mở menu tùy chọn của tài khoản, chọn **Chỉnh sửa email**, nhập email mới và lưu.
Mật khẩu, secret 2FA, hạn Plus đã nhập, cấu hình và lịch sử được giữ nguyên.
Ứng dụng đóng phiên đồng bộ/đăng nhập do mình quản lý rồi kết nối lại khi cần;
các cửa sổ Codex khác có thể tiếp tục dùng thư mục profile cũ.
Nếu email Codex đang đăng nhập khác email mới, quota/gói của phiên đó sẽ được ẩn
và tài khoản báo sai danh tính; chọn **Đăng nhập lại** để đăng nhập đúng tài khoản.

Dữ liệu cũ tự nhận ID và tên profile ban đầu khi đọc, không đổi tên thư mục.
Lần lưu tiếp theo bổ sung `account_id` cố định và `profile_name` được mã hóa trong cùng
lần ghi file an toàn. Tài khoản mới dùng ID ngẫu nhiên và profile riêng, kể cả
khi thêm lại email cũ. Cả giao diện web và Tkinter của bản này giữ các trường đó.
Sau khi đã đổi email, không chạy phiên bản cũ chưa hỗ trợ các trường định danh:
phiên bản đó có thể làm mất ánh xạ khi lưu. Nếu cần quay về, giữ bản sao dữ liệu
trên cùng máy/người dùng Windows và dùng bản ứng dụng có hỗ trợ định danh cố định.

Kiểm tra trên Windows sau khi cập nhật nhánh:

```powershell
git switch feature/edit-account-email
git pull --ff-only origin feature/edit-account-email
python run_local_web.py
```

Dùng menu đổi email sang địa chỉ chưa có trong danh sách, mở lại ứng dụng và kiểm
tra email, OTP, mật khẩu, hạn Plus và lịch sử. Không cần build lại khi dùng
`web-dist/` đã commit. Nếu lưu báo lỗi, kiểm tra quyền ghi `accounts.json` và dung
lượng ổ đĩa; profile không bị chuyển hoặc xóa khi thao tác đổi email thất bại.

## Phát triển và kiểm thử

Frontend nằm trong `frontend/`, bản production đã build nằm trong `web-dist/`.
Cần Node.js 22 trở lên khi sửa frontend.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_frontend.ps1
python -B -m unittest
```

Tài liệu kiến trúc, baseline và acceptance gate nằm trong `docs/`.

## Dữ liệu và bảo mật

- Không commit hoặc chia sẻ `accounts.json`, `.web_session.json`, `auth.json` hay `codex_profiles/`.
- Không sao chép dữ liệu đã mã hóa sang tài khoản Windows hoặc máy khác.
- Chỉ yêu cầu loopback hợp lệ được chấp nhận; thao tác ghi dùng session token, CSRF và rate limit.
- Mật khẩu, secret và OTP chỉ xuất hiện khi người dùng chủ động yêu cầu trong giao diện.
