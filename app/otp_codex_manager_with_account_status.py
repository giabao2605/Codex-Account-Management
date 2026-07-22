import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import pyotp
import ntsecuritycon
import win32api
import win32con
import win32crypt
import win32security

from .codex_sync import CodexProfileSession, CodexReloginRequired
from .trusted_clock import TrustedClock, get_default_trusted_clock


APP_VERSION = "account-status-v3-persistent-sync"

OTP_REFRESH_INTERVAL_MS = 200
CODEX_REFRESH_INTERVAL_SECONDS = 60
CODEX_QUERY_TIMEOUT_SECONDS = 20

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_FILE = BASE_DIR / "accounts.json"
CODEX_PROFILES_DIR = BASE_DIR / "codex_profiles"


def protect_sensitive_path(path: Path) -> None:
    """Giới hạn file/thư mục nhạy cảm cho user hiện tại và SYSTEM."""
    if os.name != "nt" or not path.exists():
        return

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_QUERY,
    )
    current_user_sid = win32security.GetTokenInformation(
        token,
        win32security.TokenUser,
    )[0]
    system_sid = win32security.CreateWellKnownSid(
        win32security.WinLocalSystemSid,
        None,
    )
    inheritance_flags = 0

    if path.is_dir():
        inheritance_flags = (
            win32con.OBJECT_INHERIT_ACE
            | win32con.CONTAINER_INHERIT_ACE
        )

    dacl = win32security.ACL()

    for sid in (current_user_sid, system_sid):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            inheritance_flags,
            ntsecuritycon.FILE_ALL_ACCESS,
            sid,
        )

    descriptor = win32security.GetFileSecurity(
        str(path),
        win32security.OWNER_SECURITY_INFORMATION,
    )
    descriptor.SetSecurityDescriptorDacl(
        True,
        dacl,
        False,
    )
    descriptor.SetSecurityDescriptorControl(
        win32security.SE_DACL_PROTECTED,
        win32security.SE_DACL_PROTECTED,
    )
    win32security.SetFileSecurity(
        str(path),
        (
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION
        ),
        descriptor,
    )


def protect_sensitive_tree(root: Path) -> None:
    """Áp ACL riêng cho profile hiện có mà không đi theo symlink."""
    if not root.exists():
        return

    protect_sensitive_path(root)

    for current_root, directory_names, filenames in os.walk(
        root,
        followlinks=False,
    ):
        current_path = Path(current_root)

        for name in directory_names:
            directory = current_path / name

            if not directory.is_symlink():
                protect_sensitive_path(directory)

        for name in filenames:
            file_path = current_path / name

            if not file_path.is_symlink():
                protect_sensitive_path(file_path)


@dataclass
class Account:
    email: str
    password: str
    secret: str
    totp: pyotp.TOTP


@dataclass
class CodexInfo:
    stored_email: str
    codex_email: str = "—"
    remaining_percent: str = "—"
    cycle: str = "—"
    reset_at: str = "—"
    plan_type: str = "—"
    account_state: str = "Chưa xác định"
    status: str = "Chưa liên kết"
    last_sync: str = "—"


def corrected_time(clock: TrustedClock | None = None) -> int:
    active_clock = clock or get_default_trusted_clock()
    active_clock.start()
    return int(active_clock.now())


def looks_like_base32_secret(value: str) -> bool:
    normalized = re.sub(r"[\s-]+", "", value).upper()
    return bool(
        normalized
        and re.fullmatch(r"[A-Z2-7]+=*", normalized)
    )


def normalize_secret(secret: str) -> str:
    normalized = re.sub(
        r"[\s-]+",
        "",
        secret,
    ).upper()

    if not normalized:
        raise ValueError("2FA Secret đang trống.")

    if not re.fullmatch(r"[A-Z2-7]+=*", normalized):
        raise ValueError(
            "2FA Secret không đúng định dạng Base32. "
            "Secret chỉ được chứa A-Z và các số 2-7."
        )

    return normalized


def create_totp(secret: str) -> pyotp.TOTP:
    normalized_secret = normalize_secret(secret)

    totp = pyotp.TOTP(
        normalized_secret,
        digits=6,
        interval=30,
        digest=hashlib.sha1,
    )

    # Kiểm tra secret có thể tạo mã.
    # Validation must remain deterministic and must not start network time sync.
    totp.at(0)
    return totp


def encrypt_text(value: str) -> str:
    raw_data = value.encode("utf-8")

    encrypted_data = win32crypt.CryptProtectData(
        raw_data,
        "Local OTP Account Manager",
        None,
        None,
        None,
        0,
    )

    return base64.b64encode(
        encrypted_data
    ).decode("ascii")


def decrypt_text(value: str) -> str:
    encrypted_data = base64.b64decode(
        value.encode("ascii")
    )

    _, decrypted_data = win32crypt.CryptUnprotectData(
        encrypted_data,
        None,
        None,
        None,
        0,
    )

    return decrypted_data.decode("utf-8")


def parse_account_line(
    line: str,
) -> tuple[str, str, str]:
    """
    Hỗ trợ:

    email|password|2FA_SECRET

    hoặc:

    email|password|2FA_SECRET|OTP_CŨ
    """
    line = line.strip()

    if not line:
        raise ValueError("Dòng dữ liệu đang trống.")

    parts = [
        part.strip()
        for part in line.split("|")
    ]

    if len(parts) < 3:
        raise ValueError(
            "Dữ liệu phải có dạng "
            "email|password|2FA_SECRET."
        )

    email = parts[0]

    has_trailing_otp = (
        len(parts) >= 4
        and re.fullmatch(r"\d{6,8}", parts[-1]) is not None
        and looks_like_base32_secret(parts[-2])
    )

    if has_trailing_otp:
        secret = parts[-2]
        password = "|".join(parts[1:-2])
    else:
        secret = parts[-1]
        password = "|".join(parts[1:-1])

    if not email:
        raise ValueError("Email đang trống.")

    if not password:
        raise ValueError("Password đang trống.")

    return email, password, normalize_secret(secret)


def _normalize_command_path(value: str) -> str | None:
    """
    Chuẩn hóa kết quả đường dẫn lệnh Codex.
    """
    value = value.strip().strip('"')

    if not value:
        return None

    path = Path(value)

    if path.exists():
        return str(path.resolve())

    return None


