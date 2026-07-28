import {
  computed,
  markRaw,
  onBeforeUnmount,
  shallowRef,
  type Component,
  type ComputedRef,
} from "vue";

type MotionNamespace = Record<string, Component> & {
  div: Component;
  span: Component;
};

interface LazyMotionRuntime {
  AnimatePresence: Component;
  LayoutGroup: Component;
  motion: MotionNamespace;
}

let runtimePromise: Promise<LazyMotionRuntime> | null = null;

function loadRuntime(): Promise<LazyMotionRuntime> {
  runtimePromise ??= import("@/glass/motionLite.ts").then((module) => ({
    AnimatePresence: markRaw(module.AnimatePresence),
    LayoutGroup: markRaw(module.LayoutGroup),
    motion: markRaw(module.motion) as MotionNamespace,
  }));
  return runtimePromise;
}

export function useLazyMotionRuntime(): {
  ensureMotion: () => Promise<void>;
  preloadMotion: () => Promise<void>;
  layoutGroup: ComputedRef<Component | string>;
  motionDiv: ComputedRef<Component | string>;
  motionSpan: ComputedRef<Component | string>;
  presence: ComputedRef<Component | string>;
  ready: ComputedRef<boolean>;
} {
  const runtime = shallowRef<LazyMotionRuntime | null>(null);
  let active = true;

  onBeforeUnmount(() => {
    active = false;
  });

  async function ensureMotion(): Promise<void> {
    if (runtime.value !== null) return;
    const loadedRuntime = await loadRuntime();
    if (active && runtime.value === null) {
      runtime.value = loadedRuntime;
    }
  }

  async function preloadMotion(): Promise<void> {
    await loadRuntime();
  }

  return {
    ensureMotion,
    preloadMotion,
    layoutGroup: computed<Component | string>(() => (
      runtime.value?.LayoutGroup ?? "div"
    )),
    motionDiv: computed<Component | string>(() => (
      runtime.value?.motion.div ?? "div"
    )),
    motionSpan: computed<Component | string>(() => (
      runtime.value?.motion.span ?? "span"
    )),
    presence: computed<Component | string>(() => (
      runtime.value?.AnimatePresence ?? "div"
    )),
    ready: computed(() => runtime.value !== null),
  };
}
