<script setup lang="ts">
withDefaults(defineProps<{
  tone?: "default" | "danger";
  busy?: boolean;
  disabled?: boolean;
}>(), {
  tone: "default",
  busy: false,
  disabled: false,
});
</script>

<template>
  <button
    class="surface-action-button"
    :class="`is-${tone}`"
    type="button"
    :disabled="disabled || busy"
    :aria-busy="busy || undefined"
    data-surface-action=""
  >
    <span v-if="busy" class="sr-only">Đang xử lý</span>
    <slot />
  </button>
</template>
