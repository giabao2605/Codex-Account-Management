from __future__ import annotations

import copy
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


NotificationHandler = Callable[[str, dict], None]


class CodexSessionError(RuntimeError):
    """Lỗi kết nối hoặc vòng đời của Codex App Server."""


class CodexProtocolError(CodexSessionError):
    """Codex App Server trả về JSON-RPC error."""

    def __init__(self, error: object) -> None:
        self.error = error
        super().__init__(str(error))


class CodexReloginRequired(CodexSessionError):
    """Profile không còn tài khoản OpenAI hợp lệ."""


@dataclass(frozen=True)
class CodexQuotaWindow:
    limit_id: str | None
    limit_name: str | None
    kind: str
    used_percent: float | None
    window_duration_minutes: int | None
    resets_at: int | None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "limit_id": self.limit_id,
            "limit_name": self.limit_name,
            "resets_at": self.resets_at,
            "used_percent": self.used_percent,
            "window_duration_minutes": self.window_duration_minutes,
        }


@dataclass(frozen=True)
class CodexQuotaSnapshot:
    reached_type: str | None
    exhausted: bool
    windows: tuple[CodexQuotaWindow, ...]
    banked_reset_count: int | None = None
    banked_reset_expires_at: tuple[int | None, ...] | None = None

    def to_dict(self) -> dict:
        return {
            "banked_reset_count": self.banked_reset_count,
            "banked_reset_expires_at": (
                list(self.banked_reset_expires_at)
                if self.banked_reset_expires_at is not None
                else None
            ),
            "exhausted": self.exhausted,
            "rate_limit_reached_type": self.reached_type,
            "windows": [window.to_dict() for window in self.windows],
        }


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def normalize_quota_snapshot(payload: object) -> CodexQuotaSnapshot:
    source = payload if isinstance(payload, dict) else {}
    windows: list[CodexQuotaWindow] = []
    banked_reset_count: int | None = None
    banked_reset_expires_at: tuple[int | None, ...] | None = None
    reached_type = _optional_text(source.get("rateLimitReachedType"))
    buckets = source.get("rateLimitsByLimitId")

    reset_credits = source.get("rateLimitResetCredits")
    if isinstance(reset_credits, dict):
        available_count = _optional_int(reset_credits.get("availableCount"))
        if available_count is not None:
            banked_reset_count = max(0, available_count)
        credit_rows = reset_credits.get("credits")
        if isinstance(credit_rows, list):
            expirations: list[int | None] = []
            for credit in credit_rows:
                if not isinstance(credit, dict) or "expiresAt" not in credit:
                    continue
                expires_at = credit["expiresAt"]
                if expires_at is None:
                    expirations.append(None)
                    continue
                normalized_expiration = _optional_int(expires_at)
                if normalized_expiration is not None:
                    expirations.append(normalized_expiration)
            banked_reset_expires_at = tuple(expirations)

    if isinstance(buckets, dict):
        for bucket_key, bucket in sorted(
            buckets.items(),
            key=lambda item: str(item[0]),
        ):
            if not isinstance(bucket, dict):
                continue
            if reached_type is None:
                reached_type = _optional_text(
                    bucket.get("rateLimitReachedType")
                )
            limit_id = _optional_text(bucket.get("limitId"))
            if limit_id is None and isinstance(bucket_key, str):
                limit_id = bucket_key
            limit_name = _optional_text(bucket.get("limitName"))
            for kind in ("primary", "secondary"):
                window = bucket.get(kind)
                if not isinstance(window, dict):
                    continue
                windows.append(
                    CodexQuotaWindow(
                        limit_id=limit_id,
                        limit_name=limit_name,
                        kind=kind,
                        used_percent=_optional_float(
                            window.get("usedPercent")
                        ),
                        window_duration_minutes=_optional_int(
                            window.get("windowDurationMins")
                        ),
                        resets_at=_optional_int(window.get("resetsAt")),
                    )
                )

    if not windows:
        fallback = source.get("rateLimits")
        if isinstance(fallback, dict):
            if reached_type is None:
                reached_type = _optional_text(
                    fallback.get("rateLimitReachedType")
                )
            for kind in ("primary", "secondary"):
                window = fallback.get(kind)
                if not isinstance(window, dict):
                    continue
                windows.append(
                    CodexQuotaWindow(
                        limit_id=None,
                        limit_name=None,
                        kind=kind,
                        used_percent=_optional_float(
                            window.get("usedPercent")
                        ),
                        window_duration_minutes=_optional_int(
                            window.get("windowDurationMins")
                        ),
                        resets_at=_optional_int(window.get("resetsAt")),
                    )
                )

    exhausted = bool(reached_type) or (
        bool(windows)
        and all(
            window.used_percent is not None
            and window.used_percent >= 100
            for window in windows
        )
    )
    return CodexQuotaSnapshot(
        reached_type=reached_type,
        exhausted=exhausted,
        windows=tuple(windows),
        banked_reset_count=banked_reset_count,
        banked_reset_expires_at=banked_reset_expires_at,
    )


