import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "./session.ts";
import { applicationState } from "@/test/fixtures.ts";

function bootstrapResponse(apiSchemaVersion = 11): Response {
  return new Response(
    JSON.stringify({
      api_schema_version: apiSchemaVersion,
      build_id: "production-build",
      csrf_token: "csrf-token",
      state: {
        accounts: [
          {
            id: "account-1",
            email: "production@example.test",
            account_state: "Hoạt động bình thường",
            sync_status: "Đã đồng bộ",
          },
        ],
        refresh_interval_seconds: 60,
        last_updated: null,
      },
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

describe("session store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts schema 11 and keeps CSRF in store memory", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(bootstrapResponse()));
    const store = useSessionStore();

    await store.bootstrap("access-token");

    expect(store.connectionStatus).toBe("ready");
    expect(store.accountCount).toBe(1);
    expect(store.csrfToken).toBe("csrf-token");
    expect(store.buildId).toBe("production-build");
  });

  it("fails closed on a schema mismatch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(bootstrapResponse(999)),
    );
    const store = useSessionStore();

    await store.bootstrap("access-token");

    expect(store.connectionStatus).toBe("incompatible");
    expect(store.errorMessage).toContain("không tương thích");
    expect(store.csrfToken).toBe("");
  });

  it("reports an offline state without exposing the exception", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("sensitive network detail")),
    );
    const store = useSessionStore();

    await store.bootstrap("access-token");

    expect(store.connectionStatus).toBe("offline");
    expect(store.errorMessage).toBe("Không thể kết nối ứng dụng local.");
  });

  it.each([
    {
      name: "incompatible",
      nextResponse: () => Promise.resolve(bootstrapResponse(999)),
      expectedStatus: "incompatible",
    },
    {
      name: "offline",
      nextResponse: () => Promise.reject(new Error("network detail")),
      expectedStatus: "offline",
    },
  ])("clears prior session state before an $name retry", async ({
    nextResponse,
    expectedStatus,
  }) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(bootstrapResponse())
      .mockImplementationOnce(nextResponse);
    vi.stubGlobal("fetch", fetchMock);
    const store = useSessionStore();
    await store.bootstrap("access-token");
    expect(store.csrfToken).toBe("csrf-token");

    await store.bootstrap("next-access-token");

    expect(store.connectionStatus).toBe(expectedStatus);
    expect(store.csrfToken).toBe("");
    expect(store.buildId).toBe("");
    expect(store.state).toBeNull();
  });

  it("polls without overlap and recovers from a temporary failure", async () => {
    const state = applicationState();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(bootstrapResponse())
      .mockResolvedValueOnce(new Response(JSON.stringify(state), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockRejectedValueOnce(new Error("offline")));
    const store = useSessionStore();
    await store.bootstrap("access-token");

    await store.pollState();
    expect(store.state).toEqual(state);
    expect(store.connectionStatus).toBe("ready");
    await store.pollState();
    expect(store.connectionStatus).toBe("offline");
    expect(store.errorMessage).not.toContain("offline");
  });

  it("ticks OTP locally and fetches state only on the bounded refresh cadence", async () => {
    vi.useFakeTimers();
    const state = applicationState();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        api_schema_version: 11,
        build_id: "production-build",
        csrf_token: "csrf-token",
        state,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValue(new Response(JSON.stringify(state), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const store = useSessionStore();
    await store.bootstrap("access-token");
    store.startPolling();

    await vi.advanceTimersByTimeAsync(4_000);
    expect(store.otpRemainingSeconds(store.state!.accounts[0]!)).toBe(16);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    store.stopPolling();
  });

  it("invalidates an expired OTP until the rollover state arrives", async () => {
    vi.useFakeTimers();
    const state = applicationState();
    state.accounts[0] = {
      ...state.accounts[0]!,
      otp: "123456",
      otp_remaining_seconds: 1,
    };
    let resolveState!: (value: Response) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        api_schema_version: 11,
        build_id: "production-build",
        csrf_token: "csrf-token",
        state,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => {
        resolveState = resolve;
      }));
    vi.stubGlobal("fetch", fetchMock);
    const store = useSessionStore();
    await store.bootstrap("access-token");
    store.startPolling();

    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.otpValue(store.state!.accounts[0]!)).toBeNull();
    expect(store.otpRemainingSeconds(store.state!.accounts[0]!)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const nextState = applicationState();
    nextState.accounts[0] = {
      ...nextState.accounts[0]!,
      otp: "654321",
      otp_remaining_seconds: 30,
    };
    resolveState(new Response(JSON.stringify(nextState), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    await vi.advanceTimersByTimeAsync(0);
    expect(store.otpValue(store.state!.accounts[0]!)).toBe("654321");
    store.stopPolling();
  });

  it("stops polling for shutdown and accepts a closed connection", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(bootstrapResponse())
      .mockRejectedValueOnce(new TypeError("connection closed")));
    const store = useSessionStore();
    await store.bootstrap("access-token");
    store.startPolling(1_000);

    await expect(store.shutdown()).resolves.toBe("connection-closed");
    expect(store.connectionStatus).toBe("stopping");
    store.stopPolling();
    vi.useRealTimers();
  });
});
