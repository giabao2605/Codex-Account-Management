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

  it("shows an explained recommendation queue and acts only on request", async () => {
    const session = useSessionStore();
    const state = applicationState();
    const fallback = {
      ...state.accounts[0]!,
      id: "3333333333333333",
      email: "gamma@example.test",
      quota_remaining: "60%",
      quota_reset_at: "23/07 10:00",
    };
    session.state = {
      ...state,
      accounts: [...state.accounts, fallback],
      recommendation_queue: [
        {
          ...state.recommendation!,
          rank: 1,
          reason: "Hoạt động bình thường · còn 82% quota · reset 24/07 10:00",
        },
        {
          account_id: fallback.id,
          email: fallback.email,
          quota_remaining: fallback.quota_remaining,
          quota_reset_at: fallback.quota_reset_at,
          rank: 2,
          reason: "Hoạt động bình thường · còn 60% quota · reset 23/07 10:00",
        },
      ],
      usage_statistics: {
        ...state.usage_statistics,
        next_reset_at: "23/07 10:00",
      },
    };
    const accounts = useAccountsStore();
    accounts.filter = "attention";
    const refresh = vi.spyOn(accounts, "refresh").mockResolvedValue(true);
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const wrapper = mount(AccountsPanel, { attachTo: document.body });

    const queue = wrapper.get('[aria-label="Hàng đợi tài khoản thông minh"]');
    expect(queue.get('[data-queue-role="recommended"]').text()).toContain(
      "alpha@example.test",
    );
    expect(queue.get('[data-queue-role="recommended"]').text()).toContain(
      "82%",
    );
    expect(queue.get('[data-queue-role="fallback"]').text()).toContain(
      "gamma@example.test",
    );
    expect(queue.text()).toContain("Reset gần nhất: 23/07 10:00");
    expect(refresh).not.toHaveBeenCalled();

    await queue.get('[data-action="focus-recommendation"]').trigger("click");
    await wrapper.vm.$nextTick();
    expect(accounts.filter).toBe("all");
    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(document.activeElement?.id).toBe("account-1111111111111111");
    expect(refresh).not.toHaveBeenCalled();

    await queue.get('[data-action="refresh-recommendation"]').trigger("click");
    expect(refresh).toHaveBeenCalledWith(null);
    wrapper.unmount();
  });

  it("does not invent a recommendation when the backend has none", () => {
    const session = useSessionStore();
    session.state = {
      ...applicationState(),
      recommendation: null,
      recommendation_queue: [],
    };

    const wrapper = mount(AccountsPanel);

    expect(wrapper.get('[aria-label="Hàng đợi tài khoản thông minh"]').text())
      .toContain("Chưa có tài khoản đủ dữ liệu để đề xuất");
    expect(wrapper.find('[data-action="focus-recommendation"]').exists())
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
});
