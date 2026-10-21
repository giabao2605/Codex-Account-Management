"""Temporary-data regressions for stable account and Codex profile identities."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from app import otp_codex_manager_with_account_status as manager
from app.local_web_service import LocalWebService
from app.local_web_profiles import UnsafeProfilePathError
from tests.test_codex_sync import FAKE_APP_SERVER


TOTP_FIXTURE = "JBSWY3DPEHPK3PXP"
OTHER_TOTP_FIXTURE = "KRUGS4ZANFZSAYJA"


class AccountIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = self.new_service()
        self.service.start()

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def new_service(self) -> LocalWebService:
        return LocalWebService(
            data_file=self.root / "accounts.json",
            profiles_dir=self.root / "codex_profiles",
            enable_codex=False,
        )

    def add_account(self, email="old@example.com", secret=TOTP_FIXTURE) -> str:
        self.service.import_accounts(f"{email}|password|{secret}")
        return self.service.account_id(email)

    def write_legacy(self) -> bytes:
        payload = {"version": 1, "accounts": [{
            "email": manager.encrypt_text("old@example.com"),
            "password": manager.encrypt_text("password"),
            "secret": manager.encrypt_text("JBSWY3DPEHPK3PXP"),
            "plus_expires_at": manager.encrypt_text("2027-01-10"),
        }]}
        self.service.data_file.write_text(json.dumps(payload), encoding="utf-8")
        return self.service.data_file.read_bytes()

    def restart(self) -> None:
        self.service.close()
        self.service = self.new_service()
        self.service.start()

    def test_legacy_migration_keeps_bytes_id_profile_and_history_until_save(self) -> None:
        original_bytes = self.write_legacy()
        legacy_id = hashlib.sha256(b"old@example.com").hexdigest()[:16]
        legacy_profile = self.service.profiles_dir / manager.profile_directory_for("old@example.com").name
        legacy_profile.mkdir()
        (legacy_profile / "history.jsonl").write_text("history", encoding="utf-8")
        self.restart()
        self.assertEqual(self.service.data_file.read_bytes(), original_bytes)
        self.assertEqual(self.service.account_id("old@example.com"), legacy_id)
        self.assertEqual(self.service.profile_directory("old@example.com"), legacy_profile)
        result = self.service.update_email(legacy_id, "new@example.com")
        self.assertEqual(result["id"], legacy_id)
        saved = json.loads(self.service.data_file.read_text(encoding="utf-8"))["accounts"][0]
        self.assertEqual(saved["account_id"], legacy_id)
        self.assertEqual(manager.decrypt_text(saved["profile_name"]), legacy_profile.name)
        self.assertNotEqual(saved["profile_name"], legacy_profile.name)
        self.restart()
        self.assertEqual(self.service.account_id("new@example.com"), legacy_id)
        self.assertEqual(self.service.profile_directory("new@example.com"), legacy_profile)
        self.assertEqual((legacy_profile / "history.jsonl").read_text(encoding="utf-8"), "history")
        self.assertEqual(self.service.sensitive_value(legacy_id, "password"), "password")
        self.assertEqual(self.service.sensitive_value(legacy_id, "secret"), "JBSWY3DPEHPK3PXP")
        self.assertEqual(self.service._load_accounts()[0].plus_expires_at, date(2027, 1, 10))

    def test_new_identity_does_not_contain_email_and_survives_repeated_rename(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        self.assertRegex(account_id, r"^[0-9a-f]{16}$")
        self.assertEqual(profile.name, f"profile_{account_id}")
        for email in ("new@example.com", "third@example.com", "old@example.com"):
            result = self.service.update_email(account_id, email)
            self.assertEqual(result["id"], account_id)
            self.assertEqual(self.service.profile_directory(email), profile)
        self.restart()
        self.assertEqual(self.service.account_id("old@example.com"), account_id)
        self.assertEqual(self.service.profile_directory("old@example.com"), profile)

    def test_reimport_original_email_cannot_adopt_renamed_legacy_profile(self) -> None:
        self.write_legacy()
        self.restart()
        original_id = self.service.account_id("old@example.com")
        original_profile = self.service.profile_directory("old@example.com")
        original_profile.mkdir()
        (original_profile / "history.jsonl").write_text("keep", encoding="utf-8")
        self.service.update_email(original_id, "new@example.com")
        replacement_id = self.add_account(secret=OTHER_TOTP_FIXTURE)
        self.assertNotEqual(replacement_id, original_id)
        self.assertNotEqual(self.service.profile_directory("old@example.com"), original_profile)
        self.assertEqual(self.service.profile_directory("new@example.com"), original_profile)
        self.service.delete_account(replacement_id)
        self.assertTrue(original_profile.is_dir())
        self.assertEqual((original_profile / "history.jsonl").read_text(encoding="utf-8"), "keep")

    def test_permission_denied_atomic_write_leaves_account_and_profile_unchanged(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        profile.mkdir()
        (profile / "history.jsonl").write_text("keep", encoding="utf-8")
        original_bytes = self.service.data_file.read_bytes()
        with patch.object(Path, "replace", side_effect=PermissionError("access denied")):
            with self.assertRaises(OSError) as raised:
                self.service.update_email(account_id, "new@example.com")
        self.assertNotIn("Windows đang khóa", str(raised.exception))
        self.assertEqual(self.service.data_file.read_bytes(), original_bytes)
        self.assertEqual(self.service.state()["accounts"][0]["email"], "old@example.com")
        self.assertEqual(self.service.profile_directory("old@example.com"), profile)
        self.assertEqual((profile / "history.jsonl").read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(self.root.glob(".accounts.json.*.tmp")), [])

    def test_mismatch_quarantines_quota_preserving_credentials_expiry_and_profile(self) -> None:
        account_id = self.add_account()
        self.service.update_plus_expiration(account_id, "2027-01-10")
        profile = self.service.profile_directory("old@example.com")
        profile.mkdir()
        (profile / "history.jsonl").write_text("keep", encoding="utf-8")
        self.service._codex_info["old@example.com"] = manager.CodexInfo(
            stored_email="old@example.com", codex_email="old@example.com",
            plan_type="Plus", remaining_percent="80%", account_state="Hoạt động bình thường",
        )
        self.service.update_email(account_id, "new@example.com")
        immediate = self.service.state()["accounts"][0]
        self.assertEqual(immediate["account_state"], "Sai tài khoản Codex")
        self.assertEqual(immediate["quota_remaining"], "—")
        self.assertEqual(immediate["plan_type"], "—")
        self.service._apply_codex_result("new@example.com", {
            "account": {"account": {"email": "old@example.com", "planType": "plus"}},
            "limits": {},
        })
        row = self.service.state()["accounts"][0]
        self.assertEqual(row["account_state"], "Sai tài khoản Codex")
        self.assertEqual(row["quota_remaining"], "—")
        self.assertEqual(row["plan_type"], "—")
        self.assertEqual(row["plus_expires_at"], "2027-01-10")
        self.assertEqual(self.service.sensitive_value(account_id, "password"), "password")
        self.assertEqual(self.service.sensitive_value(account_id, "secret"), "JBSWY3DPEHPK3PXP")
        self.assertEqual(self.service.profile_directory("new@example.com"), profile)
        self.assertEqual((profile / "history.jsonl").read_text(encoding="utf-8"), "keep")

    def test_correcting_mismatched_label_allows_existing_profile_to_sync(self) -> None:
        account_id = self.add_account()
        self.service._codex_info["old@example.com"] = manager.CodexInfo(
            stored_email="old@example.com", codex_email="actual@example.com",
            account_state="Sai tài khoản Codex", status="Email Codex khác",
        )
        self.service._relogin_required.add("old@example.com")
        self.service.update_email(account_id, "actual@example.com")
        self.assertNotIn("actual@example.com", self.service._relogin_required)
        self.assertNotEqual(self.service.state()["accounts"][0]["account_state"], "Sai tài khoản Codex")

    def test_queued_old_refresh_cannot_start_session_after_rename(self) -> None:
        account_id = self.add_account()
        old_account = self.service._accounts[0]
        profile = self.service.profile_directory("old@example.com")
        profile.mkdir()
        (profile / "auth.json").touch()
        self.service.update_email(account_id, "new@example.com")
        with patch.object(self.service, "_get_session") as get_session:
            self.assertEqual(self.service._refresh_account(old_account), "unlinked")
        get_session.assert_not_called()
        self.assertNotIn("old@example.com", self.service._codex_info)

    def test_legacy_desktop_round_trip_preserves_web_identity(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        self.service.update_email(account_id, "new@example.com")
        desktop = manager.OTPManagerApp.__new__(manager.OTPManagerApp)
        desktop.accounts = []
        desktop.status_label = Mock()
        desktop.rebuild_table = Mock()
        desktop.sync_codex_rows = Mock()
        with patch.object(manager, "DATA_FILE", self.service.data_file), patch.object(manager.messagebox, "showerror") as showerror:
            desktop.load_accounts_from_disk()
            self.assertEqual(len(desktop.accounts), 1)
            desktop.save_accounts_to_disk()
        showerror.assert_not_called()
        self.restart()
        self.assertEqual(self.service.account_id("new@example.com"), account_id)
        self.assertEqual(self.service.profile_directory("new@example.com"), profile)

    def test_rename_ignores_denied_profile_access_and_never_attempts_profile_move(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        profile.mkdir()
        (profile / "history.jsonl").write_text("keep", encoding="utf-8")
        real_replace = os.replace

        def deny_profile_move(source, destination, *args, **kwargs):
            if Path(source) == profile:
                raise PermissionError("profile ACL denies rename")
            return real_replace(source, destination, *args, **kwargs)

        with patch("app.local_web_service.validate_direct_profile_directory",
                   side_effect=PermissionError("profile access denied")) as validate, patch(
                       "app.local_web_service.os.replace", side_effect=deny_profile_move,
                   ):
            result = self.service.update_email(account_id, "new@example.com")
        validate.assert_not_called()
        self.assertEqual(result["id"], account_id)
        self.assertEqual(self.service.profile_directory("new@example.com"), profile)
        self.assertEqual((profile / "history.jsonl").read_text(encoding="utf-8"), "keep")

    def test_corrupt_encrypted_profile_metadata_does_not_silently_drop_account(self) -> None:
        self.add_account()
        original = self.service.data_file.read_text(encoding="utf-8")
        for corrupt in ("invalid encrypted profile", 12, None, ""):
            payload = json.loads(original)
            payload["accounts"][0]["profile_name"] = corrupt
            self.service.data_file.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(profile_name=corrupt), self.assertRaises(ValueError):
                self.service._load_accounts()

    def test_running_app_server_stops_and_relinks_on_same_profile(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        profile.mkdir()
        (profile / "auth.json").touch()
        (profile / "history.jsonl").write_text("keep", encoding="utf-8")
        command = [sys.executable, "-u", "-c", FAKE_APP_SERVER.replace("user@example.com", "old@example.com")]
        with patch("app.local_web_service.build_codex_command", return_value=command):
            session = self.service._get_session("old@example.com", profile)
            result = session.query()
            self.service._apply_codex_result("old@example.com", result)
        process = session._process
        self.assertIsNotNone(process)
        self.assertIsNone(process.poll())
        self.assertEqual(self.service.state()["accounts"][0]["quota_remaining"], "60%")
        result = self.service.update_email(account_id, "new@example.com")
        self.assertIsNotNone(process.poll())
        self.assertEqual(result["id"], account_id)
        self.assertEqual(self.service.profile_directory("new@example.com"), profile)
        self.assertTrue((profile / "auth.json").exists())
        self.assertEqual((profile / "history.jsonl").read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.service.state()["accounts"][0]["account_state"], "Sai tài khoản Codex")

        self.service.enable_codex = True
        login_process = Mock()
        login_process.wait.return_value = 0
        with patch("app.local_web_service.build_codex_command", return_value=["fake-codex", "login"]), patch(
            "app.local_web_service.subprocess.Popen", return_value=login_process,
        ) as popen, patch("app.local_web_service.threading.Thread") as waiter, patch.object(
            self.service, "refresh_async", return_value=False,
        ) as refresh:
            self.service.login(account_id)
            self.assertEqual(popen.call_args.kwargs["env"]["CODEX_HOME"], str(profile))
            waiter.call_args.kwargs["target"]()
            refresh.assert_called_once_with({account_id})
        command = [sys.executable, "-u", "-c", FAKE_APP_SERVER.replace("user@example.com", "new@example.com")]
        with patch("app.local_web_service.build_codex_command", return_value=command):
            self.assertEqual(self.service._refresh_account(self.service._accounts[0]), "success")
        row = self.service.state()["accounts"][0]
        self.assertEqual(row["id"], account_id)
        self.assertEqual(row["account_state"], "Hoạt động bình thường")
        self.assertEqual(row["quota_remaining"], "60%")
        self.assertEqual((profile / "history.jsonl").read_text(encoding="utf-8"), "keep")

    def test_old_session_notifications_cannot_change_reimported_email(self) -> None:
        account_id = self.add_account()
        profile = self.service.profile_directory("old@example.com")
        with patch("app.local_web_service.build_codex_command", return_value=["fake-codex", "app-server"]):
            old_session = self.service._get_session("old@example.com", profile)
        old_handler = old_session.notification_handler
        self.assertIsNotNone(old_handler)
        self.service.update_email(account_id, "new@example.com")
        replacement_id = self.add_account(secret=OTHER_TOTP_FIXTURE)
        before = self.service._codex_info["old@example.com"]
        for event_type, payload in (
            ("relogin_required", {}), ("account_updated", {}), ("server_stopped", {}),
            ("rate_limits_updated", {"account": {"account": {"email": "intruder@example.com"}}}),
        ):
            old_handler(event_type, payload)
        self.assertEqual(self.service._codex_info["old@example.com"], before)
        self.assertNotIn("old@example.com", self.service._relogin_required)
        self.assertNotEqual(replacement_id, account_id)

    def test_import_refuses_occupied_random_profile_without_overwrite(self) -> None:
        self.add_account()
        original_bytes = self.service.data_file.read_bytes()
        identifier = "a" * 16
        destination = self.service.profiles_dir / f"profile_{identifier}"
        destination.mkdir()
        marker = destination / "history.jsonl"
        marker.write_text("keep", encoding="utf-8")
        with patch("app.local_web_accounts.new_account_identity", return_value=(identifier, destination.name)):
            with self.assertRaises(UnsafeProfilePathError):
                self.add_account("other@example.com", "KRUGS4ZANFZSAYJA")
        self.assertEqual(self.service.data_file.read_bytes(), original_bytes)
        self.assertEqual(len(self.service.state()["accounts"]), 1)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_overlapping_renames_return_same_stable_account_id(self) -> None:
        account_id = self.add_account()
        nested_results = []

        def rename_during_refresh(account_ids):
            self.assertEqual(account_ids, {account_id})
            with patch.object(self.service, "refresh_async", return_value=False):
                nested_results.append(self.service.update_email(account_id, "third@example.com"))
            return False

        with patch.object(self.service, "refresh_async", side_effect=rename_during_refresh):
            result = self.service.update_email(account_id, "new@example.com")
        self.assertEqual(result["id"], account_id)
        self.assertEqual(nested_results[0]["id"], account_id)
        self.assertEqual(self.service.state()["accounts"][0]["email"], "third@example.com")

    def test_identity_helper_rejects_invalid_explicit_metadata(self) -> None:
        for stored_id, stored_profile in (
            ("../outside", "profile_safe"), ("A" * 16, "profile_safe"),
            ("a" * 16, "../outside"), ("a" * 16, "a/b"),
            ("a" * 16, "a\\b"), ("a" * 16, ".failover"),
            ("a" * 16, "C:\\outside"), (12, "profile_safe"),
            ("a" * 16, 12), ("", "profile_safe"),
            (None, "profile_safe"), ("a" * 16, None),
            ("a" * 16, "CON"), ("a" * 16, "profile."),
        ):
            with self.subTest(account_id=stored_id, profile=stored_profile):
                with self.assertRaises(ValueError):
                    manager.account_identity("old@example.com", stored_id, stored_profile)

    def test_invalid_metadata_on_disk_does_not_silently_drop_account(self) -> None:
        self.add_account()
        payload = json.loads(self.service.data_file.read_text(encoding="utf-8"))
        payload["accounts"][0]["account_id"] = "../outside"
        self.service.data_file.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.service._load_accounts()

    def test_duplicate_identity_or_profile_on_disk_is_rejected(self) -> None:
        self.add_account()
        self.add_account("other@example.com", "KRUGS4ZANFZSAYJA")
        original = self.service.data_file.read_text(encoding="utf-8")
        for field in ("account_id", "profile_name"):
            payload = json.loads(original)
            payload["accounts"][1][field] = payload["accounts"][0][field]
            self.service.data_file.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.service._load_accounts()


if __name__ == "__main__":
    unittest.main()
