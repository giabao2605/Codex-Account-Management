import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "./session.ts";
import { applicationState } from "@/test/fixtures.ts";

function bootstrapResponse(apiSchemaVersion = 10): Response {
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

  it("accepts schema 10 and keeps CSRF in store memory", async () => {
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
