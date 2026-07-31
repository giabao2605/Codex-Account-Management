from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import queue
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from secrets import token_hex
from typing import Callable

from .codex_sync import CodexProfileSession, CodexSessionError
from .local_web_profiles import (
    UnsafeProfilePathError,
    is_reparse_point,
    validate_direct_profile_directory,
)
from .otp_codex_manager_with_account_status import (
    CODEX_PROFILES_DIR,
    build_codex_command,
    build_codex_environment,
    ensure_codex_profile,
    protect_sensitive_path,
)


MAX_AUTH_BYTES = 8 * 1024 * 1024
A_SENTINEL = "PHASE0_A_READY"
B_SENTINEL = "PHASE0_B_RESUMED"
SessionFactory = Callable[[Path, Callable[[str, dict], None]], object]


class Phase0ProbeError(RuntimeError):
    pass


def _validate_regular_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
        unsafe = is_reparse_point(path) or not stat.S_ISREG(metadata.st_mode)
    except OSError as error:
        raise Phase0ProbeError("File xác thực không khả dụng.") from error
    if unsafe or metadata.st_size <= 0 or metadata.st_size > MAX_AUTH_BYTES:
        raise Phase0ProbeError("File xác thực không an toàn.")
    return metadata


def _discard_regular_file(path: Path, error_message: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise Phase0ProbeError(error_message) from error
    if is_reparse_point(path) or not stat.S_ISREG(metadata.st_mode):
        raise Phase0ProbeError(error_message)
    try:
        path.unlink()
    except OSError as error:
        raise Phase0ProbeError(error_message) from error


def atomic_copy_auth(source: Path, destination: Path) -> str:
    """Sao chép auth dưới dạng byte, không parse hay ghi nội dung ra log."""
    source = Path(source)
    destination = Path(destination)
    before = _validate_regular_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if is_reparse_point(destination.parent):
        raise Phase0ProbeError("Thư mục Runner không an toàn.")
    protect_sensitive_path(destination.parent)
    temporary = destination.with_name(
        f".{destination.name}.{token_hex(8)}.tmp"
    )
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while chunk := reader.read(64 * 1024):
                copied += len(chunk)
                if copied > MAX_AUTH_BYTES:
                    raise Phase0ProbeError("File xác thực vượt giới hạn.")
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        protect_sensitive_path(temporary)
        after = source.lstat()
        if (
            is_reparse_point(source)
            or not stat.S_ISREG(after.st_mode)
            or copied != before.st_size
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or (
                before.st_ino
                and after.st_ino
                and before.st_ino != after.st_ino
            )
        ):
            raise Phase0ProbeError(
                "File xác thực thay đổi trong lúc sao chép."
            )
        os.replace(temporary, destination)
        protect_sensitive_path(destination)
        return digest.hexdigest()
    except Phase0ProbeError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise Phase0ProbeError("Không thể kích hoạt file xác thực.") from error


def validate_profile_auth(
    profiles_root: Path,
    profile_dir: Path,
) -> Path:
    profiles_root = Path(profiles_root)
    profile_dir = Path(profile_dir)
    try:
        validate_direct_profile_directory(profiles_root, profile_dir)
    except (OSError, UnsafeProfilePathError) as error:
        raise Phase0ProbeError("Profile Codex không an toàn.") from error
    auth_file = profile_dir / "auth.json"
    _validate_regular_file(auth_file)
    return auth_file


def write_phase0_hooks(
    *,
    runner: Path,
    hook_log: Path,
    python_executable: Path,
) -> Path:
    runner = Path(runner)
    hook_log = Path(hook_log)
    if (
        not runner.is_dir()
        or is_reparse_point(runner)
        or hook_log.parent != runner
    ):
        raise Phase0ProbeError("Đường dẫn hook Phase 0 không an toàn.")
    recorder = Path(__file__).with_name("phase0_hook_recorder.py")
    command = subprocess.list2cmdline(
        [
            str(python_executable),
            str(recorder),
            "--root",
            str(runner),
            "--output",
            str(hook_log),
        ]
    )
    handler = {
        "hooks": [
            {
                "command": command,
                "commandWindows": command,
                "timeout": 10,
                "type": "command",
            }
        ]
    }
    payload = {
        "description": "OTP Codex Phase 0 metadata-only probe.",
        "hooks": {
            "SessionStart": [handler],
            "Stop": [handler],
            "UserPromptSubmit": [handler],
        },
    }
    config_file = runner / "hooks.json"
    temporary = runner / f".hooks.{token_hex(8)}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        protect_sensitive_path(temporary)
        os.replace(temporary, config_file)
        protect_sensitive_path(config_file)
        return config_file
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise Phase0ProbeError("Không thể tạo hook Phase 0.") from error


def _account_email(snapshot: dict) -> str:
    account_result = snapshot.get("account")
    account = (
        account_result.get("account")
        if isinstance(account_result, dict)
        else None
    )
    email = account.get("email") if isinstance(account, dict) else None
    if not isinstance(email, str) or not email.strip():
        raise Phase0ProbeError("Runner không trả về tài khoản hợp lệ.")
    return email.strip().casefold()


def _quota_available(snapshot: dict) -> bool:
    limits = snapshot.get("limits")
    if not isinstance(limits, dict):
        return True
    if limits.get("rateLimitReachedType"):
        return False
    rate_limits = limits.get("rateLimits")
    if not isinstance(rate_limits, dict):
        return True
    buckets = [
        bucket.get("usedPercent")
        for bucket in rate_limits.values()
        if isinstance(bucket, dict)
        and isinstance(bucket.get("usedPercent"), (int, float))
    ]
    return not buckets or any(value < 100 for value in buckets)


def synthetic_usage_limit_event(thread_id: str, turn_id: str) -> dict:
    return {
        "threadId": thread_id,
        "turn": {
            "error": {
                "codexErrorInfo": "usageLimitExceeded",
                "message": "Synthetic Phase 0 signal.",
            },
            "id": turn_id,
            "items": [],
            "status": "failed",
        },
    }


def is_usage_limit_event(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    turn = payload.get("turn")
    error = turn.get("error") if isinstance(turn, dict) else None
    return (
        isinstance(error, dict)
        and error.get("codexErrorInfo") == "usageLimitExceeded"
    )


def _turn_has_sentinel(turn: object, sentinel: str) -> bool:
    if not isinstance(turn, dict):
        return False
    items = turn.get("items")
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and isinstance(item.get("text"), str)
        and sentinel in item["text"]
        for item in items
    )


def _find_turn(thread_result: dict, turn_id: str) -> dict | None:
    thread = thread_result.get("thread")
    turns = thread.get("turns") if isinstance(thread, dict) else None
    if not isinstance(turns, list):
        return None
    return next(
        (
            turn
            for turn in turns
            if isinstance(turn, dict) and turn.get("id") == turn_id
        ),
        None,
    )


def _create_real_session(
    home: Path,
    notification_handler: Callable[[str, dict], None],
    timeout_seconds: float,
) -> CodexProfileSession:
    command = build_codex_command("app-server")
    if command is None:
        raise Phase0ProbeError("Không tìm thấy Codex CLI tin cậy.")
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.name == "nt"
        else 0
    )
    return CodexProfileSession(
        profile_dir=home,
        command=command,
        environment=build_codex_environment(home),
        notification_handler=notification_handler,
        timeout_seconds=timeout_seconds,
        creation_flags=creation_flags,
    )


