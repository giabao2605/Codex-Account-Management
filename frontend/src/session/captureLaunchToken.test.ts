import { describe, expect, it, vi } from "vitest";

import {
  ACCESS_TOKEN_STORAGE_KEY,
  captureLaunchToken,
} from "./captureLaunchToken.ts";

describe("captureLaunchToken", () => {
  it("stores the fragment before removing it from the URL", () => {
    const values = new Map<string, string>();
    const historyPort = { replaceState: vi.fn() };
    const storagePort = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    const token = captureLaunchToken(
      { hash: "#launch-token", pathname: "/", search: "?mode=test" },
      historyPort,
      storagePort,
    );

    expect(token).toBe("launch-token");
    expect(values.get(ACCESS_TOKEN_STORAGE_KEY)).toBe("launch-token");
    expect(historyPort.replaceState).toHaveBeenCalledWith(
      null,
      "",
      "/?mode=test",
    );
  });

  it("reuses the session token when the fragment is absent", () => {
    const historyPort = { replaceState: vi.fn() };
    const storagePort = {
      getItem: () => "saved-token",
      setItem: vi.fn(),
    };

    const token = captureLaunchToken(
      { hash: "", pathname: "/", search: "" },
      historyPort,
      storagePort,
    );

    expect(token).toBe("saved-token");
    expect(storagePort.setItem).not.toHaveBeenCalled();
    expect(historyPort.replaceState).not.toHaveBeenCalled();
  });

  it("returns an empty token when no launch session exists", () => {
    const token = captureLaunchToken(
      { hash: "", pathname: "/", search: "" },
      { replaceState: vi.fn() },
      {
        getItem: () => null,
        setItem: vi.fn(),
      },
    );

    expect(token).toBe("");
  });
});
