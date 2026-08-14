<script setup lang="ts">
import { computed, ref, useId } from "vue";

import GlassButton from "@/components/glass/GlassButton.vue";
import GlassPopover from "@/components/glass/GlassPopover.vue";
import SurfaceActionButton from "@/components/glass/SurfaceActionButton.vue";
import type { AccountAction } from "@/stores/accounts.ts";
import { useSessionStore } from "@/stores/session.ts";
import type { AccountState } from "@/types/api.ts";
import {
  normalizedStatus,
  parseQuotaPercent,
  statusTone,
} from "@/utils/accounts.ts";

const props = withDefaults(defineProps<{
  account: AccountState;
  recommended: boolean;
  busyActions?: AccountAction[];
}>(), {
  busyActions: () => [],
});
const emit = defineEmits<{
  copyEmail: [];
  copyOtp: [];
  copySensitive: [field: "password" | "secret"];
  refresh: [];
  login: [];
  unlink: [];
  editPassword: [];
  delete: [];
}>();
const optionsOpen = ref(false);
const session = useSessionStore();
const optionsId = `account-options-${useId()}`;
const optionsMorphId = `account-options-${props.account.id}`;

const quotaWindows = computed(() => {
  const windows = props.account.quota_windows.length > 0
    ? props.account.quota_windows
    : [{
        quota_remaining: props.account.quota_remaining,
        quota_cycle: props.account.quota_cycle,
        quota_reset_at: props.account.quota_reset_at,
      }];
  return windows.slice(0, 2).map((window) => ({
    ...window,
    percent: parseQuotaPercent(window.quota_remaining),
  }));
});
const quotaTone = computed(() => {
  const known = quotaWindows.value
    .map((window) => window.percent)
    .filter((percent): percent is number => percent !== null);
  if (known.length === 0) return "unknown";
  const minimum = Math.min(...known);
  if (minimum <= 0) return "empty";
  if (minimum <= 20) return "low";
  return "good";
});
const otpRemaining = computed(() => {
  const remaining = session.otpRemainingSeconds(props.account);
  return remaining === null ? null : Math.max(0, Math.min(30, remaining));
});
const otpValue = computed(() => session.otpValue(props.account));
const tone = computed(() => statusTone(props.account));
const connectionStatus = computed(() => normalizedStatus(props.account));
const isUnlinked = computed(() => (
  connectionStatus.value.includes("chưa liên kết")
));
const needsLogin = computed(() => (
  isUnlinked.value
  || ["đăng nhập", "đăng xuất", "sai tài khoản"].some(
    (term) => connectionStatus.value.includes(term),
  )
));
const loginActionLabel = computed(() => (
  isUnlinked.value ? "Liên kết Codex" : "Đăng nhập lại"
));

function isBusy(action: AccountAction): boolean {
  return props.busyActions.includes(action);
}

function closeOptions(): void {
  optionsOpen.value = false;
}

function copyOtp(): void {
  closeOptions();
  emit("copyOtp");
}

function copySecret(): void {
  closeOptions();
  emit("copySensitive", "secret");
}

function refresh(): void {
  closeOptions();
  emit("refresh");
}

function login(): void {
  closeOptions();
  emit("login");
}

function unlink(): void {
  closeOptions();
  emit("unlink");
}

function editPassword(): void {
  closeOptions();
  emit("editPassword");
}

function deleteAccount(): void {
  closeOptions();
  emit("delete");
}
</script>

