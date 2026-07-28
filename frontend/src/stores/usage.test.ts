import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalApiClient } from "@/api/client.ts";
import {
  applicationState,
  tokenUsage,
} from "@/test/fixtures.ts";
import { useSessionStore } from "./session.ts";
import { useUsageStore } from "./usage.ts";

describe("usage store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("caches token usage and preserves null versus empty buckets", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    const tokenUsageRequest = vi.fn().mockResolvedValue(tokenUsage());
    vi.spyOn(session, "getClient").mockReturnValue({
      tokenUsage: tokenUsageRequest,
    } as unknown as LocalApiClient);
    const store = useUsageStore();

    await store.fetchUsage();
    await store.fetchUsage();

    expect(tokenUsageRequest).toHaveBeenCalledTimes(1);
    expect(store.selectedBuckets).toEqual([
      { start_date: "2026-07-23", tokens: 2_400 },
    ]);
    store.selectedAccountId = "missing-account";
    expect(store.selectedBuckets).toBeNull();
  });

  it("keeps stale data when refresh fails", async () => {
    const session = useSessionStore();
    const client = {
      tokenUsage: vi
        .fn()
        .mockResolvedValueOnce(tokenUsage())
        .mockRejectedValueOnce(new Error("network")),
    };
    vi.spyOn(session, "getClient").mockReturnValue(
      client as unknown as LocalApiClient,
    );
    const store = useUsageStore();
    await store.fetchUsage();

    await store.fetchUsage(true);

    expect(store.data?.aggregate.totals.lifetime).toBe(820_000);
    expect(store.errorMessage).toContain("dữ liệu cũ");
  });

  it("shares one in-flight request even when a force request arrives", async () => {
    const session = useSessionStore();
    let resolveRequest: ((value: ReturnType<typeof tokenUsage>) => void) | undefined;
    const pending = new Promise<ReturnType<typeof tokenUsage>>((resolve) => {
      resolveRequest = resolve;
    });
    const tokenUsageRequest = vi.fn().mockReturnValue(pending);
    vi.spyOn(session, "getClient").mockReturnValue({
      tokenUsage: tokenUsageRequest,
    } as unknown as LocalApiClient);
    const store = useUsageStore();

    const first = store.fetchUsage();
    const forced = store.fetchUsage(true);

    expect(tokenUsageRequest).toHaveBeenCalledTimes(1);
    resolveRequest?.(tokenUsage());
    await Promise.all([first, forced]);
    expect(store.data?.generated_at).toBe("2026-07-23T09:45:00+07:00");
    expect(store.isLoading).toBe(false);
  });

  it("builds an email-sorted union of token and quota accounts", () => {
    const session = useSessionStore();
    const state = applicationState();
    state.usage_statistics.accounts = [
      {
        ...state.usage_statistics.accounts[0]!,
        account_id: "quota-only",
        email: "zulu@example.test",
      },
    ];
    session.state = state;
    const store = useUsageStore();
    const payload = tokenUsage();
    payload.accounts = [
      {
        ...payload.accounts[0]!,
        account_id: "shared",
        email: "Bravo@example.test",
      },
      {
        ...payload.accounts[0]!,
        account_id: "token-only",
        email: "alpha@example.test",
      },
      {
        ...payload.accounts[0]!,
        account_id: "quota-only",
        email: "different-source@example.test",
      },
    ];
    store.data = payload;

    expect(store.accountOptions.map(({ accountId, email }) => [accountId, email])).toEqual([
      ["token-only", "alpha@example.test"],
      ["shared", "Bravo@example.test"],
      ["quota-only", "zulu@example.test"],
    ]);
  });

  it("reports an initial load failure without inventing usage data", async () => {
    const session = useSessionStore();
    vi.spyOn(session, "getClient").mockReturnValue({
      tokenUsage: vi.fn().mockRejectedValue(new Error("network")),
    } as unknown as LocalApiClient);
    const store = useUsageStore();

    expect(store.selectedBuckets).toBeNull();
    await store.fetchUsage();

    expect(store.data).toBeNull();
    expect(store.errorMessage).toBe("Chưa thể tải dữ liệu token.");
    expect(store.isLoading).toBe(false);
  });
});
