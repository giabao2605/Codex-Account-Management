# Liquid Glass Phase 1 Baseline and Parity Matrix

Ngày chốt baseline: 2026-07-23.

Phase 1 khóa trạng thái frontend/backend hiện tại trước khi scaffold Vue/Vite và trước khi áp Liquid Glass. Tài liệu này chỉ ghi contract và hành vi rút ra từ source/test trong repo; không ghi snapshot dữ liệu runtime, email thật, password, TOTP secret, OTP, bearer token, CSRF token, nội dung profile, hoặc nội dung `auth.json`.

## Baseline kỹ thuật

- Branch hiện tại: `main`, commit gốc đang checkout: `b8d87ff`, working tree có thay đổi chưa commit.
- Backend contract hiện tại: `API_SCHEMA_VERSION = 11`.
- Token usage contract hiện tại: `TokenUsageResponse.schema_version = 2`, `source = "codex_account_usage"`.
- Frontend hiện tại vẫn là vanilla HTML/CSS/JS trong `web/`; chưa có `frontend/`, Vite, Vue, Pinia, hoặc Playwright trong baseline.
- Build fingerprint hiện tính từ runtime Python, local web service, token usage module, và các asset `web/`.
- Dirty baseline trước thay đổi Phase 1 gồm 11 file modified, 2 file mới (`app/token_usage.py`, `tests/test_token_usage.py`) và 2.303 dòng thêm theo `git diff --stat`. Không tạo commit hoặc stage tự động.
- Light Mode lấy CSS hiện tại làm nguồn sự thật: canvas `#e1e6ed`, surface `#eceff3`, panel `rgba(238, 241, 245, 0.96)`. `theme-init.js`, runtime theme toggle và test phải cùng dùng meta theme color `#e1e6ed`.
- Visual baseline dùng fixture synthetic trong `tests/visual_baseline_app.py`, không dùng app state thật. Fixture này dùng email `.test`, token/CSRF giả, OTP giả hoặc nullable, và bao phủ account/token states `fresh`, `stale`, `unavailable`.
- Kiểm chứng Phase 1 phải chạy:
  - `python -B -m unittest discover -s tests -v`
  - `python -B -m unittest tests.test_visual_baseline -v`
  - `node --check web\app.js`
  - `node --check web\theme-init.js`

## Visual baseline đã làm sạch dữ liệu

Fixture chạy độc lập trên loopback:

```powershell
python -m uvicorn tests.visual_baseline_app:app --host 127.0.0.1 --port 8877
```

Các ảnh dưới đây chỉ chứa dữ liệu `example.test`; không đọc `accounts.json`, `.web_session.json`, `auth.json` hoặc `codex_profiles`.

Viewport yêu cầu là kích thước đã đặt cho browser khi chụp. Bảng ghi riêng kích thước pixel của file để Phase 2 so sánh đúng artifact; ảnh desktop là full-page, ảnh mobile là viewport-only.

| Trạng thái | Viewport yêu cầu | Kích thước PNG | Artifact |
| --- | --- | --- | --- |
| Accounts, Light | 1440×900 | 1425×1458 | [accounts-light-desktop.png](baselines/liquid-glass-phase-1/accounts-light-desktop.png) |
| Accounts, Dark | 1440×900 | 1425×1458 | [accounts-dark-desktop.png](baselines/liquid-glass-phase-1/accounts-dark-desktop.png) |
| Accounts, Light | 390×844 | 375×812 | [accounts-light-mobile.png](baselines/liquid-glass-phase-1/accounts-light-mobile.png) |
| Usage token/quota, Light | 1440×900 | 1425×1167 | [usage-light-desktop.png](baselines/liquid-glass-phase-1/usage-light-desktop.png) |
| Usage token/quota, Dark | 1440×900 | 1425×1167 | [usage-dark-desktop.png](baselines/liquid-glass-phase-1/usage-dark-desktop.png) |
| Usage token/quota, Light | 390×844 | 375×812 | [usage-light-mobile.png](baselines/liquid-glass-phase-1/usage-light-mobile.png) |
| Import dialog, Light | 1440×900 | 1425×1458 | [import-dialog-light-desktop.png](baselines/liquid-glass-phase-1/import-dialog-light-desktop.png) |

