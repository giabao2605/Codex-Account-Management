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

defineOptions({ inheritAttrs: false });

const props = withDefaults(defineProps<{
  open: boolean;
  label: string;
  placement?: "start" | "end";
  morphId?: string;
}>(), {
  placement: "end",
  morphId: undefined,
});
const emit = defineEmits<{
  "update:open": [value: boolean];
}>();
const activePinia = getActivePinia();
const appearance = activePinia ? useAppearanceStore(activePinia) : undefined;
const {
  ensureMotion,
  layoutGroup,
  motionDiv,
  preloadMotion,
  presence,
  ready: motionReady,
} = useLazyMotionRuntime();
const root = ref<HTMLElement | null>(null);
const panelId = useId();
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
let restoreFocus = false;
let focusEpoch = 0;
let settleTimer = 0;
let motionPreferenceObserver: {
  observe: (
    target: HTMLElement,
    options: { attributes: boolean; attributeFilter: string[] },
  ) => void;
  disconnect: () => void;
} | undefined;

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

function triggerElement(): HTMLElement | null {
  return root.value?.querySelector<HTMLElement>(
    ".glass-popover-anchor button, .glass-popover-anchor [href], .glass-popover-anchor [tabindex]",
  ) ?? null;
}

function prepareMotion(): void {
  if (!motionReady.value) void preloadMotion();
}

async function setOpen(value: boolean): Promise<void> {
  if (value && !motionReady.value) await ensureMotion();
  restoreFocus = props.open && !value;
  emit("update:open", value);
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (!props.open) return;
  const target = event.target as Node;
  const anchor = root.value?.querySelector(".glass-popover-anchor");
  const panel = root.value?.querySelector(".glass-popover-panel");
  if (!anchor?.contains(target) && !panel?.contains(target)) setOpen(false);
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (props.open && event.key === "Escape") {
    event.preventDefault();
    setOpen(false);
  }
}

watch(() => props.open, async (open, wasOpen) => {
  const epoch = ++focusEpoch;
  if (open) {
    morphState.value = "opening";
    window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(
      settleMorph,
      reducedMotion.value ? 100 : 360,
    );
    await nextTick();
    if (epoch !== focusEpoch || !props.open) return;
    root.value
      ?.querySelector<HTMLElement>(".glass-popover-panel input, .glass-popover-panel button")
      ?.focus();
  } else if (restoreFocus || wasOpen) {
    window.clearTimeout(settleTimer);
    restoreFocus = false;
    requestAnimationFrame(() => {
      if (epoch === focusEpoch && !props.open) triggerElement()?.focus();
    });
  }
});

onMounted(() => {
  syncMotionPreference();
  motionPreferenceObserver = new window.MutationObserver(syncMotionPreference);
  motionPreferenceObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-glass-motion"],
  });
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("keydown", onDocumentKeydown);
});
onBeforeUnmount(() => {
  focusEpoch += 1;
  window.clearTimeout(settleTimer);
  motionPreferenceObserver?.disconnect();
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("keydown", onDocumentKeydown);
});
</script>

<template>
  <component
    :is="layoutGroup"
    :id="motionReady ? effectiveMorphId : undefined"
  >
    <div
      v-bind="$attrs"
      ref="root"
      class="glass-popover-root"
      :data-glass-open="String(open)"
    >
      <component
        :is="motionDiv"
        class="glass-popover-anchor"
        data-glass-morph-source="popover"
        :data-glass-morph-id="effectiveMorphId"
        :data-glass-layout-id="effectiveMorphId"
        :data-glass-morph-state="open ? 'destination' : 'source'"
        v-bind="motionReady ? {
          layout: reducedMotion ? false : 'position',
          layoutId: reducedMotion ? undefined : effectiveMorphId,
          transition: morphTransition,
          animate: { opacity: open ? 0 : 1 },
        } : {}"
        @pointerenter="prepareMotion"
        @focusin="prepareMotion"
        @click="setOpen(!open)"
      >
        <slot
          name="trigger"
          :open="open"
          :panel-id="panelId"
          :morph-id="effectiveMorphId"
        />
      </component>
      <component
        :is="presence"
        v-bind="motionReady ? { mode: 'sync' } : {}"
        :class="{ 'glass-presence-fallback': !motionReady }"
      >
        <component
          :is="motionDiv"
          v-if="open"
          :key="`popover-${effectiveMorphId}`"
          class="glass-morph-shell"
          :class="`is-${placement}`"
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
            :id="panelId"
            class="glass-popover-panel"
            :class="`is-${placement}`"
            level="prominent"
            shape="panel"
            depth="thick"
            material="regular"
            context="auto"
            concentric
            role="dialog"
            :aria-label="label"
            data-glass-morph="popover"
            :data-glass-morph-id="effectiveMorphId"
            :data-glass-layout-id="reducedMotion ? undefined : effectiveMorphId"
            data-glass-content-reveal="42"
            :data-glass-motion-mode="reducedMotion ? 'reduced' : 'full'"
            :data-glass-morph-state="morphState"
            @keydown.esc.stop="setOpen(false)"
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
              <slot />
            </component>
          </GlassSurface>
        </component>
      </component>
    </div>
  </component>
</template>
