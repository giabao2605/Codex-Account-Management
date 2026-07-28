import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GlassHybridOverlay from "./GlassHybridOverlay.vue";

interface OverlayVm {
  metrics: {
    scheduledFrames: number;
    completedFrames: number;
    canvasDraws: number;
    gpuDraws: number;
    fallbackDraws: number;
    lastRenderer: "none" | "webgpu" | "2d" | "svg";
  };
  renderOnce: () => void;
}

function canvas2dStub() {
  const gradient = { addColorStop: vi.fn() };
  return {
    clearRect: vi.fn(),
    createLinearGradient: vi.fn(() => gradient),
    createRadialGradient: vi.fn(() => gradient),
    fillRect: vi.fn(),
    setTransform: vi.fn(),
    globalCompositeOperation: "source-over",
    fillStyle: "",
  };
}

describe("GlassHybridOverlay", () => {
  let queuedFrames: FrameRequestCallback[];
  let nextFrameId: number;

  beforeEach(() => {
    queuedFrames = [];
    nextFrameId = 0;
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        queuedFrames.push(callback);
        nextFrameId += 1;
        return nextFrameId;
      }),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 3,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows its SVG optical fallback before the first render frame", () => {
    const wrapper = mount(GlassHybridOverlay, {
      props: { active: true },
    });

    expect(wrapper.get("svg").attributes("data-glass-hybrid-fallback"))
      .toBe("svg");
    expect((wrapper.vm as unknown as OverlayVm).metrics.lastRenderer)
      .toBe("svg");
  });

  it("caps DPR at 1.5 and renders exactly one 2D frame", async () => {
    const context = canvas2dStub();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockImplementation((kind: string) => (
        kind === "2d" ? context : null
      ) as never);
    const wrapper = mount(GlassHybridOverlay, {
      props: {
        active: true,
        width: 100,
        height: 40,
      },
    });

    expect(requestAnimationFrame).toHaveBeenCalledOnce();
    queuedFrames.shift()?.(16);
    await flushPromises();

    const canvas = wrapper.get("canvas").element as HTMLCanvasElement;
    const vm = wrapper.vm as unknown as OverlayVm;
    expect(canvas.width).toBe(150);
    expect(canvas.height).toBe(60);
    expect(context.setTransform).toHaveBeenCalledWith(1.5, 0, 0, 1.5, 0, 0);
    expect(vm.metrics).toMatchObject({
      scheduledFrames: 1,
      completedFrames: 1,
      canvasDraws: 1,
      gpuDraws: 0,
      lastRenderer: "2d",
    });
    expect(queuedFrames).toHaveLength(0);

    await flushPromises();
    expect(requestAnimationFrame).toHaveBeenCalledOnce();
  });

  it("coalesces prop updates and cancels a pending frame when inactive", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(canvas2dStub() as never);
    const wrapper = mount(GlassHybridOverlay, {
      props: { active: true },
    });

    await wrapper.setProps({ intensity: 0.4 });
    await wrapper.setProps({ intensity: 0.8 });
    expect(requestAnimationFrame).toHaveBeenCalledOnce();

    await wrapper.setProps({ active: false });
    const vm = wrapper.vm as unknown as OverlayVm;
    expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
    expect(vm.metrics.lastRenderer).toBe("none");
  });

  it("uses WebGPU for a one-shot render when it is available", async () => {
    const pass = {
      setPipeline: vi.fn(),
      draw: vi.fn(),
      end: vi.fn(),
    };
    const encoder = {
      beginRenderPass: vi.fn(() => pass),
      finish: vi.fn(() => ({ command: true })),
    };
    const device = {
      createShaderModule: vi.fn(() => ({ shader: true })),
      createRenderPipeline: vi.fn(() => ({ pipeline: true })),
      createCommandEncoder: vi.fn(() => encoder),
      queue: { submit: vi.fn() },
    };
    const gpuContext = {
      configure: vi.fn(),
      getCurrentTexture: vi.fn(() => ({
        createView: vi.fn(() => ({ view: true })),
      })),
    };
    const adapter = {
      requestDevice: vi.fn(async () => device),
    };
    let resolveAdapter!: (value: typeof adapter) => void;
    const adapterRequest = new Promise<typeof adapter>((resolve) => {
      resolveAdapter = resolve;
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockImplementation((kind: string) => (
        kind === "webgpu" ? gpuContext : null
      ) as never);
    vi.stubGlobal("navigator", {
      ...window.navigator,
      gpu: {
        getPreferredCanvasFormat: vi.fn(() => "bgra8unorm"),
        requestAdapter: vi.fn(() => adapterRequest),
      },
    });
    const wrapper = mount(GlassHybridOverlay, {
      props: { active: true, width: 80, height: 32 },
    });

    queuedFrames.shift()?.(16);
    await flushPromises();
    const vm = wrapper.vm as unknown as OverlayVm;
    expect(vm.metrics.lastRenderer).toBe("svg");
    expect(wrapper.get("svg").attributes("data-glass-hybrid-fallback"))
      .toBe("svg");

    resolveAdapter(adapter);
    await flushPromises();
    await flushPromises();

    expect(gpuContext.configure).toHaveBeenCalledOnce();
    expect(pass.draw).toHaveBeenCalledWith(3);
    expect(device.queue.submit).toHaveBeenCalledOnce();
    expect(vm.metrics).toMatchObject({
      scheduledFrames: 1,
      completedFrames: 1,
      gpuDraws: 1,
      canvasDraws: 0,
      lastRenderer: "webgpu",
    });
    expect(queuedFrames).toHaveLength(0);
  });

  it("falls back to a local SVG when canvas rendering is unavailable", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(null);
    const wrapper = mount(GlassHybridOverlay, {
      props: { active: true },
    });

    queuedFrames.shift()?.(16);
    await flushPromises();

    const vm = wrapper.vm as unknown as OverlayVm;
    expect(vm.metrics).toMatchObject({
      completedFrames: 1,
      fallbackDraws: 1,
      lastRenderer: "svg",
    });
    expect(wrapper.get("svg").attributes("data-glass-hybrid-fallback"))
      .toBe("svg");
    expect(queuedFrames).toHaveLength(0);
  });

  it("cancels its pending one-shot render when unmounted", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(canvas2dStub() as never);
    const wrapper = mount(GlassHybridOverlay, {
      props: { active: true },
    });

    wrapper.unmount();

    expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
  });
});
