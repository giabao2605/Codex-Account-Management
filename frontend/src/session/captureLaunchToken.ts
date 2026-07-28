export const ACCESS_TOKEN_STORAGE_KEY = "otp-codex-access-token";

interface LocationPort {
  hash: string;
  pathname: string;
  search: string;
}

interface HistoryPort {
  replaceState(data: unknown, unused: string, url?: string | URL | null): void;
}

interface StoragePort {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function captureLaunchToken(
  locationPort: LocationPort = window.location,
  historyPort: HistoryPort = window.history,
  storagePort: StoragePort = window.sessionStorage,
): string {
  const fragmentToken = locationPort.hash.slice(1).trim();

  if (fragmentToken) {
    storagePort.setItem(ACCESS_TOKEN_STORAGE_KEY, fragmentToken);
    historyPort.replaceState(
      null,
      "",
      `${locationPort.pathname}${locationPort.search}`,
    );
  }

  return storagePort.getItem(ACCESS_TOKEN_STORAGE_KEY) ?? "";
}
