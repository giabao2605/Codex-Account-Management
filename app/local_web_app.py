from __future__ import annotations

import hmac
import ipaddress
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from .build_info import (
    API_SCHEMA_VERSION,
    APP_BUILD_ID,
    FRONTEND_ASSETS_DIR,
    FRONTEND_STATIC_ASSETS_DIR,
)
from .local_web_accounts import AccountConflictError
from .local_web_profiles import UnsafeProfilePathError
from .local_web_service import AccountNotFoundError, LocalWebService
from .otp_codex_manager_with_account_status import (
    CODEX_PROFILES_DIR,
    DATA_FILE,
)


ASSETS_DIR = FRONTEND_ASSETS_DIR
STATIC_ASSETS_DIR = FRONTEND_STATIC_ASSETS_DIR
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
STATIC_ASSET_REFERENCE = re.compile(
    r"""(?:src|href)=["']/assets/([^"'?#]+)""",
)


class QuotaWindowState(BaseModel):
    quota_remaining: str
    quota_cycle: str
    quota_reset_at: str


class AccountState(BaseModel):
    id: str
    email: str
    otp: str | None
    otp_remaining_seconds: int | None
    quota_remaining: str
    quota_cycle: str
    quota_reset_at: str
    quota_windows: list[QuotaWindowState] = Field(default_factory=list)
    banked_reset_count: int | None = Field(default=None, ge=0)
    banked_reset_expires_at: list[str] | None = None
    plus_expires_at: str | None = None
    plan_type: str
    account_state: str
    sync_status: str
    last_sync: str


class AccountRecommendation(BaseModel):
    account_id: str
    email: str
    quota_remaining: str
    quota_reset_at: str


class RankedAccountRecommendation(AccountRecommendation):
    rank: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)


class AccountUsageStatistics(BaseModel):
    account_id: str
    email: str
    quota_remaining_percent: float | None
    quota_used_percent: float | None
    quota_cycle: str
    quota_reset_at: str
    plan_type: str
    account_state: str
    sync_status: str
    last_sync: str
    is_usable: bool
    needs_attention: bool
    quota_is_stale: bool


class PlanUsageCount(BaseModel):
    plan_type: str
    count: int


class UsageStatistics(BaseModel):
    schema_version: Literal[1]
    history_available: Literal[False]
    source: Literal["codex_rate_limits_snapshot"]
    generated_at: str
    total_accounts: int
    quota_known_accounts: int
    quota_unknown_accounts: int
    stale_quota_accounts: int
    usable_accounts: int
    attention_accounts: int
    low_quota_accounts: int
    exhausted_accounts: int
    average_remaining_percent: float | None
    average_used_percent: float | None
    minimum_remaining_percent: float | None
    maximum_remaining_percent: float | None
    median_remaining_percent: float | None
    next_reset_at: str | None
    plan_distribution: list[PlanUsageCount]
    accounts: list[AccountUsageStatistics]


class TokenUsageCoverage(BaseModel):
    total_accounts: int
    fresh_accounts: int
    stale_accounts: int
    unavailable_accounts: int


class TokenUsagePeriod(BaseModel):
    start_date: str
    end_date: str
    is_partial: bool


class TokenUsagePeriods(BaseModel):
    today: TokenUsagePeriod
    current_week: TokenUsagePeriod
    current_month: TokenUsagePeriod


class TokenUsageSeriesPoint(BaseModel):
    start_date: str
    end_date: str
    tokens: int | None


class TokenUsageSeries(BaseModel):
    daily: list[TokenUsageSeriesPoint]
    weekly: list[TokenUsageSeriesPoint]
    monthly: list[TokenUsageSeriesPoint]


class TokenUsageDailyBucket(BaseModel):
    start_date: str
    tokens: int


class TokenUsageTotals(BaseModel):
    today: int | None
    week: int | None
    month: int | None
    lifetime: int | None


class TokenUsageAverages(BaseModel):
    today: float | None
    week: float | None
    month: float | None
    lifetime: float | None


class TokenUsageSampleSizes(BaseModel):
    today: int
    week: int
    month: int
    lifetime: int


class TokenUsageAggregate(BaseModel):
    totals: TokenUsageTotals
    averages: TokenUsageAverages
    sample_sizes: TokenUsageSampleSizes
    daily_buckets: list[TokenUsageDailyBucket] | None
    series: TokenUsageSeries


class TokenUsageAccount(BaseModel):
    account_id: str
    email: str
    status: Literal["fresh", "stale", "unavailable"]
    updated_at: str | None
    today: int | None
    week: int | None
    month: int | None
    lifetime: int | None
    peak_daily: int | None
    longest_running_turn_seconds: int | None
    current_streak_days: int | None
    longest_streak_days: int | None
    daily_buckets: list[TokenUsageDailyBucket] | None
    series: TokenUsageSeries


