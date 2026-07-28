# Phase 4: Liquid Glass system

Ngày xác nhận cuối: 2026-07-24

## Kiến trúc

Hiệu ứng được triển khai thành primitive dùng lại, không gắn trực tiếp vào từng
feature:

- `GlassSurface`: material boundary semantic với ba mức prominent/lite/solid.
- `GlassButton`: native button semantics, pointer highlight, hover/press bằng
  `animateMini` của Motion for Vue và biến thể prominent/lite/danger.
- `GlassGroup`: nhóm control có label dùng lại cho account actions.
- `GlassSegmentedControl`: single-selection hoặc tabs, roving focus,
  ArrowLeft/ArrowRight/Home/End và ARIA state.
- `GlassPopover`: controlled state, outside click, Escape và trả focus về trigger.
- `GlassDialog`: modal semantics, focus trap, Escape, backdrop close và trả focus.
- `AppearancePopover`: Theme System/Light/Dark và Effects Auto/Full/Reduced/Off.
- `GlassOverlay`: duy nhất một `OffscreenCanvas`; WebGL2 shader chạy trong worker,
  `pointer-events: none`, DPR tối đa 2 và dừng requestAnimationFrame sau 480 ms
  không có input.

CSS chịu trách nhiệm cho vật liệu chính: translucent fill, edge highlight,
backdrop blur, saturation và shadow. WebGL/canvas chỉ là lớp tăng cường, nên UI
vẫn đúng khi GPU hoặc backdrop-filter không khả dụng.

## Mức áp dụng

- Full: top navigation, appearance popover, dialog và hành động nổi bật.
- Lite: action lặp lại trên từng account card để tránh quá nhiều blur layer.
- Content cards, bảng và heatmap giữ surface đặc nhằm bảo toàn độ đọc và chi phí
  render.

## Accessibility và fallback

- `prefers-reduced-motion` loại bỏ motion không thiết yếu.
- `prefers-reduced-transparency` và forced-colors chuyển về surface đặc.
- Effects Off tắt overlay, blur và shadow; Reduced giữ vật liệu CSS nhẹ.
- Radio, tab, dialog, fieldset, disabled OTP và live status đều dùng native
  semantics. Axe không phát hiện violation mức critical hoặc serious trong Chrome
  E2E.

## Visual acceptance PC

Theo quyết định cập nhật ngày 24/07/2026, mobile không nằm trong Phase 4
acceptance. Ma trận PC tại `docs/baselines/liquid-glass-phase-4/` gồm:

- Accounts: Light/Dark × Full/Reduced/Off.
- Usage: Dark × Full.
- Import dialog: Light × Full.

Các ảnh dùng fixture `example.test`, viewport 1440×1000 và đã được kiểm tra trực
quan. Visual review đã bắt được scissor rectangle của WebGL cũ; renderer hiện
dùng radial fragment shader và không còn artifact đó.

## Performance gate

Build production ngày 2026-07-24:

| Artifact | Raw | Gzip | Budget |
| --- | ---: | ---: | ---: |
| JavaScript khởi động Accounts | 113.48 KB | 44.67 KB | dưới 180 KB gzip |
| JavaScript Usage, tải khi mở tab | 3.31 KB | 1.71 KB | lazy |
| WebGL worker, lazy | 2.45 KB | không tải lúc bootstrap | progressive |
| CSS | 8.16 KB | 2.60 KB | dưới 35 KB gzip |

PC benchmark lấy median ba lần ở gate cutover cuối: FCP 736 ms, TTFB 37 ms,
158,735 byte truyền, 12 request và không ghi nhận long task. Canvas có DPR cap
2, không nhận pointer event và animation loop tự dừng trước 500 ms. Không có
idle animation.

## Trạng thái rollout

Phase 4 hoàn tất trên candidate cho phạm vi PC. Trạng thái “chưa cutover” tại
thời điểm đóng Phase 4 đã được Phase 5 thay thế; quyết định production hiện hành
được ghi trong `liquid-glass-phase5-production-cutover.md`.
