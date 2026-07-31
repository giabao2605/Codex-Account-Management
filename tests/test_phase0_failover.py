import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.phase0_failover_probe as phase0_probe
from app.codex_sync import CodexSessionError
from app.phase0_failover_probe import (
    Phase0ProbeError,
    atomic_copy_auth,
    discover_profile_pair,
    is_usage_limit_event,
    main as probe_main,
    run_isolated_probe,
    synthetic_usage_limit_event,
    validate_profile_auth,
    write_phase0_hooks,
)
from app.phase0_hook_recorder import (
    main as hook_main,
    sanitize_hook_event,
)


class AtomicAuthCopyTests(unittest.TestCase):
    def test_atomic_copy_and_restore_preserve_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "a.json"
            source_b = root / "b.json"
            runner_auth = root / "runner" / "auth.json"
            backup = root / "runner" / "auth.backup"
            source_a.write_bytes(b"account-a-secret")
            source_b.write_bytes(b"account-b-secret")

            atomic_copy_auth(source_a, runner_auth)
            atomic_copy_auth(runner_auth, backup)
            atomic_copy_auth(source_b, runner_auth)
            self.assertEqual(runner_auth.read_bytes(), b"account-b-secret")

            atomic_copy_auth(backup, runner_auth)
            self.assertEqual(runner_auth.read_bytes(), b"account-a-secret")
            self.assertEqual(source_a.read_bytes(), b"account-a-secret")
            self.assertEqual(source_b.read_bytes(), b"account-b-secret")

    def test_rejects_reparse_auth_without_exposing_its_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "auth.json"
            destination = Path(temp_dir) / "runner" / "auth.json"
            source.write_bytes(b"SENTINEL_AUTH_SECRET")

            with mock.patch(
                "app.phase0_failover_probe.is_reparse_point",
                return_value=True,
            ):
                with self.assertRaises(Phase0ProbeError) as raised:
                    atomic_copy_auth(source, destination)

            self.assertNotIn("SENTINEL_AUTH_SECRET", str(raised.exception))

    def test_rejects_oversized_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "auth.json"
            destination = Path(temp_dir) / "runner" / "auth.json"
            source.write_bytes(b"12345")

            with mock.patch.object(phase0_probe, "MAX_AUTH_BYTES", 4):
                with self.assertRaises(Phase0ProbeError):
                    atomic_copy_auth(source, destination)

    def test_rejects_source_changed_after_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "auth.json"
            destination = Path(temp_dir) / "runner" / "auth.json"
            source.write_bytes(b"account-a")

            with mock.patch(
                "app.phase0_failover_probe.is_reparse_point",
                side_effect=[False, False, True],
            ):
                with self.assertRaisesRegex(
                    Phase0ProbeError,
                    "thay đổi",
                ):
                    atomic_copy_auth(source, destination)

            self.assertFalse(destination.exists())


class ProfileValidationTests(unittest.TestCase):
    def test_accepts_only_direct_profile_auth_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_root = Path(temp_dir) / "profiles"
            profile = profiles_root / "account_a"
            profiles_root.mkdir()
            profile.mkdir()
            auth_file = profile / "auth.json"
            auth_file.write_bytes(b"test")

            self.assertEqual(
                validate_profile_auth(profiles_root, profile),
                auth_file,
            )

            nested = profile / "nested"
            nested.mkdir()
            (nested / "auth.json").write_bytes(b"test")
            with self.assertRaises(Phase0ProbeError):
                validate_profile_auth(profiles_root, nested)


