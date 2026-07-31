# OTP Codex Local

Ứng dụng quản lý nhiều tài khoản Codex trên máy Windows, cung cấp mã OTP, trạng thái tài khoản, quota và khả năng đồng bộ từng hồ sơ Codex độc lập.

Ứng dụng chỉ phục vụ trên địa chỉ loopback `127.0.0.1:8765`. Dữ liệu tài khoản được bảo vệ bằng cơ chế mã hóa của Windows và không được gửi ra ngoài bởi giao diện quản lý.

## Tính năng chính

- Hiển thị và sao chép OTP theo thời gian thực.
- Theo dõi quota, chu kỳ và thời điểm reset.
- Thống kê lifetime token, peak token, tác vụ dài nhất và streak theo từng tài khoản.
- Heatmap token 12 tháng với chế độ Daily, Weekly và Cumulative; di chuột để xem số token chính xác ngay tại ô.
- Gộp token và quota vào cùng màn hình; hỗ trợ xem một tài khoản hoặc so sánh toàn bộ tài khoản.
- Đồng bộ trạng thái tài khoản Codex mỗi 1 phút.
- Cô lập mỗi tài khoản trong một `CODEX_HOME` riêng.
- Lọc tài khoản theo trạng thái và quota.
- Đề xuất tài khoản phù hợp nhất dựa trên trạng thái, quota và thời điểm reset; ứng dụng không tự chuyển tài khoản.
- Sao chép email, mật khẩu hoặc secret theo thao tác chủ động.
- Thêm từng tài khoản với kiểm tra trùng email và secret ngay khi nhập.
- Liên kết lại tài khoản Codex khi phiên đăng nhập hết hiệu lực.
- Ngắt liên kết Codex và xóa vĩnh viễn profile local khi cần.
- Thoát ứng dụng an toàn ngay trên giao diện.
- Chuyển đổi giữa giao diện sáng và tối, tự ghi nhớ lựa chọn trên trình duyệt.

## Cấu trúc thư mục

```text
otp_codex/
├── app/                 Mã nguồn Python của ứng dụng
├── tests/               Bộ kiểm thử
├── scripts/             Công cụ cài đặt shortcut
├── docs/                Baseline, parity matrix và tài liệu kỹ thuật
├── frontend/            Source Vue/Vite production
├── web-dist/            Production build với hashed assets
├── codex_profiles/      Hồ sơ Codex cục bộ, không đưa lên Git
├── accounts.json        Dữ liệu tài khoản được mã hóa
├── .web_session.json    Phiên truy cập cục bộ được mã hóa
└── run_local_web.py     Launcher chính
```

Baseline và parity matrix dùng cho quá trình nâng cấp Liquid Glass nằm tại
[`docs/liquid-glass-phase1-baseline-parity.md`](docs/liquid-glass-phase1-baseline-parity.md).
Kiến trúc, lệnh chạy và gate ban đầu của Vue/Vite nằm tại
[`docs/liquid-glass-phase2-candidate-shell.md`](docs/liquid-glass-phase2-candidate-shell.md).
Functional parity trước cutover được ghi tại
[`docs/liquid-glass-phase3-functional-parity.md`](docs/liquid-glass-phase3-functional-parity.md).
Kiến trúc Liquid Glass, fallback và performance gate nằm tại
[`docs/liquid-glass-phase4-glass-system.md`](docs/liquid-glass-phase4-glass-system.md).
Quyết định production cutover nằm tại
[`docs/liquid-glass-phase5-production-cutover.md`](docs/liquid-glass-phase5-production-cutover.md).
Kết quả khôi phục parity, baseline PC và acceptance gate hiện hành nằm tại
[`docs/liquid-glass-phase6-parity-recovery.md`](docs/liquid-glass-phase6-parity-recovery.md).

## Yêu cầu

- Windows 10 hoặc Windows 11.
- Python 3.11 trở lên.
- Git.
- Codex CLI trong `PATH` để sử dụng liên kết tài khoản, quota và thống kê token.

