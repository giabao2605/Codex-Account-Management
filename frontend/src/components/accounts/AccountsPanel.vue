<script setup lang="ts">
import { computed, nextTick, ref } from "vue";

import { userFacingError } from "@/api/client.ts";
import GlassButton from "@/components/glass/GlassButton.vue";
import GlassDialog from "@/components/glass/GlassDialog.vue";
import GlassSelectPopover from "@/components/glass/GlassSelectPopover.vue";
import SurfaceActionButton from "@/components/glass/SurfaceActionButton.vue";
import { useAccountsStore, type AccountAction } from "@/stores/accounts.ts";
import { useFeedbackStore } from "@/stores/feedback.ts";
import { useSessionStore } from "@/stores/session.ts";
import type { AccountState } from "@/types/api.ts";
import type { AccountFilter } from "@/utils/accounts.ts";
import AccountCard from "./AccountCard.vue";
import AccountOverview from "./AccountOverview.vue";
import ImportDialog from "./ImportDialog.vue";

const accounts = useAccountsStore();
const feedback = useFeedbackStore();
const session = useSessionStore();
const importOpen = ref(false);
const passwordAccount = ref<AccountState | null>(null);
const updatedPassword = ref("");
const passwordSaving = ref(false);
const importMorphId = "import-account-dialog";
const recommendationQueue = computed(() => (
  session.state?.recommendation_queue ?? []
));
const recommendation = computed(() => recommendationQueue.value[0] ?? null);
const fallbackRecommendation = computed(() => (
  recommendationQueue.value[1] ?? null
));
const nextReset = computed(() => (
  session.state?.usage_statistics.next_reset_at ?? "Chưa rõ"
));
const actionTypes: AccountAction[] = [
  "refresh",
  "login",
  "unlink",
  "delete",
  "password",
  "secret",
];
const filters: Array<{ value: AccountFilter; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "usable", label: "Có thể dùng" },
  { value: "attention", label: "Cần chú ý" },
  { value: "quota-available", label: "Quota còn" },
  { value: "quota-low", label: "Quota thấp" },
  { value: "quota-empty", label: "Quota hết" },
  { value: "quota-unknown", label: "Chưa rõ quota" },
];

function busyActions(accountId: string): AccountAction[] {
  return actionTypes.filter((action) => accounts.isBusy(accountId, action));
}

function setFilter(value: string): void {
  accounts.filter = value as AccountFilter;
}

async function copy(value: string | null, label: string): Promise<void> {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    feedback.success(`Đã sao chép ${label}.`);
  } catch (error) {
    feedback.error(userFacingError(error, `Không thể sao chép ${label}.`));
  }
}

async function copySensitive(
  account: AccountState,
  field: "password" | "secret",
): Promise<void> {
  const label = field === "password" ? "mật khẩu" : "secret";
  try {
    const transientValue = await accounts.sensitiveValue(account.id, field);
    await navigator.clipboard.writeText(transientValue);
    feedback.success(`Đã sao chép ${label}.`);
  } catch (error) {
    feedback.error(userFacingError(error, `Không thể sao chép ${label}.`));
  }
}

async function refresh(accountId: string | null): Promise<void> {
  try {
    const accepted = await accounts.refresh(accountId);
    if (accepted) {
      feedback.success(
        accountId ? "Đã yêu cầu làm mới tài khoản." : "Đã yêu cầu làm mới tất cả tài khoản.",
      );
    } else {
      feedback.error("Không thể bắt đầu làm mới tài khoản.");
    }
  } catch (error) {
    feedback.error(userFacingError(error, "Không thể làm mới tài khoản."));
  }
}

async function lifecycle(
  account: AccountState,
  action: "login" | "unlink",
): Promise<void> {
  if (
    action === "unlink"
    && !window.confirm(
      `Ngắt liên kết ${account.email}? Profile Codex local sẽ bị xóa vĩnh viễn.`,
    )
  ) {
    return;
  }
  try {
    await accounts.lifecycle(account.id, action);
    const message = action === "login"
      ? "Đã mở quy trình đăng nhập."
      : "Đã bỏ liên kết và xóa profile Codex local.";
    feedback.success(message);
  } catch (error) {
    feedback.error(userFacingError(
      error,
      "Không thể cập nhật profile tài khoản.",
    ));
  }
}

async function remove(account: AccountState): Promise<void> {
  if (!window.confirm(`Xóa ${account.email}? Thao tác này không thể hoàn tác.`)) {
    return;
  }
  try {
    await accounts.deleteAccount(account.id);
    feedback.success("Đã xóa tài khoản.");
  } catch (error) {
    feedback.error(userFacingError(error, "Không thể xóa tài khoản."));
  }
}

function openPasswordEditor(account: AccountState): void {
  updatedPassword.value = "";
  passwordAccount.value = account;
}

function closePasswordEditor(): void {
  if (passwordSaving.value) return;
  updatedPassword.value = "";
  passwordAccount.value = null;
}

async function savePassword(): Promise<void> {
  const account = passwordAccount.value;
  const password = updatedPassword.value;
  if (passwordSaving.value || !account || !password.trim()) return;

  passwordSaving.value = true;
  try {
    await accounts.updatePassword(account.id, password);
    feedback.success("Đã cập nhật mật khẩu đã lưu.");
    updatedPassword.value = "";
    passwordAccount.value = null;
  } catch (error) {
    feedback.error(userFacingError(error, "Không thể cập nhật mật khẩu."));
  } finally {
    passwordSaving.value = false;
  }
}

