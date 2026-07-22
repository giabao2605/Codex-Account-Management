from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from app.local_web_app import create_app
from app.local_web_service import LocalWebService
from app.otp_codex_manager_with_account_status import (
    CODEX_PROFILES_DIR,
    DATA_FILE,
    decrypt_text,
    encrypt_text,
    protect_sensitive_path,
)


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
SESSION_FILE = Path(__file__).resolve().with_name(".web_session.json")
_NULL_STREAMS: list[object] = []


def show_startup_error(message: str) -> None:
    if sys.platform == "win32":
        from tkinter import messagebox

        messagebox.showerror("OTP Codex Local", message)
        return

    print(message, file=sys.stderr)


def ensure_standard_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            null_stream = open(
                os.devnull,
                "w",
                encoding="utf-8",
            )
            _NULL_STREAMS.append(null_stream)
            setattr(sys, stream_name, null_stream)


def reserve_local_socket() -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            server_socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        else:
            server_socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )
        server_socket.bind((HOST, PORT))
        server_socket.listen(2048)
        server_socket.setblocking(False)
        return server_socket
    except OSError:
        server_socket.close()
        raise


def load_session_token() -> str | None:
    try:
        payload = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return decrypt_text(payload["token"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_session_token(token: str) -> None:
    temporary_file = SESSION_FILE.with_name(
        f".{SESSION_FILE.name}.tmp"
    )
    temporary_file.write_text(
        json.dumps({"token": encrypt_text(token)}),
        encoding="utf-8",
    )
    protect_sensitive_path(temporary_file)
    temporary_file.replace(SESSION_FILE)
    protect_sensitive_path(SESSION_FILE)


def existing_app_is_running(token: str) -> bool:
    try:
        request = urllib.request.Request(
            f"{URL}/api/state",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(
            request,
            timeout=1.5,
        ) as response:
            return (
                response.status == 200
                and response.headers.get("X-OTP-Codex-App") == "1"
            )
    except (OSError, ValueError):
        return False


def open_browser_when_ready(token: str) -> None:
    for _ in range(180):
        try:
            with urllib.request.urlopen(
                f"{URL}/api/health",
                timeout=1,
            ) as response:
                if (
                    response.status == 200
                    and response.headers.get("X-OTP-Codex-App") == "1"
                ):
                    webbrowser.open(f"{URL}/#{token}")
                    return
        except OSError:
            time.sleep(0.25)


def main() -> int:
    ensure_standard_streams()
    try:
        server_socket = reserve_local_socket()
    except OSError:
        existing_token = load_session_token()
        if (
            existing_token is not None
            and existing_app_is_running(existing_token)
        ):
            webbrowser.open(f"{URL}/#{existing_token}")
            return 0

        show_startup_error(
            f"Không thể mở cổng {PORT}. Có thể ứng dụng đang chạy. "
            "Hãy đóng chương trình đang dùng cổng này rồi thử lại."
        )
        return 1

    service = LocalWebService(
        data_file=Path(DATA_FILE),
        profiles_dir=Path(CODEX_PROFILES_DIR),
    )
    server_holder: dict[str, uvicorn.Server] = {}

    def request_shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True

    app = create_app(
        service,
        shutdown_callback=request_shutdown,
    )
    save_session_token(service.access_token)
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        access_log=False,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server
    threading.Thread(
        target=open_browser_when_ready,
        args=(service.access_token,),
        name="open-local-web",
        daemon=True,
    ).start()

    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        if load_session_token() == service.access_token:
            SESSION_FILE.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
