from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class NormalizedTokenUsage:
    daily_tokens: tuple[tuple[date, int], ...] | None
    lifetime_tokens: int | None
    peak_daily_tokens: int | None
    longest_running_turn_seconds: int | None
    current_streak_days: int | None
    longest_streak_days: int | None


@dataclass(frozen=True)
class TokenUsageCacheEntry:
    snapshot: NormalizedTokenUsage | None
    last_attempt_monotonic: float
    updated_at: datetime | None
    stale: bool


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def normalize_token_usage(
    payload: object,
    *,
    today: date,
) -> NormalizedTokenUsage | None:
    if not isinstance(payload, dict):
        return None

    raw_buckets = payload.get("dailyUsageBuckets")
    if raw_buckets is not None and not isinstance(raw_buckets, list):
        return None

    daily_tokens: dict[date, int] = {}
    for bucket in raw_buckets or []:
        if not isinstance(bucket, dict):
            continue
        raw_date = bucket.get("startDate")
        tokens = _optional_nonnegative_int(bucket.get("tokens"))
        if not isinstance(raw_date, str) or tokens is None:
            continue
        try:
            bucket_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if bucket_date.isoformat() != raw_date or bucket_date > today:
            continue
        daily_tokens = {
            **daily_tokens,
            bucket_date: daily_tokens.get(bucket_date, 0) + tokens,
        }

    summary = payload.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    return NormalizedTokenUsage(
        daily_tokens=(
            tuple(sorted(daily_tokens.items()))
            if raw_buckets is not None
            else None
        ),
        lifetime_tokens=_optional_nonnegative_int(
            summary.get("lifetimeTokens")
        ),
        peak_daily_tokens=_optional_nonnegative_int(
            summary.get("peakDailyTokens")
        ),
        longest_running_turn_seconds=_optional_nonnegative_int(
            summary.get("longestRunningTurnSec")
        ),
        current_streak_days=_optional_nonnegative_int(
            summary.get("currentStreakDays")
        ),
        longest_streak_days=_optional_nonnegative_int(
            summary.get("longestStreakDays")
        ),
    )


def _month_bounds(value: date) -> tuple[date, date]:
    final_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=1), value.replace(day=final_day)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _periods(today: date) -> dict[str, dict[str, object]]:
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month_start, month_end = _month_bounds(today)
    return {
        "today": {
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
            "is_partial": True,
        },
        "current_week": {
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
            "is_partial": today < week_end,
        },
        "current_month": {
            "start_date": month_start.isoformat(),
            "end_date": month_end.isoformat(),
            "is_partial": today < month_end,
        },
    }


def _tokens_between(
    values: dict[date, int],
    start: date,
    end: date,
    today: date,
) -> int:
    effective_end = min(end, today)
    return sum(
        tokens
        for bucket_date, tokens in values.items()
        if start <= bucket_date <= effective_end
    )


def _series_ranges(today: date) -> dict[str, list[tuple[date, date]]]:
    daily_start = today - timedelta(days=29)
    daily = [
        (daily_start + timedelta(days=offset),) * 2
        for offset in range(30)
    ]

    current_week_start = today - timedelta(days=today.weekday())
    first_week_start = current_week_start - timedelta(weeks=11)
    weekly = [
        (
            first_week_start + timedelta(weeks=offset),
            first_week_start + timedelta(weeks=offset, days=6),
        )
        for offset in range(12)
    ]

    current_month_start = today.replace(day=1)
    monthly: list[tuple[date, date]] = []
    for offset in range(-11, 1):
        month_start = _shift_month(current_month_start, offset)
        _, month_end = _month_bounds(month_start)
        monthly.append((month_start, month_end))

    return {"daily": daily, "weekly": weekly, "monthly": monthly}


def _build_series(
    snapshots: Iterable[NormalizedTokenUsage],
    *,
    today: date,
) -> dict[str, list[dict[str, object]]]:
    snapshot_list = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.daily_tokens is not None
    )
    ranges = _series_ranges(today)
    series: dict[str, list[dict[str, object]]] = {}
    for granularity, periods in ranges.items():
        points: list[dict[str, object]] = []
        for start, end in periods:
            tokens = None
            if snapshot_list:
                tokens = sum(
                    _tokens_between(
                        dict(snapshot.daily_tokens),
                        start,
                        end,
                        today,
                    )
                    for snapshot in snapshot_list
                )
            points.append(
                {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "tokens": tokens,
                }
            )
        series[granularity] = points
    return series


def _account_totals(
    snapshot: NormalizedTokenUsage,
    *,
    today: date,
) -> dict[str, int | None]:
    if snapshot.daily_tokens is None:
        return {
            "today": None,
            "week": None,
            "month": None,
            "lifetime": snapshot.lifetime_tokens,
        }

    values = dict(snapshot.daily_tokens)
    week_start = today - timedelta(days=today.weekday())
    month_start, _ = _month_bounds(today)
    return {
        "today": values.get(today, 0),
        "week": _tokens_between(values, week_start, today, today),
        "month": _tokens_between(values, month_start, today, today),
        "lifetime": snapshot.lifetime_tokens,
    }


