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

export type AccountPlan = "plus" | "team" | "free" | "other" | "unknown";
export type AccountSort = "status" | "email";
export type AccountStatus = "ready" | "low" | "empty" | "login" | "unlinked" | "error" | "unknown";

export const accountPlans: ReadonlyArray<{ value: AccountPlan; label: string }> = [
  { value: "plus", label: "Plus" },
  { value: "team", label: "Team / Business" },
  { value: "free", label: "Free" },
  { value: "other", label: "Gói khác" },
  { value: "unknown", label: "Chưa rõ gói" },
];

export const accountStatuses: Record<AccountStatus, {
  label: string; tone: "normal" | "warning" | "error"; rank: number;
}> = {
  ready: { label: "Có thể dùng", tone: "normal", rank: 0 },
  low: { label: "Quota thấp", tone: "warning", rank: 1 },
  empty: { label: "Hết quota", tone: "error", rank: 2 },
  login: { label: "Cần đăng nhập", tone: "warning", rank: 3 },
  unlinked: { label: "Chưa liên kết", tone: "warning", rank: 4 },
  error: { label: "Cần xử lý", tone: "error", rank: 5 },
  unknown: { label: "Chưa rõ trạng thái", tone: "warning", rank: 6 },
};

export function accountPlan(account: AccountState): AccountPlan {
  const plan = account.plan_type.trim().toLocaleLowerCase("en");
  if (plan.includes("plus")) return "plus";
  if (plan.includes("team") || plan.includes("business")) return "team";
  if (plan.includes("free")) return "free";
  return ["", "—", "-", "unknown", "chưa rõ", "chưa xác định"].includes(plan)
    ? "unknown" : "other";
}

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
    "không thể",
  ].some((term) => status.includes(term));
}

export function statusTone(
  account: AccountState,
): "normal" | "warning" | "error" {
  return accountStatuses[accountStatus(account)].tone;
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
  const quota = accountQuotaPercent(account);
  const status = accountStatus(account);
  const quotaKnown = quota !== null;
  if (filter === "usable") {
    return status === "ready" || status === "low";
  }
  if (filter === "attention") {
    return needsAttention(account);
  }
  if (filter === "quota-available") {
    return status === "ready" || status === "low";
  }
  if (filter === "quota-low") {
    return status === "low";
  }
  if (filter === "quota-empty") {
    return status === "empty";
  }
  if (filter === "quota-unknown") {
    return !quotaKnown;
  }
  return true;
}

export function accountQuotaPercent(account: AccountState): number | null {
  const values = account.quota_windows.length
    ? account.quota_windows.map((window) => window.quota_remaining)
    : [account.quota_remaining];
  const percentages = values.map(parseQuotaPercent);
  if (percentages.includes(0)) return 0;
  if (percentages.some((value) => value === null)) return null;
  return Math.min(...percentages as number[]);
}

export function accountStatus(account: AccountState): AccountStatus {
  const status = normalizedStatus(account);
  if (["lỗi", "khóa", "banned", "sai tài khoản", "không thể"]
    .some((term) => status.includes(term))) return "error";
  if (status.includes("chưa liên kết")) return "unlinked";
  if (["đăng nhập", "đăng xuất"].some((term) => status.includes(term))) return "login";
  if (account.account_state !== "Hoạt động bình thường" || needsAttention(account)) {
    return "unknown";
  }
  const quota = accountQuotaPercent(account);
  if (quota === null) return "unknown";
  if (quota === 0) return "empty";
  return quota <= 20 ? "low" : "ready";
}

export function compareAccounts(
  a: AccountState, b: AccountState, sort: AccountSort,
): number {
  const emailOrder = a.email.localeCompare(b.email, "vi", { sensitivity: "base" })
    || a.id.localeCompare(b.id);
  if (sort === "email") return emailOrder;
  return accountStatuses[accountStatus(a)].rank - accountStatuses[accountStatus(b)].rank
    || (accountQuotaPercent(b) ?? -1) - (accountQuotaPercent(a) ?? -1)
    || emailOrder;
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
