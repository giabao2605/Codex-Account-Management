# OTP Codex Local

Ứng dụng Windows chạy cục bộ để quản lý nhiều tài khoản Codex, hiển thị OTP,
quota và thống kê sử dụng. Dịch vụ chỉ lắng nghe tại `127.0.0.1:8765`; dữ liệu
tài khoản được mã hóa theo người dùng Windows hiện tại.

## Tính năng chính

- Hiển thị OTP theo thời gian chuẩn, tự cập nhật bộ đếm tại frontend.
- Theo dõi quota, token, streak và heatmap sử dụng 12 tháng.
- Cô lập mỗi tài khoản trong một `CODEX_HOME` riêng.
- Xếp hàng tài khoản nên dùng và hiển thị failover dạng chỉ đọc; không tự chuyển tài khoản.
- Thêm, cập nhật mật khẩu, liên kết, ngắt liên kết và xóa tài khoản qua giao diện sáng/tối.

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