class TokenUsageResponse(BaseModel):
    schema_version: Literal[2]
    source: Literal["codex_account_usage"]
    generated_at: str
    coverage: TokenUsageCoverage
    periods: TokenUsagePeriods
    aggregate: TokenUsageAggregate
    accounts: list[TokenUsageAccount]


class TimeSyncState(BaseModel):
    status: Literal["synced", "syncing", "degraded"]
    offset_seconds: float | None
    last_synced_at: str | None
    source_count: int


class FailoverTaskCounts(BaseModel):
    total: int = Field(ge=0)
    active: int = Field(ge=0)
    completed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    quota_exhausted: int = Field(ge=0)
    eligible: int = Field(ge=0)


class FailoverQuotaCounts(BaseModel):
    total: int = Field(ge=0)
    exhausted: int = Field(ge=0)


class FailoverStatusResponse(BaseModel):
    schema_version: Literal[1]
    available: bool
    enabled: bool
    state: Literal[
        "disabled",
        "observing",
        "draining",
        "switching",
        "resuming",
        "running",
        "all_exhausted",
        "blocked",
        "error",
    ]
    updated_at: str | None
    has_error: bool
    tasks: FailoverTaskCounts
    quotas: FailoverQuotaCounts


class StateResponse(BaseModel):
    accounts: list[AccountState]
    sync_status: str
    refresh_interval_seconds: int
    recommendation: AccountRecommendation | None
    recommendation_queue: list[RankedAccountRecommendation]
    usage_statistics: UsageStatistics
    time_sync: TimeSyncState


class BootstrapResponse(BaseModel):
    api_schema_version: int
    build_id: str
    csrf_token: str
    state: StateResponse


class AccountInputRequest(BaseModel):
    lines: str = Field(min_length=1, max_length=100_000)


class AccountCheckResponse(BaseModel):
    valid: bool
    conflict: Literal["email", "secret", "invalid"] | None
    message: str


class AddAccountResponse(BaseModel):
    total: int
    email: str


class SensitiveValueRequest(BaseModel):
    field: Literal["password", "secret"]


class SensitiveValueResponse(BaseModel):
    value: str


class PasswordUpdateRequest(BaseModel):
    password: str


class PasswordUpdateResponse(BaseModel):
    updated: bool


class SecretUpdateRequest(BaseModel):
    secret: str


class SecretUpdateResponse(BaseModel):
    updated: bool


class PlusExpirationUpdateRequest(BaseModel):
    plus_expires_at: str | None = Field(...)


class PlusExpirationUpdateResponse(BaseModel):
    updated: bool


class DeleteResponse(BaseModel):
    deleted: bool


class RefreshRequest(BaseModel):
    account_id: str | None = Field(
        default=None,
        min_length=16,
        max_length=16,
    )
    force_token_usage: bool = False


class ActionResponse(BaseModel):
    accepted: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_schema_version: int
    build_id: str


class LocalWriteRateLimiter:
    def __init__(
        self,
        limit: int = 120,
        window_seconds: int = 60,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_host: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        bucket = self._requests[client_host]

        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self.limit:
            return False

        bucket.append(now)
        return True


def _is_loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value.casefold() == "localhost"


def _origin_matches_request(origin: str, host_header: str) -> bool:
    parsed = urlsplit(origin)

    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or not _is_loopback(parsed.hostname)
    ):
        return False

    expected_host = parsed.hostname

    if ":" in expected_host and not host_header.startswith("["):
        expected_authority = f"[{expected_host}]"
    else:
        expected_authority = expected_host

    try:
        origin_port = parsed.port
    except ValueError:
        return False

    if origin_port is not None:
        expected_authority = f"{expected_authority}:{origin_port}"

    return hmac.compare_digest(
        expected_authority.casefold(),
        host_header.casefold(),
    )


def _host_is_local_authority(host_header: str) -> bool:
    if not host_header or any(
        character in host_header
        for character in "/?#@"
    ):
        return False

    parsed = urlsplit(f"//{host_header}")

    try:
        port = parsed.port
    except ValueError:
        return False

    return (
        parsed.hostname is not None
        and parsed.hostname.casefold() in LOCAL_HOSTNAMES
        and (port is None or 1 <= port <= 65535)
    )


