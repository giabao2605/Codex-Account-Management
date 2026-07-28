import { describe, expect, it } from "vitest";

import {
  DEFAULT_NORMAL_MAP_CACHE_LIMIT,
  NormalMapCache,
  generateNormalMap,
  makeNormalMapKey,
  quantizeNormalMapGeometry,
} from "./normalMap.ts";
import { GlassFilterRegistry } from "./filterRegistry.ts";

describe("Liquid Glass v3 normal-map geometry", () => {
  it("quantizes geometry and selects the fixed texture budget for each surface kind", () => {
    expect(
      quantizeNormalMapGeometry({
        kind: "control",
        width: 121,
        height: 49,
        radius: 23,
      }),
    ).toEqual({
      kind: "control",
      width: 120,
      height: 48,
      radius: 24,
      textureWidth: 128,
      textureHeight: 64,
    });

    expect(
      quantizeNormalMapGeometry({
        kind: "panel",
        width: 319,
        height: 201,
        radius: 21,
      }),
    ).toEqual({
      kind: "panel",
      width: 320,
      height: 200,
      radius: 22,
      textureWidth: 256,
      textureHeight: 192,
    });
  });

  it("rejects non-finite and non-positive dimensions and clamps radius to the shape", () => {
    expect(() =>
      quantizeNormalMapGeometry({
        kind: "control",
        width: 0,
        height: 48,
        radius: 12,
      }),
    ).toThrow("width");
    expect(() =>
      quantizeNormalMapGeometry({
        kind: "control",
        width: 120,
        height: Number.NaN,
        radius: 12,
      }),
    ).toThrow("height");

    expect(
      quantizeNormalMapGeometry({
        kind: "control",
        width: 40,
        height: 20,
        radius: 99,
      }).radius,
    ).toBe(10);
  });

  it("encodes signed outward normals in R and G with a neutral center", () => {
    const map = generateNormalMap({
      kind: "control",
      width: 120,
      height: 48,
      radius: 24,
    });

    const left = map.sample(4, 32);
    const leftMirror = map.sample(4, 31);
    const right = map.sample(123, 32);
    const rightMirror = map.sample(123, 31);
    const top = map.sample(64, 4);
    const topMirror = map.sample(63, 4);
    const bottom = map.sample(64, 59);
    const bottomMirror = map.sample(63, 59);
    const center = map.sample(64, 32);

    expect(left.r).toBeLessThan(0.5);
    expect((left.g + leftMirror.g) / 2).toBeCloseTo(0.5, 5);
    expect(right.r).toBeGreaterThan(0.5);
    expect((right.g + rightMirror.g) / 2).toBeCloseTo(0.5, 5);
    expect((top.r + topMirror.r) / 2).toBeCloseTo(0.5, 5);
    expect(top.g).toBeLessThan(0.5);
    expect((bottom.r + bottomMirror.r) / 2).toBeCloseTo(0.5, 5);
    expect(bottom.g).toBeGreaterThan(0.5);
    expect(center).toEqual({
      r: 0.5,
      g: 0.5,
      b: 0.5,
      a: 1,
    });
  });

  it("keeps mirrored normals symmetric without diagonal bias", () => {
    const map = generateNormalMap({
      kind: "panel",
      width: 320,
      height: 200,
      radius: 22,
    });
    const midX = map.textureWidth / 2;
    const midY = map.textureHeight / 2;

    for (const x of [3, 9, 21, 47]) {
      const left = map.sample(x, midY);
      const right = map.sample(map.textureWidth - 1 - x, midY);
      expect(left.r + right.r).toBeCloseTo(1, 5);
      expect(left.g).toBeCloseTo(0.5, 5);
      expect(right.g).toBeCloseTo(0.5, 5);
    }

    for (const y of [3, 9, 21, 47]) {
      const top = map.sample(midX, y);
      const bottom = map.sample(midX, map.textureHeight - 1 - y);
      expect(top.g + bottom.g).toBeCloseTo(1, 5);
      expect(top.r).toBeCloseTo(0.5, 5);
      expect(bottom.r).toBeCloseTo(0.5, 5);
    }

    let horizontalBias = 0;
    let verticalBias = 0;
    for (let y = 0; y < map.textureHeight; y += 4) {
      for (let x = 0; x < map.textureWidth; x += 4) {
        const sample = map.sample(x, y);
        const horizontalMirror = map.sample(map.textureWidth - 1 - x, y);
        const verticalMirror = map.sample(x, map.textureHeight - 1 - y);
        expect(sample.r + horizontalMirror.r).toBeCloseTo(1, 5);
        expect(sample.g).toBeCloseTo(horizontalMirror.g, 5);
        expect(sample.g + verticalMirror.g).toBeCloseTo(1, 5);
        expect(sample.r).toBeCloseTo(verticalMirror.r, 5);
        horizontalBias += sample.r + horizontalMirror.r - 1;
        verticalBias += sample.g + verticalMirror.g - 1;
      }
    }
    expect(horizontalBias).toBeCloseTo(0, 5);
    expect(verticalBias).toBeCloseTo(0, 5);
  });

  it("does not expose mutable cached pixel storage", () => {
    const map = generateNormalMap({
      kind: "control",
      width: 120,
      height: 48,
      radius: 24,
    });
    const first = map.toRgbaBytes();
    const original = first[0];
    first[0] = original === 0 ? 255 : 0;

    expect(Object.isFrozen(map)).toBe(true);
    expect(map.toRgbaBytes()[0]).toBe(original);
  });
});