async function focusRecommendation(): Promise<void> {
  const accountId = recommendation.value?.account_id;
  if (!accountId) return;
  accounts.filter = "all";
  await nextTick();
  const card = document.getElementById(`account-${accountId}`);
  card?.scrollIntoView({ behavior: "smooth", block: "center" });
  card?.focus({ preventScroll: true });
}

</script>

<template>
  <section class="accounts-shell" aria-labelledby="accounts-heading">
    <div class="panel-heading accounts-heading">
      <div class="accounts-heading-main">
        <h2 id="accounts-heading">
          Tổng tài khoản: {{ session.state?.accounts.length ?? 0 }}
        </h2>
      </div>
      <div class="panel-actions">
        <GlassButton
          variant="quiet"
          :busy="accounts.isBusy('all-accounts', 'refresh')"
          @click="refresh(null)"
        >
          Làm mới tất cả
        </GlassButton>
        <ImportDialog
          :open="importOpen"
          :morph-id="importMorphId"
          @close="importOpen = false"
        >
          <template #trigger>
            <GlassButton
              shape="capsule"
              :morph-id="importMorphId"
              @click="importOpen = true"
            >
              Thêm tài khoản
            </GlassButton>
          </template>
        </ImportDialog>
      </div>
    </div>
    <section
      class="account-smart-queue standard-surface"
      data-material="standard"
      aria-label="Hàng đợi tài khoản thông minh"
    >
      <div class="account-smart-queue-heading">
        <div>
          <p class="data-label">Hàng đợi tài khoản thông minh</p>
          <h3 v-if="recommendation">Nên dùng lúc này</h3>
          <h3 v-else>Chưa có đề xuất</h3>
        </div>
        <GlassButton
          variant="quiet"
          data-action="refresh-recommendation"
          :busy="accounts.isBusy('all-accounts', 'refresh')"
          @click="refresh(null)"
        >
          Đánh giá lại
        </GlassButton>
      </div>
      <div
        v-if="recommendation"
        class="account-queue-item is-recommended"
        data-queue-role="recommended"
      >
        <div>
          <strong>{{ recommendation.email }}</strong>
          <p>{{ recommendation.reason }}</p>
        </div>
        <GlassButton
          variant="lite"
          data-action="focus-recommendation"
          @click="focusRecommendation"
        >
          Xem tài khoản
        </GlassButton>
      </div>
      <p v-else class="account-queue-empty">
        Chưa có tài khoản đủ dữ liệu để đề xuất. Hãy đồng bộ lại trạng thái.
      </p>
      <div
        v-if="fallbackRecommendation"
        class="account-queue-item"
        data-queue-role="fallback"
      >
        <span>Dự phòng</span>
        <strong>{{ fallbackRecommendation.email }}</strong>
        <span>{{ fallbackRecommendation.quota_remaining }}</span>
      </div>
      <div class="account-queue-summary">
        <span>Reset gần nhất: {{ nextReset }}</span>
        <span>
          Hết quota: {{ session.state?.usage_statistics.exhausted_accounts ?? 0 }}
        </span>
      </div>
    </section>
    <div class="account-toolbar">
      <AccountOverview />
      <GlassSelectPopover
        class="account-filter-control"
        trigger-class="account-filter-trigger"
        label="Lọc tài khoản"
        morph-id="account-filter"
        :model-value="accounts.filter"
        :options="filters"
        @update:model-value="setFilter"
      />
    </div>

    <div class="account-grid" data-content-layer="standard">
      <AccountCard
        v-for="account in accounts.filteredAccounts"
        :key="account.id"
        :account="account"
        :recommended="session.state?.recommendation?.account_id === account.id"
        :busy-actions="busyActions(account.id)"
        @copy-email="copy(account.email, 'email')"
        @copy-otp="copy(account.otp, 'OTP')"
        @copy-sensitive="copySensitive(account, $event)"
        @refresh="refresh(account.id)"
        @login="lifecycle(account, 'login')"
        @unlink="lifecycle(account, 'unlink')"
        @edit-password="openPasswordEditor(account)"
        @delete="remove(account)"
      />
    </div>
    <GlassDialog
      v-if="passwordAccount !== null"
      :open="true"
      title="Chỉnh sửa mật khẩu"
      @close="closePasswordEditor"
    >
      <label for="updated-password">
        Mật khẩu mới cho {{ passwordAccount?.email }}
      </label>
      <input
        id="updated-password"
        v-model="updatedPassword"
        name="updated-password"
        type="password"
        class="standard-control"
        data-material="standard-control"
        autocomplete="new-password"
        maxlength="4096"
        aria-describedby="password-update-note"
        @keydown.enter="savePassword"
      >
      <p id="password-update-note">
        Chỉ cập nhật mật khẩu lưu trong ứng dụng này; không đổi mật khẩu
        OpenAI/ChatGPT và không cần liên kết lại Codex.
      </p>
      <template #actions>
        <SurfaceActionButton
          :disabled="passwordSaving"
          @click="closePasswordEditor"
        >
          Hủy
        </SurfaceActionButton>
        <SurfaceActionButton
          data-action="save-password"
          :busy="passwordSaving"
          :disabled="!updatedPassword.trim()"
          @click="savePassword"
        >
          Lưu
        </SurfaceActionButton>
      </template>
    </GlassDialog>
    <p v-if="!accounts.filteredAccounts.length" class="empty">
      Không có tài khoản phù hợp.
    </p>
  </section>
</template>
