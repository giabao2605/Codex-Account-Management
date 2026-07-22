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
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .codex_sync import CodexProfileSession, CodexReloginRequired
from .local_web_accounts import merge_accounts, plan_account_merge
from .local_web_profiles import (
    archive_profile_directory,
    list_orphan_profile_directories,
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


class AccountNotFoundError(LookupError):
    pass


class ImportPreviewError(ValueError):
    pass


class ImportPreviewConflictError(ImportPreviewError):
    pass


@dataclass(frozen=True)
class _ImportPreview:
    accounts_fingerprint: str
    accounts: tuple[Account, ...]
    result: dict
    changes: tuple[dict[str, str], ...]
    created_at: float


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
        self._sessions: dict[str, CodexProfileSession] = {}
        self._login_processes: dict[str, subprocess.Popen] = {}
        self._relogin_required: set[str] = set()
        self._started = False
        self._sync_status = "Chưa đồng bộ"
        self._import_previews: dict[str, _ImportPreview] = {}

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
                    "plan_type": info.plan_type,
                    "account_state": info.account_state,
                    "sync_status": info.status,
                    "last_sync": info.last_sync,
                }
            )
        return {
            "accounts": sorted(rows, key=account_display_sort_key),
            "sync_status": sync_status,
            "refresh_interval_seconds": self.refresh_interval_seconds,
            "orphan_profile_count": self.orphan_profile_count(),
            "recommendation": self._recommend_account(rows),
            "usage_statistics": self._usage_statistics(rows),
            "time_sync": time_sync,
        }

    def preview_import(self, raw_text: str) -> dict:
        with self._account_write_lock:
            with self._lock:
                current_accounts = tuple(self._accounts)
            new_accounts, result, changes = plan_account_merge(
                current_accounts,
                raw_text,
            )
            token = secrets.token_urlsafe(32)
            preview = _ImportPreview(
                accounts_fingerprint=self._accounts_fingerprint(
                    current_accounts
                ),
                accounts=new_accounts,
                result=result,
                changes=changes,
                created_at=time.monotonic(),
            )
            with self._lock:
                self._prune_import_previews_locked()
                self._import_previews = {
                    **self._import_previews,
                    token: preview,
                }

        return {
            "preview_token": token,
            "counts": {
                "added": result["added"],
                "updated": result["updated"],
                "duplicates": result["duplicates"],
                "errors": result["error_count"],
            },
            "changes": [dict(change) for change in changes],
            "errors": list(result["errors"]),
        }

    def apply_import_preview(
        self,
        preview_token: str,
        reject_on_errors: bool,
    ) -> dict:
        with self._account_write_lock:
            with self._lock:
                self._prune_import_previews_locked()
                preview = self._import_previews.get(preview_token)
                current_accounts = tuple(self._accounts)

            if preview is None:
                raise ImportPreviewError(
                    "Bản xem trước không hợp lệ hoặc đã hết hạn."
                )

            with self._lock:
                self._import_previews = {
                    token: item
                    for token, item in self._import_previews.items()
                    if token != preview_token
                }

            if not secrets.compare_digest(
                preview.accounts_fingerprint,
                self._accounts_fingerprint(current_accounts),
            ):
                raise ImportPreviewConflictError(
                    "Danh sách tài khoản đã thay đổi. Hãy xem trước lại."
                )
            if reject_on_errors and preview.result["errors"]:
                raise ImportPreviewConflictError(
                    "Bản xem trước còn lỗi nên chưa có dữ liệu nào được lưu."
                )

            self._save_accounts(preview.accounts)
            with self._lock:
                self._accounts = preview.accounts
                self._sync_codex_info_locked()

        if preview.result["added"] or preview.result["updated"]:
            self.refresh_async(
                {
                    self.account_id(account.email)
                    for account in preview.accounts
                }
            )
        return {
            **preview.result,
            "errors": list(preview.result["errors"]),
        }

    def import_accounts(self, raw_text: str) -> dict:
        with self._account_write_lock:
            with self._lock:
                current_accounts = tuple(self._accounts)
            new_accounts, result = merge_accounts(
                current_accounts,
                raw_text,
            )
            self._save_accounts(new_accounts)

            with self._lock:
                self._accounts = new_accounts
                self._sync_codex_info_locked()

        if result["added"] or result["updated"]:
            self.refresh_async(
                {
                    self.account_id(account.email)
                    for account in new_accounts
                }
            )

        return result

    def delete_account(self, account_id: str) -> bool:
        with self._account_write_lock:
            with self._lock:
                account = self._find_account_locked(account_id)
                key = account.email.casefold()
                new_accounts = tuple(
                    item
                    for item in self._accounts
                    if item.email.casefold() != key
                )

            self._save_accounts(new_accounts)

            with self._lock:
                self._accounts = new_accounts
                self._codex_info.pop(key, None)
                self._relogin_required.discard(key)
                session = self._sessions.pop(key, None)

        if session is not None:
            session.close()

        return True

    def unlink_profile(self, account_id: str) -> bool:
        with self._account_write_lock:
            account, key, profile_dir = self._profile_operation_context(
                account_id
            )
            with self._profile_lock_for(key):
                self._stop_login_process(key)
                self._close_session(key)
                archive_profile_directory(self.profiles_dir, profile_dir)
                with self._lock:
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
                            plan_type="—",
                            account_state="Chưa xác định",
                            status="Chưa liên kết",
                            last_sync="—",
                        )
        return True

    def reset_profile(self, account_id: str) -> bool:
        with self._account_write_lock:
            account, key, profile_dir = self._profile_operation_context(
                account_id
            )
            with self._profile_lock_for(key):
                self._stop_login_process(key)
                self._close_session(key)
                archive_profile_directory(self.profiles_dir, profile_dir)
                profile_dir.mkdir(parents=False, exist_ok=False)
                protect_sensitive_path(profile_dir)
                with self._lock:
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
                            plan_type="—",
                            account_state="Chưa xác định",
                            status=(
                                "Profile đã đặt lại – cần liên kết Codex"
                            ),
                            last_sync="—",
                        )
        return True

    def orphan_profile_count(self) -> int:
        return len(self._orphan_profile_directories())

    def archive_orphan_profiles(self) -> int:
        with self._account_write_lock:
            archived = 0
            for profile_dir in self._orphan_profile_directories():
                if archive_profile_directory(
                    self.profiles_dir,
                    profile_dir,
                ) is not None:
                    archived += 1
        return archived

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

    def refresh_async(
        self,
        account_ids: set[str] | None = None,
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
            args=(accounts,),
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
            session = self._sessions.pop(key, None)
            self._relogin_required.discard(key)

        if session is not None:
            session.close()

        self._stop_login_process(key)

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
                if self._login_processes.get(key) is process:
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
    def _accounts_fingerprint(accounts: tuple[Account, ...]) -> str:
        digest = hashlib.sha256()
        for account in accounts:
            for value in (
                account.email.casefold(),
                account.password,
                account.secret,
            ):
                encoded = value.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
        return digest.hexdigest()

    def _prune_import_previews_locked(self) -> None:
        cutoff = time.monotonic() - 600
        retained = [
            (token, preview)
            for token, preview in self._import_previews.items()
            if preview.created_at >= cutoff
        ][-63:]
        self._import_previews = dict(retained)

    @staticmethod
    def _recommend_account(rows: list[dict[str, object]]) -> dict | None:
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
        return min(candidates)[3] if candidates else None

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
    def _terminate_login_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            return

    def _stop_login_process(self, key: str) -> None:
        with self._lock:
            process = self._login_processes.get(key)
            if process is not None:
                self._login_processes = {
                    process_key: current_process
                    for process_key, current_process
                    in self._login_processes.items()
                    if process_key != key
                }
        if process is not None:
            self._terminate_login_process(process)

    def _orphan_profile_directories(self) -> tuple[Path, ...]:
        with self._lock:
            active_profile_names = {
                self.profile_directory(account.email).name
                for account in self._accounts
            }
        return list_orphan_profile_directories(
            self.profiles_dir,
            active_profile_names,
        )

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
            protect_sensitive_path(self.data_file)
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

    def _refresh_account(self, account: Account) -> str:
        key = account.email.casefold()
        with self._profile_lock_for(key):
            return self._refresh_account_locked(account)

    def _refresh_account_locked(self, account: Account) -> str:
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
            result = self._get_session(
                key,
                profile_dir,
            ).query()
            self._apply_codex_result(key, result)
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

    def _close_session(self, key: str) -> None:
        with self._lock:
            session = self._sessions.pop(key, None)

        if session is not None:
            session.close()

    def _mark_relogin(self, key: str) -> None:
        with self._lock:
            current = self._codex_info.get(key)

            if current is None:
                return

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
                self._relogin_required.add(key)
                self._codex_info[key] = replace(
                    current,
                    codex_email=codex_email,
                    remaining_percent="—",
                    cycle="—",
                    reset_at="—",
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
        status = "Không có dữ liệu quota"

        if window is not None:
            try:
                used_percent = float(
                    window.get("usedPercent", 0) or 0
                )
                remaining = max(
                    0.0,
                    min(100.0, 100.0 - used_percent),
                )
                remaining_percent = (
                    f"{int(round(remaining))}%"
                    if abs(remaining - round(remaining)) < 0.05
                    else f"{remaining:.1f}%"
                )
            except (TypeError, ValueError):
                remaining_percent = "—"

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
                plan_type=(
                    plan_type.capitalize()
                    if plan_type != "—"
                    else "—"
                ),
                account_state="Hoạt động bình thường",
                status=status,
                last_sync=datetime.now().strftime("%H:%M:%S"),
            )
