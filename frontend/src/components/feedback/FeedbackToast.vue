<script setup lang="ts">
import { useFeedbackStore } from "@/stores/feedback.ts";

const feedback = useFeedbackStore();
</script>

<template>
  <aside
    v-if="feedback.isVisible"
    class="feedback-toast standard-surface"
    :class="{ 'is-error': feedback.isError }"
    data-material="standard"
    :role="feedback.isError ? 'alert' : 'status'"
    :aria-live="feedback.isError ? 'assertive' : 'polite'"
  >
    <span>{{ feedback.message }}</span>
    <button
      type="button"
      class="feedback-toast-close"
      aria-label="Đóng thông báo"
      @click="feedback.hide"
    >
      Đóng
    </button>
  </aside>
</template>
