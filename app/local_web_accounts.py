from __future__ import annotations

from .otp_codex_manager_with_account_status import (
    Account,
    create_totp,
    parse_account_line,
)


def merge_accounts(
    current_accounts: tuple[Account, ...],
    raw_text: str,
) -> tuple[tuple[Account, ...], dict]:
    merged_accounts, result, _ = plan_account_merge(
        current_accounts,
        raw_text,
    )
    return merged_accounts, result


def plan_account_merge(
    current_accounts: tuple[Account, ...],
    raw_text: str,
) -> tuple[tuple[Account, ...], dict, tuple[dict[str, str], ...]]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    if not lines:
        raise ValueError("Hãy nhập ít nhất một tài khoản.")
    if len(lines) > 500:
        raise ValueError("Mỗi lần chỉ được nhập tối đa 500 dòng.")

    working_accounts = list(current_accounts)
    added = 0
    updated = 0
    duplicates = 0
    errors: list[str] = []
    changes: list[dict[str, str]] = []

    for line_number, line in enumerate(lines, start=1):
        try:
            email, password, secret = parse_account_line(line)
            replacement = Account(
                email=email,
                password=password,
                secret=secret,
                totp=create_totp(secret),
            )
            email_index = next(
                (
                    index
                    for index, account in enumerate(working_accounts)
                    if account.email.casefold() == email.casefold()
                ),
                None,
            )
            secret_owner = next(
                (
                    account
                    for account in working_accounts
                    if account.secret == secret
                    and account.email.casefold() != email.casefold()
                ),
                None,
            )

            if secret_owner is not None:
                errors.append(
                    f"Dòng {line_number}: secret đã được dùng bởi "
                    f"{secret_owner.email}."
                )
                continue

            if email_index is None:
                working_accounts = [*working_accounts, replacement]
                added += 1
                changes.append({"email": email, "action": "add"})
                continue

            existing = working_accounts[email_index]
            if existing.password == password and existing.secret == secret:
                duplicates += 1
                continue

            working_accounts = [
                replacement if index == email_index else account
                for index, account in enumerate(working_accounts)
            ]
            updated += 1
            changes.append({"email": email, "action": "update"})
        except Exception as error:
            errors.append(f"Dòng {line_number}: {error}")

    merged_accounts = tuple(working_accounts)
    result = {
        "total": len(merged_accounts),
        "added": added,
        "updated": updated,
        "duplicates": duplicates,
        "error_count": len(errors),
        "errors": errors[:20],
    }
    return merged_accounts, result, tuple(changes)
