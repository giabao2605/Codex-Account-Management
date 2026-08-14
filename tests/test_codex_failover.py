import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.codex_failover import (
    FailoverCoordinator,
    FailoverPersistenceError,
    FailoverState,
    FailoverTransitionError,
    read_failover_snapshot,
    sanitize_hook_event,
    summarize_failover_snapshot,
)
from app.codex_failover_hook import (
    main as hook_main,
    write_failover_hooks,
)


class FailoverCoordinatorTests(unittest.TestCase):
    def test_read_only_snapshot_never_creates_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()

            self.assertIsNone(read_failover_snapshot(profiles))
            self.assertFalse((profiles / ".failover").exists())

            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            snapshot = read_failover_snapshot(profiles)

            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot["state"], "observing")

    def test_public_summary_exposes_counts_without_task_metadata(self) -> None:
        summary = summarize_failover_snapshot(
            {
                "last_error": "SENTINEL internal error",
                "quotas": {
                    "private_profile_key": {
                        "exhausted": True,
                        "rate_limit_reached_type": "weekly",
                        "windows": [],
                    }
                },
                "sequence": 4,
                "state": FailoverState.BLOCKED.value,
                "tasks": {
                    "private_session_id": {
                        "cwd": "C:\\private\\workspace",
                        "eligible": True,
                        "permission_mode": "dontAsk",
                        "session_id": "private_session_id",
                        "status": "quota_exhausted",
                        "turn_id": "private_turn_id",
                    },
                },
                "updated_at": "2026-08-12T10:00:00+00:00",
            }
        )

        self.assertEqual(summary["state"], "blocked")
        self.assertEqual(summary["tasks"]["total"], 1)
        self.assertEqual(summary["tasks"]["eligible"], 1)
        self.assertEqual(summary["tasks"]["quota_exhausted"], 1)
        self.assertEqual(summary["quotas"]["total"], 1)
        self.assertEqual(summary["quotas"]["exhausted"], 1)
        serialized = json.dumps(summary)
        for sensitive in (
            "SENTINEL",
            "private_profile_key",
            "private_session_id",
            "private_turn_id",
            "private\\workspace",
            "dontAsk",
        ):
            self.assertNotIn(sensitive, serialized)

    def test_tracks_eligible_task_and_full_state_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)

            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-phase1",
                }
            )
            coordinator.handle_codex_event(
                "profile_a",
                "quota_updated",
                {
                    "quota": {
                        "exhausted": True,
                        "rate_limit_reached_type": "weekly",
                        "windows": [],
                    }
                },
            )
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-phase1",
                    "turn_id": "turn-phase1",
                },
            )

            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.DRAINING.value,
            )
            coordinator.transition(FailoverState.SWITCHING)
            coordinator.transition(FailoverState.RESUMING)
            coordinator.transition(FailoverState.RUNNING)

            snapshot = coordinator.snapshot()
            task = snapshot["tasks"]["thread-phase1"]
            self.assertTrue(task["eligible"])
            self.assertEqual(task["permission_mode"], "dontAsk")
            self.assertEqual(task["status"], "quota_exhausted")
            self.assertEqual(task["turn_id"], "turn-phase1")
            self.assertTrue(snapshot["quotas"]["profile_a"]["exhausted"])
            sequence = snapshot["sequence"]
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-phase1",
                    "turn_id": "turn-phase1",
                },
            )
            self.assertEqual(coordinator.snapshot()["sequence"], sequence)

            coordinator.disable()
            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.DISABLED.value,
            )

    def test_bypass_permissions_task_blocks_automatic_failover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "bypassPermissions",
                    "session_id": "thread-manual",
                }
            )

            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-manual",
                    "turn_id": "turn-manual",
                },
            )

            snapshot = coordinator.snapshot()
            self.assertEqual(snapshot["state"], FailoverState.BLOCKED.value)
            self.assertEqual(
                snapshot["tasks"]["thread-manual"]["status"],
                "blocked",
            )
            self.assertFalse(
                snapshot["tasks"]["thread-manual"]["eligible"]
            )

    def test_stop_does_not_erase_usage_limit_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-phase1",
                }
            )
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-phase1",
                    "turn_id": "turn-phase1",
                },
            )

            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-phase1",
                    "turn_id": "turn-phase1",
                }
            )

            self.assertEqual(
                coordinator.snapshot()["tasks"]["thread-phase1"]["status"],
                "quota_exhausted",
            )

    def test_normal_stop_marks_task_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-complete",
                }
            )
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-complete",
                    "turn_id": "turn-complete",
                }
            )

            self.assertEqual(
                coordinator.snapshot()["tasks"]["thread-complete"]["status"],
                "completed",
            )

            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "UserPromptSubmit",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-complete",
                    "turn_id": "turn-next",
                }
            )
            self.assertEqual(
                coordinator.snapshot()["tasks"]["thread-complete"]["status"],
                "active",
            )

    def test_usage_limit_overrides_earlier_stop_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-race",
                }
            )
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "Stop",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-race",
                    "turn_id": "turn-race",
                }
            )

            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-race",
                    "turn_id": "turn-race",
                },
            )

            snapshot = coordinator.snapshot()
            self.assertEqual(snapshot["state"], FailoverState.DRAINING.value)
            self.assertEqual(
                snapshot["tasks"]["thread-race"]["status"],
                "quota_exhausted",
            )

    def test_invalid_transition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)

            with self.assertRaises(FailoverTransitionError):
                coordinator.transition(FailoverState.SWITCHING)

    def test_all_declared_terminal_states_can_recover_to_observing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.transition(FailoverState.ERROR, "test error")
            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.ERROR.value,
            )
            coordinator.enable()
            coordinator.transition(FailoverState.BLOCKED, "test blocked")
            coordinator.enable()
            coordinator.transition(FailoverState.DRAINING)
            coordinator.transition(FailoverState.ALL_EXHAUSTED)
            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.ALL_EXHAUSTED.value,
            )
            coordinator.enable()
            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.OBSERVING.value,
            )

    def test_global_lock_preserves_tasks_from_concurrent_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspaces = [
                Path(temp_dir) / "project-one",
                Path(temp_dir) / "project-two",
            ]
            for workspace in workspaces:
                workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            script = (
                Path(__file__).parents[1]
                / "app"
                / "codex_failover_hook.py"
            )
            barrier = threading.Barrier(2)
            results: list[subprocess.CompletedProcess[str]] = []

            def register(session_id: str, workspace: Path) -> None:
                barrier.wait()
                results.append(
                    subprocess.run(
                        [
                            sys.executable,
                            str(script),
                            "--profiles-root",
                            str(profiles),
                            "--expected-event",
                            "SessionStart",
                        ],
                        input=json.dumps(
                            {
                                "cwd": str(workspace),
                                "hook_event_name": "SessionStart",
                                "permission_mode": "dontAsk",
                                "session_id": session_id,
                            }
                        ),
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=10,
                    )
                )

            threads = [
                threading.Thread(
                    target=register,
                    args=("thread-one", workspaces[0]),
                ),
                threading.Thread(
                    target=register,
                    args=("thread-two", workspaces[1]),
                ),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertTrue(all(result.returncode == 0 for result in results))
            self.assertEqual(
                set(coordinator.snapshot()["tasks"]),
                {"thread-one", "thread-two"},
            )

    def test_recovers_registry_from_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-recovery",
                }
            )
            expected = coordinator.snapshot()
            (profiles / ".failover" / "registry.json").unlink()

            recovered = FailoverCoordinator(profiles).snapshot()

            self.assertEqual(recovered, expected)

    def test_rejects_account_identifier_that_can_expose_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()

            with self.assertRaises(ValueError):
                coordinator.handle_codex_event(
                    "user@example.com",
                    "quota_updated",
                    {
                        "quota": {
                            "exhausted": False,
                            "rate_limit_reached_type": None,
                            "windows": [],
                        }
                    },
                )

    def test_quota_windows_are_whitelisted_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            quota = {
                "exhausted": False,
                "rate_limit_reached_type": "weekly",
                "windows": [
                    {
                        "kind": "primary",
                        "limit_id": "codex",
                        "limit_name": "Codex",
                        "resets_at": 123456,
                        "used_percent": 25.5,
                        "window_duration_minutes": 300,
                        "ignored": "SENTINEL_PRIVATE_FIELD",
                    }
                ],
            }

            coordinator.handle_codex_event(
                "profile_a",
                "quota_updated",
                {"quota": quota},
            )

            persisted = coordinator.snapshot()["quotas"]["profile_a"]
            self.assertEqual(persisted["windows"][0]["used_percent"], 25.5)
            self.assertNotIn("ignored", persisted["windows"][0])
            invalid = {
                **quota,
                "windows": [
                    {
                        **quota["windows"][0],
                        "used_percent": 101,
                    }
                ],
            }
            with self.assertRaises(ValueError):
                coordinator.handle_codex_event(
                    "profile_a",
                    "quota_updated",
                    {"quota": invalid},
                )

    def test_unknown_task_usage_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()

            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "unknown-thread",
                    "turn_id": "unknown-turn",
                },
            )

            self.assertEqual(
                coordinator.snapshot()["state"],
                FailoverState.BLOCKED.value,
            )

    def test_disabled_coordinator_ignores_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            initial = coordinator.snapshot()

            coordinator.handle_codex_event(
                "profile_a",
                "quota_updated",
                {
                    "quota": {
                        "exhausted": False,
                        "rate_limit_reached_type": None,
                        "windows": [],
                    }
                },
            )
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-disabled",
                    "turn_id": "turn-disabled",
                },
            )
            coordinator.handle_codex_event(
                "profile_a",
                "unrelated_event",
                {},
            )

            self.assertEqual(coordinator.snapshot(), initial)

    def test_rejects_reparse_failover_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()

            with mock.patch(
                "app.codex_failover.is_reparse_point",
                return_value=True,
            ):
                with self.assertRaises(FailoverPersistenceError):
                    FailoverCoordinator(profiles)

    def test_corrupt_registry_without_recovery_snapshot_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.registry_file.write_text(
                "not-json",
                encoding="utf-8",
            )

            with self.assertRaises(FailoverPersistenceError):
                FailoverCoordinator(profiles)


