import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app.codex_sync import (
    CodexProfileSession,
    CodexReloginRequired,
    CodexSessionError,
    merge_sparse_dict,
)
from app.otp_codex_manager_with_account_status import (
    CodexInfo,
    OTPManagerApp,
    ensure_codex_profile,
    find_codex_executable,
    protect_sensitive_path,
    requires_codex_relogin,
)


FAKE_APP_SERVER = textwrap.dedent(
    r"""
    import json
    import sys

    for raw_line in sys.stdin:
        message = json.loads(raw_line)
        method = message.get("method")
        message_id = message.get("id")

        if method == "initialize":
            print(json.dumps({"id": message_id, "result": {}}), flush=True)
        elif method == "initialized":
            print(json.dumps({
                "method": "account/updated",
                "params": {"authMode": "chatgpt", "planType": "plus"},
            }), flush=True)
        elif method == "account/read":
            print(json.dumps({
                "id": message_id,
                "result": {
                    "account": {
                        "type": "chatgpt",
                        "email": "user@example.com",
                        "planType": "plus",
                    },
                    "requiresOpenaiAuth": True,
                },
            }), flush=True)
        elif method == "account/rateLimits/read":
            print(json.dumps({
                "id": message_id,
                "result": {
                    "rateLimits": {
                        "primary": {
                            "usedPercent": 25,
                            "windowDurationMins": 300,
                            "resetsAt": 1893456000,
                        },
                        "secondary": {
                            "usedPercent": 40,
                            "windowDurationMins": 10080,
                            "resetsAt": 1894060800,
                        },
                    },
                },
            }), flush=True)
    """
)


FAKE_LOGGED_OUT_SERVER = textwrap.dedent(
    r"""
    import json
    import sys

    for raw_line in sys.stdin:
        message = json.loads(raw_line)
        method = message.get("method")
        message_id = message.get("id")

        if method == "initialize":
            print(json.dumps({"id": message_id, "result": {}}), flush=True)
        elif method == "initialized":
            print(json.dumps({
                "method": "account/updated",
                "params": {"authMode": None, "planType": None},
            }), flush=True)
        elif method == "account/read":
            print(json.dumps({
                "id": message_id,
                "result": {
                    "account": None,
                    "requiresOpenaiAuth": True,
                },
            }), flush=True)
    """
)


FAKE_HANGING_SERVER = textwrap.dedent(
    r"""
    import json
    import sys

    print("SENTINEL_SECRET_TOKEN", file=sys.stderr, flush=True)

    for raw_line in sys.stdin:
        message = json.loads(raw_line)
        if message.get("method") == "initialize":
            print(json.dumps({
                "id": message.get("id"),
                "result": {},
            }), flush=True)
    """
)


class CodexExecutableTests(unittest.TestCase):
    def test_prefers_runnable_standalone_install_over_path_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            standalone = (
                local_app_data
                / "Programs"
                / "OpenAI"
                / "Codex"
                / "bin"
                / "codex.exe"
            )
            standalone.parent.mkdir(parents=True)
            standalone.touch()

            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=False,
            ), mock.patch(
                "app.otp_codex_manager_with_account_status.shutil.which",
                return_value=r"C:\Program Files\WindowsApps\OpenAI.Codex\codex.exe",
            ):
                self.assertEqual(
                    find_codex_executable(),
                    str(standalone.resolve()),
                )

    def test_rejects_untrusted_command_shim_from_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shim = root / "codex.cmd"
            shim.touch()

            def fake_which(name: str) -> str | None:
                if name.startswith("codex"):
                    return str(shim)
                return None

            with mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": str(root / "local"),
                    "APPDATA": str(root),
                },
                clear=False,
            ), mock.patch(
                "app.otp_codex_manager_with_account_status.shutil.which",
                side_effect=fake_which,
            ):
                self.assertIsNone(find_codex_executable())

    def test_rejects_command_shim_even_inside_trusted_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            trusted_bin = (
                local_app_data
                / "Programs"
                / "OpenAI"
                / "Codex"
                / "bin"
            )
            trusted_bin.mkdir(parents=True)
            shim = trusted_bin / "codex.cmd"
            shim.touch()

            def fake_which(name: str) -> str | None:
                return str(shim) if name == "codex" else None

            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=False,
            ), mock.patch(
                "app.otp_codex_manager_with_account_status.shutil.which",
                side_effect=fake_which,
            ):
                self.assertIsNone(find_codex_executable())


class ProfileConfigurationTests(unittest.TestCase):
    def test_ensure_profile_replaces_non_file_credential_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "profile"
            profile_dir.mkdir()
            config_file = profile_dir / "config.toml"
            config_file.write_text(
                'model = "gpt-5.5"\n'
                'cli_auth_credentials_store = "keyring"\n'
                'cli_auth_credentials_store = "auto"\n',
                encoding="utf-8",
            )

            ensure_codex_profile(profile_dir)

            content = config_file.read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.5"', content)
            self.assertEqual(
                content.count('cli_auth_credentials_store = "file"'),
                1,
            )
            self.assertNotIn('"keyring"', content)
            self.assertNotIn('"auto"', content)

    def test_credential_store_stays_at_toml_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "profile"
            profile_dir.mkdir()
            config_file = profile_dir / "config.toml"
            config_file.write_text(
                '[features]\n'
                'multi_agent = true\n',
                encoding="utf-8",
            )

            ensure_codex_profile(profile_dir)

            content = config_file.read_text(encoding="utf-8")
            self.assertLess(
                content.index('cli_auth_credentials_store = "file"'),
                content.index("[features]"),
            )


