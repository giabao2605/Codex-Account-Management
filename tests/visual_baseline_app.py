from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI

from app.local_web_app import create_app
from app.local_web_accounts import AccountConflictError


# Public, non-production credentials used only by the sanitized visual fixture.
VISUAL_BASELINE_ACCESS_TOKEN = "visual-baseline-access-token"
VISUAL_BASELINE_CSRF_TOKEN = "visual-baseline-csrf-token"
_GENERATED_AT = "2026-07-23T09:45:00+07:00"
_TODAY = date(2026, 7, 23)


def _series(
    *,
    multiplier: int,
    available: bool = True,
) -> dict[str, list[dict[str, object]]]:
    daily_start = _TODAY - timedelta(days=29)
    week_start = _TODAY - timedelta(days=_TODAY.weekday(), weeks=11)
    month_start = date(2025, 8, 1)
    return {
        "daily": [
            {
                "start_date": current.isoformat(),
                "end_date": current.isoformat(),
                "tokens": (
                    (index % 7 + 1) * multiplier
                    if available
                    else None
                ),
            }
            for index in range(30)
            for current in (daily_start + timedelta(days=index),)
        ],
        "weekly": [
            {
                "start_date": current.isoformat(),
                "end_date": (current + timedelta(days=6)).isoformat(),
                "tokens": (
                    (index + 1) * multiplier * 7
                    if available
                    else None
                ),
            }
            for index in range(12)
            for current in (week_start + timedelta(weeks=index),)
        ],
        "monthly": [
            {
                "start_date": current.isoformat(),
                "end_date": (
                    date(
                        current.year + (current.month == 12),
                        current.month % 12 + 1,
                        1,
                    )
                    - timedelta(days=1)
                ).isoformat(),
                "tokens": (
                    (index + 1) * multiplier * 30
                    if available
                    else None
                ),
            }
            for index in range(12)
            for month_index in (month_start.month - 1 + index,)
            for current in (
                date(
                    month_start.year + month_index // 12,
                    month_index % 12 + 1,
                    1,
                ),
            )
        ],
    }


def _daily_buckets(multiplier: int) -> list[dict[str, object]]:
    start = _TODAY - timedelta(days=44)
    return [
        {
            "start_date": (start + timedelta(days=index)).isoformat(),
            "tokens": (index % 7 + 1) * multiplier,
        }
        for index in range(45)
    ]


_ACCOUNT_ROWS = [
    {
        "id": "1111111111111111",
        "email": "alpha@example.test",
        "otp": "123456",
        "otp_remaining_seconds": 24,
        "quota_remaining": "82%",
        "quota_cycle": "5 giờ",
        "quota_reset_at": "23/07 14:00",
        "banked_reset_count": 2,
        "banked_reset_expires_at": ["30/07 09:00", "Không hết hạn"],
        "plus_expires_at": "2026-10-11",
        "quota_windows": [
            {
                "quota_remaining": "82%",
                "quota_cycle": "5 giờ",
                "quota_reset_at": "23/07 14:00",
            },
            {
                "quota_remaining": "64%",
                "quota_cycle": "Weekly",
                "quota_reset_at": "28/07 09:00",
            },
        ],
        "plan_type": "Plus",
        "account_state": "Hoạt động bình thường",
        "sync_status": "Đã đồng bộ",
        "last_sync": "23/07 09:45",
    },
    {
        "id": "2222222222222222",
        "email": "beta@example.test",
        "otp": "654321",
        "otp_remaining_seconds": 11,
        "quota_remaining": "12%",
        "quota_cycle": "5 giờ",
        "quota_reset_at": "23/07 12:30",
        "banked_reset_count": 3,
        "banked_reset_expires_at": None,
        "plus_expires_at": None,
        "quota_windows": [
            {
                "quota_remaining": "12%",
                "quota_cycle": "5 giờ",
                "quota_reset_at": "23/07 12:30",
            },
            {
                "quota_remaining": "48%",
                "quota_cycle": "Weekly",
                "quota_reset_at": "28/07 09:00",
            },
        ],
        "plan_type": "Plus",
        "account_state": "Hoạt động bình thường",
        "sync_status": "Dữ liệu token đã cũ",
        "last_sync": "23/07 09:30",
    },
    {
        "id": "3333333333333333",
        "email": "gamma@example.test",
        "otp": None,
        "otp_remaining_seconds": None,
        "quota_remaining": "Chưa rõ",
        "quota_cycle": "Chưa rõ",
        "quota_reset_at": "Chưa rõ",
        "banked_reset_count": None,
        "banked_reset_expires_at": None,
        "plus_expires_at": None,
        "quota_windows": [],
        "plan_type": "Chưa rõ",
        "account_state": "Chưa xác định",
        "sync_status": "Chưa liên kết",
        "last_sync": "Chưa đồng bộ",
    },
]