def find_codex_executable() -> str | None:
    """
    Tìm Codex CLI trên Windows theo nhiều cách.

    Chỉ chấp nhận executable standalone trong thư mục cài Codex tin cậy;
    không chạy .cmd/.bat/.ps1 từ PATH trong tiến trình giữ credentials.
    """
    # Ưu tiên bản CLI standalone của Codex app. Trên Windows, PATH có thể
    # trỏ vào alias trong WindowsApps nhưng alias đó không cho tiến trình
    # Python desktop thực thi trực tiếp (Access is denied).
    local_app_data = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    trusted_roots: list[Path] = []

    if local_app_data:
        trusted_roots.append(
            Path(local_app_data)
            / "Programs"
            / "OpenAI"
            / "Codex"
            / "bin"
        )

    if user_profile:
        trusted_roots.append(
            Path(user_profile)
            / ".codex"
            / "packages"
            / "standalone"
        )

    def trusted_executable(value: str) -> str | None:
        normalized = _normalize_command_path(value)

        if (
            normalized is None
            or Path(normalized).suffix.casefold()
            != ".exe"
        ):
            return None

        if any(
            Path(normalized).is_relative_to(
                root.resolve()
            )
            for root in trusted_roots
        ):
            return normalized

        return None

    if local_app_data:
        standalone_directory = (
            Path(local_app_data)
            / "Programs"
            / "OpenAI"
            / "Codex"
            / "bin"
        )

        for filename in ("codex.exe",):
            candidate = standalone_directory / filename

            if candidate.exists():
                normalized = trusted_executable(
                    str(candidate)
                )

                if normalized:
                    return normalized

    command_names = (
        "codex.exe",
        "codex",
    )

    for command_name in command_names:
        resolved = shutil.which(command_name)

        if resolved:
            normalized = trusted_executable(
                resolved
            )

            if normalized:
                return normalized

    return None


def build_codex_command(
    *arguments: str,
) -> list[str] | None:
    codex_path = find_codex_executable()

    if not codex_path:
        return None

    return [
        codex_path,
        *arguments,
    ]


def profile_directory_for(email: str) -> Path:
    local_part = email.split("@", 1)[0]

    safe_name = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        local_part,
    ).strip("._-")

    if not safe_name:
        safe_name = "account"

    digest = hashlib.sha256(
        email.casefold().encode("utf-8")
    ).hexdigest()[:12]

    return CODEX_PROFILES_DIR / f"{safe_name[:24]}_{digest}"


def ensure_codex_profile(profile_dir: Path) -> None:
    """
    Mỗi tài khoản dùng CODEX_HOME riêng.

    Dùng file-based credential storage để phiên đăng nhập của
    các profile không đè lên nhau trong Windows Credential Manager.
    """
    profile_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    protect_sensitive_path(profile_dir)

    config_file = profile_dir / "config.toml"

    if config_file.exists():
        content = config_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
    else:
        content = ""

    setting_pattern = re.compile(
        r"^\s*cli_auth_credentials_store\s*=.*$",
        re.MULTILINE,
    )
    remaining_lines = [
        line
        for line in content.splitlines()
        if setting_pattern.fullmatch(line) is None
    ]
    first_table_index = next(
        (
            index
            for index, line in enumerate(
                remaining_lines
            )
            if line.lstrip().startswith("[")
        ),
        len(remaining_lines),
    )
    remaining_lines.insert(
        first_table_index,
        'cli_auth_credentials_store = "file"',
    )
    updated_content = "\n".join(
        remaining_lines
    ).rstrip() + "\n"

    if updated_content != content:
        config_file.write_text(
            updated_content,
            encoding="utf-8",
        )

    protect_sensitive_path(config_file)


def build_codex_environment(
    profile_dir: Path,
) -> dict[str, str]:
    ensure_codex_profile(profile_dir)

    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(profile_dir)

    return environment


def format_cycle(minutes: int | float | None) -> str:
    if minutes is None:
        return "—"

    try:
        total_minutes = int(minutes)
    except (TypeError, ValueError):
        return "—"

    if total_minutes >= 10080:
        weeks = total_minutes / 10080

        if abs(weeks - round(weeks)) < 0.01:
            count = int(round(weeks))
            return "Weekly" if count == 1 else f"{count} tuần"

    if total_minutes >= 1440:
        days = total_minutes / 1440

        if abs(days - round(days)) < 0.01:
            count = int(round(days))
            return "Daily" if count == 1 else f"{count} ngày"

    if total_minutes >= 60:
        hours = total_minutes / 60

        if abs(hours - round(hours)) < 0.01:
            return f"{int(round(hours))} giờ"

    return f"{total_minutes} phút"


def format_reset_time(timestamp: object) -> str:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        return "—"

    return datetime.fromtimestamp(
        value
    ).strftime("%d/%m %H:%M")



BANNED_ACCOUNT_MARKERS = (
    "deleted or deactivated",
    "account deactivated",
    "account has been deactivated",
    "account is deactivated",
    "account suspended",
    "account has been suspended",
    "account is suspended",
    "account disabled",
    "account has been disabled",
    "account is disabled",
    "account banned",
    "account has been banned",
    "account is banned",
)


def detect_banned_account(error_message: object) -> bool:
    """Chỉ kết luận banned khi lỗi ghi rõ tài khoản bị khóa."""
    normalized = " ".join(str(error_message).casefold().split())
    return any(marker in normalized for marker in BANNED_ACCOUNT_MARKERS)


AUTH_RELOGIN_MARKERS = (
    "failed to refresh",
    "refresh token",
    "invalid_grant",
    "invalid token",
    "token expired",
    "expired token",
    "unauthorized",
    "authentication required",
    "login required",
    "not logged in",
    "signed out",
    "logged out",
    "missing credentials",
    "credentials are invalid",
)


def requires_codex_relogin(
    error_message: object,
) -> bool:
    """
    Nhận diện profile Codex đã bị đăng xuất, token hết hạn
    hoặc không còn refresh được.

    Đây là lỗi xác thực, không phải tài khoản bị banned.
    """
    normalized = " ".join(
        str(error_message).casefold().split()
    )

    if any(
        marker in normalized
        for marker in AUTH_RELOGIN_MARKERS
    ):
        return True

    # -32603 là mã internal error chung, có thể là lỗi mạng hoặc backend.
    # Chỉ notification account/updated authMode=null, account/read trả
    # account=null, hoặc marker xác thực rõ ràng mới được coi là logout.
    return False


