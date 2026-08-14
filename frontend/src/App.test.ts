import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { applicationState } from "@/test/fixtures.ts";
import App from "./App.vue";

afterEach(() => {
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("production App", () => {
  it("renders the query-gated Glass Lab without starting a production session", async () => {
    window.history.replaceState({}, "", "/?glass-lab=1");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(App, {
      props: { accessToken: "access-token" },
      global: { plugins: [createPinia()] },
      attachTo: document.body,
    });
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(wrapper.get('[data-testid="glass-lab"]').attributes(
      "data-glass-lab",
    )).toBe("v3");
    expect(wrapper.find(".shell").exists()).toBe(false);
    expect(wrapper.find(".app-command-layer").exists()).toBe(false);
    expect(wrapper.find(".feedback-toast").exists()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();

    wrapper.unmount();
  });

  it("bootstraps and preserves accessible workspace tab behavior", async () => {
    let notifyIntersection:
      | ((isIntersecting: boolean) => void)
      | undefined;
    const disconnect = vi.fn();
    const observe = vi.fn();
    class IntersectionObserverStub {
      constructor(callback: IntersectionObserverCallback) {
        notifyIntersection = (isIntersecting: boolean) => {
          callback(
            [{ isIntersecting } as IntersectionObserverEntry],
            this as unknown as IntersectionObserver,
          );
        };
      }

      observe = observe;
      disconnect = disconnect;
      unobserve = vi.fn();
      takeRecords = vi.fn().mockReturnValue([]);
      root = null;
      rootMargin = "";
      thresholds = [];
    }
    vi.stubGlobal("IntersectionObserver", IntersectionObserverStub);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            api_schema_version: 11,
            build_id: "production-build",
            csrf_token: "csrf-token",
            state: {
              ...applicationState(),
              accounts: [{
                ...applicationState().accounts[0],
                id: "account-1",
                email: "production@example.test",
              }],
              sync_status: "1 thành công, 0 cần đăng nhập, 0 chưa liên kết, 0 lỗi tạm thời",
            },
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    const wrapper = mount(App, {
      props: { accessToken: "access-token" },
      global: { plugins: [createPinia()] },
      attachTo: document.body,
    });
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(wrapper.find(".glass-overlay").exists()).toBe(false);
    expect(
      wrapper.get("[data-liquid-glass-defs='v3']").element.tagName,
    ).toBe("svg");
    expect(wrapper.find("canvas").exists()).toBe(false);
    expect(wrapper.get(".app-content-header").text()).toContain(
      "Tài khoản Codex",
    );
    const commandLayer = wrapper.get(".app-command-layer");
    expect(commandLayer.attributes("aria-label")).toBe(
      "Điều khiển ứng dụng",
    );
    expect(commandLayer.attributes("data-over-content")).toBe("false");
    expect(commandLayer.attributes("data-scroll-edge")).toBe("soft");
    expect(observe).toHaveBeenCalledOnce();
    notifyIntersection?.(false);
    await nextTick();
    expect(commandLayer.attributes("data-over-content")).toBe("true");
    expect(commandLayer.find(".workspace-tabs").exists()).toBe(true);
    expect(commandLayer.find(".app-system-controls").exists()).toBe(true);
    expect(commandLayer.find(".connection").attributes("data-surface")).toBe(
      "standard",
    );

    expect(wrapper.findAll(".account-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("production@example.test");
    expect(wrapper.text()).not.toContain("Local account manager");
    expect(wrapper.text()).not.toContain("Quản lý local");
    const usageTab = wrapper.get("#usage-tab");
    const failoverTab = wrapper.get("#failover-tab");
    await usageTab.trigger("click");
    expect(usageTab.attributes("aria-selected")).toBe("true");
    expect(commandLayer.attributes("data-scroll-edge")).toBe("hard");
    expect(wrapper.get("#usage-panel").isVisible()).toBe(true);

    await usageTab.trigger("keydown", { key: "ArrowLeft" });
    expect(wrapper.get("#accounts-tab").attributes("aria-selected")).toBe(
      "true",
    );

    const accountsTab = wrapper.get("#accounts-tab");
    await accountsTab.trigger("keydown", { key: "ArrowRight" });
    expect(usageTab.attributes("aria-selected")).toBe("true");
    await usageTab.trigger("keydown", { key: "Home" });
    expect(accountsTab.attributes("aria-selected")).toBe("true");
    await flushPromises();
    expect(document.activeElement?.id).toBe("accounts-tab");
    (accountsTab.element as HTMLElement).focus();
    await accountsTab.trigger("keydown", { key: "End" });
    expect(failoverTab.attributes("aria-selected")).toBe("true");
    await flushPromises();
    expect(document.activeElement?.id).toBe("failover-tab");
    expect(wrapper.get("#failover-panel").isVisible()).toBe(true);
    await failoverTab.trigger("keydown", { key: "Enter" });

    const themeButton = wrapper.get(".header-actions button");
    await themeButton.trigger("click");
    await vi.dynamicImportSettled();
    await wrapper.get('input[name="theme"][value="light"]').trigger("change");
    expect(document.documentElement.dataset.theme).toBe("light");

    wrapper.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("shows a visible offline banner when bootstrap cannot reach the local app", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(
      new Error("sensitive connection detail"),
    ));

    const wrapper = mount(App, {
      props: { accessToken: "access-token" },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    const banner = wrapper.get(".offline-banner");
    expect(banner.attributes("role")).toBe("alert");
    expect(banner.text()).toContain("Mất kết nối");
    expect(banner.text()).not.toContain("sensitive connection detail");

    wrapper.unmount();
  });

  it("requires confirmation before requesting local shutdown", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          api_schema_version: 11,
          build_id: "production-build",
          csrf_token: "csrf-token",
          state: applicationState(),
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", confirm);
    const wrapper = mount(App, {
      props: { accessToken: "access-token" },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    const shutdownButton = wrapper.findAll("button")
      .find((button) => button.text().includes("Tắt ứng dụng"));
    expect(shutdownButton).toBeDefined();
    await shutdownButton!.trigger("click");

    expect(confirm).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledOnce();
    wrapper.unmount();
  });
});
