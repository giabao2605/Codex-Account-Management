import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  EXPECTED_API_SCHEMA_VERSION,
  LocalApiClient,
} from "@/api/client.ts";
import type { ApplicationState } from "@/types/api.ts";

export type ConnectionStatus =
  | "booting"
  | "ready"
  | "offline"
  | "incompatible"
  | "stopping";

export const useSessionStore = defineStore("session", () => {
  const connectionStatus = ref<ConnectionStatus>("booting");
  const buildId = ref("");
  const csrfToken = ref("");
  const state = shallowRef<ApplicationState | null>(null);
  const errorMessage = ref("");
  const lastUpdated = ref<Date | null>(null);
  let apiClient: LocalApiClient | null = null;
  let pollTimer: number | null = null;
  let pollInFlight = false;

  const accountCount = computed(() => state.value?.accounts.length ?? 0);

  async function bootstrap(accessToken: string): Promise<void> {
    connectionStatus.value = "booting";
    errorMessage.value = "";
    buildId.value = "";
    csrfToken.value = "";
    state.value = null;
    lastUpdated.value = null;
    apiClient = new LocalApiClient(accessToken, () => csrfToken.value);

    try {
      const payload = await apiClient.bootstrap();
      if (payload.api_schema_version !== EXPECTED_API_SCHEMA_VERSION) {
        connectionStatus.value = "incompatible";
        errorMessage.value = "Phiên bản giao diện và backend không tương thích.";
        return;
      }

      csrfToken.value = payload.csrf_token;
      buildId.value = payload.build_id;
      state.value = payload.state;
      lastUpdated.value = new Date();
      connectionStatus.value = "ready";
    } catch {
      connectionStatus.value = "offline";
      errorMessage.value = "Không thể kết nối ứng dụng local.";
    }
  }

  function getClient(): LocalApiClient {
    if (!apiClient) {
      throw new ApiError("Phiên truy cập chưa sẵn sàng.", 401);
    }
    return apiClient;
  }

  async function pollState(): Promise<void> {
    if (
      pollInFlight
      || connectionStatus.value === "incompatible"
      || connectionStatus.value === "stopping"
    ) {
      return;
    }
    pollInFlight = true;
    try {
      state.value = await getClient().state();
      connectionStatus.value = "ready";
      errorMessage.value = "";
      lastUpdated.value = new Date();
    } catch {
      connectionStatus.value = "offline";
      errorMessage.value = "Không thể cập nhật trạng thái local.";
    } finally {
      pollInFlight = false;
    }
  }

  function startPolling(intervalMilliseconds = 1_000): void {
    stopPolling();
    pollTimer = window.setInterval(() => {
      void pollState();
    }, intervalMilliseconds);
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function shutdown(): Promise<"accepted" | "connection-closed"> {
    stopPolling();
    connectionStatus.value = "stopping";
    try {
      await getClient().shutdown();
      return "accepted";
    } catch (error) {
      if (error instanceof ApiError && error.status === 0) {
        return "connection-closed";
      }
      connectionStatus.value = state.value ? "ready" : "offline";
      startPolling();
      throw error;
    }
  }

  return {
    accountCount,
    bootstrap,
    buildId,
    connectionStatus,
    csrfToken,
    errorMessage,
    getClient,
    lastUpdated,
    pollState,
    shutdown,
    startPolling,
    state,
    stopPolling,
  };
});
