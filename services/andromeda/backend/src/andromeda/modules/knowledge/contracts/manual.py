"""Typed contracts for human-submitted source and claim candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AccountId,
    NonEmptyText,
    SourceHash,
    UniversityId,
)

from .claims import ClaimedPolicyStage, ClaimProposition
from .evidence import EvidenceLocator
from .sources import (
    KnowledgeSourceKind,
    SourceAllowedRoute,
    SourceId,
    SourceIdentityKey,
    SourceIssuerId,
    SourceJurisdiction,
    SourceObservationId,
    SourceReliabilityTier,
    _require_safe_https_url,
)
from .temporal import SourceMilestones, TemporalInterval

ManualSubmissionId = Annotated[
    str, StringConstraints(pattern=r"^knowledge-manual-submission:[a-f0-9]{64}$")
]
ManualIdempotencyKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=16, max_length=128)
]


class ManualSubmissionKind(StrEnum):
    SOURCE_SNAPSHOT = "source_snapshot"
    CLAIM_CANDIDATE = "claim_candidate"


class ManualSourceRegistrationDraft(ContractModel):
    source_id: SourceId
    issuer_id: SourceIssuerId
    jurisdiction: SourceJurisdiction
    identity_key: SourceIdentityKey
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
    source_kind: KnowledgeSourceKind
    reliability_tier: SourceReliabilityTier
    adapter_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,95}$")]
    adapter_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    start_url: HttpUrl
    allowlist: tuple[SourceAllowedRoute, ...] = Field(min_length=1, max_length=64)
    poll_interval_seconds: int = Field(strict=True, ge=300, le=31_536_000)
    freshness_budget_seconds: int = Field(strict=True, ge=1, le=31_536_000)
    reason: NonEmptyText

    @field_validator("start_url")
    @classmethod
    def start_url_is_safe(cls, value: HttpUrl) -> HttpUrl:
        _require_safe_https_url(value)
        return value

    @model_validator(mode="after")
    def unique_routes_and_start_allowlist(self) -> ManualSourceRegistrationDraft:
        start_path = self.start_url.path or "/"
        routes = {(route.host, route.path_prefix) for route in self.allowlist}
        if len(routes) != len(self.allowlist):
            raise ValueError("manual source allowlist routes must be unique")
        if not any(
            route.host == self.start_url.host
            and (
                route.path_prefix == "/"
                or start_path == route.path_prefix
                or start_path.startswith(route.path_prefix + "/")
            )
            for route in self.allowlist
        ):
            raise ValueError("source start URL must match an explicit allowlist route")
        return self


class ManualClaimDraft(ContractModel):
    """Operator-authored source excerpt; it still enters as a review candidate."""

    source_observation_id: SourceObservationId
    source_text: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    assertion_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
    locator: EvidenceLocator
    proposition: ClaimProposition | None = None
    claimed_stage: ClaimedPolicyStage
    source_milestones: SourceMilestones
    valid_time: TemporalInterval | None = None
    reason: NonEmptyText
    expires_at: datetime | None = None
    idempotency_key: ManualIdempotencyKey

    @field_validator("expires_at")
    @classmethod
    def expiry_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _require_aware(value, "expires_at")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def candidate_is_manual_and_pending(self) -> ManualClaimDraft:
        if self.source_milestones.captured_at is not None:
            raise ValueError("manual source capture time is assigned from the stored observation")
        if self.source_text.count(self.assertion_text) != 1:
            raise ValueError("claim assertion must occur exactly once in the supplied source excerpt")
        return self


class ManualClaimMetadataCorrection(ContractModel):
    """A scoped correction that appends a review-required claim revision."""

    claim_id: Annotated[str, StringConstraints(pattern=r"^claim:[a-f0-9]{64}$")]
    expected_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    expected_revision_hash: SourceHash
    proposition: ClaimProposition | None = None
    claimed_stage: ClaimedPolicyStage
    reason: NonEmptyText
    expires_at: datetime | None = None
    idempotency_key: ManualIdempotencyKey

    @field_validator("expires_at")
    @classmethod
    def correction_expiry_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _require_aware(value, "expires_at")
            return value.astimezone(UTC)
        return None

    @field_validator("expected_revision_hash")
    @classmethod
    def revision_hash_is_sha256(cls, value: SourceHash) -> SourceHash:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("expected_revision_hash must be a lowercase SHA-256 digest")
        return value


class KnowledgeManualSubmission(ContractModel):
    """Append-only audit metadata for one exact human-submitted candidate."""

    submission_id: ManualSubmissionId
    kind: ManualSubmissionKind
    idempotency_key: SourceHash
    request_fingerprint: SourceHash
    actor_account_id: AccountId
    university_id: UniversityId | None = None
    reason: NonEmptyText
    target_id: Annotated[str, StringConstraints(min_length=1, max_length=140)]
    target_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    target_hash: SourceHash
    source_observation_id: SourceObservationId
    expires_at: datetime | None = None
    recorded_at: datetime

    @field_validator("expires_at", "recorded_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _require_aware(value, "manual submission timestamp")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def exact_candidate_identity(self) -> KnowledgeManualSubmission:
        if self.kind is ManualSubmissionKind.CLAIM_CANDIDATE:
            if not self.target_id.startswith("claim:"):
                raise ValueError("claim submission must target a claim candidate")
        elif not self.target_id.startswith("source-observation:"):
            raise ValueError("snapshot submission must target its source observation")
        if self.expires_at is not None and self.expires_at <= self.recorded_at:
            raise ValueError("manual submission expiry must follow its recorded time")
        if self.submission_id != manual_submission_id(
            actor_account_id=self.actor_account_id,
            idempotency_key=self.idempotency_key,
            request_fingerprint=self.request_fingerprint,
        ):
            raise ValueError("manual submission ID does not match its immutable identity")
        return self


def manual_submission_id(
    *, actor_account_id: str, idempotency_key: str, request_fingerprint: str
) -> ManualSubmissionId:
    payload = json.dumps(
        {
            "actor_account_id": actor_account_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"knowledge-manual-submission:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def manual_request_fingerprint(payload: object) -> SourceHash:
    if hasattr(payload, "model_dump"):
        value = payload.model_dump(mode="json")
    else:
        value = payload
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "KnowledgeManualSubmission",
    "ManualClaimDraft",
    "ManualClaimMetadataCorrection",
    "ManualIdempotencyKey",
    "ManualSourceRegistrationDraft",
    "ManualSubmissionId",
    "ManualSubmissionKind",
    "manual_request_fingerprint",
    "manual_submission_id",
]
