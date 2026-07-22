import os
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.local_web_app import create_app
from app.local_web_service import LocalWebService, account_display_sort_key
from run_local_web import reserve_local_socket


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

    def tearDown(self) -> None:
        self.client.close()
        self.service.close()
        self.temp_dir.cleanup()

    def test_security_headers_and_local_health(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
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

    def test_import_state_and_sensitive_values_are_separated(self) -> None:
        response = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
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
        first = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|JBSWY3DPEHPK3PXP"
                )
            },
        )
        duplicate = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|JBSWY3DPEHPK3PXP"
                )
            },
        )
        update = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|new-password|JBSWY3DPEHPK3PXQ"
                )
            },
        )
        conflict = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "other@example.com|password|JBSWY3DPEHPK3PXQ\n"
                    "invalid-line"
                )
            },
        )

        self.assertEqual(first.json()["added"], 1)
        self.assertEqual(duplicate.json()["duplicates"], 1)
        self.assertEqual(update.json()["updated"], 1)
        self.assertEqual(len(conflict.json()["errors"]), 2)

    def test_invalid_sensitive_field_does_not_echo_input(self) -> None:
        import_response = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
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
        self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={
                "lines": (
                    "user@example.com|password|"
                    "JBSWY3DPEHPK3PXP"
                )
            },
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


if __name__ == "__main__":
    unittest.main()
