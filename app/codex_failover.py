from __future__ import annotations

import copy
import json
import os
import re
import stat
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from secrets import token_hex
from typing import Callable, Iterator

from .local_web_profiles import is_reparse_point, validate_profiles_root
from .otp_codex_manager_with_account_status import protect_sensitive_path


FAILOVER_DIR_NAME = ".failover"
MAX_REGISTRY_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_TASKS = 512
MAX_QUOTA_ACCOUNTS = 128
MAX_HOOK_FIELD_LENGTH = 4096
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
ACCOUNT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ALLOWED_HOOK_EVENTS = {"SessionStart", "Stop", "UserPromptSubmit"}
HOOK_EVENT_ALIASES = {
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
SAFE_HOOK_FIELDS = (
    "session_id",
    "turn_id",
    "cwd",
    "hook_event_name",
    "permission_mode",
)
TASK_STATUSES = {
    "active",
    "blocked",
    "completed",
    "quota_exhausted",
}
_FAILOVER_LOCK = threading.RLock()


class FailoverState(str, Enum):
    DISABLED = "disabled"
    OBSERVING = "observing"
    DRAINING = "draining"
    SWITCHING = "switching"
    RESUMING = "resuming"
    RUNNING = "running"
    ALL_EXHAUSTED = "all_exhausted"
    BLOCKED = "blocked"
    ERROR = "error"


ALLOWED_TRANSITIONS = {
    FailoverState.DISABLED: {FailoverState.OBSERVING},
    FailoverState.OBSERVING: {
        FailoverState.BLOCKED,
        FailoverState.DISABLED,
        FailoverState.DRAINING,
        FailoverState.ERROR,
    },
    FailoverState.DRAINING: {
        FailoverState.ALL_EXHAUSTED,
        FailoverState.BLOCKED,
        FailoverState.DISABLED,
        FailoverState.ERROR,
        FailoverState.SWITCHING,
    },
    FailoverState.SWITCHING: {
        FailoverState.BLOCKED,
        FailoverState.DISABLED,
        FailoverState.ERROR,
        FailoverState.RESUMING,
    },
    FailoverState.RESUMING: {
        FailoverState.BLOCKED,
        FailoverState.DISABLED,
        FailoverState.ERROR,
        FailoverState.RUNNING,
    },
    FailoverState.RUNNING: {
        FailoverState.BLOCKED,
        FailoverState.DISABLED,
        FailoverState.DRAINING,
        FailoverState.ERROR,
    },
    FailoverState.ALL_EXHAUSTED: {
        FailoverState.DISABLED,
        FailoverState.ERROR,
        FailoverState.OBSERVING,
    },
    FailoverState.BLOCKED: {
        FailoverState.DISABLED,
        FailoverState.ERROR,
        FailoverState.OBSERVING,
    },
    FailoverState.ERROR: {
        FailoverState.DISABLED,
        FailoverState.OBSERVING,
    },
}
PROMPT_BLOCK_STATES = {
    FailoverState.ALL_EXHAUSTED,
    FailoverState.BLOCKED,
    FailoverState.DRAINING,
    FailoverState.ERROR,
    FailoverState.RESUMING,
    FailoverState.SWITCHING,
}


class FailoverError(RuntimeError):
    pass


class FailoverPersistenceError(FailoverError):
    pass


class FailoverTransitionError(FailoverError):
    pass


def sanitize_hook_event(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    event = {
        key: value
        for key in SAFE_HOOK_FIELDS
        if isinstance((value := payload.get(key)), str)
        and 0 < len(value) <= MAX_HOOK_FIELD_LENGTH
        and "\x00" not in value
    }
    event_name = event.get("hook_event_name")
    if event_name in HOOK_EVENT_ALIASES:
        event["hook_event_name"] = HOOK_EVENT_ALIASES[event_name]
    if event.get("hook_event_name") not in ALLOWED_HOOK_EVENTS:
        return {}
    permission_mode = event.get("permission_mode")
    if (
        permission_mode is not None
        and permission_mode not in ALLOWED_PERMISSION_MODES
    ):
        event.pop("permission_mode", None)
    return event


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_snapshot() -> dict:
    return {
        "last_error": None,
        "quotas": {},
        "sequence": 0,
        "state": FailoverState.DISABLED.value,
        "tasks": {},
        "updated_at": None,
    }


def summarize_failover_snapshot(snapshot: object) -> dict[str, object]:
    clean = _validate_snapshot(snapshot)
    task_statuses = {
        status: sum(
            task["status"] == status
            for task in clean["tasks"].values()
        )
        for status in TASK_STATUSES
    }
    state = FailoverState(clean["state"])
    return {
        "schema_version": 1,
        "available": True,
        "enabled": state != FailoverState.DISABLED,
        "state": state.value,
        "updated_at": clean["updated_at"],
        "has_error": state in {
            FailoverState.BLOCKED,
            FailoverState.ERROR,
        },
        "tasks": {
            "total": len(clean["tasks"]),
            "active": task_statuses["active"],
            "completed": task_statuses["completed"],
            "blocked": task_statuses["blocked"],
            "quota_exhausted": task_statuses["quota_exhausted"],
            "eligible": sum(
                task["eligible"] for task in clean["tasks"].values()
            ),
        },
        "quotas": {
            "total": len(clean["quotas"]),
            "exhausted": sum(
                quota["exhausted"] for quota in clean["quotas"].values()
            ),
        },
    }


def read_failover_snapshot(profiles_root: Path) -> dict | None:
    """Read the atomic registry without creating or modifying failover state."""
    root_path = Path(profiles_root).resolve(strict=True)
    try:
        validate_profiles_root(root_path)
    except (OSError, ValueError) as error:
        raise FailoverPersistenceError(
            "Thư mục profile không an toàn."
        ) from error

    failover_root = root_path / FAILOVER_DIR_NAME
    try:
        root_metadata = failover_root.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise FailoverPersistenceError(
            "Không đọc được registry failover."
        ) from error
    if (
        failover_root.parent != root_path
        or is_reparse_point(failover_root)
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise FailoverPersistenceError("Registry failover không an toàn.")

    registry_file = failover_root / "registry.json"
    try:
        metadata = registry_file.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise FailoverPersistenceError(
            "Không đọc được registry failover."
        ) from error
    if (
        registry_file.parent != failover_root
        or is_reparse_point(registry_file)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_REGISTRY_BYTES
    ):
        raise FailoverPersistenceError("Registry failover không an toàn.")
    try:
        return _validate_snapshot(
            json.loads(registry_file.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise FailoverPersistenceError(
            "Không đọc được registry failover."
        ) from error


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} không hợp lệ.")
    return value


def _validate_account_key(value: object) -> str:
    if not isinstance(value, str) or not ACCOUNT_KEY_PATTERN.fullmatch(value):
        raise ValueError("Mã profile tài khoản không hợp lệ.")
    return value


def _validate_cwd(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_HOOK_FIELD_LENGTH
        or "\x00" in value
        or not Path(value).is_absolute()
    ):
        raise ValueError("Thư mục task không hợp lệ.")
    return value


def _optional_short_text(value: object, limit: int = 512) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= limit:
        raise ValueError("Giá trị text không hợp lệ.")
    return value


def _normalize_quota(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Snapshot quota không hợp lệ.")
    exhausted = payload.get("exhausted")
    if not isinstance(exhausted, bool):
        raise ValueError("Trạng thái quota không hợp lệ.")
    reached_type = payload.get("rate_limit_reached_type")
    if reached_type is not None:
        reached_type = _validate_identifier(
            reached_type,
            "Loại giới hạn",
        )
    source_windows = payload.get("windows")
    if not isinstance(source_windows, list) or len(source_windows) > 64:
        raise ValueError("Cửa sổ quota không hợp lệ.")
    windows: list[dict] = []
    for source in source_windows:
        if not isinstance(source, dict):
            raise ValueError("Cửa sổ quota không hợp lệ.")
        kind = source.get("kind")
        if kind not in {"primary", "secondary"}:
            raise ValueError("Loại cửa sổ quota không hợp lệ.")
        used_percent = source.get("used_percent")
        if used_percent is not None and (
            isinstance(used_percent, bool)
            or not isinstance(used_percent, (int, float))
            or not 0 <= float(used_percent) <= 100
        ):
            raise ValueError("Phần trăm quota không hợp lệ.")
        duration = source.get("window_duration_minutes")
        resets_at = source.get("resets_at")
        for number in (duration, resets_at):
            if number is not None and (
                isinstance(number, bool) or not isinstance(number, int)
            ):
                raise ValueError("Mốc quota không hợp lệ.")
        windows.append(
            {
                "kind": kind,
                "limit_id": _optional_short_text(
                    source.get("limit_id"),
                    128,
                ),
                "limit_name": _optional_short_text(
                    source.get("limit_name"),
                    128,
                ),
                "resets_at": resets_at,
                "used_percent": (
                    float(used_percent)
                    if used_percent is not None
                    else None
                ),
                "window_duration_minutes": duration,
            }
        )
    return {
        "exhausted": exhausted,
        "rate_limit_reached_type": reached_type,
        "windows": windows,
    }


def _validate_task(task_id: str, payload: object) -> dict:
    _validate_identifier(task_id, "Session ID")
    if not isinstance(payload, dict):
        raise FailoverPersistenceError("Task registry không hợp lệ.")
    permission_mode = payload.get("permission_mode")
    if permission_mode not in ALLOWED_PERMISSION_MODES:
        raise FailoverPersistenceError("Permission mode không hợp lệ.")
    status = payload.get("status")
    if status not in TASK_STATUSES:
        raise FailoverPersistenceError("Trạng thái task không hợp lệ.")
    eligible = payload.get("eligible")
    if not isinstance(eligible, bool):
        raise FailoverPersistenceError("Eligibility không hợp lệ.")
    turn_id = payload.get("turn_id")
    if turn_id is not None:
        _validate_identifier(turn_id, "Turn ID")
    return {
        "cwd": _validate_cwd(payload.get("cwd")),
        "eligible": eligible,
        "permission_mode": permission_mode,
        "session_id": task_id,
        "status": status,
        "turn_id": turn_id,
    }


def _validate_snapshot(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise FailoverPersistenceError("Registry failover không hợp lệ.")
    try:
        state = FailoverState(payload.get("state"))
    except ValueError as error:
        raise FailoverPersistenceError(
            "Trạng thái failover không hợp lệ."
        ) from error
    sequence = payload.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise FailoverPersistenceError("Sequence failover không hợp lệ.")
    source_tasks = payload.get("tasks")
    if not isinstance(source_tasks, dict) or len(source_tasks) > MAX_TASKS:
        raise FailoverPersistenceError("Task registry vượt giới hạn.")
    tasks = {
        task_id: _validate_task(task_id, task)
        for task_id, task in source_tasks.items()
    }
    source_quotas = payload.get("quotas")
    if (
        not isinstance(source_quotas, dict)
        or len(source_quotas) > MAX_QUOTA_ACCOUNTS
    ):
        raise FailoverPersistenceError("Quota registry vượt giới hạn.")
    quotas = {
        _validate_account_key(account_key): _normalize_quota(quota)
        for account_key, quota in source_quotas.items()
    }
    return {
        "last_error": _optional_short_text(payload.get("last_error")),
        "quotas": quotas,
        "sequence": sequence,
        "state": state.value,
        "tasks": tasks,
        "updated_at": _optional_short_text(
            payload.get("updated_at"),
            128,
        ),
    }


class FailoverCoordinator:
    def __init__(self, profiles_root: Path) -> None:
        self.profiles_root = Path(profiles_root).resolve(strict=True)
        try:
            validate_profiles_root(self.profiles_root)
        except (OSError, ValueError) as error:
            raise FailoverPersistenceError(
                "Thư mục profile không an toàn."
            ) from error
        self.root = self.profiles_root / FAILOVER_DIR_NAME
        try:
            self.root.mkdir(exist_ok=True)
            metadata = self.root.lstat()
        except OSError as error:
            raise FailoverPersistenceError(
                "Không thể tạo registry failover."
            ) from error
        if (
            self.root.parent != self.profiles_root
            or is_reparse_point(self.root)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise FailoverPersistenceError(
                "Registry failover không an toàn."
            )
        protect_sensitive_path(self.root)
        self.registry_file = self.root / "registry.json"
        self.journal_file = self.root / "recovery.jsonl"
        self.lock_file = self.root / ".lock"
        with _FAILOVER_LOCK, self._storage_lock():
            snapshot = self._load_latest()
            if not self.registry_file.exists():
                self._write_registry(snapshot)
            if not self.journal_file.exists():
                self.journal_file.touch()
                protect_sensitive_path(self.journal_file)
            self._snapshot = snapshot

    def snapshot(self) -> dict:
        with _FAILOVER_LOCK, self._storage_lock():
            self._snapshot = self._load_latest()
            return copy.deepcopy(self._snapshot)

    def enable(self) -> dict:
        def mutate(snapshot: dict) -> None:
            current = FailoverState(snapshot["state"])
            if current == FailoverState.DISABLED:
                snapshot["state"] = FailoverState.OBSERVING.value
            elif current in {
                FailoverState.ALL_EXHAUSTED,
                FailoverState.BLOCKED,
                FailoverState.ERROR,
            }:
                snapshot["state"] = FailoverState.OBSERVING.value
            snapshot["last_error"] = None

        return self._mutate("enabled", mutate)

    def disable(self) -> dict:
        def mutate(snapshot: dict) -> None:
            snapshot["state"] = FailoverState.DISABLED.value
            snapshot["last_error"] = None

        return self._mutate("disabled", mutate)

    def transition(
        self,
        target: FailoverState,
        reason: str | None = None,
    ) -> dict:
        target = FailoverState(target)
        clean_reason = _optional_short_text(reason)

        def mutate(snapshot: dict) -> None:
            current = FailoverState(snapshot["state"])
            if target == current:
                return
            if target not in ALLOWED_TRANSITIONS[current]:
                raise FailoverTransitionError(
                    f"Không thể chuyển {current.value} sang {target.value}."
                )
            snapshot["state"] = target.value
            snapshot["last_error"] = (
                clean_reason
                if target in {FailoverState.BLOCKED, FailoverState.ERROR}
                else None
            )

        return self._mutate(f"transition:{target.value}", mutate)

    def handle_hook_event(self, payload: object) -> dict:
        event = sanitize_hook_event(payload)
        if not event:
            raise ValueError("Hook event không hợp lệ.")
        event_name = event["hook_event_name"]
        session_id = _validate_identifier(
            event.get("session_id"),
            "Session ID",
        )
        cwd = event.get("cwd")
        permission_mode = event.get("permission_mode")
        turn_id = event.get("turn_id")
        if turn_id is not None:
            _validate_identifier(turn_id, "Turn ID")

        def mutate(snapshot: dict) -> None:
            if snapshot["state"] == FailoverState.DISABLED.value:
                return
            tasks = snapshot["tasks"]
            existing = tasks.get(session_id)
            if event_name == "Stop" and existing is None:
                return
            if cwd is None:
                if existing is None:
                    raise ValueError("Hook event thiếu thư mục task.")
                clean_cwd = existing["cwd"]
            else:
                clean_cwd = _validate_cwd(cwd)
            clean_mode = permission_mode or (
                existing["permission_mode"]
                if existing is not None
                else "default"
            )
            if clean_mode not in ALLOWED_PERMISSION_MODES:
                raise ValueError("Permission mode không hợp lệ.")
            status = (
                existing["status"] if existing is not None else "active"
            )
            if event_name == "SessionStart":
                status = "active"
            elif (
                event_name == "UserPromptSubmit"
                and snapshot["state"]
                in {
                    FailoverState.OBSERVING.value,
                    FailoverState.RUNNING.value,
                }
            ):
                status = "active"
            elif event_name == "Stop" and status != "quota_exhausted":
                status = "completed"
            tasks[session_id] = {
                "cwd": clean_cwd,
                "eligible": clean_mode == "dontAsk",
                "permission_mode": clean_mode,
                "session_id": session_id,
                "status": status,
                "turn_id": turn_id or (
                    existing.get("turn_id")
                    if existing is not None
                    else None
                ),
            }

        snapshot = self._mutate(f"hook:{event_name}", mutate)
        state = FailoverState(snapshot["state"])
        if (
            event_name == "UserPromptSubmit"
            and state in PROMPT_BLOCK_STATES
        ):
            return {
                "decision": "block",
                "reason": (
                    "OTP Codex đang điều phối tài khoản; "
                    "prompt mới tạm thời bị khóa."
                ),
            }
        return {}

    def handle_codex_event(
        self,
        account_key: str,
        event_type: str,
        payload: object,
    ) -> dict:
        clean_account_key = _validate_account_key(account_key)
        if event_type == "quota_updated":
            if not isinstance(payload, dict):
                raise ValueError("Quota event không hợp lệ.")
            quota = _normalize_quota(payload.get("quota"))

            def update_quota(snapshot: dict) -> None:
                if snapshot["state"] == FailoverState.DISABLED.value:
                    return
                snapshot["quotas"][clean_account_key] = quota

            return self._mutate("quota_updated", update_quota)

        if event_type != "usage_limit_exceeded":
            return self.snapshot()
        if not isinstance(payload, dict):
            raise ValueError("Usage-limit event không hợp lệ.")
        if payload.get("error_kind") != "usageLimitExceeded":
            return self.snapshot()
        thread_id = _validate_identifier(
            payload.get("thread_id"),
            "Thread ID",
        )
        turn_id = _validate_identifier(
            payload.get("turn_id"),
            "Turn ID",
        )

        def mark_exhausted(snapshot: dict) -> None:
            state = FailoverState(snapshot["state"])
            if state == FailoverState.DISABLED:
                return
            task = snapshot["tasks"].get(thread_id)
            if task is None:
                snapshot["state"] = FailoverState.BLOCKED.value
                snapshot["last_error"] = (
                    "Không tìm thấy task cho tín hiệu hết quota."
                )
                return
            if (
                task["status"] == "quota_exhausted"
                and task["turn_id"] == turn_id
            ):
                return
            task["turn_id"] = turn_id
            if not task["eligible"]:
                task["status"] = "blocked"
                snapshot["state"] = FailoverState.BLOCKED.value
                snapshot["last_error"] = (
                    "Task không ở chế độ Never ask."
                )
                return
            task["status"] = "quota_exhausted"
            if state in {
                FailoverState.OBSERVING,
                FailoverState.RUNNING,
            }:
                snapshot["state"] = FailoverState.DRAINING.value
                snapshot["last_error"] = None

        return self._mutate("usage_limit_exceeded", mark_exhausted)

    def _mutate(
        self,
        kind: str,
        mutator: Callable[[dict], None],
    ) -> dict:
        with _FAILOVER_LOCK, self._storage_lock():
            current = self._load_latest()
            candidate = copy.deepcopy(current)
            mutator(candidate)
            if candidate == current:
                self._snapshot = current
                return copy.deepcopy(current)
            candidate["sequence"] = current["sequence"] + 1
            candidate["updated_at"] = _utc_now()
            candidate = _validate_snapshot(candidate)
            self._append_journal(kind, candidate)
            self._write_registry(candidate)
            self._snapshot = candidate
            return copy.deepcopy(candidate)

    @contextmanager
    def _storage_lock(self) -> Iterator[None]:
        self._validate_storage_file(self.lock_file, allow_missing=True)
        with self.lock_file.open("a+b") as stream:
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
            protect_sensitive_path(self.lock_file)
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _validate_storage_file(
        self,
        path: Path,
        *,
        allow_missing: bool,
    ) -> None:
        if path.parent != self.root:
            raise FailoverPersistenceError(
                "Đường dẫn failover không hợp lệ."
            )
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise FailoverPersistenceError(
                "File failover không tồn tại."
            )
        except OSError as error:
            raise FailoverPersistenceError(
                "Không đọc được file failover."
            ) from error
        if is_reparse_point(path) or not stat.S_ISREG(metadata.st_mode):
            raise FailoverPersistenceError(
                "File failover không an toàn."
            )

    def _load_json_file(self, path: Path) -> dict | None:
        self._validate_storage_file(path, allow_missing=True)
        if not path.exists():
            return None
        try:
            if path.stat().st_size > MAX_REGISTRY_BYTES:
                raise FailoverPersistenceError(
                    "Registry failover vượt giới hạn."
                )
            return _validate_snapshot(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except FailoverPersistenceError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None

    def _load_journal_snapshot(self) -> dict | None:
        self._validate_storage_file(self.journal_file, allow_missing=True)
        if not self.journal_file.exists():
            return None
        try:
            if self.journal_file.stat().st_size > MAX_JOURNAL_BYTES:
                raise FailoverPersistenceError(
                    "Recovery journal vượt giới hạn."
                )
            latest: dict | None = None
            for line in self.journal_file.read_text(
                encoding="utf-8"
            ).splitlines():
                try:
                    entry = json.loads(line)
                    snapshot = _validate_snapshot(entry.get("snapshot"))
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    latest is None
                    or snapshot["sequence"] > latest["sequence"]
                ):
                    latest = snapshot
            return latest
        except FailoverPersistenceError:
            raise
        except (OSError, UnicodeError) as error:
            raise FailoverPersistenceError(
                "Không đọc được recovery journal."
            ) from error

    def _load_latest(self) -> dict:
        registry_exists = self.registry_file.exists()
        registry = self._load_json_file(self.registry_file)
        journal = self._load_journal_snapshot()
        if registry is None and journal is None:
            if registry_exists:
                raise FailoverPersistenceError(
                    "Không thể phục hồi registry failover."
                )
            return _default_snapshot()
        if registry is None:
            return journal or _default_snapshot()
        if journal is None:
            return registry
        return (
            journal
            if journal["sequence"] > registry["sequence"]
            else registry
        )

    def _write_registry(self, snapshot: dict) -> None:
        payload = (
            json.dumps(
                snapshot,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_REGISTRY_BYTES:
            raise FailoverPersistenceError(
                "Registry failover vượt giới hạn."
            )
        temporary = self.root / f".registry.{token_hex(8)}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            protect_sensitive_path(temporary)
            os.replace(temporary, self.registry_file)
            protect_sensitive_path(self.registry_file)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise FailoverPersistenceError(
                "Không thể ghi registry failover."
            ) from error

    def _append_journal(self, kind: str, snapshot: dict) -> None:
        self._validate_storage_file(self.journal_file, allow_missing=True)
        entry = {
            "kind": _optional_short_text(kind, 128),
            "sequence": snapshot["sequence"],
            "snapshot": snapshot,
        }
        line = (
            json.dumps(
                entry,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        try:
            compact = (
                self.journal_file.exists()
                and self.journal_file.stat().st_size + len(line)
                > MAX_JOURNAL_BYTES
            )
            if compact:
                temporary = self.root / f".journal.{token_hex(8)}.tmp"
                try:
                    with temporary.open("xb") as stream:
                        stream.write(line)
                        stream.flush()
                        os.fsync(stream.fileno())
                    protect_sensitive_path(temporary)
                    os.replace(temporary, self.journal_file)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                descriptor = os.open(
                    self.journal_file,
                    os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                    0o600,
                )
                try:
                    os.write(descriptor, line)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            protect_sensitive_path(self.journal_file)
        except OSError as error:
            raise FailoverPersistenceError(
                "Không thể ghi recovery journal."
            ) from error
