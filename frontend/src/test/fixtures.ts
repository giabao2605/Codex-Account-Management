import type {
  ApplicationState,
  TokenUsageResponse,
} from "@/types/api.ts";

export function applicationState(): ApplicationState {
  return {
    accounts: [
      {
        id: "1111111111111111",
        email: "alpha@example.test",
        otp: "123456",
        otp_remaining_seconds: 20,
        quota_remaining: "82%",
        quota_cycle: "5 giờ",
        quota_reset_at: "23/07 14:00",
        banked_reset_count: 2,
        banked_reset_expires_at: ["30/07 09:00", "Không hết hạn"],
        quota_windows: [
          {
            quota_remaining: "82%",
            quota_cycle: "5 giờ",
            quota_reset_at: "23/07 14:00",
          },
          {
            quota_remaining: "64%",
            quota_cycle: "Weekly",
            quota_reset_at: "28/07 09:00",
          },
        ],
        plan_type: "Plus",
        account_state: "Hoạt động bình thường",
        sync_status: "Đã đồng bộ",
        last_sync: "23/07 09:45",
      },
      {
        id: "2222222222222222",
        email: "beta@example.test",
        otp: null,
        otp_remaining_seconds: null,
        quota_remaining: "Chưa rõ",
        quota_cycle: "Chưa rõ",
        quota_reset_at: "Chưa rõ",
        banked_reset_count: null,
        banked_reset_expires_at: null,
        quota_windows: [],
        plan_type: "Chưa rõ",
        account_state: "Chưa xác định",
        sync_status: "Chưa liên kết",
        last_sync: "Chưa đồng bộ",
      },
    ],
    sync_status: "1 thành công, 0 cần đăng nhập, 1 chưa liên kết, 0 lỗi tạm thời",
    refresh_interval_seconds: 60,
    recommendation: {
      account_id: "1111111111111111",
      email: "alpha@example.test",
      quota_remaining: "82%",
      quota_reset_at: "23/07 14:00",
    },
    recommendation_queue: [
      {
        account_id: "1111111111111111",
        email: "alpha@example.test",
        quota_remaining: "82%",
        quota_reset_at: "23/07 14:00",
        rank: 1,
        reason: "Hoạt động bình thường · còn 82% quota · reset 23/07 14:00",
      },
    ],
    usage_statistics: {
      schema_version: 1,
      history_available: false,
      source: "codex_rate_limits_snapshot",
      generated_at: "2026-07-23T09:45:00+07:00",
      total_accounts: 2,
      quota_known_accounts: 1,
      quota_unknown_accounts: 1,
      stale_quota_accounts: 0,
      usable_accounts: 1,
      attention_accounts: 1,
      low_quota_accounts: 0,
      exhausted_accounts: 0,
      average_remaining_percent: 82,
      average_used_percent: 18,
      minimum_remaining_percent: 82,
      maximum_remaining_percent: 82,
      median_remaining_percent: 82,
      next_reset_at: "23/07 14:00",
      plan_distribution: [{ plan_type: "Plus", count: 1 }],
      accounts: [
        {
          account_id: "1111111111111111",
          email: "alpha@example.test",
          quota_remaining_percent: 82,
          quota_used_percent: 18,
          quota_cycle: "5 giờ",
          quota_reset_at: "23/07 14:00",
          plan_type: "Plus",
          account_state: "Hoạt động bình thường",
          sync_status: "Đã đồng bộ",
          last_sync: "23/07 09:45",
          is_usable: true,
          needs_attention: false,
          quota_is_stale: false,
        },
      ],
    },
    time_sync: {
      status: "synced",
      offset_seconds: 0.12,
      last_synced_at: "2026-07-23T09:45:00+07:00",
      source_count: 3,
    },
  };
}

export function tokenUsage(): TokenUsageResponse {
  const series = { daily: [], weekly: [], monthly: [] };
  return {
    schema_version: 2,
    source: "codex_account_usage",
    generated_at: "2026-07-23T09:45:00+07:00",
    coverage: {
      total_accounts: 2,
      fresh_accounts: 1,
      stale_accounts: 0,
      unavailable_accounts: 1,
    },
    periods: {
      today: {
        start_date: "2026-07-23",
        end_date: "2026-07-23",
        is_partial: true,
      },
      current_week: {
        start_date: "2026-07-20",
        end_date: "2026-07-26",
        is_partial: true,
      },
      current_month: {
        start_date: "2026-07-01",
        end_date: "2026-07-31",
        is_partial: true,
      },
    },
    aggregate: {
      totals: {
        today: 2_400,
        week: 12_600,
        month: 48_000,
        lifetime: 820_000,
      },
      averages: {
        today: 2_400,
        week: 12_600,
        month: 48_000,
        lifetime: 820_000,
      },
      sample_sizes: { today: 1, week: 1, month: 1, lifetime: 1 },
      daily_buckets: [{ start_date: "2026-07-23", tokens: 2_400 }],
      series,
    },
    accounts: [
      {
        account_id: "1111111111111111",
        email: "alpha@example.test",
        status: "fresh",
        updated_at: "2026-07-23T09:45:00+07:00",
        today: 2_400,
        week: 12_600,
        month: 48_000,
        lifetime: 820_000,
        peak_daily: 18_500,
        longest_running_turn_seconds: 312,
        current_streak_days: 6,
        longest_streak_days: 18,
        daily_buckets: [{ start_date: "2026-07-23", tokens: 2_400 }],
        series,
      },
    ],
  };
}
