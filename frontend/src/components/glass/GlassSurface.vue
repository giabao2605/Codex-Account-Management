<script setup lang="ts">
import { computed, useTemplateRef } from "vue";

import { useGlassContext } from "@/composables/useGlassContext.ts";
import { useGlassGeometry } from "@/composables/useGlassGeometry.ts";
import { useGlassGroupMember } from "@/glass/groupContext.ts";
import {
  type GlassContext,
  type GlassMaterial,
  type LiquidGlassDepth,
  type LiquidGlassShape,
  type LiquidGlassTint,
  useLiquidGlass,
} from "@/composables/useLiquidGlass.ts";

const props = withDefaults(defineProps<{
  as?: string;
  level?: "prominent" | "lite" | "solid";
  shape?: LiquidGlassShape;
  depth?: LiquidGlassDepth;
  tint?: LiquidGlassTint;
  interactive?: boolean;
  ariaLabel?: string;
  material?: GlassMaterial;
  context?: GlassContext;
  concentric?: boolean | null;
}>(), {
  as: "div",
  level: "prominent",
  shape: "rounded",
  depth: "auto",
  tint: "neutral",
  interactive: false,
  ariaLabel: undefined,
  material: "regular",
  context: "auto",
  concentric: null,
});
const element = useTemplateRef<HTMLElement>("surface");
const { clearPointer, mode, setPressed, trackPointer } = useLiquidGlass();
const effectiveDepth = computed<LiquidGlassDepth>(() => {
  if (props.depth !== "auto") return props.depth;
  if (props.level === "lite") return "thin";
  if (props.level === "solid") return "thick";
  return "regular";
});
const effectiveMaterial = computed<GlassMaterial>(() => (
  props.material === "clear" && props.context !== "media"
    ? "regular"
    : props.material
));
const effectiveConcentric = computed(
  () => props.concentric ?? props.shape === "panel",
);
useGlassGeometry(element, {
  shape: () => props.shape,
  material: effectiveMaterial,
});
useGlassContext(element, () => props.context);
useGlassGroupMember(element);
defineExpose({ element });
</script>

<template>
  <component
    :is="as"
    ref="surface"
    class="glass-surface"
    :class="[
      `is-${level}`,
      `is-shape-${shape}`,
      `is-depth-${effectiveDepth}`,
      `is-tint-${tint}`,
      `is-material-${effectiveMaterial}`,
      { 'is-interactive': interactive },
    ]"
    :data-glass-level="level"
    data-glass-version="3"
    data-liquid-glass-v3=""
    data-material-layer="control"
    :data-glass-shape="shape"
    :data-glass-depth="effectiveDepth"
    :data-glass-tint="tint"
    :data-glass-mode="mode"
    :data-glass-material="effectiveMaterial"
    :data-glass-context="context"
    :data-glass-concentric="effectiveConcentric ? '' : undefined"
    :data-glass-interactive="interactive ? '' : undefined"
    :data-glass-prominent="level === 'prominent' ? '' : undefined"
    :aria-label="ariaLabel"
    @pointermove="interactive && trackPointer($event)"
    @pointerdown="interactive && setPressed($event, true)"
    @pointerup="interactive && setPressed($event, false)"
    @pointercancel="interactive && clearPointer($event)"
    @pointerleave="interactive && clearPointer($event)"
  >
    <slot />
  </component>
</template>
