from __future__ import annotations

import copy
import json
import queue
import subprocess
import threading
import time
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

                return {
                    "account": account,
                    "limits": limits,
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

    def restart(self) -> None:
        """Dừng process hiện tại; request kế tiếp sẽ mở lại."""
        with self._lifecycle_lock:
            self._stop_process()

    def close(self) -> None:
        with self._lifecycle_lock:
            self._closed = True
            self._stop_process()

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
                self._cached_limits = merge_sparse_dict(current, payload)
                account = copy.deepcopy(self._cached_account)
                limits = copy.deepcopy(self._cached_limits)

            if account is not None:
                self._emit(
                    "rate_limits_updated",
                    {"account": account, "limits": limits},
                )

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

    def _stop_process(self) -> None:
        process = self._process
        generation = self._process_generation
        self._process = None

        if process is None:
            return

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

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=3)
                except Exception:
                    pass

        for stream in (
            process.stdout,
            process.stderr,
        ):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
