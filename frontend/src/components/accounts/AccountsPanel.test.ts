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
    expect(wrapper.get(".account-grid").text()).toContain("beta@example.test");
    expect(wrapper.get(".account-grid").text()).not.toContain(
      "alpha@example.test",
    );
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

  it("hides the smart account recommendation queue", () => {
    const wrapper = mount(AccountsPanel);

    expect(wrapper.find('[aria-label="Hàng đợi tài khoản thông minh"]').exists())
      .toBe(false);
  });

  it("does not expose orphan profile archiving", () => {
    const wrapper = mount(AccountsPanel);

    expect(wrapper.find('[data-action="archive-orphans"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("profile mồ côi");
  });

  it("requires confirmation before unlink and delete mutations", async () => {
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
    expect(wrapper.find('[data-action="reset-profile"]').exists()).toBe(false);
    await options().trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="delete"]').trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledTimes(2);
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

  it("updates only the locally stored password without prefilling it", async () => {
    const accounts = useAccountsStore();
    let finishUpdate!: () => void;
    const updatePassword = vi.spyOn(accounts, "updatePassword")
      .mockImplementation(() => new Promise<void>((resolve) => {
        finishUpdate = resolve;
      }));
    const wrapper = mount(AccountsPanel, {
      global: { stubs: { Teleport: true } },
    });

    await wrapper.findAll('[data-action="options"]')[0]!.trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="edit-password"]').trigger("click");
    const input = wrapper.get<HTMLInputElement>(
      'input[name="updated-password"]',
    );

    expect(input.attributes("type")).toBe("password");
    expect(input.element.value).toBe("");
    expect(wrapper.get('[role="dialog"]').text()).toContain(
      "không đổi mật khẩu OpenAI/ChatGPT",
    );
    await input.setValue("new-password");
    await wrapper.get('[data-action="save-password"]').trigger("click");
    await input.trigger("keydown.enter");
    expect(updatePassword).toHaveBeenCalledOnce();
    finishUpdate();
    await flushPromises();

    expect(updatePassword).toHaveBeenCalledWith(
      applicationState().accounts[0]!.id,
      "new-password",
    );
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("new-password");
    expect(JSON.stringify(accounts.$state)).not.toContain("new-password");
  });

  it("opens a secret form, copies the saved secret, and saves a replacement", async () => {
    const accounts = useAccountsStore();
    const sensitiveValue = vi.spyOn(accounts, "sensitiveValue")
      .mockResolvedValue("saved-secret");
    const updateSecret = vi.spyOn(accounts, "updateSecret").mockResolvedValue();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const wrapper = mount(AccountsPanel, {
      global: { stubs: { Teleport: true } },
    });

    await wrapper.findAll('[data-action="options"]')[0]!.trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="secret"]').trigger("click");
    expect(wrapper.get('[role="dialog"]').text()).toContain("Secret hiện tại");
    expect(sensitiveValue).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("saved-secret");

    await wrapper.get('[data-action="copy-secret"]').trigger("click");
    await flushPromises();
    expect(sensitiveValue).toHaveBeenCalledWith(
      applicationState().accounts[0]!.id, "secret",
    );
    expect(writeText).toHaveBeenCalledWith("saved-secret");

    const input = wrapper.get<HTMLInputElement>('input[name="updated-secret"]');
    expect(input.attributes("type")).toBe("password");
    await input.setValue("KRUGS4ZANFZSAYJA");
    await wrapper.get('[data-action="save-secret"]').trigger("click");
    await flushPromises();
    expect(updateSecret).toHaveBeenCalledWith(
      applicationState().accounts[0]!.id, "KRUGS4ZANFZSAYJA",
    );
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("KRUGS4ZANFZSAYJA");
    expect(JSON.stringify(accounts.$state)).not.toContain("KRUGS4ZANFZSAYJA");
  });

  it("edits and clears a locally stored Plus expiration with a native date input", async () => {
    const accounts = useAccountsStore();
    const updatePlusExpiration = vi.spyOn(accounts, "updatePlusExpiration")
      .mockResolvedValue();
    const wrapper = mount(AccountsPanel, {
      global: { stubs: { Teleport: true } },
    });

    await wrapper.findAll('[data-action="options"]')[0]!.trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="edit-plus-expiration"]').trigger("click");
    const input = wrapper.get<HTMLInputElement>(
      'input[name="updated-plus-expiration"]',
    );

    expect(input.attributes("type")).toBe("date");
    expect(input.element.value).toBe("2026-10-11");
    expect(wrapper.get('[role="dialog"]').text()).toContain("tự nhập");
    await input.setValue("2026-11-12");
    await wrapper.get('[data-action="save-plus-expiration"]').trigger("click");
    await flushPromises();

    expect(updatePlusExpiration).toHaveBeenCalledWith(
      applicationState().accounts[0]!.id,
      "2026-11-12",
    );
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await wrapper.findAll('[data-action="options"]')[0]!.trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('[data-action="edit-plus-expiration"]').trigger("click");
    const clearInput = wrapper.get<HTMLInputElement>(
      'input[name="updated-plus-expiration"]',
    );
    await clearInput.setValue("");
    await wrapper.get('[data-action="save-plus-expiration"]').trigger("click");
    await flushPromises();

    expect(updatePlusExpiration).toHaveBeenLastCalledWith(
      applicationState().accounts[0]!.id,
      null,
    );
  });
});
