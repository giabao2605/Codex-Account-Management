# Phase 5: Production cutover

Ngày thực hiện: 2026-07-24

## Phạm vi

Vue Liquid Glass trong `frontend/`, build tại `web-dist/`, là frontend
production mặc định của launcher `run_local_web.py`. Phạm vi nghiệm thu visual
chỉ gồm PC theo quyết định ngày 24/07/2026. Responsive CSS vẫn được giữ để tránh
regression ngoài ý muốn nhưng mobile không phải release gate.

## Runtime contract

- `app.build_info` chọn mode `vue` mặc định và mode `legacy` chỉ khi
  `OTP_CODEX_FRONTEND=legacy`.
- Vue phục vụ `web-dist/index.html` và mount `/assets` trực tiếp vào
  `web-dist/assets`; build thiếu index, thư mục assets hoặc referenced asset sẽ
  fail-fast trước khi service bắt đầu.
- Build fingerprint hash toàn bộ bundle đang được phục vụ và tên frontend mode.
  Đổi bundle hoặc chuyển Vue/legacy buộc launcher nhận diện build mới, dừng phiên
  cũ an toàn rồi khởi động lại.
- `web/` được giữ nguyên làm rollback artifact trong Phase 5, không còn là
  frontend mặc định.
- `scripts/build_frontend.ps1` dùng `npm ci`, typecheck qua script build, tạo
  hashed production assets và từ chối source map.

## Security invariants

- Chỉ bind `127.0.0.1:8765`; Host và Origin phải là loopback hợp lệ.
- Access token được nhận một lần từ URL fragment, chuyển vào `sessionStorage`
  rồi xóa fragment khỏi URL.
- API ngoài health yêu cầu Bearer token; mutation yêu cầu thêm CSRF token.
- CSP không dùng `unsafe-inline` hoặc `unsafe-eval`; bundle không có production
  source map và không đưa secret vào biến môi trường Vite.
- Password và secret chỉ đi qua protected reveal endpoint khi người dùng chủ
  động yêu cầu sao chép; không render HTML từ backend.

## Build và vận hành

Build lại production:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_frontend.ps1
```

Chạy production:

```powershell
python run_local_web.py
```

Rollback tạm thời:

```powershell
$env:OTP_CODEX_FRONTEND = "legacy"
python run_local_web.py
```

Trở lại Vue:

```powershell
Remove-Item Env:OTP_CODEX_FRONTEND -ErrorAction SilentlyContinue
python run_local_web.py
```

Không xóa `accounts.json`, `.web_session.json` hoặc `codex_profiles/` trong quá
trình cutover hay rollback. Hai frontend dùng chung API contract và theme key
`otp-codex-theme`, nên dữ liệu tài khoản và lựa chọn theme không cần migration.

## Acceptance evidence

Gate cuối ngày 24/07/2026:

- Python unit/integration: 109 test pass, gồm production distribution,
  authenticated API, fail-fast build, fingerprint theo mode và legacy rollback.
- Vue: 37 test pass; coverage 91.69% statements, 80.83% branches, 89.24%
  functions và 91.50% lines.
- Typecheck, ESLint, production build, PowerShell parser, `pip check`,
  `git diff --check` và dependency audit đều pass; npm audit không có
  vulnerability.
- Chrome E2E PC: 4/4 pass qua default production asset path; không có console
  error, failed response hoặc accessibility violation critical/serious.
- PC median ba lần: FCP 736 ms, TTFB 37 ms, 158,735 byte, 12 request và không
  ghi nhận long task.
- Live canary: launcher phát hiện build cũ, shutdown/restart sang fingerprint
  `070114604b24d5c0`; health schema 5 trả `ok`, shell Vue hiện diện, legacy shell
  vắng mặt và 5/5 initial JS/CSS asset trả HTTP 200 đúng content type.
- Sau canary chỉ còn một `run_local_web.py` giữ cổng 8765. Một orphan manager
  từ 22/07 không giữ cổng cùng 7 `codex.exe` con của chính nó đã được dừng theo
  PID đã xác minh; không đụng tiến trình Python/Codex ngoài project.
- Rollback integration phục vụ thành công `web/` khi mode `legacy`, không cần
  Vue assets và có build fingerprint khác mode Vue.

## Production audit

Trạng thái: 84/100, launchable with caveats, không có blocker cho ứng dụng
local PC. Điểm bị giới hạn ở 84 vì repository chưa có CI workflow; toàn bộ gate
hiện chạy local. Các caveat không chặn release:

- dependency bắc cầu `glob@10.5.0` phát cảnh báo deprecation khi `npm ci`, nhưng
  npm audit hiện không có advisory;
- Starlette TestClient phát cảnh báo lộ trình chuyển từ `httpx` sang `httpx2`;
  cần theo dõi khi nâng FastAPI/Starlette, không ảnh hưởng runtime hiện tại;
- chưa có CI để tự chạy lại Python, Vue và E2E gate sau mỗi thay đổi.
