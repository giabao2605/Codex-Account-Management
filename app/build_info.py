from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, Protocol, cast


API_SCHEMA_VERSION = 6
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_MODE_ENV = "OTP_CODEX_FRONTEND"
FrontendMode = Literal["vue", "legacy"]


class Digest(Protocol):
    def update(self, data: bytes) -> object: ...


CORE_BUILD_INPUTS = (
    "run_local_web.py",
    "app/build_info.py",
    "app/codex_sync.py",
    "app/local_web_accounts.py",
    "app/local_web_app.py",
    "app/local_web_profiles.py",
    "app/local_web_service.py",
    "app/otp_codex_manager_with_account_status.py",
    "app/trusted_clock.py",
    "app/token_usage.py",
)
FRONTEND_BUILD_INPUTS: dict[FrontendMode, tuple[str, ...]] = {
    "vue": ("web-dist",),
    "legacy": (
        "web/app.js",
        "web/index.html",
        "web/styles.css",
        "web/theme-init.js",
    ),
}


def resolve_frontend_mode(value: str | None) -> FrontendMode:
    normalized = (value or "vue").strip().casefold()
    if normalized not in FRONTEND_BUILD_INPUTS:
        raise ValueError(
            f"{FRONTEND_MODE_ENV} must be 'vue' or 'legacy', "
            f"got {value!r}."
        )
    return cast(FrontendMode, normalized)


def frontend_asset_paths(
    mode: FrontendMode,
) -> tuple[Path, Path | None]:
    if mode == "legacy":
        return PROJECT_ROOT / "web", None
    assets_dir = PROJECT_ROOT / "web-dist"
    return assets_dir, assets_dir / "assets"


APP_FRONTEND_MODE = resolve_frontend_mode(os.environ.get(FRONTEND_MODE_ENV))
FRONTEND_ASSETS_DIR, FRONTEND_STATIC_ASSETS_DIR = frontend_asset_paths(
    APP_FRONTEND_MODE
)
BUILD_INPUTS = (
    *CORE_BUILD_INPUTS,
    *FRONTEND_BUILD_INPUTS[APP_FRONTEND_MODE],
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


def calculate_build_id(
    frontend_mode: FrontendMode | str | None = None,
) -> str:
    active_mode = resolve_frontend_mode(frontend_mode)
    digest = hashlib.sha256()
    digest.update(f"frontend:{active_mode}\0".encode("utf-8"))
    active_inputs = (
        *CORE_BUILD_INPUTS,
        *FRONTEND_BUILD_INPUTS[active_mode],
    )
    for relative_path in active_inputs:
        _hash_path(digest, relative_path)
    return digest.hexdigest()[:16]


APP_BUILD_ID = calculate_build_id(APP_FRONTEND_MODE)
