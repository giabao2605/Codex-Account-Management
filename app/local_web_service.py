from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .codex_failover import (
    FailoverPersistenceError,
    read_failover_snapshot,
    summarize_failover_snapshot,
)
from .codex_sync import (
    CodexProfileSession,
    CodexReloginRequired,
    normalize_quota_snapshot,
)
from .local_web_accounts import (
    AccountConflictError,
    append_new_account,
    find_account_conflict,
    parse_new_account,
)
from .local_web_profiles import (
    UnsafeProfilePathError,
    delete_profile_directory,
    delete_staged_profile_directories,
    restore_staged_profile_directory,
    stage_profile_directory_for_deletion,
    validate_profiles_root,
)
from .otp_codex_manager_with_account_status import (
    Account,
    CodexInfo,
    build_codex_command,
    build_codex_environment,
    create_totp,
    decrypt_text,
    detect_banned_account,
    encrypt_text,
    extract_best_rate_limit,
    format_cycle,
    format_reset_time,
    profile_directory_for,
    protect_sensitive_path,
    protect_sensitive_tree,
    requires_codex_relogin,
)
from .trusted_clock import TrustedClock, get_default_trusted_clock
from .token_usage import (
    TokenUsageCacheEntry,
    build_token_usage_statistics,
    normalize_token_usage,
)


class AccountNotFoundError(LookupError):
    pass


_ATTENTION_TERMS = (
    "lỗi",
    "khóa",
    "banned",
    "chưa",
    "đăng nhập",
    "đăng xuất",
    "sai tài khoản",
)
_QUOTA_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")
_TOKEN_USAGE_CACHE_TTL_SECONDS = 300.0


def account_display_sort_key(
    row: dict[str, object],
) -> tuple[int, float, str]:
    status = (
        f"{row.get('account_state', '')} "
        f"{row.get('sync_status', '')}"
    ).casefold()
    email = str(row.get("email", "")).casefold()
    quota_match = _QUOTA_PATTERN.search(
        str(row.get("quota_remaining", ""))
    )
    quota = (
        float(quota_match.group(0).replace(",", "."))
        if quota_match is not None
        else None
    )

    if any(term in status for term in _ATTENTION_TERMS):
        return (0, 0, email)
    if quota is None:
        return (2, 0, email)
    if quota <= 0:
        return (3, 0, email)
    return (1, -quota, email)


def _format_remaining_percent(value: object) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        used_percent = float(value)
    except (TypeError, ValueError):
        return "—"
    remaining = max(0.0, min(100.0, 100.0 - used_percent))
    return (
        f"{int(round(remaining))}%"
        if abs(remaining - round(remaining)) < 0.05
        else f"{remaining:.1f}%"
    )


def _format_quota_windows(result: dict) -> tuple[dict[str, str], ...]:
    limits = result.get("limits")
    quota = result.get("quota")
    if not isinstance(quota, dict) and isinstance(limits, dict):
        quota = normalize_quota_snapshot(limits).to_dict()
    windows = quota.get("windows") if isinstance(quota, dict) else None
    candidates = (
        [window for window in windows if isinstance(window, dict)]
        if isinstance(windows, list)
        else []
    )
    preferred_limit_id = (
        "codex"
        if any(window.get("limit_id") == "codex" for window in candidates)
        else next(
            (
                window.get("limit_id")
                for window in candidates
                if window.get("limit_id") is not None
            ),
            None,
        )
    )
    if preferred_limit_id is not None:
        candidates = [
            window
            for window in candidates
            if window.get("limit_id") == preferred_limit_id
        ]

    def duration(window: dict) -> int:
        value = window.get(
            "windowDurationMins",
            window.get("window_duration_minutes"),
        )
        try:
            return int(value)
        except (TypeError, ValueError):
            return 2**31 - 1

    return tuple(
        {
            "quota_remaining": _format_remaining_percent(
                window.get("usedPercent", window.get("used_percent"))
            ),
            "quota_cycle": format_cycle(
                window.get(
                    "windowDurationMins",
                    window.get("window_duration_minutes"),
                )
            ),
            "quota_reset_at": format_reset_time(
                window.get("resetsAt", window.get("resets_at"))
            ),
        }
        for window in sorted(candidates, key=duration)[:2]
    )


