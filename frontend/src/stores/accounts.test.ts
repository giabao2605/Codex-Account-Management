import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalApiClient } from "@/api/client.ts";
import { applicationState } from "@/test/fixtures.ts";
import { useAccountsStore } from "./accounts.ts";
import { useSessionStore } from "./session.ts";

describe("accounts store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
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
});
