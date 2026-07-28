import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GlassLab from "./GlassLab.vue";

const sceneIds = [
  "stripe",
  "checkerboard",
  "text",
  "white",
  "black",
  "color",
  "media",
] as const;

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeEach(() => {
  window.history.replaceState({}, "", "/?glass-lab=1");
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(() => {
  document.body.innerHTML = "";
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("GlassLab", () => {
  it("is unavailable unless the test-only query parameter is enabled", () => {
    window.history.replaceState({}, "", "/");
    const wrapper = mount(GlassLab);

    expect(wrapper.find('[data-testid="glass-lab"]').exists()).toBe(false);
  });

  it("renders every optical scene with a stable v3 contract", () => {
    const wrapper = mount(GlassLab);

    expect(wrapper.get('[data-testid="glass-lab"]').attributes(
      "data-glass-lab",
    )).toBe("v3");
    for (const sceneId of sceneIds) {
      const scene = wrapper.get(
        `[data-testid="glass-lab-background-${sceneId}"]`,
      );
      expect(scene.find(
        `[data-testid="glass-lab-${sceneId}-regular"]`,
      ).exists()).toBe(true);
    }
    expect(wrapper.findAll('[data-testid^="glass-lab-background-"]'))
      .toHaveLength(sceneIds.length);
  });

  it("keeps Clear material in the media scene and exposes all shape families", () => {
    const wrapper = mount(GlassLab);

    const clear = wrapper.get('[data-testid="glass-lab-media-clear"]');
    expect(clear.attributes("data-glass-material")).toBe("clear");
    expect(clear.attributes("data-glass-context")).toBe("media");
    expect(wrapper.findAll('[data-glass-material="clear"]')).toHaveLength(1);
    expect(
      wrapper.get('[data-testid="glass-lab-shape-rounded"]').attributes(
        "data-glass-shape",
      ),
    ).toBe("rounded");
    expect(
      wrapper.get('[data-testid="glass-lab-shape-capsule"]').attributes(
        "data-glass-shape",
      ),
    ).toBe("capsule");
    expect(
      wrapper.get('[data-testid="glass-lab-shape-panel"]').attributes(
        "data-glass-shape",
      ),
    ).toBe("panel");
  });

  it("records the reference sources and measurement date", () => {
    const wrapper = mount(GlassLab);
    const references = wrapper.get('[data-testid="glass-lab-reference"]');
    const links = references.findAll("a").map((link) => link.attributes("href"));

    expect(links).toEqual([
      "https://developer.apple.com/design/human-interface-guidelines/materials",
      "https://developer.apple.com/videos/play/wwdc2026/269/",
    ]);
    expect(references.get("time").attributes("datetime")).toBe("2026-07-27");
    expect(references.text()).toContain("phép đo suy ra");
  });

  it("tracks mouse, touch, pen, and keyboard input without an idle loop", async () => {
    const wrapper = mount(GlassLab);
    const lab = wrapper.get('[data-testid="glass-lab"]');
    const mode = wrapper.get('[data-testid="glass-lab-input-mode"]');

    await lab.trigger("pointerdown", { pointerType: "touch" });
    expect(mode.text()).toContain("touch");
    await lab.trigger("pointerdown", { pointerType: "pen" });
    expect(mode.text()).toContain("pen");
    await lab.trigger("pointerdown", { pointerType: "mouse" });
    expect(mode.text()).toContain("mouse");
    await lab.trigger("keydown", { key: "Tab" });
    expect(mode.text()).toContain("keyboard");
  });

  it("opens a labelled morph destination from a semantic source", async () => {
    const wrapper = mount(GlassLab, { attachTo: document.body });
    const trigger = wrapper.get('[data-testid="glass-lab-morph-trigger"]');

    expect(trigger.attributes("aria-expanded")).toBe("false");
    await trigger.trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(
      wrapper.get('[data-testid="glass-lab-morph-trigger"]')
        .attributes("aria-expanded"),
    ).toBe("true");
    const destination = wrapper.get(
      '[data-testid="glass-lab-morph-destination"]',
    );
    expect(destination.text()).toContain("Bề mặt đích");
    const panel = destination.element.closest(".glass-popover-panel");
    expect(panel?.getAttribute("role")).toBe("dialog");
    expect(panel?.getAttribute("data-glass-morph-id")).toBe("glass-lab-morph");
  });
});
