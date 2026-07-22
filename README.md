# OTP Codex Local

Ứng dụng quản lý nhiều tài khoản Codex trên máy Windows, cung cấp mã OTP, trạng thái tài khoản, quota và khả năng đồng bộ từng hồ sơ Codex độc lập.

Ứng dụng chỉ phục vụ trên địa chỉ loopback `127.0.0.1:8765`. Dữ liệu tài khoản được bảo vệ bằng cơ chế mã hóa của Windows và không được gửi ra ngoài bởi giao diện quản lý.

## Tính năng chính

- Hiển thị và sao chép OTP theo thời gian thực.
- Theo dõi quota, chu kỳ và thời điểm reset.
- Đồng bộ trạng thái tài khoản Codex mỗi 1 phút.
- Cô lập mỗi tài khoản trong một `CODEX_HOME` riêng.
- Lọc tài khoản theo trạng thái và quota.
- Sao chép email, mật khẩu hoặc secret theo thao tác chủ động.
- Liên kết lại tài khoản Codex khi phiên đăng nhập hết hiệu lực.

## Cấu trúc thư mục

```text
otp_codex/
├── app/                 Mã nguồn Python của ứng dụng
├── tests/               Bộ kiểm thử
├── scripts/             Công cụ cài đặt shortcut
├── web/                 HTML, CSS và JavaScript
├── codex_profiles/      Hồ sơ Codex cục bộ, không đưa lên Git
├── accounts.json        Dữ liệu tài khoản được mã hóa
├── .web_session.json    Phiên truy cập cục bộ được mã hóa
└── run_local_web.py     Launcher chính
```

## Yêu cầu

- Windows 10 hoặc Windows 11.
- Python 3.11 trở lên.
- Các thư viện Python của dự án, bao gồm FastAPI, Uvicorn, PyOTP và pywin32.

## Chạy ứng dụng

Tại thư mục dự án:

```powershell
python run_local_web.py
```

Ứng dụng sẽ mở trình duyệt tại `http://127.0.0.1:8765` sau khi dịch vụ sẵn sàng. Nếu ứng dụng đã chạy, launcher sẽ mở lại trang đang hoạt động thay vì tạo thêm dịch vụ trên cùng cổng.

## Tạo shortcut

Chạy PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_web_shortcut.ps1
```

Script tạo shortcut `OTP Codex Local` trên Desktop và trong Start Menu.

## Chạy kiểm thử

```powershell
python -B -m unittest
```

Tùy chọn `-B` ngăn Python tạo thư mục `__pycache__` trong lúc kiểm thử.

## Dữ liệu và bảo mật

- Không commit `accounts.json`, `.web_session.json` hoặc `codex_profiles/`.
- Không đọc, in hoặc chia sẻ file `auth.json` bên trong hồ sơ Codex.
- Chỉ các yêu cầu từ loopback hợp lệ mới được dịch vụ chấp nhận.
- Các thao tác thay đổi dữ liệu được bảo vệ bằng session token và CSRF token.
- Mật khẩu và secret chỉ được trả về khi người dùng chủ động yêu cầu sao chép.

## Dừng ứng dụng

Đóng tiến trình `pythonw.exe` có command line trỏ tới `run_local_web.py`. Không dừng toàn bộ tiến trình Python trên máy vì có thể ảnh hưởng ứng dụng khác.
