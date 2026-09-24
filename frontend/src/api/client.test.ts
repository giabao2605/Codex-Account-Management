import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, LocalApiClient, userFacingError } from "./client.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LocalApiClient", () => {
  it("sends bearer auth without persisting CSRF for GET requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new LocalApiClient("access-token", () => "csrf-token");

    await client.request("/api/state");

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(requestInit.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.has("X-CSRF-Token")).toBe(false);
  });

  it("requires and sends the in-memory CSRF token for mutations", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ accepted: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new LocalApiClient("access-token", () => "csrf-token");

    await client.request("/api/codex/refresh", {
      method: "POST",
      body: JSON.stringify({ force_token_usage: true }),
    });

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(requestInit.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("fails closed when a mutation has no CSRF token", async () => {
    const client = new LocalApiClient("access-token", () => "");

    await expect(
      client.request("/api/codex/refresh", { method: "POST" }),
    ).rejects.toEqual(
      expect.objectContaining({ status: 403 }),
    );
  });

  it("returns a generic error for rejected responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    );
    const client = new LocalApiClient("invalid", () => "");

    await expect(client.bootstrap()).rejects.toEqual(
      expect.objectContaining({
        message: "Không thể kết nối ứng dụng local.",
        status: 401,
      }),
    );
  });

  it("uses a bounded error detail only when it comes from the local app", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(new Response(
          JSON.stringify({ detail: "Không tìm thấy tài khoản." }),
          {
            status: 404,
            headers: {
              "Content-Type": "application/json",
              "X-OTP-Codex-App": "1",
            },
          },
        ))
        .mockResolvedValueOnce(new Response(
          JSON.stringify({ detail: "SENTINEL untrusted detail" }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          },
        )),
    );
    const client = new LocalApiClient("access-token", () => "csrf-token");

    await expect(client.deleteAccount("missing")).rejects.toEqual(
      expect.objectContaining({ message: "Không tìm thấy tài khoản." }),
    );
    await expect(client.deleteAccount("missing")).rejects.toEqual(
      expect.objectContaining({
        message: "Không thể kết nối ứng dụng local.",
      }),
    );
    expect(userFacingError(
      new ApiError("Thao tác quá nhanh.", 429),
      "Không thể hoàn tất.",
    )).toBe("Thao tác quá nhanh.");
    expect(userFacingError(
      new Error("SENTINEL internal"),
      "Không thể hoàn tất.",
    )).toBe("Không thể hoàn tất.");
  });

  it("maps every Phase 3 endpoint through the centralized client", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ accepted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    const client = new LocalApiClient("access-token", () => "csrf-token");

    await client.state();
    await client.tokenUsage();
    await client.failoverStatus();
    await client.checkAccount("alpha@example.test|password|secret");
    await client.addAccount("alpha@example.test|password|secret");
    await client.sensitiveValue("1111111111111111", "password");
    await client.updatePassword("1111111111111111", "new-password");
    await client.updateSecret("1111111111111111", "KRUGS4ZANFZSAYJA");
    await client.updatePlusExpiration("1111111111111111", "2026-10-11");
    await client.refresh("1111111111111111");
    await client.login("1111111111111111");
    await client.unlink("1111111111111111");
    await client.deleteAccount("1111111111111111");
    await client.shutdown();
    expect("archiveOrphans" in client).toBe(false);
    expect("resetProfile" in client).toBe(false);

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/state",
      "/api/usage/tokens",
      "/api/failover/status",
      "/api/accounts/import/check",
      "/api/accounts/import",
      "/api/accounts/1111111111111111/sensitive",
      "/api/accounts/1111111111111111/password",
      "/api/accounts/1111111111111111/secret",
      "/api/accounts/1111111111111111/plus-expiration",
      "/api/codex/refresh",
      "/api/codex/1111111111111111/login",
      "/api/codex/1111111111111111/unlink",
      "/api/accounts/1111111111111111",
      "/api/application/shutdown",
    ]);
    const passwordCall = fetchMock.mock.calls.find(
      ([path]) => path === "/api/accounts/1111111111111111/password",
    )!;
    expect(passwordCall[1]).toEqual(expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ password: "new-password" }),
    }));
    const secretCall = fetchMock.mock.calls.find(
      ([path]) => path === "/api/accounts/1111111111111111/secret",
    )!;
    expect(secretCall[1]).toEqual(expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ secret: "KRUGS4ZANFZSAYJA" }),
    }));
    const plusExpirationCall = fetchMock.mock.calls.find(
      ([path]) => path === "/api/accounts/1111111111111111/plus-expiration",
    )!;
    expect(plusExpirationCall[1]).toEqual(expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ plus_expires_at: "2026-10-11" }),
    }));

    const mutationCalls = fetchMock.mock.calls.filter(([, init]) => (
      !["GET", "HEAD", "OPTIONS"].includes(
        String((init as RequestInit).method ?? "GET").toUpperCase(),
      )
    ));
    expect(
      mutationCalls.every(([, init]) => (
        new Headers((init as RequestInit).headers).get("X-CSRF-Token")
        === "csrf-token"
      )),
    ).toBe(true);
  });
});
