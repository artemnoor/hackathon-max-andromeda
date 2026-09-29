from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from andromeda.api.request_controls import (
    SlidingWindowRateLimiter,
    enforce_rate_limit,
    enforce_trusted_origin,
    normalize_correlation_id,
)
from andromeda.api.public_api_v1 import register_public_api_v1_routes
from andromeda.api.routes.admin_ops import router as admin_ops_router
from andromeda.api.routes.admission_benefits import router as admission_benefits_router
from andromeda.api.routes.admission_fit import router as admission_fit_router
from andromeda.api.routes.admissions import router as admissions_router
from andromeda.api.routes.analytics import router as analytics_router
from andromeda.api.routes.analytics_ops import router as analytics_ops_router
from andromeda.api.routes.assistant import router as assistant_router
from andromeda.api.routes.auth import router as auth_router
from andromeda.api.routes.campus import router as campus_router
from andromeda.api.routes.compare import router as compare_router
from andromeda.api.routes.decision import router as decision_router
from andromeda.api.routes.disciplines import router as disciplines_router
from andromeda.api.routes.events import router as events_router
from andromeda.api.routes.health import expected_schema_revision
from andromeda.api.routes.health import router as health_router
from andromeda.api.routes.knowledge_ops import router as knowledge_ops_router
from andromeda.api.routes.knowledge_review import router as knowledge_review_router
from andromeda.api.routes.personal_route import router as personal_route_router
from andromeda.api.routes.proftest import router as proftest_router
from andromeda.api.routes.programs import router as programs_router
from andromeda.api.routes.recommendations import router as recommendations_router
from andromeda.api.routes.university_admin import router as university_admin_router
from andromeda.api.routes.university_catalog import router as university_catalog_router
from andromeda.api.routes.university_events import router as university_events_router
from andromeda.composition import build_container
from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.database.base import create_engine_for_url
from andromeda.shared.contracts.errors import (
    AndromedaError,
    ErrorCode,
    ErrorResponse,
    details_from_validation,
)

logger = logging.getLogger("andromeda.api.request")