def _usage_account(
    account: dict[str, object],
    *,
    remaining: float | None,
    usable: bool,
    attention: bool,
    stale: bool,
) -> dict[str, object]:
    return {
        "account_id": account["id"],
        "email": account["email"],
        "quota_remaining_percent": remaining,
        "quota_used_percent": (
            round(100 - remaining, 2)
            if remaining is not None
            else None
        ),
        "quota_cycle": account["quota_cycle"],
        "quota_reset_at": account["quota_reset_at"],
        "plan_type": account["plan_type"],
        "account_state": account["account_state"],
        "sync_status": account["sync_status"],
        "last_sync": account["last_sync"],
        "is_usable": usable,
        "needs_attention": attention,
        "quota_is_stale": stale,
    }


_USAGE_ACCOUNTS = [
    _usage_account(
        _ACCOUNT_ROWS[0],
        remaining=82.0,
        usable=True,
        attention=False,
        stale=False,
    ),
    _usage_account(
        _ACCOUNT_ROWS[1],
        remaining=12.0,
        usable=True,
        attention=False,
        stale=True,
    ),
    _usage_account(
        _ACCOUNT_ROWS[2],
        remaining=None,
        usable=False,
        attention=True,
        stale=False,
    ),
]


def _token_account(
    account: dict[str, object],
    *,
    status: str,
    multiplier: int,
) -> dict[str, object]:
    available = status != "unavailable"
    return {
        "account_id": account["id"],
        "email": account["email"],
        "status": status,
        "updated_at": _GENERATED_AT if available else None,
        "today": 2_400 * multiplier if available else None,
        "week": 12_600 * multiplier if available else None,
        "month": 48_000 * multiplier if available else None,
        "lifetime": 820_000 * multiplier if available else None,
        "peak_daily": 18_500 * multiplier if available else None,
        "longest_running_turn_seconds": 312 if available else None,
        "current_streak_days": 6 if available else None,
        "longest_streak_days": 18 if available else None,
        "daily_buckets": (
            _daily_buckets(multiplier)
            if available
            else None
        ),
        "series": _series(
            multiplier=multiplier,
            available=available,
        ),
    }


_TOKEN_ACCOUNTS = [
    _token_account(_ACCOUNT_ROWS[0], status="fresh", multiplier=2),
    _token_account(_ACCOUNT_ROWS[1], status="stale", multiplier=1),
    _token_account(
        _ACCOUNT_ROWS[2],
        status="unavailable",
        multiplier=1,
    ),
]


