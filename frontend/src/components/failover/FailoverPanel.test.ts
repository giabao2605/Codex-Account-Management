import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalApiClient } from "@/api/client.ts";
import { useSessionStore } from "@/stores/session.ts";
import FailoverPanel from "./FailoverPanel.vue";

describe("FailoverPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders only aggregate failover metadata and refreshes on request", async () => {
    const status = {
      schema_version: 1 as const,
      available: true,
      enabled: true,
      state: "observing" as const,
      updated_at: "2026-08-12T10:00:00+00:00",
      has_error: false,
      tasks: {
        total: 3,
        active: 1,
        completed: 1,
        blocked: 0,
        quota_exhausted: 1,
        eligible: 2,
      },
      quotas: { total: 2, exhausted: 1 },
    };
    const failoverStatus = vi.fn().mockResolvedValue(status);
    vi.spyOn(useSessionStore(), "getClient").mockReturnValue({
      failoverStatus,
    } as unknown as LocalApiClient);
    const wrapper = mount(FailoverPanel);
    await flushPromises();

    expect(wrapper.get("h2").text()).toBe("Trạng thái failover");
    expect(wrapper.text()).toContain("Đang theo dõi");
    expect(wrapper.text()).toContain("Task đang hoạt động");
    expect(wrapper.text()).toContain("1");
    expect(wrapper.text()).toContain("metadata tổng hợp");
    expect(wrapper.text()).not.toContain("session_id");
    expect(wrapper.text()).not.toContain("cwd");

    await wrapper.get('[data-action="refresh-failover"]').trigger("click");
    await flushPromises();
    expect(failoverStatus).toHaveBeenCalledTimes(2);
  });

  it("explains an absent registry without implying failover is active", async () => {
    vi.spyOn(useSessionStore(), "getClient").mockReturnValue({
      failoverStatus: vi.fn().mockResolvedValue({
        schema_version: 1,
        available: false,
        enabled: false,
        state: "disabled",
        updated_at: null,
        has_error: false,
        tasks: {
          total: 0,
          active: 0,
          completed: 0,
          blocked: 0,
          quota_exhausted: 0,
          eligible: 0,
        },
        quotas: { total: 0, exhausted: 0 },
      }),
    } as unknown as LocalApiClient);

    const wrapper = mount(FailoverPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Chưa có registry");
    expect(wrapper.text()).toContain("không tạo registry mới");
  });
});