SECURITY_HEADERS = {
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
DOCS_CONTENT_SECURITY_POLICY = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'"
HSTS_HEADER = "max-age=31536000; includeSubDomains"


def _canonicalize_openapi(document: dict[str, Any]) -> dict[str, Any]:
    """Keep generated contracts stable across Python HTTP reason-phrase versions."""

    paths = document.get("paths")
    if not isinstance(paths, dict):
        return document
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            response = responses.get("422")
            if (
                isinstance(response, dict)
                and response.get("description") == "Unprocessable Content"
            ):
                response["description"] = "Unprocessable Entity"
    return document


class AndromedaFastAPI(FastAPI):
    """FastAPI application with a stable, checked-in OpenAPI representation."""

    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            self.openapi_schema = _canonicalize_openapi(
                get_openapi(
                    title=self.title,
                    version=self.version,
                    description=self.description,
                    routes=self.routes,
                )
            )
        return self.openapi_schema


def _andromeda_error_response(
    request: Request, exc: AndromedaError, settings: Settings
) -> JSONResponse:
    status = (
        429
        if exc.code is ErrorCode.RATE_LIMITED
        else 401
        if exc.code is ErrorCode.UNAUTHORIZED
        else 403
        if exc.code is ErrorCode.FORBIDDEN
        else 404
        if exc.code is ErrorCode.NOT_FOUND
        else 409
        if exc.code is ErrorCode.CONFLICT
        else 400
        if exc.code
        in (
            ErrorCode.VALIDATION_ERROR,
            ErrorCode.CONTRACT_ERROR,
            ErrorCode.SOURCE_CONTRACT_ERROR,
            ErrorCode.UNSUPPORTED_METRIC,
            ErrorCode.UNSUPPORTED_AGGREGATION,
            ErrorCode.INVALID_QUERY,
            ErrorCode.AMBIGUOUS_ENTITY,
            ErrorCode.INSUFFICIENT_DATA,
        )
        else 500
    )
    if exc.code is ErrorCode.RATE_LIMITED:
        logger.warning(
            "request_rate_limited path=%s correlation_id=%s",
            request.url.path,
            getattr(request.state, "correlation_id", "unknown"),
        )
    headers = (
        {"Retry-After": str(settings.rate_limit_window_seconds)}
        if status == 429
        else None
    )
    return JSONResponse(
        status_code=status,
        headers=headers,
        content=exc.response().model_dump(mode="json", by_alias=True),
    )


def create_app(database_url: str | None = None) -> FastAPI:
    settings = Settings.from_environment(database_url)
    app = AndromedaFastAPI(
        title="Andromeda Decision Support API",
        version="1.0.0",
        description="Strict source-backed contracts for discovering, comparing and choosing educational programmes across supported universities.",
        responses={
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            429: {
                "model": ErrorResponse,
                "description": "Request rate limit reached",
                "headers": {
                    "Retry-After": {
                        "description": "Seconds until another request may be made",
                        "schema": {"type": "string"},
                    }
                },
            },
            500: {"model": ErrorResponse},
        },
    )
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_window_seconds
    )
    app.state.engine = create_engine_for_url(
        settings.database_url, **settings.engine_options
    )
    app.state.container = build_container(app.state.engine, settings)
    try:
        app.state.expected_schema_revision = expected_schema_revision()
    except RuntimeError:
        logger.exception("schema_head_discovery_failed")
        app.state.expected_schema_revision = None
    origins = tuple(filter(None, settings.frontend_origin.split(",")))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started_at = perf_counter()
        correlation_id = normalize_correlation_id(
            request.headers.get("X-Correlation-Id")
        )
        request.state.correlation_id = correlation_id
        response: Response | None = None
        try:
            enforce_trusted_origin(request, settings)
            enforce_rate_limit(request, app.state.rate_limiter, settings)
            response = await call_next(request)
        except AndromedaError as exc:
            response = _andromeda_error_response(request, exc, settings)
        except Exception as exc:
            logger.error(
                "unhandled_exception exception_type=%s correlation_id=%s",
                type(exc).__name__,
                correlation_id,
            )
            response = JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    code=ErrorCode.INTERNAL_ERROR, message="Internal server error"
                ).model_dump(mode="json", by_alias=True),
            )
        profile_cookie_header = getattr(request.state, "profile_cookie_header", None)
        if isinstance(
            profile_cookie_header, str
        ) and profile_cookie_header not in response.headers.getlist("set-cookie"):
            response.headers.append("set-cookie", profile_cookie_header)
        response.headers["X-Correlation-Id"] = correlation_id
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["Content-Security-Policy"] = (
            DOCS_CONTENT_SECURITY_POLICY
            if response.headers.get("content-type", "").startswith("text/html")
            else API_CONTENT_SECURITY_POLICY
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = HSTS_HEADER
        logger.info(
            "request_complete method=%s path=%s status=%d duration_ms=%.2f correlation_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started_at) * 1000,
            correlation_id,
        )
        return response

    @app.exception_handler(AndromedaError)
    async def andromeda_error_handler(
        request: Request, exc: AndromedaError
    ) -> JSONResponse:
        return _andromeda_error_response(request, exc, settings)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        response = ErrorResponse(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            details=details_from_validation(exc.errors()),
        )
        return JSONResponse(
            status_code=422, content=response.model_dump(mode="json", by_alias=True)
        )

    @app.exception_handler(ResponseValidationError)
    async def response_validation_handler(
        request: Request, exc: ResponseValidationError
    ) -> JSONResponse:
        logger.error(
            "response_contract_violation exception_type=%s correlation_id=%s",
            type(exc).__name__,
            getattr(request.state, "correlation_id", "unknown"),
        )
        response = ErrorResponse(
            code=ErrorCode.CONTRACT_ERROR, message="Response contract failed"
        )
        return JSONResponse(
            status_code=500, content=response.model_dump(mode="json", by_alias=True)
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        response = ErrorResponse(
            code=ErrorCode.CONTRACT_ERROR,
            message="Contract validation failed",
            details=details_from_validation(exc.errors()),
        )
        return JSONResponse(
            status_code=500, content=response.model_dump(mode="json", by_alias=True)
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.error(
            "database_error exception_type=%s correlation_id=%s",
            type(exc).__name__,
            getattr(request.state, "correlation_id", "unknown"),
        )
        response = ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR, message="Database operation failed"
        )
        return JSONResponse(
            status_code=500, content=response.model_dump(mode="json", by_alias=True)
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled_exception exception_type=%s correlation_id=%s",
            type(exc).__name__,
            getattr(request.state, "correlation_id", "unknown"),
        )
        response = ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR, message="Internal server error"
        )
        return JSONResponse(
            status_code=500, content=response.model_dump(mode="json", by_alias=True)
        )

    app.include_router(programs_router)
    app.include_router(admissions_router)
    app.include_router(admission_fit_router)
    app.include_router(admission_benefits_router)
    app.include_router(disciplines_router)
    app.include_router(compare_router)
    app.include_router(analytics_router)
    app.include_router(assistant_router)
    app.include_router(proftest_router)
    app.include_router(recommendations_router)
    app.include_router(events_router)
    app.include_router(campus_router)
    app.include_router(personal_route_router)
    app.include_router(admin_ops_router)
    app.include_router(analytics_ops_router)
    app.include_router(knowledge_ops_router)
    app.include_router(knowledge_review_router)
    app.include_router(auth_router)
    app.include_router(decision_router)
    app.include_router(university_admin_router)
    app.include_router(university_catalog_router)
    app.include_router(university_events_router)
    app.include_router(health_router)
    register_public_api_v1_routes(
        app,
        (
            admission_benefits_router,
            admission_fit_router,
            admissions_router,
            analytics_router,
            assistant_router,
            auth_router,
            campus_router,
            compare_router,
            decision_router,
            disciplines_router,
            events_router,
            health_router,
            personal_route_router,
            proftest_router,
            programs_router,
            recommendations_router,
            university_catalog_router,
            university_events_router,
        ),
    )
    return app


app = create_app()
