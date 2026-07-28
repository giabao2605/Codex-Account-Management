<script setup lang="ts">
import { getActivePinia } from "pinia";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  useId,
} from "vue";

import { useAppearanceStore } from "@/stores/appearance.ts";

import GlassGroup from "./GlassGroup.vue";
import GlassHybridOverlay from "./GlassHybridOverlay.vue";

defineOptions({ inheritAttrs: false });

export interface GlassSegmentOption {
  value: string;
  label: string;
  id?: string;
  disabled?: boolean;
  controls?: string;
}

const props = withDefaults(defineProps<{
  modelValue: string;
  options: readonly GlassSegmentOption[];
  label: string;
  mode?: "single" | "tabs";
  level?: "prominent" | "lite";
}>(), {
  mode: "single",
  level: "prominent",
});
const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();
const activePinia = getActivePinia();
const appearance = activePinia ? useAppearanceStore(activePinia) : undefined;
const layoutGroupId = `segmented-${useId()}`;
const lensLayoutId = `${layoutGroupId}-active-lens`;
const reducedMotion = ref(readMotionPreference());
const geometryMotionEnabled = computed(() => (
  !reducedMotion.value
  && appearance?.runtimeProfile.quality !== "off"
));
const hybridEnabled = computed(
  () => appearance?.runtimeProfile.renderer === "hybrid",
);
let motionPreferenceObserver: {
  observe: (
    target: HTMLElement,
    options: { attributes: boolean; attributeFilter: string[] },
  ) => void;
  disconnect: () => void;
} | undefined;
const activeColumn = computed(() => {
  const index = props.options.findIndex(
    (option) => option.value === props.modelValue,
  );
  return Math.max(0, index) + 1;
});
const segmentCount = computed(() => Math.max(1, props.options.length));
const activeOffset = computed(() => `${(activeColumn.value - 1) * 100}%`);

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

function select(value: string): void {
  emit("update:modelValue", value);
}

async function moveFocus(
  event: KeyboardEvent,
  optionIndex: number,
): Promise<void> {
  const group = (event.currentTarget as HTMLElement).parentElement;
  const enabled = props.options
    .map((option, index) => ({ option, index }))
    .filter(({ option }) => !option.disabled);
  if (!enabled.length) return;
  const current = enabled.findIndex(({ index }) => index === optionIndex);
  let nextIndex: number;
  if (event.key === "ArrowRight") {
    nextIndex = (current + 1) % enabled.length;
  } else if (event.key === "ArrowLeft") {
    nextIndex = (current - 1 + enabled.length) % enabled.length;
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = enabled.length - 1;
  } else {
    return;
  }
  const next = enabled[nextIndex];
  if (!next) return;
  event.preventDefault();
  select(next.option.value);
  await nextTick();
  group?.querySelectorAll<HTMLButtonElement>("button")[next.index]?.focus();
}

onMounted(() => {
  syncMotionPreference();
  motionPreferenceObserver = new window.MutationObserver(syncMotionPreference);
  motionPreferenceObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-glass-motion"],
  });
});
onBeforeUnmount(() => motionPreferenceObserver?.disconnect());
</script>

<template>
  <GlassGroup
    v-bind="$attrs"
    class="glass-segmented-control"
    :level="level"
    shape="capsule"
    depth="thin"
    :interactive="false"
    :role="mode === 'tabs' ? 'tablist' : 'group'"
    :aria-label="label"
    :group-id="layoutGroupId"
    :style="{ '--glass-segment-count': segmentCount }"
    data-glass-segmented="v3"
  >
    <span
      class="glass-segmented-lens"
      data-glass-active-lens=""
      :data-glass-motion="geometryMotionEnabled ? 'compositor-transform' : 'instant'"
      :data-glass-layout-id="lensLayoutId"
      aria-hidden="true"
      :style="{
        '--glass-active-column': activeColumn,
        '--glass-active-offset': activeOffset,
      }"
    >
      <GlassHybridOverlay
        v-if="hybridEnabled"
        active
        :intensity=".76"
      />
    </span>
    <button
      v-for="(option, index) in options"
      :id="option.id"
      :key="option.value"
      type="button"
      :role="mode === 'tabs' ? 'tab' : undefined"
      :aria-selected="mode === 'tabs' ? modelValue === option.value : undefined"
      :aria-pressed="mode === 'single' ? modelValue === option.value : undefined"
      :aria-controls="option.controls"
      :tabindex="modelValue === option.value ? 0 : -1"
      :disabled="option.disabled"
      :class="{ 'is-active': modelValue === option.value }"
      :style="{ '--glass-segment-column': index + 1 }"
      @click="select(option.value)"
      @keydown="moveFocus($event, index)"
    >
      {{ option.label }}
    </button>
  </GlassGroup>
</template>
