from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


API_SCHEMA_VERSION = 11
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Digest(Protocol):
    def update(self, data: bytes) -> object: ...


CORE_BUILD_INPUTS = (
    "run_local_web.py",
    "app/build_info.py",
    "app/codex_sync.py",
    "app/codex_failover.py",
    "app/codex_failover_hook.py",
    "app/local_web_accounts.py",
    "app/local_web_app.py",
    "app/local_web_profiles.py",
    "app/local_web_service.py",
    "app/otp_codex_manager_with_account_status.py",
    "app/trusted_clock.py",
    "app/token_usage.py",
)
FRONTEND_BUILD_INPUTS = ("web-dist",)
FRONTEND_ASSETS_DIR = PROJECT_ROOT / "web-dist"
FRONTEND_STATIC_ASSETS_DIR = FRONTEND_ASSETS_DIR / "assets"
BUILD_INPUTS = (
    *CORE_BUILD_INPUTS,
    *FRONTEND_BUILD_INPUTS,
)


def _hash_path(digest: Digest, relative_path: str) -> None:
    path = PROJECT_ROOT / relative_path
    if path.is_dir():
        files = sorted(
            item
            for item in path.rglob("*")
            if item.is_file()
        )
        if not files:
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\0missing\0")
            return
        for file_path in files:
            nested_relative = file_path.relative_to(PROJECT_ROOT).as_posix()
            _hash_path(digest, nested_relative)
        return

    digest.update(relative_path.encode("utf-8"))
    digest.update(b"\0")
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"missing")
    digest.update(b"\0")


def calculate_build_id() -> str:
    digest = hashlib.sha256()
    for relative_path in BUILD_INPUTS:
        _hash_path(digest, relative_path)
    return digest.hexdigest()[:16]


APP_BUILD_ID = calculate_build_id()
