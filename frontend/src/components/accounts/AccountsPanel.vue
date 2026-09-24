<script setup lang="ts">
import { ref } from "vue";

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
const secretAccount = ref<AccountState | null>(null);
const updatedSecret = ref("");
const secretSaving = ref(false);
const plusExpirationAccount = ref<AccountState | null>(null);
const updatedPlusExpiration = ref("");
const plusExpirationSaving = ref(false);
const importMorphId = "import-account-dialog";
const actionTypes: AccountAction[] = [
  "refresh",
  "login",
  "unlink",
  "delete",
  "plusExpiration",
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

function openSecretEditor(account: AccountState): void {
  updatedSecret.value = "";
  secretAccount.value = account;
}

function closeSecretEditor(): void {
  if (secretSaving.value) return;
  updatedSecret.value = "";
  secretAccount.value = null;
}

async function copyCurrentSecret(): Promise<void> {
  if (secretAccount.value) {
    await copySensitive(secretAccount.value, "secret");
  }
}

async function saveSecret(): Promise<void> {
  const account = secretAccount.value;
  const secret = updatedSecret.value;
  if (
    secretSaving.value || !account || !secret.trim()
    || accounts.isBusy(account.id, "secret")
  ) return;

  secretSaving.value = true;
  try {
    await accounts.updateSecret(account.id, secret);
    feedback.success(session.connectionStatus === "ready"
      ? "Đã cập nhật secret 2FA và mã OTP."
      : "Đã lưu secret 2FA. Mã OTP sẽ hiện khi kết nối lại.");
    updatedSecret.value = "";
    secretAccount.value = null;
  } catch (error) {
    feedback.error(userFacingError(error, "Không thể cập nhật secret 2FA."));
  } finally {
    secretSaving.value = false;
  }
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

function openPlusExpirationEditor(account: AccountState): void {
  updatedPlusExpiration.value = account.plus_expires_at ?? "";
  plusExpirationAccount.value = account;
}

function closePlusExpirationEditor(): void {
  if (plusExpirationSaving.value) return;
  updatedPlusExpiration.value = "";
  plusExpirationAccount.value = null;
}

async function savePlusExpiration(): Promise<void> {
  const account = plusExpirationAccount.value;
  if (plusExpirationSaving.value || !account) return;

  plusExpirationSaving.value = true;
  try {
    await accounts.updatePlusExpiration(
      account.id,
      updatedPlusExpiration.value || null,
    );
    feedback.success("Đã cập nhật ngày hết hạn Plus.");
    updatedPlusExpiration.value = "";
    plusExpirationAccount.value = null;
  } catch (error) {
    feedback.error(userFacingError(
      error,
      "Không thể cập nhật ngày hết hạn Plus.",
    ));
  } finally {
    plusExpirationSaving.value = false;
  }
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
        @edit-secret="openSecretEditor(account)"
        @refresh="refresh(account.id)"
        @login="lifecycle(account, 'login')"
        @unlink="lifecycle(account, 'unlink')"
        @edit-password="openPasswordEditor(account)"
        @edit-plus-expiration="openPlusExpirationEditor(account)"
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
    <GlassDialog
      v-if="secretAccount !== null"
      :open="true"
      title="Secret 2FA"
      @close="closeSecretEditor"
    >
      <label for="current-secret">Secret hiện tại</label>
      <div class="secret-copy-row">
        <input
          id="current-secret"
          class="standard-control"
          type="text"
          value="Đã lưu trong ứng dụng"
          readonly
          tabindex="-1"
        >
        <SurfaceActionButton
          data-action="copy-secret"
          :busy="accounts.isBusy(secretAccount.id, 'secret')"
          :disabled="secretSaving"
          :aria-label="`Sao chép secret của ${secretAccount.email}`"
          title="Sao chép secret"
          @click="copyCurrentSecret"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="8" y="8" width="11" height="11" rx="2" />
            <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
          </svg>
        </SurfaceActionButton>
      </div>
      <label for="updated-secret">Secret mới</label>
      <input
        id="updated-secret"
        v-model="updatedSecret"
        name="updated-secret"
        type="password"
        class="standard-control"
        autocomplete="new-password"
        spellcheck="false"
        autocapitalize="off"
        maxlength="256"
        @keydown.enter="saveSecret"
      >
      <template #actions>
        <SurfaceActionButton :disabled="secretSaving" @click="closeSecretEditor">Hủy</SurfaceActionButton>
        <SurfaceActionButton
          data-action="save-secret"
          :busy="secretSaving"
          :disabled="!updatedSecret.trim() || accounts.isBusy(secretAccount.id, 'secret')"
          @click="saveSecret"
        >
          Lưu
        </SurfaceActionButton>
      </template>
    </GlassDialog>
    <GlassDialog
      v-if="plusExpirationAccount !== null"
      :open="true"
      title="Chỉnh sửa hạn Plus"
      @close="closePlusExpirationEditor"
    >
      <label for="updated-plus-expiration">
        Ngày hết hạn Plus cho {{ plusExpirationAccount?.email }}
      </label>
      <input
        id="updated-plus-expiration"
        v-model="updatedPlusExpiration"
        name="updated-plus-expiration"
        type="date"
        class="standard-control"
        data-material="standard-control"
        autocomplete="off"
        aria-describedby="plus-expiration-update-note"
        @keydown.enter="savePlusExpiration"
      >
      <p id="plus-expiration-update-note">
        Đây là ngày tự nhập. Codex chỉ trả loại gói, không trả ngày hết hạn.
        Xóa ngày để đặt lại thành chưa rõ.
      </p>
      <template #actions>
        <SurfaceActionButton
          :disabled="plusExpirationSaving"
          @click="closePlusExpirationEditor"
        >
          Hủy
        </SurfaceActionButton>
        <SurfaceActionButton
          data-action="save-plus-expiration"
          :busy="plusExpirationSaving"
          @click="savePlusExpiration"
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
