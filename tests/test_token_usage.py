from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.token_usage import (
    TokenUsageCacheEntry,
    build_token_usage_statistics,
    normalize_token_usage,
)


class TokenUsageNormalizationTests(unittest.TestCase):
    def test_normalize_merges_duplicates_and_rejects_invalid_buckets(self) -> None:
        snapshot = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": 1_234,
                    "peakDailyTokens": 600,
                },
                "dailyUsageBuckets": [
                    {"startDate": "2026-07-22", "tokens": 100},
                    {"startDate": "2026-07-22", "tokens": 25},
                    {"startDate": "2026-07-24", "tokens": 999},
                    {"startDate": "not-a-date", "tokens": 100},
                    {"startDate": "2026-07-21", "tokens": -1},
                    {"startDate": "2026-07-20", "tokens": True},
                ],
            },
            today=date(2026, 7, 23),
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(dict(snapshot.daily_tokens), {date(2026, 7, 22): 125})
        self.assertEqual(snapshot.lifetime_tokens, 1_234)
        self.assertEqual(snapshot.peak_daily_tokens, 600)

    def test_null_daily_buckets_preserve_all_summary_fields(self) -> None:
        snapshot = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": 500,
                    "peakDailyTokens": 125,
                    "longestRunningTurnSec": 90,
                    "currentStreakDays": 3,
                    "longestStreakDays": 8,
                },
                "dailyUsageBuckets": None,
            },
            today=date(2026, 7, 23),
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertIsNone(snapshot.daily_tokens)
        self.assertEqual(snapshot.lifetime_tokens, 500)
        self.assertEqual(snapshot.peak_daily_tokens, 125)
        self.assertEqual(snapshot.longest_running_turn_seconds, 90)
        self.assertEqual(snapshot.current_streak_days, 3)
        self.assertEqual(snapshot.longest_streak_days, 8)


