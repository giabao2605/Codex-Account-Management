# Liquid Glass v3 visual baselines

Baseline v3 được tạo ngày `2026-07-27` từ production bundle bằng Chrome ở
viewport `1440x1000`.

## Matrix bắt buộc

| Artifact | Theme | Effects |
| --- | --- | --- |
| `accounts-dark-full-pc.png` | Dark | Full |
| `accounts-light-full-pc.png` | Light | Full |
| `accounts-dark-reduced-pc.png` | Dark | Reduced |
| `accounts-dark-off-pc.png` | Dark | Off |
| `usage-dark-full-pc.png` | Dark | Full |
| `usage-light-full-pc.png` | Light | Full |
| `appearance-popover-light-full-pc.png` | Light | Full |
| `options-popover-dark-full-pc.png` | Dark | Full |
| `import-dialog-light-full-pc.png` | Light | Full |
| `control-rest-dark-full-pc.png` | Dark | Full |
| `control-hover-dark-full-pc.png` | Dark | Full |
| `control-pressed-dark-full-pc.png` | Dark | Full |
| `heatmap-light-daily-pc.png` | Light | Full |
| `heatmap-light-weekly-pc.png` | Light | Full |
| `heatmap-light-cumulative-pc.png` | Light | Full |

OTP countdown, freshness và vùng `aria-live` được mask. Screenshot tắt animation
trừ pressed state. Không ghi đè baseline của Phase 4 hoặc Phase 6.

Tạo lại riêng matrix này:

```powershell
cd frontend
npx playwright test tests/e2e/visual-acceptance.spec.ts --project=chrome
npx playwright test tests/e2e/visual-polish.spec.ts --project=chrome
```

Baseline đã được review trực quan cùng contract E2E, parity E2E và performance
gate. Account-options popover được kiểm tra lại sau khi khóa geometry đích của
shared-layout, không còn co shell hoặc tràn viewport.
