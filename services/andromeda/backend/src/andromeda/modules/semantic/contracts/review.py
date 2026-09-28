"""Typed, review-only contracts for semantic active-learning queues."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import CurriculumItemId, DisciplineId, SemanticVersion, SourceHash
from andromeda.shared.contracts.provenance import SourceAttribution

from .public import SemanticFeatureValue


class SemanticReviewReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    MISSING_COVERAGE = "missing_coverage"
    DETERMINISTIC_DISAGREEMENT = "deterministic_disagreement"
    TAXONOMY_CHANGED = "taxonomy_changed"


class SemanticReviewCandidate(ContractModel):
    discipline_id: DisciplineId
    curriculum_item_id: CurriculumItemId | None = None
    discipline_name: str = Field(min_length=1, max_length=256)
    values: tuple[SemanticFeatureValue, ...] = Field(default=(), max_length=100)
    source_hash: SourceHash | None = None
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    deterministic_disagreement: bool = False
    taxonomy_changed: bool = False
    created_at: datetime


class SemanticReviewQueueItem(ContractModel):
    queue_id: str = Field(pattern=r"^semantic-review:[a-f0-9]{32}$")
    discipline_id: DisciplineId
    curriculum_item_id: CurriculumItemId | None = None
    discipline_name: str = Field(min_length=1, max_length=256)
    reasons: tuple[SemanticReviewReason, ...] = Field(min_length=1, max_length=4)
    values: tuple[SemanticFeatureValue, ...] = Field(default=(), max_length=100)
    source_hash: SourceHash | None = None
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=20)
    created_at: datetime


def build_review_queue(
    candidates: Iterable[SemanticReviewCandidate],
    *,
    reviewed_queue_ids: frozenset[str] = frozenset(),
    confidence_floor: Decimal = Decimal("0.80"),
) -> tuple[SemanticReviewQueueItem, ...]:
    """Build an idempotent queue without coercing unavailable values to zero."""

    if not Decimal("0") <= confidence_floor <= Decimal("1"):
        raise ValueError("confidence floor must be between zero and one")
    result: list[SemanticReviewQueueItem] = []
    for candidate in candidates:
        reasons = _reasons(candidate, confidence_floor)
        if not reasons:
            continue
        queue_id = _queue_id(candidate)
        if queue_id in reviewed_queue_ids:
            continue
        provenance_items: list[SourceAttribution] = []
        for value in candidate.values:
            for attribution in value.provenance:
                if attribution not in provenance_items:
                    provenance_items.append(attribution)
        provenance = tuple(provenance_items)
        result.append(
            SemanticReviewQueueItem(
                queue_id=queue_id,
                discipline_id=candidate.discipline_id,
                curriculum_item_id=candidate.curriculum_item_id,
                discipline_name=candidate.discipline_name,
                reasons=reasons,
                values=candidate.values,
                source_hash=candidate.source_hash,
                semantic_version=candidate.semantic_version,
                classifier_version=candidate.classifier_version,
                provenance=provenance,
                created_at=candidate.created_at,
            )
        )
    return tuple(result)


def _reasons(candidate: SemanticReviewCandidate, confidence_floor: Decimal) -> tuple[SemanticReviewReason, ...]:
    reasons: list[SemanticReviewReason] = []
    if not candidate.values or any(value.status.value != "available" for value in candidate.values):
        reasons.append(SemanticReviewReason.MISSING_COVERAGE)
    if any(value.value is not None and value.confidence < confidence_floor for value in candidate.values):
        reasons.append(SemanticReviewReason.LOW_CONFIDENCE)
    if candidate.deterministic_disagreement:
        reasons.append(SemanticReviewReason.DETERMINISTIC_DISAGREEMENT)
    if candidate.taxonomy_changed:
        reasons.append(SemanticReviewReason.TAXONOMY_CHANGED)
    return tuple(reasons)


def _queue_id(candidate: SemanticReviewCandidate) -> str:
    import hashlib

    identity = ":".join(
        (
            candidate.curriculum_item_id or candidate.discipline_id,
            candidate.semantic_version,
            candidate.source_hash or "missing-source-hash",
        )
    )
    return f"semantic-review:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


__all__ = [
    "SemanticReviewCandidate",
    "SemanticReviewQueueItem",
    "SemanticReviewReason",
    "build_review_queue",
]
