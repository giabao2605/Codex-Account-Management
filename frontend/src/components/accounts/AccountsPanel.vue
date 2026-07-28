<script setup lang="ts">
import { ref } from "vue";

import GlassButton from "@/components/glass/GlassButton.vue";
import GlassSelectPopover from "@/components/glass/GlassSelectPopover.vue";
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
const archiveBusy = ref(false);
const importMorphId = "import-account-dialog";
const actionTypes: AccountAction[] = [
  "refresh",
  "login",
  "unlink",
  "reset-profile",
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
  } catch {
    feedback.error(`Không thể sao chép ${label}.`);
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
  } catch {
    feedback.error(`Không thể sao chép ${label}.`);
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
  } catch {
    feedback.error("Không thể làm mới tài khoản.");
  }
}

async function lifecycle(
  account: AccountState,
  action: "login" | "unlink" | "reset-profile",
): Promise<void> {
  if (
    action !== "login"
    && !window.confirm(`Xác nhận thao tác với ${account.email}?`)
  ) {
    return;
  }
  try {
    await accounts.lifecycle(account.id, action);
    const message = {
      login: "Đã mở quy trình đăng nhập.",
      unlink: "Đã bỏ liên kết profile.",
      "reset-profile": "Đã đặt lại profile.",
    }[action];
    feedback.success(message);
  } catch {
    feedback.error("Không thể cập nhật profile tài khoản.");
  }
}

async function remove(account: AccountState): Promise<void> {
  if (!window.confirm(`Xóa ${account.email}? Thao tác này không thể hoàn tác.`)) {
    return;
  }
  try {
    await accounts.deleteAccount(account.id);
    feedback.success("Đã xóa tài khoản.");
  } catch {
    feedback.error("Không thể xóa tài khoản.");
  }
}

async function archiveOrphans(): Promise<void> {
  const count = session.state?.orphan_profile_count ?? 0;
  if (
    count === 0
    || !window.confirm(`Lưu trữ ${count} profile mồ côi?`)
  ) {
    return;
  }
  archiveBusy.value = true;
  try {
    const result = await accounts.archiveOrphans();
    feedback.success(`Đã lưu trữ ${result.archived} profile mồ côi.`);
  } catch {
    feedback.error("Không thể lưu trữ profile mồ côi.");
  } finally {
    archiveBusy.value = false;
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
        @refresh="refresh(account.id)"
        @login="lifecycle(account, 'login')"
        @unlink="lifecycle(account, 'unlink')"
        @reset-profile="lifecycle(account, 'reset-profile')"
        @delete="remove(account)"
      />
    </div>
    <p v-if="!accounts.filteredAccounts.length" class="empty">
      Không có tài khoản phù hợp.
    </p>
    <GlassButton
      v-if="session.state?.orphan_profile_count"
      variant="quiet"
      data-action="archive-orphans"
      :busy="archiveBusy"
      @click="archiveOrphans"
    >
      Lưu trữ {{ session.state.orphan_profile_count }} profile mồ côi
    </GlassButton>
  </section>
</template>
