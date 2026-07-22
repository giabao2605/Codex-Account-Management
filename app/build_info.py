from __future__ import annotations

import hashlib
from pathlib import Path


API_SCHEMA_VERSION = 3
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_INPUTS = (
    "run_local_web.py",
    "app/build_info.py",
    "app/codex_sync.py",
    "app/local_web_accounts.py",
    "app/local_web_app.py",
    "app/local_web_profiles.py",
    "app/local_web_service.py",
    "app/otp_codex_manager_with_account_status.py",
    "app/trusted_clock.py",
    "web/app.js",
    "web/index.html",
    "web/styles.css",
    "web/theme-init.js",
)


def calculate_build_id() -> str:
    digest = hashlib.sha256()
    for relative_path in BUILD_INPUTS:
        path = PROJECT_ROOT / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


APP_BUILD_ID = calculate_build_id()
