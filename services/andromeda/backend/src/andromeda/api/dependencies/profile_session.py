"""Anonymous profile session boundary for the HTTP API."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from typing import Literal, cast

from fastapi import Depends, Request, Response

from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.proftest.contracts.public import ProfileScope

from .auth_session import get_optional_current_account


logger = logging.getLogger("andromeda.api.profile_session")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def resolve_profile_scope(request: Request, response: Response, settings: Settings, account_id: str | None = None) -> ProfileScope:
    """Resolve a request to a hash-only profile scope and set a cookie if needed."""

    raw_token = request.cookies.get(settings.profile_cookie_name)
    event = "session_cookie_reused"
    if raw_token is None:
        raw_token = secrets.token_urlsafe(32)
        _set_session_cookie(request, response, settings, raw_token)
        event = "session_cookie_missing"
    elif _TOKEN_PATTERN.fullmatch(raw_token) is None:
        logger.warning(
            "profile_session_cookie_rotated reason=malformed endpoint=%s correlation_id=%s",
            request.url.path,
            getattr(request.state, "correlation_id", "-"),
        )
        raw_token = secrets.token_urlsafe(32)
        _set_session_cookie(request, response, settings, raw_token)
        event = "session_cookie_rotated"

    logger.debug(
        "profile_session_resolved event=%s endpoint=%s correlation_id=%s",
        event,
        request.url.path,
        getattr(request.state, "correlation_id", "-"),
    )
    session_key_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    return ProfileScope(session_key_hash=session_key_hash, account_id=account_id)


def get_profile_scope(
    request: Request,
    response: Response,
    account: Account | None = Depends(get_optional_current_account),
) -> ProfileScope:
    """FastAPI dependency exposing only the typed, one-way profile scope."""

    settings = getattr(request.app.state, "settings", Settings.from_environment())
    return resolve_profile_scope(request, response, settings, account_id=account.account_id if account is not None else None)


def get_anonymous_profile_scope(request: Request, response: Response) -> ProfileScope:
    """Resolve only the anonymous owner for auth-time profile transfer."""

    settings = getattr(request.app.state, "settings", Settings.from_environment())
    return resolve_profile_scope(request, response, settings)


def _set_session_cookie(request: Request, response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.profile_cookie_name,
        value=token,
        max_age=settings.profile_cookie_max_age,
        httponly=True,
        samesite=cast(Literal["lax", "strict", "none"], settings.profile_cookie_samesite),
        secure=settings.profile_cookie_secure,
        path="/",
    )
    # Exception handlers return a replacement Response. Keep the rendered
    # header request-local so middleware can preserve it without exposing the
    # token to application contracts or logs.
    request.state.profile_cookie_header = response.headers.get("set-cookie")


__all__ = ["get_anonymous_profile_scope", "get_profile_scope", "resolve_profile_scope"]
