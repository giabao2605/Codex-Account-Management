from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from secrets import token_hex

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.codex_failover import (
    FailoverCoordinator,
    FailoverPersistenceError,
    sanitize_hook_event,
)
from app.local_web_profiles import is_reparse_point
from app.otp_codex_manager_with_account_status import protect_sensitive_path


MAX_INPUT_BYTES = 1024 * 1024
BLOCK_RESPONSE = {
    "decision": "block",
    "reason": (
        "OTP Codex chưa đọc được trạng thái điều phối; "
        "prompt mới tạm thời bị khóa."
    ),
}


def write_failover_hooks(
    *,
    runner: Path,
    profiles_root: Path,
    python_executable: Path,
) -> Path:
    runner = Path(runner)
    profiles_root = Path(profiles_root).resolve(strict=True)
    FailoverCoordinator(profiles_root)
    try:
        metadata = runner.lstat()
    except OSError as error:
        raise FailoverPersistenceError(
            "Runner failover không tồn tại."
        ) from error
    if is_reparse_point(runner) or not stat.S_ISDIR(metadata.st_mode):
        raise FailoverPersistenceError("Runner failover không an toàn.")
    config_file = runner / "hooks.json"
    if config_file.exists() or config_file.is_symlink():
        raise FailoverPersistenceError(
            "Runner đã có hooks.json; không tự động ghi đè."
        )
    def handler(event_name: str) -> dict:
        command = subprocess.list2cmdline(
            [
                str(python_executable),
                str(Path(__file__).resolve()),
                "--profiles-root",
                str(profiles_root),
                "--expected-event",
                event_name,
            ]
        )
        return {
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
        "description": "OTP Codex local failover metadata hooks.",
        "hooks": {
            "SessionStart": [handler("SessionStart")],
            "Stop": [handler("Stop")],
            "UserPromptSubmit": [handler("UserPromptSubmit")],
        },
    }
    temporary = runner / f".failover-hooks.{token_hex(8)}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        protect_sensitive_path(temporary)
        os.replace(temporary, config_file)
        protect_sensitive_path(config_file)
        return config_file
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise FailoverPersistenceError(
            "Không thể ghi hook failover."
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profiles-root", required=True, type=Path)
    parser.add_argument(
        "--expected-event",
        choices=("SessionStart", "Stop", "UserPromptSubmit"),
    )
    event: dict[str, str] = {}
    response: dict = {}
    expected_event: str | None = None
    try:
        args = parser.parse_args(argv)
        expected_event = args.expected_event
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError
        event = sanitize_hook_event(json.loads(raw.decode("utf-8")))
        if (
            not event
            or expected_event is not None
            and event.get("hook_event_name") != expected_event
        ):
            raise ValueError
        response = FailoverCoordinator(
            args.profiles_root
        ).handle_hook_event(event)
    except Exception:
        if (
            expected_event == "UserPromptSubmit"
            or event.get("hook_event_name") == "UserPromptSubmit"
        ):
            response = BLOCK_RESPONSE
    print(json.dumps(response, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