def create_app(
    service: LocalWebService | None = None,
    assets_dir: Path = ASSETS_DIR,
    shutdown_callback: Callable[[], None] | None = None,
    *,
    static_assets_dir: Path | None = STATIC_ASSETS_DIR,
) -> FastAPI:
    active_static_assets_dir = static_assets_dir or assets_dir
    if static_assets_dir is not None:
        index_path = assets_dir / "index.html"
        missing_paths = []
        if not index_path.is_file():
            missing_paths.append(str(index_path))
        if not static_assets_dir.is_dir():
            missing_paths.append(str(static_assets_dir))

        if not missing_paths:
            static_root = static_assets_dir.resolve()
            index_content = index_path.read_text(encoding="utf-8")
            references = STATIC_ASSET_REFERENCE.findall(index_content)
            if not references:
                missing_paths.append("no /assets/ references in index.html")
            for reference in references:
                target = (static_root / reference).resolve()
                if (
                    not target.is_relative_to(static_root)
                    or not target.is_file()
                ):
                    missing_paths.append(reference)

        if missing_paths:
            missing = ", ".join(missing_paths)
            raise FileNotFoundError(
                "Production frontend build is incomplete: "
                f"missing {missing}."
            )

    active_service = service or LocalWebService(
        data_file=DATA_FILE,
        profiles_dir=CODEX_PROFILES_DIR,
    )
    rate_limiter = LocalWriteRateLimiter()
    shutdown_lock = threading.Lock()
    shutdown_requested = False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        active_service.start()
        yield
        active_service.close()

    app = FastAPI(
        title="OTP Codex Local",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.service = active_service

    @app.middleware("http")
    async def local_only_and_security_headers(
        request: Request,
        call_next,
    ):
        client_host = (
            request.client.host
            if request.client is not None
            else ""
        )
        host_header = request.headers.get("host", "")
        if (
            not _is_loopback(client_host)
            or not _host_is_local_authority(host_header)
        ):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Chỉ cho phép truy cập local."},
            )
        elif request.url.path.startswith("/api/") and (
            request.url.path != "/api/health"
            and not hmac.compare_digest(
                request.headers.get("authorization", ""),
                f"Bearer {active_service.access_token}",
            )
        ):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Phiên truy cập không hợp lệ."},
            )
        else:
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")

                if origin and not _origin_matches_request(
                    origin,
                    host_header,
                ):
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Origin không hợp lệ."},
                    )
                elif not rate_limiter.check(client_host):
                    response = JSONResponse(
                        status_code=429,
                        content={"detail": "Thao tác quá nhanh."},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-OTP-Codex-App"] = "1"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request,
        __: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "Dữ liệu yêu cầu không hợp lệ."},
        )

    def require_csrf(
        x_csrf_token: Annotated[
            str | None,
            Header(alias="X-CSRF-Token"),
        ] = None,
    ) -> None:
        if (
            x_csrf_token is None
            or not hmac.compare_digest(
                x_csrf_token,
                active_service.csrf_token,
            )
        ):
            raise HTTPException(
                status_code=403,
                detail="CSRF token không hợp lệ.",
            )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            api_schema_version=API_SCHEMA_VERSION,
            build_id=APP_BUILD_ID,
        )

    @app.get("/api/bootstrap", response_model=BootstrapResponse)
    def bootstrap() -> BootstrapResponse:
        return BootstrapResponse(
            api_schema_version=API_SCHEMA_VERSION,
            build_id=APP_BUILD_ID,
            csrf_token=active_service.csrf_token,
            state=StateResponse.model_validate(
                active_service.state()
            ),
        )

    @app.get("/api/state", response_model=StateResponse)
    def state() -> StateResponse:
        return StateResponse.model_validate(
            active_service.state()
        )

    @app.get(
        "/api/usage/tokens",
        response_model=TokenUsageResponse,
    )
    def token_usage() -> TokenUsageResponse:
        return TokenUsageResponse.model_validate(
            active_service.token_usage_statistics()
        )

    @app.get(
        "/api/failover/status",
        response_model=FailoverStatusResponse,
    )
    def failover_status() -> FailoverStatusResponse:
        return FailoverStatusResponse.model_validate(
            active_service.failover_status()
        )

    @app.post(
        "/api/accounts/import/check",
        response_model=AccountCheckResponse,
        dependencies=[Depends(require_csrf)],
    )
    def check_account(
        request: AccountInputRequest,
    ) -> AccountCheckResponse:
        return AccountCheckResponse.model_validate(
            active_service.check_account(request.lines)
        )

    @app.post(
        "/api/accounts/import",
        response_model=AddAccountResponse,
        dependencies=[Depends(require_csrf)],
    )
    def import_accounts(
        request: AccountInputRequest,
    ) -> AddAccountResponse:
        try:
            result = active_service.import_accounts(request.lines)
        except AccountConflictError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

        return AddAccountResponse.model_validate(result)

    @app.delete(
        "/api/accounts/{account_id}",
        response_model=DeleteResponse,
        dependencies=[Depends(require_csrf)],
    )
    def delete_account(
        account_id: str,
    ) -> DeleteResponse:
        try:
            active_service.delete_account(account_id)
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error
        except (OSError, UnsafeProfilePathError) as error:
            raise HTTPException(
                status_code=409,
                detail="Không thể xóa tài khoản an toàn.",
            ) from error

        return DeleteResponse(deleted=True)

    @app.post(
        "/api/accounts/{account_id}/sensitive",
        response_model=SensitiveValueResponse,
        dependencies=[Depends(require_csrf)],
    )
    def sensitive_value(
        account_id: str,
        request: SensitiveValueRequest,
    ) -> SensitiveValueResponse:
        try:
            value = active_service.sensitive_value(
                account_id,
                request.field,
            )
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error

        return SensitiveValueResponse(value=value)

    @app.patch(
        "/api/accounts/{account_id}/password",
        response_model=PasswordUpdateResponse,
        dependencies=[Depends(require_csrf)],
    )
    def update_password(
        account_id: str,
        request: PasswordUpdateRequest,
    ) -> PasswordUpdateResponse:
        try:
            active_service.update_password(account_id, request.password)
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Không thể cập nhật mật khẩu an toàn.",
            ) from error

        return PasswordUpdateResponse(updated=True)

    @app.patch(
        "/api/accounts/{account_id}/secret",
        response_model=SecretUpdateResponse,
        dependencies=[Depends(require_csrf)],
    )
    def update_secret(
        account_id: str,
        request: SecretUpdateRequest,
    ) -> SecretUpdateResponse:
        try:
            active_service.update_secret(account_id, request.secret)
        except AccountNotFoundError as error:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.") from error
        except AccountConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Không thể cập nhật secret an toàn.",
            ) from error

        return SecretUpdateResponse(updated=True)

    @app.patch(
        "/api/accounts/{account_id}/plus-expiration",
        response_model=PlusExpirationUpdateResponse,
        dependencies=[Depends(require_csrf)],
    )
    def update_plus_expiration(
        account_id: str,
        request: PlusExpirationUpdateRequest,
    ) -> PlusExpirationUpdateResponse:
        try:
            active_service.update_plus_expiration(
                account_id,
                request.plus_expires_at,
            )
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Không thể cập nhật ngày hết hạn Plus an toàn.",
            ) from error

        return PlusExpirationUpdateResponse(updated=True)

    @app.post(
        "/api/codex/refresh",
        response_model=ActionResponse,
        dependencies=[Depends(require_csrf)],
    )
    def refresh_codex(
        request: RefreshRequest,
    ) -> ActionResponse:
        account_ids = (
            {request.account_id}
            if request.account_id
            else None
        )
        return ActionResponse(
            accepted=active_service.refresh_async(
                account_ids,
                force_token_usage=request.force_token_usage,
            )
        )

    @app.post(
        "/api/codex/{account_id}/login",
        response_model=ActionResponse,
        dependencies=[Depends(require_csrf)],
    )
    def login_codex(
        account_id: str,
    ) -> ActionResponse:
        try:
            active_service.login(account_id)
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail="Không thể mở đăng nhập Codex.",
            ) from error

        return ActionResponse(accepted=True)

    @app.post(
        "/api/codex/{account_id}/unlink",
        response_model=ActionResponse,
        dependencies=[Depends(require_csrf)],
    )
    def unlink_codex(account_id: str) -> ActionResponse:
        try:
            active_service.unlink_profile(account_id)
        except AccountNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản.",
            ) from error
        except (OSError, UnsafeProfilePathError) as error:
            raise HTTPException(
                status_code=409,
                detail="Không thể ngắt liên kết profile an toàn.",
            ) from error
        return ActionResponse(accepted=True)

    @app.post(
        "/api/application/shutdown",
        response_model=ActionResponse,
        dependencies=[Depends(require_csrf)],
    )
    def shutdown_application() -> ActionResponse:
        nonlocal shutdown_requested
        with shutdown_lock:
            if shutdown_requested:
                return ActionResponse(accepted=False)
            shutdown_requested = True
        if shutdown_callback is not None:
            try:
                shutdown_callback()
            except Exception as error:
                with shutdown_lock:
                    shutdown_requested = False
                raise HTTPException(
                    status_code=503,
                    detail="Không thể gửi yêu cầu thoát ứng dụng.",
                ) from error
        return ActionResponse(accepted=True)

    app.mount(
        "/assets",
        GZipMiddleware(
            StaticFiles(
                directory=active_static_assets_dir,
                check_dir=False,
            ),
            minimum_size=1000,
        ),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(assets_dir / "index.html")

    return app


app = create_app()
