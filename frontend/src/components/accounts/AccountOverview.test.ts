import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "@/stores/session.ts";
import { applicationState } from "@/test/fixtures.ts";
import AccountOverview from "./AccountOverview.vue";

describe("AccountOverview", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("keeps only actionable status visible and moves telemetry into details", async () => {
    const session = useSessionStore();
    session.state = applicationState();
    session.lastUpdated = new Date("2026-07-23T09:59:00+07:00");

    const wrapper = mount(AccountOverview);

    expect(wrapper.text()).not.toContain("1 tài khoản cần xử lý");
    expect(wrapper.text()).not.toContain("Tự làm mới");
    expect(wrapper.findAll(".overview-card")).toHaveLength(0);
    const detailsTrigger = wrapper.get('[data-action="account-status-details"]');
    expect(detailsTrigger.attributes("aria-haspopup")).toBe("dialog");
    expect(detailsTrigger.attributes("aria-controls")).toBeTruthy();

    await detailsTrigger.trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(wrapper.text()).toContain("1 tài khoản cần xử lý");
    expect(wrapper.text()).toContain("Tự làm mới");
    expect(wrapper.text()).toContain("60 giây");
    expect(wrapper.text()).toContain("Cập nhật gần nhất");
    expect(wrapper.text()).toContain("09:59");
    expect(wrapper.text()).toContain("Đồng bộ thời gian");
    expect(wrapper.text()).toContain("bù 0 giây");
    expect(wrapper.text()).toContain("Đồng bộ tài khoản");
    expect(wrapper.text()).toContain("1 / 2");
    expect(wrapper.text()).toContain("1 chưa liên kết");
  });

  it("does not report healthy status when quota data needs updating", async () => {
    const session = useSessionStore();
    const current = applicationState();
    session.state = {
      ...current,
      sync_status: "2 thành công, 0 cần đăng nhập, 0 chưa liên kết, 0 lỗi tạm thời",
      usage_statistics: {
        ...current.usage_statistics,
        attention_accounts: 0,
        low_quota_accounts: 0,
        exhausted_accounts: 0,
        quota_unknown_accounts: 1,
        stale_quota_accounts: 1,
      },
    };

    const wrapper = mount(AccountOverview);
    await wrapper.get('[data-action="account-status-details"]').trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(wrapper.text()).toContain("Dữ liệu quota cần cập nhật");
    expect(wrapper.text()).not.toContain("Tất cả hoạt động bình thường");
  });

  it.each([
    [1, 1, "1 tài khoản hết quota"],
    [0, 1, "1 tài khoản quota thấp"],
    [0, 0, "Tất cả hoạt động bình thường"],
  ])(
    "prioritizes exhausted=%i and low=%i as %s",
    async (exhausted, low, expected) => {
      const session = useSessionStore();
      const current = applicationState();
      session.state = {
        ...current,
        sync_status: "2 thành công, 0 cần đăng nhập, 0 chưa liên kết, 0 lỗi tạm thời",
        usage_statistics: {
          ...current.usage_statistics,
          attention_accounts: 0,
          exhausted_accounts: exhausted,
          low_quota_accounts: low,
          quota_unknown_accounts: 0,
          stale_quota_accounts: 0,
        },
      };
      const wrapper = mount(AccountOverview);

      await wrapper.get('[data-action="account-status-details"]').trigger("click");
      await vi.dynamicImportSettled();
      await flushPromises();

      expect(wrapper.text()).toContain(expected);
    },
  );
});
