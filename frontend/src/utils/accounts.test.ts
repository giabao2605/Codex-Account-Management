import { describe, expect, it } from "vitest";

import type { AccountState, ApplicationState } from "@/types/api.ts";
import {
  accountMatchesFilter,
  needsAttention,
  parseQuotaPercent,
  syncMetrics,
} from "./accounts.ts";

function account(overrides: Partial<AccountState> = {}): AccountState {
  return {
    id: "1111111111111111",
    email: "alpha@example.test",
    otp: "123456",
    otp_remaining_seconds: 20,
    quota_remaining: "82%",
    quota_cycle: "5 giờ",
    quota_reset_at: "23/07 14:00",
    quota_windows: [],
    plan_type: "Plus",
    account_state: "Hoạt động bình thường",
    sync_status: "Đã đồng bộ",
    last_sync: "23/07 09:45",
    ...overrides,
  };
}

describe("account parity utilities", () => {
  it("parses and clamps quota percentages", () => {
    expect(parseQuotaPercent("82,5%")).toBe(82.5);
    expect(parseQuotaPercent("-1%")).toBe(0);
    expect(parseQuotaPercent("120%")).toBe(100);
    expect(parseQuotaPercent("Chưa rõ")).toBeNull();
  });

  it("matches every legacy account filter", () => {
    const healthy = account();
    const attention = account({
      account_state: "Chưa xác định",
      quota_remaining: "Chưa rõ",
    });
    const low = account({ quota_remaining: "12%" });
    const empty = account({ quota_remaining: "0%" });

    expect(accountMatchesFilter(healthy, "usable")).toBe(true);
    expect(accountMatchesFilter(attention, "attention")).toBe(true);
    expect(accountMatchesFilter(healthy, "quota-available")).toBe(true);
    expect(accountMatchesFilter(low, "quota-low")).toBe(true);
    expect(accountMatchesFilter(empty, "quota-empty")).toBe(true);
    expect(accountMatchesFilter(attention, "quota-unknown")).toBe(true);
    expect(needsAttention(healthy)).toBe(false);
  });

  it("derives sync metrics when the summary is not parseable", () => {
    const state = {
      accounts: [
        account(),
        account({
          id: "2222222222222222",
          sync_status: "Cần đăng nhập",
        }),
        account({
          id: "3333333333333333",
          sync_status: "Chưa liên kết",
        }),
      ],
      sync_status: "Đang đồng bộ",
    } as ApplicationState;

    expect(syncMetrics(state)).toEqual({
      success: 1,
      login: 1,
      unlinked: 1,
      error: 0,
    });
  });
});
