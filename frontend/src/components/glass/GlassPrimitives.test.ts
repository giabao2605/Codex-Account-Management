import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import GlassButton from "./GlassButton.vue";
import GlassDialog from "./GlassDialog.vue";
import GlassGroup from "./GlassGroup.vue";
import GlassPopover from "./GlassPopover.vue";
import GlassSegmentedControl from "./GlassSegmentedControl.vue";
import GlassSurface from "./GlassSurface.vue";
import LiquidGlassDefs from "./LiquidGlassDefs.vue";
import SurfaceActionButton from "./SurfaceActionButton.vue";

enableAutoUnmount(afterEach);

afterEach(() => {
  document.body.innerHTML = "";
  delete document.documentElement.dataset.effects;
  vi.unstubAllGlobals();
});

describe("Liquid Glass primitives", () => {
  it("renders a semantic v3 surface with independent material context", () => {
    const wrapper = mount(GlassSurface, {
      props: {
        as: "nav",
        level: "prominent",
        shape: "capsule",
        depth: "thin",
        tint: "accent",
        interactive: true,
        ariaLabel: "Điều hướng",
        material: "regular",
        context: "text",
        concentric: true,
      },
      slots: { default: "Nội dung" },
    });

    expect(wrapper.element.tagName).toBe("NAV");
    expect(wrapper.classes()).toContain("glass-surface");
    expect(wrapper.attributes("data-glass-level")).toBe("prominent");
    expect(wrapper.attributes("data-glass-version")).toBe("3");
    expect(wrapper.attributes("data-glass-shape")).toBe("capsule");
    expect(wrapper.attributes("data-glass-depth")).toBe("thin");
    expect(wrapper.attributes("data-glass-tint")).toBe("accent");
    expect(wrapper.attributes("data-glass-material")).toBe("regular");
    expect(wrapper.attributes("data-glass-context")).toBe("text");
    expect(wrapper.attributes("data-glass-concentric")).toBe("");
    expect(wrapper.attributes("data-material-layer")).toBe("control");
    expect(wrapper.attributes("aria-label")).toBe("Điều hướng");
  });

  it("provides one registered render scope for a labelled group", () => {
    const wrapper = mount(GlassGroup, {
      props: {
        ariaLabel: "Bộ lọc",
        level: "lite",
        shape: "capsule",
        groupId: "filters",
        mergeDistance: 12,
        renderer: "auto",
      },
      slots: { default: "<button>Lọc</button>" },
    });

    expect(wrapper.attributes("role")).toBe("group");
    expect(wrapper.attributes("aria-label")).toBe("Bộ lọc");
    expect(wrapper.classes()).toContain("glass-group");
    expect(wrapper.attributes("data-glass-container")).toBe("");
    expect(wrapper.attributes("data-glass-group-id")).toBe("filters");
    expect(wrapper.attributes("data-glass-merge-distance")).toBe("12");
    expect(wrapper.attributes("data-glass-renderer")).toBe("auto");
    expect(wrapper.findAll(".glass-surface")).toHaveLength(1);
  });

  it("mounts the v3 SVG filter registry and never creates a global canvas", () => {
    const defs = mount(LiquidGlassDefs);

    expect(defs.attributes("data-liquid-glass-defs")).toBe("v3");
    expect(defs.find("#liquid-glass-capsule").exists()).toBe(true);
    expect(defs.find("#liquid-glass-rounded").exists()).toBe(true);
    expect(defs.find("#liquid-glass-panel").exists()).toBe(true);
    expect(defs.findAll("feDisplacementMap")).toHaveLength(3);
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("renders actions inside glass without creating a nested boundary", () => {
    const wrapper = mount(GlassSurface, {
      slots: {
        default: () => h(
          SurfaceActionButton,
          { tone: "danger" },
          () => "Xóa",
        ),
      },
    });

    const action = wrapper.get("button");
    expect(action.classes()).toContain("surface-action-button");
    expect(action.attributes("data-surface-action")).toBe("");
    expect(action.attributes("data-glass-version")).toBeUndefined();
    expect(wrapper.findAll("[data-glass-version='3']")).toHaveLength(1);
  });

  it("uses rounded desktop buttons by default and exposes morph identity", () => {
    const wrapper = mount(GlassButton, {
      props: { morphId: "appearance" },
      slots: { default: "Giao diện" },
    });

    expect(wrapper.attributes("data-glass-version")).toBe("3");
    expect(wrapper.attributes("data-glass-shape")).toBe("rounded");
    expect(wrapper.attributes("data-glass-morph-id")).toBe("appearance");
  });

  it("resolves automatic depth, clear-media, tint, and busy branches", async () => {
    const surface = mount(GlassSurface, {
      props: {
        level: "lite",
        depth: "auto",
        material: "clear",
        context: "text",
        shape: "rounded",
        concentric: false,
      },
    });
    expect(surface.attributes("data-glass-depth")).toBe("thin");
    expect(surface.attributes("data-glass-material")).toBe("regular");
    expect(surface.attributes("data-glass-concentric")).toBeUndefined();
    await surface.trigger("pointermove");
    expect(surface.attributes("data-glass-pressed")).toBeUndefined();

    await surface.setProps({ level: "solid" });
    expect(surface.attributes("data-glass-depth")).toBe("thick");
    await surface.setProps({ depth: "regular" });
    expect(surface.attributes("data-glass-depth")).toBe("regular");

    const button = mount(GlassButton, {
      props: {
        variant: "danger",
        material: "clear",
        context: "media",
        busy: true,
      },
      slots: { default: "Xóa" },
    });
    expect(button.attributes("data-glass-depth")).toBe("regular");
    expect(button.attributes("data-glass-tint")).toBe("danger");
    expect(button.attributes("data-glass-material")).toBe("clear");
    expect(button.attributes("disabled")).toBeDefined();
    expect(button.get(".sr-only").text()).toBe("Đang xử lý");
  });

  it("updates pointer variables on a local animation frame without an idle loop", async () => {
    let queuedFrame: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      queuedFrame = callback;
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    document.documentElement.dataset.effects = "full";
    const wrapper = mount(GlassButton, {
      attachTo: document.body,
      slots: { default: "Lưu" },
    });

    wrapper.element.dispatchEvent(new MouseEvent("pointermove", {
      bubbles: true,
      clientX: 12,
      clientY: 8,
    }));
    await wrapper.vm.$nextTick();
    expect(queuedFrame).toBeTypeOf("function");
    expect(
      (window as Window & {
        __otpLiquidGlassDebug?: { pendingFrames: number };
      }).__otpLiquidGlassDebug?.pendingFrames,
    ).toBe(1);

    queuedFrame?.(16);
    expect(wrapper.element.getAttribute("style")).toContain("--glass-pointer-x");
    expect(
      (window as Window & {
        __otpLiquidGlassDebug?: { pendingFrames: number };
      }).__otpLiquidGlassDebug?.pendingFrames,
    ).toBe(0);
    expect(wrapper.attributes("data-glass-input")).toBe("mouse");
  });

  it("supports single selection and roving keyboard focus", async () => {
    const wrapper = mount(GlassSegmentedControl, {
      attachTo: document.body,
      props: {
        modelValue: "accounts",
        label: "Khu vực",
        mode: "tabs",
        options: [
          { value: "accounts", label: "Tài khoản", controls: "accounts-panel" },
          { value: "usage", label: "Sử dụng", controls: "usage-panel" },
        ],
      },
    });
    const buttons = wrapper.findAll("button");

    expect(buttons[0]!.attributes("role")).toBe("tab");
    expect(buttons[0]!.attributes("aria-selected")).toBe("true");
    expect(wrapper.find("[data-glass-active-lens]").exists()).toBe(true);
    expect(wrapper.get(".glass-group").attributes("data-glass-segmented")).toBe("v3");
    expect(wrapper.get("[data-glass-active-lens]").attributes(
      "data-glass-motion",
    )).toBe("compositor-transform");
    expect(wrapper.get("[data-glass-active-lens]").attributes(
      "data-glass-layout-id",
    )).toContain("active-lens");
    expect(
      wrapper.get(".glass-group").attributes("data-glass-interactive"),
    ).toBeUndefined();
    expect(wrapper.find("[data-glass-active-lens]").attributes("style"))
      .toContain("--glass-active-column: 1");
    await wrapper.setProps({ modelValue: "usage" });
    expect(wrapper.find("[data-glass-active-lens]").attributes("style"))
      .toContain("--glass-active-offset: 100%");
    await buttons[0]!.trigger("keydown", { key: "ArrowRight" });

    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["usage"]);
    expect(document.activeElement).toBe(buttons[1]!.element);
  });

  it("closes a popover with Escape and restores trigger focus", async () => {
    const wrapper = mount(GlassPopover, {
      attachTo: document.body,
      props: {
        open: true,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });
    const trigger = wrapper.get(".glass-popover-anchor button");
    expect(wrapper.get(".glass-popover-anchor").attributes(
      "data-glass-morph-id",
    )).toBe("appearance");
    expect(wrapper.get(".glass-popover-panel").attributes(
      "data-glass-morph-id",
    )).toBe("appearance");
    expect(wrapper.get(".glass-popover-anchor").attributes(
      "data-glass-layout-id",
    )).toBe("appearance");
    expect(wrapper.get(".glass-popover-panel").attributes(
      "data-glass-layout-id",
    )).toBe("appearance");
    expect(wrapper.get(".glass-popover-panel").attributes(
      "data-glass-content-reveal",
    )).toBe("42");
    (trigger.element as HTMLElement).focus();
    document.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
    }));

    expect(wrapper.emitted("update:open")?.at(-1)).toEqual([false]);
    await wrapper.setProps({ open: false });
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(document.activeElement).toBe(trigger.element);
  });

  it("closes a popover when its transparent morph shell is clicked", () => {
    const wrapper = mount(GlassPopover, {
      attachTo: document.body,
      props: {
        open: true,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });

    wrapper.get(".glass-morph-shell").element.dispatchEvent(
      new MouseEvent("pointerdown", { bubbles: true }),
    );

    expect(wrapper.emitted("update:open")?.at(-1)).toEqual([false]);
  });

  it("loads motion before emitting the popover open state", async () => {
    const wrapper = mount(GlassPopover, {
      props: {
        open: false,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });

    wrapper.get(".glass-popover-anchor button").element.dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
    expect(wrapper.emitted("update:open")).toBeUndefined();

    await vi.dynamicImportSettled();
    await flushPromises();
    expect(wrapper.emitted("update:open")?.at(-1)).toEqual([true]);

    await wrapper.setProps({ open: true });
    expect(wrapper.get(".glass-morph-shell").attributes("style"))
      .not.toContain("opacity: 0");
  });

  it("exposes a modal dialog contract and closes on Escape", async () => {
    const wrapper = mount(GlassDialog, {
      attachTo: document.body,
      props: {
        open: true,
        title: "Nhập tài khoản",
        morphId: "import-dialog",
      },
      slots: {
        trigger: "<button>Thêm tài khoản</button>",
        default: "<input aria-label='Dữ liệu'>",
        actions: "<button>Hủy</button>",
      },
    });

    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.getAttribute("aria-modal")).toBe("true");
    expect(dialog?.getAttribute("data-glass-morph-id")).toBe("import-dialog");
    expect(dialog?.getAttribute("data-glass-layout-id")).toBe("import-dialog");
    expect(dialog?.getAttribute("data-glass-content-reveal")).toBe("42");
    expect(dialog?.textContent).toContain("Nhập tài khoản");
    expect(wrapper.get("[data-glass-morph-source='dialog']").attributes(
      "data-glass-layout-id",
    )).toBe("import-dialog");
    dialog?.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
    }));
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("uses opacity-only motion for reduced motion surfaces", () => {
    document.documentElement.dataset.glassMotion = "reduced";
    const popover = mount(GlassPopover, {
      props: {
        open: true,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });
    const dialog = mount(GlassDialog, {
      props: {
        open: true,
        title: "Nhập tài khoản",
        morphId: "import-dialog",
      },
      slots: { default: "<input aria-label='Dữ liệu'>" },
    });

    expect(popover.get(".glass-popover-panel").attributes(
      "data-glass-motion-mode",
    )).toBe("reduced");
    expect(popover.get(".glass-popover-panel").attributes(
      "data-glass-layout-id",
    )).toBeUndefined();
    expect(document.body.querySelector(".glass-dialog")?.getAttribute(
      "data-glass-motion-mode",
    )).toBe("reduced");
    expect(document.body.querySelector(".glass-dialog")?.getAttribute(
      "data-glass-layout-id",
    )).toBeNull();

    popover.unmount();
    dialog.unmount();
    delete document.documentElement.dataset.glassMotion;
  });

  it("mounts one-shot hybrid overlays only in active lens and morph scopes", () => {
    vi.stubGlobal("CSS", { supports: () => true });
    vi.stubGlobal("navigator", Object.assign(
      Object.create(window.navigator) as Navigator,
      { gpu: {} },
    ));
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const pinia = createPinia();
    setActivePinia(pinia);
    const segmented = mount(GlassSegmentedControl, {
      global: { plugins: [pinia] },
      props: {
        modelValue: "accounts",
        label: "Khu vực",
        options: [
          { value: "accounts", label: "Tài khoản" },
          { value: "usage", label: "Sử dụng" },
        ],
      },
    });
    const popover = mount(GlassPopover, {
      global: { plugins: [pinia] },
      props: {
        open: true,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });
    const dialog = mount(GlassDialog, {
      global: { plugins: [pinia] },
      props: {
        open: true,
        title: "Nhập tài khoản",
        morphId: "import-dialog",
      },
      slots: { default: "<input aria-label='Dữ liệu'>" },
    });

    expect(segmented.findAll(".glass-hybrid-overlay")).toHaveLength(1);
    expect(popover.findAll(".glass-hybrid-overlay")).toHaveLength(1);
    expect(document.body.querySelectorAll(
      ".glass-dialog .glass-hybrid-overlay",
    )).toHaveLength(1);

    segmented.unmount();
    popover.unmount();
    dialog.unmount();
  });

  it("settles on the latest popover state during rapid interruption", async () => {
    const wrapper = mount(GlassPopover, {
      attachTo: document.body,
      props: {
        open: false,
        label: "Tùy chỉnh",
        morphId: "appearance",
      },
      slots: {
        trigger: "<button>Mở</button>",
        default: "<button>Trong popover</button>",
      },
    });
    const trigger = wrapper.get(".glass-popover-anchor button");
    (trigger.element as HTMLElement).focus();

    const opening = wrapper.setProps({ open: true });
    const closing = wrapper.setProps({ open: false });
    const reopening = wrapper.setProps({ open: true });
    await Promise.all([opening, closing, reopening]);
    await wrapper.vm.$nextTick();

    expect(wrapper.findAll(".glass-popover-panel")).toHaveLength(1);
    expect(document.activeElement).toBe(
      wrapper.get(".glass-popover-panel button").element,
    );

    await wrapper.setProps({ open: false });
    wrapper.unmount();
    expect(document.body.querySelector(".glass-popover-panel")).toBeNull();
  });
});
