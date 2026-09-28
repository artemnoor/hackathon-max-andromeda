"""Small, process-local controls for the public HTTP boundary.

The API is currently a single process per deployment unit. The limiter is
therefore intentionally bounded and process-local; a multi-replica rollout
must move this state to a shared store before relying on it as a global quota.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from re import Pattern, compile
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import Request

from andromeda.infrastructure.config.settings import Settings
from andromeda.shared.contracts.errors import RateLimitError, ValidationError


_CORRELATION_ID_PATTERN: Pattern[str] = compile(r"^[A-Za-z0-9._:-]{1,64}$")
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTH_RATE_LIMITED_PATHS = frozenset({
    "/auth/login",
    "/auth/register",
    "/auth/decision/import-guest",
})
_SENSITIVE_RATE_LIMITED_PATHS = frozenset({
    "/proftest/results",
    "/proftest/profile",
    "/proftest/sessions",
    "/proftest/sessions/current",
    "/proftest/sessions/current/next",
    "/proftest/sessions/current/complete",
})


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    key_prefix: str
    limit: int


class SlidingWindowRateLimiter:
    """Bounded in-memory sliding-window limiter for one API process."""

    def __init__(self, window_seconds: int, *, max_keys: int = 4096) -> None:
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self._window_seconds = float(window_seconds)
        self._max_keys = max_keys
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, limit: int, *, now: float | None = None) -> bool:
        if limit < 1:
            return False
        current = monotonic() if now is None else now
        cutoff = current - self._window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(current)
            self._trim_empty_buckets()
            return True

    def _trim_empty_buckets(self) -> None:
        if len(self._buckets) <= self._max_keys:
            return
        empty = [key for key, bucket in self._buckets.items() if not bucket]
        for key in empty[: len(self._buckets) - self._max_keys]:
            self._buckets.pop(key, None)
        while len(self._buckets) > self._max_keys:
            self._buckets.pop(next(iter(self._buckets)))


def normalize_correlation_id(value: str | None) -> str:
    if value is not None and _CORRELATION_ID_PATTERN.fullmatch(value) is not None:
        return value
    return uuid4().hex


def enforce_trusted_origin(request: Request, settings: Settings) -> None:
    """Reject browser state changes from an origin outside the configured UI."""

    if request.method not in _MUTATING_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        # Non-browser clients and same-origin form-less API integrations do not
        # always send Origin. SameSite cookies remain the browser-side guard.
        return
    trusted_origins = {
        item.strip().rstrip("/")
        for item in settings.frontend_origin.split(",")
        if item.strip()
    }
    if origin.rstrip("/") not in trusted_origins:
        raise ValidationError("Request origin is not allowed")


def rate_limit_policy(request: Request, settings: Settings) -> RateLimitPolicy | None:
    if request.method not in _MUTATING_METHODS:
        return None
    path = _legacy_api_path(request.url.path)
    if path in _AUTH_RATE_LIMITED_PATHS:
        return RateLimitPolicy("auth", settings.auth_rate_limit_max)
    if path.startswith("/ops/"):
        return RateLimitPolicy("ops", settings.ops_rate_limit_max)
    if path in _SENSITIVE_RATE_LIMITED_PATHS or path.startswith("/decision/"):
        return RateLimitPolicy("sensitive", settings.sensitive_rate_limit_max)
    return None


def enforce_rate_limit(request: Request, limiter: SlidingWindowRateLimiter, settings: Settings) -> None:
    policy = rate_limit_policy(request, settings)
    if policy is None:
        return
    client_host = request.client.host if request.client is not None else "unknown"
    path = _legacy_api_path(request.url.path)
    key = f"{policy.key_prefix}:{client_host}:{request.method}:{path}"
    if not limiter.allow(key, policy.limit):
        raise RateLimitError()


def _legacy_api_path(path: str) -> str:
    """Map only the public v1 prefix to its legacy path for shared policies."""

    prefix = "/api/v1"
    if path == prefix:
        return "/"
    if path.startswith(f"{prefix}/"):
        return path[len(prefix) :]
    return path


__all__ = [
    "RateLimitPolicy",
    "SlidingWindowRateLimiter",
    "enforce_rate_limit",
    "enforce_trusted_origin",
    "normalize_correlation_id",
    "rate_limit_policy",
]
