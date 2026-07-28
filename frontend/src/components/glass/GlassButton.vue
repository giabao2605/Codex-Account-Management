<script setup lang="ts">
import { computed, useTemplateRef } from "vue";

import { useGlassContext } from "@/composables/useGlassContext.ts";
import { useGlassGeometry } from "@/composables/useGlassGeometry.ts";
import {
  type GlassContext,
  type GlassMaterial,
  type LiquidGlassDepth,
  type LiquidGlassShape,
  type LiquidGlassTint,
  useLiquidGlass,
} from "@/composables/useLiquidGlass.ts";

const props = withDefaults(defineProps<{
  variant?: "default" | "prominent" | "lite" | "danger" | "quiet";
  shape?: LiquidGlassShape;
  depth?: LiquidGlassDepth;
  tint?: LiquidGlassTint;
  busy?: boolean;
  disabled?: boolean;
  material?: GlassMaterial;
  context?: GlassContext;
  morphId?: string;
}>(), {
  variant: "prominent",
  shape: "rounded",
  depth: "auto",
  tint: undefined,
  busy: false,
  disabled: false,
  material: "regular",
  context: "auto",
  morphId: undefined,
});

const { clearPointer, mode, setPressed, trackPointer } = useLiquidGlass();
const element = useTemplateRef<HTMLButtonElement>("button");
const effectiveDepth = computed<LiquidGlassDepth>(() => {
  if (props.depth !== "auto") return props.depth;
  return props.variant === "prominent" || props.variant === "danger"
    ? "regular"
    : "thin";
});
const effectiveMaterial = computed<GlassMaterial>(() => (
  props.material === "clear" && props.context !== "media"
    ? "regular"
    : props.material
));
useGlassGeometry(element, {
  shape: () => props.shape,
  material: effectiveMaterial,
});
useGlassContext(element, () => props.context);
const effectiveTint = computed<LiquidGlassTint>(() => {
  if (props.tint) return props.tint;
  if (props.variant === "danger") return "danger";
  if (props.variant === "prominent") return "accent";
  return "neutral";
});
</script>

<template>
  <button
    ref="button"
    class="glass-button"
    :class="[
      `is-${variant}`,
      `is-shape-${shape}`,
      `is-depth-${effectiveDepth}`,
      `is-tint-${effectiveTint}`,
      `is-material-${effectiveMaterial}`,
    ]"
    type="button"
    :disabled="disabled || busy"
    :aria-busy="busy || undefined"
    data-glass-version="3"
    data-liquid-glass-v3=""
    data-material-layer="control"
    :data-glass-shape="shape"
    :data-glass-depth="effectiveDepth"
    :data-glass-tint="effectiveTint"
    :data-glass-mode="mode"
    :data-glass-material="effectiveMaterial"
    :data-glass-context="context"
    :data-glass-morph-id="morphId"
    :data-glass-prominent="variant === 'prominent' ? '' : undefined"
    @pointermove="trackPointer"
    @pointerdown="setPressed($event, true)"
    @pointerup="setPressed($event, false)"
    @pointercancel="clearPointer"
    @pointerleave="clearPointer"
  >
    <span v-if="busy" class="sr-only">Đang xử lý</span>
    <slot />
  </button>
</template>