def extract_usage_limit_event(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    thread_id = payload.get("threadId")
    turn = payload.get("turn")
    if not isinstance(thread_id, str) or not isinstance(turn, dict):
        return None
    turn_id = turn.get("id")
    error = turn.get("error")
    if (
        not isinstance(turn_id, str)
        or not isinstance(error, dict)
        or error.get("codexErrorInfo") != "usageLimitExceeded"
    ):
        return None
    return {
        "error_kind": "usageLimitExceeded",
        "thread_id": thread_id,
        "turn_id": turn_id,
    }


def merge_sparse_dict(current: dict, update: dict) -> dict:
    """
    Gộp notification dạng sparse mà không sửa object đầu vào.

    App-server dùng null cho một số trường không có trong lần cập nhật;
    null vì vậy không được xóa giá trị đã biết trước đó.
    """
    merged = copy.deepcopy(current)

    for key, value in update.items():
        if value is None:
            continue

        existing = merged.get(key)

        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_sparse_dict(existing, value)
        else:
            merged[key] = copy.deepcopy(value)

    return merged


def _merge_rate_limit_update(current: dict, update: dict) -> dict:
    merged = merge_sparse_dict(current, update)

    def apply_authoritative_nulls(
        destination: dict,
        source: dict,
    ) -> None:
        if "rateLimitReachedType" in source:
            destination["rateLimitReachedType"] = copy.deepcopy(
                source["rateLimitReachedType"]
            )
        for key, value in source.items():
            nested = destination.get(key)
            if isinstance(value, dict) and isinstance(nested, dict):
                apply_authoritative_nulls(nested, value)

    apply_authoritative_nulls(merged, update)

    reset_credit_update = update.get("rateLimitResetCredits")
    reset_credit_destination = merged.get("rateLimitResetCredits")
    if (
        isinstance(reset_credit_update, dict)
        and isinstance(reset_credit_destination, dict)
        and "credits" in reset_credit_update
    ):
        reset_credit_destination["credits"] = copy.deepcopy(
            reset_credit_update["credits"]
        )
    return merged


class CodexProfileSession:
    """
    Một app-server bền vững cho đúng một CODEX_HOME.

    Mỗi request dùng id riêng, trong khi một reader thread liên tục nhận cả
    response lẫn notification realtime từ Codex.
    """

    def __init__(
        self,
        profile_dir: Path,
        command: list[str],
        environment: dict[str, str],
        notification_handler: NotificationHandler | None = None,
        timeout_seconds: float = 20,
        creation_flags: int = 0,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.command = list(command)
        self.environment = dict(environment)
        self.notification_handler = notification_handler
        self.timeout_seconds = timeout_seconds
        self.creation_flags = creation_flags

        self._lifecycle_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._pending: dict[
            int,
            tuple[int, queue.Queue],
        ] = {}
        self._next_request_id = 1
        self._process: subprocess.Popen | None = None
        self._process_generation = 0
        self._closed = False
        self._cached_account: dict | None = None
        self._cached_limits: dict | None = None
        self._cached_quota = CodexQuotaSnapshot(None, False, ())

    @property
    def process_id(self) -> int | None:
        with self._lifecycle_lock:
            process = self._process

            if process is None or process.poll() is not None:
                return None

            return process.pid

    def query(self) -> dict:
        """Đọc snapshot account và quota trên phiên đang chạy."""
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                self._ensure_started()
                account = self._request(
                    "account/read",
                    {"refreshToken": False},
                )

                if (
                    not isinstance(account.get("account"), dict)
                    and account.get("requiresOpenaiAuth") is not False
                ):
                    raise CodexReloginRequired(
                        "Codex profile đã đăng xuất hoặc cần liên kết lại."
                    )

                limits = self._request("account/rateLimits/read")

                with self._cache_lock:
                    self._cached_account = copy.deepcopy(account)
                    self._cached_limits = copy.deepcopy(limits)
                    self._cached_quota = normalize_quota_snapshot(limits)

                return {
                    "account": account,
                    "limits": limits,
                    "quota": self._cached_quota.to_dict(),
                }

            except CodexReloginRequired:
                raise
            except CodexProtocolError:
                raise
            except CodexSessionError as error:
                last_error = error

                if attempt == 0:
                    self.restart()
                    continue

                raise

        raise CodexSessionError(str(last_error or "Không đọc được Codex."))

    def read_token_usage(self) -> dict:
        """Đọc thống kê token từ app-server trên phiên đang chạy."""
        return self._request("account/usage/read")

    def request(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict:
        """Gửi một request app-server đã được khởi tạo."""
        return self._request(method, params)

    def restart(self) -> None:
        """Dừng process hiện tại; request kế tiếp sẽ mở lại."""
        with self._lifecycle_lock:
            if not self._stop_process():
                raise CodexSessionError(
                    "Không thể dừng Codex App Server."
                )

    def close(self) -> bool:
        with self._lifecycle_lock:
            self._closed = True
            return self._stop_process()

    def _ensure_started(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise CodexSessionError("Codex session đã đóng.")

            if self._process is not None and self._process.poll() is None:
                return

            self._stop_process()

            try:
                process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=self.environment,
                    creationflags=self.creation_flags,
                )
            except Exception as error:
                raise CodexSessionError(
                    f"Không mở được Codex App Server: {error}"
                ) from error

            if process.stdin is None or process.stdout is None:
                process.kill()
                raise CodexSessionError(
                    "Không mở được stdin/stdout của Codex App Server."
                )

            self._process = process
            self._process_generation += 1
            generation = self._process_generation
            threading.Thread(
                target=self._read_stdout,
                args=(process, generation),
                daemon=True,
            ).start()
            threading.Thread(
                target=self._read_stderr,
                args=(process,),
                daemon=True,
            ).start()

            try:
                self._request_on_running_process(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "local_otp_codex_manager",
                            "title": "Local OTP Codex Manager",
                            "version": "persistent-sync-v1",
                        }
                    },
                )
                self._send_message(
                    {"method": "initialized", "params": {}},
                    expected_generation=generation,
                )
            except Exception:
                self._stop_process()
                raise

    def _request(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict:
        self._ensure_started()
        return self._request_on_running_process(method, params)

    def _request_on_running_process(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict:
        with self._pending_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            generation = self._process_generation
            response_queue: queue.Queue = queue.Queue()
            self._pending[request_id] = (
                generation,
                response_queue,
            )

        message: dict = {
            "method": method,
            "id": request_id,
        }

        if params is not None:
            message["params"] = params

        try:
            self._send_message(
                message,
                expected_generation=generation,
            )

            try:
                response = response_queue.get(timeout=self.timeout_seconds)
            except queue.Empty as error:
                raise CodexSessionError(
                    "Codex không trả dữ liệu trong thời gian cho phép."
                ) from error

            if isinstance(response, Exception):
                raise response

            if "error" in response:
                raise CodexProtocolError(response["error"])

            result = response.get("result")
            return result if isinstance(result, dict) else {}

        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _send_message(
        self,
        message: dict,
        expected_generation: int | None = None,
    ) -> None:
        process = self._process

        if (
            process is None
            or process.stdin is None
            or process.poll() is not None
            or (
                expected_generation is not None
                and expected_generation
                != self._process_generation
            )
        ):
            raise CodexSessionError("Codex App Server đã dừng.")

        payload = json.dumps(message, ensure_ascii=False) + "\n"

        try:
            with self._write_lock:
                process.stdin.write(payload)
                process.stdin.flush()
        except Exception as error:
            raise CodexSessionError(
                f"Không gửi được request tới Codex: {error}"
            ) from error

    def _read_stdout(
        self,
        process: subprocess.Popen,
        generation: int,
    ) -> None:
        stream = process.stdout

        if stream is None:
            return

        try:
            for raw_line in stream:
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                self._handle_message(
                    message,
                    generation,
                )
        except Exception as error:
            self._fail_pending(
                CodexSessionError(f"Lỗi đọc Codex App Server: {error}"),
                generation,
            )
        finally:
            is_current_process = (
                self._process is process
                and self._process_generation
                == generation
            )

            if not self._closed and is_current_process:
                self._fail_pending(
                    CodexSessionError("Codex App Server đã dừng."),
                    generation,
                )
                self._emit("server_stopped", {})

    def _read_stderr(self, process: subprocess.Popen) -> None:
        stream = process.stderr

        if stream is None:
            return

        for raw_line in stream:
            # Luôn drain stderr để tránh process bị block, nhưng không giữ
            # nội dung vì log auth có thể chứa dữ liệu nhạy cảm.
            _ = raw_line

    def _handle_message(
        self,
        message: dict,
        generation: int | None = None,
    ) -> None:
        if (
            generation is not None
            and generation != self._process_generation
        ):
            return

        message_id = message.get("id")

        if isinstance(message_id, int):
            with self._pending_lock:
                pending = self._pending.get(message_id)

            if pending is not None:
                pending_generation, response_queue = pending

                if (
                    generation is None
                    or pending_generation == generation
                ):
                    response_queue.put_nowait(message)
            return

        method = message.get("method")
        params = message.get("params")
        payload = params if isinstance(params, dict) else {}

        if method == "account/updated":
            if (
                "authMode" in payload
                and payload["authMode"] is None
            ):
                self._emit("relogin_required", payload)
            else:
                with self._cache_lock:
                    account_result = self._cached_account

                    if (
                        isinstance(account_result, dict)
                        and isinstance(
                            account_result.get("account"),
                            dict,
                        )
                    ):
                        account_update = {
                            key: payload[key]
                            for key in (
                                "email",
                                "planType",
                            )
                            if key in payload
                        }
                        updated_result = copy.deepcopy(
                            account_result
                        )
                        updated_result["account"] = (
                            merge_sparse_dict(
                                account_result["account"],
                                account_update,
                            )
                        )
                        self._cached_account = (
                            updated_result
                        )

                self._emit("account_updated", payload)
            return

        if method == "account/rateLimits/updated":
            with self._cache_lock:
                current = self._cached_limits or {}
                self._cached_limits = _merge_rate_limit_update(
                    current,
                    payload,
                )
                self._cached_quota = normalize_quota_snapshot(
                    self._cached_limits
                )
                account = copy.deepcopy(self._cached_account)
                limits = copy.deepcopy(self._cached_limits)
                quota = self._cached_quota.to_dict()

            if account is not None:
                self._emit(
                    "rate_limits_updated",
                    {"account": account, "limits": limits},
                )
            self._emit("quota_updated", {"quota": quota})
            return

        if method == "turn/completed":
            usage_limit = extract_usage_limit_event(payload)
            if usage_limit is not None:
                self._emit("usage_limit_exceeded", usage_limit)
            self._emit("turn_completed", payload)

    def _emit(self, event: str, payload: dict) -> None:
        handler = self.notification_handler

        if handler is None:
            return

        try:
            handler(event, copy.deepcopy(payload))
        except Exception:
            return

    def _fail_pending(
        self,
        error: Exception,
        generation: int | None = None,
    ) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())

        for pending_generation, response_queue in pending:
            if (
                generation is not None
                and pending_generation != generation
            ):
                continue

            response_queue.put_nowait(error)

    def _stop_process(self) -> bool:
        process = self._process
        generation = self._process_generation
        self._process = None

        if process is None:
            return True

        def process_exited() -> bool:
            try:
                return process.poll() is not None
            except Exception:
                return False

        # Vô hiệu hóa ngay mọi message đến muộn từ reader của process cũ.
        self._process_generation += 1

        self._fail_pending(
            CodexSessionError("Codex App Server đã dừng."),
            generation,
        )

        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass

        if not process_exited():
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                pass

        if not process_exited():
            try:
                process.kill()
                process.wait(timeout=3)
            except Exception:
                pass

        if not process_exited():
            self._process = process
            return False

        for stream in (
            process.stdout,
            process.stderr,
        ):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

        return True
