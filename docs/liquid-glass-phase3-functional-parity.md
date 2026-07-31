# Phase 3: Functional parity trên Vue candidate

Ngày xác nhận: 2026-07-23

## Phạm vi đã hoàn tất

Frontend candidate trong `frontend/` đã nối đầy đủ với API schema 5 nhưng chưa
thay thế `web/` production:

- bootstrap bằng access token trong URL fragment, xóa fragment ngay sau khi đọc,
  giữ access token trong `sessionStorage` và CSRF token chỉ trong bộ nhớ;
- polling `/api/state` mỗi 1 giây, không chồng request, giữ trạng thái offline và
  fail-closed khi sai schema;
- lọc, đề xuất, copy email/OTP, copy password/secret theo hành động chủ động;
- refresh toàn bộ hoặc từng tài khoản, login, unlink và xóa tài khoản;
- import theo quy trình preview token rồi apply; nội dung thay đổi làm vô hiệu
  preview đang có;
- token usage schema 2, cache 5 phút, force refresh, trạng thái fresh/stale/
  unavailable, daily/weekly/cumulative và phân biệt `null` với `[]`;
- shutdown chấp nhận cả response thành công và trường hợp kết nối đóng ngay sau
  khi backend nhận lệnh.

## Ranh giới an toàn

- Không render HTML từ backend và không đưa secret vào Pinia hoặc DOM lâu dài.
- Các mutation đi qua CSRF header của typed API client.
- Thao tác phá hủy yêu cầu xác nhận.
- Candidate vẫn build vào `web-dist/`; `web/` và launcher production chưa cutover.

## Gate

- Python: 105 test pass và 12 subtest pass.
- Vue unit: 30 test pass.
- Coverage logic: statements 90.85%, branches 81.81%, functions 89.24%, lines
  90.64%. Component presentation được kiểm tra bằng Playwright thay vì tính vào
  coverage logic.
- Chrome E2E: bootstrap, fragment cleanup, polling, filter, nullable OTP, tabs,
  token heatmap, persistence theme/effects và console/network gate đều pass.