class HookSafetyTests(unittest.TestCase):
    def test_recorder_rejects_invalid_event_shapes(self) -> None:
        self.assertEqual(sanitize_hook_event("invalid"), {})
        self.assertEqual(
            sanitize_hook_event(
                {
                    "session_id": "thread-phase0",
                    "hook_event_name": "PreToolUse",
                }
            ),
            {},
        )
        self.assertEqual(
            sanitize_hook_event(
                {
                    "session_id": "thread-phase0",
                    "hook_event_name": "Stop",
                    "permission_mode": "unknown",
                }
            ),
            {
                "session_id": "thread-phase0",
                "hook_event_name": "Stop",
            },
        )
        self.assertEqual(
            sanitize_hook_event(
                {
                    "session_id": "thread-phase0",
                    "hook_event_name": "userPromptSubmit",
                }
            )["hook_event_name"],
            "UserPromptSubmit",
        )

    def test_recorder_keeps_metadata_and_drops_prompt_and_transcript(self) -> None:
        event = sanitize_hook_event(
            {
                "session_id": "thread-phase0",
                "turn_id": "turn-phase0",
                "cwd": "C:\\workspace",
                "hook_event_name": "UserPromptSubmit",
                "permission_mode": "dontAsk",
                "prompt": "SENTINEL_PROMPT_SECRET",
                "transcript_path": "C:\\secret\\transcript.jsonl",
                "last_assistant_message": "SENTINEL_ASSISTANT_SECRET",
            }
        )

        self.assertEqual(
            event,
            {
                "session_id": "thread-phase0",
                "turn_id": "turn-phase0",
                "cwd": "C:\\workspace",
                "hook_event_name": "UserPromptSubmit",
                "permission_mode": "dontAsk",
            },
        )
        self.assertNotIn("SENTINEL", str(event))

    def test_hook_config_contains_only_required_phase0_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = root / "runner"
            runner.mkdir()
            hook_log = runner / "hook-events.jsonl"

            config_file = write_phase0_hooks(
                runner=runner,
                hook_log=hook_log,
                python_executable=Path("C:\\Python\\python.exe"),
            )
            content = config_file.read_text(encoding="utf-8")

            self.assertIn('"SessionStart"', content)
            self.assertIn('"UserPromptSubmit"', content)
            self.assertIn('"Stop"', content)
            self.assertNotIn("bypass", content.casefold())
            self.assertNotIn("auth.json", content.casefold())

    def test_recorder_writes_only_sanitized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "hook-events.jsonl"
            payload = {
                "session_id": "thread-phase0",
                "turn_id": "turn-phase0",
                "cwd": str(root),
                "hook_event_name": "Stop",
                "permission_mode": "dontAsk",
                "last_assistant_message": "SENTINEL_ASSISTANT_SECRET",
            }
            stdin = io.TextIOWrapper(
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(
                stdout
            ):
                result = hook_main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue().strip(), "{}")
            saved = output.read_text(encoding="utf-8")
            self.assertIn("thread-phase0", saved)
            self.assertNotIn("SENTINEL", saved)

    def test_recorder_ignores_invalid_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root.parent / "hook-events.jsonl"
            payload = {
                "session_id": "thread-phase0",
                "hook_event_name": "Stop",
            }
            stdin = io.TextIOWrapper(
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                encoding="utf-8",
            )

            with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(
                io.StringIO()
            ):
                result = hook_main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(outside),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertFalse(outside.exists())

    def test_recorder_rejects_existing_reparse_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "hook-events.jsonl"
            output.write_text("", encoding="utf-8")
            payload = {
                "session_id": "thread-phase0",
                "hook_event_name": "Stop",
            }
            stdin = io.TextIOWrapper(
                io.BytesIO(json.dumps(payload).encode("utf-8")),
                encoding="utf-8",
            )

            with mock.patch(
                "pathlib.Path.is_symlink",
                return_value=True,
            ), mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(
                io.StringIO()
            ):
                result = hook_main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "")

    def test_recorder_fails_open_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "hook-events.jsonl"
            stdin = io.TextIOWrapper(
                io.BytesIO(b"not-json"),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(
                stdout
            ):
                result = hook_main(
                    [
                        "--root",
                        str(root),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue().strip(), "{}")
            self.assertFalse(output.exists())


class FakeSession:
    def __init__(
        self,
        runner_dir: Path,
        notification_handler,
        state: dict,
    ) -> None:
        self.runner_dir = runner_dir
        self.notification_handler = notification_handler
        self.state = state

    def query(self) -> dict:
        auth_marker = (self.runner_dir / "auth.json").read_bytes()
        self.state.setdefault("queries", []).append(auth_marker)
        email = (
            "account-a@example.com"
            if auth_marker == b"account-a"
            else "account-b@example.com"
        )
        return {
            "account": {
                "account": {
                    "email": email,
                    "planType": "plus",
                    "type": "chatgpt",
                },
                "requiresOpenaiAuth": True,
            },
            "limits": {
                "rateLimits": {
                    "primary": {"usedPercent": 10},
                }
            },
        }

    def request(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        if method == "thread/start":
            self.state["thread_id"] = "thread-phase0"
            self.state["cwd"] = params["cwd"]
            return {
                "thread": {
                    "id": self.state["thread_id"],
                    "cwd": self.state["cwd"],
                    "turns": [],
                }
            }
        if method == "thread/resume":
            return {
                "thread": {
                    "id": params["threadId"],
                    "cwd": self.state["cwd"],
                    "turns": list(self.state["turns"]),
                }
            }
        if method == "turn/start":
            turn_number = len(self.state["turns"]) + 1
            sentinel = (
                "PHASE0_A_READY"
                if turn_number == 1
                else (
                    "missing"
                    if self.state.get("omit_b_sentinel")
                    else "PHASE0_B_RESUMED"
                )
            )
            turn = {
                "id": f"turn-{turn_number}",
                "items": [
                    {
                        "id": f"message-{turn_number}",
                        "text": sentinel,
                        "type": "agentMessage",
                    }
                ],
                "status": "completed",
            }
            self.state["turns"].append(turn)
            self.notification_handler(
                "turn_completed",
                {
                    "threadId": params["threadId"],
                    "turn": turn,
                },
            )
            return {"turn": turn}
        if method == "thread/read":
            return {
                "thread": {
                    "id": params["threadId"],
                    "cwd": self.state["cwd"],
                    "turns": list(self.state["turns"]),
                }
            }
        raise AssertionError(f"Unexpected method: {method}")

    def close(self) -> None:
        return None


class IsolatedProtocolProbeTests(unittest.TestCase):
    def test_uses_prepared_runner_and_keeps_it_after_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles_root = root / "profiles"
            profile_a = profiles_root / "account_a"
            profile_b = profiles_root / "account_b"
            runner = profiles_root / ".phase0_desktop_runner"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, runner, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            (runner / "auth.json").write_bytes(b"account-a")
            state = {"turns": []}

            report = run_isolated_probe(
                profiles_root=profiles_root,
                profile_a=profile_a,
                profile_b=profile_b,
                expected_a_email="account-a@example.com",
                expected_b_email="account-b@example.com",
                workspace=workspace,
                runner_dir=runner,
                session_factory=lambda home, handler: FakeSession(
                    home,
                    handler,
                    state,
                ),
                timeout_seconds=1,
                require_hooks=False,
            )

            self.assertTrue(report["passed"])
            self.assertTrue(runner.is_dir())
            self.assertEqual(
                (runner / "auth.json").read_bytes(),
                b"account-a",
            )
            self.assertFalse((runner / ".auth-a.backup").exists())

    def test_rejects_real_profile_as_prepared_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "profiles"
            profile_a = profiles / "account_a"
            profile_b = profiles / "account_b"
            profile_c = profiles / "account_c"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, profile_c, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            (profile_c / "auth.json").write_bytes(b"account-c")

            with self.assertRaisesRegex(
                Phase0ProbeError,
                "không hợp lệ",
            ):
                run_isolated_probe(
                    profiles_root=profiles,
                    profile_a=profile_a,
                    profile_b=profile_b,
                    expected_a_email="account-a@example.com",
                    expected_b_email="account-b@example.com",
                    workspace=workspace,
                    runner_dir=profile_c,
                    session_factory=lambda _home, _handler: None,
                    timeout_seconds=1,
                    require_hooks=False,
                )

            self.assertEqual(
                (profile_c / "auth.json").read_bytes(),
                b"account-c",
            )

    def test_discards_stale_backup_before_using_prepared_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "profiles"
            profile_a = profiles / "account_a"
            profile_b = profiles / "account_b"
            runner = profiles / ".phase0_desktop_runner"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, runner, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            (runner / "auth.json").write_bytes(b"account-a")
            (runner / ".auth-a.backup").write_bytes(b"stale-auth")

            with self.assertRaisesRegex(Phase0ProbeError, "stop"):
                run_isolated_probe(
                    profiles_root=profiles,
                    profile_a=profile_a,
                    profile_b=profile_b,
                    expected_a_email="account-a@example.com",
                    expected_b_email="account-b@example.com",
                    workspace=workspace,
                    runner_dir=runner,
                    session_factory=lambda _home, _handler: (
                        _ for _ in ()
                    ).throw(Phase0ProbeError("stop")),
                    timeout_seconds=1,
                    require_hooks=False,
                )

            self.assertEqual(
                (runner / "auth.json").read_bytes(),
                b"account-a",
            )
            self.assertFalse((runner / ".auth-a.backup").exists())

    def test_switches_a_to_b_and_resumes_same_thread_and_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles_root = root / "profiles"
            profile_a = profiles_root / "account_a"
            profile_b = profiles_root / "account_b"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            state = {"turns": []}

            def session_factory(runner_dir, notification_handler):
                return FakeSession(
                    runner_dir,
                    notification_handler,
                    state,
                )

            report = run_isolated_probe(
                profiles_root=profiles_root,
                profile_a=profile_a,
                profile_b=profile_b,
                expected_a_email="account-a@example.com",
                expected_b_email="account-b@example.com",
                workspace=workspace,
                runner_parent=root,
                session_factory=session_factory,
                timeout_seconds=1,
                require_hooks=False,
            )

            self.assertTrue(report["passed"])
            self.assertEqual(report["thread_id_preserved"], True)
            self.assertEqual(report["cwd_preserved"], True)
            self.assertEqual(report["turns_after_resume"], 2)
            self.assertEqual(report["active_account_restored"], True)
            self.assertTrue(report["synthetic_usage_limit_observed"])
            self.assertTrue(report["history_continuity_verified"])
            self.assertNotIn("account-a@example.com", str(report))
            self.assertNotIn("account-b@example.com", str(report))

    def test_does_not_switch_without_usage_limit_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "profiles"
            profile_a = profiles / "a"
            profile_b = profiles / "b"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            state = {"turns": []}

            def session_factory(runner_dir, notification_handler):
                return FakeSession(runner_dir, notification_handler, state)

            with mock.patch(
                "app.phase0_failover_probe.synthetic_usage_limit_event",
                return_value={"turn": {"error": None}},
            ):
                with self.assertRaises(Phase0ProbeError):
                    run_isolated_probe(
                        profiles_root=profiles,
                        profile_a=profile_a,
                        profile_b=profile_b,
                        expected_a_email="account-a@example.com",
                        expected_b_email="account-b@example.com",
                        workspace=workspace,
                        runner_parent=root,
                        session_factory=session_factory,
                        timeout_seconds=1,
                        require_hooks=False,
                    )

            self.assertNotIn(b"account-b", state["queries"])

    def test_rejects_completed_turn_without_continuity_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "profiles"
            profile_a = profiles / "a"
            profile_b = profiles / "b"
            workspace = root / "workspace"
            for path in (profile_a, profile_b, workspace):
                path.mkdir(parents=True)
            (profile_a / "auth.json").write_bytes(b"account-a")
            (profile_b / "auth.json").write_bytes(b"account-b")
            state = {"turns": [], "omit_b_sentinel": True}

            def session_factory(runner_dir, notification_handler):
                return FakeSession(runner_dir, notification_handler, state)

            with self.assertRaisesRegex(
                Phase0ProbeError,
                "không nhớ được ngữ cảnh",
            ):
                run_isolated_probe(
                    profiles_root=profiles,
                    profile_a=profile_a,
                    profile_b=profile_b,
                    expected_a_email="account-a@example.com",
                    expected_b_email="account-b@example.com",
                    workspace=workspace,
                    runner_parent=root,
                    session_factory=session_factory,
                    timeout_seconds=1,
                    require_hooks=False,
                )


class UsageLimitSignalTests(unittest.TestCase):
    def test_classifies_only_usage_limit_error(self) -> None:
        event = synthetic_usage_limit_event("thread-phase0", "turn-phase0")
        self.assertTrue(is_usage_limit_event(event))
        self.assertFalse(
            is_usage_limit_event(
                {
                    "turn": {
                        "error": {
                            "codexErrorInfo": "serverOverloaded",
                        }
                    }
                }
            )
        )


class ProfileDiscoveryTests(unittest.TestCase):
    def test_ignores_internal_runner_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "profiles"
            profiles.mkdir()
            internal = profiles / ".phase0_desktop_runner"
            profile_a = profiles / "a"
            profile_b = profiles / "b"
            for profile in (internal, profile_a, profile_b):
                profile.mkdir()
                (profile / "auth.json").write_bytes(b"test")

            def snapshot(profile: Path, _timeout: float) -> dict:
                if profile == internal:
                    raise AssertionError("Internal runner was inspected")
                return {
                    "account": {
                        "account": {
                            "email": f"{profile.name}@example.com",
                        }
                    },
                    "limits": {
                        "rateLimits": {
                            "primary": {"usedPercent": 10},
                        }
                    },
                }

            with mock.patch(
                "app.phase0_failover_probe._profile_snapshot",
                side_effect=snapshot,
            ):
                result = discover_profile_pair(profiles, 1)

            self.assertEqual(result[0], profile_a)
            self.assertEqual(result[2], profile_b)

    def test_discovers_two_distinct_profiles_with_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "profiles"
            profiles.mkdir()
            profile_a = profiles / "a"
            profile_b = profiles / "b"
            for profile in (profile_a, profile_b):
                profile.mkdir()
                (profile / "auth.json").write_bytes(b"test")
            snapshots = [
                {
                    "account": {
                        "account": {"email": "a@example.com"},
                    },
                    "limits": {
                        "rateLimits": {
                            "primary": {"usedPercent": 20},
                        }
                    },
                },
                {
                    "account": {
                        "account": {"email": "b@example.com"},
                    },
                    "limits": {
                        "rateLimits": {
                            "primary": {"usedPercent": 30},
                        }
                    },
                },
            ]

            with mock.patch(
                "app.phase0_failover_probe._profile_snapshot",
                side_effect=snapshots,
            ):
                result = discover_profile_pair(profiles, 1)

            self.assertEqual(result[0], profile_a)
            self.assertEqual(result[1], "a@example.com")
            self.assertEqual(result[2], profile_b)
            self.assertEqual(result[3], "b@example.com")

    def test_cli_refuses_to_run_while_manager_is_active(self) -> None:
        stdout = io.StringIO()
        with mock.patch(
            "app.phase0_failover_probe._local_manager_is_running",
            return_value=True,
        ), contextlib.redirect_stdout(stdout):
            result = probe_main([])

        self.assertEqual(result, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["passed"])
        self.assertNotIn("auth", stdout.getvalue().casefold())

    def test_cli_redacts_codex_session_error(self) -> None:
        stdout = io.StringIO()
        with mock.patch(
            "app.phase0_failover_probe._local_manager_is_running",
            return_value=False,
        ), mock.patch(
            "app.phase0_failover_probe.discover_profile_pair",
            side_effect=CodexSessionError("SENTINEL_PRIVATE_PATH"),
        ), contextlib.redirect_stdout(stdout):
            result = probe_main([])

        self.assertEqual(result, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["passed"])
        self.assertNotIn("SENTINEL_PRIVATE_PATH", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
