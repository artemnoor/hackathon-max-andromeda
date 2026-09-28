"""HTTP-only auth session boundary for the API."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import secrets
from typing import Literal, cast

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from andromeda.composition import AndromedaContainer
from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.auth.repository.ports import AccountRepository
from andromeda.shared.contracts.errors import UnauthorizedError, ValidationError
from andromeda.shared.contracts.ids import SessionTokenHash

from .request_context import get_session


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def get_auth_repository(request: Request, session: Session = Depends(get_session)) -> AccountRepository:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, AndromedaContainer):
        raise RuntimeError("Andromeda composition root is not configured")
    return container.account_repository(session)


def auth_token_hash(raw_token: str) -> SessionTokenHash:
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


def new_auth_token() -> str:
    return secrets.token_urlsafe(32)


def get_auth_token_hash(request: Request) -> SessionTokenHash | None:
    raw_token = request.cookies.get(_settings(request).auth_cookie_name)
    if raw_token is None or _TOKEN_PATTERN.fullmatch(raw_token) is None:
        return None
    return auth_token_hash(raw_token)


def get_optional_current_account(
    request: Request,
    response: Response,
    repository: AccountRepository = Depends(get_auth_repository),
) -> Account | None:
    settings = _settings(request)
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if raw_token is None:
        return None
    if _TOKEN_PATTERN.fullmatch(raw_token) is None:
        delete_auth_cookie(response, settings)
        return None
    account = repository.get_by_session_hash(auth_token_hash(raw_token), now=datetime.now(timezone.utc))
    if account is None:
        delete_auth_cookie(response, settings)
    return account


def require_current_account(account: Account | None = Depends(get_optional_current_account)) -> Account:
    if account is None:
        raise UnauthorizedError()
    return account


def require_trusted_origin(request: Request) -> None:
    """Protect credentialed state-changing auth calls from cross-origin POSTs."""

    origin = request.headers.get("origin")
    if origin is None:
        return
    trusted_origins = {item.strip().rstrip("/") for item in _settings(request).frontend_origin.split(",") if item.strip()}
    if origin.rstrip("/") not in trusted_origins:
        raise ValidationError("Request origin is not allowed")


def set_auth_cookie(response: Response, settings: Settings, raw_token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=settings.auth_cookie_max_age,
        httponly=True,
        samesite=cast(Literal["lax", "strict", "none"], settings.auth_cookie_samesite),
        secure=settings.auth_cookie_secure,
        path="/",
    )


def delete_auth_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=settings.auth_cookie_name, path="/")


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", Settings.from_environment())


__all__ = [
    "auth_token_hash",
    "delete_auth_cookie",
    "get_auth_repository",
    "get_auth_token_hash",
    "get_optional_current_account",
    "new_auth_token",
    "require_current_account",
    "require_trusted_origin",
    "set_auth_cookie",
]
