from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .codex_sync import CodexProfileSession, CodexReloginRequired
from .local_web_accounts import merge_accounts
from .otp_codex_manager_with_account_status import (
    Account,
    CodexInfo,
    build_codex_command,
    build_codex_environment,
    corrected_time,
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
    ) -> None:
        self.data_file = Path(data_file)
        self.profiles_dir = Path(profiles_dir)
        self.enable_codex = enable_codex
        self.refresh_interval_seconds = refresh_interval_seconds
        self.csrf_token = secrets.token_urlsafe(32)
        self.access_token = secrets.token_urlsafe(48)
        self._lock = threading.RLock()
        self._account_write_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self._accounts: tuple[Account, ...] = ()
        self._codex_info: dict[str, CodexInfo] = {}
        self._sessions: dict[str, CodexProfileSession] = {}
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
            protect_sensitive_tree(self.profiles_dir)

            if self.data_file.exists():
                protect_sensitive_path(self.data_file)
            self._accounts = self._load_accounts()
            self._sync_codex_info_locked()
            self._started = True

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

    def state(self) -> dict:
        now = corrected_time()
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
            remaining_seconds = (
                account.totp.interval
                - now % account.totp.interval
            )
            rows.append(
                {
                    "id": self.account_id(account.email),
                    "email": account.email,
                    "otp": account.totp.at(now),
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
            current = self._codex_info.get(key)
            if current is not None:
                self._codex_info[key] = replace(
                    current,
                    status="Đang chờ đăng nhập...",
                )

        def wait_for_login() -> None:
            return_code = process.wait()

            with self._lock:
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
