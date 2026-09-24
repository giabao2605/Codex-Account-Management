import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalApiClient } from "@/api/client.ts";
import { applicationState } from "@/test/fixtures.ts";
import { useAccountsStore } from "./accounts.ts";
import { useSessionStore } from "./session.ts";

describe("accounts store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("filters account state without mutating the backend snapshot", () => {
    const session = useSessionStore();
    session.state = applicationState();
    const original = structuredClone(session.state);
    const store = useAccountsStore();

    store.filter = "attention";

    expect(store.filteredAccounts.map((account) => account.email)).toEqual([
      "beta@example.test",
    ]);
    expect(session.state).toEqual(original);
  });

  it("keeps sensitive values transient and clears busy state", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    const sensitiveValue = vi.fn().mockResolvedValue({ value: "test-value" });
    vi.spyOn(session, "getClient").mockReturnValue({
      sensitiveValue,
    } as unknown as LocalApiClient);
    const store = useAccountsStore();

    const value = await store.sensitiveValue(
      "1111111111111111",
      "password",
    );

    expect(value).toBe("test-value");
    expect(store.isBusy("1111111111111111", "password")).toBe(false);
    expect(JSON.stringify(store.$state)).not.toContain("test-value");
  });

  it("routes account, add, and cleanup actions through the typed client", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    const client = {
      refresh: vi.fn().mockResolvedValue({ accepted: true }),
      login: vi.fn().mockResolvedValue({ accepted: true }),
      unlink: vi.fn().mockResolvedValue({ accepted: true }),
      deleteAccount: vi.fn().mockResolvedValue({ deleted: true }),
      updatePassword: vi.fn().mockResolvedValue({ updated: true }),
      checkAccount: vi.fn().mockResolvedValue({
        valid: true,
        conflict: null,
        message: "Tài khoản có thể được thêm.",
      }),
      addAccount: vi.fn().mockResolvedValue({
        total: 1,
        email: "new@example.test",
      }),
    };
    vi.spyOn(session, "getClient").mockReturnValue(
      client as unknown as LocalApiClient,
    );
    vi.spyOn(session, "pollState").mockResolvedValue();
    const store = useAccountsStore();

    expect(await store.refresh(null)).toBe(true);
    await store.lifecycle("1111111111111111", "login");
    await store.lifecycle("1111111111111111", "unlink");
    vi.mocked(session.pollState).mockRejectedValue(new Error("offline"));
    await store.updatePassword("1111111111111111", "new-password");
    expect(session.pollState).toHaveBeenCalledTimes(3);
    vi.mocked(session.pollState).mockResolvedValue();
    await store.deleteAccount("1111111111111111");
    expect((await store.checkAccount("line")).valid).toBe(true);
    expect((await store.addAccount("line")).email).toBe("new@example.test");
    expect("archiveOrphans" in store).toBe(false);
    expect(store.accountById("1111111111111111")?.email).toContain("alpha");
    expect(client.login).toHaveBeenCalledOnce();
    expect(client.unlink).toHaveBeenCalledOnce();
    expect(client.updatePassword).toHaveBeenCalledWith(
      "1111111111111111",
      "new-password",
    );
  });

  it("updates the Plus expiration through the typed client and refreshes state", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    const updatePlusExpiration = vi.fn().mockResolvedValue({ updated: true });
    vi.spyOn(session, "getClient").mockReturnValue({
      updatePlusExpiration,
    } as unknown as LocalApiClient);
    vi.spyOn(session, "pollState").mockResolvedValue();
    const store = useAccountsStore();

    await store.updatePlusExpiration("1111111111111111", "2026-10-11");

    expect(updatePlusExpiration).toHaveBeenCalledWith(
      "1111111111111111",
      "2026-10-11",
    );
    expect(session.pollState).toHaveBeenCalledOnce();
    expect(store.isBusy("1111111111111111", "plusExpiration")).toBe(false);
  });

  it("refreshes the account OTP after updating its secret", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    session.connectionStatus = "ready";
    const updateSecret = vi.fn().mockResolvedValue({ updated: true });
    vi.spyOn(session, "getClient").mockReturnValue({
      updateSecret,
    } as unknown as LocalApiClient);
    vi.spyOn(session, "pollState").mockResolvedValue();

    await useAccountsStore().updateSecret("1111111111111111", "KRUGS4ZANFZSAYJA");

    expect(updateSecret).toHaveBeenCalledWith("1111111111111111", "KRUGS4ZANFZSAYJA");
    expect(session.pollState).toHaveBeenCalledWith(true);
  });

  it("hides a stale OTP when the post-save state refresh fails", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    session.connectionStatus = "offline";
    vi.spyOn(session, "getClient").mockReturnValue({
      updateSecret: vi.fn().mockResolvedValue({ updated: true }),
    } as unknown as LocalApiClient);
    vi.spyOn(session, "pollState").mockResolvedValue();

    await useAccountsStore().updateSecret("1111111111111111", "KRUGS4ZANFZSAYJA");

    expect(session.state?.accounts[0]?.otp).toBeNull();
    expect(session.state?.accounts[0]?.otp_remaining_seconds).toBeNull();
  });

  it("gets a fresh OTP after a secret save races with an existing poll", async () => {
    const session = useSessionStore();
    const oldState = applicationState();
    const newState = applicationState();
    newState.accounts[0] = { ...newState.accounts[0]!, otp: "654321" };
    let finishOldPoll!: (value: Response) => void;
    const oldPollResponse = new Promise<Response>((resolve) => {
      finishOldPoll = resolve;
    });
    let stateRequests = 0;
    const jsonResponse = (value: unknown) => new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi.fn((path: string) => {
      if (path === "/api/bootstrap") return Promise.resolve(jsonResponse({
        api_schema_version: 14,
        build_id: "test-build",
        csrf_token: "csrf-token",
        state: oldState,
      }));
      if (path.endsWith("/secret")) {
        return Promise.resolve(jsonResponse({ updated: true }));
      }
      stateRequests += 1;
      return stateRequests === 1
        ? oldPollResponse
        : Promise.resolve(jsonResponse(newState));
    });
    vi.stubGlobal("fetch", fetchMock);
    await session.bootstrap("access-token");

    const oldPoll = session.pollState();
    const save = useAccountsStore().updateSecret("1111111111111111", "KRUGS4ZANFZSAYJA");
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/secret"))).toBe(true);
    });
    finishOldPoll(jsonResponse(oldState));
    await Promise.all([oldPoll, save]);

    expect(stateRequests).toBe(2);
    expect(session.state?.accounts[0]?.otp).toBe("654321");
  });
});
