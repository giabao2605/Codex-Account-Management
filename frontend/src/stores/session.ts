import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";

import {
  ApiError,
  EXPECTED_API_SCHEMA_VERSION,
  LocalApiClient,
  userFacingError,
} from "@/api/client.ts";
import type { AccountState, ApplicationState } from "@/types/api.ts";

export type ConnectionStatus =
  | "booting"
  | "ready"
  | "offline"
  | "incompatible"
  | "stopping";

export const useSessionStore = defineStore("session", () => {
  const stateRefreshIntervalMilliseconds = 5_000;
  const connectionStatus = ref<ConnectionStatus>("booting");
  const buildId = ref("");
  const csrfToken = ref("");
  const state = shallowRef<ApplicationState | null>(null);
  const otpElapsedSeconds = ref(0);
  const errorMessage = ref("");
  const lastUpdated = ref<Date | null>(null);
  let apiClient: LocalApiClient | null = null;
  let pollTimer: number | null = null;
  let pollInFlight = false;
  let lastPollTick = 0;
  let countdownRemainderMilliseconds = 0;
  let millisecondsSinceStateRefresh = 0;

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
      applyServerState(payload.state);
      connectionStatus.value = "ready";
    } catch (error) {
      connectionStatus.value = "offline";
      errorMessage.value = userFacingError(
        error,
        "Không thể kết nối ứng dụng local.",
      );
    }
  }

  function getClient(): LocalApiClient {
    if (!apiClient) {
      throw new ApiError("Phiên truy cập chưa sẵn sàng.", 401);
    }
    return apiClient;
  }

  function resetPollingClock(): void {
    lastPollTick = Date.now();
    countdownRemainderMilliseconds = 0;
    millisecondsSinceStateRefresh = 0;
    otpElapsedSeconds.value = 0;
  }

  function applyServerState(nextState: ApplicationState): void {
    state.value = nextState;
    lastUpdated.value = new Date();
    resetPollingClock();
  }

  function advanceOtpCountdown(elapsedSeconds: number): boolean {
    const current = state.value;
    if (!current || elapsedSeconds <= 0) return false;
    const previousElapsed = otpElapsedSeconds.value;
    const nextElapsed = previousElapsed + elapsedSeconds;
    otpElapsedSeconds.value = nextElapsed;
    return current.accounts.some((account) => {
      const remaining = account.otp_remaining_seconds;
      return remaining !== null
        && remaining > previousElapsed
        && remaining <= nextElapsed;
    });
  }

  function otpRemainingSeconds(account: AccountState): number | null {
    const remaining = account.otp_remaining_seconds;
    if (remaining === null) return null;
    const liveRemaining = remaining - otpElapsedSeconds.value;
    return liveRemaining > 0 ? liveRemaining : null;
  }

  function otpValue(account: AccountState): string | null {
    return otpRemainingSeconds(account) === null ? null : account.otp;
  }

  function pollTick(): void {
    const now = Date.now();
    const elapsedMilliseconds = Math.max(0, now - lastPollTick);
    lastPollTick = now;
    millisecondsSinceStateRefresh += elapsedMilliseconds;
    const countdownMilliseconds = (
      countdownRemainderMilliseconds + elapsedMilliseconds
    );
    const elapsedSeconds = Math.floor(countdownMilliseconds / 1_000);
    countdownRemainderMilliseconds = countdownMilliseconds % 1_000;
    const rollover = advanceOtpCountdown(elapsedSeconds);
    if (
      rollover
      || millisecondsSinceStateRefresh >= stateRefreshIntervalMilliseconds
    ) {
      millisecondsSinceStateRefresh = 0;
      void pollState();
    }
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
      applyServerState(await getClient().state());
      connectionStatus.value = "ready";
      errorMessage.value = "";
    } catch (error) {
      connectionStatus.value = "offline";
      errorMessage.value = userFacingError(
        error,
        "Không thể cập nhật trạng thái local.",
      );
    } finally {
      pollInFlight = false;
    }
  }

  function startPolling(intervalMilliseconds = 1_000): void {
    stopPolling();
    resetPollingClock();
    pollTimer = window.setInterval(pollTick, intervalMilliseconds);
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
    countdownRemainderMilliseconds = 0;
    millisecondsSinceStateRefresh = 0;
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
    otpRemainingSeconds,
    otpValue,
    pollState,
    shutdown,
    startPolling,
    state,
    stopPolling,
  };
});
