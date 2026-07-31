from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from secrets import token_hex


class UnsafeProfilePathError(ValueError):
    pass


INTERNAL_PROFILE_DIRECTORIES = {".failover"}


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
        or profile_dir.name in {"", ".", ".."}
        or profile_dir.name in INTERNAL_PROFILE_DIRECTORIES
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


def delete_profile_directory(
    profiles_dir: Path,
    profile_dir: Path,
) -> bool:
    profiles_dir = Path(profiles_dir)
    profile_dir = Path(profile_dir)
    validate_direct_profile_directory(profiles_dir, profile_dir)
    try:
        profile_dir.lstat()
    except FileNotFoundError:
        return False

    shutil.rmtree(profile_dir)
    return True


def delete_staged_profile_directories(
    profiles_dir: Path,
    profile_dir: Path | None = None,
) -> int:
    profiles_dir = Path(profiles_dir)
    validate_profiles_root(profiles_dir)
    profile_name = None
    if profile_dir is not None:
        profile_dir = Path(profile_dir)
        validate_direct_profile_directory(profiles_dir, profile_dir)
        profile_name = profile_dir.name

    candidates: list[Path] = []
    marker = ".deleting-"
    for candidate in profiles_dir.iterdir():
        marker_index = candidate.name.rfind(marker)
        original_name = candidate.name[1:marker_index]
        token = candidate.name[marker_index + len(marker):]
        if (
            not candidate.name.startswith(".")
            or marker_index <= 1
            or len(token) != 16
            or any(character not in "0123456789abcdef" for character in token)
            or (profile_name is not None and original_name != profile_name)
        ):
            continue
        validate_direct_profile_directory(
            profiles_dir,
            profiles_dir / original_name,
        )
        candidates.append(candidate)

    first_error: Exception | None = None
    deleted = 0
    for candidate in candidates:
        try:
            deleted += int(
                delete_profile_directory(profiles_dir, candidate)
            )
        except (OSError, UnsafeProfilePathError) as error:
            first_error = first_error or error

    if first_error is not None:
        raise first_error
    return deleted


def stage_profile_directory_for_deletion(
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

    staged_dir = profiles_dir / (
        f".{profile_dir.name}.deleting-{token_hex(8)}"
    )
    validate_direct_profile_directory(profiles_dir, staged_dir)
    os.replace(profile_dir, staged_dir)
    return staged_dir


def restore_staged_profile_directory(
    profiles_dir: Path,
    staged_dir: Path,
    profile_dir: Path,
) -> None:
    validate_direct_profile_directory(profiles_dir, staged_dir)
    validate_direct_profile_directory(profiles_dir, profile_dir)
    try:
        profile_dir.lstat()
    except FileNotFoundError:
        os.replace(staged_dir, profile_dir)
        return
    raise UnsafeProfilePathError("Profile đích đã tồn tại.")
