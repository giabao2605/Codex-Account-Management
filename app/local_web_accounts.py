from __future__ import annotations

from typing import Literal

from .otp_codex_manager_with_account_status import (
    Account,
    create_totp,
    parse_account_line,
)


ConflictField = Literal["email", "secret"]


class AccountConflictError(ValueError):
    def __init__(self, field: ConflictField) -> None:
        self.field = field
        message = (
            "Email đã tồn tại."
            if field == "email"
            else "Secret 2FA đã được dùng bởi tài khoản khác."
        )
        super().__init__(message)


def parse_new_account(raw_text: str) -> Account:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Hãy nhập thông tin tài khoản.")
    if len(lines) != 1:
        raise ValueError("Mỗi lần chỉ được thêm một tài khoản.")

    email, password, secret = parse_account_line(lines[0])
    return Account(
        email=email,
        password=password,
        secret=secret,
        totp=create_totp(secret),
    )


def find_account_conflict(
    current_accounts: tuple[Account, ...],
    candidate: Account,
) -> ConflictField | None:
    if any(
        account.email.casefold() == candidate.email.casefold()
        for account in current_accounts
    ):
        return "email"
    if any(
        account.secret == candidate.secret
        for account in current_accounts
    ):
        return "secret"
    return None


def append_new_account(
    current_accounts: tuple[Account, ...],
    raw_text: str,
) -> tuple[tuple[Account, ...], Account]:
    candidate = parse_new_account(raw_text)
    conflict = find_account_conflict(current_accounts, candidate)
    if conflict is not None:
        raise AccountConflictError(conflict)
    return (*current_accounts, candidate), candidate
