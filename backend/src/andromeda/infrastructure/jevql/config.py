"""Validated jevQL deployment configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class JevQLMode(StrEnum):
    AUTO = "auto"
    EMBEDDED = "embedded"
    SHARED_SERVICE = "shared_service"


@dataclass(frozen=True, slots=True)
class JevQLConfig:
    mode: JevQLMode = JevQLMode.AUTO
    timeout_seconds: float = 2.0
    max_rows: int = 100
    max_chars_per_row: int = 2000
    max_batch_size: int = 32
    max_concurrency: int = 1
    max_failures: int = 3
    circuit_open_seconds: float = 30.0
    shared_endpoint: str | None = None
    shared_allowed_hosts: tuple[str, ...] = ()
    shared_bearer_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", JevQLMode(self.mode))
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("jevQL timeout must be between zero and thirty seconds")
        if not 0 < self.max_rows <= 1000 or not 0 < self.max_chars_per_row <= 8000:
            raise ValueError("jevQL row budget is outside the supported bounds")
        if not 0 < self.max_batch_size <= 100 or not 0 < self.max_concurrency <= 8:
            raise ValueError("jevQL concurrency budget is outside the supported bounds")
        if self.max_failures < 1 or self.circuit_open_seconds <= 0:
            raise ValueError("jevQL circuit-breaker bounds are invalid")
        if self.shared_endpoint is not None:
            parsed = urlparse(self.shared_endpoint)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise ValueError("jevQL shared endpoint must be an absolute HTTP URL")
            if parsed.hostname not in self.shared_allowed_hosts:
                raise ValueError("jevQL shared endpoint host is not allow-listed")


__all__ = ["JevQLConfig", "JevQLMode"]