@unittest.skipUnless(os.name == "nt", "Windows ACL only")
class SensitiveFilePermissionTests(unittest.TestCase):
    def test_sensitive_file_acl_only_allows_user_and_system(self) -> None:
        import win32api
        import win32con
        import win32security

        with tempfile.TemporaryDirectory() as temp_dir:
            sensitive_file = Path(temp_dir) / "auth.json"
            sensitive_file.write_text("placeholder", encoding="utf-8")

            protect_sensitive_path(sensitive_file)

            descriptor = win32security.GetFileSecurity(
                str(sensitive_file),
                win32security.DACL_SECURITY_INFORMATION,
            )
            dacl = descriptor.GetSecurityDescriptorDacl()
            actual_sids = {
                win32security.ConvertSidToStringSid(
                    dacl.GetAce(index)[2]
                )
                for index in range(dacl.GetAceCount())
            }
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32con.TOKEN_QUERY,
            )
            current_user_sid = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )[0]
            expected_sids = {
                win32security.ConvertSidToStringSid(current_user_sid),
                win32security.ConvertSidToStringSid(
                    win32security.CreateWellKnownSid(
                        win32security.WinLocalSystemSid,
                        None,
                    )
                ),
            }

            self.assertEqual(actual_sids, expected_sids)


class AccountIsolationTests(unittest.TestCase):
    def test_email_mismatch_quarantines_quota(self) -> None:
        app = object.__new__(OTPManagerApp)
        app.codex_info = {
            "stored@example.com": CodexInfo(
                stored_email="stored@example.com",
                remaining_percent="80%",
                cycle="Weekly",
                reset_at="01/01 12:00",
                plan_type="Plus",
                account_state="Hoạt động bình thường",
                status="Đã đồng bộ",
            )
        }
        app.codex_relogin_required = set()
        app.update_codex_row = mock.Mock()

        app.apply_codex_result(
            "stored@example.com",
            {
                "account": {
                    "account": {
                        "type": "chatgpt",
                        "email": "other@example.com",
                        "planType": "plus",
                    }
                },
                "limits": {
                    "rateLimits": {
                        "secondary": {
                            "usedPercent": 10,
                            "windowDurationMins": 10080,
                            "resetsAt": 1894060800,
                        }
                    }
                },
            },
        )

        info = app.codex_info["stored@example.com"]
        self.assertEqual(info.remaining_percent, "—")
        self.assertEqual(info.cycle, "—")
        self.assertEqual(info.reset_at, "—")
        self.assertEqual(info.plan_type, "—")
        self.assertEqual(info.account_state, "Sai tài khoản Codex")
        self.assertIn("stored@example.com", app.codex_relogin_required)


class ErrorClassificationTests(unittest.TestCase):
    def test_generic_internal_error_is_temporary(self) -> None:
        self.assertFalse(
            requires_codex_relogin(
                "{'code': -32603, 'message': 'failed to fetch rate limits'}"
            )
        )

    def test_explicit_refresh_token_error_requires_login(self) -> None:
        self.assertTrue(
            requires_codex_relogin("invalid_grant: refresh token expired")
        )


class SparseMergeTests(unittest.TestCase):
    def test_sparse_notification_does_not_erase_existing_values(self) -> None:
        current = {
            "rateLimits": {
                "primary": {"usedPercent": 20, "resetsAt": 100},
                "secondary": {"usedPercent": 40, "resetsAt": 200},
            },
            "spendControlReached": False,
        }
        update = {
            "rateLimits": {
                "primary": {"usedPercent": 25},
            },
            "spendControlReached": None,
        }

        merged = merge_sparse_dict(current, update)

        self.assertEqual(
            merged["rateLimits"]["primary"],
            {"usedPercent": 25, "resetsAt": 100},
        )
        self.assertEqual(
            merged["rateLimits"]["secondary"],
            {"usedPercent": 40, "resetsAt": 200},
        )
        self.assertFalse(merged["spendControlReached"])
        self.assertEqual(current["rateLimits"]["primary"]["usedPercent"], 20)


