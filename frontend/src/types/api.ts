export type TokenUsageStatus = "fresh" | "stale" | "unavailable";

export interface QuotaWindowState {
  quota_remaining: string;
  quota_cycle: string;
  quota_reset_at: string;
}

export interface AccountState {
  id: string;
  email: string;
  otp: string | null;
  otp_remaining_seconds: number | null;
  quota_remaining: string;
  quota_cycle: string;
  quota_reset_at: string;
  quota_windows: ReadonlyArray<QuotaWindowState>;
  banked_reset_count: number | null;
  banked_reset_expires_at: ReadonlyArray<string> | null;
  plus_expires_at: string | null;
  plan_type: string;
  account_state: string;
  sync_status: string;
  last_sync: string;
}

export interface AccountRecommendation {
  account_id: string;
  email: string;
  quota_remaining: string;
  quota_reset_at: string;
}

export interface RankedAccountRecommendation extends AccountRecommendation {
  rank: number;
  reason: string;
}

export interface AccountUsageStatistics {
  account_id: string;
  email: string;
  quota_remaining_percent: number | null;
  quota_used_percent: number | null;
  quota_cycle: string;
  quota_reset_at: string;
  plan_type: string;
  account_state: string;
  sync_status: string;
  last_sync: string;
  is_usable: boolean;
  needs_attention: boolean;
  quota_is_stale: boolean;
}

export interface UsageStatistics {
  schema_version: 1;
  history_available: false;
  source: "codex_rate_limits_snapshot";
  generated_at: string;
  total_accounts: number;
  quota_known_accounts: number;
  quota_unknown_accounts: number;
  stale_quota_accounts: number;
  usable_accounts: number;
  attention_accounts: number;
  low_quota_accounts: number;
  exhausted_accounts: number;
  average_remaining_percent: number | null;
  average_used_percent: number | null;
  minimum_remaining_percent: number | null;
  maximum_remaining_percent: number | null;
  median_remaining_percent: number | null;
  next_reset_at: string | null;
  plan_distribution: Array<{ plan_type: string; count: number }>;
  accounts: AccountUsageStatistics[];
}

export interface TimeSyncState {
  status: "synced" | "syncing" | "degraded";
  offset_seconds: number | null;
  last_synced_at: string | null;
  source_count: number;
}

export interface ApplicationState {
  accounts: AccountState[];
  sync_status: string;
  refresh_interval_seconds: number;
  recommendation: AccountRecommendation | null;
  recommendation_queue: RankedAccountRecommendation[];
  usage_statistics: UsageStatistics;
  time_sync: TimeSyncState;
}

export type FailoverState =
  | "disabled"
  | "observing"
  | "draining"
  | "switching"
  | "resuming"
  | "running"
  | "all_exhausted"
  | "blocked"
  | "error";

export interface FailoverStatusResponse {
  schema_version: 1;
  available: boolean;
  enabled: boolean;
  state: FailoverState;
  updated_at: string | null;
  has_error: boolean;
  tasks: {
    total: number;
    active: number;
    completed: number;
    blocked: number;
    quota_exhausted: number;
    eligible: number;
  };
  quotas: {
    total: number;
    exhausted: number;
  };
}

export interface BootstrapResponse {
  api_schema_version: number;
  build_id: string;
  csrf_token: string;
  state: ApplicationState;
}

export interface TokenUsagePeriod {
  start_date: string;
  end_date: string;
  is_partial: boolean;
}

export interface TokenUsageSeriesPoint {
  start_date: string;
  end_date: string;
  tokens: number | null;
}

export interface TokenUsageSeries {
  daily: TokenUsageSeriesPoint[];
  weekly: TokenUsageSeriesPoint[];
  monthly: TokenUsageSeriesPoint[];
}

export interface TokenUsageDailyBucket {
  start_date: string;
  tokens: number;
}

export interface TokenUsageAccount {
  account_id: string;
  email: string;
  status: TokenUsageStatus;
  updated_at: string | null;
  today: number | null;
  week: number | null;
  month: number | null;
  lifetime: number | null;
  peak_daily: number | null;
  longest_running_turn_seconds: number | null;
  current_streak_days: number | null;
  longest_streak_days: number | null;
  daily_buckets: TokenUsageDailyBucket[] | null;
  series: TokenUsageSeries;
}

export interface TokenUsageResponse {
  schema_version: 2;
  source: "codex_account_usage";
  generated_at: string;
  coverage: {
    total_accounts: number;
    fresh_accounts: number;
    stale_accounts: number;
    unavailable_accounts: number;
  };
  periods: {
    today: TokenUsagePeriod;
    current_week: TokenUsagePeriod;
    current_month: TokenUsagePeriod;
  };
  aggregate: {
    totals: {
      today: number | null;
      week: number | null;
      month: number | null;
      lifetime: number | null;
    };
    averages: {
      today: number | null;
      week: number | null;
      month: number | null;
      lifetime: number | null;
    };
    sample_sizes: {
      today: number;
      week: number;
      month: number;
      lifetime: number;
    };
    daily_buckets: TokenUsageDailyBucket[] | null;
    series: TokenUsageSeries;
  };
  accounts: TokenUsageAccount[];
}

export interface AccountCheckResponse {
  valid: boolean;
  conflict: "email" | "secret" | "invalid" | null;
  message: string;
}

export interface AddAccountResponse {
  total: number;
  email: string;
}

export interface ActionResponse {
  accepted: boolean;
}

export interface DeleteResponse {
  deleted: boolean;
}

export interface SensitiveValueResponse {
  value: string;
}

export interface PasswordUpdateResponse {
  updated: boolean;
}

export interface SecretUpdateResponse {
  updated: boolean;
}

export interface PlusExpirationUpdateResponse {
  updated: boolean;
}
