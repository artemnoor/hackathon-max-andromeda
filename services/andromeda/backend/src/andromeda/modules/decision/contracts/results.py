"""Results and derived suggestion contracts for decision consumers."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from andromeda.modules.admission_fit.contracts.public import AdmissionFitResult, AdmissionFitStatus
from andromeda.modules.proftest.contracts.public import MatchScore, RecommendationEvidence
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import NonEmptyText, ProgramCode, ProgramId, ShortText, SourceHash
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from ..domain.entities import DecisionContext
from ..domain.values import AdmissionGate, DecisionId, ShortlistEntryState, ShortlistRole


class DecisionCandidatePartition(StrEnum):
    """Derived bucket for a candidate; it is never persisted as user choice."""

    PRIMARY = "primary"
    ALTERNATIVE = "alternative"
    INELIGIBLE = "ineligible"
    INSUFFICIENT_DATA = "insufficient_data"


class DecisionConstraintDimension(StrEnum):
    """User-entered decision dimensions that can be checked per candidate."""

    APPLICANT_SCORES = "applicant_scores"
    ADMISSION_YEAR = "admission_year"
    FUNDING = "funding"
    STUDY_FORM = "study_form"
    MAX_TUITION = "max_tuition"
    LOCATION = "location"


class DecisionConstraintApplicability(StrEnum):
    """Whether a candidate constraint was compared against source facts."""

    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_DATA = "insufficient_data"


class DecisionDataCompleteness(StrEnum):
    """Completeness of the evidence shown by one suggestions read."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class DecisionContextResult(ContractModel):
    """Current explicit context plus its read-only preference projection."""

    decision_id: DecisionId
    context: DecisionContext


class DecisionMutationResult(ContractModel):
    """Result of an explicit transition, including the new optimistic revision."""

    decision_id: DecisionId
    context: DecisionContext
    changed: bool


class DecisionSuggestionReasons(ContractModel):
    """Separate, user-facing evidence buckets; no opaque combined score."""

    why_included: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)
    why_may_not_fit: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)
    admission_risk: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)
    content_differences: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)
    missing_data: tuple[NonEmptyText, ...] = Field(default=(), max_length=8)


class DecisionConstraintOutcome(ContractModel):
    """Typed, candidate-level result for one explicit user constraint."""

    dimension: DecisionConstraintDimension
    applicability: DecisionConstraintApplicability
    satisfied: bool | None = None
    message: NonEmptyText
    source_gaps: tuple[ShortText, ...] = Field(default=(), max_length=4)


class DecisionSuggestion(ContractModel):
    """System-derived candidate proposal, never persisted as user choice."""

    program_id: ProgramId
    program_code: ProgramCode
    program_name: NonEmptyText
    partition: DecisionCandidatePartition = DecisionCandidatePartition.PRIMARY
    admission_status: AdmissionFitStatus | None = None
    admission_risk: AdmissionGate = AdmissionGate.NOT_EVALUATED
    admission_fit: AdmissionFitResult | None = None
    content_fit: MatchScore | None = None
    evidence: RecommendationEvidence | None = None
    constraint_outcomes: tuple[DecisionConstraintOutcome, ...] = Field(default=(), max_length=8)
    reasons: DecisionSuggestionReasons
    source_gaps: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    source_hashes: tuple[SourceHash, ...] = Field(default=(), max_length=8)
    provenance: tuple[SourceAttribution, ...] = ()
    source_gap_details: tuple[SourceGapReference, ...] = ()


class DecisionShortlistItem(ContractModel):
    """Read-only evidence for an active explicit shortlist entry.

    Program metadata is optional because a retained user choice must remain
    visible even when the current catalog snapshot has a source gap.
    """

    program_id: ProgramId
    program_code: ProgramCode | None = None
    program_name: NonEmptyText | None = None
    role: ShortlistRole
    state: ShortlistEntryState = ShortlistEntryState.ACTIVE
    admission_status: AdmissionFitStatus | None = None
    admission_risk: AdmissionGate = AdmissionGate.NOT_EVALUATED
    admission_fit: AdmissionFitResult | None = None
    content_fit: MatchScore | None = None
    evidence: RecommendationEvidence | None = None
    constraint_outcomes: tuple[DecisionConstraintOutcome, ...] = Field(default=(), max_length=8)
    reasons: DecisionSuggestionReasons
    source_gaps: tuple[NonEmptyText, ...] = Field(default=(), max_length=16)
    source_hashes: tuple[SourceHash, ...] = Field(default=(), max_length=8)
    provenance: tuple[SourceAttribution, ...] = ()
    source_gap_details: tuple[SourceGapReference, ...] = ()


class DecisionRefinementOption(ContractModel):
    """Bounded answer option for a deterministic candidate refinement question."""

    id: ShortText
    label: NonEmptyText
    affected_dimension: ShortText
    effect: NonEmptyText = "уточняет различие между кандидатами"


class DecisionRefinementQuestion(ContractModel):
    """Optional question shown only when it can distinguish current candidates."""

    id: ShortText
    prompt: NonEmptyText
    candidate_program_ids: tuple[ProgramId, ...] = Field(min_length=2, max_length=3)
    options: tuple[DecisionRefinementOption, ...] = Field(min_length=2, max_length=4)
    discriminating_dimensions: tuple[ShortText, ...] = Field(default=(), max_length=4)


class DecisionSuggestionsResult(ContractModel):
    """Derived candidates and uncertainty for the current context."""

    decision_id: DecisionId
    context_revision: int = Field(strict=True, ge=1)
    data_completeness: DecisionDataCompleteness = DecisionDataCompleteness.UNAVAILABLE
    active_shortlist: tuple[DecisionShortlistItem, ...] = Field(default=(), max_length=20)
    primary_candidates: tuple[DecisionSuggestion, ...] = Field(default=(), max_length=3)
    alternative_candidates: tuple[DecisionSuggestion, ...] = Field(default=(), max_length=2)
    ineligible_candidates: tuple[DecisionSuggestion, ...] = Field(default=(), max_length=20)
    insufficient_data_candidates: tuple[DecisionSuggestion, ...] = Field(default=(), max_length=20)
    suggestions: tuple[DecisionSuggestion, ...] = Field(default=(), max_length=5)
    refinement_question: DecisionRefinementQuestion | None = None
    source_gaps: tuple[NonEmptyText, ...] = Field(default=(), max_length=32)
    missing_data: tuple[NonEmptyText, ...] = Field(default=(), max_length=32)


class DecisionRefinementResult(ContractModel):
    """Updated derived candidates after an explicit profile refinement."""

    suggestions: DecisionSuggestionsResult
    profile_revision: int = Field(strict=True, ge=1)


__all__ = [
    "DecisionCandidatePartition",
    "DecisionConstraintApplicability",
    "DecisionConstraintDimension",
    "DecisionConstraintOutcome",
    "DecisionContextResult",
    "DecisionDataCompleteness",
    "DecisionMutationResult",
    "DecisionRefinementOption",
    "DecisionRefinementQuestion",
    "DecisionRefinementResult",
    "DecisionShortlistItem",
    "DecisionSuggestion",
    "DecisionSuggestionReasons",
    "DecisionSuggestionsResult",
]