class PersistentSessionTests(unittest.TestCase):
    def test_reuses_one_app_server_process_for_multiple_queries(self) -> None:
        events: list[tuple[str, dict]] = []
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[sys.executable, "-u", "-c", FAKE_APP_SERVER],
            environment=os.environ.copy(),
            notification_handler=lambda event, payload: events.append(
                (event, payload)
            ),
            timeout_seconds=3,
        )

        try:
            first = session.query()
            first_pid = session.process_id
            second = session.query()

            self.assertIsNotNone(first_pid)
            self.assertEqual(session.process_id, first_pid)
            self.assertEqual(
                first["account"]["account"]["email"],
                "user@example.com",
            )
            self.assertEqual(first, second)

            deadline = time.monotonic() + 1
            while not events and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertIn(
                "account_updated",
                [event for event, _ in events],
            )
        finally:
            session.close()

    def test_sparse_account_update_without_auth_mode_is_not_logout(self) -> None:
        events: list[tuple[str, dict]] = []
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[sys.executable, "-c", "pass"],
            environment=os.environ.copy(),
            notification_handler=lambda event, payload: events.append(
                (event, payload)
            ),
        )

        session._handle_message(
            {
                "method": "account/updated",
                "params": {"planType": "pro"},
            }
        )

        self.assertNotIn(
            "relogin_required",
            [event for event, _ in events],
        )
        self.assertIn(
            "account_updated",
            [event for event, _ in events],
        )

    def test_close_unblocks_a_pending_request_immediately(self) -> None:
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[
                sys.executable,
                "-u",
                "-c",
                FAKE_HANGING_SERVER,
            ],
            environment=os.environ.copy(),
            timeout_seconds=10,
        )
        errors: list[Exception] = []

        def query() -> None:
            try:
                session.query()
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=query)
        worker.start()
        deadline = time.monotonic() + 2

        while session.process_id is None and time.monotonic() < deadline:
            time.sleep(0.01)

        started = time.monotonic()
        session.close()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], CodexSessionError)

    def test_timeout_does_not_expose_app_server_stderr(self) -> None:
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[
                sys.executable,
                "-u",
                "-c",
                FAKE_HANGING_SERVER,
            ],
            environment=os.environ.copy(),
            timeout_seconds=0.1,
        )

        try:
            with self.assertRaises(CodexSessionError) as context:
                session.query()

            self.assertNotIn(
                "SENTINEL_SECRET_TOKEN",
                str(context.exception),
            )
        finally:
            session.close()

    def test_account_update_refreshes_cached_plan_for_realtime_quota(self) -> None:
        events: list[tuple[str, dict]] = []
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[sys.executable, "-c", "pass"],
            environment=os.environ.copy(),
            notification_handler=lambda event, payload: events.append(
                (event, payload)
            ),
        )
        session._cached_account = {
            "account": {
                "type": "chatgpt",
                "email": "user@example.com",
                "planType": "plus",
            },
            "requiresOpenaiAuth": True,
        }
        session._cached_limits = {
            "rateLimits": {
                "primary": {"usedPercent": 20},
            }
        }

        session._handle_message(
            {
                "method": "account/updated",
                "params": {
                    "authMode": "chatgpt",
                    "planType": "pro",
                },
            }
        )
        session._handle_message(
            {
                "method": "account/rateLimits/updated",
                "params": {
                    "rateLimits": {
                        "primary": {"usedPercent": 25},
                    }
                },
            }
        )

        realtime_payloads = [
            payload
            for event, payload in events
            if event == "rate_limits_updated"
        ]
        self.assertEqual(
            realtime_payloads[-1]["account"]["account"]["planType"],
            "pro",
        )

    def test_stale_process_response_cannot_complete_new_request(self) -> None:
        import queue

        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[sys.executable, "-c", "pass"],
            environment=os.environ.copy(),
        )
        response_queue: queue.Queue = queue.Queue()
        session._process_generation = 2
        session._pending[99] = (2, response_queue)

        session._handle_message(
            {"id": 99, "result": {"source": "old"}},
            generation=1,
        )

        self.assertTrue(response_queue.empty())

    def test_stopped_process_notification_is_ignored(self) -> None:
        events: list[tuple[str, dict]] = []
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[sys.executable, "-u", "-c", FAKE_APP_SERVER],
            environment=os.environ.copy(),
            notification_handler=lambda event, payload: events.append(
                (event, payload)
            ),
            timeout_seconds=3,
        )

        try:
            session.query()
            old_generation = session._process_generation
            events.clear()
            session.restart()
            session._handle_message(
                {
                    "method": "account/updated",
                    "params": {
                        "authMode": None,
                        "planType": None,
                    },
                },
                generation=old_generation,
            )

            self.assertEqual(events, [])
        finally:
            session.close()

    def test_account_null_is_authoritative_relogin_state(self) -> None:
        events: list[tuple[str, dict]] = []
        session = CodexProfileSession(
            profile_dir=Path.cwd(),
            command=[
                sys.executable,
                "-u",
                "-c",
                FAKE_LOGGED_OUT_SERVER,
            ],
            environment=os.environ.copy(),
            notification_handler=lambda event, payload: events.append(
                (event, payload)
            ),
            timeout_seconds=3,
        )

        try:
            with self.assertRaises(CodexReloginRequired):
                session.query()

            deadline = time.monotonic() + 1
            while not events and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertIn(
                "relogin_required",
                [event for event, _ in events],
            )
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
