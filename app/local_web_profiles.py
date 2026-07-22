from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path
from secrets import token_hex

from .otp_codex_manager_with_account_status import protect_sensitive_path


class UnsafeProfilePathError(ValueError):
    pass


def is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def validate_profiles_root(profiles_dir: Path) -> None:
    profiles_dir = Path(profiles_dir)
    try:
        metadata = profiles_dir.lstat()
    except FileNotFoundError as error:
        raise UnsafeProfilePathError(
            "Thư mục gốc profile không tồn tại."
        ) from error
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        profiles_dir.is_symlink()
        or bool(attributes & reparse_flag)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise UnsafeProfilePathError(
            "Thư mục gốc profile không an toàn."
        )


def validate_direct_profile_directory(
    profiles_dir: Path,
    profile_dir: Path,
) -> None:
    profiles_dir = Path(profiles_dir)
    profile_dir = Path(profile_dir)
    validate_profiles_root(profiles_dir)
    if (
        profile_dir.parent != profiles_dir
        or profile_dir.name in {"", ".", "..", ".archived"}
    ):
        raise UnsafeProfilePathError("Đường dẫn profile không hợp lệ.")
    try:
        metadata = profile_dir.lstat()
    except FileNotFoundError:
        return
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        profile_dir.is_symlink()
        or bool(attributes & reparse_flag)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise UnsafeProfilePathError("Profile không phải thư mục an toàn.")


def archive_profile_directory(
    profiles_dir: Path,
    profile_dir: Path,
) -> Path | None:
    profiles_dir = Path(profiles_dir)
    profile_dir = Path(profile_dir)
    validate_direct_profile_directory(profiles_dir, profile_dir)
    try:
        profile_dir.lstat()
    except FileNotFoundError:
        return None

    archived_dir = profiles_dir / ".archived"
    archived_dir.mkdir(parents=True, exist_ok=True)
    if is_reparse_point(archived_dir):
        raise UnsafeProfilePathError("Kho lưu trữ profile không an toàn.")
    protect_sensitive_path(archived_dir)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = archived_dir / (
        f"{profile_dir.name}-{timestamp}-{token_hex(4)}"
    )
    os.replace(profile_dir, destination)
    destination_metadata = destination.lstat()
    if (
        destination.parent != archived_dir
        or is_reparse_point(destination)
        or not stat.S_ISDIR(destination_metadata.st_mode)
    ):
        raise UnsafeProfilePathError(
            "Profile sau khi lưu trữ không còn là thư mục an toàn."
        )
    protect_sensitive_path(destination)
    return destination


def list_orphan_profile_directories(
    profiles_dir: Path,
    active_profile_names: set[str],
) -> tuple[Path, ...]:
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.exists():
        return ()
    validate_profiles_root(profiles_dir)

    orphans: list[Path] = []
    for candidate in profiles_dir.iterdir():
        if (
            candidate.name == ".archived"
            or candidate.name in active_profile_names
        ):
            continue
        try:
            validate_direct_profile_directory(profiles_dir, candidate)
        except (OSError, UnsafeProfilePathError):
            continue
        orphans.append(candidate)
    return tuple(sorted(orphans, key=lambda path: path.name.casefold()))