## Cài đặt và chạy

Mở PowerShell và chạy:

```powershell
git clone https://github.com/giabao2605/Codex-Account-Management.git
Set-Location .\Codex-Account-Management
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn pyotp pywin32
.\.venv\Scripts\python.exe run_local_web.py
```

Ứng dụng sẽ mở trình duyệt tại `http://127.0.0.1:8765` sau khi dịch vụ sẵn sàng. Nếu ứng dụng đã chạy, launcher sẽ mở lại trang đang hoạt động thay vì tạo thêm dịch vụ trên cùng cổng.

Launcher phục vụ Vue Liquid Glass từ `web-dist/`. Không cần chạy
Vite dev server hoặc mở thêm cổng khi sử dụng hằng ngày.

Lần đầu sử dụng, thêm tài khoản của chính bạn trong giao diện. Không sao chép
`accounts.json`, `.web_session.json` hoặc `codex_profiles/` từ máy khác:
những dữ liệu này chứa thông tin riêng tư và được bảo vệ theo tài khoản Windows
đã tạo ra chúng.

## Build lại frontend production

Chỉ cần Node.js 22 trở lên nếu muốn sửa và build lại frontend. Sau khi thay đổi
source trong `frontend/`, chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_frontend.ps1
```

Script cài đúng dependency theo `package-lock.json`, typecheck, build vào
`web-dist/`, từ chối source map production và dừng ngay nếu bundle không đầy đủ.

## Chuyển giao diện

Sử dụng nút ở góc trên bên phải trang để chuyển giữa giao diện sáng và tối. Ứng dụng ghi nhớ lựa chọn cho những lần mở sau; nếu chưa từng chọn, giao diện sẽ sử dụng thiết lập sáng hoặc tối của hệ điều hành.

## Thêm tài khoản

Nhập một tài khoản theo định dạng `email|password|secret`. Ứng dụng tự kiểm tra email và secret ngay trong lúc nhập; nút thêm chỉ được bật khi dữ liệu hợp lệ và chưa tồn tại.

Mỗi lần chỉ thêm một tài khoản mới. Email đã tồn tại không được dùng để cập nhật mật khẩu hoặc secret của tài khoản cũ. Backend kiểm tra lại xung đột ngay trước khi ghi để tránh hai yêu cầu đồng thời tạo dữ liệu trùng.

## Quản lý hồ sơ Codex

`Ngắt liên kết` yêu cầu xác nhận, xóa vĩnh viễn profile Codex local nhưng vẫn giữ tài khoản trong danh sách. Lần sau cần liên kết Codex lại.

## Đồng bộ giờ OTP

Ứng dụng không phụ thuộc vào giờ Windows để sinh OTP. Khi khởi động và định kỳ mỗi 1 phút, backend đọc giờ từ ba nguồn HTTPS, loại mẫu chậm hoặc bất thường, lấy trung vị rồi neo kết quả vào đồng hồ monotonic. Mã OTP và bộ đếm 30 giây luôn dùng cùng mốc này, nên việc máy công ty chỉnh giờ nhanh hoặc chậm không làm mã bị lệch.

Nếu mạng tạm thời lỗi, ứng dụng tiếp tục dùng mốc chuẩn gần nhất và hiển thị trạng thái suy giảm. Nếu chưa từng lấy được giờ chuẩn kể từ lúc mở ứng dụng, mã OTP sẽ tạm khóa thay vì dùng giờ Windows có thể sai. Có thể thay danh sách nguồn bằng biến môi trường `OTP_TIME_SOURCES`, gồm các URL HTTPS phân tách bằng dấu phẩy.

## Thống kê sử dụng

Tab `Thống kê sử dụng` gộp token và quota vào cùng một màn hình. Dữ liệu token được đọc độc lập cho từng `CODEX_HOME` qua Codex app-server, không đọc nội dung `auth.json`. Khi chọn một tài khoản, giao diện hiển thị lifetime token, peak token theo ngày, tác vụ dài nhất, streak hiện tại, streak dài nhất, quota còn lại, chu kỳ và thời điểm reset. Khi chọn `Tất cả tài khoản`, giao diện hiển thị heatmap tổng hợp, độ phủ dữ liệu và bảng so sánh token/quota giữa các tài khoản.

Heatmap bao phủ 12 tháng và có ba chế độ: `Daily` hiển thị token từng ngày, `Weekly` cộng token theo tuần bắt đầu từ thứ Hai, còn `Cumulative` hiển thị tổng lũy kế qua từng tuần. Màu xanh đậm dần theo mức token; tooltip dùng số token nguyên gốc. `dailyUsageBuckets: []` là dữ liệu hợp lệ nhưng chưa có hoạt động, còn `dailyUsageBuckets: null` nghĩa là heatmap chưa khả dụng và không được xem như 0.

Token được cache trong bộ nhớ 5 phút. Khi nguồn tạm lỗi, ứng dụng giữ bản gần nhất với nhãn `Dữ liệu cũ`; nút đồng bộ thủ công buộc làm mới token. Bucket token theo ngày có thể được phía Codex cập nhật trễ so với hoạt động thực tế. Các summary field không có dữ liệu, chẳng hạn tác vụ dài nhất, được hiển thị là `—` thay vì suy diễn thành 0.

Phần quota trên cùng màn hình hiển thị snapshot mới nhất theo từng tài khoản: phần trăm còn lại, gói, chu kỳ, thời điểm reset, trạng thái và lần đồng bộ gần nhất. Token là số hoạt động thực tế còn quota là phần trăm cửa sổ giới hạn của OpenAI; ứng dụng không quy đổi hai loại dữ liệu này.

Phần tổng hợp gồm số tài khoản có hoặc chưa có dữ liệu quota, tài khoản cần đồng bộ lại, dùng được, cần xử lý, quota thấp, hết quota, bình quân, min–max, trung vị, reset gần nhất và phân bổ theo gói. Quota cũ của tài khoản đang cần xử lý không được tính vào tổng hợp. Các giá trị bình quân chỉ tính trên những tài khoản có dữ liệu hiện hành và không phải tổng dung lượng quota tuyệt đối giữa các gói.

Nguồn account usage hiện chỉ cung cấp tổng token, nên giao diện không tách input/output token và không suy diễn số request. Ứng dụng không tạo cơ sở dữ liệu lịch sử riêng; khi khởi động lại, dữ liệu ngày được lấy lại từ Codex app-server.

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
- Không commit `auth.json`, `.env`, khóa riêng, log, cache, coverage hoặc `node_modules/`.
- Không đọc, in hoặc chia sẻ file `auth.json` bên trong hồ sơ Codex.
- Chỉ các yêu cầu từ loopback hợp lệ mới được dịch vụ chấp nhận.
- Các thao tác thay đổi dữ liệu được bảo vệ bằng session token và CSRF token.
- Mật khẩu và secret chỉ được trả về khi người dùng chủ động yêu cầu sao chép.
- Kết quả kiểm tra tài khoản không trả lại mật khẩu hoặc secret.
- Thao tác ngắt liên kết chỉ được xóa profile trực tiếp trong `codex_profiles/` sau khi kiểm tra đường dẫn an toàn.

## Dừng ứng dụng

Chọn `Thoát ứng dụng` trên giao diện và xác nhận. Dịch vụ sẽ dừng đồng bộ, đóng phiên cục bộ và kết thúc tiến trình do launcher quản lý.

Nếu giao diện không còn phản hồi, chỉ đóng tiến trình `pythonw.exe` có command line trỏ tới `run_local_web.py`. Không dừng toàn bộ tiến trình Python trên máy vì có thể ảnh hưởng ứng dụng khác.