Visual fixture xác nhận ba account states, nullable OTP, recommendation, token coverage `fresh/stale/unavailable`, heatmap 365 ngày, quota aggregation và responsive layout. Đây là before-snapshot cho Phase 2; không phải acceptance cho Liquid Glass.

## Security và local-only invariants

| Invariant | Baseline hiện tại | Parity requirement cho Vue/Vite |
| --- | --- | --- |
| Local-only access | API reject non-loopback client và malformed/khác Host authority. | Không mở rộng CORS/LAN; Vite dev chỉ proxy local, production vẫn qua local FastAPI. |
| Session auth | Mọi `/api/*` trừ `/api/health` cần `Authorization: Bearer <session token>`. | Fragment token phải được lưu vào `sessionStorage` trước khi xóa URL; reload không mất session. |
| CSRF | Mọi mutation dùng `X-CSRF-Token`; token lấy từ `/api/bootstrap`. | CSRF chỉ giữ trong memory frontend store; mọi POST/DELETE gọi qua một API client chung. |
| Origin | Mutation chỉ chấp nhận origin HTTP loopback khớp Host/port. | Client không tự tạo cross-origin request; dev proxy giữ same-origin semantics. |
| CSP | `script-src 'self'`, `style-src 'self'`, `connect-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`. | Không inline script/style trong production candidate; `theme-init` là asset local. |
| Sensitive reveal | Password/secret chỉ lấy qua `/api/accounts/{account_id}/sensitive`, cần auth và CSRF. | Không lưu password/secret trong store lâu dài; chỉ dùng transient để copy. |
| Nullable OTP | Khi trusted time chưa sẵn sàng, OTP và countdown nullable; copy OTP disabled. | Component phải phân biệt unavailable với empty string hoặc 0. |
| Import preview | Preview read-only, redacts credentials, apply cần preview token, chống stale/tamper. | Dialog Vue giữ preview token trong memory, reset token khi đóng hoặc preview mới. |
| Token usage | `/api/usage/tokens` trả thống kê token an toàn, không expose secret/runtime path. | Usage store cache 5 phút, phân biệt `fresh`, `stale`, `unavailable`, và không suy diễn null thành 0. |
| Shutdown/profile lifecycle | Shutdown và unlink là mutation cần auth/CSRF và path-safe checks. | Mọi action giữ disabled/loading/error state tương đương baseline. |

## API parity matrix

| Endpoint | Method | Baseline contract | Tests khóa baseline |
| --- | --- | --- | --- |
| `/api/health` | GET | Public local health, trả `status`, `api_schema_version`, `build_id`. | `test_security_headers_and_local_health` |
| `/api/bootstrap` | GET | Authenticated bootstrap, trả CSRF token và state ban đầu. | `test_security_headers_and_local_health`, `test_api_state_requires_launch_session_token` |
| `/api/state` | GET | Authenticated state gồm accounts, hàng đợi recommendation, usage statistics, time sync. | `test_state_recommends_valid_account_with_highest_quota`, `test_state_reports_usage_statistics_per_account_and_totals` |
| `/api/failover/status` | GET | Trạng thái failover chỉ đọc, chỉ trả metadata tổng hợp và không trả task/profile/runtime path. | `test_failover_status_requires_auth_and_returns_only_safe_summary`, `test_public_summary_exposes_counts_without_task_metadata` |
| `/api/usage/tokens` | GET | Authenticated token usage schema v2, coverage, periods, aggregate, per-account stats. | `test_token_usage_endpoint_requires_auth_and_returns_safe_data`, `tests/test_token_usage.py` |
| `/api/accounts/import/preview` | POST | CSRF-protected preview, không ghi file, redacts credentials. | `test_import_preview_is_read_only_and_redacts_credentials` |
| `/api/accounts/import` | POST | CSRF-protected apply bằng preview token, reject stale/tamper. | `test_import_requires_preview_token_and_rejects_tampering`, `test_import_rejects_stale_preview_token` |
| `/api/accounts/{account_id}` | DELETE | CSRF-protected delete, clear token cache. | `test_delete_account_requires_csrf_and_removes_it`, `test_deleting_account_clears_token_usage_cache` |
| `/api/accounts/{account_id}/sensitive` | POST | CSRF-protected reveal password/secret theo field whitelist. | `test_invalid_sensitive_field_does_not_echo_input` |
| `/api/codex/refresh` | POST | Refresh all hoặc một account; `force_token_usage` buộc làm mới token. | `test_manual_refresh_can_force_token_usage_refresh`, `test_account_refresh_can_force_token_usage_refresh` |
| `/api/codex/{account_id}/login` | POST | Mở login local cho account. | `test_lifecycle_mutations_require_authentication_and_csrf` |
| `/api/codex/{account_id}/unlink` | POST | Ngắt liên kết và xóa vĩnh viễn profile local sau path validation. | `test_unlink_permanently_deletes_profile_without_reading_auth` |
| `/api/application/shutdown` | POST | Shutdown callback at-most-once, retry được nếu callback fail. | `test_shutdown_callback_is_invoked_at_most_once`, `test_shutdown_can_retry_after_callback_failure` |

