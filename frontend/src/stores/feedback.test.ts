import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useFeedbackStore } from "./feedback.ts";

describe("feedback store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.useFakeTimers();
  });

  it("exposes generic success and error helpers and auto-hides feedback", () => {
    const store = useFeedbackStore();

    store.success("Đã hoàn tất.");
    expect(store.isVisible).toBe(true);
    expect(store.isError).toBe(false);

    store.error("Không thể hoàn tất.");
    expect(store.message).toBe("Không thể hoàn tất.");
    expect(store.isError).toBe(true);

    vi.advanceTimersByTime(3_200);
    expect(store.isVisible).toBe(false);
    vi.useRealTimers();
  });
});