def extract_best_rate_limit(
    result: dict,
) -> tuple[dict | None, dict | None]:
    """
    Ưu tiên cửa sổ quota dài nhất, thường là Weekly.

    Trả về:
    - window: usedPercent, windowDurationMins, resetsAt
    - bucket: limitId, limitName, planType...
    """
    candidates: list[tuple[int, dict, dict]] = []

    buckets = result.get(
        "rateLimitsByLimitId"
    )

    if isinstance(buckets, dict):
        for bucket in buckets.values():
            if not isinstance(bucket, dict):
                continue

            for window_name in (
                "primary",
                "secondary",
            ):
                window = bucket.get(window_name)

                if not isinstance(window, dict):
                    continue

                try:
                    duration = int(
                        window.get(
                            "windowDurationMins",
                            0,
                        )
                        or 0
                    )
                except (TypeError, ValueError):
                    duration = 0

                candidates.append(
                    (duration, window, bucket)
                )

    fallback_bucket = result.get("rateLimits")

    if isinstance(fallback_bucket, dict):
        for window_name in (
            "primary",
            "secondary",
        ):
            window = fallback_bucket.get(
                window_name
            )

            if not isinstance(window, dict):
                continue

            try:
                duration = int(
                    window.get(
                        "windowDurationMins",
                        0,
                    )
                    or 0
                )
            except (TypeError, ValueError):
                duration = 0

            candidates.append(
                (
                    duration,
                    window,
                    fallback_bucket,
                )
            )

    if not candidates:
        return None, None

    _, window, bucket = max(
        candidates,
        key=lambda item: item[0],
    )

    return window, bucket


class OTPManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(
            f"OTP & Codex Account Manager - "
            f"{APP_VERSION}"
        )
        self.root.geometry("1380x760")
        self.root.minsize(1040, 600)

        self.accounts: list[Account] = []
        self.codex_info: dict[str, CodexInfo] = {}

        self.background_queue: queue.Queue[
            tuple
        ] = queue.Queue()

        self.codex_refresh_lock = threading.Lock()
        self.codex_relogin_required: set[str] = set()
        self.codex_sessions: dict[
            str,
            CodexProfileSession,
        ] = {}
        self.codex_sessions_lock = threading.Lock()
        self.closed = False

        CODEX_PROFILES_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )
        protect_sensitive_tree(
            CODEX_PROFILES_DIR
        )

        if DATA_FILE.exists():
            protect_sensitive_path(DATA_FILE)

        self.build_ui()
        self.load_accounts_from_disk()
        self.refresh_codes()
        self.process_background_events()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

        # Đồng bộ Codex sau khi giao diện mở.
        self.root.after(
            1200,
            self.refresh_all_codex_async,
        )

        self.root.after(
            CODEX_REFRESH_INTERVAL_SECONDS
            * 1000,
            self.schedule_codex_refresh,
        )

    def build_ui(self) -> None:
        self.notebook = ttk.Notebook(
            self.root
        )
        self.notebook.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        self.account_tab = ttk.Frame(
            self.notebook
        )
        self.codex_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.account_tab,
            text="Quản lý tài khoản & OTP",
        )
        self.notebook.add(
            self.codex_tab,
            text="Thông tin Codex",
        )

        self.build_account_tab()
        self.build_codex_tab()

    def build_account_tab(self) -> None:
        input_frame = ttk.LabelFrame(
            self.account_tab,
            text="Thêm hoặc cập nhật tài khoản",
            padding=10,
        )
        input_frame.pack(
            fill="x",
            padx=12,
            pady=(12, 6),
        )

        ttk.Label(
            input_frame,
            text=(
                "Mỗi tài khoản một dòng: "
                "email|password|2FA_SECRET"
            ),
        ).pack(anchor="w")

        self.input_text = tk.Text(
            input_frame,
            height=7,
            wrap="none",
        )
        self.input_text.pack(
            fill="x",
            pady=(8, 8),
        )

        button_frame = ttk.Frame(
            input_frame
        )
        button_frame.pack(fill="x")

        ttk.Button(
            button_frame,
            text="Lưu danh sách",
            command=self.submit_accounts,
        ).pack(side="left")

        ttk.Button(
            button_frame,
            text="Dán clipboard",
            command=self.paste_clipboard,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            button_frame,
            text="Xóa ô nhập",
            command=self.clear_input,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            button_frame,
            text="Xóa tài khoản đã chọn",
            command=self.delete_selected_account,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        self.status_label = ttk.Label(
            button_frame,
            text="Đang khởi động...",
        )
        self.status_label.pack(side="right")

        copy_frame = ttk.Frame(
            input_frame
        )
        copy_frame.pack(
            fill="x",
            pady=(8, 0),
        )

        ttk.Label(
            copy_frame,
            text="Sao chép tài khoản đã chọn:",
        ).pack(side="left")

        ttk.Button(
            copy_frame,
            text="Copy Email",
            command=self.copy_selected_email,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            copy_frame,
            text="Copy Password",
            command=self.copy_selected_password,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            copy_frame,
            text="Copy Secret",
            command=self.copy_selected_secret,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            copy_frame,
            text="Copy OTP",
            command=self.copy_selected_otp,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        table_frame = ttk.Frame(
            self.account_tab
        )
        table_frame.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=(6, 12),
        )

        columns = (
            "index",
            "email",
            "password",
            "secret",
            "otp",
            "remaining",
        )

        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        headings = {
            "index": "#",
            "email": "Email",
            "password": "Password",
            "secret": "2FA Secret",
            "otp": "OTP",
            "remaining": "Còn lại",
        }

        for column, title in headings.items():
            self.tree.heading(
                column,
                text=title,
            )

        self.tree.column(
            "index",
            width=45,
            anchor="center",
            stretch=False,
        )
        self.tree.column(
            "email",
            width=270,
            anchor="w",
        )
        self.tree.column(
            "password",
            width=220,
            anchor="w",
        )
        self.tree.column(
            "secret",
            width=340,
            anchor="w",
        )
        self.tree.column(
            "otp",
            width=110,
            anchor="center",
            stretch=False,
        )
        self.tree.column(
            "remaining",
            width=85,
            anchor="center",
            stretch=False,
        )

        vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )

        self.tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

        self.tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        vertical_scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        horizontal_scrollbar.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        table_frame.rowconfigure(
            0,
            weight=1,
        )
        table_frame.columnconfigure(
            0,
            weight=1,
        )

        self.tree.bind(
            "<Double-1>",
            self.copy_selected_otp,
        )

        ttk.Label(
            self.account_tab,
            text=(
                f"Dữ liệu OTP: {DATA_FILE} | "
                "Thời gian OTP: tự đồng bộ HTTPS"
            ),
        ).pack(
            anchor="w",
            padx=12,
            pady=(0, 10),
        )

    def build_codex_tab(self) -> None:
        action_frame = ttk.LabelFrame(
            self.codex_tab,
            text="Codex quota",
            padding=10,
        )
        action_frame.pack(
            fill="x",
            padx=12,
            pady=(12, 6),
        )

        ttk.Label(
            action_frame,
            text=(
                "Tài khoản ở tab OTP sẽ tự xuất hiện tại đây. "
                "Mỗi tài khoản cần bấm “Liên kết Codex” một lần "
                "để đăng nhập vào profile riêng."
            ),
        ).pack(anchor="w")

        button_frame = ttk.Frame(
            action_frame
        )
        button_frame.pack(
            fill="x",
            pady=(8, 0),
        )

        ttk.Button(
            button_frame,
            text="Liên kết Codex",
            command=self.login_selected_codex,
        ).pack(side="left")

        ttk.Button(
            button_frame,
            text="Cập nhật tài khoản đã chọn",
            command=self.refresh_selected_codex_async,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        ttk.Button(
            button_frame,
            text="Cập nhật tất cả",
            command=self.refresh_all_codex_async,
        ).pack(
            side="left",
            padx=(8, 0),
        )

        self.codex_status_label = ttk.Label(
            button_frame,
            text="Chưa đồng bộ.",
        )
        self.codex_status_label.pack(
            side="right"
        )

        table_frame = ttk.Frame(
            self.codex_tab
        )
        table_frame.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=(6, 12),
        )

        columns = (
            "index",
            "stored_email",
            "remaining",
            "cycle",
            "reset",
            "plan",
            "account_state",
            "status",
            "last_sync",
        )

        self.codex_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        headings = {
            "index": "#",
            "stored_email": "Tài khoản đã lưu",
            "remaining": "Quota còn lại",
            "cycle": "Chu kỳ",
            "reset": "Reset",
            "plan": "Gói",
            "account_state": "Tình trạng tài khoản",
            "status": "Trạng thái đồng bộ",
            "last_sync": "Cập nhật lúc",
        }

        for column, title in headings.items():
            self.codex_tree.heading(
                column,
                text=title,
            )

        self.codex_tree.column(
            "index",
            width=45,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "stored_email",
            width=260,
            anchor="w",
        )
        self.codex_tree.column(
            "remaining",
            width=115,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "cycle",
            width=100,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "reset",
            width=130,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "plan",
            width=90,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "account_state",
            width=190,
            anchor="center",
            stretch=False,
        )
        self.codex_tree.column(
            "status",
            width=220,
            anchor="center",
        )
        self.codex_tree.column(
            "last_sync",
            width=120,
            anchor="center",
            stretch=False,
        )

        vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.codex_tree.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.codex_tree.xview,
        )

        self.codex_tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

        self.codex_tree.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        vertical_scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )
        horizontal_scrollbar.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        table_frame.rowconfigure(
            0,
            weight=1,
        )
        table_frame.columnconfigure(
            0,
            weight=1,
        )

        codex_path = (
            find_codex_executable()
            or "Chưa tìm thấy"
        )

        ttk.Label(
            self.codex_tab,
            text=(
                f"Codex CLI: {codex_path} | "
                f"Tự cập nhật mỗi "
                f"{CODEX_REFRESH_INTERVAL_SECONDS} giây | "
                f"Profiles: {CODEX_PROFILES_DIR}"
            ),
        ).pack(
            anchor="w",
            padx=12,
            pady=(0, 10),
        )

    def save_accounts_to_disk(self) -> None:
        encrypted_accounts = []

        for account in self.accounts:
            encrypted_accounts.append(
                {
                    "email": encrypt_text(
                        account.email
                    ),
                    "password": encrypt_text(
                        account.password
                    ),
                    "secret": encrypt_text(
                        account.secret
                    ),
                }
            )

        output_data = {
            "version": 1,
            "accounts": encrypted_accounts,
        }

        temporary_file = DATA_FILE.with_suffix(
            ".tmp"
        )

        temporary_file.write_text(
            json.dumps(
                output_data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        protect_sensitive_path(temporary_file)

        temporary_file.replace(DATA_FILE)
        protect_sensitive_path(DATA_FILE)

    def load_accounts_from_disk(self) -> None:
        if not DATA_FILE.exists():
            self.status_label.config(
                text="Chưa có tài khoản đã lưu."
            )
            self.sync_codex_rows()
            return

        try:
            raw_data = json.loads(
                DATA_FILE.read_text(
                    encoding="utf-8"
                )
            )

            loaded_accounts: list[Account] = []
            seen_emails: set[str] = set()
            seen_secrets: set[str] = set()
            skipped_count = 0

            for item in raw_data.get(
                "accounts",
                [],
            ):
                try:
                    email = decrypt_text(
                        item["email"]
                    )
                    password = decrypt_text(
                        item["password"]
                    )
                    secret = normalize_secret(
                        decrypt_text(
                            item["secret"]
                        )
                    )

                    email_key = email.casefold()

                    if (
                        email_key in seen_emails
                        or secret in seen_secrets
                    ):
                        skipped_count += 1
                        continue

                    loaded_accounts.append(
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
                    skipped_count += 1

            self.accounts = loaded_accounts
            self.rebuild_table()
            self.sync_codex_rows()

            status = (
                f"Đã nạp {len(self.accounts)} tài khoản."
            )

            if skipped_count:
                status += (
                    f" Bỏ qua {skipped_count} dòng lỗi hoặc trùng."
                )

            self.status_label.config(
                text=status
            )

        except Exception as error:
            messagebox.showerror(
                "Không thể đọc dữ liệu",
                (
                    "Không thể mở accounts.json.\n\n"
                    f"Chi tiết: {error}"
                ),
            )

    def submit_accounts(self) -> None:
        raw_text = self.input_text.get(
            "1.0",
            "end",
        )

        lines = [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip()
        ]

        if not lines:
            messagebox.showwarning(
                "Chưa có dữ liệu",
                "Hãy dán ít nhất một tài khoản.",
            )
            return

        added_count = 0
        updated_count = 0
        duplicate_count = 0
        errors: list[str] = []

        for line_number, line in enumerate(
            lines,
            start=1,
        ):
            try:
                email, password, secret = (
                    parse_account_line(line)
                )

                totp = create_totp(secret)

                existing_by_email = next(
                    (
                        account
                        for account in self.accounts
                        if account.email.casefold()
                        == email.casefold()
                    ),
                    None,
                )

                if existing_by_email is not None:
                    identical = (
                        existing_by_email.password
                        == password
                        and existing_by_email.secret
                        == secret
                    )

                    if identical:
                        duplicate_count += 1
                        continue

                    existing_by_secret = next(
                        (
                            account
                            for account in self.accounts
                            if account.secret == secret
                            and account.email.casefold()
                            != email.casefold()
                        ),
                        None,
                    )

                    if existing_by_secret is not None:
                        errors.append(
                            (
                                f"Dòng {line_number}: secret đã được "
                                f"dùng bởi {existing_by_secret.email}."
                            )
                        )
                        continue

                    existing_by_email.password = password
                    existing_by_email.secret = secret
                    existing_by_email.totp = totp
                    updated_count += 1
                    continue

                existing_by_secret = next(
                    (
                        account
                        for account in self.accounts
                        if account.secret == secret
                    ),
                    None,
                )

                if existing_by_secret is not None:
                    errors.append(
                        (
                            f"Dòng {line_number}: secret đã được "
                            f"dùng bởi {existing_by_secret.email}."
                        )
                    )
                    continue

                self.accounts.append(
                    Account(
                        email=email,
                        password=password,
                        secret=secret,
                        totp=totp,
                    )
                )

                added_count += 1

            except Exception as error:
                errors.append(
                    f"Dòng {line_number}: {error}"
                )

        try:
            self.save_accounts_to_disk()
            self.rebuild_table()
            self.sync_codex_rows()

            self.status_label.config(
                text=(
                    f"Tổng: {len(self.accounts)} | "
                    f"Thêm: {added_count} | "
                    f"Cập nhật: {updated_count} | "
                    f"Trùng: {duplicate_count}"
                )
            )

            if added_count or updated_count:
                self.clear_input()

            if errors:
                messagebox.showwarning(
                    "Một số dòng không được lưu",
                    "\n".join(errors[:20]),
                )

        except Exception as error:
            messagebox.showerror(
                "Không thể lưu dữ liệu",
                str(error),
            )

    def rebuild_table(self) -> None:
        selected_email = self.get_selected_email()

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        current_time = corrected_time()

        for index, account in enumerate(
            self.accounts,
            start=1,
        ):
            otp_code = account.totp.at(
                current_time
            )

            remaining = (
                account.totp.interval
                - current_time
                % account.totp.interval
            )

            item_id = str(index - 1)

            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    index,
                    account.email,
                    account.password,
                    account.secret,
                    otp_code,
                    f"{remaining:02d}s",
                ),
            )

            if (
                selected_email
                and account.email.casefold()
                == selected_email.casefold()
            ):
                self.tree.selection_set(item_id)

    def refresh_codes(self) -> None:
        if self.closed:
            return

        current_time = corrected_time()

        for index, account in enumerate(
            self.accounts
        ):
            item_id = str(index)

            if not self.tree.exists(item_id):
                continue

            otp_code = account.totp.at(
                current_time
            )

            remaining = (
                account.totp.interval
                - current_time
                % account.totp.interval
            )

            values = list(
                self.tree.item(
                    item_id,
                    "values",
                )
            )

            if len(values) < 6:
                continue

            values[4] = otp_code
            values[5] = f"{remaining:02d}s"

            self.tree.item(
                item_id,
                values=values,
            )

        self.root.after(
            OTP_REFRESH_INTERVAL_MS,
            self.refresh_codes,
        )

    def sync_codex_rows(self) -> None:
        current_keys = {
            account.email.casefold()
            for account in self.accounts
        }

        for key in list(
            self.codex_info.keys()
        ):
            if key not in current_keys:
                self.close_codex_session(key)
                del self.codex_info[key]

        for account in self.accounts:
            key = account.email.casefold()

            if key not in self.codex_info:
                self.codex_info[key] = CodexInfo(
                    stored_email=account.email
                )
            else:
                self.codex_info[
                    key
                ].stored_email = account.email

        self.rebuild_codex_table()

    def rebuild_codex_table(self) -> None:
        selected_key = (
            self.get_selected_codex_email_key()
        )

        for item_id in self.codex_tree.get_children():
            self.codex_tree.delete(item_id)

        for index, account in enumerate(
            self.accounts,
            start=1,
        ):
            key = account.email.casefold()

            info = self.codex_info.setdefault(
                key,
                CodexInfo(
                    stored_email=account.email
                ),
            )

            item_id = str(index - 1)

            self.codex_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    index,
                    info.stored_email,
                    info.remaining_percent,
                    info.cycle,
                    info.reset_at,
                    info.plan_type,
                    info.account_state,
                    info.status,
                    info.last_sync,
                ),
            )

            if key == selected_key:
                self.codex_tree.selection_set(
                    item_id
                )

    def update_codex_row(
        self,
        email_key: str,
    ) -> None:
        account_index = next(
            (
                index
                for index, account in enumerate(
                    self.accounts
                )
                if account.email.casefold()
                == email_key
            ),
            None,
        )

        if account_index is None:
            return

        item_id = str(account_index)

        if not self.codex_tree.exists(
            item_id
        ):
            self.rebuild_codex_table()
            return

        info = self.codex_info[email_key]

        self.codex_tree.item(
            item_id,
            values=(
                account_index + 1,
                info.stored_email,
                info.remaining_percent,
                info.cycle,
                info.reset_at,
                info.plan_type,
                info.account_state,
                info.status,
                info.last_sync,
            ),
        )

    def get_selected_email(self) -> str | None:
        selected = self.tree.selection()

        if not selected:
            return None

        values = self.tree.item(
            selected[0],
            "values",
        )

        if len(values) < 2:
            return None

        return str(values[1])

    def get_selected_account(
        self,
    ) -> Account | None:
        selected_email = self.get_selected_email()

        if selected_email is None:
            return None

        return next(
            (
                account
                for account in self.accounts
                if account.email.casefold()
                == selected_email.casefold()
            ),
            None,
        )

    def get_selected_codex_email_key(
        self,
    ) -> str | None:
        selected = self.codex_tree.selection()

        if not selected:
            return None

        values = self.codex_tree.item(
            selected[0],
            "values",
        )

        if len(values) < 2:
            return None

        return str(values[1]).casefold()

    def get_account_by_key(
        self,
        email_key: str,
    ) -> Account | None:
        return next(
            (
                account
                for account in self.accounts
                if account.email.casefold()
                == email_key
            ),
            None,
        )

    def get_codex_session(
        self,
        email_key: str,
        profile_dir: Path,
    ) -> CodexProfileSession:
        with self.codex_sessions_lock:
            existing = self.codex_sessions.get(
                email_key
            )

            if existing is not None:
                return existing

            command = build_codex_command(
                "app-server"
            )

            if command is None:
                raise RuntimeError(
                    "Không tìm thấy lệnh codex trong PATH."
                )

            creation_flags = 0

            if os.name == "nt":
                creation_flags = getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                )

            def handle_notification(
                event_type: str,
                payload: dict,
            ) -> None:
                if self.closed:
                    return

                if event_type == "rate_limits_updated":
                    self.background_queue.put(
                        (
                            "codex_result",
                            email_key,
                            payload,
                        )
                    )
                elif event_type == "relogin_required":
                    self.background_queue.put(
                        (
                            "codex_relogin_required",
                            email_key,
                        )
                    )
                elif event_type == "account_updated":
                    self.background_queue.put(
                        (
                            "codex_account_active",
                            email_key,
                        )
                    )
                elif event_type == "server_stopped":
                    self.background_queue.put(
                        (
                            "codex_server_stopped",
                            email_key,
                        )
                    )

            session = CodexProfileSession(
                profile_dir=profile_dir,
                command=command,
                environment=build_codex_environment(
                    profile_dir
                ),
                notification_handler=(
                    handle_notification
                ),
                timeout_seconds=(
                    CODEX_QUERY_TIMEOUT_SECONDS
                ),
                creation_flags=creation_flags,
            )
            self.codex_sessions[email_key] = session
            return session

    def close_codex_session(
        self,
        email_key: str,
    ) -> None:
        with self.codex_sessions_lock:
            session = self.codex_sessions.pop(
                email_key,
                None,
            )

        if session is not None:
            session.close()

    def copy_to_clipboard(
        self,
        value: str,
        field_name: str,
        account: Account,
    ) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()

        self.status_label.config(
            text=(
                f"Đã copy {field_name} của "
                f"{account.email}."
            )
        )

    def copy_selected_email(self) -> None:
        account = self.get_selected_account()

        if account is None:
            self.status_label.config(
                text="Chưa chọn tài khoản."
            )
            return

        self.copy_to_clipboard(
            account.email,
            "Email",
            account,
        )

    def copy_selected_password(self) -> None:
        account = self.get_selected_account()

        if account is None:
            self.status_label.config(
                text="Chưa chọn tài khoản."
            )
            return

        self.copy_to_clipboard(
            account.password,
            "Password",
            account,
        )

    def copy_selected_secret(self) -> None:
        account = self.get_selected_account()

        if account is None:
            self.status_label.config(
                text="Chưa chọn tài khoản."
            )
            return

        self.copy_to_clipboard(
            account.secret,
            "2FA Secret",
            account,
        )

    def copy_selected_otp(
        self,
        event=None,
    ) -> None:
        account = self.get_selected_account()

        if account is None:
            self.status_label.config(
                text="Chưa chọn tài khoản."
            )
            return

        otp_code = account.totp.at(
            corrected_time()
        )

        self.copy_to_clipboard(
            otp_code,
            "OTP",
            account,
        )

    def delete_selected_account(self) -> None:
        account = self.get_selected_account()

        if account is None:
            messagebox.showwarning(
                "Chưa chọn tài khoản",
                "Hãy chọn tài khoản cần xóa.",
            )
            return

        confirmed = messagebox.askyesno(
            "Xác nhận xóa",
            (
                "Xóa tài khoản này khỏi danh sách?\n\n"
                f"{account.email}"
            ),
        )

        if not confirmed:
            return

        self.accounts = [
            existing_account
            for existing_account in self.accounts
            if existing_account.email.casefold()
            != account.email.casefold()
        ]

        try:
            self.save_accounts_to_disk()
            self.rebuild_table()
            self.sync_codex_rows()

            self.status_label.config(
                text=(
                    f"Đã xóa {account.email}. "
                    f"Còn {len(self.accounts)} tài khoản."
                )
            )

        except Exception as error:
            messagebox.showerror(
                "Không thể lưu dữ liệu",
                str(error),
            )

    def paste_clipboard(self) -> None:
        try:
            clipboard_text = (
                self.root.clipboard_get()
            )

            current_content = self.input_text.get(
                "1.0",
                "end-1c",
            )

            if current_content.strip():
                self.input_text.insert(
                    "end",
                    "\n",
                )

            self.input_text.insert(
                "end",
                clipboard_text,
            )

        except tk.TclError:
            messagebox.showwarning(
                "Clipboard trống",
                "Clipboard không chứa văn bản.",
            )

    def clear_input(self) -> None:
        self.input_text.delete(
            "1.0",
            "end",
        )

    def login_selected_codex(self) -> None:
        email_key = (
            self.get_selected_codex_email_key()
        )

        if email_key is None:
            messagebox.showwarning(
                "Chưa chọn tài khoản",
                "Hãy chọn tài khoản cần liên kết Codex.",
            )
            return

        account = self.get_account_by_key(
            email_key
        )

        if account is None:
            return

        command = build_codex_command(
            "login"
        )

        if command is None:
            messagebox.showerror(
                "Chưa cài Codex CLI",
                (
                    "Không tìm thấy lệnh codex.\n\n"
                    "Hãy cài Codex CLI trước, sau đó mở lại ứng dụng."
                ),
            )
            return

        profile_dir = profile_directory_for(
            account.email
        )

        environment = build_codex_environment(
            profile_dir
        )

        info = self.codex_info[email_key]

        # Người dùng chủ động liên kết lại, cho phép profile
        # được kiểm tra lại ngay sau khi login hoàn tất.
        self.codex_relogin_required.discard(
            email_key
        )
        # App-server đang chạy giữ auth state trong bộ nhớ. Dừng phiên cũ
        # trước khi login để lần đồng bộ sau nạp auth.json vừa cập nhật.
        self.close_codex_session(email_key)

        info.status = "Đang chờ đăng nhập..."
        self.update_codex_row(email_key)

        try:
            creation_flags = 0

            if os.name == "nt":
                creation_flags = getattr(
                    subprocess,
                    "CREATE_NEW_CONSOLE",
                    0,
                )

            process = subprocess.Popen(
                command,
                env=environment,
                creationflags=creation_flags,
            )

        except Exception as error:
            info.status = (
                f"Không mở được đăng nhập: {error}"
            )
            self.update_codex_row(email_key)
            return

        def wait_for_login() -> None:
            return_code = process.wait()

            self.background_queue.put(
                (
                    "login_finished",
                    email_key,
                    return_code,
                )
            )

        threading.Thread(
            target=wait_for_login,
            daemon=True,
        ).start()

    def refresh_selected_codex_async(
        self,
    ) -> None:
        email_key = (
            self.get_selected_codex_email_key()
        )

        if email_key is None:
            messagebox.showwarning(
                "Chưa chọn tài khoản",
                "Hãy chọn tài khoản cần cập nhật.",
            )
            return

        account = self.get_account_by_key(
            email_key
        )

        if account is None:
            return

        self.start_codex_sync_thread(
            [account]
        )

    def refresh_all_codex_async(
        self,
    ) -> None:
        if not self.accounts:
            self.codex_status_label.config(
                text="Chưa có tài khoản."
            )
            return

        self.start_codex_sync_thread(
            list(self.accounts)
        )

    def start_codex_sync_thread(
        self,
        accounts: list[Account],
    ) -> None:
        if not self.codex_refresh_lock.acquire(
            blocking=False
        ):
            self.codex_status_label.config(
                text="Đang có một lượt đồng bộ chạy."
            )
            return

        self.codex_status_label.config(
            text=(
                f"Đang đồng bộ "
                f"{len(accounts)} tài khoản..."
            )
        )

        def worker() -> None:
            summary = {
                "success": 0,
                "unlinked": 0,
                "relogin": 0,
                "error": 0,
            }

            def sync_one(account: Account) -> str:
                if self.closed:
                    return "error"

                email_key = account.email.casefold()

                if email_key in self.codex_relogin_required:
                    self.background_queue.put(
                        (
                            "codex_relogin_required",
                            email_key,
                        )
                    )
                    return "relogin"

                profile_dir = profile_directory_for(
                    account.email
                )
                auth_file = profile_dir / "auth.json"

                if not auth_file.exists():
                    self.close_codex_session(email_key)
                    self.background_queue.put(
                        (
                            "codex_unlinked",
                            email_key,
                        )
                    )
                    return "unlinked"

                self.background_queue.put(
                    (
                        "codex_syncing",
                        email_key,
                    )
                )

                try:
                    session = self.get_codex_session(
                        email_key,
                        profile_dir,
                    )
                    result = session.query()
                    self.background_queue.put(
                        (
                            "codex_result",
                            email_key,
                            result,
                        )
                    )
                    return "success"

                except CodexReloginRequired:
                    self.background_queue.put(
                        (
                            "codex_relogin_required",
                            email_key,
                        )
                    )
                    return "relogin"

                except Exception as error:
                    self.background_queue.put(
                        (
                            "codex_error",
                            email_key,
                            str(error),
                        )
                    )
                    return "error"

            try:
                codex_path = (
                    find_codex_executable()
                )

                if not codex_path:
                    for account in accounts:
                        self.background_queue.put(
                            (
                                "codex_error",
                                account.email.casefold(),
                                (
                                    "Chưa cài Codex CLI "
                                    "hoặc codex chưa có trong PATH."
                                ),
                            )
                        )
                        summary["error"] += 1
                    return

                worker_count = min(
                    4,
                    max(1, len(accounts)),
                )

                with ThreadPoolExecutor(
                    max_workers=worker_count,
                    thread_name_prefix="codex-sync",
                ) as executor:
                    futures = [
                        executor.submit(sync_one, account)
                        for account in accounts
                    ]

                    for future in as_completed(futures):
                        try:
                            status = future.result()
                        except Exception:
                            status = "error"

                        summary[status] += 1

            finally:
                self.codex_refresh_lock.release()

                self.background_queue.put(
                    (
                        "codex_batch_finished",
                        summary,
                    )
                )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def apply_codex_result(
        self,
        email_key: str,
        result: dict,
    ) -> None:
        info = self.codex_info.get(
            email_key
        )

        if info is None:
            return

        # Đọc được dữ liệu thành công nghĩa là profile đã hoạt động lại.
        self.codex_relogin_required.discard(
            email_key
        )

        account_result = result.get(
            "account",
            {},
        )
        account_data = account_result.get(
            "account"
        )

        if not isinstance(account_data, dict):
            if info.account_state != "Bị khóa (banned)":
                info.account_state = "Chưa xác định"

            info.codex_email = "—"
            info.remaining_percent = "—"
            info.cycle = "—"
            info.reset_at = "—"
            info.plan_type = "—"
            info.status = (
                "Chưa đăng nhập hoặc phiên đã hết hạn"
            )
            info.last_sync = datetime.now().strftime(
                "%H:%M:%S"
            )
            self.update_codex_row(email_key)
            return

        info.account_state = "Hoạt động bình thường"


        codex_email = str(
            account_data.get("email") or "—"
        )
        plan_type = str(
            account_data.get("planType")
            or "—"
        )

        if (
            codex_email != "—"
            and codex_email.casefold()
            != info.stored_email.casefold()
        ):
            # Không hiển thị quota của tài khoản Codex A trên dòng tài
            # khoản lưu B. Giữ profile ở trạng thái cách ly đến khi user
            # liên kết lại đúng email.
            info.codex_email = codex_email
            info.remaining_percent = "—"
            info.cycle = "—"
            info.reset_at = "—"
            info.plan_type = "—"
            info.account_state = "Sai tài khoản Codex"
            info.status = (
                "Email Codex khác – bấm Liên kết Codex"
            )
            info.last_sync = datetime.now().strftime(
                "%H:%M:%S"
            )
            self.codex_relogin_required.add(
                email_key
            )
            self.update_codex_row(email_key)
            return

        limits_result = result.get(
            "limits",
            {},
        )

        window, bucket = extract_best_rate_limit(
            limits_result
        )

        info.codex_email = codex_email
        info.plan_type = (
            plan_type.capitalize()
            if plan_type != "—"
            else "—"
        )

        if window is None:
            info.remaining_percent = "—"
            info.cycle = "—"
            info.reset_at = "—"
            info.status = "Không có dữ liệu quota"
        else:
            try:
                used_percent = float(
                    window.get("usedPercent", 0)
                    or 0
                )
                remaining = max(
                    0.0,
                    min(
                        100.0,
                        100.0 - used_percent,
                    ),
                )

                if abs(
                    remaining - round(remaining)
                ) < 0.05:
                    info.remaining_percent = (
                        f"{int(round(remaining))}%"
                    )
                else:
                    info.remaining_percent = (
                        f"{remaining:.1f}%"
                    )

            except (TypeError, ValueError):
                info.remaining_percent = "—"

            info.cycle = format_cycle(
                window.get(
                    "windowDurationMins"
                )
            )
            info.reset_at = format_reset_time(
                window.get("resetsAt")
            )

            if (
                bucket
                and info.plan_type == "—"
                and bucket.get("planType")
            ):
                info.plan_type = str(
                    bucket["planType"]
                ).capitalize()

            info.status = "Đã đồng bộ"

        info.last_sync = datetime.now().strftime(
            "%H:%M:%S"
        )

        self.update_codex_row(email_key)

    def process_background_events(self) -> None:
        if self.closed:
            return

        while True:
            try:
                event = self.background_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]

            if event_type == "codex_syncing":
                email_key = event[1]
                info = self.codex_info.get(
                    email_key
                )

                if info:
                    info.status = "Đang đồng bộ..."
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == "codex_unlinked":
                email_key = event[1]
                info = self.codex_info.get(
                    email_key
                )

                if info:
                    if info.account_state != "Bị khóa (banned)":
                        info.account_state = "Chưa xác định"

                    info.status = "Chưa liên kết"
                    info.last_sync = "—"
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == (
                "codex_relogin_required"
            ):
                email_key = event[1]
                info = self.codex_info.get(
                    email_key
                )

                if info:
                    self.codex_relogin_required.add(
                        email_key
                    )
                    info.status = (
                        "Đã đăng xuất – bấm Liên kết Codex"
                    )
                    info.last_sync = (
                        datetime.now().strftime(
                            "%H:%M:%S"
                        )
                    )
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == "codex_account_active":
                email_key = event[1]
                info = self.codex_info.get(
                    email_key
                )
                self.codex_relogin_required.discard(
                    email_key
                )

                if (
                    info
                    and info.status.startswith(
                        "Đã đăng xuất"
                    )
                ):
                    info.status = (
                        "Phiên đã hoạt động, chờ cập nhật quota"
                    )
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == "codex_server_stopped":
                email_key = event[1]
                info = self.codex_info.get(
                    email_key
                )

                if (
                    info
                    and email_key
                    not in self.codex_relogin_required
                ):
                    info.status = (
                        "App-server đã dừng, sẽ tự kết nối lại"
                    )
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == "codex_result":
                self.apply_codex_result(
                    event[1],
                    event[2],
                )

            elif event_type == "codex_error":
                email_key = event[1]
                error_message = event[2]
                info = self.codex_info.get(
                    email_key
                )

                if info:
                    if detect_banned_account(
                        error_message
                    ):
                        # Chỉ đánh dấu banned khi lỗi ghi rõ
                        # tài khoản bị khóa/vô hiệu hóa.
                        info.account_state = (
                            "Bị khóa (banned)"
                        )
                        info.status = (
                            "OpenAI đã khóa hoặc "
                            "vô hiệu hóa tài khoản"
                        )

                    elif requires_codex_relogin(
                        error_message
                    ):
                        # Logout/token hỏng không phải banned.
                        # Giữ nguyên quota và tình trạng gần nhất,
                        # đồng thời dừng auto-sync cho profile này.
                        self.codex_relogin_required.add(
                            email_key
                        )
                        info.status = (
                            "Đã đăng xuất – "
                            "bấm Liên kết Codex"
                        )

                    else:
                        if info.account_state not in (
                            "Hoạt động bình thường",
                            "Bị khóa (banned)",
                        ):
                            info.account_state = (
                                "Chưa xác định"
                            )
                        info.status = (
                            "Lỗi đồng bộ tạm thời – "
                            "ứng dụng sẽ tự thử lại"
                        )

                    info.last_sync = (
                        datetime.now().strftime(
                            "%H:%M:%S"
                        )
                    )
                    self.update_codex_row(
                        email_key
                    )

            elif event_type == "login_finished":
                email_key = event[1]
                return_code = event[2]
                info = self.codex_info.get(
                    email_key
                )

                if info:
                    if return_code == 0:
                        self.codex_relogin_required.discard(
                            email_key
                        )
                        info.status = (
                            "Đăng nhập xong, đang đồng bộ..."
                        )
                    else:
                        info.status = (
                            f"Đăng nhập kết thúc với mã "
                            f"{return_code}"
                        )

                    self.update_codex_row(
                        email_key
                    )

                account = self.get_account_by_key(
                    email_key
                )

                if account and return_code == 0:
                    self.start_codex_sync_thread(
                        [account]
                    )

            elif event_type == (
                "codex_batch_finished"
            ):
                summary = event[1]
                total_errors = (
                    summary["error"]
                    + summary["relogin"]
                    + summary["unlinked"]
                )
                summary_text = (
                    f"{summary['success']} thành công"
                )

                if total_errors:
                    summary_text += (
                        f", {summary['relogin']} cần đăng nhập, "
                        f"{summary['unlinked']} chưa liên kết, "
                        f"{summary['error']} lỗi tạm thời"
                    )

                self.codex_status_label.config(
                    text=(
                        "Đồng bộ: "
                        + summary_text
                        + " lúc "
                        + datetime.now().strftime(
                            "%H:%M:%S"
                        )
                    )
                )

        self.root.after(
            250,
            self.process_background_events,
        )

    def schedule_codex_refresh(self) -> None:
        if self.closed:
            return

        self.refresh_all_codex_async()

        self.root.after(
            CODEX_REFRESH_INTERVAL_SECONDS
            * 1000,
            self.schedule_codex_refresh,
        )

    def on_close(self) -> None:
        self.closed = True

        with self.codex_sessions_lock:
            sessions = list(
                self.codex_sessions.values()
            )
            self.codex_sessions.clear()

        for session in sessions:
            session.close()

        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    OTPManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
