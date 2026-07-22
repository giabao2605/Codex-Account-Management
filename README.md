# OTP Codex Local

Ứng dụng quản lý nhiều tài khoản Codex trên máy Windows, cung cấp mã OTP, trạng thái tài khoản, quota và khả năng đồng bộ từng hồ sơ Codex độc lập.

Ứng dụng chỉ phục vụ trên địa chỉ loopback `127.0.0.1:8765`. Dữ liệu tài khoản được bảo vệ bằng cơ chế mã hóa của Windows và không được gửi ra ngoài bởi giao diện quản lý.

## Tính năng chính

- Hiển thị và sao chép OTP theo thời gian thực.
- Theo dõi quota, chu kỳ và thời điểm reset.
- Tab thống kê quota hiện tại theo từng tài khoản và tổng hợp toàn hệ thống.
- Đồng bộ trạng thái tài khoản Codex mỗi 1 phút.
- Cô lập mỗi tài khoản trong một `CODEX_HOME` riêng.
- Lọc tài khoản theo trạng thái và quota.
- Đề xuất tài khoản phù hợp nhất dựa trên trạng thái, quota và thời điểm reset; ứng dụng không tự chuyển tài khoản.
- Sao chép email, mật khẩu hoặc secret theo thao tác chủ động.
- Xem trước kết quả import, chọn lưu toàn bộ hoặc chỉ các dòng hợp lệ.
- Liên kết lại tài khoản Codex khi phiên đăng nhập hết hiệu lực.
- Ngắt liên kết, tạo lại hồ sơ sạch và lưu trữ hồ sơ không còn gắn với tài khoản.
- Thoát ứng dụng an toàn ngay trên giao diện.
- Chuyển đổi giữa giao diện sáng và tối, tự ghi nhớ lựa chọn trên trình duyệt.

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

## Chuyển giao diện

Sử dụng nút ở góc trên bên phải trang để chuyển giữa giao diện sáng và tối. Ứng dụng ghi nhớ lựa chọn cho những lần mở sau; nếu chưa từng chọn, giao diện sẽ sử dụng thiết lập sáng hoặc tối của hệ điều hành.

## Import tài khoản

Dán danh sách tài khoản rồi chọn xem trước. Ứng dụng chỉ hiển thị email, hành động dự kiến và lỗi; mật khẩu và secret không xuất hiện trong kết quả xem trước.

Mặc định, nếu có bất kỳ dòng lỗi nào thì ứng dụng không lưu dữ liệu. Bạn có thể bỏ lựa chọn này để chỉ lưu các dòng hợp lệ. Kết quả xem trước chỉ dùng được một lần và sẽ bị từ chối nếu dữ liệu tài khoản đã thay đổi trước khi áp dụng.

## Quản lý hồ sơ Codex

Các thao tác ngắt liên kết và tạo lại hồ sơ đều yêu cầu xác nhận. Hồ sơ cũ được chuyển vào `codex_profiles/.archived/` thay vì xóa vĩnh viễn, nên có thể khôi phục thủ công khi cần.

- `Ngắt liên kết` lưu trữ profile đăng nhập hiện tại nhưng giữ tài khoản trong danh sách. Lần sau cần liên kết Codex lại.
- `Đặt lại profile` lưu trữ toàn bộ profile hiện tại rồi tạo một profile trống, dùng khi profile bị lỗi hoặc cần đăng nhập lại từ đầu.

## Thống kê sử dụng

Tab `Thống kê sử dụng` hiển thị snapshot quota mới nhất theo từng tài khoản: phần trăm đã dùng và còn lại, gói, chu kỳ, thời điểm reset, trạng thái và lần đồng bộ gần nhất.

Phần tổng hợp gồm số tài khoản có hoặc chưa có dữ liệu quota, tài khoản cần đồng bộ lại, dùng được, cần xử lý, quota thấp, hết quota, bình quân, min–max, trung vị, reset gần nhất và phân bổ theo gói. Quota cũ của tài khoản đang cần xử lý không được tính vào tổng hợp. Các giá trị bình quân chỉ tính trên những tài khoản có dữ liệu hiện hành và không phải tổng dung lượng quota tuyệt đối giữa các gói.

Ứng dụng hiện không có dữ liệu token, request hoặc lịch sử theo ngày, vì vậy tab không hiển thị biểu đồ xu hướng hay dự báo tiêu thụ chưa có căn cứ.

## Sau khi cập nhật mã nguồn

Launcher kiểm tra fingerprint của backend và frontend đang chạy. Nếu phát hiện tiến trình cũ, launcher sẽ yêu cầu tiến trình đó thoát an toàn rồi khởi động bản mới trước khi mở trình duyệt. Với phiên bản cũ chưa hỗ trợ cơ chế này, hãy đóng `OTP Codex Local` một lần rồi mở lại.

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
- Kết quả xem trước import không chứa mật khẩu hoặc secret.
- Thao tác vòng đời hồ sơ chỉ lưu trữ hồ sơ trong phạm vi `codex_profiles/`, không xóa vĩnh viễn.

## Dừng ứng dụng

Chọn `Thoát ứng dụng` trên giao diện và xác nhận. Dịch vụ sẽ dừng đồng bộ, đóng phiên cục bộ và kết thúc tiến trình do launcher quản lý.

Nếu giao diện không còn phản hồi, chỉ đóng tiến trình `pythonw.exe` có command line trỏ tới `run_local_web.py`. Không dừng toàn bộ tiến trình Python trên máy vì có thể ảnh hưởng ứng dụng khác.
