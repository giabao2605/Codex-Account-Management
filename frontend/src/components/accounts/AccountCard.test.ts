import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { applicationState } from "@/test/fixtures.ts";
import AccountCard from "./AccountCard.vue";

describe("AccountCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows recommendation, plan, OTP, quota, sync, reset, and last-sync state", () => {
    const account = applicationState().accounts[0]!;
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: true,
        busyActions: [],
      },
    });

    expect(wrapper.element.tagName).toBe("ARTICLE");
    expect(wrapper.text()).toContain("alpha@example.test");
    expect(wrapper.text()).toContain("Plus");
    expect(wrapper.text()).toContain("Đề xuất sử dụng");
    expect(wrapper.text()).toContain("Còn 20 giây");
    expect(wrapper.get(".otp-progress").attributes("value")).toBe("20");
    expect(wrapper.get(".quota-progress").attributes("value")).toBe("82");
    expect(wrapper.text()).toContain("Đã đồng bộ");
    expect(wrapper.text()).toContain("23/07 14:00");
    expect(wrapper.text()).toContain("23/07 09:45");
    expect(wrapper.get(".status").classes()).toContain("is-normal");
    expect(wrapper.attributes("data-material")).toBe("standard");
    expect(wrapper.attributes("data-material-role")).toBe("account-card");
    expect(wrapper.find('[data-glass-level]').exists()).toBe(false);
  });

  it("keeps a long email in a single constrained identity field", () => {
    const account = {
      ...applicationState().accounts[0]!,
      email: "amoeba55kilt+20fable.minted@icloud.com",
    };
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: false,
        busyActions: [],
      },
    });

    const email = wrapper.get(".account-email");
    expect(email.text()).toBe(account.email);
    expect(email.attributes("title")).toBe(account.email);
    expect(wrapper.get(".status").attributes("title")).toBe(account.account_state);
  });

  it("copies the OTP when its displayed value is clicked", async () => {
    const account = applicationState().accounts[0]!;
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: false,
        busyActions: [],
      },
    });

    const otpValue = wrapper.get('[data-action="otp-value"]');
    expect(otpValue.element.tagName).toBe("BUTTON");
    expect(otpValue.text()).toBe(account.otp);
    expect(otpValue.attributes("aria-label")).toContain(account.otp!);

    await otpValue.trigger("click");

    expect(wrapper.emitted("copyOtp")).toHaveLength(1);
  });

  it("keeps primary actions compact and puts remaining actions in an accessible popover", async () => {
    const account = applicationState().accounts[0]!;
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: false,
        busyActions: ["password", "refresh"],
      },
    });

    const primaryActions = wrapper.get(".account-primary-actions");
    expect(primaryActions.attributes("role")).toBe("group");
    expect(primaryActions.attributes("data-liquid-container")).toBe("actions");
    expect(primaryActions.text()).toContain("Email");
    expect(primaryActions.text()).toContain("Mật khẩu");
    expect(primaryActions.text()).toContain("Tùy chọn");
    expect(primaryActions.findAll(":scope > button")).toHaveLength(2);
    expect(wrapper.get('[data-action="password"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-action="password"]').attributes("aria-busy")).toBe("true");
    expect(wrapper.find("details").exists()).toBe(false);

    const trigger = wrapper.get('[data-action="options"]');
    expect(trigger.attributes("aria-haspopup")).toBe("menu");
    expect(trigger.attributes("aria-expanded")).toBe("false");
    await trigger.trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();
    expect(wrapper.get('[data-action="options"]').attributes("aria-expanded"))
      .toBe("true");
    expect(wrapper.get(".account-option-actions").attributes("role")).toBe("menu");
    expect(
      wrapper.get(".glass-popover-panel").attributes("data-glass-depth"),
    ).toBe("thick");
    expect(
      wrapper.get(".glass-popover-panel").attributes("data-glass-morph"),
    ).toBe("popover");
    expect(trigger.attributes("data-glass-morph-id")).toBe(
      `account-options-${account.id}`,
    );
    expect(
      wrapper.get(".glass-popover-panel").attributes("data-glass-morph-id"),
    ).toBe(`account-options-${account.id}`);
    expect(
      wrapper.findAll(".account-option-actions [data-glass-version]"),
    ).toHaveLength(0);
    expect(wrapper.find('[data-action="login"]').exists()).toBe(false);
    expect(wrapper.get('[data-action="refresh"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get(".account-option-actions").text()).toContain("Secret");
    expect(wrapper.get(".account-option-actions").text()).toContain("Đồng bộ");
    expect(wrapper.get(".account-option-actions").text()).toContain("Ngắt liên kết");
    expect(wrapper.get(".account-option-actions").text()).toContain("Đặt lại profile");
    expect(wrapper.get(".account-option-actions").text()).toContain("Xóa tài khoản");

    await wrapper.get('[data-action="unlink"]').trigger("click");
    expect(wrapper.emitted("unlink")).toHaveLength(1);
    expect(wrapper.get('[data-action="options"]').attributes("aria-expanded"))
      .toBe("false");
  });

  it("shows only the Codex link action for an unlinked account", async () => {
    const account = applicationState().accounts[1]!;
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: false,
        busyActions: [],
      },
    });

    expect(wrapper.get(".status").classes()).toContain("is-warning");
    await wrapper.get('[data-action="options"]').trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(wrapper.get('[data-action="login"]').text()).toBe("Liên kết Codex");
    expect(wrapper.find('[data-action="unlink"]').exists()).toBe(false);
    await wrapper.get('[data-action="login"]').trigger("click");
    expect(wrapper.emitted("login")).toHaveLength(1);
  });

  it("does not render unavailable OTP as a sensitive value", async () => {
    const account = applicationState().accounts[1]!;
    const wrapper = mount(AccountCard, {
      props: {
        account,
        recommended: false,
        busyActions: [],
      },
    });

    expect(wrapper.text()).toContain("Không khả dụng");
    await wrapper.get('[data-action="options"]').trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();
    expect(wrapper.get('[data-action="otp"]').attributes("disabled")).toBeDefined();
    expect(wrapper.find(".otp-progress").exists()).toBe(false);
  });
});
