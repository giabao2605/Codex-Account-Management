import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  AccountCheckResponse,
  AccountState,
  AddAccountResponse,
  ArchiveProfilesResponse,
} from "@/types/api.ts";
import {
  accountMatchesFilter,
  type AccountFilter,
} from "@/utils/accounts.ts";
import { useSessionStore } from "./session.ts";

export type AccountAction =
  | "refresh"
  | "login"
  | "unlink"
  | "reset-profile"
  | "delete"
  | "password"
  | "secret";

export const useAccountsStore = defineStore("accounts", () => {
  const session = useSessionStore();
  const filter = ref<AccountFilter>("all");
  const busyKeys = ref<string[]>([]);

  const accounts = computed(() => session.state?.accounts ?? []);
  const filteredAccounts = computed(() => (
    accounts.value.filter((account) => (
      accountMatchesFilter(account, filter.value)
    ))
  ));

  function busyKey(accountId: string, action: AccountAction): string {
    return `${accountId}:${action}`;
  }

  function isBusy(accountId: string, action: AccountAction): boolean {
    return busyKeys.value.includes(busyKey(accountId, action));
  }

  async function withBusy<T>(
    accountId: string,
    action: AccountAction,
    operation: () => Promise<T>,
  ): Promise<T> {
    const key = busyKey(accountId, action);
    busyKeys.value = [...busyKeys.value, key];
    try {
      return await operation();
    } finally {
      busyKeys.value = busyKeys.value.filter((candidate) => candidate !== key);
    }
  }

  async function refresh(accountId: string | null): Promise<boolean> {
    const key = accountId ?? "all-accounts";
    return withBusy(key, "refresh", async () => {
      const result = await session.getClient().refresh(accountId);
      await session.pollState();
      return result.accepted;
    });
  }

  async function sensitiveValue(
    accountId: string,
    field: "password" | "secret",
  ): Promise<string> {
    return withBusy(accountId, field, async () => {
      const response = await session.getClient().sensitiveValue(
        accountId,
        field,
      );
      return response.value;
    });
  }

  async function lifecycle(
    accountId: string,
    action: "login" | "unlink" | "reset-profile",
  ): Promise<void> {
    await withBusy(accountId, action, async () => {
      const client = session.getClient();
      if (action === "login") {
        await client.login(accountId);
      } else if (action === "unlink") {
        await client.unlink(accountId);
      } else {
        await client.resetProfile(accountId);
      }
      await session.pollState();
    });
  }

  async function deleteAccount(accountId: string): Promise<void> {
    await withBusy(accountId, "delete", async () => {
      await session.getClient().deleteAccount(accountId);
      await session.pollState();
    });
  }

  async function checkAccount(lines: string): Promise<AccountCheckResponse> {
    return session.getClient().checkAccount(lines);
  }

  async function addAccount(lines: string): Promise<AddAccountResponse> {
    const result = await session.getClient().addAccount(lines);
    await session.pollState();
    return result;
  }

  async function archiveOrphans(): Promise<ArchiveProfilesResponse> {
    const result = await session.getClient().archiveOrphans();
    await session.pollState();
    return result;
  }

  function accountById(accountId: string): AccountState | undefined {
    return accounts.value.find((account) => account.id === accountId);
  }

  return {
    accountById,
    accounts,
    addAccount,
    archiveOrphans,
    checkAccount,
    deleteAccount,
    filter,
    filteredAccounts,
    isBusy,
    lifecycle,
    refresh,
    sensitiveValue,
  };
});
