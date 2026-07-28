# Liquid Glass Phase 2 — Vue/Vite candidate shell

## Trạng thái

Phase 2 dựng một frontend candidate chạy song song với giao diện production:

- Source: `frontend/`.
- Production build candidate: `web-dist/`.
- Frontend production hiện tại vẫn là `web/`.
- `python run_local_web.py` chưa phục vụ candidate và không cần Node.js.
- Chưa áp dụng Liquid Glass hoặc chuyển các flow nghiệp vụ; các phần này thuộc Phase 3 và Phase 4.

## Kiến trúc candidate

- Vue 3, TypeScript, Composition API và Pinia.
- Không dùng Vue Router vì URL fragment được dành cho launch session token.
- Vite bind `127.0.0.1:5173`; `/api` proxy về `127.0.0.1:8765`.
- Proxy ghi lại `Origin` theo backend origin để giữ nguyên kiểm tra same-origin của FastAPI.
- Vite build vào `web-dist/`, tắt production sourcemap và tạo hashed JavaScript/CSS trong `web-dist/assets/`.
- `theme-init.js` là external asset chạy trước module entry, tiếp tục dùng key `otp-codex-theme`.
- FastAPI nhận riêng `assets_dir` cho `index.html` và optional `static_assets_dir` cho hashed assets. Candidate thiếu build sẽ fail-fast.

## Security và parity đã khóa

- Production root vẫn là `ASSETS_DIR = web/`; `BUILD_INPUTS` chưa chứa candidate source hoặc dist.
- Launch token được lấy từ fragment trước khi Vue mount, lưu vào `sessionStorage` key `otp-codex-access-token`, rồi fragment được xóa.
- API client luôn gửi bearer token; CSRF chỉ nằm trong Pinia memory state và bắt buộc với mutation.
- Candidate từ chối bootstrap nếu API schema khác `5`.
- Không có inline script, inline style, CDN, `eval`, `v-html` hoặc secret trong biến `VITE_*`.
- Theme Light/Dark giữ meta color `#e1e6ed` và `#0b1020`.
- Workspace tabs dùng native button, ARIA tablist/tabpanel, roving tabindex và ArrowLeft/ArrowRight/Home/End.

## Lệnh phát triển và kiểm chứng

```powershell
cd frontend
npm ci
npm run typecheck
npm run lint
npm run test:coverage
npm run build
npm run test:e2e
```

Candidate E2E chạy một FastAPI fixture trên loopback với dữ liệu synthetic `.test`:

```powershell
python -m uvicorn tests.production_frontend_server:app --host 127.0.0.1 --port 8878
```

Sau khi server sẵn sàng, mở:

```text
http://127.0.0.1:8878/#visual-baseline-access-token
```

Token trên là fixture công khai chỉ dùng cho test. Không dùng server candidate này với `accounts.json`, `.web_session.json`, `auth.json` hoặc `codex_profiles/`.

## Gate Phase 2

- Python candidate contract: candidate index và mọi hashed JS/CSS được FastAPI phục vụ; middleware auth/CSP vẫn hoạt động.
- Candidate mode fail-fast nếu thiếu `web-dist/index.html` hoặc `web-dist/assets/`.
- Vue typecheck và ESLint phải pass.
- Vitest coverage statements, branches, functions và lines đều tối thiểu 80%.
- Vite build không tạo sourcemap và không dùng URL `/assets/assets/...`.
- Playwright Chrome phải chứng minh fragment cleanup, session persistence, schema bootstrap, ARIA tabs, theme persistence và console sạch.
- Full Python regression suite phải tiếp tục pass trước khi bắt đầu Phase 3.

## Kết quả kiểm chứng ngày 23/07/2026

- `npm ci`: pass; 278 packages được audit, 0 vulnerability.
- `npm run typecheck`: pass.
- `npm run lint`: pass.
- `npm run test:coverage`: 15 tests pass; statements 99.09%, branches 96.49%, functions 96%, lines 100%.
- `npm run build`: pass; JavaScript 29.04 kB gzip và CSS 1.13 kB gzip.
- Hai lần build liên tiếp tạo cùng danh sách file và SHA-256.
- `npm run test:e2e`: 1 Chrome E2E pass; không có console warning/error hoặc response lỗi.
- `python -B -m unittest discover -s tests -v`: 105 tests pass.
- `python -m pip check`: không có dependency Python bị hỏng.
- `npm audit --audit-level=high`: 0 vulnerability.
- Secret-shaped scan: không có kết quả trong source, dist, tests và docs thuộc phạm vi.
- `git diff --check`: không có whitespace error; chỉ có cảnh báo LF/CRLF của working tree hiện hữu.

`npm ci` có cảnh báo deprecation cho dependency bắc cầu `glob@10.5.0`, nhưng audit không có advisory. Không dùng `--force` hoặc override dependency tree trong Phase 2.

## Chưa thuộc Phase 2

- Chưa cutover launcher sang `web-dist/`.
- Chưa đưa candidate vào runtime build fingerprint.
- Chưa chuyển import, profile lifecycle, refresh, token usage, quota, shutdown và toàn bộ error/offline behavior.
- Chưa tạo Liquid Glass primitives, Motion animation, SVG hoặc WebGL enhancement.

Phase 3 chỉ bắt đầu khi candidate shell và legacy production cùng đạt các gate trên.
