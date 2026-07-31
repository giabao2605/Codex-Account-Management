from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


MAX_INPUT_BYTES = 1024 * 1024
ALLOWED_EVENTS = {"SessionStart", "Stop", "UserPromptSubmit"}
EVENT_ALIASES = {
    "sessionStart": "SessionStart",
    "stop": "Stop",
    "userPromptSubmit": "UserPromptSubmit",
}
ALLOWED_PERMISSION_MODES = {
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
}
SAFE_FIELDS = (
    "session_id",
    "turn_id",
    "cwd",
    "hook_event_name",
    "permission_mode",
)


def sanitize_hook_event(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    event = {
        key: value
        for key in SAFE_FIELDS
        if isinstance((value := payload.get(key)), str)
        and 0 < len(value) <= 4096
    }
    event_name = event.get("hook_event_name")
    if event_name in EVENT_ALIASES:
        event["hook_event_name"] = EVENT_ALIASES[event_name]
    if event.get("hook_event_name") not in ALLOWED_EVENTS:
        return {}
    permission_mode = event.get("permission_mode")
    if (
        permission_mode is not None
        and permission_mode not in ALLOWED_PERMISSION_MODES
    ):
        event.pop("permission_mode", None)
    return event


def _safe_output(root: Path, output: Path) -> Path | None:
    try:
        root = root.resolve(strict=True)
        output_parent = output.parent.resolve(strict=True)
    except OSError:
        return None
    if output_parent != root or output.name != "hook-events.jsonl":
        return None
    try:
        metadata = output.lstat()
    except FileNotFoundError:
        return output
    except OSError:
        return None
    if (
        output.is_symlink()
        or not output.is_file()
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        return None
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError
        event = sanitize_hook_event(json.loads(raw.decode("utf-8")))
        output = _safe_output(args.root, args.output)
        if event and output is not None:
            line = (
                json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            descriptor = os.open(
                output,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, line)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:
        pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
