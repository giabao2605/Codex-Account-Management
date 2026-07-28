import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAccountsStore } from "@/stores/accounts.ts";
import { useFeedbackStore } from "@/stores/feedback.ts";
import { useSessionStore } from "@/stores/session.ts";
import { applicationState } from "@/test/fixtures.ts";
import AccountsPanel from "./AccountsPanel.vue";

describe("AccountsPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useSessionStore().state = applicationState();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("offers all seven account filters in a morphing popover", async () => {
    const wrapper = mount(AccountsPanel);
    await wrapper.get(".account-filter-trigger").trigger("click");
    await vi.dynamicImportSettled();
    const options = wrapper.findAll(
      'input[name^="glass-select-"][type="radio"]',
    );

    expect(options).toHaveLength(7);
    expect(wrapper.text()).toContain("Quota còn");
    expect(wrapper.text()).toContain("Quota hết");
    await options.find(
      (option) => option.attributes("value") === "quota-unknown",
    )!.setValue();
    expect(useAccountsStore().filter).toBe("quota-unknown");
    expect(wrapper.text()).toContain("beta@example.test");
    expect(wrapper.text()).not.toContain("alpha@example.test");
  });

  it("separates standard account content from liquid action controls", () => {
    const wrapper = mount(AccountsPanel);

    expect(wrapper.get("#accounts-heading").text()).toBe("Tổng tài khoản: 2");
    expect(
      wrapper.get(".account-toolbar [data-action='account-status-details']")
        .text(),
    ).toBe("Chi tiết");
    expect(
      wrapper.find(".accounts-heading-main [data-action='account-status-details']")
        .exists(),
    ).toBe(false);
    expect(wrapper.get(".account-filter-trigger").classes())
      .toContain("glass-button");
    expect(wrapper.get(".account-grid").attributes("data-content-layer")).toBe(
      "standard",
    );
    expect(
      wrapper.findAll('.account-card[data-material="standard"]'),
    ).toHaveLength(2);
    expect(
      wrapper.findAll('[data-liquid-container="actions"]'),
    ).toHaveLength(2);
  });

  it("confirms orphan archive and reports generic global feedback", async () => {
    const accounts = useAccountsStore();
    const archiveOrphans = vi.spyOn(accounts, "archiveOrphans")
      .mockResolvedValue({ archived: 1 });
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    const wrapper = mount(AccountsPanel);

    await wrapper.get('[data-action="archive-orphans"]').trigger("click");
    await flushPromises();

    expect(archiveOrphans).toHaveBeenCalledOnce();
    expect(useFeedbackStore().message).toBe("Đã lưu trữ 1 profile mồ côi.");
    expect(useFeedbackStore().isError).toBe(false);
  });

  it("requires confirmation before unlink, reset, and delete mutations", async () => {
    const accounts = useAccountsStore();
    const lifecycle = vi.spyOn(accounts, "lifecycle").mockResolvedValue();
    const deleteAccount = vi.spyOn(accounts, "deleteAccount").mockResolvedValue();
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirm);
    const wrapper = mount(AccountsPanel);

    const options = () => (
      wrapper.findAll('[data-action="options"]')[0]!
    );
    await options().trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="unlink"]').trigger("click");
    await options().trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="reset-profile"]').trigger("click");
    await options().trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="delete"]').trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledTimes(3);
    expect(lifecycle).not.toHaveBeenCalled();
    expect(deleteAccount).not.toHaveBeenCalled();
  });

  it("copies a sensitive value transiently without storing or rendering it", async () => {
    const accounts = useAccountsStore();
    vi.spyOn(accounts, "sensitiveValue").mockResolvedValue("transient-password");
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const wrapper = mount(AccountsPanel);

    await wrapper.get('[data-action="password"]').trigger("click");
    await flushPromises();

    expect(writeText).toHaveBeenCalledWith("transient-password");
    expect(wrapper.text()).not.toContain("transient-password");
    expect(JSON.stringify(accounts.$state)).not.toContain("transient-password");
    expect(useFeedbackStore().message).not.toContain("transient-password");
  });
});
