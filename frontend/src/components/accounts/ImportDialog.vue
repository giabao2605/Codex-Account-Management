<script setup lang="ts">
import { computed, ref, watch } from "vue";

import GlassDialog from "@/components/glass/GlassDialog.vue";
import SurfaceActionButton from "@/components/glass/SurfaceActionButton.vue";
import { useAccountsStore } from "@/stores/accounts.ts";
import { useFeedbackStore } from "@/stores/feedback.ts";
import type { AccountCheckResponse } from "@/types/api.ts";

const props = defineProps<{ open: boolean; morphId: string }>();
const emit = defineEmits<{ close: [] }>();
const accounts = useAccountsStore();
const feedback = useFeedbackStore();
const line = ref("");
const check = ref<AccountCheckResponse | null>(null);
const checking = ref(false);
const saving = ref(false);
const error = ref("");
let checkRequestId = 0;

const busy = computed(() => checking.value || saving.value);
const addDisabled = computed(() => (
  saving.value
  || checking.value
  || check.value?.valid !== true
));
const statusMessage = computed(() => (
  error.value
  || (checking.value ? "Đang kiểm tra tài khoản..." : check.value?.message ?? "")
));
const statusState = computed(() => {
  if (error.value || check.value?.valid === false) return "error";
  if (check.value?.valid === true) return "success";
  return checking.value ? "checking" : "";
});

function resetDialog(): void {
  checkRequestId += 1;
  line.value = "";
  check.value = null;
  checking.value = false;
  saving.value = false;
  error.value = "";
}

function closeDialog(): void {
  if (busy.value) return;
  resetDialog();
  emit("close");
}

async function checkCurrentLine(value: string, requestId: number): Promise<void> {
  try {
    const result = await accounts.checkAccount(value);
    if (requestId !== checkRequestId || value !== line.value) return;
    check.value = result;
  } catch {
    if (requestId !== checkRequestId) return;
    error.value = "Không thể kiểm tra tài khoản.";
  } finally {
    if (requestId === checkRequestId) checking.value = false;
  }
}

watch(line, (value) => {
  const requestId = ++checkRequestId;
  check.value = null;
  error.value = "";
  if (!value.trim()) {
    checking.value = false;
    return;
  }
  checking.value = true;
  void checkCurrentLine(value, requestId);
});

watch(() => props.open, (value) => {
  if (!value) resetDialog();
});

async function addAccount(): Promise<void> {
  if (addDisabled.value) return;
  const requestedLine = line.value;
  saving.value = true;
  error.value = "";
  try {
    const result = await accounts.addAccount(requestedLine);
    feedback.success(`Đã thêm ${result.email}.`);
    saving.value = false;
    closeDialog();
  } catch {
    const requestId = ++checkRequestId;
    check.value = null;
    try {
      const result = await accounts.checkAccount(requestedLine);
      if (requestId === checkRequestId) {
        check.value = result;
        error.value = result.valid ? "Không thể thêm tài khoản." : "";
      }
    } catch {
      if (requestId === checkRequestId) {
        error.value = "Không thể thêm tài khoản.";
      }
    }
    feedback.error(error.value || check.value?.message || "Không thể thêm tài khoản.");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <GlassDialog
    :open="open"
    title="Thêm tài khoản"
    :morph-id="morphId"
    @close="closeDialog"
  >
    <template #trigger>
      <slot name="trigger" />
    </template>
    <label id="account-format" for="account-line">
      Nhập một tài khoản theo định dạng: email|password|secret
    </label>
    <input
      id="account-line"
      v-model="line"
      name="account"
      type="text"
      class="standard-control"
      data-material="standard-control"
      spellcheck="false"
      autocomplete="off"
      autocapitalize="off"
      aria-describedby="account-check"
      placeholder="user@example.com|password|TOTP_SECRET"
    >
    <p
      id="account-check"
      class="account-check-status"
      :class="statusState"
      :role="statusState === 'error' ? 'alert' : 'status'"
      aria-live="polite"
    >
      {{ statusMessage }}
    </p>
    <template #actions>
      <SurfaceActionButton
        :disabled="busy"
        @click="closeDialog"
      >
        Hủy
      </SurfaceActionButton>
      <SurfaceActionButton
        :busy="saving"
        :disabled="addDisabled"
        @click="addAccount"
      >
        Thêm
      </SurfaceActionButton>
    </template>
  </GlassDialog>
</template>
