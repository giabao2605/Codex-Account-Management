<script setup lang="ts">
import { getActivePinia } from "pinia";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  useId,
  watch,
} from "vue";

import { useAppearanceStore } from "@/stores/appearance.ts";
import { useLazyMotionRuntime } from "@/composables/useLazyMotionRuntime.ts";

import GlassHybridOverlay from "./GlassHybridOverlay.vue";
import GlassSurface from "./GlassSurface.vue";

const props = defineProps<{
  open: boolean;
  title: string;
  morphId?: string;
}>();
const emit = defineEmits<{ close: [] }>();
const activePinia = getActivePinia();
const appearance = activePinia ? useAppearanceStore(activePinia) : undefined;
const {
  ensureMotion,
  layoutGroup,
  motionDiv,
  presence,
  ready: motionReady,
} = useLazyMotionRuntime();
const titleId = useId();
const dialogId = useId();
const generatedMorphId = useId();
const effectiveMorphId = computed(() => props.morphId ?? generatedMorphId);
const reducedMotion = ref(readMotionPreference());
const morphState = ref<"opening" | "settled">("opening");
const hybridEnabled = computed(
  () => appearance?.runtimeProfile.renderer === "hybrid",
);
const morphTransition = computed(() => (
  reducedMotion.value
    ? { duration: 0.1, ease: "linear" as const }
    : props.open
      ? {
          type: "spring" as const,
          stiffness: 420,
          damping: 36,
          mass: 0.8,
        }
      : {
          type: "spring" as const,
          stiffness: 500,
          damping: 40,
          mass: 0.7,
        }
));
const contentTransition = computed(() => (
  reducedMotion.value
    ? { duration: 0.1, delay: 0 }
    : { duration: 0.16, delay: 0, ease: "easeOut" as const }
));
let previousFocus: HTMLElement | null = null;
let focusEpoch = 0;
let restoreFrame = 0;
let settleTimer = 0;
let motionPreferenceObserver: {
  observe: (
    target: HTMLElement,
    options: { attributes: boolean; attributeFilter: string[] },
  ) => void;
  disconnect: () => void;
} | undefined;

function dialogElement(): HTMLElement | null {
  return document.getElementById(dialogId);
}

function readMotionPreference(): boolean {
  const mediaReduced = window.matchMedia?.(
    "(prefers-reduced-motion: reduce)",
  ).matches ?? false;
  return (
    document.documentElement.dataset.glassMotion === "reduced"
    || mediaReduced
  );
}

function syncMotionPreference(): void {
  reducedMotion.value = readMotionPreference();
}

function settleMorph(): void {
  if (props.open) morphState.value = "settled";
}

function settleReducedMotion(): void {
  if (reducedMotion.value) settleMorph();
}

function focusableElements(): HTMLElement[] {
  return [...(dialogElement()?.querySelectorAll<HTMLElement>(
    "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex='-1'])",
  ) ?? [])];
}

function close(): void {
  emit("close");
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = focusableElements();
  if (!focusable.length) {
    event.preventDefault();
    dialogElement()?.focus();
    return;
  }
  const first = focusable[0]!;
  const last = focusable.at(-1)!;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

watch(() => props.open, async (open) => {
  const epoch = ++focusEpoch;
  if (open) {
    morphState.value = "opening";
    window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(
      settleMorph,
      reducedMotion.value ? 100 : 360,
    );
    if (restoreFrame) {
      cancelAnimationFrame(restoreFrame);
      restoreFrame = 0;
    }
    previousFocus = document.activeElement as HTMLElement | null;
    void ensureMotion();
    await nextTick();
    if (epoch !== focusEpoch || !props.open) return;
    (focusableElements()[0] ?? dialogElement())?.focus();
  } else if (previousFocus) {
    window.clearTimeout(settleTimer);
    const target = previousFocus;
    previousFocus = null;
    restoreFrame = requestAnimationFrame(() => {
      restoreFrame = 0;
      if (epoch === focusEpoch && !props.open) target.focus();
    });
  }
}, { immediate: true });

onMounted(() => {
  syncMotionPreference();
  motionPreferenceObserver = new window.MutationObserver(syncMotionPreference);
  motionPreferenceObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-glass-motion"],
  });
});
onBeforeUnmount(() => {
  focusEpoch += 1;
  window.clearTimeout(settleTimer);
  motionPreferenceObserver?.disconnect();
  if (restoreFrame) cancelAnimationFrame(restoreFrame);
  previousFocus?.focus();
});
</script>

