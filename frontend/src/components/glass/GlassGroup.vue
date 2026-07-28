<script setup lang="ts">
import { computed, provide, toRef, useId } from "vue";

import {
  createGlassGroupContext,
  GLASS_GROUP_KEY,
} from "@/glass/groupContext.ts";
import type {
  GlassContext,
  GlassMaterial,
  GlassRenderer,
  LiquidGlassDepth,
  LiquidGlassShape,
  LiquidGlassTint,
} from "@/composables/useLiquidGlass.ts";

import GlassSurface from "./GlassSurface.vue";

const props = withDefaults(defineProps<{
  as?: string;
  level?: "prominent" | "lite" | "solid";
  shape?: LiquidGlassShape;
  depth?: LiquidGlassDepth;
  tint?: LiquidGlassTint;
  interactive?: boolean;
  role?: string;
  ariaLabel?: string;
  material?: GlassMaterial;
  context?: GlassContext;
  concentric?: boolean | null;
  groupId?: string;
  mergeDistance?: number;
  renderer?: GlassRenderer;
}>(), {
  as: "div",
  level: "prominent",
  shape: "rounded",
  depth: "auto",
  tint: "neutral",
  interactive: true,
  role: "group",
  ariaLabel: undefined,
  material: "regular",
  context: "auto",
  concentric: null,
  groupId: undefined,
  mergeDistance: 12,
  renderer: "auto",
});
const generatedGroupId = useId();
const effectiveGroupId = computed(() => props.groupId ?? generatedGroupId);
const groupContext = createGlassGroupContext(
  effectiveGroupId,
  toRef(props, "mergeDistance"),
);
const memberCount = computed(() => groupContext.members.value.length);
provide(GLASS_GROUP_KEY, groupContext);
</script>

<template>
  <GlassSurface
    :as="as"
    class="glass-group"
    :level="level"
    :shape="shape"
    :depth="depth"
    :tint="tint"
    :interactive="interactive"
    :material="material"
    :context="context"
    :concentric="concentric"
    :role="role"
    :aria-label="ariaLabel"
    data-glass-container=""
    data-material-layer="control"
    :data-glass-group-id="effectiveGroupId"
    :data-glass-merge-distance="mergeDistance"
    :data-glass-renderer="renderer"
    :data-glass-member-count="memberCount"
  >
    <slot />
  </GlassSurface>
</template>
