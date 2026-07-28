import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalApiClient } from "@/api/client.ts";
import { applicationState, tokenUsage } from "@/test/fixtures.ts";
import { useSessionStore } from "@/stores/session.ts";
import { useUsageStore } from "@/stores/usage.ts";
import UsagePanel from "./UsagePanel.vue";

describe("UsagePanel", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    setActivePinia(createPinia());
  });

  function mountPanel() {
    const session = useSessionStore();
    session.state = applicationState();
    const tokenUsageRequest = vi.fn().mockResolvedValue(tokenUsage());
    vi.spyOn(session, "getClient").mockReturnValue({
      tokenUsage: tokenUsageRequest,
    } as unknown as LocalApiClient);
    return {
      tokenUsageRequest,
      wrapper: mount(UsagePanel, { attachTo: document.body }),
    };
  }

  it("owns the token fetch and renders the all-account contract", async () => {
    const { tokenUsageRequest, wrapper } = mountPanel();
    await flushPromises();

    expect(tokenUsageRequest).toHaveBeenCalledTimes(1);
    expect(wrapper.find("h2").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Dữ liệu token");
    expect(wrapper.get(".usage-account-trigger").text())
      .toContain("Tất cả tài khoản");
    expect(wrapper.find(".all-account-statistics > .usage-heading").exists())
      .toBe(false);
    expect(wrapper.text()).toContain("1 mới");
    expect(wrapper.text()).toContain("1 chưa có");
    expect(wrapper.findAll("thead th").map((cell) => cell.text())).toEqual([
      "Tài khoản",
      "Gói",
      "Lifetime",
      "Peak/ngày",
      "Longest task",
      "Current streak",
      "Longest streak",
      "Quota còn lại",
      "Trạng thái",
      "Reset quota",
      "Đồng bộ cuối",
    ]);
    expect(wrapper.findAll(".all-token-total")).toHaveLength(4);
    expect(wrapper.get(".all-token-total span").text())
      .toBe("Hôm qua · 22/07/2026");
    expect(wrapper.find(".quota-summary").exists()).toBe(true);
  });

  it("separates standard usage content from the liquid control layer", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();

    const standardContent = wrapper.findAll(
      ".solid-content-card, .solid-content-table",
    );
    expect(standardContent.length).toBeGreaterThan(0);
    expect(
      standardContent.every(
        (surface) => surface.attributes("data-material") === "standard",
      ),
    ).toBe(true);
    expect(wrapper.get(".usage-account-trigger").classes())
      .toContain("glass-button");

    const refreshControl = wrapper.get(".usage-refresh-control.glass-button");
    expect(refreshControl.attributes("data-material-layer")).toBe("control");

    const heatmapModeControl = wrapper.get(".heatmap-mode-control");
    expect(heatmapModeControl.attributes("data-material-layer")).toBe("control");
    expect(heatmapModeControl.classes()).toContain("glass-segmented-control");
    expect(heatmapModeControl.attributes("data-glass-container")).toBeDefined();

    const usage = useUsageStore();
    usage.selectedAccountId = "1111111111111111";
    await wrapper.vm.$nextTick();
    expect(
      wrapper.findAll(".solid-content-card").every(
        (surface) => surface.classes().includes("standard-surface")
          && surface.attributes("data-material") === "standard",
      ),
    ).toBe(true);
  });

  it("renders single-account details and the matching quota card", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();
    const usage = useUsageStore();

    usage.selectedAccountId = "1111111111111111";
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).toContain("alpha@example.test");
    expect(wrapper.text()).toContain("Plus");
    expect(wrapper.text()).toContain("Peak tokens");
    expect(wrapper.text()).toContain("Longest task");
    expect(wrapper.text()).toContain("Current streak");
    expect(wrapper.text()).toContain("Longest streak");
    expect(wrapper.get(".token-kpis .usage-metric-card span").text())
      .toBe("Hôm qua · 22/07/2026");
    expect(wrapper.find(".single-quota-card").text()).toContain("82%");
    expect(wrapper.find(".all-account-statistics").exists()).toBe(false);
  });

  it("renders a deterministic zero heatmap and supports roving keyboard focus", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();
    const usage = useUsageStore();
    if (!usage.data) throw new Error("Expected loaded usage fixture");
    usage.data = {
      ...usage.data,
      aggregate: {
        ...usage.data.aggregate,
        daily_buckets: [],
      },
    };
    await wrapper.vm.$nextTick();

    const cells = wrapper.findAll<HTMLButtonElement>(".heat-cell");
    expect(cells).toHaveLength(365);
    expect(cells.filter((cell) => cell.attributes("tabindex") === "0")).toHaveLength(1);
    expect(cells.every((cell) => cell.attributes("data-start-date"))).toBe(true);
    expect(cells.every((cell) => cell.attributes("aria-label")?.includes("token"))).toBe(true);
    expect(wrapper.text()).toContain("Chưa có hoạt động trong 12 tháng này.");

    const active = cells.find((cell) => cell.attributes("tabindex") === "0");
    await active?.trigger("keydown", { key: "Home" });
    expect(document.activeElement).toBe(wrapper.findAll(".heat-cell")[0]?.element);
    await wrapper.findAll(".heat-cell")[0]?.trigger("keydown", { key: "End" });
    expect(document.activeElement).toBe(wrapper.findAll(".heat-cell").at(-1)?.element);
    await wrapper.findAll(".heat-cell").at(-1)?.trigger("keydown", { key: "ArrowLeft" });
    expect(document.activeElement).toBe(wrapper.findAll(".heat-cell").at(-2)?.element);
  });

  it("shows one immediate tooltip at the pointer without a native title", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();
    const cell = wrapper.findAll(".heat-cell").at(-1);
    if (!cell) throw new Error("Expected a heatmap cell");

    expect(cell.attributes("title")).toBeUndefined();
    expect(wrapper.find("#heatmap-tooltip").exists()).toBe(false);

    cell.element.dispatchEvent(new MouseEvent("pointerenter", {
      bubbles: true,
      clientX: 320,
      clientY: 240,
    }));
    await wrapper.vm.$nextTick();

    const tooltip = document.querySelector<HTMLElement>(
      "#heatmap-pointer-tooltip",
    );
    if (!tooltip) throw new Error("Expected the pointer tooltip");
    expect(tooltip.parentElement).toBe(document.body);
    expect(tooltip.textContent?.trim()).toBe(cell.attributes("aria-label"));
    expect(tooltip.style.left).toBe("332px");
    expect(tooltip.style.top).toBe("228px");

    cell.element.dispatchEvent(new MouseEvent("pointermove", {
      bubbles: true,
      clientX: 60,
      clientY: 60,
    }));
    await wrapper.vm.$nextTick();
    expect(tooltip.style.left).toBe("72px");
    expect(tooltip.style.top).toBe("48px");

    cell.element.dispatchEvent(new MouseEvent("pointerenter", {
      bubbles: true,
      clientX: window.innerWidth - 10,
      clientY: 240,
    }));
    await wrapper.vm.$nextTick();
    expect(tooltip.classList).toContain("is-left");
  });

  it("keeps null buckets unavailable instead of drawing zero activity", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();
    const usage = useUsageStore();
    if (!usage.data) throw new Error("Expected loaded usage fixture");
    usage.data = {
      ...usage.data,
      aggregate: {
        ...usage.data.aggregate,
        daily_buckets: null,
      },
    };
    await wrapper.vm.$nextTick();

    expect(wrapper.findAll(".heat-cell")).toHaveLength(0);
    expect(wrapper.text()).toContain("Dữ liệu heatmap chưa khả dụng");
    expect(wrapper.text()).not.toContain("Chưa có hoạt động trong 12 tháng này.");
  });

  it("renders weekly and cumulative ranges as seven-row visual columns", async () => {
    const { wrapper } = mountPanel();
    await flushPromises();
    const usage = useUsageStore();

    for (const mode of ["weekly", "cumulative"] as const) {
      usage.heatmapMode = mode;
      await wrapper.vm.$nextTick();

      const cells = wrapper.findAll(".heat-cell");
      expect([52, 53]).toContain(cells.length);
      expect(wrapper.findAll(".heat-cell-segment")).toHaveLength(
        cells.length * 7,
      );
      expect(
        wrapper.get(".heatmap-grid").element.nextElementSibling,
      ).toBe(wrapper.get(".heatmap-months").element);
    }
  });
});