<template>
  <component
    :is="layoutGroup"
    :id="motionReady ? effectiveMorphId : undefined"
  >
    <component
      :is="motionDiv"
      v-if="$slots.trigger"
      class="glass-dialog-anchor"
      data-glass-morph-source="dialog"
      :data-glass-morph-id="effectiveMorphId"
      :data-glass-layout-id="effectiveMorphId"
      :data-glass-morph-state="open ? 'destination' : 'source'"
      v-bind="motionReady ? {
        layout: reducedMotion ? false : 'position',
        layoutId: reducedMotion ? undefined : effectiveMorphId,
        transition: morphTransition,
        animate: { opacity: open ? 0 : 1 },
      } : {}"
      @pointerenter="ensureMotion"
      @focusin="ensureMotion"
    >
      <slot name="trigger" />
    </component>
    <Teleport to="body">
      <component
        :is="presence"
        v-bind="motionReady ? { mode: 'sync' } : {}"
        :class="{ 'glass-presence-fallback': !motionReady }"
      >
        <component
          :is="motionDiv"
          v-if="open"
          :key="`dialog-backdrop-${effectiveMorphId}`"
          class="dialog-backdrop"
          v-bind="motionReady ? {
            layoutRoot: !reducedMotion,
            initial: { opacity: 0 },
            animate: { opacity: 1 },
            exit: { opacity: 0 },
            transition: reducedMotion
              ? { duration: 0.1, ease: 'linear' }
              : { duration: 0.18, ease: 'easeOut' },
          } : {}"
          @pointerdown.self="close"
        >
          <component
            :is="motionDiv"
            class="glass-morph-shell glass-dialog-morph-shell"
            v-bind="motionReady ? {
              layout: reducedMotion ? false : true,
              layoutId: reducedMotion ? undefined : effectiveMorphId,
              initial: { opacity: 1 },
              animate: { opacity: 1 },
              exit: { opacity: 0 },
              transition: morphTransition,
            } : {}"
            :style="{ animation: 'none' }"
            @animation-complete="settleReducedMotion"
            @layout-animation-complete="settleMorph"
          >
            <GlassSurface
              :id="dialogId"
              as="section"
              class="glass-dialog"
              level="prominent"
              shape="panel"
              depth="thick"
              material="regular"
              context="auto"
              concentric
              role="dialog"
              aria-modal="true"
              data-glass-morph="dialog"
              :data-glass-morph-id="effectiveMorphId"
              :data-glass-layout-id="reducedMotion ? undefined : effectiveMorphId"
              data-glass-content-reveal="42"
              :data-glass-motion-mode="reducedMotion ? 'reduced' : 'full'"
              :data-glass-morph-state="morphState"
              :aria-labelledby="titleId"
              tabindex="-1"
              @keydown="onKeydown"
            >
              <GlassHybridOverlay
                v-if="hybridEnabled"
                :active="open"
                :intensity=".72"
              />
              <component
                :is="motionDiv"
                class="glass-morph-content"
                v-bind="motionReady ? {
                  initial: { opacity: 0 },
                  animate: { opacity: 1 },
                  exit: { opacity: 0 },
                  transition: contentTransition,
                } : {}"
              >
                <header class="glass-dialog-header">
                  <h2 :id="titleId">{{ title }}</h2>
                  <slot name="header" />
                </header>
                <div class="glass-dialog-body">
                  <slot />
                </div>
                <div v-if="$slots.actions" class="glass-dialog-actions">
                  <slot name="actions" />
                </div>
              </component>
            </GlassSurface>
          </component>
        </component>
      </component>
    </Teleport>
  </component>
</template>
