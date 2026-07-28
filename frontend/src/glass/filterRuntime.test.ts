import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  acquireRuntimeGlassFilter,
  resetGlassFilterRuntimeForTests,
  useGlassFilterDescriptors,
} from "./filterRuntime.ts";

const request = Object.freeze({
  kind: "control" as const,
  width: 121,
  height: 49,
  radius: 17,
});

function installCanvasStub(): { createImageData: ReturnType<typeof vi.fn> } {
  const createImageData = vi.fn((width: number, height: number) => ({
    data: new Uint8ClampedArray(width * height * 4),
    width,
    height,
    colorSpace: "srgb",
  }));
  const context = {
    createImageData,
    putImageData: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => context as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(
    "data:image/png;base64,bGlxdWlkLWdsYXNzLXYz",
  );
  return { createImageData };
}

beforeEach(() => {
  resetGlassFilterRuntimeForTests();
});

afterEach(() => {
  resetGlassFilterRuntimeForTests();
  vi.restoreAllMocks();
});

describe("Liquid Glass v3 filter runtime", () => {
  it("publishes immutable shared descriptors and cleans up on final release", () => {
    const { createImageData } = installCanvasStub();
    const descriptors = useGlassFilterDescriptors();
    expect(Object.isFrozen(descriptors.value)).toBe(true);

    const first = acquireRuntimeGlassFilter(request, 8);
    const firstSnapshot = descriptors.value;
    const second = acquireRuntimeGlassFilter(request, 8);

    expect(first.key).toBe("control:120x48:r18:t128x64:d8");
    expect(first.filterId).toContain("liquid-glass-v3-control-120x48-r18");
    expect(first.dataUrl).toMatch(/^data:image\/png;base64,/);
    expect(first.map).toBe(second.map);
    expect(createImageData).toHaveBeenCalledTimes(1);
    expect(createImageData).toHaveBeenCalledWith(128, 64);
    expect(firstSnapshot).toHaveLength(1);
    expect(firstSnapshot[0]?.references).toBe(1);
    expect(descriptors.value[0]).toEqual({
      key: first.key,
      filterId: first.filterId,
      dataUrl: first.dataUrl,
      displacement: 8,
      references: 2,
    });
    expect(Object.isFrozen(descriptors.value)).toBe(true);
    expect(Object.isFrozen(descriptors.value[0])).toBe(true);

    first.release();
    first.release();
    expect(descriptors.value[0]?.references).toBe(1);
    second.release();
    expect(descriptors.value).toEqual([]);
    expect(Object.isFrozen(descriptors.value)).toBe(true);
  });

  it("keeps displacement variants distinct while reusing the immutable map", () => {
    installCanvasStub();
    const descriptors = useGlassFilterDescriptors();
    const regular = acquireRuntimeGlassFilter(request, 8);
    const clear = acquireRuntimeGlassFilter(request, 10);

    expect(regular.map).toBe(clear.map);
    expect(regular.key).not.toBe(clear.key);
    expect(regular.filterId).not.toBe(clear.filterId);
    expect(descriptors.value.map((entry) => entry.displacement)).toEqual([8, 10]);

    regular.release();
    expect(descriptors.value.map((entry) => entry.displacement)).toEqual([10]);
    clear.release();
    expect(descriptors.value).toHaveLength(0);
  });

  it("keeps a valid solid fallback descriptor when canvas encoding is unavailable", () => {
    installCanvasStub();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValueOnce(null);
    const descriptors = useGlassFilterDescriptors();
    const lease = acquireRuntimeGlassFilter({
      ...request,
      width: 200,
    }, 8);

    expect(lease.dataUrl).toBe("");
    expect(descriptors.value[0]?.dataUrl).toBe("");
    lease.release();
    expect(descriptors.value).toHaveLength(0);
  });

  it("does not let a stale lease remove a new descriptor after test cleanup", () => {
    installCanvasStub();
    const descriptors = useGlassFilterDescriptors();
    const stale = acquireRuntimeGlassFilter(request, 8);
    resetGlassFilterRuntimeForTests();
    const current = acquireRuntimeGlassFilter(request, 8);

    stale.release();
    expect(descriptors.value).toHaveLength(1);
    expect(descriptors.value[0]?.references).toBe(1);
    current.release();
    expect(descriptors.value).toHaveLength(0);
  });
});
