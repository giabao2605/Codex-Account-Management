import { createPinia, setActivePinia } from "pinia";
import {
  flushPromises,
  mount,
  type DOMWrapper,
  type VueWrapper,
} from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAccountsStore } from "@/stores/accounts.ts";
import { useFeedbackStore } from "@/stores/feedback.ts";
import type { AccountCheckResponse } from "@/types/api.ts";
import ImportDialog from "./ImportDialog.vue";

const accountLine = (
  "alpha@example.test|fixture-password|JBSWY3DPEHPK3PXP"
);
const available: AccountCheckResponse = {
  valid: true,
  conflict: null,
  message: "Tài khoản có thể được thêm.",
};

function button(
  wrapper: VueWrapper,
  label: string,
): DOMWrapper<HTMLButtonElement> {
  const match = wrapper
    .findAll("button")
    .find((candidate) => candidate.text() === label);
  if (!match) throw new Error(`Không tìm thấy nút ${label}`);
  return match;
}

function mountDialog(): VueWrapper {
  return mount(ImportDialog, {
    props: { open: true, morphId: "import-account-dialog" },
    global: {
      plugins: [createPinia()],
      stubs: { Teleport: true },
    },
  });
}

describe("ImportDialog", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders one secure account input without preview or bulk controls", () => {
    const wrapper = mountDialog();

    expect(wrapper.get('[role="dialog"]').text()).toContain("Thêm tài khoản");
    expect(wrapper.text()).toContain(
      "Nhập một tài khoản theo định dạng: email|password|secret",
    );
    expect(wrapper.get('input[name="account"]').attributes("placeholder")).toBe(
      "user@example.com|password|TOTP_SECRET",
    );
    expect(wrapper.text()).not.toContain("Thông tin tài khoản");
    expect(wrapper.text()).not.toContain("Dữ liệu được mã hóa");
    expect(wrapper.text()).not.toContain(
      "Tài khoản chỉ được thêm khi email và secret chưa tồn tại.",
    );
    expect(wrapper.get(".account-check-status").text()).toBe("");
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Xem trước");
    expect(button(wrapper, "Thêm").attributes()).toHaveProperty(
      "disabled",
    );
    expect(
      wrapper.findAll(".glass-dialog-actions .surface-action-button"),
    ).toHaveLength(2);

    wrapper.unmount();
  });

  it("debounces checks and enables adding only when the latest value is available", async () => {
    vi.useFakeTimers();
    const wrapper = mountDialog();
    const accounts = useAccountsStore();
    const checkAccount = vi.spyOn(accounts, "checkAccount").mockResolvedValue(
      available,
    );

    const input = wrapper.get('input[name="account"]');
    await input.setValue(accountLine.replace("alpha", "first"));
    await input.setValue(accountLine);
    await vi.advanceTimersByTimeAsync(299);
    expect(checkAccount).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();

    expect(checkAccount).toHaveBeenCalledOnce();
    expect(checkAccount).toHaveBeenCalledWith(accountLine);
    expect(wrapper.get('[role="status"]').text()).toBe(available.message);
    expect(wrapper.get(".account-check-status").classes()).toContain("success");
    expect(button(wrapper, "Thêm").attributes()).not.toHaveProperty(
      "disabled",
    );

    wrapper.unmount();
  });

  it("shows duplicate feedback inline and keeps adding disabled", async () => {
    vi.useFakeTimers();
    const wrapper = mountDialog();
    const accounts = useAccountsStore();
    vi.spyOn(accounts, "checkAccount").mockResolvedValue({
      valid: false,
      conflict: "email",
      message: "Email đã tồn tại.",
    });

    await wrapper.get('input[name="account"]').setValue(accountLine);
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toBe("Email đã tồn tại.");
    expect(wrapper.get(".account-check-status").classes()).toContain("error");
    expect(button(wrapper, "Thêm").attributes()).toHaveProperty(
      "disabled",
    );

    wrapper.unmount();
  });

  it("ignores an outdated check after the input changes", async () => {
    vi.useFakeTimers();
    const wrapper = mountDialog();
    const accounts = useAccountsStore();
    let resolveFirst!: (value: AccountCheckResponse) => void;
    let resolveSecond!: (value: AccountCheckResponse) => void;
    vi.spyOn(accounts, "checkAccount")
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveFirst = resolve;
      }))
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveSecond = resolve;
      }));
    const input = wrapper.get('input[name="account"]');

    await input.setValue(accountLine);
    await vi.advanceTimersByTimeAsync(300);
    await input.setValue(accountLine.replace("alpha", "beta"));
    await vi.advanceTimersByTimeAsync(300);
    resolveFirst({
      valid: false,
      conflict: "email",
      message: "Kết quả cũ.",
    });
    resolveSecond(available);
    await flushPromises();

    expect(wrapper.text()).toContain(available.message);
    expect(wrapper.text()).not.toContain("Kết quả cũ.");

    wrapper.unmount();
  });

  it("adds the checked account, clears local state, and closes", async () => {
    vi.useFakeTimers();
    const wrapper = mountDialog();
    const accounts = useAccountsStore();
    const feedback = useFeedbackStore();
    vi.spyOn(accounts, "checkAccount").mockResolvedValue(available);
    const addAccount = vi.spyOn(accounts, "addAccount").mockResolvedValue({
      total: 1,
      email: "alpha@example.test",
    });
    const success = vi.spyOn(feedback, "success").mockImplementation(() => {});

    await wrapper.get('input[name="account"]').setValue(accountLine);
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await button(wrapper, "Thêm").trigger("click");
    await flushPromises();

    expect(addAccount).toHaveBeenCalledWith(accountLine);
    expect(success).toHaveBeenCalledWith("Đã thêm alpha@example.test.");
    expect(wrapper.emitted("close")).toHaveLength(1);
    expect(wrapper.get<HTMLInputElement>('input[name="account"]').element.value)
      .toBe("");

    wrapper.unmount();
  });

  it("rechecks a rejected add and keeps the input for correction", async () => {
    vi.useFakeTimers();
    const wrapper = mountDialog();
    const accounts = useAccountsStore();
    const feedback = useFeedbackStore();
    vi.spyOn(accounts, "checkAccount")
      .mockResolvedValueOnce(available)
      .mockResolvedValueOnce({
        valid: false,
        conflict: "secret",
        message: "Secret 2FA đã được dùng bởi tài khoản khác.",
      });
    vi.spyOn(accounts, "addAccount").mockRejectedValue(new Error("race"));
    const showError = vi.spyOn(feedback, "error").mockImplementation(() => {});

    await wrapper.get('input[name="account"]').setValue(accountLine);
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    await button(wrapper, "Thêm").trigger("click");
    await flushPromises();

    expect(wrapper.emitted("close")).toBeUndefined();
    expect(wrapper.get<HTMLInputElement>('input[name="account"]').element.value)
      .toBe(accountLine);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Secret 2FA đã được dùng bởi tài khoản khác.",
    );
    expect(showError).toHaveBeenCalledWith(
      "Secret 2FA đã được dùng bởi tài khoản khác.",
    );

    wrapper.unmount();
  });
});
