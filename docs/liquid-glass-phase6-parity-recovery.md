# Phase 6: Baseline parity recovery

Ngày thực hiện: 2026-07-24

## Phạm vi

Phase 6 giữ nguyên kiến trúc Vue 3, Pinia, Vite và hệ Liquid Glass hiện có, nhưng
khôi phục mật độ thông tin UI/UX từ giao diện cũ cho PC. Mobile không phải gate
theo quyết định hiện tại.

Không thay đổi schema API, database, cơ chế mã hóa credential hoặc rollback
legacy. `web/` tiếp tục là artifact rollback; frontend production mặc định vẫn
lấy từ `web-dist`.

## Parity đã khôi phục

- Accounts có lại dashboard tổng quan, bộ lọc trạng thái, card tài khoản giàu
  thông tin, badge gói, badge đề xuất sử dụng, OTP countdown, quota progress,
  sync detail và nhóm hành động chính/tùy chọn.
- Hành động tài khoản có trạng thái busy theo từng account/action, không khóa
  nhầm toàn bộ UI; lỗi backend được hiển thị bằng thông báo chung, không echo chi
  tiết nội bộ.
- Import có lại preview an toàn trước khi lưu: đếm thêm mới/cập nhật/trùng/lỗi,
  danh sách email đã sanitize, checkbox chặn lưu khi còn dòng lỗi và cảnh báo khi
  cho phép lưu partial.
- Usage có lại chế độ tất cả tài khoản và từng tài khoản, bảng quota 11 cột,
  KPI token, quota summary, trạng thái fresh/stale/unavailable và heatmap 12
  tháng với daily, weekly, cumulative mode.
- Heatmap dùng button grid có nhãn aria, roving focus, tooltip, dữ liệu rỗng
  tách biệt với dữ liệu không khả dụng.
- CSS PC mở rộng shell lên 1440 px, ưu tiên content card nền solid để đọc dữ
  liệu tốt hơn; glass tập trung vào shell, dialog và control.

## Security invariants

- Password và secret không được đưa vào preview, state, toast hoặc baseline ảnh.
- Sensitive copy vẫn đi qua reveal endpoint chỉ khi người dùng bấm copy.
- Import preview token chỉ dùng một lần; sau lỗi apply phải preview lại.
- Token usage request được dedupe, kể cả khi người dùng bấm làm mới trong lúc
  request đang chạy.
- API mutation vẫn cần Bearer token và CSRF như Phase 5; rollback legacy không
  bypass các rule này.

## Visual baseline

Baseline Phase 6 nằm ở `docs/baselines/liquid-glass-phase-6/`:

- Accounts: dark/light với effects full, reduced và off.
- Usage: dark/light với effects full.
- Import dialog: dark/light với effects full.

Các ảnh này được sinh từ fixture đã khử nhạy cảm trong
`tests/visual_baseline_app.py` và không thay thế baseline lịch sử của Phase 1
hoặc Phase 4.

## Acceptance evidence

Gate cuối ngày 24/07/2026:

- Vue typecheck: pass.
- ESLint: pass.
- Vue unit coverage: 64 test pass, 86.16% statements, 81.26% branches, 87.09%
  functions và 87.20% lines.
- Chrome E2E PC: 9/9 pass, gồm parity recovery, production shell,
  visual acceptance và performance.
- Phase 6 PC performance median ở lần gate cuối: FCP 1.068 ms, TTFB 63,3 ms,
  189.261 byte, 12 request, long task 54 ms. Long task vượt ideal target 50 ms
  một chút nhưng vẫn
  dưới hard budget 100 ms.
- Python unit/integration: 111/111 pass.
- Production build: `scripts/build_frontend.ps1` pass, tạo hashed assets trong
  `web-dist` và không ship source map.
- Dependency/security: `npm audit --omit=dev` không có vulnerability;
  `pip check` không có broken requirements; secret pattern scan không có kết
  quả.
- PowerShell parser và `git diff --check`: pass.
- Live canary: health schema 5 và Vue fingerprint `1d81579ea6abf62b` khớp
  production build hiện hành tại `http://127.0.0.1:8765`.
- Rollback live sang legacy fingerprint `33ff56d2bcaaf661` thành công, sau đó
  launcher chuyển lại Vue. Contract test cũng xác nhận legacy phục vụ `web/`
  không cần Vue assets.

## Caveat không chặn

- `npm ci` vẫn cảnh báo deprecation cho dependency bắc cầu `glob@10.5.0`; audit
  hiện không có advisory.
- FastAPI TestClient vẫn phát `StarletteDeprecationWarning` về lộ trình
  `httpx2`; đây là cảnh báo dependency test, không phải lỗi runtime Phase 6.

## Visual polish follow-up

Đợt chỉnh sau acceptance tập trung đúng các sai lệch được phát hiện trên PC:

- Bỏ hoàn toàn surface, viền và shadow bọc ngoài ba nút Email, Mật khẩu và Tùy
  chọn; từng nút vẫn giữ hit area và focus ring độc lập.
- Cân lại palette light/dark theo semantic surface, success, warning và danger
  để giảm chói nhưng vẫn phân biệt rõ card, quota và trạng thái.
- Đồng bộ chuyển động hover, press, release và đổi theme bằng easing thống nhất;
  `prefers-reduced-motion` và effects preference vẫn được tôn trọng.
- Heatmap daily dùng ô vuông và trải kín card, nhãn tháng đặt dưới grid. Weekly
  và cumulative giữ 52/53 cột dữ liệu nhưng mỗi cột hiển thị đủ 7 ô, không còn
  co thành một hàng mỏng.

Theo phạm vi kiểm thử rút gọn đã thống nhất, follow-up được xác nhận bằng 13
component test liên quan, typecheck, ESLint, production build, một Chrome E2E
kiểm tra hình học cả ba heatmap mode và live canary schema 5. Không chạy lại
toàn bộ Python/backend suite vì follow-up không đổi API hoặc backend.