class TokenUsageAggregationTests(unittest.TestCase):
    @staticmethod
    def entry(
        buckets: list[tuple[str, int]],
        *,
        lifetime: int | None,
        peak: int | None,
        stale: bool = False,
    ) -> TokenUsageCacheEntry:
        snapshot = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": lifetime,
                    "peakDailyTokens": peak,
                },
                "dailyUsageBuckets": [
                    {"startDate": start_date, "tokens": tokens}
                    for start_date, tokens in buckets
                ],
            },
            today=date(2026, 7, 23),
        )
        assert snapshot is not None
        return TokenUsageCacheEntry(
            snapshot=snapshot,
            last_attempt_monotonic=10.0,
            updated_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
            stale=stale,
        )

    def test_calendar_periods_cover_leap_month_and_monday_week(self) -> None:
        now = datetime(2024, 2, 29, 12, 0, tzinfo=timezone.utc)
        snapshot = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": 500,
                    "peakDailyTokens": 200,
                },
                "dailyUsageBuckets": [
                    {"startDate": "2024-02-29", "tokens": 10},
                    {"startDate": "2024-02-26", "tokens": 5},
                    {"startDate": "2024-02-01", "tokens": 20},
                    {"startDate": "2024-01-31", "tokens": 99},
                ],
            },
            today=now.date(),
        )
        assert snapshot is not None

        statistics = build_token_usage_statistics(
            accounts=[{"account_id": "a" * 16, "email": "one@example.com"}],
            entries={
                "one@example.com": TokenUsageCacheEntry(
                    snapshot=snapshot,
                    last_attempt_monotonic=10.0,
                    updated_at=now,
                    stale=False,
                )
            },
            now=now,
        )

        self.assertEqual(
            statistics["periods"]["current_week"],
            {
                "start_date": "2024-02-26",
                "end_date": "2024-03-03",
                "is_partial": True,
            },
        )
        self.assertEqual(
            statistics["periods"]["current_month"],
            {
                "start_date": "2024-02-01",
                "end_date": "2024-02-29",
                "is_partial": False,
            },
        )
        self.assertEqual(statistics["aggregate"]["totals"]["today"], 10)
        self.assertEqual(statistics["aggregate"]["totals"]["week"], 15)
        self.assertEqual(statistics["aggregate"]["totals"]["month"], 35)
        self.assertEqual(statistics["aggregate"]["totals"]["lifetime"], 500)

    def test_week_can_cross_year_boundary(self) -> None:
        now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        snapshot = normalize_token_usage(
            {
                "summary": {},
                "dailyUsageBuckets": [
                    {"startDate": "2025-12-29", "tokens": 7},
                    {"startDate": "2026-01-01", "tokens": 11},
                ],
            },
            today=now.date(),
        )
        assert snapshot is not None

        statistics = build_token_usage_statistics(
            accounts=[{"account_id": "b" * 16, "email": "year@example.com"}],
            entries={
                "year@example.com": TokenUsageCacheEntry(
                    snapshot=snapshot,
                    last_attempt_monotonic=10.0,
                    updated_at=now,
                    stale=False,
                )
            },
            now=now,
        )

        self.assertEqual(
            statistics["periods"]["current_week"]["start_date"],
            "2025-12-29",
        )
        self.assertEqual(
            statistics["periods"]["current_week"]["end_date"],
            "2026-01-04",
        )
        self.assertEqual(statistics["aggregate"]["totals"]["week"], 18)

    def test_month_end_uses_actual_calendar_length(self) -> None:
        cases = (
            (datetime(2023, 2, 12, tzinfo=timezone.utc), "2023-02-28"),
            (datetime(2024, 2, 12, tzinfo=timezone.utc), "2024-02-29"),
            (datetime(2026, 4, 12, tzinfo=timezone.utc), "2026-04-30"),
            (datetime(2026, 7, 12, tzinfo=timezone.utc), "2026-07-31"),
        )
        for now, expected_end in cases:
            with self.subTest(now=now):
                statistics = build_token_usage_statistics(
                    accounts=[],
                    entries={},
                    now=now,
                )
                self.assertEqual(
                    statistics["periods"]["current_month"]["end_date"],
                    expected_end,
                )
                self.assertEqual(
                    statistics["aggregate"]["series"]["monthly"][-1][
                        "end_date"
                    ],
                    expected_end,
                )

    def test_average_includes_valid_zero_and_discloses_missing_accounts(self) -> None:
        now = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
        entries = {
            "active@example.com": self.entry(
                [("2026-07-23", 10)],
                lifetime=100,
                peak=10,
            ),
            "zero@example.com": self.entry(
                [],
                lifetime=0,
                peak=0,
                stale=True,
            ),
        }

        statistics = build_token_usage_statistics(
            accounts=[
                {"account_id": "a" * 16, "email": "active@example.com"},
                {"account_id": "b" * 16, "email": "zero@example.com"},
                {"account_id": "c" * 16, "email": "missing@example.com"},
            ],
            entries=entries,
            now=now,
        )

        self.assertEqual(
            statistics["coverage"],
            {
                "total_accounts": 3,
                "fresh_accounts": 1,
                "stale_accounts": 1,
                "unavailable_accounts": 1,
            },
        )
        self.assertEqual(statistics["aggregate"]["totals"]["today"], 10)
        self.assertEqual(statistics["aggregate"]["averages"]["today"], 5.0)
        self.assertEqual(statistics["aggregate"]["sample_sizes"]["today"], 2)
        statuses = {row["email"]: row["status"] for row in statistics["accounts"]}
        self.assertEqual(statuses["active@example.com"], "fresh")
        self.assertEqual(statuses["zero@example.com"], "stale")
        self.assertEqual(statuses["missing@example.com"], "unavailable")

    def test_daily_buckets_distinguish_empty_from_unavailable_and_aggregate(self) -> None:
        now = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
        empty = self.entry([], lifetime=0, peak=0)
        active = self.entry(
            [("2026-07-22", 10), ("2026-07-23", 20)],
            lifetime=30,
            peak=20,
        )
        unavailable_activity = normalize_token_usage(
            {
                "summary": {
                    "lifetimeTokens": 50,
                    "peakDailyTokens": 25,
                    "longestRunningTurnSec": 60,
                    "currentStreakDays": 2,
                    "longestStreakDays": 4,
                },
                "dailyUsageBuckets": None,
            },
            today=now.date(),
        )
        assert unavailable_activity is not None

        statistics = build_token_usage_statistics(
            accounts=[
                {"account_id": "a" * 16, "email": "empty@example.com"},
                {"account_id": "b" * 16, "email": "active@example.com"},
                {"account_id": "c" * 16, "email": "summary@example.com"},
            ],
            entries={
                "empty@example.com": empty,
                "active@example.com": active,
                "summary@example.com": TokenUsageCacheEntry(
                    snapshot=unavailable_activity,
                    last_attempt_monotonic=10.0,
                    updated_at=now,
                    stale=False,
                ),
            },
            now=now,
        )

        rows = {row["email"]: row for row in statistics["accounts"]}
        self.assertEqual(rows["empty@example.com"]["daily_buckets"], [])
        self.assertIsNone(rows["summary@example.com"]["daily_buckets"])
        self.assertEqual(
            statistics["aggregate"]["daily_buckets"],
            [
                {"start_date": "2026-07-22", "tokens": 10},
                {"start_date": "2026-07-23", "tokens": 20},
            ],
        )
        self.assertEqual(
            rows["summary@example.com"]["longest_running_turn_seconds"],
            60,
        )
        self.assertEqual(rows["summary@example.com"]["current_streak_days"], 2)
        self.assertEqual(rows["summary@example.com"]["longest_streak_days"], 4)

    def test_no_available_account_returns_null_totals_and_averages(self) -> None:
        statistics = build_token_usage_statistics(
            accounts=[{"account_id": "a" * 16, "email": "missing@example.com"}],
            entries={},
            now=datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
        )

        self.assertIsNone(statistics["aggregate"]["totals"]["today"])
        self.assertIsNone(statistics["aggregate"]["averages"]["today"])
        self.assertEqual(statistics["aggregate"]["sample_sizes"]["today"], 0)
        self.assertEqual(len(statistics["aggregate"]["series"]["daily"]), 30)
        self.assertEqual(len(statistics["aggregate"]["series"]["weekly"]), 12)
        self.assertEqual(len(statistics["aggregate"]["series"]["monthly"]), 12)


if __name__ == "__main__":
    unittest.main()
