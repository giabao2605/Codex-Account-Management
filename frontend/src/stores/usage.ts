import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";

import { userFacingError } from "@/api/client.ts";
import type { TokenUsageResponse } from "@/types/api.ts";
import type { HeatmapMode } from "@/utils/heatmap.ts";
import { useSessionStore } from "./session.ts";

const TOKEN_CACHE_MILLISECONDS = 300_000;

export interface UsageAccountOption {
  accountId: string;
  email: string;
}

export const useUsageStore = defineStore("usage", () => {
  const session = useSessionStore();
  const data = shallowRef<TokenUsageResponse | null>(null);
  const fetchedAt = ref(0);
  const isLoading = ref(false);
  const errorMessage = ref("");
  const selectedAccountId = ref("all");
  const heatmapMode = ref<HeatmapMode>("daily");
  let inFlight: Promise<void> | null = null;

  const accountOptions = computed<UsageAccountOption[]>(() => {
    const byId = new Map<string, string>();
    for (const account of data.value?.accounts ?? []) {
      byId.set(account.account_id, account.email);
    }
    for (const account of session.state?.usage_statistics.accounts ?? []) {
      byId.set(account.account_id, account.email);
    }
    return [...byId.entries()]
      .map(([accountId, email]) => ({ accountId, email }))
      .sort((left, right) => (
        left.email.localeCompare(right.email, "vi", { sensitivity: "base" })
        || left.accountId.localeCompare(right.accountId)
      ));
  });

  const selectedTokenAccount = computed(() => (
    selectedAccountId.value === "all"
      ? null
      : data.value?.accounts.find(
        (account) => account.account_id === selectedAccountId.value,
      ) ?? null
  ));
  const selectedQuotaAccount = computed(() => (
    session.state?.usage_statistics.accounts.find(
      (account) => account.account_id === selectedAccountId.value,
    ) ?? null
  ));
  const selectedBuckets = computed(() => {
    if (!data.value) {
      return null;
    }
    return selectedAccountId.value === "all"
      ? data.value.aggregate.daily_buckets
      : selectedTokenAccount.value?.daily_buckets ?? null;
  });

  function fetchUsage(force = false): Promise<void> {
    if (inFlight) return inFlight;
    if (
      !force
      && data.value
      && Date.now() - fetchedAt.value < TOKEN_CACHE_MILLISECONDS
    ) {
      return Promise.resolve();
    }
    isLoading.value = true;
    errorMessage.value = "";
    const request = session.getClient().tokenUsage()
      .then((payload) => {
        data.value = payload;
        fetchedAt.value = Date.now();
      })
      .catch((error) => {
        const fallback = data.value
          ? "Không thể làm mới; đang hiển thị dữ liệu cũ."
          : "Chưa thể tải dữ liệu token.";
        const detail = userFacingError(error, fallback);
        errorMessage.value = data.value && detail !== fallback
          ? `${detail} Đang hiển thị dữ liệu cũ.`
          : detail;
      })
      .finally(() => {
        if (inFlight === request) inFlight = null;
        isLoading.value = false;
      });
    inFlight = request;
    return request;
  }

  function invalidate(): void {
    fetchedAt.value = 0;
  }

  return {
    accountOptions,
    data,
    errorMessage,
    fetchUsage,
    heatmapMode,
    invalidate,
    isLoading,
    selectedAccountId,
    selectedBuckets,
    selectedQuotaAccount,
    selectedTokenAccount,
  };
});