class VisualBaselineService:
    access_token = VISUAL_BASELINE_ACCESS_TOKEN
    csrf_token = VISUAL_BASELINE_CSRF_TOKEN

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def state(self) -> dict[str, object]:
        return {
            "accounts": _ACCOUNT_ROWS,
            "sync_status": "Đã đồng bộ 2/3 tài khoản",
            "refresh_interval_seconds": 30,
            "recommendation": {
                "account_id": _ACCOUNT_ROWS[0]["id"],
                "email": _ACCOUNT_ROWS[0]["email"],
                "quota_remaining": "82%",
                "quota_reset_at": "23/07 14:00",
            },
            "recommendation_queue": [
                {
                    "account_id": _ACCOUNT_ROWS[0]["id"],
                    "email": _ACCOUNT_ROWS[0]["email"],
                    "quota_remaining": "82%",
                    "quota_reset_at": "23/07 14:00",
                    "rank": 1,
                    "reason": (
                        "Hoạt động bình thường · còn 82% quota · "
                        "reset 23/07 14:00"
                    ),
                },
                {
                    "account_id": _ACCOUNT_ROWS[1]["id"],
                    "email": _ACCOUNT_ROWS[1]["email"],
                    "quota_remaining": "12%",
                    "quota_reset_at": "23/07 12:30",
                    "rank": 2,
                    "reason": (
                        "Hoạt động bình thường · còn 12% quota · "
                        "reset 23/07 12:30"
                    ),
                },
            ],
            "usage_statistics": {
                "schema_version": 1,
                "history_available": False,
                "source": "codex_rate_limits_snapshot",
                "generated_at": _GENERATED_AT,
                "total_accounts": 3,
                "quota_known_accounts": 2,
                "quota_unknown_accounts": 1,
                "stale_quota_accounts": 1,
                "usable_accounts": 2,
                "attention_accounts": 1,
                "low_quota_accounts": 1,
                "exhausted_accounts": 0,
                "average_remaining_percent": 47.0,
                "average_used_percent": 53.0,
                "minimum_remaining_percent": 12.0,
                "maximum_remaining_percent": 82.0,
                "median_remaining_percent": 47.0,
                "next_reset_at": "23/07 12:30",
                "plan_distribution": [
                    {"plan_type": "Plus", "count": 2},
                    {"plan_type": "Chưa rõ", "count": 1},
                ],
                "accounts": _USAGE_ACCOUNTS,
            },
            "time_sync": {
                "status": "synced",
                "offset_seconds": 0.12,
                "last_synced_at": _GENERATED_AT,
                "source_count": 3,
            },
        }

    def token_usage_statistics(self) -> dict[str, object]:
        aggregate_buckets = [
            {
                "start_date": bucket["start_date"],
                "tokens": int(bucket["tokens"]) * 3,
            }
            for bucket in _daily_buckets(1)
        ]
        return {
            "schema_version": 2,
            "source": "codex_account_usage",
            "generated_at": _GENERATED_AT,
            "coverage": {
                "total_accounts": 3,
                "fresh_accounts": 1,
                "stale_accounts": 1,
                "unavailable_accounts": 1,
            },
            "periods": {
                "today": {
                    "start_date": "2026-07-23",
                    "end_date": "2026-07-23",
                    "is_partial": True,
                },
                "current_week": {
                    "start_date": "2026-07-20",
                    "end_date": "2026-07-26",
                    "is_partial": True,
                },
                "current_month": {
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "is_partial": True,
                },
            },
            "aggregate": {
                "totals": {
                    "today": 7_200,
                    "week": 37_800,
                    "month": 144_000,
                    "lifetime": 2_460_000,
                },
                "averages": {
                    "today": 3_600.0,
                    "week": 18_900.0,
                    "month": 72_000.0,
                    "lifetime": 1_230_000.0,
                },
                "sample_sizes": {
                    "today": 2,
                    "week": 2,
                    "month": 2,
                    "lifetime": 2,
                },
                "daily_buckets": aggregate_buckets,
                "series": _series(multiplier=3),
            },
            "accounts": _TOKEN_ACCOUNTS,
        }

    def failover_status(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "available": True,
            "enabled": False,
            "state": "disabled",
            "updated_at": None,
            "has_error": False,
            "tasks": {
                "total": 0,
                "active": 0,
                "completed": 0,
                "blocked": 0,
                "quota_exhausted": 0,
                "eligible": 0,
            },
            "quotas": {"total": 0, "exhausted": 0},
        }

    def refresh_async(
        self,
        account_ids: set[str] | None,
        *,
        force_token_usage: bool = False,
    ) -> bool:
        del account_ids, force_token_usage
        return True

    def login(self, account_id: str) -> None:
        del account_id

    def unlink_profile(self, account_id: str) -> None:
        del account_id

    def delete_account(self, account_id: str) -> None:
        del account_id

    def sensitive_value(
        self,
        account_id: str,
        field: str,
    ) -> str:
        del account_id, field
        return "fixture-only-value"

    def update_password(self, account_id: str, password: str) -> None:
        del account_id, password

    def update_plus_expiration(
        self,
        account_id: str,
        plus_expires_at: str | None,
    ) -> None:
        del account_id, plus_expires_at

    def check_account(self, lines: str) -> dict[str, object]:
        stripped = lines.strip()
        if "\n" in stripped or stripped.count("|") < 2:
            return {
                "valid": False,
                "conflict": "invalid",
                "message": "Mỗi lần chỉ được thêm một tài khoản.",
            }
        email = stripped.split("|", 1)[0].strip()
        if email.casefold() == "alpha@example.test":
            return {
                "valid": False,
                "conflict": "email",
                "message": "Email đã tồn tại.",
            }
        return {
            "valid": True,
            "conflict": None,
            "message": "Tài khoản có thể được thêm.",
        }

    def import_accounts(self, lines: str) -> dict[str, object]:
        check = self.check_account(lines)
        if not check["valid"]:
            if check["conflict"] == "email":
                raise AccountConflictError("email")
            raise ValueError(str(check["message"]))
        return {
            "total": len(_ACCOUNT_ROWS) + 1,
            "email": lines.split("|", 1)[0].strip(),
        }


def create_visual_baseline_app() -> FastAPI:
    return create_app(service=VisualBaselineService())


app = create_visual_baseline_app()
