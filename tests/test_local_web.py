import os
import json
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.build_info import API_SCHEMA_VERSION, APP_BUILD_ID
from app.local_web_app import create_app
from app.local_web_profiles import (
    UnsafeProfilePathError,
    archive_profile_directory,
)
from app.local_web_service import LocalWebService, account_display_sort_key
from app.otp_codex_manager_with_account_status import CodexInfo
from run_local_web import (
    existing_app_is_running,
    main as run_local_web_main,
    open_browser_when_ready,
    read_existing_build_id,
    request_existing_app_shutdown,
    reserve_local_socket,
    reserve_socket_after_shutdown,
)


class LocalWebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.service = LocalWebService(
            data_file=root / "accounts.json",
            profiles_dir=root / "codex_profiles",
            enable_codex=False,
        )
        self.service.start()
        self.client = TestClient(
            create_app(self.service),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51000),
        )
        self.client.headers.update(
            {
                "Authorization": (
                    f"Bearer {self.service.access_token}"
                )
            }
        )
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.csrf_token = response.json()["csrf_token"]
        self.headers = {
            "X-CSRF-Token": self.csrf_token,
            "Origin": "http://127.0.0.1",
        }

    def preview_and_import(
        self,
        lines: str,
        *,
        reject_on_errors: bool = False,
    ):
        preview = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={"lines": lines},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        return self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "preview_token": preview.json()["preview_token"],
                "reject_on_errors": reject_on_errors,
            },
        )

    def tearDown(self) -> None:
        self.client.close()
        self.service.close()
        self.temp_dir.cleanup()

    def test_security_headers_and_local_health(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "api_schema_version": API_SCHEMA_VERSION,
                "build_id": APP_BUILD_ID,
            },
        )
        self.assertIn(
            "default-src 'self'",
            response.headers["content-security-policy"],
        )
        self.assertEqual(
            response.headers["x-content-type-options"],
            "nosniff",
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-otp-codex-app"], "1")
        bootstrap = self.client.get("/api/bootstrap").json()
        self.assertEqual(
            bootstrap["api_schema_version"],
            API_SCHEMA_VERSION,
        )
        self.assertEqual(bootstrap["build_id"], APP_BUILD_ID)
        self.assertEqual(
            self.client.get("/api/state").json()[
                "refresh_interval_seconds"
            ],
            60,
        )

    def test_account_display_order_prioritizes_attention_then_quota(
        self,
    ) -> None:
        rows = [
            {
                "email": "zero@example.com",
                "account_state": "Hoạt động bình thường",
                "sync_status": "Đã đồng bộ",
                "quota_remaining": "0%",
            },
            {
                "email": "low@example.com",
                "account_state": "Hoạt động bình thường",
                "sync_status": "Đã đồng bộ",
                "quota_remaining": "20%",
            },
            {
                "email": "attention@example.com",
                "account_state": "Chưa xác định",
                "sync_status": "Cần đăng nhập",
                "quota_remaining": "0%",
            },
            {
                "email": "logged-out@example.com",
                "account_state": "Hoạt động bình thường",
                "sync_status": "Đã đăng xuất – bấm Liên kết Codex",
                "quota_remaining": "1%",
            },
            {
                "email": "unknown@example.com",
                "account_state": "Hoạt động bình thường",
                "sync_status": "Đã đồng bộ",
                "quota_remaining": "—",
            },
            {
                "email": "high@example.com",
                "account_state": "Hoạt động bình thường",
                "sync_status": "Đã đồng bộ",
                "quota_remaining": "85%",
            },
        ]

        ordered = sorted(rows, key=account_display_sort_key)

        self.assertEqual(
            [row["email"] for row in ordered],
            [
                "attention@example.com",
                "logged-out@example.com",
                "high@example.com",
                "low@example.com",
                "unknown@example.com",
                "zero@example.com",
            ],
        )

    def test_index_loads_local_assets_only(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OTP Codex Local", response.text)
        self.assertIn('href="/assets/styles.css"', response.text)
        self.assertIn('src="/assets/app.js"', response.text)
        self.assertNotIn("<script>", response.text)
        self.assertIn('id="open-import"', response.text)
        self.assertIn('id="account-dialog"', response.text)
        self.assertIn('id="account-filter"', response.text)
        self.assertIn('value="usable"', response.text)
        self.assertIn('value="attention"', response.text)
        self.assertIn('value="quota-available"', response.text)
        self.assertIn('value="quota-low"', response.text)
        self.assertIn('value="quota-empty"', response.text)
        self.assertIn('value="quota-unknown"', response.text)
        self.assertNotIn('id="account-search"', response.text)
        self.assertNotIn('id="attention-filter"', response.text)

        script = self.client.get("/assets/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("window.sessionStorage", script.text)

    def test_frontend_supports_persistent_light_and_dark_themes(self) -> None:
        page = self.client.get("/").text
        init_script = self.client.get("/assets/theme-init.js")
        app_script = self.client.get("/assets/app.js").text
        styles = self.client.get("/assets/styles.css").text

        self.assertEqual(init_script.status_code, 200)
        self.assertIn('content="light dark"', page)
        self.assertIn('src="/assets/theme-init.js"', page)
        self.assertIn('id="theme-toggle"', page)
        self.assertIn('aria-pressed="true"', page)
        self.assertIn('id="theme-color"', page)
        self.assertIn('otp-codex-theme', init_script.text)
        self.assertIn('window.localStorage', init_script.text)
        self.assertIn('prefers-color-scheme: light', init_script.text)
        self.assertIn('themeToggle: document.querySelector("#theme-toggle")', app_script)
        self.assertIn('ui.themeToggle.addEventListener("click"', app_script)
        self.assertIn('window.localStorage.setItem(themeStorageKey', app_script)
        self.assertIn(':root[data-theme="light"]', styles)
        self.assertIn('--canvas: #e8edf5;', styles)
        self.assertIn('--surface: #f1f4f8;', styles)
        self.assertIn('--panel-background: rgba(242, 245, 249, 0.94);', styles)
        self.assertIn('.theme-toggle {', styles)
        self.assertIn('position: fixed', styles)

    def test_frontend_prioritizes_primary_actions_and_accessible_feedback(
        self,
    ) -> None:
        page = self.client.get("/").text
        script = self.client.get("/assets/app.js").text
        styles = self.client.get("/assets/styles.css").text

        self.assertIn('id="refresh-interval">—', page)
        self.assertNotIn("TRÌNH QUẢN LÝ CỤC BỘ", page)
        self.assertIn('id="last-updated"', page)
        self.assertNotIn('id="last-updated" aria-live="polite"', page)
        self.assertEqual(page.count('class="summary-card"'), 4)
        self.assertIn('id="sync-success-ratio"', page)
        self.assertIn('class="sync-breakdown"', page)
        self.assertIn('id="sync-success-count"', page)
        self.assertIn('id="sync-login-count"', page)
        self.assertIn('id="sync-unlinked-count"', page)
        self.assertIn('id="sync-error-count"', page)
        self.assertNotIn('class="sync-banner"', page)
        self.assertIn('id="visible-account-count"', page)
        self.assertIn("option-toggle", script)
        self.assertIn('actionButton(account.otp, "copy-otp"', script)
        self.assertIn('title = "Bấm để sao chép OTP"', script)
        self.assertIn('setAttribute("aria-expanded"', script)
        self.assertNotIn('"account-more"', script)
        self.assertIn(".option-actions[hidden]", styles)
        self.assertIn("grid-column: 3", styles)
        self.assertIn("cursor: copy", styles)
        self.assertIn("appearance: none", styles)
        self.assertIn("background-position:", styles)
        self.assertIn("Sao chép mật khẩu", script)
        self.assertIn("Sao chép secret", script)
        self.assertIn('element("progress"', script)
        self.assertIn('ui.toast.setAttribute("role", "alert")', script)
        self.assertIn("otp: _otp", script)
        self.assertIn("openAccountIds", script)
        self.assertIn("min-width: 0", styles)
        self.assertIn("overflow-wrap: anywhere", styles)
        self.assertNotIn("innerHTML", script)
        self.assertIn('ui.accountFilter.addEventListener("change"', script)
        self.assertNotIn("attentionOnly", script)
        self.assertIn('filter === "usable"', script)
        self.assertIn('quotaKnown && quota > 0', script)
        self.assertIn('filter === "attention"', script)
        self.assertIn('filter === "quota-available"', script)
        self.assertIn('filter === "quota-low"', script)
        self.assertIn('filter === "quota-empty"', script)
        self.assertIn('filter === "quota-unknown"', script)
        self.assertIn("function syncMetrics", script)
        self.assertIn("function formatRefreshInterval", script)
        self.assertIn("summaryTotal === state.accounts.length", script)
        self.assertIn('classList.toggle("is-active"', script)
        self.assertIn("grid-template-columns: repeat(4", styles)
        self.assertIn(".sync-breakdown", styles)
        self.assertNotIn(".connection::before", styles)

        create_card = script[
            script.index("function createAccountCard") :
            script.index("function applyAccountFilters")
        ]
        primary_actions = create_card[
            create_card.index('const actions = element("div", "card-actions")') :
            create_card.index("const optionToggle")
        ]
        option_actions = create_card[
            create_card.index('const optionActions = element("div", "option-actions")') :
            create_card.index("const deleteButton")
        ]
        self.assertIn('"Sao chép email", "copy-email"', primary_actions)
        self.assertIn('"Sao chép mật khẩu", "copy-sensitive"', primary_actions)
        self.assertNotIn('"Sao chép OTP", "copy-otp"', primary_actions)
        self.assertNotIn('"Đồng bộ", "refresh"', primary_actions)
        self.assertIn('"Sao chép OTP", "copy-otp"', option_actions)
        self.assertIn('"Đồng bộ", "refresh"', option_actions)
        self.assertIn('ariaLabel: `Sao chép secret của ${account.email}`', option_actions)
        self.assertIn('ariaLabel: `Liên kết Codex cho ${account.email}`', option_actions)
        self.assertIn('ariaLabel: `Xóa tài khoản ${account.email}`', create_card)
        self.assertNotIn('"Sao chép email", "copy-email"', option_actions)
        self.assertNotIn('"Sao chép mật khẩu", "copy-sensitive"', option_actions)

        render_state = script[script.index("function renderState") :]
        self.assertLess(
            render_state.index("applyAccountFilters();"),
            render_state.index("restoreCardInteraction(cardInteraction);"),
        )

    def test_frontend_exposes_preview_profile_recommendation_and_shutdown_actions(
        self,
    ) -> None:
        page = self.client.get("/").text
        script = self.client.get("/assets/app.js").text

        self.assertIn('id="preview-import"', page)
        self.assertIn('id="reject-on-errors"', page)
        self.assertIn('id="recommended-account"', page)
        self.assertIn('id="orphan-profile-count"', page)
        self.assertIn('id="archive-orphan-profiles"', page)
        self.assertIn('id="shutdown-application"', page)
        self.assertIn('"unlink"', script)
        self.assertIn('"reset-profile"', script)
        self.assertIn("/api/accounts/import/preview", script)
        self.assertIn("preview_token", script)
        self.assertIn("reject_on_errors", script)
        self.assertIn("/unlink", script)
        self.assertIn("/reset-profile", script)
        self.assertIn("/api/profiles/orphans/archive", script)
        self.assertIn("/api/application/shutdown", script)
        self.assertIn("previewRequestId", script)
        self.assertIn("requestedLines", script)
        self.assertIn("ui.accountLines.value.trim() !== requestedLines", script)
        shutdown_function = script[
            script.index("async function shutdownApplication()") :
            script.index("async function refreshAllAccounts()")
        ]
        self.assertLess(
            shutdown_function.index("applicationStopping = true"),
            shutdown_function.index('await api("/api/application/shutdown"'),
        )
        self.assertIn("if (!error.status)", shutdown_function)
        self.assertGreaterEqual(script.count("window.confirm("), 4)

    def test_frontend_exposes_accessible_usage_statistics_tab(self) -> None:
        page = self.client.get("/").text
        script = self.client.get("/assets/app.js").text
        styles = self.client.get("/assets/styles.css").text

        self.assertIn('role="tablist"', page)
        self.assertIn('id="accounts-tab"', page)
        self.assertIn('id="usage-tab"', page)
        self.assertIn('aria-controls="accounts-panel"', page)
        self.assertIn('aria-controls="usage-panel"', page)
        self.assertIn('id="usage-panel"', page)
        self.assertIn('id="usage-account-rows"', page)
        self.assertIn('id="usage-average-used"', page)
        self.assertIn('id="usage-average-remaining"', page)
        self.assertIn('id="usage-known-count"', page)
        self.assertIn('id="usage-stale-count"', page)
        self.assertIn('id="usage-attention-count"', page)
        self.assertIn("function activateTab", script)
        self.assertIn("function renderUsageStatistics", script)
        self.assertIn('event.key === "ArrowRight"', script)
        self.assertIn('event.key === "ArrowLeft"', script)
        self.assertIn("usage_statistics", script)
        self.assertIn("expectedApiSchemaVersion", script)
        self.assertIn("Dịch vụ nền đang dùng phiên bản cũ", script)
        self.assertIn("backendCompatible", script)
        self.assertIn(".workspace-tabs", styles)
        self.assertIn(".usage-table", styles)

    def test_frontend_explains_recommendation_and_profile_actions(
        self,
    ) -> None:
        page = self.client.get("/").text
        script = self.client.get("/assets/app.js").text

        self.assertIn("Tài khoản khỏe, còn quota cao nhất", page)
        self.assertIn("Profile không còn dùng", page)
        self.assertIn("Thư mục đăng nhập cũ", page)
        self.assertIn("Giữ tài khoản trong danh sách", script)
        self.assertIn("tạo profile trống", script)

    def test_rejects_non_loopback_client(self) -> None:
        remote_client = TestClient(
            create_app(self.service),
            base_url="http://127.0.0.1",
            client=("203.0.113.10", 51001),
        )

        try:
            response = remote_client.get("/api/health")
            self.assertEqual(response.status_code, 403)
        finally:
            remote_client.close()

    def test_api_state_requires_launch_session_token(self) -> None:
        unauthenticated_client = TestClient(
            create_app(self.service),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51002),
        )

        try:
            self.assertEqual(
                unauthenticated_client.get("/api/state").status_code,
                401,
            )
            self.assertEqual(
                unauthenticated_client.get("/api/health").status_code,
                200,
            )
        finally:
            unauthenticated_client.close()

    def test_lifecycle_mutations_require_authentication_and_csrf(self) -> None:
        account_id = "0" * 16
        paths = (
            f"/api/codex/{account_id}/unlink",
            f"/api/codex/{account_id}/reset-profile",
            "/api/profiles/orphans/archive",
            "/api/application/shutdown",
        )
        unauthenticated_client = TestClient(
            create_app(self.service),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51003),
        )

        try:
            for path in paths:
                with self.subTest(path=path, protection="auth"):
                    response = unauthenticated_client.post(path)
                    self.assertEqual(response.status_code, 401)
                with self.subTest(path=path, protection="csrf"):
                    response = self.client.post(path)
                    self.assertEqual(response.status_code, 403)
        finally:
            unauthenticated_client.close()

    def test_shutdown_callback_is_invoked_at_most_once(self) -> None:
        callback_calls: list[None] = []
        shutdown_client = TestClient(
            create_app(
                self.service,
                shutdown_callback=lambda: callback_calls.append(None),
            ),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51004),
        )
        shutdown_client.headers.update(
            {"Authorization": f"Bearer {self.service.access_token}"}
        )

        try:
            csrf_token = shutdown_client.get("/api/bootstrap").json()[
                "csrf_token"
            ]
            headers = {
                "X-CSRF-Token": csrf_token,
                "Origin": "http://127.0.0.1",
            }
            first = shutdown_client.post(
                "/api/application/shutdown",
                headers=headers,
            )
            second = shutdown_client.post(
                "/api/application/shutdown",
                headers=headers,
            )

            self.assertEqual(first.status_code, 200, first.text)
            self.assertIn(second.status_code, {200, 409})
            self.assertEqual(callback_calls, [None])
        finally:
            shutdown_client.close()

    def test_shutdown_can_retry_after_callback_failure(self) -> None:
        callback_calls: list[int] = []

        def flaky_callback() -> None:
            callback_calls.append(len(callback_calls) + 1)
            if len(callback_calls) == 1:
                raise RuntimeError("temporary failure")

        shutdown_client = TestClient(
            create_app(
                self.service,
                shutdown_callback=flaky_callback,
            ),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51005),
        )
        shutdown_client.headers.update(
            {"Authorization": f"Bearer {self.service.access_token}"}
        )

        try:
            csrf_token = shutdown_client.get("/api/bootstrap").json()[
                "csrf_token"
            ]
            headers = {
                "X-CSRF-Token": csrf_token,
                "Origin": "http://127.0.0.1",
            }
            first = shutdown_client.post(
                "/api/application/shutdown",
                headers=headers,
            )
            second = shutdown_client.post(
                "/api/application/shutdown",
                headers=headers,
            )
            third = shutdown_client.post(
                "/api/application/shutdown",
                headers=headers,
            )

            self.assertEqual(first.status_code, 503)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json(), {"accepted": True})
            self.assertEqual(third.json(), {"accepted": False})
            self.assertEqual(callback_calls, [1, 2])
        finally:
            shutdown_client.close()

    def test_profile_lifecycle_archives_without_reading_auth_file(self) -> None:
        self.service.import_accounts(
            "user@example.com|password|JBSWY3DPEHPK3PXP"
        )
        account_id = self.service.account_id("user@example.com")
        profile_dir = self.service.profile_directory("user@example.com")
        profile_dir.mkdir(parents=True)
        (profile_dir / "auth.json").write_text(
            "unlink-auth-content",
            encoding="utf-8",
        )
        original_open = Path.open

        def reject_auth_reads(path: Path, mode="r", *args, **kwargs):
            if path.name == "auth.json" and "r" in mode:
                raise AssertionError("auth.json must not be read")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", reject_auth_reads):
            unlink = self.client.post(
                f"/api/codex/{account_id}/unlink",
                headers=self.headers,
            )
        self.assertEqual(unlink.status_code, 200, unlink.text)
        self.assertFalse(profile_dir.exists())

        profile_dir.mkdir(parents=True)
        (profile_dir / "auth.json").write_text(
            "reset-auth-content",
            encoding="utf-8",
        )
        with patch.object(Path, "open", reject_auth_reads):
            reset = self.client.post(
                f"/api/codex/{account_id}/reset-profile",
                headers=self.headers,
            )
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertTrue(profile_dir.is_dir())
        self.assertFalse((profile_dir / "auth.json").exists())

        orphan_dir = self.service.profiles_dir / "orphan-profile"
        orphan_dir.mkdir()
        (orphan_dir / "auth.json").write_text(
            "orphan-auth-content",
            encoding="utf-8",
        )
        self.assertEqual(
            self.client.get("/api/state").json()["orphan_profile_count"],
            1,
        )
        with patch.object(Path, "open", reject_auth_reads):
            archive = self.client.post(
                "/api/profiles/orphans/archive",
                headers=self.headers,
            )
        self.assertEqual(archive.status_code, 200, archive.text)
        self.assertFalse(orphan_dir.exists())
        self.assertEqual(
            self.client.get("/api/state").json()["orphan_profile_count"],
            0,
        )

        archived_auth_values = {
            path.read_text(encoding="utf-8")
            for path in (self.service.profiles_dir / ".archived").rglob(
                "auth.json"
            )
        }
        self.assertEqual(
            archived_auth_values,
            {
                "unlink-auth-content",
                "reset-auth-content",
                "orphan-auth-content",
            },
        )

    def test_state_recommends_valid_account_with_highest_quota(self) -> None:
        self.service.import_accounts(
            "high@example.com|password|JBSWY3DPEHPK3PXP\n"
            "low@example.com|password|JBSWY3DPEHPK3PXQ\n"
            "attention@example.com|password|JBSWY3DPEHPK3PXR"
        )
        with self.service._lock:
            self.service._codex_info = {
                "high@example.com": CodexInfo(
                    stored_email="high@example.com",
                    remaining_percent="85%",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
                "low@example.com": CodexInfo(
                    stored_email="low@example.com",
                    remaining_percent="25%",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
                "attention@example.com": CodexInfo(
                    stored_email="attention@example.com",
                    remaining_percent="99%",
                    account_state="Chưa xác định",
                    status="Cần đăng nhập",
                ),
            }

        recommendation = self.client.get("/api/state").json()[
            "recommendation"
        ]

        self.assertEqual(recommendation["email"], "high@example.com")
        self.assertEqual(
            recommendation["account_id"],
            self.service.account_id("high@example.com"),
        )
        self.assertEqual(recommendation["quota_remaining"], "85%")

    def test_recommendation_uses_earlier_reset_as_quota_tie_breaker(
        self,
    ) -> None:
        self.service.import_accounts(
            "later@example.com|password|JBSWY3DPEHPK3PXP\n"
            "sooner@example.com|password|JBSWY3DPEHPK3PXQ"
        )
        with self.service._lock:
            self.service._codex_info = {
                "later@example.com": CodexInfo(
                    stored_email="later@example.com",
                    remaining_percent="50%",
                    reset_at="24/07 10:00",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
                "sooner@example.com": CodexInfo(
                    stored_email="sooner@example.com",
                    remaining_percent="50%",
                    reset_at="23/07 10:00",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
            }

        recommendation = self.client.get("/api/state").json()[
            "recommendation"
        ]

        self.assertEqual(recommendation["email"], "sooner@example.com")
        self.assertEqual(recommendation["quota_reset_at"], "23/07 10:00")

    def test_state_reports_usage_statistics_per_account_and_totals(
        self,
    ) -> None:
        self.service.import_accounts(
            "healthy@example.com|password|JBSWY3DPEHPK3PXP\n"
            "low@example.com|password|JBSWY3DPEHPK3PXQ\n"
            "empty@example.com|password|JBSWY3DPEHPK3PXR\n"
            "attention@example.com|password|JBSWY3DPEHPK3PXS\n"
            "unknown@example.com|password|JBSWY3DPEHPK3PXT"
        )
        with self.service._lock:
            self.service._codex_info = {
                "healthy@example.com": CodexInfo(
                    stored_email="healthy@example.com",
                    remaining_percent="75%",
                    cycle="Weekly",
                    reset_at="25/07 10:00",
                    plan_type="Plus",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                    last_sync="09:00:00",
                ),
                "low@example.com": CodexInfo(
                    stored_email="low@example.com",
                    remaining_percent="10%",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
                "empty@example.com": CodexInfo(
                    stored_email="empty@example.com",
                    remaining_percent="0%",
                    account_state="Hoạt động bình thường",
                    status="Đã đồng bộ",
                ),
                "attention@example.com": CodexInfo(
                    stored_email="attention@example.com",
                    remaining_percent="90%",
                    account_state="Chưa xác định",
                    status="Cần đăng nhập",
                ),
                "unknown@example.com": CodexInfo(
                    stored_email="unknown@example.com",
                    remaining_percent="—",
                    account_state="Chưa xác định",
                    status="Chưa liên kết",
                ),
            }

        usage = self.client.get("/api/state").json()["usage_statistics"]

        self.assertEqual(usage["total_accounts"], 5)
        self.assertEqual(usage["quota_known_accounts"], 3)
        self.assertEqual(usage["quota_unknown_accounts"], 1)
        self.assertEqual(usage["stale_quota_accounts"], 1)
        self.assertEqual(usage["usable_accounts"], 2)
        self.assertEqual(usage["attention_accounts"], 2)
        self.assertEqual(usage["low_quota_accounts"], 1)
        self.assertEqual(usage["exhausted_accounts"], 1)
        self.assertEqual(usage["average_remaining_percent"], 28.33)
        self.assertEqual(usage["average_used_percent"], 71.67)
        self.assertEqual(usage["minimum_remaining_percent"], 0.0)
        self.assertEqual(usage["maximum_remaining_percent"], 75.0)
        self.assertEqual(usage["median_remaining_percent"], 10.0)
        self.assertEqual(usage["next_reset_at"], "25/07 10:00")
        self.assertEqual(usage["schema_version"], 1)
        self.assertFalse(usage["history_available"])
        self.assertEqual(usage["source"], "codex_rate_limits_snapshot")
        self.assertTrue(usage["generated_at"])
        self.assertNotIn("as_of", usage)
        self.assertEqual(
            usage["plan_distribution"],
            [
                {"plan_type": "—", "count": 4},
                {"plan_type": "Plus", "count": 1},
            ],
        )
        self.assertEqual(len(usage["accounts"]), 5)
        serialized_usage = str(usage).casefold()
        for sensitive_name in (
            "otp",
            "password",
            "secret",
            "access_token",
            "csrf",
            "auth.json",
        ):
            self.assertNotIn(sensitive_name, serialized_usage)

        healthy = next(
            row for row in usage["accounts"]
            if row["email"] == "healthy@example.com"
        )
        self.assertEqual(healthy["quota_remaining_percent"], 75.0)
        self.assertEqual(healthy["quota_used_percent"], 25.0)
        self.assertEqual(healthy["plan_type"], "Plus")
        self.assertEqual(healthy["quota_cycle"], "Weekly")
        self.assertEqual(healthy["quota_reset_at"], "25/07 10:00")
        self.assertEqual(healthy["last_sync"], "09:00:00")
        self.assertTrue(healthy["is_usable"])
        self.assertFalse(healthy["needs_attention"])

        unknown = next(
            row for row in usage["accounts"]
            if row["email"] == "unknown@example.com"
        )
        self.assertIsNone(unknown["quota_remaining_percent"])
        self.assertIsNone(unknown["quota_used_percent"])

        stale = next(
            row for row in usage["accounts"]
            if row["email"] == "attention@example.com"
        )
        self.assertIsNone(stale["quota_remaining_percent"])
        self.assertIsNone(stale["quota_used_percent"])
        self.assertTrue(stale["quota_is_stale"])
        self.assertEqual(stale["quota_cycle"], "—")
        self.assertEqual(stale["quota_reset_at"], "—")

    def test_usage_statistics_clamps_out_of_range_quota_values(self) -> None:
        usage = self.service._usage_statistics(
            [
                {
                    "id": "high",
                    "email": "high@example.com",
                    "quota_remaining": "150%",
                    "account_state": "Hoạt động bình thường",
                    "sync_status": "Đã đồng bộ",
                },
                {
                    "id": "low",
                    "email": "low@example.com",
                    "quota_remaining": "-5%",
                    "account_state": "Hoạt động bình thường",
                    "sync_status": "Đã đồng bộ",
                },
            ]
        )

        self.assertEqual(usage["minimum_remaining_percent"], 0.0)
        self.assertEqual(usage["maximum_remaining_percent"], 100.0)
        self.assertEqual(
            [row["quota_used_percent"] for row in usage["accounts"]],
            [0.0, 100.0],
        )

    def test_archive_revalidates_destination_before_protecting_it(self) -> None:
        profiles_dir = Path(self.temp_dir.name) / "safe-profiles"
        profiles_dir.mkdir()
        profile_dir = profiles_dir / "profile"
        profile_dir.mkdir()

        with (
            patch(
                "app.local_web_profiles.is_reparse_point",
                side_effect=lambda path: path.name != ".archived",
            ),
            patch(
                "app.local_web_profiles.protect_sensitive_path"
            ) as protect_path,
        ):
            with self.assertRaises(UnsafeProfilePathError):
                archive_profile_directory(profiles_dir, profile_dir)

        self.assertEqual(protect_path.call_count, 1)

    def test_rejects_malformed_host_authority(self) -> None:
        response = self.client.get(
            "/api/state",
            headers={"Host": "127.0.0.1:notaport"},
        )

        self.assertEqual(response.status_code, 403)

    def test_mutation_requires_csrf_token(self) -> None:
        response = self.client.post(
            "/api/accounts/import",
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_import_preview_is_read_only_and_redacts_credentials(self) -> None:
        lines = (
            "user@example.com|super-private-password|"
            "JBSWY3DPEHPK3PXP\n"
            "invalid-line"
        )

        response = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={"lines": lines},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsInstance(payload["preview_token"], str)
        self.assertGreaterEqual(len(payload["preview_token"]), 32)
        self.assertEqual(payload["counts"]["added"], 1)
        self.assertEqual(payload["counts"]["updated"], 0)
        self.assertEqual(payload["counts"]["duplicates"], 0)
        self.assertEqual(payload["counts"]["errors"], 1)
        self.assertEqual(
            payload["changes"],
            [{"email": "user@example.com", "action": "add"}],
        )
        serialized_changes = str(payload["changes"]).casefold()
        self.assertNotIn("super-private-password", serialized_changes)
        self.assertNotIn("jbswy3dpehpk3pxp", serialized_changes)
        self.assertEqual(self.service.state()["accounts"], [])
        self.assertFalse(self.service.data_file.exists())

    def test_import_requires_preview_token_and_rejects_tampering(self) -> None:
        missing_token = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"reject_on_errors": False},
        )
        preview = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
        )
        token = preview.json()["preview_token"]
        tampered = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "preview_token": f"{token[:-1]}x",
                "reject_on_errors": False,
            },
        )

        self.assertEqual(missing_token.status_code, 422)
        self.assertGreaterEqual(tampered.status_code, 400)
        self.assertLess(tampered.status_code, 500)
        self.assertEqual(self.service.state()["accounts"], [])

    def test_import_rejects_stale_preview_token(self) -> None:
        preview = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={
                "lines": (
                    "previewed@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.service.import_accounts(
            "concurrent@example.com|password|JBSWY3DPEHPK3PXQ"
        )

        response = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "preview_token": preview.json()["preview_token"],
                "reject_on_errors": False,
            },
        )

        self.assertEqual(response.status_code, 409)
        emails = {
            account["email"]
            for account in self.service.state()["accounts"]
        }
        self.assertEqual(emails, {"concurrent@example.com"})

    def test_import_reject_on_errors_is_all_or_nothing(self) -> None:
        preview = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={
                "lines": (
                    "valid@example.com|password|"
                    "JBSWY3DPEHPK3PXP\n"
                    "invalid-line"
                )
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["counts"]["errors"], 1)

        response = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "preview_token": preview.json()["preview_token"],
                "reject_on_errors": True,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.service.state()["accounts"], [])
        self.assertFalse(self.service.data_file.exists())

    def test_import_can_accept_valid_rows_from_preview_with_errors(self) -> None:
        response = self.preview_and_import(
            "valid@example.com|password|JBSWY3DPEHPK3PXP\n"
            "invalid-line",
            reject_on_errors=False,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["added"], 1)
        self.assertEqual(len(response.json()["errors"]), 1)
        self.assertEqual(
            self.service.state()["accounts"][0]["email"],
            "valid@example.com",
        )

    def test_import_state_and_sensitive_values_are_separated(self) -> None:
        response = self.preview_and_import(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["added"], 1)

        state_response = self.client.get("/api/state")
        state = state_response.json()
        serialized_state = state_response.text.casefold()
        self.assertEqual(len(state["accounts"]), 1)
        self.assertEqual(
            state["accounts"][0]["email"],
            "user@example.com",
        )
        self.assertNotIn("password", serialized_state)
        self.assertNotIn("jbswy3dpehpk3pxp", serialized_state)

        account_id = state["accounts"][0]["id"]
        secret_response = self.client.post(
            f"/api/accounts/{account_id}/sensitive",
            headers=self.headers,
            json={"field": "secret"},
        )
        password_response = self.client.post(
            f"/api/accounts/{account_id}/sensitive",
            headers=self.headers,
            json={"field": "password"},
        )
        self.assertEqual(
            secret_response.json()["value"],
            "JBSWY3DPEHPK3PXP",
        )
        self.assertEqual(
            password_response.json()["value"],
            "password",
        )

    def test_import_reports_duplicates_updates_and_conflicts(self) -> None:
        first = self.preview_and_import(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        duplicate = self.preview_and_import(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        update = self.preview_and_import(
            "user@example.com|new-password|JBSWY3DPEHPK3PXQ",
        )
        conflict = self.preview_and_import(
            "other@example.com|password|JBSWY3DPEHPK3PXQ\n"
            "invalid-line",
        )

        self.assertEqual(first.json()["added"], 1)
        self.assertEqual(duplicate.json()["duplicates"], 1)
        self.assertEqual(update.json()["updated"], 1)
        self.assertEqual(len(conflict.json()["errors"]), 2)

    def test_invalid_sensitive_field_does_not_echo_input(self) -> None:
        import_response = self.preview_and_import(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        self.assertEqual(import_response.status_code, 200)
        account_id = self.client.get(
            "/api/state"
        ).json()["accounts"][0]["id"]

        response = self.client.post(
            f"/api/accounts/{account_id}/sensitive",
            headers=self.headers,
            json={"field": "secret-and-token-value"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret-and-token-value", response.text)

    def test_delete_account_requires_csrf_and_removes_it(self) -> None:
        self.preview_and_import(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        account_id = self.client.get(
            "/api/state"
        ).json()["accounts"][0]["id"]

        response = self.client.delete(
            f"/api/accounts/{account_id}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": True})
        self.assertEqual(
            self.client.get("/api/state").json()["accounts"],
            [],
        )

    def test_rejects_cross_origin_mutation(self) -> None:
        response = self.client.post(
            "/api/accounts/import",
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Origin": "https://attacker.example",
            },
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_rejects_other_loopback_port_origin(self) -> None:
        response = self.client.post(
            "/api/accounts/import",
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Origin": "http://127.0.0.1:9999",
            },
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_concurrent_imports_do_not_lose_accounts(self) -> None:
        barrier = threading.Barrier(8)

        def import_one(index: int) -> None:
            barrier.wait()
            secret = f"JBSWY3DPEHPK3P{chr(ord('A') + index)}"
            self.service.import_accounts(
                f"user{index}@example.com|password|{secret}"
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(import_one, index) for index in range(8)]
            for future in futures:
                future.result()

        self.assertEqual(len(self.service.state()["accounts"]), 8)

    def test_missing_codex_command_does_not_leave_waiting_status(self) -> None:
        enabled_service = LocalWebService(
            data_file=Path(self.temp_dir.name) / "login-accounts.json",
            profiles_dir=Path(self.temp_dir.name) / "login-profiles",
            enable_codex=True,
        )
        enabled_service.refresh_async = lambda account_ids=None: False
        enabled_service.import_accounts(
            "login@example.com|password|JBSWY3DPEHPK3PXP"
        )
        account_id = enabled_service.state()["accounts"][0]["id"]

        with patch("app.local_web_service.build_codex_command", return_value=None):
            with self.assertRaises(RuntimeError):
                enabled_service.login(account_id)

        status = enabled_service.state()["accounts"][0]["sync_status"]
        self.assertNotEqual(status, "Đang chờ đăng nhập...")
        enabled_service.close()

    def test_service_can_start_after_close(self) -> None:
        service = LocalWebService(
            data_file=Path(self.temp_dir.name) / "restart-accounts.json",
            profiles_dir=Path(self.temp_dir.name) / "restart-profiles",
            enable_codex=False,
        )
        service.start()
        service.close()
        service.start()

        self.assertFalse(service._stop_event.is_set())
        service.close()

    def test_launcher_allows_only_one_process_per_port(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()

        with (
            patch("run_local_web.HOST", "127.0.0.1"),
            patch("run_local_web.PORT", free_port),
        ):
            first_socket = reserve_local_socket()
            try:
                with self.assertRaises(OSError):
                    reserve_local_socket()
            finally:
                first_socket.close()

    def test_launcher_rejects_running_app_with_stale_build(self) -> None:
        with patch(
            "run_local_web.read_existing_build_id",
            return_value="stale-build",
        ):
            self.assertFalse(existing_app_is_running("session-token"))

    def test_launcher_accepts_authenticated_current_build(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"X-OTP-Codex-App": "1"}

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

        with (
            patch(
                "run_local_web.read_existing_build_id",
                return_value=APP_BUILD_ID,
            ),
            patch(
                "run_local_web.urllib.request.urlopen",
                return_value=FakeResponse(),
            ) as urlopen,
        ):
            self.assertTrue(existing_app_is_running("session-token"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer session-token",
        )

    def test_launcher_reads_current_build_from_health(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"X-OTP-Codex-App": "1"}

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {"status": "ok", "build_id": APP_BUILD_ID}
                ).encode("utf-8")

        with patch(
            "run_local_web.urllib.request.urlopen",
            return_value=FakeResponse(),
        ):
            self.assertEqual(read_existing_build_id(), APP_BUILD_ID)

    def test_launcher_opens_browser_only_for_current_build(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"X-OTP-Codex-App": "1"}

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {"status": "ok", "build_id": APP_BUILD_ID}
                ).encode("utf-8")

        with (
            patch(
                "run_local_web.urllib.request.urlopen",
                return_value=FakeResponse(),
            ),
            patch("run_local_web.webbrowser.open") as open_browser,
        ):
            open_browser_when_ready("session-token")

        open_browser.assert_called_once_with(
            "http://127.0.0.1:8765/#session-token"
        )

    def test_launcher_requests_authenticated_shutdown_for_stale_app(
        self,
    ) -> None:
        class FakeResponse:
            def __init__(self, payload: dict) -> None:
                self.status = 200
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        responses = (
            FakeResponse({"csrf_token": "csrf-token"}),
            FakeResponse({"accepted": True}),
        )
        with patch(
            "run_local_web.urllib.request.urlopen",
            side_effect=responses,
        ) as urlopen:
            self.assertTrue(
                request_existing_app_shutdown("session-token")
            )

        shutdown_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(shutdown_request.get_method(), "POST")
        self.assertTrue(
            shutdown_request.full_url.endswith(
                "/api/application/shutdown"
            )
        )
        self.assertEqual(
            shutdown_request.get_header("Authorization"),
            "Bearer session-token",
        )
        self.assertEqual(
            shutdown_request.get_header("X-csrf-token"),
            "csrf-token",
        )

    def test_launcher_waits_for_port_release_after_shutdown(self) -> None:
        reserved_socket = object()
        with (
            patch(
                "run_local_web.reserve_local_socket",
                side_effect=(OSError(), reserved_socket),
            ),
            patch("run_local_web.time.sleep") as sleep,
        ):
            result = reserve_socket_after_shutdown()

        self.assertIs(result, reserved_socket)
        sleep.assert_called_once_with(0.1)

    def test_launcher_reuses_fresh_app_when_restart_races(self) -> None:
        with (
            patch("run_local_web.ensure_standard_streams"),
            patch(
                "run_local_web.reserve_local_socket",
                side_effect=OSError(),
            ),
            patch(
                "run_local_web.load_session_token",
                side_effect=("old-token", "fresh-token"),
            ),
            patch(
                "run_local_web.read_existing_build_id",
                return_value="stale-build",
            ),
            patch(
                "run_local_web.request_existing_app_shutdown",
                return_value=True,
            ),
            patch(
                "run_local_web.reserve_socket_after_shutdown",
                return_value=None,
            ),
            patch(
                "run_local_web.existing_app_is_running",
                return_value=True,
            ) as app_is_running,
            patch("run_local_web.webbrowser.open") as open_browser,
            patch("run_local_web.show_startup_error") as startup_error,
        ):
            result = run_local_web_main()

        self.assertEqual(result, 0)
        app_is_running.assert_called_once_with("fresh-token")
        open_browser.assert_called_once_with(
            "http://127.0.0.1:8765/#fresh-token"
        )
        startup_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
