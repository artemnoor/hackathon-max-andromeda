"""Typed, bounded language-model work used to drive assistant turns."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import Field

from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.admission_benefits.contracts.public import OlympiadResultType
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear

from .public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    ExamScore,
)


class AssistantEntityMention(ContractModel):
    """A user phrase to resolve against the canonical catalog, never an ID."""

    entity_type: ResolutionEntityType
    query: str = Field(min_length=1, max_length=512)


class AssistantQueryInterpretation(ContractModel):
    """A model-extracted query candidate that domain services must validate."""

    intent: ConversationIntent
    olympiad_query: str | None = Field(default=None, min_length=1, max_length=256)
    olympiad_profile_query: str | None = Field(default=None, min_length=1, max_length=256)
    olympiad_result_year: EducationYear | None = None
    olympiad_level: int | None = Field(default=None, strict=True, ge=1, le=3)
    olympiad_result_type: OlympiadResultType | None = None
    entities: tuple[AssistantEntityMention, ...] = Field(default=(), max_length=12)
    metric_codes: tuple[str, ...] = Field(default=(), max_length=8)
    total_score: Decimal | None = Field(
        default=None, strict=True, ge=Decimal(0), le=Decimal(400)
    )
    exam_scores: tuple[ExamScore, ...] = Field(default=(), max_length=16)
    preferred_areas: tuple[DisciplineAreaCode, ...] = Field(default=(), max_length=8)
    avoided_areas: tuple[DisciplineAreaCode, ...] = Field(default=(), max_length=8)
    funding_type: FundingType | None = None
    study_form: StudyForm | None = None
    study_form_ambiguous: bool = False
    admission_year: EducationYear | None = None
    admission_university_scope: AdmissionUniversityScope | None = None
    compare_with_any_other_direction: bool = False
    starts_new_task: bool = False
    unverified_answer: str | None = Field(default=None, max_length=4_000)


class AssistantEntityCandidate(ContractModel):
    """One real catalog item allowed in an AI-assisted user-requested choice."""

    entity_type: ResolutionEntityType
    canonical_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=512)


class AssistantClarificationRequest(ContractModel):
    user_message: str = Field(min_length=1, max_length=2_000)
    intent: ConversationIntent
    missing_slots: tuple[ConversationSlot, ...] = Field(min_length=1, max_length=8)
    available_options: tuple[str, ...] = Field(default=(), max_length=20)
    current_question: str = Field(min_length=1, max_length=512)
    resolved_entities: tuple[str, ...] = Field(default=(), max_length=16)
    unresolved_entities: tuple[str, ...] = Field(default=(), max_length=16)


class ConversationAssistantAIPort(Protocol):
    """Bounded language operations; no canonical writes or domain calculations."""

    def interpret(
        self,
        text: str,
        *,
        current_intent: ConversationIntent | None,
        missing_slots: tuple[ConversationSlot, ...],
        known_entities: tuple[str, ...],
        allowed_metrics: tuple[str, ...],
        rate_limit_key: str,
    ) -> AssistantQueryInterpretation: ...

    def clarify(
        self,
        request: AssistantClarificationRequest,
        *,
        rate_limit_key: str,
    ) -> str: ...

    def select_catalog_candidate(
        self,
        user_message: str,
        *,
        candidates: tuple[AssistantEntityCandidate, ...],
        rate_limit_key: str,
    ) -> str | None: ...


__all__ = [
    "AssistantClarificationRequest",
    "AssistantEntityCandidate",
    "AssistantEntityMention",
    "AssistantQueryInterpretation",
    "ConversationAssistantAIPort",
]
