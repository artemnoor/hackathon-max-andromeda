"""Typed identity, registry, and capture-observation contracts."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import unquote

from pydantic import Field, HttpUrl, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AccountId,
    IngestRunId,
    NonEmptyText,
    SourceHash,
)

SourceId = Annotated[str, StringConstraints(pattern=r"^source:[a-z0-9][a-z0-9-]{0,95}$")]
SourceIssuerId = Annotated[str, StringConstraints(pattern=r"^issuer:[a-z0-9][a-z0-9-]{0,95}$")]
SourceObservationId = Annotated[
    str,
    StringConstraints(pattern=r"^source-observation:[a-f0-9]{32}$"),
]
SourceIdentityKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,95}$")]
SourceAdapterId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,95}$")]
SourceHost = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=253,
        pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$",
    ),
]


class SourceJurisdiction(StrEnum):
    FEDERAL = "federal"
    REGIONAL = "regional"
    UNIVERSITY = "university"
    INTERNATIONAL = "international"
    UNKNOWN = "unknown"


class KnowledgeSourceKind(StrEnum):
    NORMATIVE_DOCUMENT = "normative_document"
    MINISTRY_PUBLICATION = "ministry_publication"
    UNIVERSITY_ADMISSION_RULES = "university_admission_rules"
    UNIVERSITY_ORDER = "university_order"
    OFFICIAL_APPENDIX = "official_appendix"
    OFFICIAL_NEWS = "official_news"
    OFFICIAL_FEED = "official_feed"
    OFFICIAL_API = "official_api"


class SourceReliabilityTier(StrEnum):
    PRIMARY_NORMATIVE = "primary_normative"
    OFFICIAL_ISSUER = "official_issuer"
    OFFICIAL_UNIVERSITY = "official_university"
    TRUSTED_SECONDARY = "trusted_secondary"
    UNVERIFIED_SECONDARY = "unverified_secondary"
    COMMUNITY = "community"
    USER_SUPPLIED = "user_supplied"
    UNKNOWN = "unknown"


class SourceIdentity(ContractModel):
    source_id: SourceId
    issuer_id: SourceIssuerId
    jurisdiction: SourceJurisdiction
    identity_key: SourceIdentityKey
    display_name: str = Field(min_length=1, max_length=256)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class SourceAllowedRoute(ContractModel):
    host: SourceHost
    path_prefix: str = Field(min_length=1, max_length=1024)

    @field_validator("host")
    @classmethod
    def reject_ip_literals(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return value
        raise ValueError("source allowlist hosts must be DNS names")

    @field_validator("path_prefix")
    @classmethod
    def validate_path_prefix(cls, value: str) -> str:
        decoded = unquote(value)
        if (
            not value.startswith("/")
            or "?" in value
            or "#" in value
            or "\\" in decoded
            or any(part == ".." for part in decoded.split("/"))
            or any(ord(char) < 32 for char in decoded)
        ):
            raise ValueError("path_prefix must be a normalized absolute path without query or traversal")
        return value.rstrip("/") or "/"


class ApprovedSourceRegistryRevision(ContractModel):
    """An approved immutable registry version; drafts live in review workflow."""

    source_id: SourceId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    source_kind: KnowledgeSourceKind
    reliability_tier: SourceReliabilityTier
    adapter_id: SourceAdapterId
    adapter_version: str = Field(min_length=1, max_length=64)
    start_url: HttpUrl
    allowlist: tuple[SourceAllowedRoute, ...] = Field(min_length=1, max_length=64)
    poll_interval_seconds: int = Field(strict=True, ge=300, le=31_536_000)
    freshness_budget_seconds: int = Field(strict=True, ge=1, le=31_536_000)
    enabled: bool
    approved_by_account_id: AccountId
    approved_at: datetime
    approval_reason: NonEmptyText
    recorded_at: datetime

    @field_validator("start_url")
    @classmethod
    def require_https_start_url(cls, value: HttpUrl) -> HttpUrl:
        _require_safe_https_url(value)
        return value

    @field_validator("approved_at", "recorded_at")
    @classmethod
    def require_aware_registry_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_approved_allowlist(self) -> ApprovedSourceRegistryRevision:
        routes = {(item.host, item.path_prefix) for item in self.allowlist}
        if len(routes) != len(self.allowlist):
            raise ValueError("allowlist routes must be unique")
        if not any(_route_allows(self.start_url, item) for item in self.allowlist):
            raise ValueError("start_url must match an explicit allowlist route")
        if self.recorded_at < self.approved_at:
            raise ValueError("recorded_at cannot precede approval")
        return self


class SourceObservation(ContractModel):
    source_observation_id: SourceObservationId
    source_id: SourceId
    registry_revision: int = Field(strict=True, ge=1)
    idempotency_key: SourceHash
    ingest_run_id: IngestRunId
    snapshot_sha256: SourceHash
    requested_url: HttpUrl
    final_url: HttpUrl
    status_code: int = Field(strict=True, ge=200, le=599)
    content_type: str | None = Field(default=None, max_length=256)
    response_class: str = Field(min_length=1, max_length=64)
    access_mode: str = Field(min_length=1, max_length=32)
    truncated: bool
    captured_at: datetime
    observed_at: datetime

    @field_validator("requested_url", "final_url")
    @classmethod
    def require_safe_https_urls(cls, value: HttpUrl) -> HttpUrl:
        _require_safe_https_url(value)
        return value

    @field_validator("captured_at", "observed_at")
    @classmethod
    def require_aware_observation_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_observation_time_order(self) -> SourceObservation:
        if self.observed_at < self.captured_at:
            raise ValueError("observed_at cannot precede captured_at")
        return self


def _require_safe_https_url(value: HttpUrl) -> None:
    if (
        value.scheme != "https"
        or value.username
        or value.password
        or value.port not in (None, 443)
        or value.query
        or value.fragment
    ):
        raise ValueError("source URLs must be HTTPS and contain no credentials, query, or fragment")


def _route_allows(url: HttpUrl, route: SourceAllowedRoute) -> bool:
    path = url.path or "/"
    prefix = route.path_prefix.rstrip("/") or "/"
    decoded_path = unquote(path)
    host = url.host
    return (
        host is not None
        and "\\" not in decoded_path
        and not any(part == ".." for part in decoded_path.split("/"))
        and host.lower() == route.host
        and (prefix == "/" or path == prefix or path.startswith(prefix + "/"))
    )


__all__ = [
    "ApprovedSourceRegistryRevision",
    "KnowledgeSourceKind",
    "SourceAllowedRoute",
    "SourceHost",
    "SourceId",
    "SourceIdentity",
    "SourceIdentityKey",
    "SourceIssuerId",
    "SourceJurisdiction",
    "SourceObservation",
    "SourceObservationId",
    "SourceReliabilityTier",
]
