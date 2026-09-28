"""Deterministic identity helpers for the knowledge source boundary."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import unquote, urlsplit


def observation_idempotency_key(
    *,
    source_id: str,
    registry_revision: int,
    ingest_run_id: str,
    requested_url: str,
    snapshot_sha256: str,
) -> str:
    """Return a stable key for one source URL/content capture within a run."""

    value = {
        "source_id": source_id,
        "registry_revision": registry_revision,
        "ingest_run_id": ingest_run_id,
        "requested_url": _safe_url_identity(requested_url),
        "snapshot_sha256": snapshot_sha256,
    }
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def observation_id_from_idempotency_key(idempotency_key: str) -> str:
    if len(idempotency_key) != 64 or any(char not in "0123456789abcdef" for char in idempotency_key):
        raise ValueError("idempotency_key must be a lowercase SHA-256 digest")
    return f"source-observation:{idempotency_key[:32]}"


def is_allowed_source_url(url: str, *, host: str, path_prefix: str) -> bool:
    """Match an HTTPS URL to one explicit host and path-prefix allowlist row."""

    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return False
        if parsed.query or parsed.fragment or parsed.hostname.lower() != host.lower():
            return False
        path = unquote(parsed.path or "/")
        if "\\" in path or any(part == ".." for part in path.split("/")):
            return False
        prefix = path_prefix.rstrip("/") or "/"
        return prefix == "/" or path == prefix or path.startswith(prefix + "/")
    except (TypeError, ValueError):
        return False


def _safe_url_identity(value: str) -> str:
    """Normalize only URL syntax; never include credentials/query values in keys."""

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("source URL identity must be HTTPS and contain no credentials, query, or fragment")
    path = unquote(parsed.path or "/")
    if "\\" in path or any(part == ".." for part in path.split("/")):
        raise ValueError("source URL identity must not contain path traversal")
    return f"https://{parsed.hostname.lower()}{path}"


__all__ = [
    "is_allowed_source_url",
    "observation_id_from_idempotency_key",
    "observation_idempotency_key",
]