## Frontend parity matrix

| Khu vực | Baseline hiện tại | Parity requirement cho candidate |
| --- | --- | --- |
| Topbar | Brand, theme toggle, connection status, shutdown. | Giữ trạng thái connection live, shutdown disabled/loading/error, theme-color đúng Light/Dark. |
| Workspace tabs | Accounts và Usage dùng ARIA tablist/tabpanel. | Giữ keyboard semantics, `aria-selected`, hidden panel đúng; không dùng URL fragment cho tab. |
| Accounts overview | Summary cards, sync breakdown, refresh interval, time sync. | Không mất các chỉ số account count, last updated, sync ratio, time sync status. |
| Account list | Sort ưu tiên attention/quota, recommended badge, filters, primary và option actions. | Giữ thứ tự, filter semantics, disabled state cho unavailable OTP, và copy feedback. |
| Import dialog | Open/close/cancel, textarea, preview counts, changes, errors, reject-on-errors, confirm save. | Preview không ghi dữ liệu, đóng dialog reset transient state, apply refresh lại state. |
| Profile lifecycle | Login và unlink. | Action buttons phải giữ loading state, disabled state, error toast, và không expose path/profile content. |
| Usage dashboard | Account selector, freshness badge, selected-account KPIs, heatmap daily/weekly/cumulative, single quota card, all-account quota table. | Giữ phân biệt all account vs single account, `daily_buckets: []` khác `daily_buckets: null`, tooltip/focus accessible. |
| Theme | `otp-codex-theme`, `theme-init.js`, muted Light Mode palette, Dark Mode isolated. | Appearance store phải đọc legacy key và ghi lại để rollback không mất lựa chọn. |
| Feedback | Toast, aria-live status, empty states, unavailable/stale labels. | Không làm im lặng lỗi; user-facing error vẫn generic, không echo input nhạy cảm. |
| Responsive | Desktop 1600px shell, tablet collapse, mobile single-column. | Quyết định cập nhật 24/07/2026: visual acceptance của Liquid Glass chỉ khóa PC 1440×1000; responsive CSS được giữ để tránh regression nhưng mobile không còn là gate Phase 4/cutover. |

## Phase 1 acceptance

- Baseline verification ngày 23/07/2026:
  - `python -B -m unittest discover -s tests -v`: 99 tests pass.
  - `node --check web\app.js` và `node --check web\theme-init.js`: pass.
  - `python -m pip check`: không có dependency bị hỏng.
  - `git diff --check`: không có whitespace error; chỉ có cảnh báo chuyển LF sang CRLF.
  - Branch coverage của các runtime module thuộc Phase 1: 81%.
  - Coverage toàn repository: 72%; phần thiếu chủ yếu nằm ở legacy `app/otp_codex_manager_with_account_status.py` và `run_local_web.py`, được ghi nhận là technical debt ngoài phạm vi Phase 1.
  - Chromium browser smoke: không có console error/warning; URL fragment được xóa sau bootstrap; meta theme color là `#e1e6ed` ở Light và `#0b1020` ở Dark.
- Baseline tests phải tiếp tục xanh trước khi bắt đầu Phase 2.
- Candidate Vue/Vite chỉ được coi là parity-complete khi mọi hàng trong hai matrix trên có test hoặc E2E coverage tương ứng.
- Mọi tài liệu/screenshot parity phải dùng fixtures giả trong `tests/visual_baseline_app.py`; không dùng dữ liệu trong `accounts.json`, `.web_session.json`, `auth.json`, hoặc `codex_profiles`.
- Nếu API schema tăng sau Phase 1, phải cập nhật tài liệu này và test contract trong cùng thay đổi.
