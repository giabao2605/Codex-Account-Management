import { describe, expect, it } from "vitest";

import type { AccountState, ApplicationState } from "@/types/api.ts";
import {
  accountMatchesFilter,
  accountPlan,
  accountStatus,
  compareAccounts,
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
    banked_reset_count: null,
    banked_reset_expires_at: null,
    plus_expires_at: null,
    plan_type: "Plus",
    account_state: "Hoạt động bình thường",
    sync_status: "Đã đồng bộ",
    last_sync: "23/07 09:45",
    ...overrides,
  };
}

describe("account parity utilities", () => {
  it("groups plan aliases without guessing unknown or other plans", () => {
    expect(["PLUS", "Team workspace", "Business Standard", "Free plan", "Pro", "—"]
      .map((plan_type) => accountPlan(account({ plan_type }))))
      .toEqual(["plus", "team", "team", "free", "other", "unknown"]);
  });

  it("uses all quota windows and puts login or errors ahead of cached quota", () => {
    const windows = [
      { quota_remaining: "0%", quota_cycle: "5 giờ", quota_reset_at: "—" },
      { quota_remaining: "82%", quota_cycle: "Weekly", quota_reset_at: "—" },
    ];
    const exhausted = account({ quota_windows: windows });
    const login = account({ sync_status: "Cần đăng nhập" });
    expect(accountStatus(exhausted)).toBe("empty");
    expect(accountMatchesFilter(exhausted, "usable")).toBe(false);
    expect(accountMatchesFilter(exhausted, "quota-empty")).toBe(true);
    expect(accountStatus(login)).toBe("login");
    expect(accountMatchesFilter(login, "quota-available")).toBe(false);
    expect(accountStatus(account({ sync_status: "Lỗi tạm thời" }))).toBe("error");
    expect(accountStatus(account({ sync_status: "Chưa liên kết" }))).toBe("unlinked");
    expect(accountStatus(account({ quota_remaining: "12%" }))).toBe("low");
    expect(accountStatus(account({ quota_remaining: "—" }))).toBe("unknown");
    expect(accountStatus(account({ account_state: "Chưa xác định" }))).toBe("unknown");
    expect(accountStatus(account({ quota_windows: [
      { ...windows[0]!, quota_remaining: "—" }, windows[1]!,
    ] }))).toBe("unknown");
  });

  it("orders usable accounts by quota with stable email ties without mutating input", () => {
    const rows = [
      account({ id: "login", sync_status: "Cần đăng nhập" }),
      account({ id: "low", quota_remaining: "12%" }),
      account({ id: "ready", quota_remaining: "90%" }),
      account({ id: "empty", quota_remaining: "0%" }),
    ];
    expect([...rows].sort((a, b) => compareAccounts(a, b, "status"))
      .map((row) => row.id)).toEqual(["ready", "low", "empty", "login"]);
    expect(rows[0]!.id).toBe("login");
    expect(compareAccounts(account({ email: "a@example.test" }),
      account({ email: "z@example.test" }), "email")).toBeLessThan(0);
  });

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
