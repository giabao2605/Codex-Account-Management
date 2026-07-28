<script setup lang="ts">
import { computed, ref, useId } from "vue";

import GlassButton from "@/components/glass/GlassButton.vue";
import GlassPopover from "@/components/glass/GlassPopover.vue";
import SurfaceActionButton from "@/components/glass/SurfaceActionButton.vue";
import type { AccountAction } from "@/stores/accounts.ts";
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
  resetProfile: [];
  delete: [];
}>();
const optionsOpen = ref(false);
const optionsId = `account-options-${useId()}`;
const optionsMorphId = `account-options-${props.account.id}`;

const quotaPercent = computed(() => (
  parseQuotaPercent(props.account.quota_remaining)
));
const quotaTone = computed(() => {
  if (quotaPercent.value === null) return "unknown";
  if (quotaPercent.value <= 0) return "empty";
  if (quotaPercent.value <= 20) return "low";
  return "good";
});
const otpRemaining = computed(() => {
  const remaining = props.account.otp_remaining_seconds;
  return remaining === null ? null : Math.max(0, Math.min(30, remaining));
});
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

function resetProfile(): void {
  closeOptions();
  emit("resetProfile");
}

function deleteAccount(): void {
  closeOptions();
  emit("delete");
}
</script>

<template>
  <article
    class="account-card standard-surface"
    data-material="standard"
    data-material-role="account-card"
    :aria-label="account.email"
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
            :disabled="account.otp === null"
            :aria-label="account.otp === null
              ? `OTP của ${account.email} chưa sẵn sàng`
              : `Sao chép mã OTP ${account.otp} của ${account.email}`"
            :title="account.otp === null ? 'OTP chưa sẵn sàng' : 'Bấm để sao chép OTP'"
            @click="copyOtp"
          >
            {{ account.otp ?? "Không khả dụng" }}
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
        <div class="meter-heading">
          <span>Quota</span>
          <strong>{{ account.quota_remaining }}</strong>
        </div>
        <progress
          v-if="quotaPercent !== null"
          class="quota-progress"
          :value="quotaPercent"
          max="100"
        />
        <small>{{ account.quota_cycle }}</small>
      </section>
    </div>

    <dl class="account-sync-details">
      <div><dt>Đồng bộ</dt><dd>{{ account.sync_status }}</dd></div>
      <div><dt>Đặt lại quota</dt><dd>{{ account.quota_reset_at }}</dd></div>
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
            :disabled="account.otp === null"
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
            data-action="reset-profile"
            :busy="isBusy('reset-profile')"
            @click="resetProfile"
          >
            Đặt lại profile
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
