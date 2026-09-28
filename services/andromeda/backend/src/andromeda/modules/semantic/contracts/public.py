"""Public semantic contracts; deliberately independent of storage and channels."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    CurriculumItemId,
    DisciplineId,
    IngestRunId,
    SemanticFeatureCode,
    SemanticFeatureId,
    SemanticVersion,
    ShortText,
    SourceHash,
    UniversityId,
)
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference
from andromeda.shared.contracts.versions import (
    SEMANTIC_CLASSIFIER_VERSION,
    SEMANTIC_TAXONOMY_VERSION,
)

from .inputs import SemanticClassificationInput


class SemanticFeatureGroup(StrEnum):
    SUBJECT = "subject"
    SKILL = "skill"
    ACTIVITY = "activity"
    LEARNING_STYLE = "learning_style"
    CURRICULUM_STRUCTURE = "curriculum_structure"


class SemanticValueType(StrEnum):
    INTENSITY = "intensity"
    BOOLEAN_SIGNAL = "boolean_signal"


class SemanticClassificationMethod(StrEnum):
    MANUAL = "manual"
    RULE = "rule"
    DICTIONARY = "dictionary"
    MODEL = "model"
    JEV = "jev"
    LLM = "llm"
    INHERITED = "inherited"


class SemanticValueStatus(StrEnum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class SemanticReviewStatus(StrEnum):
    """Human-review state for inferred semantic values."""

    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class SemanticEnrichmentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SemanticFeature(ContractModel):
    id: SemanticFeatureId
    code: SemanticFeatureCode
    name: ShortText
    description: str = Field(min_length=1, max_length=1024)
    feature_group: SemanticFeatureGroup
    value_type: SemanticValueType = SemanticValueType.INTENSITY
    semantic_version: SemanticVersion = SEMANTIC_TAXONOMY_VERSION
    definition_version: SemanticVersion = SEMANTIC_TAXONOMY_VERSION
    active: bool = True
    retired_at: datetime | None = None


class SemanticFeatureDefinition(SemanticFeature):
    """Versioned registry definition; codes remain data, not Python enums."""


class SemanticClassificationEvidence(ContractModel):
    feature_id: SemanticFeatureId
    rule_id: ShortText
    matched_terms: tuple[ShortText, ...] = Field(min_length=1, max_length=16)
    rationale: str = Field(min_length=1, max_length=512)


class SemanticFeatureValue(ContractModel):
    feature_id: SemanticFeatureId
    value: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)
    status: SemanticValueStatus = SemanticValueStatus.AVAILABLE
    confidence: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)
    classification_method: SemanticClassificationMethod
    review_status: SemanticReviewStatus = SemanticReviewStatus.UNREVIEWED
    classifier_version: SemanticVersion = SEMANTIC_CLASSIFIER_VERSION
    semantic_version: SemanticVersion = SEMANTIC_TAXONOMY_VERSION
    source_hash: SourceHash | None = None
    source_run_id: IngestRunId | None = None
    created_at: datetime
    evidence: tuple[SemanticClassificationEvidence, ...] = Field(default=(), max_length=16)
    provenance: tuple[SourceAttribution, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_status_value(self) -> "SemanticFeatureValue":
        if self.status is SemanticValueStatus.AVAILABLE and self.value is None:
            raise ValueError("available semantic values require an explicit value, including zero")
        if self.status is not SemanticValueStatus.AVAILABLE and self.value is not None:
            raise ValueError("unknown or unavailable semantic values cannot carry a numeric value")
        return self


class DisciplineSemanticDefault(ContractModel):
    discipline_id: DisciplineId
    feature: SemanticFeatureValue


class CurriculumItemSemanticFeature(ContractModel):
    curriculum_item_id: CurriculumItemId
    feature: SemanticFeatureValue
    overrides_discipline_default: bool = True


class SemanticClassificationResult(ContractModel):
    discipline_id: DisciplineId
    curriculum_item_id: CurriculumItemId | None = None
    values: tuple[SemanticFeatureValue, ...] = Field(min_length=1, max_length=100)
    source_gaps: tuple[SourceGapReference, ...] = Field(default=(), max_length=20)


class SemanticEnrichmentRun(ContractModel):
    id: ShortText
    ingest_run_id: IngestRunId
    university_id: UniversityId
    status: SemanticEnrichmentRunStatus
    semantic_version: SemanticVersion
    classifier_version: SemanticVersion
    affected_item_ids: tuple[CurriculumItemId, ...] = Field(default=(), max_length=100_000)
    changed_item_ids: tuple[CurriculumItemId, ...] = Field(default=(), max_length=100_000)
    affected_item_count: int = Field(default=0, strict=True, ge=0)
    classified_item_count: int = Field(default=0, strict=True, ge=0)
    unchanged_item_count: int = Field(default=0, strict=True, ge=0)
    failed_item_count: int = Field(default=0, strict=True, ge=0)
    started_at: datetime
    finished_at: datetime | None = None
    retry_of_run_id: ShortText | None = None
    error_code: ShortText | None = None
    error_message: ShortText | None = None


class SemanticClassifierPort(Protocol):
    def classify(self, input: SemanticClassificationInput) -> SemanticClassificationResult:
        """Classify one canonical discipline/item context into typed signals."""

    @property
    def semantic_version(self) -> SemanticVersion:
        """Return the taxonomy version used by this classifier."""

    @property
    def classifier_version(self) -> SemanticVersion:
        """Return the deterministic policy version used by this classifier."""


class SemanticFeatureRegistryPort(Protocol):
    def get_by_codes(
        self,
        codes: tuple[str, ...],
        *,
        definition_version: SemanticVersion | None = None,
    ) -> tuple[SemanticFeatureDefinition, ...]: ...

    def list_active(self, definition_version: SemanticVersion) -> tuple[SemanticFeatureDefinition, ...]: ...


__all__ = [
    "CurriculumItemSemanticFeature",
    "DisciplineSemanticDefault",
    "SemanticClassificationEvidence",
    "SemanticClassificationInput",
    "SemanticClassificationMethod",
    "SemanticClassificationResult",
    "SemanticClassifierPort",
    "SemanticEnrichmentRun",
    "SemanticEnrichmentRunStatus",
    "SemanticFeature",
    "SemanticFeatureDefinition",
    "SemanticFeatureGroup",
    "SemanticFeatureRegistryPort",
    "SemanticFeatureValue",
    "SemanticReviewStatus",
    "SemanticValueStatus",
    "SemanticValueType",
]
