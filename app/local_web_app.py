from __future__ import annotations

import hmac
import ipaddress
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .local_web_service import AccountNotFoundError, LocalWebService
from .otp_codex_manager_with_account_status import (
    CODEX_PROFILES_DIR,
    DATA_FILE,
)


ASSETS_DIR = Path(__file__).resolve().parents[1] / "web"
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


class AccountState(BaseModel):
    id: str
    email: str
    otp: str
    otp_remaining_seconds: int
    quota_remaining: str
    quota_cycle: str
    quota_reset_at: str
    plan_type: str
    account_state: str
    sync_status: str
    last_sync: str


class StateResponse(BaseModel):
    accounts: list[AccountState]
    sync_status: str
    refresh_interval_seconds: int


class BootstrapResponse(BaseModel):
    csrf_token: str
    state: StateResponse


class ImportAccountsRequest(BaseModel):
    lines: str = Field(min_length=1, max_length=100_000)


class ImportAccountsResponse(BaseModel):
    total: int
    added: int
    updated: int
    duplicates: int
    errors: list[str]


class SensitiveValueRequest(BaseModel):
    field: Literal["password", "secret"]


class SensitiveValueResponse(BaseModel):
    value: str


class DeleteResponse(BaseModel):
    deleted: bool


class RefreshRequest(BaseModel):
    account_id: str | None = Field(
        default=None,
        min_length=16,
        max_length=16,
    )


class ActionResponse(BaseModel):
    accepted: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]


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
) -> FastAPI:
    active_service = service or LocalWebService(
        data_file=DATA_FILE,
        profiles_dir=CODEX_PROFILES_DIR,
    )
    rate_limiter = LocalWriteRateLimiter()

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
        return HealthResponse(status="ok")

    @app.get("/api/bootstrap", response_model=BootstrapResponse)
    def bootstrap() -> BootstrapResponse:
        return BootstrapResponse(
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

    @app.post(
        "/api/accounts/import",
        response_model=ImportAccountsResponse,
        dependencies=[Depends(require_csrf)],
    )
    def import_accounts(
        request: ImportAccountsRequest,
    ) -> ImportAccountsResponse:
        try:
            result = active_service.import_accounts(
                request.lines
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

        return ImportAccountsResponse.model_validate(result)

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
                account_ids
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

    app.mount(
        "/assets",
        StaticFiles(directory=assets_dir, check_dir=False),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(assets_dir / "index.html")

    return app


app = create_app()
