"""Typed, source-backed relationships between exact claim revisions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .claims import ClaimRevisionRef
from .evidence import EvidenceRef
from .temporal import TemporalInterval

KnowledgeRelationId = Annotated[str, StringConstraints(pattern=r"^knowledge-relation:[a-f0-9]{64}$")]


class KnowledgeRelationKind(StrEnum):
    SUPPORTED_BY = "supported_by"
    CONTRADICTS = "contradicts"
    CLARIFIES = "clarifies"
    DERIVED_FROM = "derived_from"


class KnowledgeRelationReviewState(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class KnowledgeClaimRelationRevisionFields(ContractModel):
    relation_id: KnowledgeRelationId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    kind: KnowledgeRelationKind
    source: ClaimRevisionRef
    target: ClaimRevisionRef
    valid_time: TemporalInterval | None = None
    review_state: KnowledgeRelationReviewState = KnowledgeRelationReviewState.CANDIDATE
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=64)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("knowledge relation recorded_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_exact_typed_edge(self) -> KnowledgeClaimRelationRevisionFields:
        source_key = (self.source.claim_id, self.source.revision)
        target_key = (self.target.claim_id, self.target.revision)
        if source_key == target_key:
            raise ValueError("knowledge claim relations cannot be self edges")
        if self.kind is KnowledgeRelationKind.CONTRADICTS and source_key > target_key:
            raise ValueError("symmetric CONTRADICTS endpoints must use canonical order")
        if self.relation_id != knowledge_relation_id(self.kind, self.source, self.target):
            raise ValueError("knowledge relation ID does not match its typed endpoints")
        evidence_keys = tuple(_evidence_key(item) for item in self.evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("knowledge relation evidence references must be unique")
        return self


class KnowledgeClaimRelationRevision(KnowledgeClaimRelationRevisionFields):
    content_hash: SourceHash

    @model_validator(mode="after")
    def content_hash_matches(self) -> KnowledgeClaimRelationRevision:
        if self.content_hash != knowledge_relation_content_hash(self):
            raise ValueError("knowledge relation content hash does not match immutable revision")
        return self


def knowledge_relation_id(
    kind: KnowledgeRelationKind,
    source: ClaimRevisionRef,
    target: ClaimRevisionRef,
) -> KnowledgeRelationId:
    left = (source.claim_id, source.revision)
    right = (target.claim_id, target.revision)
    if kind is KnowledgeRelationKind.CONTRADICTS and right < left:
        left, right = right, left
    canonical = json.dumps(
        {"kind": kind.value, "source": left, "target": right},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"knowledge-relation:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def knowledge_relation_content_hash(
    relation: KnowledgeClaimRelationRevisionFields,
) -> SourceHash:
    payload = relation.model_dump(mode="json", exclude={"content_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_key(evidence: EvidenceRef) -> tuple[str, str, str, str]:
    return (
        evidence.source_observation_id,
        evidence.snapshot_sha256,
        str(evidence.source_url),
        evidence.locator.model_dump_json(),
    )


__all__ = [
    "KnowledgeClaimRelationRevision",
    "KnowledgeClaimRelationRevisionFields",
    "KnowledgeRelationId",
    "KnowledgeRelationKind",
    "KnowledgeRelationReviewState",
    "knowledge_relation_content_hash",
    "knowledge_relation_id",
]