class LocalWebService:
    def __init__(
        self,
        data_file: Path,
        profiles_dir: Path,
        enable_codex: bool = True,
        refresh_interval_seconds: int = 60,
        trusted_clock: TrustedClock | None = None,
    ) -> None:
        self.data_file = Path(data_file)
        self.profiles_dir = Path(profiles_dir)
        self.enable_codex = enable_codex
        self.refresh_interval_seconds = refresh_interval_seconds
        self._trusted_clock = trusted_clock or get_default_trusted_clock()
        self._owns_trusted_clock = trusted_clock is not None
        self.csrf_token = secrets.token_urlsafe(32)
        self.access_token = secrets.token_urlsafe(48)
        self._lock = threading.RLock()
        self._account_write_lock = threading.Lock()
        self._profile_locks_lock = threading.Lock()
        self._profile_locks: dict[str, threading.RLock] = {}
        self._sync_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._accounts: tuple[Account, ...] = ()
        self._codex_info: dict[str, CodexInfo] = {}
        self._token_usage_cache: dict[str, TokenUsageCacheEntry] = {}
        self._sessions: dict[str, CodexProfileSession] = {}
        self._login_processes: dict[str, subprocess.Popen] = {}
        self._relogin_required: set[str] = set()
        self._started = False
        self._sync_status = "Chưa đồng bộ"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._stop_event.clear()
            self.data_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self.profiles_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
            validate_profiles_root(self.profiles_dir)
            try:
                delete_staged_profile_directories(self.profiles_dir)
            except (OSError, UnsafeProfilePathError):
                pass
            protect_sensitive_tree(self.profiles_dir)

            if self.data_file.exists():
                protect_sensitive_path(self.data_file)
            self._accounts = self._load_accounts()
            self._sync_codex_info_locked()
            self._started = True

        self._trusted_clock.start()

        if self.enable_codex:
            scheduler_thread = threading.Thread(
                target=self._scheduler,
                name="codex-web-scheduler",
                daemon=True,
            )
            with self._lock:
                self._scheduler_thread = scheduler_thread
            scheduler_thread.start()
            self.refresh_async()

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions = {}
            login_processes = tuple(self._login_processes.values())
            self._login_processes = {}
            scheduler_thread = self._scheduler_thread
            self._scheduler_thread = None
            self._started = False
        if (
            scheduler_thread is not None
            and scheduler_thread is not threading.current_thread()
        ):
            scheduler_thread.join(timeout=2)
        for session in sessions:
            session.close()
        for process in login_processes:
            self._terminate_login_process(process)
        if self._owns_trusted_clock:
            self._trusted_clock.close()

    def state(self) -> dict:
        time_sync = self._trusted_clock.status()
        has_trusted_time = time_sync["last_synced_at"] is not None
        now = int(self._trusted_clock.now()) if has_trusted_time else None
        with self._lock:
            accounts = tuple(self._accounts)
            info_by_key = dict(self._codex_info)
            sync_status = self._sync_status
        rows = []
        for account in accounts:
            key = account.email.casefold()
            info = info_by_key.get(
                key,
                CodexInfo(stored_email=account.email),
            )
            remaining_seconds = None if now is None else (
                account.totp.interval - now % account.totp.interval
            )
            rows.append(
                {
                    "id": self.account_id(account.email),
                    "email": account.email,
                    "otp": None if now is None else account.totp.at(now),
                    "otp_remaining_seconds": remaining_seconds,
                    "quota_remaining": info.remaining_percent,
                    "quota_cycle": info.cycle,
                    "quota_reset_at": info.reset_at,
                    "quota_windows": [
                        dict(window) for window in info.quota_windows
                    ],
                    "plan_type": info.plan_type,
                    "account_state": info.account_state,
                    "sync_status": info.status,
                    "last_sync": info.last_sync,
                }
            )
        recommendation_queue = self._recommend_accounts(rows)
        return {
            "accounts": sorted(rows, key=account_display_sort_key),
            "sync_status": sync_status,
            "refresh_interval_seconds": self.refresh_interval_seconds,
            "recommendation": (
                recommendation_queue[0] if recommendation_queue else None
            ),
            "recommendation_queue": recommendation_queue,
            "usage_statistics": self._usage_statistics(rows),
            "time_sync": time_sync,
        }

    def failover_status(self) -> dict[str, object]:
        has_error = False
        try:
            snapshot = read_failover_snapshot(self.profiles_dir)
        except (FailoverPersistenceError, OSError, ValueError):
            snapshot = None
            has_error = True
        if snapshot is not None:
            return summarize_failover_snapshot(snapshot)
        return {
            "schema_version": 1,
            "available": False,
            "enabled": False,
            "state": "error" if has_error else "disabled",
            "updated_at": None,
            "has_error": has_error,
            "tasks": {
                "total": 0,
                "active": 0,
                "completed": 0,
                "blocked": 0,
                "quota_exhausted": 0,
                "eligible": 0,
            },
            "quotas": {"total": 0, "exhausted": 0},
        }

    def token_usage_statistics(self) -> dict[str, object]:
        with self._lock:
            accounts = [
                {
                    "account_id": self.account_id(account.email),
                    "email": account.email,
                }
                for account in self._accounts
            ]
            entries = dict(self._token_usage_cache)

        return build_token_usage_statistics(
            accounts=accounts,
            entries=entries,
            now=self._trusted_local_datetime(),
        )

    def _trusted_local_datetime(self) -> datetime:
        return datetime.fromtimestamp(
            self._trusted_clock.now(),
        ).astimezone()

    def check_account(self, raw_text: str) -> dict[str, object]:
        try:
            candidate = parse_new_account(raw_text)
        except ValueError as error:
            return {
                "valid": False,
                "conflict": "invalid",
                "message": str(error),
            }

        with self._lock:
            conflict = find_account_conflict(self._accounts, candidate)
        if conflict is not None:
            return {
                "valid": False,
                "conflict": conflict,
                "message": str(AccountConflictError(conflict)),
            }
        return {
            "valid": True,
            "conflict": None,
            "message": "Tài khoản có thể được thêm.",
        }

    def import_accounts(self, raw_text: str) -> dict[str, object]:
        with self._account_write_lock:
            with self._lock:
                current_accounts = tuple(self._accounts)
            new_accounts, candidate = append_new_account(
                current_accounts,
                raw_text,
            )
            self._save_accounts(new_accounts)

            with self._lock:
                self._accounts = new_accounts
                self._sync_codex_info_locked()

        self.refresh_async({self.account_id(candidate.email)})
        return {
            "total": len(new_accounts),
            "email": candidate.email,
        }

    def delete_account(self, account_id: str) -> bool:
        with self._account_write_lock:
            with self._lock:
                account = self._find_account_locked(account_id)
                key = account.email.casefold()
                profile_dir = self.profile_directory(account.email)
                current_accounts = tuple(self._accounts)
                new_accounts = tuple(
                    item
                    for item in current_accounts
                    if item.email.casefold() != key
            )

            with self._profile_lock_for(key):
                if not self._stop_login_process(key):
                    raise OSError("Không thể dừng đăng nhập Codex.")
                if not self._close_session(key):
                    raise OSError("Không thể dừng Codex App Server.")
                delete_staged_profile_directories(
                    self.profiles_dir,
                    profile_dir,
                )
                staged_profile_dir = (
                    stage_profile_directory_for_deletion(
                        self.profiles_dir,
                        profile_dir,
                    )
                )
                try:
                    self._save_accounts(new_accounts)
                except (OSError, UnsafeProfilePathError):
                    if staged_profile_dir is not None:
                        restore_staged_profile_directory(
                            self.profiles_dir,
                            staged_profile_dir,
                            profile_dir,
                        )
                    self._save_accounts(current_accounts)
                    raise

                with self._lock:
                    self._accounts = new_accounts
                    self._codex_info.pop(key, None)
                    self._token_usage_cache.pop(key, None)
                    self._relogin_required.discard(key)

                if staged_profile_dir is not None:
                    delete_profile_directory(
                        self.profiles_dir,
                        staged_profile_dir,
                    )

        return True

    def unlink_profile(self, account_id: str) -> bool:
        with self._account_write_lock:
            account, key, profile_dir = self._profile_operation_context(
                account_id
            )
            with self._profile_lock_for(key):
                if not self._stop_login_process(key):
                    raise OSError("Không thể dừng đăng nhập Codex.")
                if not self._close_session(key):
                    raise OSError("Không thể dừng Codex App Server.")
                delete_staged_profile_directories(
                    self.profiles_dir,
                    profile_dir,
                )
                staged_profile_dir = stage_profile_directory_for_deletion(
                    self.profiles_dir,
                    profile_dir,
                )
                with self._lock:
                    self._token_usage_cache.pop(key, None)
                    self._relogin_required.discard(key)
                    current = self._codex_info.get(key)
                    if current is not None:
                        self._codex_info[key] = replace(
                            current,
                            stored_email=account.email,
                            codex_email="—",
                            remaining_percent="—",
                            cycle="—",
                            reset_at="—",
                            quota_windows=(),
                            plan_type="—",
                            account_state="Chưa xác định",
                            status="Chưa liên kết",
                            last_sync="—",
                        )
                if staged_profile_dir is not None:
                    delete_profile_directory(
                        self.profiles_dir,
                        staged_profile_dir,
                    )
        return True

    def sensitive_value(
        self,
        account_id: str,
        field: str,
    ) -> str:
        with self._lock:
            account = self._find_account_locked(account_id)

        if field == "password":
            return account.password

        if field == "secret":
            return account.secret

        raise ValueError("Trường dữ liệu không hợp lệ.")

    def update_password(self, account_id: str, password: str) -> bool:
        if not password.strip():
            raise ValueError("Mật khẩu không được để trống.")
        if len(password) > 4096:
            raise ValueError("Mật khẩu không được dài quá 4096 ký tự.")

        with self._account_write_lock:
            with self._lock:
                account = self._find_account_locked(account_id)
                new_accounts = tuple(
                    replace(item, password=password)
                    if item is account
                    else item
                    for item in self._accounts
                )

            self._save_accounts(new_accounts)

            with self._lock:
                self._accounts = new_accounts

        return True

    def refresh_async(
        self,
        account_ids: set[str] | None = None,
        *,
        force_token_usage: bool = False,
    ) -> bool:
        if not self.enable_codex:
            return False

        if not self._sync_lock.acquire(blocking=False):
            return False

        with self._lock:
            accounts = tuple(
                account
                for account in self._accounts
                if account_ids is None
                or self.account_id(account.email)
                in account_ids
            )
            self._sync_status = (
                f"Đang đồng bộ {len(accounts)} tài khoản..."
            )

        threading.Thread(
            target=self._run_refresh,
            args=(accounts, force_token_usage),
            name="codex-web-refresh",
            daemon=True,
        ).start()
        return True

    def login(self, account_id: str) -> None:
        with self._lock:
            account = self._find_account_locked(account_id)
            key = account.email.casefold()
        with self._profile_lock_for(key):
            self._login_locked(account_id)

    def _login_locked(self, account_id: str) -> None:
        if not self.enable_codex:
            raise RuntimeError("Đồng bộ Codex đang tắt.")

        with self._lock:
            account = self._find_account_locked(account_id)
            key = account.email.casefold()

        command = build_codex_command("login")
        if command is None:
            raise RuntimeError("Không tìm thấy Codex CLI.")

        with self._lock:
            self._token_usage_cache.pop(key, None)
            self._relogin_required.discard(key)

        if not self._close_session(key):
            raise RuntimeError("Không thể dừng Codex App Server.")

        if not self._stop_login_process(key):
            raise RuntimeError("Không thể dừng đăng nhập Codex trước đó.")

        profile_dir = self.profile_directory(account.email)
        creation_flags = 0

        if os.name == "nt":
            creation_flags = getattr(
                subprocess,
                "CREATE_NEW_CONSOLE",
                0,
            )

        try:
            process = subprocess.Popen(
                command,
                env=build_codex_environment(profile_dir),
                creationflags=creation_flags,
            )
        except (OSError, subprocess.SubprocessError) as error:
            with self._lock:
                current = self._codex_info.get(key)
                if current is not None:
                    self._codex_info[key] = replace(
                        current,
                        status="Không thể mở đăng nhập Codex",
                    )
            raise RuntimeError("Không thể mở đăng nhập Codex.") from error

        with self._lock:
            self._login_processes = {
                **self._login_processes,
                key: process,
            }
            current = self._codex_info.get(key)
            if current is not None:
                self._codex_info[key] = replace(
                    current,
                    status="Đang chờ đăng nhập...",
                )

        def wait_for_login() -> None:
            return_code = process.wait()

            with self._lock:
                if self._login_processes.get(key) is not process:
                    return
                self._login_processes = {
                    process_key: current_process
                    for process_key, current_process
                    in self._login_processes.items()
                    if process_key != key
                }
                current = self._codex_info.get(key)

                if current is not None:
                    status = (
                        "Đăng nhập xong, đang đồng bộ..."
                        if return_code == 0
                        else "Đăng nhập chưa hoàn tất"
                    )
                    self._codex_info[key] = replace(
                        current,
                        status=status,
                    )

            if return_code == 0:
                self.refresh_async({account_id})

        threading.Thread(
            target=wait_for_login,
            name="codex-web-login",
            daemon=True,
        ).start()

    @staticmethod
    def account_id(email: str) -> str:
        return hashlib.sha256(
            email.casefold().encode("utf-8")
        ).hexdigest()[:16]

    def profile_directory(self, email: str) -> Path:
        return self.profiles_dir / profile_directory_for(email).name

    @staticmethod
    def _recommend_account(rows: list[dict[str, object]]) -> dict | None:
        recommendations = LocalWebService._recommend_accounts(rows)
        return recommendations[0] if recommendations else None

    @staticmethod
    def _recommend_accounts(
        rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        candidates: list[tuple[float, float, str, dict[str, str]]] = []
        for row in rows:
            if str(row.get("account_state")) != "Hoạt động bình thường":
                continue
            quota_match = _QUOTA_PATTERN.search(
                str(row.get("quota_remaining", ""))
            )
            if quota_match is None:
                continue
            quota = float(quota_match.group(0).replace(",", "."))
            status = str(row.get("sync_status", "")).casefold()
            if quota <= 0 or any(term in status for term in _ATTENTION_TERMS):
                continue
            candidates.append(
                (
                    -quota,
                    LocalWebService._reset_sort_key(
                        str(row.get("quota_reset_at", "—"))
                    ),
                    str(row.get("email", "")).casefold(),
                    {
                        "account_id": str(row.get("id", "")),
                        "email": str(row.get("email", "")),
                        "quota_remaining": str(
                            row.get("quota_remaining", "—")
                        ),
                        "quota_reset_at": str(
                            row.get("quota_reset_at", "—")
                        ),
                    },
                )
            )
        recommendations: list[dict[str, object]] = []
        for rank, (_, _, _, candidate) in enumerate(
            sorted(candidates),
            start=1,
        ):
            quota = candidate["quota_remaining"]
            reset = candidate["quota_reset_at"]
            recommendations.append(
                {
                    **candidate,
                    "rank": rank,
                    "reason": (
                        f"Hoạt động bình thường · còn {quota} quota · "
                        f"reset {reset}"
                    ),
                }
            )
        return recommendations

    @staticmethod
    def _usage_statistics(rows: list[dict[str, object]]) -> dict:
        account_statistics: list[dict[str, object]] = []
        known_remaining: list[float] = []
        plan_counts: Counter[str] = Counter()
        reset_candidates: list[tuple[float, str]] = []
        usable_accounts = 0
        attention_accounts = 0
        low_quota_accounts = 0
        exhausted_accounts = 0
        unknown_quota_accounts = 0
        stale_quota_accounts = 0

        for row in rows:
            plan_type = str(row.get("plan_type", "—"))
            plan_counts[plan_type] += 1
            reset_at = str(row.get("quota_reset_at", "—"))
            quota_match = _QUOTA_PATTERN.search(
                str(row.get("quota_remaining", ""))
            )
            raw_remaining = (
                max(
                    0.0,
                    min(
                        100.0,
                        float(quota_match.group(0).replace(",", ".")),
                    ),
                )
                if quota_match is not None
                else None
            )
            status = (
                f"{row.get('account_state', '')} "
                f"{row.get('sync_status', '')}"
            ).casefold()
            needs_attention = any(
                term in status for term in _ATTENTION_TERMS
            )
            quota_is_current = (
                raw_remaining is not None
                and str(row.get("account_state"))
                == "Hoạt động bình thường"
                and not needs_attention
            )
            quota_is_stale = raw_remaining is not None and not quota_is_current
            remaining = raw_remaining if quota_is_current else None
            used = None if remaining is None else 100.0 - remaining
            is_usable = (
                quota_is_current
                and remaining is not None
                and remaining > 0
            )

            if remaining is not None:
                known_remaining.append(remaining)
                reset_sort_key = LocalWebService._reset_sort_key(reset_at)
                if reset_sort_key != float("inf"):
                    reset_candidates.append((reset_sort_key, reset_at))
                if remaining <= 0:
                    exhausted_accounts += 1
            elif quota_is_stale:
                stale_quota_accounts += 1
            else:
                unknown_quota_accounts += 1
            if is_usable:
                usable_accounts += 1
                if remaining is not None and remaining <= 20:
                    low_quota_accounts += 1
            if needs_attention:
                attention_accounts += 1

            account_statistics.append(
                {
                    "account_id": str(row.get("id", "")),
                    "email": str(row.get("email", "")),
                    "quota_remaining_percent": remaining,
                    "quota_used_percent": used,
                    "quota_cycle": (
                        str(row.get("quota_cycle", "—"))
                        if quota_is_current
                        else "—"
                    ),
                    "quota_reset_at": reset_at if quota_is_current else "—",
                    "plan_type": plan_type,
                    "account_state": str(
                        row.get("account_state", "Chưa xác định")
                    ),
                    "sync_status": str(row.get("sync_status", "—")),
                    "last_sync": str(row.get("last_sync", "—")),
                    "is_usable": is_usable,
                    "needs_attention": needs_attention,
                    "quota_is_stale": quota_is_stale,
                }
            )

        average_remaining = (
            round(sum(known_remaining) / len(known_remaining), 2)
            if known_remaining
            else None
        )
        sorted_remaining = sorted(known_remaining)
        middle = len(sorted_remaining) // 2
        median_remaining = None
        if sorted_remaining:
            median_remaining = (
                sorted_remaining[middle]
                if len(sorted_remaining) % 2
                else round(
                    (
                        sorted_remaining[middle - 1]
                        + sorted_remaining[middle]
                    )
                    / 2,
                    2,
                )
            )
        return {
            "schema_version": 1,
            "history_available": False,
            "source": "codex_rate_limits_snapshot",
            "generated_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "total_accounts": len(rows),
            "quota_known_accounts": len(known_remaining),
            "quota_unknown_accounts": unknown_quota_accounts,
            "stale_quota_accounts": stale_quota_accounts,
            "usable_accounts": usable_accounts,
            "attention_accounts": attention_accounts,
            "low_quota_accounts": low_quota_accounts,
            "exhausted_accounts": exhausted_accounts,
            "average_remaining_percent": average_remaining,
            "average_used_percent": (
                round(100.0 - average_remaining, 2)
                if average_remaining is not None
                else None
            ),
            "minimum_remaining_percent": (
                min(known_remaining) if known_remaining else None
            ),
            "maximum_remaining_percent": (
                max(known_remaining) if known_remaining else None
            ),
            "median_remaining_percent": median_remaining,
            "next_reset_at": (
                min(reset_candidates)[1] if reset_candidates else None
            ),
            "plan_distribution": [
                {"plan_type": plan_type, "count": count}
                for plan_type, count in sorted(
                    plan_counts.items(),
                    key=lambda item: (-item[1], item[0].casefold()),
                )
            ],
            "accounts": sorted(
                account_statistics,
                key=lambda account: str(account["email"]).casefold(),
            ),
        }

    @staticmethod
    def _reset_sort_key(value: str) -> float:
        try:
            now = datetime.now()
            reset_at = datetime.strptime(
                value,
                "%d/%m %H:%M",
            ).replace(year=now.year)
            if reset_at < now:
                reset_at = reset_at.replace(year=now.year + 1)
            return reset_at.timestamp()
        except (TypeError, ValueError):
            return float("inf")

    def _profile_operation_context(
        self,
        account_id: str,
    ) -> tuple[Account, str, Path]:
        with self._lock:
            account = self._find_account_locked(account_id)
        key = account.email.casefold()
        return account, key, self.profile_directory(account.email)

    def _profile_lock_for(self, key: str) -> threading.RLock:
        with self._profile_locks_lock:
            lock = self._profile_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._profile_locks = {**self._profile_locks, key: lock}
            return lock

    @staticmethod
    def _terminate_login_process(process: subprocess.Popen) -> bool:
        try:
            if process.poll() is not None:
                return True
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            return True
        except (
            OSError,
            subprocess.SubprocessError,
            subprocess.TimeoutExpired,
        ):
            return False

    def _stop_login_process(self, key: str) -> bool:
        with self._lock:
            process = self._login_processes.get(key)
            if process is None:
                return True
            self._login_processes = {
                process_key: current_process
                for process_key, current_process
                in self._login_processes.items()
                if process_key != key
            }

        terminated = self._terminate_login_process(process)
        if not terminated:
            try:
                terminated = process.poll() is not None
            except (OSError, subprocess.SubprocessError):
                terminated = False
        if terminated:
            return True

        with self._lock:
            if key not in self._login_processes:
                self._login_processes = {
                    **self._login_processes,
                    key: process,
                }
        return False

    def _load_accounts(self) -> tuple[Account, ...]:
        if not self.data_file.exists():
            return ()

        raw_data = json.loads(
            self.data_file.read_text(encoding="utf-8")
        )
        accounts: list[Account] = []
        seen_emails: set[str] = set()
        seen_secrets: set[str] = set()

        for item in raw_data.get("accounts", []):
            try:
                email = decrypt_text(item["email"])
                password = decrypt_text(item["password"])
                secret = decrypt_text(item["secret"])
                email_key = email.casefold()

                if (
                    email_key in seen_emails
                    or secret in seen_secrets
                ):
                    continue

                accounts.append(
                    Account(
                        email=email,
                        password=password,
                        secret=secret,
                        totp=create_totp(secret),
                    )
                )
                seen_emails.add(email_key)
                seen_secrets.add(secret)
            except Exception:
                continue

        return tuple(accounts)

    def _save_accounts(
        self,
        accounts: tuple[Account, ...],
    ) -> None:
        output = {
            "version": 1,
            "accounts": [
                {
                    "email": encrypt_text(account.email),
                    "password": encrypt_text(account.password),
                    "secret": encrypt_text(account.secret),
                }
                for account in accounts
            ],
        }
        temporary_file = self.data_file.with_name(
            f".{self.data_file.name}.{secrets.token_hex(8)}.tmp"
        )
        try:
            temporary_file.write_text(
                json.dumps(output, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            protect_sensitive_path(temporary_file)
            temporary_file.replace(self.data_file)
        finally:
            temporary_file.unlink(missing_ok=True)

    def _find_account_locked(
        self,
        account_id: str,
    ) -> Account:
        account = next(
            (
                item
                for item in self._accounts
                if self.account_id(item.email)
                == account_id
            ),
            None,
        )

        if account is None:
            raise AccountNotFoundError(account_id)

        return account

    def _sync_codex_info_locked(self) -> None:
        current_keys = {
            account.email.casefold()
            for account in self._accounts
        }
        self._codex_info = {
            key: value
            for key, value in self._codex_info.items()
            if key in current_keys
        }
        self._token_usage_cache = {
            key: value
            for key, value in self._token_usage_cache.items()
            if key in current_keys
        }

        for account in self._accounts:
            key = account.email.casefold()
            current = self._codex_info.get(key)
            self._codex_info[key] = (
                replace(
                    current,
                    stored_email=account.email,
                )
                if current is not None
                else CodexInfo(stored_email=account.email)
            )

    def _scheduler(self) -> None:
        while not self._stop_event.wait(
            self.refresh_interval_seconds
        ):
            self.refresh_async()

    def _run_refresh(
        self,
        accounts: tuple[Account, ...],
        force_token_usage: bool,
    ) -> None:
        summary = {
            "success": 0,
            "relogin": 0,
            "unlinked": 0,
            "error": 0,
        }

        try:
            with ThreadPoolExecutor(
                max_workers=min(4, max(1, len(accounts))),
                thread_name_prefix="codex-web-account",
            ) as executor:
                futures = [
                    executor.submit(
                        self._refresh_account,
                        account,
                        force_token_usage,
                    )
                    for account in accounts
                ]

                for future in as_completed(futures):
                    try:
                        summary[future.result()] += 1
                    except Exception:
                        summary["error"] += 1
        finally:
            with self._lock:
                self._sync_status = (
                    f"{summary['success']} thành công, "
                    f"{summary['relogin']} cần đăng nhập, "
                    f"{summary['unlinked']} chưa liên kết, "
                    f"{summary['error']} lỗi tạm thời | "
                    f"{datetime.now().strftime('%H:%M:%S')}"
                )
            self._sync_lock.release()

    def _refresh_account(
        self,
        account: Account,
        force_token_usage: bool = False,
    ) -> str:
        key = account.email.casefold()
        with self._profile_lock_for(key):
            return self._refresh_account_locked(
                account,
                force_token_usage,
            )

    def _refresh_account_locked(
        self,
        account: Account,
        force_token_usage: bool = False,
    ) -> str:
        key = account.email.casefold()
        profile_dir = self.profile_directory(account.email)
        auth_file = profile_dir / "auth.json"

        with self._lock:
            if key in self._relogin_required:
                return "relogin"

            current = self._codex_info[key]

        if not auth_file.exists():
            self._close_session(key)

            with self._lock:
                self._token_usage_cache.pop(key, None)
                self._codex_info[key] = replace(
                    current,
                    status="Chưa liên kết",
                    account_state="Chưa xác định",
                    last_sync="—",
                )
            return "unlinked"

        with self._lock:
            self._codex_info[key] = replace(
                current,
                status="Đang đồng bộ...",
            )

        try:
            session = self._get_session(
                key,
                profile_dir,
            )
            result = session.query()
            self._apply_codex_result(key, result)
            with self._lock:
                is_current_account = (
                    self._codex_info[key].account_state
                    == "Hoạt động bình thường"
                )
            if is_current_account:
                self._refresh_token_usage(
                    key,
                    session,
                    force=force_token_usage,
                )
            return "success"
        except CodexReloginRequired:
            self._mark_relogin(key)
            return "relogin"
        except Exception as error:
            if detect_banned_account(error):
                with self._lock:
                    self._codex_info[key] = replace(
                        self._codex_info[key],
                        account_state="Bị khóa (banned)",
                        status=(
                            "OpenAI đã khóa hoặc vô hiệu hóa tài khoản"
                        ),
                        last_sync=datetime.now().strftime(
                            "%H:%M:%S"
                        ),
                    )
            elif requires_codex_relogin(error):
                self._mark_relogin(key)
                return "relogin"
            else:
                with self._lock:
                    self._codex_info[key] = replace(
                        self._codex_info[key],
                        status=(
                            "Lỗi đồng bộ tạm thời – sẽ tự thử lại"
                        ),
                        last_sync=datetime.now().strftime(
                            "%H:%M:%S"
                        ),
                    )
            return "error"

    def _refresh_token_usage(
        self,
        key: str,
        session: CodexProfileSession,
        *,
        force: bool,
    ) -> None:
        attempted_at = time.monotonic()
        with self._lock:
            current = self._token_usage_cache.get(key)

        if (
            not force
            and current is not None
            and attempted_at - current.last_attempt_monotonic
            < _TOKEN_USAGE_CACHE_TTL_SECONDS
        ):
            return

        trusted_now = self._trusted_local_datetime()
        try:
            snapshot = normalize_token_usage(
                session.read_token_usage(),
                today=trusted_now.date(),
            )
        except Exception:
            fallback = TokenUsageCacheEntry(
                snapshot=(current.snapshot if current is not None else None),
                last_attempt_monotonic=attempted_at,
                updated_at=(current.updated_at if current is not None else None),
                stale=(
                    current is not None
                    and current.snapshot is not None
                ),
            )
            with self._lock:
                self._token_usage_cache = {
                    **self._token_usage_cache,
                    key: fallback,
                }
            return

        entry = TokenUsageCacheEntry(
            snapshot=snapshot,
            last_attempt_monotonic=attempted_at,
            updated_at=trusted_now,
            stale=False,
        )
        with self._lock:
            self._token_usage_cache = {
                **self._token_usage_cache,
                key: entry,
            }

    def _get_session(
        self,
        key: str,
        profile_dir: Path,
    ) -> CodexProfileSession:
        with self._lock:
            existing = self._sessions.get(key)

            if existing is not None:
                return existing

        command = build_codex_command("app-server")

        if command is None:
            raise RuntimeError("Không tìm thấy Codex CLI.")

        creation_flags = 0

        if os.name == "nt":
            creation_flags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        def notification_handler(
            event_type: str,
            payload: dict,
        ) -> None:
            if event_type == "rate_limits_updated":
                self._apply_codex_result(key, payload)
            elif event_type == "relogin_required":
                self._mark_relogin(key)
            elif event_type == "account_updated":
                with self._lock:
                    self._relogin_required.discard(key)
            elif event_type == "server_stopped":
                with self._lock:
                    current = self._codex_info.get(key)

                    if current is not None:
                        self._codex_info[key] = replace(
                            current,
                            status=(
                                "App-server đã dừng, sẽ tự kết nối lại"
                            ),
                        )

        session = CodexProfileSession(
            profile_dir=profile_dir,
            command=command,
            environment=build_codex_environment(profile_dir),
            notification_handler=notification_handler,
            timeout_seconds=20,
            creation_flags=creation_flags,
        )

        with self._lock:
            concurrent = self._sessions.get(key)

            if concurrent is None:
                self._sessions[key] = session
                return session

        session.close()
        return concurrent

    def _close_session(self, key: str) -> bool:
        with self._lock:
            session = self._sessions.pop(key, None)

        if session is None:
            return True

        try:
            closed = session.close()
        except Exception:
            closed = False

        if closed is not False:
            return True

        with self._lock:
            if key not in self._sessions:
                self._sessions = {
                    **self._sessions,
                    key: session,
                }
        return False

    def _mark_relogin(self, key: str) -> None:
        with self._lock:
            current = self._codex_info.get(key)

            if current is None:
                return

            self._token_usage_cache.pop(key, None)
            self._relogin_required.add(key)
            self._codex_info[key] = replace(
                current,
                status="Đã đăng xuất – bấm Liên kết Codex",
                last_sync=datetime.now().strftime("%H:%M:%S"),
            )

    def _apply_codex_result(
        self,
        key: str,
        result: dict,
    ) -> None:
        with self._lock:
            current = self._codex_info.get(key)

        if current is None:
            return

        account_result = result.get("account", {})
        account_data = account_result.get("account")

        if not isinstance(account_data, dict):
            self._mark_relogin(key)
            return

        codex_email = str(account_data.get("email") or "—")

        if (
            codex_email != "—"
            and codex_email.casefold()
            != current.stored_email.casefold()
        ):
            with self._lock:
                self._token_usage_cache.pop(key, None)
                self._relogin_required.add(key)
                self._codex_info[key] = replace(
                    current,
                    codex_email=codex_email,
                    remaining_percent="—",
                    cycle="—",
                    reset_at="—",
                    quota_windows=(),
                    plan_type="—",
                    account_state="Sai tài khoản Codex",
                    status=(
                        "Email Codex khác – bấm Liên kết Codex"
                    ),
                    last_sync=datetime.now().strftime(
                        "%H:%M:%S"
                    ),
                )
            return

        limits = result.get("limits", {})
        window, bucket = extract_best_rate_limit(limits)
        plan_type = str(
            account_data.get("planType") or "—"
        )
        remaining_percent = "—"
        cycle = "—"
        reset_at = "—"
        quota_windows = _format_quota_windows(result)
        status = "Không có dữ liệu quota"

        if window is not None:
            remaining_percent = _format_remaining_percent(
                window.get("usedPercent")
            )

            cycle = format_cycle(
                window.get("windowDurationMins")
            )
            reset_at = format_reset_time(
                window.get("resetsAt")
            )
            status = "Đã đồng bộ"

            if plan_type == "—" and bucket:
                plan_type = str(
                    bucket.get("planType") or "—"
                )

        with self._lock:
            self._relogin_required.discard(key)
            self._codex_info[key] = replace(
                current,
                codex_email=codex_email,
                remaining_percent=remaining_percent,
                cycle=cycle,
                reset_at=reset_at,
                quota_windows=quota_windows,
                plan_type=(
                    plan_type.capitalize()
                    if plan_type != "—"
                    else "—"
                ),
                account_state="Hoạt động bình thường",
                status=status,
                last_sync=datetime.now().strftime("%H:%M:%S"),
            )