def _session_and_events(
    home: Path,
    session_factory: SessionFactory,
) -> tuple[
    object,
    queue.Queue,
    Callable[[str, dict], None],
]:
    events: queue.Queue = queue.Queue()

    def notification_handler(event: str, payload: dict) -> None:
        if event == "turn_completed":
            events.put_nowait(payload)

    return session_factory(home, notification_handler), events, (
        notification_handler
    )


def _wait_for_turn(
    events: queue.Queue,
    thread_id: str,
    turn_id: str,
    timeout_seconds: float,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Phase0ProbeError("Turn thử nghiệm không hoàn tất đúng hạn.")
        try:
            payload = events.get(timeout=remaining)
        except queue.Empty as error:
            raise Phase0ProbeError(
                "Turn thử nghiệm không hoàn tất đúng hạn."
            ) from error
        turn = payload.get("turn")
        if (
            payload.get("threadId") == thread_id
            and isinstance(turn, dict)
            and turn.get("id") == turn_id
        ):
            if turn.get("status") != "completed":
                raise Phase0ProbeError("Turn thử nghiệm không thành công.")
            return turn


def _wait_for_usage_limit(
    events: queue.Queue,
    thread_id: str,
    timeout_seconds: float,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Phase0ProbeError(
                "Không quan sát được tín hiệu usageLimitExceeded."
            )
        try:
            payload = events.get(timeout=remaining)
        except queue.Empty as error:
            raise Phase0ProbeError(
                "Không quan sát được tín hiệu usageLimitExceeded."
            ) from error
        if (
            payload.get("threadId") == thread_id
            and is_usage_limit_event(payload)
        ):
            return payload


def _thread_identity(result: dict) -> tuple[str, str]:
    thread = result.get("thread")
    if not isinstance(thread, dict):
        raise Phase0ProbeError("Codex không trả về thread hợp lệ.")
    thread_id = thread.get("id")
    cwd = thread.get("cwd")
    if not isinstance(thread_id, str) or not isinstance(cwd, str):
        raise Phase0ProbeError("Thread thiếu định danh hoặc thư mục làm việc.")
    return thread_id, cwd


def _close_session(session: object | None) -> None:
    if session is None:
        return
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _hooks_ready(result: dict) -> bool:
    entries = result.get("data")
    if not isinstance(entries, list):
        return False
    hooks = [
        hook
        for entry in entries
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    ]
    expected = {"sessionStart", "stop", "userPromptSubmit"}
    active = {
        hook.get("eventName")
        for hook in hooks
        if hook.get("enabled") is True
        and hook.get("trustStatus") in {"managed", "trusted"}
    }
    return expected.issubset(active)


def _recorded_hook_events(hook_log: Path) -> set[str]:
    try:
        metadata = hook_log.lstat()
        if (
            is_reparse_point(hook_log)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 1024 * 1024
        ):
            return set()
        lines = hook_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    events: set[str] = set()
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_name = (
            payload.get("hook_event_name")
            if isinstance(payload, dict)
            else None
        )
        if isinstance(event_name, str):
            events.add(event_name)
    return events


def run_isolated_probe(
    *,
    profiles_root: Path,
    profile_a: Path,
    profile_b: Path,
    expected_a_email: str,
    expected_b_email: str,
    workspace: Path,
    runner_parent: Path | None = None,
    runner_dir: Path | None = None,
    session_factory: SessionFactory | None = None,
    timeout_seconds: float = 120,
    require_hooks: bool = True,
) -> dict:
    auth_a = validate_profile_auth(profiles_root, profile_a)
    auth_b = validate_profile_auth(profiles_root, profile_b)
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise Phase0ProbeError("Workspace thử nghiệm không tồn tại.")
    expected_a = expected_a_email.strip().casefold()
    expected_b = expected_b_email.strip().casefold()
    if not expected_a or not expected_b or expected_a == expected_b:
        raise Phase0ProbeError("Cần hai tài khoản Codex khác nhau.")

    factory = session_factory
    if factory is None:
        factory = lambda home, handler: _create_real_session(
            home,
            handler,
            timeout_seconds,
        )

    if runner_dir is None:
        parent = str(runner_parent) if runner_parent is not None else None
        runner_context = tempfile.TemporaryDirectory(
            prefix="otp-codex-phase0-",
            dir=parent,
        )
    else:
        runner = Path(runner_dir)
        try:
            validate_direct_profile_directory(profiles_root, runner)
        except (OSError, UnsafeProfilePathError) as error:
            raise Phase0ProbeError(
                "Runner Phase 0 không an toàn."
            ) from error
        if (
            not runner.is_dir()
            or runner.name != ".phase0_desktop_runner"
            or runner in {Path(profile_a), Path(profile_b)}
        ):
            raise Phase0ProbeError("Runner Phase 0 không hợp lệ.")
        runner_context = contextlib.nullcontext(str(runner))

    with runner_context as temp_dir:
        runner = Path(temp_dir)
        protect_sensitive_path(runner)
        ensure_codex_profile(runner)
        runner_auth = runner / "auth.json"
        backup_a = runner / ".auth-a.backup"
        hook_log = runner / "hook-events.jsonl"
        _discard_regular_file(
            backup_a,
            "Backup auth Phase 0 không an toàn.",
        )
        if require_hooks:
            _discard_regular_file(
                hook_log,
                "Log hook Phase 0 không an toàn.",
            )
            write_phase0_hooks(
                runner=runner,
                hook_log=hook_log,
                python_executable=Path(sys.executable),
            )
        atomic_copy_auth(auth_a, runner_auth)

        session: object | None = None
        restored = False
        backup_created = False
        hooks_trusted = not require_hooks
        try:
            session, events, observe_event = _session_and_events(
                runner,
                factory,
            )
            if _account_email(session.query()) != expected_a:
                raise Phase0ProbeError("Runner A không khớp profile nguồn.")
            if require_hooks:
                hooks_trusted = _hooks_ready(
                    session.request(
                        "hooks/list",
                        {"cwds": [str(workspace)]},
                    )
                )
            start_result = session.request(
                "thread/start",
                {
                    "approvalPolicy": "never",
                    "cwd": str(workspace),
                    "ephemeral": False,
                    "sandbox": "read-only",
                },
            )
            thread_id, original_cwd = _thread_identity(start_result)
            first_turn = session.request(
                "turn/start",
                {
                    "approvalPolicy": "never",
                    "input": [
                        {
                            "type": "text",
                            "text": (
                                "Phase 0 continuity probe. Reply with "
                                "PHASE0_A_READY. If the next prompt is "
                                "continue, reply with PHASE0_B_RESUMED."
                            ),
                        }
                    ],
                    "threadId": thread_id,
                },
            ).get("turn")
            if not isinstance(first_turn, dict) or not isinstance(
                first_turn.get("id"),
                str,
            ):
                raise Phase0ProbeError("Không khởi tạo được turn A.")
            _wait_for_turn(
                events,
                thread_id,
                first_turn["id"],
                timeout_seconds,
            )
            read_after_a = session.request(
                "thread/read",
                {"includeTurns": True, "threadId": thread_id},
            )
            if not _turn_has_sentinel(
                _find_turn(read_after_a, first_turn["id"]),
                A_SENTINEL,
            ):
                raise Phase0ProbeError(
                    "Turn A không trả về sentinel mong đợi."
                )
            usage_limit = synthetic_usage_limit_event(
                thread_id,
                first_turn["id"],
            )
            observe_event("turn_completed", usage_limit)
            observed_usage_limit = _wait_for_usage_limit(
                events,
                thread_id,
                timeout_seconds,
            )
            usage_limit_observed = is_usage_limit_event(
                observed_usage_limit
            )
            _close_session(session)
            session = None

            atomic_copy_auth(runner_auth, backup_a)
            backup_created = True
            atomic_copy_auth(auth_b, runner_auth)
            session, events, _ = _session_and_events(runner, factory)
            if _account_email(session.query()) != expected_b:
                raise Phase0ProbeError("Runner B không khớp profile nguồn.")
            resume_result = session.request(
                "thread/resume",
                {"threadId": thread_id},
            )
            resumed_id, resumed_cwd = _thread_identity(resume_result)
            second_turn = session.request(
                "turn/start",
                {
                    "approvalPolicy": "never",
                    "input": [{"type": "text", "text": "continue"}],
                    "threadId": thread_id,
                },
            ).get("turn")
            if not isinstance(second_turn, dict) or not isinstance(
                second_turn.get("id"),
                str,
            ):
                raise Phase0ProbeError("Không khởi tạo được turn B.")
            _wait_for_turn(
                events,
                thread_id,
                second_turn["id"],
                timeout_seconds,
            )
            read_result = session.request(
                "thread/read",
                {"includeTurns": True, "threadId": thread_id},
            )
            if not _turn_has_sentinel(
                _find_turn(read_result, second_turn["id"]),
                B_SENTINEL,
            ):
                raise Phase0ProbeError(
                    "Turn B không nhớ được ngữ cảnh từ Runner A."
                )
            read_id, read_cwd = _thread_identity(read_result)
            thread = read_result["thread"]
            turns = thread.get("turns")
            if not isinstance(turns, list):
                raise Phase0ProbeError("Không đọc được lịch sử turn.")
            _close_session(session)
            session = None

            atomic_copy_auth(backup_a, runner_auth)
            session, _, _ = _session_and_events(runner, factory)
            restored = _account_email(session.query()) == expected_a
            if not restored:
                raise Phase0ProbeError("Không khôi phục được Runner A.")

            identity_preserved = (
                resumed_id == thread_id == read_id
            )
            cwd_preserved = (
                resumed_cwd == original_cwd == read_cwd == str(workspace)
            )
            protocol_passed = (
                identity_preserved
                and cwd_preserved
                and len(turns) >= 2
                and restored
            )
            required_hook_events = {
                "SessionStart",
                "Stop",
                "UserPromptSubmit",
            }
            hook_events = _recorded_hook_events(hook_log)
            hooks_recorded = (
                not require_hooks
                or required_hook_events.issubset(hook_events)
            )
            passed = (
                protocol_passed
                and usage_limit_observed
                and hooks_trusted
                and hooks_recorded
            )
            return {
                "passed": passed,
                "protocol_passed": protocol_passed,
                "synthetic_usage_limit_observed": usage_limit_observed,
                "thread_id_preserved": identity_preserved,
                "cwd_preserved": cwd_preserved,
                "history_continuity_verified": True,
                "turns_after_resume": len(turns),
                "active_account_restored": restored,
                "hooks_trusted": hooks_trusted,
                "hooks_recorded": hooks_recorded,
            }
        finally:
            _close_session(session)
            rollback_succeeded = restored
            if backup_created and not restored:
                try:
                    atomic_copy_auth(backup_a, runner_auth)
                    rollback_succeeded = True
                except Phase0ProbeError:
                    pass
            if not backup_created or rollback_succeeded:
                _discard_regular_file(
                    backup_a,
                    "Không thể dọn backup auth Phase 0.",
                )


def _profile_snapshot(profile_dir: Path, timeout_seconds: float) -> dict:
    session = _create_real_session(
        profile_dir,
        lambda _event, _payload: None,
        timeout_seconds,
    )
    try:
        return session.query()
    finally:
        session.close()


def discover_profile_pair(
    profiles_root: Path,
    timeout_seconds: float,
) -> tuple[Path, str, Path, str]:
    candidates: list[tuple[Path, str]] = []
    for profile_dir in sorted(
        (
            item
            for item in Path(profiles_root).iterdir()
            if item.is_dir() and not item.name.startswith(".")
        ),
        key=lambda item: item.name.casefold(),
    ):
        try:
            validate_profile_auth(profiles_root, profile_dir)
            snapshot = _profile_snapshot(profile_dir, timeout_seconds)
            email = _account_email(snapshot)
            if _quota_available(snapshot):
                candidates.append((profile_dir, email))
        except (OSError, CodexSessionError, Phase0ProbeError):
            continue
        if len(candidates) == 2:
            first, second = candidates
            if first[1] != second[1]:
                return first[0], first[1], second[0], second[1]
            candidates.pop()
    raise Phase0ProbeError("Không tìm thấy hai profile còn quota.")


def _local_manager_is_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Chạy gate Phase 0 trong CODEX_HOME tạm.",
    )
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=CODEX_PROFILES_DIR,
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--runner-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)

    try:
        if _local_manager_is_running():
            raise Phase0ProbeError(
                "Hãy dừng OTP Codex Local trước khi chạy Phase 0."
            )
        profile_a, email_a, profile_b, email_b = discover_profile_pair(
            args.profiles_dir,
            args.timeout,
        )
        report = run_isolated_probe(
            profiles_root=args.profiles_dir,
            profile_a=profile_a,
            profile_b=profile_b,
            expected_a_email=email_a,
            expected_b_email=email_b,
            workspace=args.workspace,
            runner_dir=args.runner_dir,
            timeout_seconds=args.timeout,
        )
    except (CodexSessionError, Phase0ProbeError) as error:
        message = (
            str(error)
            if isinstance(error, Phase0ProbeError)
            else "Codex App Server không hoàn tất Phase 0."
        )
        print(
            json.dumps(
                {"passed": False, "error": message},
                ensure_ascii=True,
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
