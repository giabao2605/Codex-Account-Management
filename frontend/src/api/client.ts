import type {
  AccountCheckResponse,
  ActionResponse,
  AddAccountResponse,
  ApplicationState,
  ArchiveProfilesResponse,
  BootstrapResponse,
  DeleteResponse,
  SensitiveValueResponse,
  TokenUsageResponse,
} from "@/types/api.ts";

export const EXPECTED_API_SCHEMA_VERSION = 6;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class LocalApiClient {
  constructor(
    private readonly accessToken: string,
    private readonly getCsrfToken: () => string,
  ) {}

  async bootstrap(): Promise<BootstrapResponse> {
    return this.request<BootstrapResponse>("/api/bootstrap");
  }

  async state(): Promise<ApplicationState> {
    return this.request<ApplicationState>("/api/state");
  }

  async tokenUsage(): Promise<TokenUsageResponse> {
    return this.request<TokenUsageResponse>("/api/usage/tokens");
  }

  async checkAccount(lines: string): Promise<AccountCheckResponse> {
    return this.request<AccountCheckResponse>(
      "/api/accounts/import/check",
      {
        method: "POST",
        body: JSON.stringify({ lines }),
      },
    );
  }

  async addAccount(lines: string): Promise<AddAccountResponse> {
    return this.request<AddAccountResponse>("/api/accounts/import", {
      method: "POST",
      body: JSON.stringify({ lines }),
    });
  }

  async sensitiveValue(
    accountId: string,
    field: "password" | "secret",
  ): Promise<SensitiveValueResponse> {
    return this.request<SensitiveValueResponse>(
      `/api/accounts/${encodeURIComponent(accountId)}/sensitive`,
      {
        method: "POST",
        body: JSON.stringify({ field }),
      },
    );
  }

  async refresh(accountId: string | null): Promise<ActionResponse> {
    return this.request<ActionResponse>("/api/codex/refresh", {
      method: "POST",
      body: JSON.stringify({
        account_id: accountId,
        force_token_usage: true,
      }),
    });
  }

  async login(accountId: string): Promise<ActionResponse> {
    return this.accountAction(accountId, "login");
  }

  async unlink(accountId: string): Promise<ActionResponse> {
    return this.accountAction(accountId, "unlink");
  }

  async resetProfile(accountId: string): Promise<ActionResponse> {
    return this.accountAction(accountId, "reset-profile");
  }

  async deleteAccount(accountId: string): Promise<DeleteResponse> {
    return this.request<DeleteResponse>(
      `/api/accounts/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
    );
  }

  async archiveOrphans(): Promise<ArchiveProfilesResponse> {
    return this.request<ArchiveProfilesResponse>(
      "/api/profiles/orphans/archive",
      { method: "POST" },
    );
  }

  async shutdown(): Promise<ActionResponse> {
    return this.request<ActionResponse>("/api/application/shutdown", {
      method: "POST",
    });
  }

  private async accountAction(
    accountId: string,
    action: "login" | "unlink" | "reset-profile",
  ): Promise<ActionResponse> {
    return this.request<ActionResponse>(
      `/api/codex/${encodeURIComponent(accountId)}/${action}`,
      { method: "POST" },
    );
  }

  async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const method = (init.method ?? "GET").toUpperCase();
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.accessToken}`);
    headers.set("Accept", "application/json");

    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      const csrfToken = this.getCsrfToken();
      if (!csrfToken) {
        throw new ApiError("Phiên bảo mật chưa sẵn sàng.", 403);
      }
      headers.set("X-CSRF-Token", csrfToken);
      headers.set("Content-Type", "application/json");
    }

    let response: Response;
    try {
      response = await fetch(path, {
        ...init,
        method,
        headers,
      });
    } catch {
      throw new ApiError("Không thể kết nối ứng dụng local.", 0);
    }

    if (!response.ok) {
      throw new ApiError("Không thể kết nối ứng dụng local.", response.status);
    }

    return response.json() as Promise<T>;
  }
}
