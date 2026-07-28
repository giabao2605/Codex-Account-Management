import type {
  AccountState,
  ApplicationState,
} from "@/types/api.ts";

export type AccountFilter =
  | "all"
  | "usable"
  | "attention"
  | "quota-available"
  | "quota-low"
  | "quota-empty"
  | "quota-unknown";

export interface SyncMetrics {
  success: number;
  login: number;
  unlinked: number;
  error: number;
}

export function normalizedStatus(account: AccountState): string {
  return `${account.account_state} ${account.sync_status}`
    .toLocaleLowerCase("vi");
}

export function needsAttention(account: AccountState): boolean {
  const status = normalizedStatus(account);
  return [
    "lỗi",
    "khóa",
    "banned",
    "chưa",
    "đăng nhập",
    "đăng xuất",
    "sai tài khoản",
  ].some((term) => status.includes(term));
}

export function statusTone(
  account: AccountState,
): "normal" | "warning" | "error" {
  const status = normalizedStatus(account);
  if (
    ["lỗi", "khóa", "banned", "sai tài khoản"].some(
      (term) => status.includes(term),
    )
  ) {
    return "error";
  }
  return needsAttention(account) ? "warning" : "normal";
}

export function parseQuotaPercent(value: string): number | null {
  const match = (value ?? "").match(/-?\d+(?:[.,]\d+)?/);
  if (!match) {
    return null;
  }
  const parsed = Number(match[0].replace(",", "."));
  return Math.max(0, Math.min(100, parsed));
}

export function accountMatchesFilter(
  account: AccountState,
  filter: AccountFilter,
): boolean {
  const quota = parseQuotaPercent(account.quota_remaining);
  const quotaKnown = quota !== null;
  if (filter === "usable") {
    return !needsAttention(account) && quotaKnown && quota > 0;
  }
  if (filter === "attention") {
    return needsAttention(account);
  }
  if (filter === "quota-available") {
    return quotaKnown && quota > 0;
  }
  if (filter === "quota-low") {
    return quotaKnown && quota > 0 && quota <= 20;
  }
  if (filter === "quota-empty") {
    return quotaKnown && quota === 0;
  }
  if (filter === "quota-unknown") {
    return !quotaKnown;
  }
  return true;
}

export function syncMetrics(state: ApplicationState): SyncMetrics {
  const summary = state.sync_status.match(
    /(\d+)\s+thành công,\s*(\d+)\s+cần đăng nhập,\s*(\d+)\s+chưa liên kết,\s*(\d+)\s+lỗi tạm thời/i,
  );
  if (summary) {
    const metrics = {
      success: Number(summary[1]),
      login: Number(summary[2]),
      unlinked: Number(summary[3]),
      error: Number(summary[4]),
    };
    const total = Object.values(metrics).reduce(
      (sum, count) => sum + count,
      0,
    );
    if (total === state.accounts.length) {
      return metrics;
    }
  }

  return state.accounts.reduce<SyncMetrics>(
    (metrics, account) => {
      const status = normalizedStatus(account);
      if (status.includes("chưa liên kết")) {
        return { ...metrics, unlinked: metrics.unlinked + 1 };
      }
      if (status.includes("đăng nhập") || status.includes("đăng xuất")) {
        return { ...metrics, login: metrics.login + 1 };
      }
      if (
        ["lỗi", "khóa", "banned", "sai tài khoản", "không thể"].some(
          (term) => status.includes(term),
        )
        || needsAttention(account)
      ) {
        return { ...metrics, error: metrics.error + 1 };
      }
      return { ...metrics, success: metrics.success + 1 };
    },
    { success: 0, login: 0, unlinked: 0, error: 0 },
  );
}
