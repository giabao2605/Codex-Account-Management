import {
  onBeforeUnmount,
  onMounted,
  toValue,
  watch,
  type MaybeRefOrGetter,
  type Ref,
} from "vue";

import {
  acquireRuntimeGlassFilter,
  type RuntimeGlassFilterLease,
} from "@/glass/filterRuntime.ts";
import type {
  GlassMaterial,
  LiquidGlassShape,
} from "./useLiquidGlass.ts";

interface GlassGeometryOptions {
  shape: MaybeRefOrGetter<LiquidGlassShape>;
  material: MaybeRefOrGetter<GlassMaterial>;
}

let geometryQueue: Array<() => void> = [];
let geometryFrame: number | null = null;

function flushGeometryQueue(): void {
  geometryFrame = null;
  const [next, ...remaining] = geometryQueue;
  geometryQueue = remaining;
  next?.();
  if (geometryQueue.length > 0) {
    geometryFrame = requestAnimationFrame(flushGeometryQueue);
  }
}

function scheduleGeometry(task: () => void): void {
  if (geometryQueue.includes(task)) return;
  geometryQueue = [...geometryQueue, task];
  geometryFrame ??= requestAnimationFrame(flushGeometryQueue);
}

function cancelGeometry(task: () => void): void {
  geometryQueue = geometryQueue.filter((candidate) => candidate !== task);
  if (geometryQueue.length === 0 && geometryFrame !== null) {
    cancelAnimationFrame(geometryFrame);
    geometryFrame = null;
  }
}

function radiusFor(
  element: HTMLElement,
  shape: LiquidGlassShape,
  height: number,
): number {
  if (shape === "capsule") return height / 2;
  const computedRadius = Number.parseFloat(
    getComputedStyle(element).borderTopLeftRadius,
  );
  if (Number.isFinite(computedRadius)) return computedRadius;
  return shape === "panel" ? 24 : 16;
}

export function displacementFor(
  material: GlassMaterial,
  shape: LiquidGlassShape,
): number {
  if (material === "clear") return shape === "panel" ? 14 : 10;
  return shape === "panel" ? 12 : 8;
}

export function useGlassGeometry(
  element: Readonly<Ref<HTMLElement | null>>,
  options: GlassGeometryOptions,
): { refresh: () => void } {
  let lease: RuntimeGlassFilterLease | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let scheduled = false;

  function applyGeometry(): void {
    scheduled = false;
    const target = element.value;
    if (!target?.isConnected) return;
    const bounds = target.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const shape = toValue(options.shape);
    const material = toValue(options.material);
    const displacement = displacementFor(material, shape);
    const nextLease = acquireRuntimeGlassFilter({
      kind: shape === "panel" ? "panel" : "control",
      width: bounds.width,
      height: bounds.height,
      radius: radiusFor(target, shape, bounds.height),
    }, displacement);
    if (nextLease.key === lease?.key) {
      nextLease.release();
    } else {
      lease?.release();
      lease = nextLease;
    }
    target.dataset.glassNormalMap = lease?.map.key;
    target.style.setProperty(
      "--glass-filter-url",
      `url("#${lease?.filterId}")`,
    );
    target.style.setProperty(
      "--glass-displacement",
      `${displacement}px`,
    );
  }

  function refresh(): void {
    if (scheduled) return;
    scheduled = true;
    scheduleGeometry(applyGeometry);
  }

  onMounted(() => {
    refresh();
    if (typeof ResizeObserver === "function" && element.value) {
      resizeObserver = new ResizeObserver(refresh);
      resizeObserver.observe(element.value);
    }
  });

  watch(
    [() => toValue(options.shape), () => toValue(options.material)],
    refresh,
  );

  onBeforeUnmount(() => {
    resizeObserver?.disconnect();
    if (scheduled) {
      scheduled = false;
      cancelGeometry(applyGeometry);
    }
    lease?.release();
  });

  return { refresh };
}
