import os
import json
import re
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.build_info import API_SCHEMA_VERSION, APP_BUILD_ID, BUILD_INPUTS
from app.local_web_accounts import AccountConflictError
from app.local_web_app import STATIC_ASSETS_DIR, create_app
from app.local_web_profiles import (
    UnsafeProfilePathError,
    archive_profile_directory,
)
from app.local_web_service import LocalWebService, account_display_sort_key
from app.otp_codex_manager_with_account_status import CodexInfo
from app.token_usage import TokenUsageCacheEntry, normalize_token_usage
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

    def add_account(self, lines: str):
        return self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"lines": lines},
        )

    def add_service_accounts(self, lines: str) -> None:
        for line in lines.splitlines():
            self.service.import_accounts(line)

    def tearDown(self) -> None:
        self.client.close()
        self.service.close()
        self.temp_dir.cleanup()

    def production_asset_text(self, suffix: str) -> str:
        self.assertIsNotNone(STATIC_ASSETS_DIR)
        matching_paths = [
            f"/assets/{path.name}"
            for path in sorted(
                STATIC_ASSETS_DIR.glob(f"*{suffix}"),
                key=lambda item: item.name,
            )
        ]
        self.assertTrue(matching_paths, suffix)
        contents = []
        for path in matching_paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            contents.append(response.text)
        return "\n".join(contents)

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
        state = self.client.get("/api/state").json()
        self.assertEqual(state["refresh_interval_seconds"], 60)
        self.assertIn(state["time_sync"]["status"], {
            "synced",
            "syncing",
            "degraded",
        })
        self.assertIn("offset_seconds", state["time_sync"])

    def test_runtime_token_module_participates_in_build_id(self) -> None:
        self.assertIn("app/token_usage.py", BUILD_INPUTS)

    def test_liquid_glass_phase1_parity_document_covers_baseline(
        self,
    ) -> None:
        baseline_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "liquid-glass-phase1-baseline-parity.md"
        )

        content = baseline_path.read_text(encoding="utf-8")

        for expected in (
            "API_SCHEMA_VERSION = 5",
            "TokenUsageResponse.schema_version = 2",
            "/api/usage/tokens",
            "Authorization: Bearer <session token>",
            "X-CSRF-Token",
            "sessionStorage",
            "daily_buckets: []",
            "daily_buckets: null",
            "otp-codex-theme",
            "tests/visual_baseline_app.py",
            "python -B -m unittest discover -s tests -v",
            "python -B -m unittest tests.test_visual_baseline -v",
            "node --check web\\app.js",
            "node --check web\\theme-init.js",
        ):
            self.assertIn(expected, content)

        self.assertNotRegex(content, r"Bearer\s+[A-Za-z0-9_-]{16,}")

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
        self.assertIn('<div id="app"></div>', response.text)
        self.assertNotRegex(response.text, r"https?://")
        self.assertNotRegex(
            response.text,
            r"<script(?![^>]*\bsrc=)[^>]*>",
        )
        asset_paths = re.findall(
            r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"',
            response.text,
        )
        self.assertGreaterEqual(len(asset_paths), 3)
        for asset_path in asset_paths:
            asset_response = self.client.get(asset_path)
            self.assertEqual(asset_response.status_code, 200, asset_path)
        script = self.production_asset_text(".js")
        self.assertIn("otp-codex-access-token", script)

    def test_frontend_supports_persistent_light_and_dark_themes(self) -> None:
        page = self.client.get("/").text
        init_script = self.client.get("/assets/theme-init.js")
        app_script = self.production_asset_text(".js")
        styles = self.production_asset_text(".css")

        self.assertEqual(init_script.status_code, 200)
        self.assertIn('content="light dark"', page)
        self.assertIn('src="/assets/theme-init.js"', page)
        self.assertIn('id="theme-color"', page)
        self.assertIn('otp-codex-theme', init_script.text)
        self.assertIn('window.localStorage', init_script.text)
        self.assertIn('prefers-color-scheme: light', init_script.text)
        self.assertIn('otp-codex-theme', app_script)
        self.assertIn('otp-codex-effects', app_script)
        self.assertIn('[data-theme=light]', styles)
        self.assertIn('--canvas:#dfe4eb', styles)
        self.assertIn('? "#dfe4eb"', init_script.text)
        self.assertIn("Giao diện", app_script)
        self.assertLess(
            page.index('src="/assets/theme-init.js"'),
            page.index('type="module"'),
        )

    def test_frontend_prioritizes_primary_actions_and_accessible_feedback(
        self,
    ) -> None:
        script = self.production_asset_text(".js")
        styles = self.production_asset_text(".css")

        for expected in (
            "Làm mới tất cả",
            "Thêm tài khoản",
            "Cần chú ý",
            "Quota thấp",
            "Chưa rõ quota",
            "Mật khẩu",
            "Secret",
            "Không có tài khoản phù hợp.",
            "Không thể kết nối ứng dụng local.",
        ):
            self.assertIn(expected, script)
        self.assertIn(".account-actions", styles)
        self.assertIn("overflow-wrap:anywhere", styles)

    def test_frontend_exposes_single_add_profile_shutdown_and_overview(
        self,
    ) -> None:
        script = self.production_asset_text(".js")

        self.assertIn("Thêm tài khoản", script)
        self.assertIn("Ngắt liên kết", script)
        self.assertIn("Đặt lại profile", script)
        self.assertIn("Tổng tài khoản", script)
        self.assertIn("thành công", script)
        self.assertIn("/api/accounts/import/check", script)
        self.assertIn("/api/accounts/import", script)
        self.assertIn("/api/codex/", script)
        self.assertIn("/api/profiles/orphans/archive", script)
        self.assertIn("/api/application/shutdown", script)
        self.assertGreaterEqual(script.count("confirm("), 2)

    def test_frontend_exposes_accessible_usage_statistics_tab(self) -> None:
        script = self.production_asset_text(".js")
        styles = self.production_asset_text(".css")

        for expected in (
            "Tài khoản",
            "Sử dụng",
            "Tất cả",
            "Ngày",
            "Tuần",
            "Tích lũy",
            "Token theo ngày",
            "12 tháng gần nhất",
        ):
            self.assertIn(expected, script)
        self.assertIn("force_token_usage", script)
        self.assertIn(".workspace-tabs", styles)
        self.assertIn(".heatmap", styles)
        self.assertIn(".heat-cell", styles)

    def test_frontend_keeps_profile_actions_with_overview_cards(
        self,
    ) -> None:
        script = self.production_asset_text(".js")

        self.assertIn("Ngắt liên kết", script)
        self.assertIn("Đặt lại profile", script)
        self.assertIn("profile mồ côi", script)

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

    def test_token_usage_endpoint_requires_auth_and_returns_safe_data(
        self,
    ) -> None:
        self.service.import_accounts(
            "usage@example.com|password|JBSWY3DPEHPK3PXP"
        )
        snapshot = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": 1_000,
                    "peakDailyTokens": 400,
                    "longestRunningTurnSec": 90,
                    "currentStreakDays": 2,
                    "longestStreakDays": 5,
                },
                "dailyUsageBuckets": [
                    {"startDate": date.today().isoformat(), "tokens": 25},
                ],
            },
            today=date.today(),
        )
        assert snapshot is not None
        with self.service._lock:
            self.service._token_usage_cache = {
                "usage@example.com": TokenUsageCacheEntry(
                    snapshot=snapshot,
                    last_attempt_monotonic=10.0,
                    updated_at=datetime.now(timezone.utc),
                    stale=False,
                )
            }

        response = self.client.get("/api/usage/tokens")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["coverage"]["fresh_accounts"], 1)
        self.assertEqual(payload["aggregate"]["totals"]["today"], 25)
        self.assertEqual(payload["accounts"][0]["email"], "usage@example.com")
        self.assertEqual(payload["accounts"][0]["longest_running_turn_seconds"], 90)
        self.assertEqual(payload["accounts"][0]["current_streak_days"], 2)
        self.assertEqual(payload["accounts"][0]["longest_streak_days"], 5)
        self.assertEqual(
            payload["accounts"][0]["daily_buckets"],
            [{"start_date": date.today().isoformat(), "tokens": 25}],
        )
        self.assertEqual(len(payload["aggregate"]["series"]["daily"]), 30)
        serialized = json.dumps(payload).casefold()
        for sensitive_name in (
            "password",
            "secret",
            "access_token",
            "csrf",
            "auth.json",
            "profile_dir",
            "otp",
        ):
            self.assertNotIn(sensitive_name, serialized)

        unauthenticated_client = TestClient(
            create_app(self.service),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51004),
        )
        try:
            self.assertEqual(
                unauthenticated_client.get("/api/usage/tokens").status_code,
                401,
            )
        finally:
            unauthenticated_client.close()

        state = self.client.get("/api/state").json()
        self.assertNotIn("dailyUsageBuckets", json.dumps(state))
        self.assertNotIn("token_activity", state)

    def test_manual_refresh_can_force_token_usage_refresh(self) -> None:
        with patch.object(
            self.service,
            "refresh_async",
            return_value=True,
        ) as refresh_async:
            response = self.client.post(
                "/api/codex/refresh",
                headers=self.headers,
                json={
                    "account_id": None,
                    "force_token_usage": True,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["accepted"])
        refresh_async.assert_called_once_with(
            None,
            force_token_usage=True,
        )

    def test_account_refresh_can_force_token_usage_refresh(self) -> None:
        account_id = "a" * 16
        with patch.object(
            self.service,
            "refresh_async",
            return_value=True,
        ) as refresh_async:
            response = self.client.post(
                "/api/codex/refresh",
                headers=self.headers,
                json={
                    "account_id": account_id,
                    "force_token_usage": True,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        refresh_async.assert_called_once_with(
            {account_id},
            force_token_usage=True,
        )

    def test_refresh_async_forwards_force_token_usage_to_worker(self) -> None:
        self.service.import_accounts(
            "worker@example.com|password|JBSWY3DPEHPK3PXP"
        )
        self.service.enable_codex = True

        with patch("app.local_web_service.threading.Thread") as thread_type:
            accepted = self.service.refresh_async(
                force_token_usage=True,
            )

        self.assertTrue(accepted)
        _, kwargs = thread_type.call_args
        self.assertEqual(kwargs["args"][1], True)
        self.assertEqual(len(kwargs["args"][0]), 1)
        thread_type.return_value.start.assert_called_once_with()
        self.service._sync_lock.release()

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
        self.add_service_accounts(
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
        self.add_service_accounts(
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

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                value = cls(2026, 7, 22, 12, 0)
                return value if tz is None else value.replace(tzinfo=tz)

        with patch("app.local_web_service.datetime", FixedDateTime):
            recommendation = self.client.get("/api/state").json()[
                "recommendation"
            ]

        self.assertEqual(recommendation["email"], "sooner@example.com")
        self.assertEqual(recommendation["quota_reset_at"], "23/07 10:00")

    def test_state_reports_usage_statistics_per_account_and_totals(
        self,
    ) -> None:
        self.add_service_accounts(
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

    def test_token_usage_cache_ttl_force_refresh_and_stale_fallback(
        self,
    ) -> None:
        session = Mock()
        session.read_token_usage.return_value = {
            "summary": {
                "lifetimeTokens": 500,
                "peakDailyTokens": 100,
            },
            "dailyUsageBuckets": [
                {"startDate": date.today().isoformat(), "tokens": 40},
            ],
        }

        with patch("app.local_web_service.time.monotonic", return_value=100.0):
            self.service._refresh_token_usage(
                "usage@example.com",
                session,
                force=False,
            )
        session.read_token_usage.assert_called_once_with()

        with patch("app.local_web_service.time.monotonic", return_value=200.0):
            self.service._refresh_token_usage(
                "usage@example.com",
                session,
                force=False,
            )
        session.read_token_usage.assert_called_once_with()

        session.read_token_usage.side_effect = RuntimeError("temporary")
        with patch("app.local_web_service.time.monotonic", return_value=210.0):
            self.service._refresh_token_usage(
                "usage@example.com",
                session,
                force=True,
            )

        self.assertEqual(session.read_token_usage.call_count, 2)
        with self.service._lock:
            cached = self.service._token_usage_cache["usage@example.com"]
        self.assertTrue(cached.stale)
        self.assertIsNotNone(cached.snapshot)
        assert cached.snapshot is not None
        self.assertEqual(dict(cached.snapshot.daily_tokens)[date.today()], 40)

    def test_token_usage_failure_does_not_discard_other_account_or_quota(
        self,
    ) -> None:
        self.add_service_accounts(
            "fresh@example.com|password|JBSWY3DPEHPK3PXP\n"
            "failed@example.com|password|JBSWY3DPEHPK3PXQ"
        )
        sessions = {}
        for account in self.service._accounts:
            profile_dir = self.service.profile_directory(account.email)
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "auth.json").touch()
            session = Mock()
            session.query.return_value = {
                "account": {
                    "account": {
                        "email": account.email,
                        "planType": "plus",
                    }
                },
                "limits": {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 25,
                            "windowDurationMins": 10_080,
                            "resetsAt": 1_893_456_000,
                        }
                    }
                },
            }
            sessions[account.email.casefold()] = session

        sessions["fresh@example.com"].read_token_usage.return_value = {
            "summary": {
                "lifetimeTokens": 500,
                "peakDailyTokens": 50,
            },
            "dailyUsageBuckets": [
                {"startDate": date.today().isoformat(), "tokens": 25}
            ],
        }
        sessions["failed@example.com"].read_token_usage.side_effect = (
            RuntimeError("temporary token failure")
        )

        with patch.object(
            self.service,
            "_get_session",
            side_effect=lambda key, _profile_dir: sessions[key],
        ):
            results = [
                self.service._refresh_account_locked(account)
                for account in self.service._accounts
            ]

        self.assertEqual(results, ["success", "success"])
        with self.service._lock:
            self.assertEqual(
                self.service._codex_info["fresh@example.com"].remaining_percent,
                "75%",
            )
            self.assertEqual(
                self.service._codex_info["failed@example.com"].remaining_percent,
                "75%",
            )
            self.assertIsNotNone(
                self.service._token_usage_cache["fresh@example.com"].snapshot
            )
            self.assertIsNone(
                self.service._token_usage_cache["failed@example.com"].snapshot
            )

    def test_deleting_account_clears_token_usage_cache(self) -> None:
        self.service.import_accounts(
            "delete-usage@example.com|password|JBSWY3DPEHPK3PXP"
        )
        key = "delete-usage@example.com"
        snapshot = normalize_token_usage(
            {"summary": {}, "dailyUsageBuckets": []},
            today=date.today(),
        )
        assert snapshot is not None
        with self.service._lock:
            self.service._token_usage_cache = {
                key: TokenUsageCacheEntry(
                    snapshot=snapshot,
                    last_attempt_monotonic=10.0,
                    updated_at=datetime.now(timezone.utc),
                    stale=False,
                )
            }

        self.service.delete_account(self.service.account_id(key))

        with self.service._lock:
            self.assertNotIn(key, self.service._token_usage_cache)

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

    def test_single_account_is_checked_inline_and_added_without_preview(
        self,
    ) -> None:
        lines = "user@example.com|password|JBSWY3DPEHPK3PXP"

        check = self.client.post(
            "/api/accounts/import/check",
            headers=self.headers,
            json={"lines": lines},
        )
        add = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"lines": lines},
        )

        self.assertEqual(check.status_code, 200, check.text)
        self.assertEqual(
            check.json(),
            {
                "valid": True,
                "conflict": None,
                "message": "Tài khoản có thể được thêm.",
            },
        )
        self.assertEqual(add.status_code, 200, add.text)
        self.assertEqual(
            add.json(),
            {"total": 1, "email": "user@example.com"},
        )
        self.assertEqual(
            self.service.state()["accounts"][0]["email"],
            "user@example.com",
        )

    def test_single_account_rejects_duplicate_email_and_secret(self) -> None:
        first = "user@example.com|password|JBSWY3DPEHPK3PXP"
        self.assertEqual(
            self.client.post(
                "/api/accounts/import",
                headers=self.headers,
                json={"lines": first},
            ).status_code,
            200,
        )

        duplicate_email = (
            "user@example.com|new-password|JBSWY3DPEHPK3PXQ"
        )
        duplicate_secret = (
            "other@example.com|password|JBSWY3DPEHPK3PXP"
        )
        email_check = self.client.post(
            "/api/accounts/import/check",
            headers=self.headers,
            json={"lines": duplicate_email},
        )
        secret_check = self.client.post(
            "/api/accounts/import/check",
            headers=self.headers,
            json={"lines": duplicate_secret},
        )
        email_add = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"lines": duplicate_email},
        )
        secret_add = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"lines": duplicate_secret},
        )

        self.assertEqual(email_check.status_code, 200, email_check.text)
        self.assertEqual(email_check.json()["conflict"], "email")
        self.assertEqual(secret_check.status_code, 200, secret_check.text)
        self.assertEqual(secret_check.json()["conflict"], "secret")
        self.assertEqual(email_add.status_code, 409)
        self.assertEqual(secret_add.status_code, 409)
        self.assertEqual(len(self.service.state()["accounts"]), 1)
        account_id = self.service.state()["accounts"][0]["id"]
        password = self.client.post(
            f"/api/accounts/{account_id}/sensitive",
            headers=self.headers,
            json={"field": "password"},
        )
        self.assertEqual(password.json()["value"], "password")

    def test_single_account_rejects_multiple_lines_and_removes_preview(
        self,
    ) -> None:
        lines = (
            "one@example.com|password|JBSWY3DPEHPK3PXP\n"
            "two@example.com|password|JBSWY3DPEHPK3PXQ"
        )

        check = self.client.post(
            "/api/accounts/import/check",
            headers=self.headers,
            json={"lines": lines},
        )
        add = self.client.post(
            "/api/accounts/import",
            headers=self.headers,
            json={"lines": lines},
        )
        preview = self.client.post(
            "/api/accounts/import/preview",
            headers=self.headers,
            json={"lines": lines},
        )

        self.assertEqual(check.status_code, 200, check.text)
        self.assertFalse(check.json()["valid"])
        self.assertEqual(check.json()["conflict"], "invalid")
        self.assertEqual(add.status_code, 400)
        self.assertEqual(preview.status_code, 404)
        self.assertEqual(self.service.state()["accounts"], [])

    def test_import_state_and_sensitive_values_are_separated(self) -> None:
        response = self.add_account(
            "user@example.com|password|JBSWY3DPEHPK3PXP",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"total": 1, "email": "user@example.com"},
        )

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

    def test_invalid_sensitive_field_does_not_echo_input(self) -> None:
        import_response = self.add_account(
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
        self.add_account(
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

    def test_concurrent_duplicate_adds_create_one_account(self) -> None:
        barrier = threading.Barrier(8)
        line = "same@example.com|password|JBSWY3DPEHPK3PXP"

        def add_same_account() -> bool:
            barrier.wait()
            try:
                self.service.import_accounts(line)
            except AccountConflictError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: add_same_account(), range(8)))

        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(self.service.state()["accounts"]), 1)

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
