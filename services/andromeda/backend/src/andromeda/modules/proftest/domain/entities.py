"""Pure proftest entities and typed value objects."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.program_analytics.contracts.fingerprint import ActivityCode, CurriculumEvidence, DistinctiveSubject, ProgramFingerprint
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import NonEmptyText, ShortText

from .values import ONE, ZERO


class QuestionBlock(StrEnum):
    CONTEXT = "context"
    INTERESTS = "interests"
    ACTIVITIES = "activities"
    ANTI_INTERESTS = "anti_interests"
    TRADE_OFFS = "trade_offs"
    ADAPTIVE = "adaptive"


class QuestionStage(StrEnum):
    ABOUT = "about"
    INTERESTS = "interests"
    WORK_STYLE = "work_style"
    ANTI_INTERESTS = "anti_interests"
    TRADE_OFFS = "trade_offs"
    CLARIFICATION = "clarification"


class QuestionComponentType(StrEnum):
    CHIP_SELECT = "ChipSelect"
    SINGLE_CHOICE = "SingleChoiceCard"
    MULTI_CHOICE = "MultiChoiceCard"
    ANCHORED_SCALE = "AnchoredScale"
    PAIR_CHOICE = "PairChoice"
    SCENARIO_CHOICE = "ScenarioChoice"
    RANK_TOP = "RankTop"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"


class QuestionOption(ContractModel):
    id: ShortText
    label: NonEmptyText
    subject_weights: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    activity_weights: dict[ActivityCode, Decimal] = Field(default_factory=dict)
    anti_interest_weights: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    context_tags: tuple[ShortText, ...] = Field(default=(), max_length=8)
    filter_tags: tuple[ShortText, ...] = Field(default=(), max_length=8)
    format_tags: tuple[ShortText, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_weights(self) -> Self:
        for name, weights in (
            ("subject_weights", self.subject_weights),
            ("activity_weights", self.activity_weights),
            ("anti_interest_weights", self.anti_interest_weights),
        ):
            if any(weight < ZERO or weight > ONE for weight in weights.values()):
                raise ValueError(f"{name} values must be between zero and one")
        for name, values in (
            ("context_tags", self.context_tags),
            ("filter_tags", self.filter_tags),
            ("format_tags", self.format_tags),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
        return self


class Question(ContractModel):
    id: ShortText
    block: QuestionBlock
    prompt: NonEmptyText
    options: tuple[QuestionOption, ...] = Field(min_length=2, max_length=12)
    stage: QuestionStage | None = None
    component_type: QuestionComponentType = QuestionComponentType.SINGLE_CHOICE
    order: int = Field(default=0, strict=True, ge=0, le=1000)
    helper_text: ShortText | None = None
    declared_dimensions: tuple[ShortText, ...] = Field(default=(), max_length=12)
    branch_key: ShortText | None = None
    required: bool = True
    adaptive: bool = False
    allow_uncertain: bool = False
    allow_skip: bool = False
    multi_select: bool = False
    max_selected: int = Field(default=1, strict=True, ge=1, le=6)

    @model_validator(mode="after")
    def validate_options(self) -> Self:
        option_ids = tuple(option.id for option in self.options)
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("question options must have unique ids")
        if self.adaptive and self.block is not QuestionBlock.ADAPTIVE:
            raise ValueError("adaptive questions must use the adaptive block")
        if not self.multi_select and self.max_selected != 1:
            raise ValueError("single-select questions must allow one option")
        if len(self.declared_dimensions) != len(set(self.declared_dimensions)):
            raise ValueError("question dimensions must have unique ids")
        if self.component_type is QuestionComponentType.MULTI_CHOICE and not self.multi_select:
            raise ValueError("multi-choice components must allow multiple options")
        if self.required and self.allow_skip:
            raise ValueError("required questions cannot allow skip")
        return self


class Answer(ContractModel):
    question_id: ShortText
    option_ids: tuple[ShortText, ...] = Field(default=(), max_length=6)
    intensity: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=ONE, max_digits=5, decimal_places=4)
    status: AnswerStatus = AnswerStatus.ANSWERED

    @model_validator(mode="after")
    def validate_option_ids(self) -> Self:
        if len(self.option_ids) != len(set(self.option_ids)):
            raise ValueError("answer option ids must be unique")
        if not self.option_ids and self.status is AnswerStatus.ANSWERED:
            raise ValueError("answered answers must contain at least one option")
        if self.status is AnswerStatus.SKIPPED and self.option_ids:
            raise ValueError("skipped answers cannot contain options")
        return self


class AdaptiveAnswer(ContractModel):
    question_id: ShortText
    option_id: ShortText
    dimension: ShortText


class AnswerSet(ContractModel):
    answers: tuple[Answer, ...] = ()
    adaptive_answers: tuple[AdaptiveAnswer, ...] = ()

    @model_validator(mode="after")
    def validate_questions(self) -> Self:
        question_ids = tuple(answer.question_id for answer in self.answers)
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("answer set cannot contain duplicate questions")
        adaptive_ids = tuple(answer.question_id for answer in self.adaptive_answers)
        if len(adaptive_ids) != len(set(adaptive_ids)):
            raise ValueError("answer set cannot contain duplicate adaptive questions")
        return self


class AntiInterest(ContractModel):
    area: DisciplineAreaCode
    intensity: Decimal = Field(strict=True, ge=ZERO, le=ONE, max_digits=5, decimal_places=4)


class Confidence(ContractModel):
    value: Decimal = Field(strict=True, ge=ZERO, le=ONE, max_digits=5, decimal_places=4)
    answered_base: int = Field(strict=True, ge=0)
    answered_adaptive: int = Field(strict=True, ge=0)


class UserProfile(ContractModel):
    """Stable public representation of a user's educational-content preferences."""

    version: Literal[1] = 1
    interests: tuple[DisciplineAreaCode, ...] = ()
    activity_preferences: tuple[ActivityCode, ...] = ()
    anti_interests: tuple[AntiInterest, ...] = ()
    preferred_subject_weights: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    preferred_activity_weights: dict[ActivityCode, Decimal] = Field(default_factory=dict)
    negative_weights: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    confidence: Confidence = Confidence(value=ZERO, answered_base=0, answered_adaptive=0)
    adaptive_answers: tuple[AdaptiveAnswer, ...] = ()
    decision_context: tuple[ShortText, ...] = Field(default=(), max_length=12)
    hard_filters: tuple[ShortText, ...] = Field(default=(), max_length=12)
    format_preferences: tuple[ShortText, ...] = Field(default=(), max_length=12)
    load_tolerance: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=ONE, max_digits=5, decimal_places=4)
    confidence_by_dimension: dict[ShortText, Decimal] = Field(default_factory=dict)
    consistency_flags: tuple[ShortText, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_distributions(self) -> Self:
        for name, weights in (
            ("preferred_subject_weights", self.preferred_subject_weights),
            ("preferred_activity_weights", self.preferred_activity_weights),
            ("negative_weights", self.negative_weights),
        ):
            if any(weight < ZERO or weight > ONE for weight in weights.values()):
                raise ValueError(f"{name} values must be between zero and one")
        for name, weights in (
            ("preferred_subject_weights", self.preferred_subject_weights),
            ("preferred_activity_weights", self.preferred_activity_weights),
        ):
            if weights and abs(sum(weights.values(), ZERO) - ONE) > Decimal("0.001"):
                raise ValueError(f"{name} must sum to one")
        areas = tuple(item.area for item in self.anti_interests)
        if len(areas) != len(set(areas)):
            raise ValueError("anti_interests must contain unique areas")
        if any(value < ZERO or value > ONE for value in self.confidence_by_dimension.values()):
            raise ValueError("confidence_by_dimension values must be between zero and one")
        for name, values in (
            ("decision_context", self.decision_context),
            ("hard_filters", self.hard_filters),
            ("format_preferences", self.format_preferences),
            ("consistency_flags", self.consistency_flags),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
        return self


__all__ = [
    "ActivityCode",
    "AnswerStatus",
    "AdaptiveAnswer",
    "Answer",
    "AnswerSet",
    "AntiInterest",
    "Confidence",
    "CurriculumEvidence",
    "DistinctiveSubject",
    "ONE",
    "ProgramFingerprint",
    "Question",
    "QuestionBlock",
    "QuestionComponentType",
    "QuestionOption",
    "QuestionStage",
    "UserProfile",
    "ZERO",
]