def _daily_buckets(
    snapshots: Iterable[NormalizedTokenUsage],
    *,
    today: date,
) -> list[dict[str, object]] | None:
    activity_snapshots = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.daily_tokens is not None
    )
    if not activity_snapshots:
        return None

    first_day = _shift_month(today.replace(day=1), -11)
    totals: dict[date, int] = {}
    for snapshot in activity_snapshots:
        assert snapshot.daily_tokens is not None
        for bucket_date, tokens in snapshot.daily_tokens:
            if first_day <= bucket_date <= today:
                totals = {
                    **totals,
                    bucket_date: totals.get(bucket_date, 0) + tokens,
                }

    return [
        {"start_date": bucket_date.isoformat(), "tokens": tokens}
        for bucket_date, tokens in sorted(totals.items())
    ]


def build_token_usage_statistics(
    *,
    accounts: list[dict[str, str]],
    entries: dict[str, TokenUsageCacheEntry],
    now: datetime,
) -> dict[str, object]:
    today = now.date()
    rows: list[dict[str, object]] = []
    available_snapshots: list[NormalizedTokenUsage] = []
    activity_snapshots: list[NormalizedTokenUsage] = []
    fresh_accounts = 0
    stale_accounts = 0

    for account in accounts:
        email = account["email"]
        entry = entries.get(email.casefold())
        snapshot = entry.snapshot if entry is not None else None
        if snapshot is None:
            status = "unavailable"
            totals = {
                "today": None,
                "week": None,
                "month": None,
                "lifetime": None,
            }
            peak_daily = None
            longest_running_turn_seconds = None
            current_streak_days = None
            longest_streak_days = None
            updated_at = None
            account_series = _build_series((), today=today)
            account_daily_buckets = None
        else:
            status = "stale" if entry.stale else "fresh"
            if entry.stale:
                stale_accounts += 1
            else:
                fresh_accounts += 1
            available_snapshots.append(snapshot)
            if snapshot.daily_tokens is not None:
                activity_snapshots.append(snapshot)
            totals = _account_totals(snapshot, today=today)
            peak_daily = snapshot.peak_daily_tokens
            longest_running_turn_seconds = (
                snapshot.longest_running_turn_seconds
            )
            current_streak_days = snapshot.current_streak_days
            longest_streak_days = snapshot.longest_streak_days
            updated_at = (
                entry.updated_at.isoformat(timespec="seconds")
                if entry.updated_at is not None
                else None
            )
            account_series = _build_series((snapshot,), today=today)
            account_daily_buckets = _daily_buckets(
                (snapshot,),
                today=today,
            )

        rows.append(
            {
                "account_id": account["account_id"],
                "email": email,
                "status": status,
                "updated_at": updated_at,
                "today": totals["today"],
                "week": totals["week"],
                "month": totals["month"],
                "lifetime": totals["lifetime"],
                "peak_daily": peak_daily,
                "longest_running_turn_seconds": (
                    longest_running_turn_seconds
                ),
                "current_streak_days": current_streak_days,
                "longest_streak_days": longest_streak_days,
                "daily_buckets": account_daily_buckets,
                "series": account_series,
            }
        )

    available_count = len(available_snapshots)
    aggregate_totals: dict[str, int | None] = {}
    aggregate_averages: dict[str, float | None] = {}
    sample_sizes: dict[str, int] = {}
    for metric in ("today", "week", "month", "lifetime"):
        values = [
            row[metric]
            for row in rows
            if row["status"] != "unavailable"
            and isinstance(row[metric], int)
        ]
        sample_sizes[metric] = len(values)
        aggregate_totals[metric] = sum(values) if values else None
        aggregate_averages[metric] = (
            round(sum(values) / len(values), 2) if values else None
        )

    return {
        "schema_version": 2,
        "source": "codex_account_usage",
        "generated_at": now.isoformat(timespec="seconds"),
        "coverage": {
            "total_accounts": len(accounts),
            "fresh_accounts": fresh_accounts,
            "stale_accounts": stale_accounts,
            "unavailable_accounts": len(accounts) - available_count,
        },
        "periods": _periods(today),
        "aggregate": {
            "totals": aggregate_totals,
            "averages": aggregate_averages,
            "sample_sizes": sample_sizes,
            "daily_buckets": _daily_buckets(
                activity_snapshots,
                today=today,
            ),
            "series": _build_series(activity_snapshots, today=today),
        },
        "accounts": sorted(
            rows,
            key=lambda row: str(row["email"]).casefold(),
        ),
    }
