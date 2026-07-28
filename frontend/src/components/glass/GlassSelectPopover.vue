<script setup lang="ts">
import { computed, ref, useId } from "vue";

import GlassButton from "./GlassButton.vue";
import GlassPopover from "./GlassPopover.vue";

export interface GlassSelectOption {
  readonly value: string;
  readonly label: string;
}

const props = defineProps<{
  label: string;
  options: readonly GlassSelectOption[];
  morphId: string;
  triggerClass?: string;
}>();
const model = defineModel<string>({ required: true });
const open = ref(false);
const groupName = `glass-select-${useId().replaceAll(":", "")}`;
const selectedLabel = computed(() => (
  props.options.find((option) => option.value === model.value)?.label
  ?? props.options[0]?.label
  ?? ""
));

function select(value: string): void {
  model.value = value;
  open.value = false;
}
</script>

<template>
  <div class="glass-select-control">
    <span class="glass-select-label">{{ label }}</span>
    <GlassPopover
      v-model:open="open"
      class="glass-select-popover"
      placement="start"
      :label="label"
      :morph-id="morphId"
    >
      <template #trigger="{ panelId }">
        <GlassButton
          :class="['glass-select-trigger', triggerClass]"
          variant="lite"
          :morph-id="morphId"
          aria-haspopup="dialog"
          :aria-expanded="open"
          :aria-controls="panelId"
          :aria-label="`${label}: ${selectedLabel}`"
        >
          <span class="glass-select-trigger-label">{{ selectedLabel }}</span>
          <span class="glass-select-chevron" aria-hidden="true" />
        </GlassButton>
      </template>
      <fieldset class="glass-select-options">
        <legend class="sr-only">{{ label }}</legend>
        <label v-for="option in options" :key="option.value">
          <input
            type="radio"
            :name="groupName"
            :value="option.value"
            :checked="model === option.value"
            @change="select(option.value)"
          >
          <span>{{ option.label }}</span>
        </label>
      </fieldset>
    </GlassPopover>
  </div>
</template>
