<script setup lang="ts">
import { ref } from "vue";

import {
  type EffectsPreference,
  type ThemePreference,
  useAppearanceStore,
} from "@/stores/appearance.ts";
import GlassButton from "./GlassButton.vue";
import GlassPopover from "./GlassPopover.vue";
import SurfaceActionButton from "./SurfaceActionButton.vue";

const appearance = useAppearanceStore();
const open = ref(false);
const appearanceMorphId = "appearance";
</script>

<template>
  <GlassPopover
    v-model:open="open"
    class="appearance-control"
    label="Tùy chỉnh giao diện"
    :morph-id="appearanceMorphId"
  >
    <template #trigger>
      <GlassButton
        variant="prominent"
        :morph-id="appearanceMorphId"
        aria-haspopup="dialog"
        :aria-expanded="open"
      >
        Giao diện
      </GlassButton>
    </template>
    <template #default>
      <fieldset>
        <legend>Chủ đề</legend>
        <label
          v-for="option in ([
            ['system', 'Hệ thống'],
            ['light', 'Sáng'],
            ['dark', 'Tối'],
          ] as Array<[ThemePreference, string]>)"
          :key="option[0]"
        >
          <input
            type="radio"
            name="theme"
            :value="option[0]"
            :checked="appearance.themePreference === option[0]"
            @change="appearance.setThemePreference(option[0])"
          >
          {{ option[1] }}
        </label>
      </fieldset>
      <fieldset>
        <legend>Hiệu ứng</legend>
        <label
          v-for="option in ([
            ['auto', 'Tự động'],
            ['full', 'Đầy đủ'],
            ['reduced', 'Giảm'],
            ['off', 'Tắt'],
          ] as Array<[EffectsPreference, string]>)"
          :key="option[0]"
        >
          <input
            type="radio"
            name="effects"
            :value="option[0]"
            :checked="appearance.effectsPreference === option[0]"
            @change="appearance.setEffectsPreference(option[0])"
          >
          {{ option[1] }}
        </label>
      </fieldset>
      <SurfaceActionButton @click="open = false">Đóng</SurfaceActionButton>
    </template>
  </GlassPopover>
</template>
