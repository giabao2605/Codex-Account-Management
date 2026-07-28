import { ref } from "vue";
import { defineStore } from "pinia";

export const useFeedbackStore = defineStore("feedback", () => {
  const message = ref("");
  const isError = ref(false);
  const isVisible = ref(false);
  let hideTimer: number | null = null;

  function show(nextMessage: string, error = false): void {
    if (hideTimer !== null) {
      window.clearTimeout(hideTimer);
    }
    message.value = nextMessage;
    isError.value = error;
    isVisible.value = true;
    hideTimer = window.setTimeout(() => {
      isVisible.value = false;
      hideTimer = null;
    }, 3_200);
  }

  function hide(): void {
    if (hideTimer !== null) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
    isVisible.value = false;
  }

  function success(nextMessage: string): void {
    show(nextMessage);
  }

  function error(nextMessage: string): void {
    show(nextMessage, true);
  }

  return {
    error,
    hide,
    isError,
    isVisible,
    message,
    show,
    success,
  };
});