<template>
  <article
    :id="`account-${account.id}`"
    class="account-card standard-surface"
    data-material="standard"
    data-material-role="account-card"
    :aria-label="account.email"
    tabindex="-1"
  >
    <header class="account-card-header">
      <div class="account-identity">
        <h3 class="account-email" :title="account.email">{{ account.email }}</h3>
        <div class="account-badges">
          <span class="plan-badge">{{ account.plan_type }}</span>
          <span v-if="recommended" class="recommendation-badge">Đề xuất sử dụng</span>
        </div>
      </div>
      <span
        class="status"
        :class="`is-${tone}`"
        :title="account.account_state"
      >
        {{ account.account_state }}
      </span>
    </header>

    <div class="account-meter-grid">
      <section
        class="account-meter otp-meter standard-surface"
        data-material="standard-inset"
        aria-label="Trạng thái OTP"
      >
        <div class="otp-heading">
          <span>OTP</span>
          <button
            class="otp-copy-button"
            type="button"
            data-action="otp-value"
            :disabled="otpValue === null"
            :aria-label="otpValue === null
              ? `OTP của ${account.email} chưa sẵn sàng`
              : `Sao chép mã OTP ${otpValue} của ${account.email}`"
            :title="otpValue === null ? 'OTP chưa sẵn sàng' : 'Bấm để sao chép OTP'"
            @click="copyOtp"
          >
            {{ otpValue ?? "Không khả dụng" }}
          </button>
        </div>
        <div class="otp-validity">
          <progress
            v-if="otpRemaining !== null"
            class="otp-progress"
            :value="otpRemaining"
            max="30"
          />
          <small>
            {{ otpRemaining === null ? "Chờ đồng bộ thời gian" : `Còn ${otpRemaining} giây` }}
          </small>
        </div>
      </section>
      <section
        class="account-meter quota-meter standard-surface"
        :class="`is-${quotaTone}`"
        data-material="standard-inset"
        aria-label="Trạng thái quota"
      >
        <span class="quota-title">Quota</span>
        <div class="quota-window-list">
          <div
            v-for="window in quotaWindows"
            :key="`${window.quota_cycle}-${window.quota_reset_at}`"
            class="quota-window"
          >
            <div class="meter-heading">
              <small>{{ window.quota_cycle }}</small>
              <strong>{{ window.quota_remaining }}</strong>
            </div>
            <progress
              v-if="window.percent !== null"
              class="quota-progress"
              :value="window.percent"
              max="100"
              :aria-label="`Quota ${window.quota_cycle} còn ${window.quota_remaining}`"
            />
          </div>
        </div>
      </section>
    </div>

    <dl class="account-sync-details">
      <div><dt>Đồng bộ</dt><dd>{{ account.sync_status }}</dd></div>
      <div class="quota-reset-details">
        <dt>Đặt lại quota</dt>
        <dd
          v-for="window in quotaWindows"
          :key="`${window.quota_cycle}-${window.quota_reset_at}`"
          class="quota-reset-row"
        >
          <span>{{ window.quota_cycle }}</span>
          <strong>{{ window.quota_reset_at }}</strong>
        </dd>
      </div>
      <div><dt>Lần đồng bộ cuối</dt><dd>{{ account.last_sync }}</dd></div>
    </dl>

    <div
      class="account-primary-actions"
      data-liquid-container="actions"
      role="group"
      :aria-label="`Hành động chính cho ${account.email}`"
    >
      <GlassButton
        variant="quiet"
        depth="thin"
        data-action="email"
        @click="emit('copyEmail')"
      >
        Email
      </GlassButton>
      <GlassButton
        variant="quiet"
        depth="thin"
        data-action="password"
        :busy="isBusy('password')"
        @click="emit('copySensitive', 'password')"
      >
        Mật khẩu
      </GlassButton>
      <GlassPopover
        v-model:open="optionsOpen"
        class="account-options-popover"
        :label="`Tùy chọn cho ${account.email}`"
        :morph-id="optionsMorphId"
        placement="end"
      >
        <template #trigger>
          <GlassButton
            variant="quiet"
            depth="thin"
            :morph-id="optionsMorphId"
            data-action="options"
            aria-haspopup="menu"
            :aria-expanded="optionsOpen"
            :aria-controls="optionsId"
          >
            Tùy chọn
          </GlassButton>
        </template>
        <div
          :id="optionsId"
          class="account-option-actions"
          role="menu"
          data-material-layer="floating-actions"
        >
          <SurfaceActionButton
            role="menuitem"
            data-action="otp"
            :disabled="otpValue === null"
            @click="copyOtp"
          >
            OTP
          </SurfaceActionButton>
          <SurfaceActionButton
            role="menuitem"
            data-action="secret"
            :busy="isBusy('secret')"
            @click="copySecret"
          >
            Secret
          </SurfaceActionButton>
          <SurfaceActionButton
            role="menuitem"
            data-action="refresh"
            :busy="isBusy('refresh')"
            @click="refresh"
          >
            Đồng bộ
          </SurfaceActionButton>
          <SurfaceActionButton
            v-if="needsLogin"
            role="menuitem"
            data-action="login"
            :busy="isBusy('login')"
            @click="login"
          >
            {{ loginActionLabel }}
          </SurfaceActionButton>
          <SurfaceActionButton
            v-if="!isUnlinked"
            role="menuitem"
            data-action="unlink"
            :busy="isBusy('unlink')"
            @click="unlink"
          >
            Ngắt liên kết
          </SurfaceActionButton>
          <SurfaceActionButton
            role="menuitem"
            data-action="edit-password"
            @click="editPassword"
          >
            Chỉnh sửa mật khẩu
          </SurfaceActionButton>
          <SurfaceActionButton
            tone="danger"
            role="menuitem"
            data-action="delete"
            :busy="isBusy('delete')"
            @click="deleteAccount"
          >
            Xóa tài khoản
          </SurfaceActionButton>
        </div>
      </GlassPopover>
    </div>
  </article>
</template>