class FailoverHookTests(unittest.TestCase):
    def test_sanitizer_keeps_metadata_only(self) -> None:
        event = sanitize_hook_event(
            {
                "cwd": "C:\\project",
                "hook_event_name": "UserPromptSubmit",
                "permission_mode": "dontAsk",
                "prompt": "SENTINEL_PRIVATE_PROMPT",
                "session_id": "thread-phase1",
                "transcript_path": "C:\\private\\transcript.jsonl",
                "turn_id": "turn-phase1",
            }
        )

        self.assertEqual(
            event,
            {
                "cwd": "C:\\project",
                "hook_event_name": "UserPromptSubmit",
                "permission_mode": "dontAsk",
                "session_id": "thread-phase1",
                "turn_id": "turn-phase1",
            },
        )
        self.assertNotIn("SENTINEL", str(event))
        self.assertEqual(sanitize_hook_event(None), {})
        self.assertEqual(
            sanitize_hook_event({"hook_event_name": "Unknown"}),
            {},
        )
        alias = sanitize_hook_event(
            {
                "cwd": "C:\\project",
                "hook_event_name": "sessionStart",
                "permission_mode": "invalid-mode",
                "session_id": "thread-phase1",
            }
        )
        self.assertEqual(alias["hook_event_name"], "SessionStart")
        self.assertNotIn("permission_mode", alias)

    def test_user_prompt_hook_blocks_while_switching_without_storing_prompt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
            workspace = Path(temp_dir) / "project"
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            coordinator.handle_hook_event(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "SessionStart",
                    "permission_mode": "dontAsk",
                    "session_id": "thread-phase1",
                }
            )
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-phase1",
                    "turn_id": "turn-phase1",
                },
            )
            coordinator.transition(FailoverState.SWITCHING)
            raw = json.dumps(
                {
                    "cwd": str(workspace),
                    "hook_event_name": "UserPromptSubmit",
                    "permission_mode": "dontAsk",
                    "prompt": "SENTINEL_PRIVATE_PROMPT",
                    "session_id": "thread-phase1",
                    "turn_id": "turn-phase1-next",
                }
            ).encode("utf-8")
            stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
            stdout = io.StringIO()

            with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(
                stdout
            ):
                result = hook_main(
                    ["--profiles-root", str(profiles)]
                )

            self.assertEqual(result, 0)
            response = json.loads(stdout.getvalue())
            self.assertEqual(response["decision"], "block")
            persisted = (
                profiles / ".failover" / "registry.json"
            ).read_text(encoding="utf-8")
            journal = (
                profiles / ".failover" / "recovery.jsonl"
            ).read_text(encoding="utf-8")
            self.assertNotIn("SENTINEL_PRIVATE_PROMPT", persisted)
            self.assertNotIn("SENTINEL_PRIVATE_PROMPT", journal)

    def test_user_prompt_hook_fails_closed_on_invalid_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles = Path(temp_dir) / "codex_profiles"
            profiles.mkdir()
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
                        "--profiles-root",
                        str(profiles),
                        "--expected-event",
                        "UserPromptSubmit",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(stdout.getvalue())["decision"],
                "block",
            )

    def test_hook_config_contains_only_required_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "codex_profiles"
            runner = root / "runner"
            profiles.mkdir()
            runner.mkdir()

            config = write_failover_hooks(
                runner=runner,
                profiles_root=profiles,
                python_executable=Path(sys.executable),
            )
            content = config.read_text(encoding="utf-8")

            self.assertIn('"SessionStart"', content)
            self.assertIn('"UserPromptSubmit"', content)
            self.assertIn('"Stop"', content)
            self.assertIn("--expected-event", content)
            self.assertNotIn("auth.json", content)
            with self.assertRaises(FailoverPersistenceError):
                write_failover_hooks(
                    runner=runner,
                    profiles_root=profiles,
                    python_executable=Path(sys.executable),
                )

    def test_hook_script_round_trip_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / "codex_profiles"
            workspace = root / "project"
            profiles.mkdir()
            workspace.mkdir()
            coordinator = FailoverCoordinator(profiles)
            coordinator.enable()
            script = (
                Path(__file__).parents[1]
                / "app"
                / "codex_failover_hook.py"
            )
            base_command = [
                sys.executable,
                str(script),
                "--profiles-root",
                str(profiles),
            ]
            started = subprocess.run(
                [
                    *base_command,
                    "--expected-event",
                    "SessionStart",
                ],
                input=json.dumps(
                    {
                        "cwd": str(workspace),
                        "hook_event_name": "SessionStart",
                        "permission_mode": "dontAsk",
                        "session_id": "thread-subprocess",
                    }
                ),
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )

            self.assertEqual(started.returncode, 0)
            self.assertEqual(json.loads(started.stdout), {})
            self.assertIn(
                "thread-subprocess",
                coordinator.snapshot()["tasks"],
            )
            coordinator.handle_codex_event(
                "profile_a",
                "usage_limit_exceeded",
                {
                    "error_kind": "usageLimitExceeded",
                    "thread_id": "thread-subprocess",
                    "turn_id": "turn-subprocess",
                },
            )
            coordinator.transition(FailoverState.SWITCHING)
            blocked = subprocess.run(
                [
                    *base_command,
                    "--expected-event",
                    "UserPromptSubmit",
                ],
                input=json.dumps(
                    {
                        "cwd": str(workspace),
                        "hook_event_name": "UserPromptSubmit",
                        "permission_mode": "dontAsk",
                        "prompt": "SENTINEL_PRIVATE_PROMPT",
                        "session_id": "thread-subprocess",
                        "turn_id": "turn-next",
                    }
                ),
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )

            self.assertEqual(blocked.returncode, 0)
            self.assertEqual(
                json.loads(blocked.stdout)["decision"],
                "block",
            )
            self.assertNotIn(
                "SENTINEL_PRIVATE_PROMPT",
                coordinator.registry_file.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