describe("Liquid Glass v3 normal-map cache", () => {
  it("defaults to an immutable 64-entry LRU and promotes cache hits", () => {
    const cache = new NormalMapCache();
    expect(cache.maxEntries).toBe(DEFAULT_NORMAL_MAP_CACHE_LIMIT);
    expect(DEFAULT_NORMAL_MAP_CACHE_LIMIT).toBe(64);

    const firstRequest = {
      kind: "control" as const,
      width: 100,
      height: 40,
      radius: 12,
    };
    const first = cache.get(firstRequest);
    expect(cache.get(firstRequest)).toBe(first);
  });

  it("evicts the least recently used geometry without mutating retained maps", () => {
    const cache = new NormalMapCache(2);
    const firstRequest = {
      kind: "control" as const,
      width: 100,
      height: 40,
      radius: 12,
    };
    const secondRequest = {
      kind: "control" as const,
      width: 140,
      height: 44,
      radius: 14,
    };
    const thirdRequest = {
      kind: "panel" as const,
      width: 300,
      height: 180,
      radius: 22,
    };
    const first = cache.get(firstRequest);
    cache.get(secondRequest);
    cache.get(firstRequest);
    cache.get(thirdRequest);

    expect(cache.size).toBe(2);
    expect(cache.has(makeNormalMapKey(firstRequest))).toBe(true);
    expect(cache.has(makeNormalMapKey(secondRequest))).toBe(false);
    expect(cache.get(firstRequest)).toBe(first);
  });
});

describe("Liquid Glass v3 filter registry", () => {
  it("reference-counts shared geometry and removes the filter after the final release", () => {
    const registry = new GlassFilterRegistry();
    const request = {
      kind: "control" as const,
      width: 120,
      height: 48,
      radius: 24,
    };
    const first = registry.acquire(request);
    const second = registry.acquire(request);

    expect(registry.size).toBe(1);
    expect(first.key).toBe(second.key);
    expect(first.filterId).toBe(second.filterId);
    expect(first.map).toBe(second.map);
    expect(Object.isFrozen(first)).toBe(true);
    expect(registry.getReferenceCount(first.key)).toBe(2);
    expect(registry.snapshot()).toEqual([
      {
        key: first.key,
        filterId: first.filterId,
        map: first.map,
        references: 2,
      },
    ]);
    expect(Object.isFrozen(registry.snapshot())).toBe(true);

    first.release();
    first.release();
    expect(registry.getReferenceCount(first.key)).toBe(1);

    second.release();
    expect(registry.size).toBe(0);
    expect(registry.getReferenceCount(first.key)).toBe(0);
  });

  it("does not let a stale lease release a new generation after registry cleanup", () => {
    const registry = new GlassFilterRegistry();
    const request = {
      kind: "panel" as const,
      width: 320,
      height: 200,
      radius: 22,
    };
    const stale = registry.acquire(request);
    registry.clear();
    const current = registry.acquire(request);

    stale.release();
    expect(registry.getReferenceCount(current.key)).toBe(1);
    current.release();
    expect(registry.size).toBe(0);
  });
});
