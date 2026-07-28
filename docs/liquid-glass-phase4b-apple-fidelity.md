# Liquid Glass v3 — Apple fidelity

## Mục tiêu

Liquid Glass v3 dùng material theo từng control, không dùng overlay toàn màn
hình. Glass chỉ là functional layer dành cho command bar, button, segmented
control, popover và dialog; account card, heatmap, bảng và form vẫn là standard
material. Phạm vi nghiệm thu là Chrome PC ở viewport `1440x1000`.

## Acceptance contract

- Trang chỉ có một SVG registry `data-liquid-glass-defs="v3"`. Filter động dùng
  normal map SDF theo geometry thật, quantize kích thước 4px/radius 2px và cache
  LRU 64 entry. Không có `.glass-overlay`, worker hoặc animation loop nền.
- Mỗi glass group là đúng một material boundary v3, không chứa thêm glass
  boundary bên trong. Primitive công khai material, context, depth, renderer và
  effective mode bằng các thuộc tính `data-glass-*`.
- Runtime tách độc lập quality, motion, transparency, contrast, input và
  renderer. Reduced motion chỉ bỏ chuyển động hình học; reduced transparency bỏ
  displacement; forced colors dùng system colors.
- Command layer sticky dùng scroll-edge mask 64px. Workspace tabs dùng shared
  active lens; popover/dialog dùng cùng morph identity với trigger.
- Appearance, account options và import dialog quản lý focus đầy đủ: focus đi
  vào surface khi mở, Escape đóng, rồi trả focus về trigger.
- WebGPU chỉ bổ sung specular/caustic/light-spill cho active segmented lens và
  active morph; SVG/Canvas cục bộ là fallback và không chạy khi idle.
- Accounts và Usage giữ nguyên lọc, action, import preview, heatmap keyboard,
  quota/table và single-account flow. Content surfaces không bị đổi thành glass.

## Visual acceptance

Baseline mới nằm tại `docs/baselines/liquid-glass-v3`:

- Accounts: Light/Dark Full; Dark Reduced/Off.
- Usage: Light/Dark Full.
- Appearance popover, account options popover và import dialog.
- Rest, hover và pressed của control tham chiếu.

Ảnh chụp dùng Chrome, viewport `1440x1000`, tắt animation trong lúc capture và
mask OTP/freshness/aria-live để tránh sai khác do thời gian. Không cập nhật
snapshot toàn cục.

## Performance gates

Baseline trước v3: median FCP `88 ms`, transfer `203779 bytes`, `10 requests`
và long task median `0 ms`.

| Chỉ số | Gate v3 |
| --- | ---: |
| Median FCP | `<= 1200 ms` |
| Transferred bytes | `<= 250000` |
| Requests | `<= 15` |
| Long task tối đa | `<= 65 ms` |
| p95 RAF khi morph | `<= 20 ms` |
| Frame trên 25 ms | `<= 5%` |
| Idle rendering | counters RAF/canvas không đổi trong 250 ms |

Kết quả nghiệm thu ngày `2026-07-27`:

| Chỉ số | Kết quả |
| --- | ---: |
| Median FCP | `60 ms` |
| Transferred bytes | `238795` |
| Requests | `8` |
| Long task tối đa, median theo navigation | `0 ms` |
| p95 RAF khi morph | `16.8 ms` |
| Frame trên 25 ms | `0.32%` trong full suite |
| Idle rendering | RAF/canvas counters không đổi |

Full Chrome suite đạt `17/17`. Stress gate `--repeat-each=10` đạt `10/10`;
p95 RAF nằm trong `16.8–16.9 ms`, tỷ lệ frame trên 25 ms nằm trong
`0.90–2.90%`. Unit coverage đạt `87.23%` statements, `80.01%` branches,
`89.58%` functions và `88.74%` lines. Python contract đạt `112/112`.

Canary production đang chạy tại cổng `8765` trả HTTP `200`, health `ok` và
schema `5`. Vì cổng này thuộc tiến trình người dùng đang chạy, kiểm tra có xác
thực OTP/quota/shutdown được thực hiện trên fixture production cô lập tại cổng
`8766`: 3 account có đủ trường OTP/quota, 3 account usage và shutdown trả
`accepted=true`; fixture được dừng ngay sau kiểm tra. Không dừng tiến trình
người dùng ở cổng `8765`.

Optical contract, visual matrix và performance gate đều đạt nên renderer
`hybrid` được giữ làm mặc định khi WebGPU khả dụng. Runtime tự rơi về SVG v3
nếu không có adapter hoặc không đủ điều kiện, không đổi layout hay semantics.

## Lệnh kiểm tra trọng yếu

Chạy từ `frontend`:

```powershell
npm run typecheck
npm run lint
npm run test:coverage
npm run build
npx playwright test tests/e2e/liquid-glass-v3.spec.ts --project=chrome
npx playwright test tests/e2e/parity-recovery.spec.ts --project=chrome
npx playwright test tests/e2e/performance-v3.spec.ts --project=chrome
npx playwright test tests/e2e/visual-acceptance.spec.ts --project=chrome
npx playwright test --project=chrome
npx playwright test tests/e2e/performance-v3.spec.ts --project=chrome --grep "ten v3 morph" --repeat-each=10
```

Các test contract được viết RED trước implementation. Chỉ chấp nhận cutover khi
contract, parity, performance và review trực quan của toàn bộ matrix đều đạt.

## Nguồn đối chiếu chính thức

- [Human Interface Guidelines — Materials](https://developer.apple.com/design/human-interface-guidelines/materials):
  glass là functional layer, content dùng standard material và glass được dùng
  có chọn lọc.
- [WWDC26 SwiftUI](https://developer.apple.com/videos/play/wwdc2026/269/):
  chuẩn đối chiếu motion/material của kế hoạch, truy cập ngày `2026-07-27`.

Các token CSS, ngưỡng luma và giới hạn displacement là phép đo suy ra trong
Glass Lab, không phải giá trị Apple công bố.
