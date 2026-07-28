import { mount } from "@vue/test-utils";
import {
  defineComponent,
  h,
  nextTick,
  ref,
  type Ref,
} from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  resetGlassFilterRuntimeForTests,
  useGlassFilterDescriptors,
} from "@/glass/filterRuntime.ts";
import {
  displacementFor,
  useGlassGeometry,
} from "./useGlassGeometry.ts";
import type {
  GlassMaterial,
  LiquidGlassShape,
} from "./useLiquidGlass.ts";

interface MutableBounds {
  width: number;
  height: number;
}

class ResizeObserverStub {
  static instances: ResizeObserverStub[] = [];
  readonly observe = vi.fn();
  readonly disconnect = vi.fn();
  readonly #callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.#callback = callback;
    ResizeObserverStub.instances.push(this);
  }

  trigger(): void {
    this.#callback([], this as unknown as ResizeObserver);
  }
}

function installCanvasStub(): void {
  const context = {
    createImageData: vi.fn((width: number, height: number) => ({
      data: new Uint8ClampedArray(width * height * 4),
      width,
      height,
      colorSpace: "srgb",
    })),
    putImageData: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => context as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(
    "data:image/png;base64,bGlxdWlkLWdsYXNzLXYz",
  );
}

function installAnimationFrameQueue(): {
  flush: () => void;
  cancel: ReturnType<typeof vi.fn>;
} {
  let nextId = 1;
  const frames = new Map<number, FrameRequestCallback>();
  const cancel = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    const id = nextId;
    nextId += 1;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", cancel);
  return {
    cancel,
    flush() {
      const pending = Array.from(frames.values());
      frames.clear();
      pending.forEach((callback) => callback(16));
    },
  };
}

function rectFrom(bounds: MutableBounds): DOMRect {
  return {
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: bounds.width,
    bottom: bounds.height,
    width: bounds.width,
    height: bounds.height,
    toJSON: () => ({}),
  } as DOMRect;
}

function geometryHarness(
  shape: Ref<LiquidGlassShape>,
  material: Ref<GlassMaterial>,
) {
  return defineComponent({
    setup() {
      const element = ref<HTMLElement | null>(null);
      useGlassGeometry(element, { shape, material });
      return () =>
        h("div", {
          ref: element,
          style: { borderRadius: "18px" },
        });
    },
  });
}

beforeEach(() => {
  ResizeObserverStub.instances = [];
  resetGlassFilterRuntimeForTests();
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  installCanvasStub();
});

afterEach(() => {
  resetGlassFilterRuntimeForTests();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useGlassGeometry", () => {
  it("resolves every material and shape displacement preset", () => {
    expect(displacementFor("regular", "rounded")).toBe(8);
    expect(displacementFor("regular", "panel")).toBe(12);
    expect(displacementFor("clear", "rounded")).toBe(10);
    expect(displacementFor("clear", "panel")).toBe(14);
  });

  it("acquires quantized filters on resize and releases the replaced geometry", () => {
    const animationFrames = installAnimationFrameQueue();
    const descriptors = useGlassFilterDescriptors();
    const bounds: MutableBounds = { width: 121, height: 49 };
    const shape = ref<LiquidGlassShape>("rounded");
    const material = ref<GlassMaterial>("regular");
    const wrapper = mount(geometryHarness(shape, material), {
      attachTo: document.body,
    });
    const element = wrapper.element as HTMLElement;
    element.style.borderTopLeftRadius = "18px";
    vi.spyOn(element, "getBoundingClientRect").mockImplementation(
      () => rectFrom(bounds),
    );

    animationFrames.flush();
    expect(element.dataset.glassNormalMap).toBe(
      "control:120x48:r18:t128x64",
    );
    expect(element.style.getPropertyValue("--glass-displacement")).toBe("8px");
    expect(element.style.getPropertyValue("--glass-filter-url")).toContain(
      descriptors.value[0]?.filterId ?? "missing-filter",
    );
    expect(descriptors.value).toHaveLength(1);
    expect(descriptors.value[0]?.references).toBe(1);

    bounds.width = 121.4;
    bounds.height = 49.4;
    ResizeObserverStub.instances[0]?.trigger();
    animationFrames.flush();
    expect(descriptors.value).toHaveLength(1);
    expect(descriptors.value[0]?.references).toBe(1);
    expect(element.dataset.glassNormalMap).toBe(
      "control:120x48:r18:t128x64",
    );

    bounds.width = 125;
    bounds.height = 53;
    ResizeObserverStub.instances[0]?.trigger();
    animationFrames.flush();
    expect(descriptors.value).toHaveLength(1);
    expect(element.dataset.glassNormalMap).toBe(
      "control:124x52:r18:t128x64",
    );
    expect(descriptors.value[0]?.key).toContain("control:124x52:r18");

    wrapper.unmount();
    expect(descriptors.value).toHaveLength(0);
    expect(ResizeObserverStub.instances[0]?.disconnect).toHaveBeenCalledOnce();
  });

  it("updates displacement by material and cancels scheduled work on unmount", async () => {
    const animationFrames = installAnimationFrameQueue();
    const descriptors = useGlassFilterDescriptors();
    const bounds: MutableBounds = { width: 120, height: 48 };
    const shape = ref<LiquidGlassShape>("rounded");
    const material = ref<GlassMaterial>("regular");
    const wrapper = mount(geometryHarness(shape, material), {
      attachTo: document.body,
    });
    const element = wrapper.element as HTMLElement;
    element.style.borderTopLeftRadius = "18px";
    vi.spyOn(element, "getBoundingClientRect").mockImplementation(
      () => rectFrom(bounds),
    );
    animationFrames.flush();

    material.value = "clear";
    await nextTick();
    animationFrames.flush();
    expect(element.style.getPropertyValue("--glass-displacement")).toBe("10px");
    expect(descriptors.value).toHaveLength(1);
    expect(descriptors.value[0]?.displacement).toBe(10);

    ResizeObserverStub.instances[0]?.trigger();
    wrapper.unmount();
    expect(animationFrames.cancel).toHaveBeenCalledOnce();
    expect(descriptors.value).toHaveLength(0);
  });

  it("uses capsule geometry and panel or rounded fallback radii", async () => {
    const animationFrames = installAnimationFrameQueue();
    const bounds: MutableBounds = { width: 120, height: 48 };
    const shape = ref<LiquidGlassShape>("capsule");
    const material = ref<GlassMaterial>("regular");
    vi.stubGlobal("getComputedStyle", () => ({
      borderTopLeftRadius: "",
    }));
    const wrapper = mount(geometryHarness(shape, material), {
      attachTo: document.body,
    });
    const element = wrapper.element as HTMLElement;
    vi.spyOn(element, "getBoundingClientRect").mockImplementation(
      () => rectFrom(bounds),
    );
    animationFrames.flush();
    expect(element.dataset.glassNormalMap).toBe(
      "control:120x48:r24:t128x64",
    );

    shape.value = "panel";
    await nextTick();
    animationFrames.flush();
    expect(element.dataset.glassNormalMap).toBe(
      "panel:120x48:r24:t256x192",
    );
    expect(element.style.getPropertyValue("--glass-displacement")).toBe("12px");

    material.value = "clear";
    await nextTick();
    animationFrames.flush();
    expect(element.style.getPropertyValue("--glass-displacement")).toBe("14px");

    shape.value = "rounded";
    await nextTick();
    animationFrames.flush();
    expect(element.dataset.glassNormalMap).toBe(
      "control:120x48:r16:t128x64",
    );
    expect(element.style.getPropertyValue("--glass-displacement")).toBe("10px");
    wrapper.unmount();
  });

  it("does not acquire filters for disconnected or zero-sized elements", () => {
    const animationFrames = installAnimationFrameQueue();
    const descriptors = useGlassFilterDescriptors();
    const shape = ref<LiquidGlassShape>("rounded");
    const material = ref<GlassMaterial>("regular");
    const detached = mount(geometryHarness(shape, material));
    animationFrames.flush();
    expect(descriptors.value).toHaveLength(0);
    detached.unmount();

    const zeroSized = mount(geometryHarness(shape, material), {
      attachTo: document.body,
    });
    vi.spyOn(
      zeroSized.element as HTMLElement,
      "getBoundingClientRect",
    ).mockReturnValue(rectFrom({ width: 0, height: 0 }));
    animationFrames.flush();
    expect(descriptors.value).toHaveLength(0);
    zeroSized.unmount();
  });
});
