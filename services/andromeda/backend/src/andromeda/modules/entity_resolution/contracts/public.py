"""Bounded, explainable results shared by every channel adapter."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import DirectionId, EducationYear, UniversityId


class ResolutionEntityType(StrEnum):
    UNIVERSITY = "university"
    DIRECTION = "direction"
    PROGRAM = "program"
    DISCIPLINE = "discipline"
    METRIC = "metric"
    OLYMPIAD = "olympiad"
    OLYMPIAD_PROFILE = "olympiad_profile"


class ResolutionStatus(StrEnum):
    EXACT = "exact"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class CandidateMatchReason(StrEnum):
    CANONICAL_ID = "canonical_id"
    CODE = "code"
    ALIAS = "alias"
    NAME = "name"
    TOKEN_MATCH = "token_match"


class ResolutionContext(ContractModel):
    university_id: UniversityId | None = None
    direction_id: DirectionId | None = None
    admission_year: EducationYear | None = None


class EntityResolutionCandidate(ContractModel):
    entity_type: ResolutionEntityType
    canonical_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=512)
    match_reason: CandidateMatchReason
    score: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    confidence: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"))
    university_id: UniversityId | None = None
    direction_id: DirectionId | None = None
    code: str | None = Field(default=None, max_length=128)
    parent_id: str | None = Field(default=None, max_length=256)
    admission_year: EducationYear | None = None


class EntityResolutionResult(ContractModel):
    entity_type: ResolutionEntityType
    query: str = Field(min_length=1, max_length=512)
    status: ResolutionStatus
    candidates: tuple[EntityResolutionCandidate, ...] = Field(default=(), max_length=1000)
    selected_id: str | None = Field(default=None, min_length=1, max_length=256)
    resolution_strategy: str = Field(default="deterministic", min_length=1, max_length=64)
    candidate_hash: str | None = Field(default=None, min_length=1, max_length=128)
    resolution_evidence: dict[str, str] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def validate_selection(self) -> EntityResolutionResult:
        ids = tuple(candidate.canonical_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("resolution candidates must have unique canonical ids")
        if self.selected_id is not None and self.selected_id not in ids:
            raise ValueError("selected resolution candidate must be present in candidates")
        if self.status is ResolutionStatus.AMBIGUOUS and self.selected_id is not None:
            raise ValueError("ambiguous resolution must not silently select a candidate")
        if self.status is ResolutionStatus.NOT_FOUND and self.candidates:
            raise ValueError("not found resolution must not contain candidates")
        if self.status in {ResolutionStatus.EXACT, ResolutionStatus.RESOLVED} and self.selected_id is None:
            raise ValueError("resolved result must identify its selected candidate")
        return self


__all__ = [
    "CandidateMatchReason",
    "EntityResolutionCandidate",
    "EntityResolutionResult",
    "ResolutionContext",
    "ResolutionEntityType",
    "ResolutionStatus",
]
