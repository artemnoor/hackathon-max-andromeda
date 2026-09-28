"""Bounded state for arbitrary educational questions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    ApplicantAdmissionContext,
)
from andromeda.modules.admission_fit.contracts.public import (
    ApplicantAdmissionProfile,
    BatchAdmissionFitRequest,
)
from andromeda.modules.admissions.contracts.admission_cycles import AdmissionCycleId
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.analytics.contracts.metrics import MetricAggregation
from andromeda.modules.analytics.contracts.query import (
    QueryFilter,
    QueryScope,
    QuerySort,
    QuerySpec,
)
from andromeda.modules.entity_resolution.contracts.public import ResolutionEntityType
from andromeda.modules.knowledge.contracts.public import (
    ClaimChangeEventId,
    ClaimPredicate,
    SourceId,
)
from andromeda.modules.policy.contracts.public import (
    PolicyImpactId,
    PolicyResolutionTraceId,
    PolicyRuleId,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EducationYear, Semester, UniversityId

CONVERSATION_PARSER_VERSION = "conversation-parser.v4"
from andromeda.shared.contracts.versions import DECISION_POLICY_VERSION

QuerySessionId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^query-session:[0-9a-f]{32}$")
]


class ConversationIntent(StrEnum):
    UNKNOWN = "unknown"
    ANALYTICS_QUERY = "analytics_query"
    COMPARE_PROGRAMS = "compare_programs"
    ADMISSION_SEARCH = "admission_search"
    KNOWLEDGE_POLICY_QUERY = "knowledge_policy_query"


class AdmissionUniversityScope(StrEnum):
    """Explicit applicant choice for searching the whole university catalog."""

    ANY_UNIVERSITY = "any_university"


class ConversationSlot(StrEnum):
    METRIC = "metric"
    ENTITY = "entity"
    EXAMS = "exams"
    TOTAL_SCORE = "total_score"
    UNIVERSITY_SCOPE = "university_scope"
    FUNDING = "funding"
    STUDY_FORM = "study_form"
    ADMISSION_YEAR = "admission_year"


class NextAction(StrEnum):
    NONE = "none"
    ASK_FOR_METRIC = "ask_for_metric"
    ASK_FOR_ENTITY = "ask_for_entity"
    ASK_FOR_EXAMS = "ask_for_exams"
    ASK_FOR_UNIVERSITY_SCOPE = "ask_for_university_scope"
    ASK_FOR_FUNDING = "ask_for_funding"
    ASK_FOR_STUDY_FORM = "ask_for_study_form"
    ASK_FOR_ADMISSION_YEAR = "ask_for_admission_year"
    EXECUTE_QUERY = "execute_query"
    CLARIFY = "clarify"


class FactOrigin(StrEnum):
    EXPLICIT_USER = "explicit_user"
    DETERMINISTIC_INFERENCE = "deterministic_inference"
    PROFILE_PROJECTION = "profile_projection"
    POLICY_DEFAULT = "policy_default"
    EXTERNAL_MODEL_CANDIDATE = "external_model_candidate"


class PolicyQueryFocus(StrEnum):
    STATUS = "status"
    CHANGE = "change"
    APPLICABILITY = "applicability"
    IMPACT = "impact"
    HISTORY = "history"
    WHAT_IF = "what_if"


class PolicyQueryYear(ContractModel):
    """Explicit year mentioned as a policy effective-time claim, not applicant cycle."""

    year: EducationYear
    origin: FactOrigin = FactOrigin.EXPLICIT_USER
    confirmed: bool = True
    source: str = Field(default="conversation", min_length=1, max_length=64)


class PolicyQueryContext(ContractModel):
    """Bounded policy references and temporal mode carried across query turns.

    Applicant year/university/program/direction/route remain in QuerySession's
    existing typed slots, resolved entities and cycle trace to avoid competing
    copies of the same user state.
    """

    schema_version: Literal["policy-query-context.v1"] = "policy-query-context.v1"
    focus: PolicyQueryFocus
    claim_predicate: ClaimPredicate | None = None
    mentioned_effective_year: PolicyQueryYear | None = None
    comparison_admission_years: tuple[EducationYear, ...] = Field(
        default=(), max_length=2
    )
    valid_as_of: datetime | None = None
    as_known_at: datetime | None = None
    source_id: SourceId | None = None
    change_event_id: ClaimChangeEventId | None = None
    policy_rule_id: PolicyRuleId | None = None
    admission_cycle_id: AdmissionCycleId | None = None
    resolution_trace_id: PolicyResolutionTraceId | None = None
    impact_preview_id: PolicyImpactId | None = None
    what_if_rule_id: PolicyRuleId | None = None

    @field_validator("valid_as_of", "as_known_at")
    @classmethod
    def policy_query_times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("policy query timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def comparison_years_are_chronological(self) -> PolicyQueryContext:
        if self.comparison_admission_years and (
            len(self.comparison_admission_years) != 2
            or self.comparison_admission_years[0] >= self.comparison_admission_years[1]
        ):
            raise ValueError("policy comparison requires two ascending admission years")
        return self


class QueryFact(ContractModel):
    value: object
    origin: FactOrigin
    confirmed: bool = False
    source: str = Field(default="conversation", min_length=1, max_length=64)


class QueryFrame(ContractModel):
    """The current typed question, separate from explicit decision state."""

    intent: ConversationIntent = ConversationIntent.UNKNOWN
    admission_university_scope: AdmissionUniversityScope | None = None
    entities: dict[ResolutionEntityType, tuple[str, ...]] = Field(
        default_factory=dict, max_length=8
    )
    metrics: tuple[str, ...] = Field(default=(), max_length=8)
    scope: QueryScope = QueryScope.ALL
    scope_ids: tuple[str, ...] = Field(default=(), max_length=100)
    filters: tuple[QueryFilter, ...] = Field(default=(), max_length=16)
    aggregation: MetricAggregation = MetricAggregation.VALUE
    group_by: tuple[str, ...] = Field(default=(), max_length=4)
    ordering: QuerySort | None = None
    personalization: dict[str, object] = Field(default_factory=dict, max_length=16)
    presentation_intent: str | None = Field(default=None, max_length=64)
    semester: Semester | None = None
    course_year: int | None = Field(default=None, strict=True, ge=1, le=12)
    missing_fields: tuple[ConversationSlot, ...] = Field(default=(), max_length=8)
    resolution_evidence: dict[str, str] = Field(default_factory=dict, max_length=32)


class ExamScore(ContractModel):
    subject: str = Field(min_length=1, max_length=128)
    score: Decimal = Field(strict=True, ge=Decimal(0), le=Decimal(100))


class ParsedQuery(ContractModel):
    """Typed partial parser output; unresolved text is intentionally retained."""

    intent: ConversationIntent = ConversationIntent.UNKNOWN
    admission_university_scope: AdmissionUniversityScope | None = None
    metric_codes: tuple[str, ...] = Field(default=(), max_length=8)
    entity_queries: tuple[str, ...] = Field(default=(), max_length=20)
    university_queries: tuple[str, ...] = Field(default=(), max_length=20)
    direction_queries: tuple[str, ...] = Field(default=(), max_length=20)
    program_queries: tuple[str, ...] = Field(default=(), max_length=20)
    total_score: Decimal | None = Field(
        default=None, strict=True, ge=Decimal(0), le=Decimal(400)
    )
    exam_scores: tuple[ExamScore, ...] = Field(default=(), max_length=16)
    funding_type: FundingType | None = None
    study_form: StudyForm | None = None
    study_form_ambiguous: bool = False
    admission_year: EducationYear | None = None
    policy_query_context: PolicyQueryContext | None = None
    scope: QueryScope | None = None
    aggregation: MetricAggregation | None = None
    semester: Semester | None = None
    course_year: int | None = Field(default=None, strict=True, ge=1, le=12)
    unresolved_text: str = Field(default="", max_length=1000)


class QuerySession(ContractModel):
    session_id: QuerySessionId
    owner_scope: ProfileScope
    intent: ConversationIntent = ConversationIntent.UNKNOWN
    admission_university_scope: AdmissionUniversityScope | None = None
    frame: QueryFrame = Field(default_factory=QueryFrame)
    entities: dict[ResolutionEntityType, tuple[str, ...]] = Field(
        default_factory=dict, max_length=8
    )
    metrics: tuple[str, ...] = Field(default=(), max_length=8)
    scope: QueryScope = QueryScope.ALL
    scope_ids: tuple[str, ...] = Field(default=(), max_length=100)
    filters: tuple[QueryFilter, ...] = Field(default=(), max_length=16)
    aggregation: MetricAggregation = MetricAggregation.VALUE
    known_slots: dict[str, object] = Field(default_factory=dict, max_length=32)
    confirmed_parameters: dict[str, QueryFact] = Field(
        default_factory=dict, max_length=32
    )
    inferred_parameters: dict[str, QueryFact] = Field(
        default_factory=dict, max_length=32
    )
    policy_query_context: PolicyQueryContext | None = None
    applicant_admission_context: ApplicantAdmissionContext | None = None
    resolution_cache: dict[str, str] = Field(default_factory=dict, max_length=32)
    unresolved_entities: tuple[str, ...] = Field(default=(), max_length=20)
    missing_slots: tuple[ConversationSlot, ...] = Field(default=(), max_length=8)
    assumptions: tuple[str, ...] = Field(default=(), max_length=16)
    last_query: QuerySpec | None = None
    last_result_ref: str | None = Field(default=None, max_length=256)
    next_action: NextAction = NextAction.NONE
    last_question: str | None = Field(default=None, max_length=512)
    last_action: NextAction = NextAction.NONE
    revision: int = Field(default=1, strict=True, ge=1)
    parser_version: str = CONVERSATION_PARSER_VERSION
    policy_version: str = DECISION_POLICY_VERSION
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @model_validator(mode="before")
    @classmethod
    def hydrate_known_slots(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        hydrated = dict(values)
        known_slots = values.get("known_slots")
        if isinstance(known_slots, dict):
            hydrated_slots = dict(known_slots)
            raw_scores = known_slots.get("exam_scores")
            if isinstance(raw_scores, (list, tuple)):
                hydrated_slots["exam_scores"] = tuple(
                    score
                    if isinstance(score, ExamScore)
                    else ExamScore.model_validate(score, strict=False)
                    for score in raw_scores
                )
            for key, enum_type in (
                ("funding_type", FundingType),
                ("study_form", StudyForm),
            ):
                value = hydrated_slots.get(key)
                if isinstance(value, str):
                    try:
                        hydrated_slots[key] = enum_type(value)
                    except ValueError:
                        pass
            hydrated["known_slots"] = hydrated_slots

        for field_name in ("confirmed_parameters", "inferred_parameters"):
            facts = values.get(field_name)
            if not isinstance(facts, dict):
                continue
            hydrated_facts = dict(facts)
            for key, enum_type in (
                ("funding_type", FundingType),
                ("study_form", StudyForm),
            ):
                raw_fact = facts.get(key)
                if not isinstance(raw_fact, dict):
                    continue
                fact = dict(raw_fact)
                value = fact.get("value")
                if isinstance(value, str):
                    try:
                        fact["value"] = enum_type(value)
                    except ValueError:
                        pass
                hydrated_facts[key] = fact
            hydrated[field_name] = hydrated_facts
        return hydrated

    @model_validator(mode="after")
    def validate_lifecycle(self) -> QuerySession:
        if (
            self.created_at.tzinfo is None
            or self.updated_at.tzinfo is None
            or self.expires_at.tzinfo is None
        ):
            raise ValueError("query session timestamps must be timezone-aware")
        if self.created_at > self.updated_at or self.updated_at >= self.expires_at:
            raise ValueError("query session timestamps must be ordered and unexpired")
        return self


class ConversationCompilation(ContractModel):
    next_action: NextAction
    missing_slots: tuple[ConversationSlot, ...] = Field(default=(), max_length=8)
    analytics_query: QuerySpec | None = None
    admission_request: BatchAdmissionFitRequest | None = None
    admission_requests: tuple[BatchAdmissionFitRequest, ...] = Field(
        default=(), max_length=100
    )
    applicant: ApplicantAdmissionProfile | None = None
    university_scope_ids: tuple[UniversityId, ...] = Field(default=(), max_length=20)
    policy_query_context: PolicyQueryContext | None = None


__all__ = [
    "CONVERSATION_PARSER_VERSION",
    "AdmissionUniversityScope",
    "ConversationCompilation",
    "ConversationIntent",
    "ConversationSlot",
    "ExamScore",
    "FactOrigin",
    "NextAction",
    "ParsedQuery",
    "PolicyQueryContext",
    "PolicyQueryFocus",
    "PolicyQueryYear",
    "QueryFact",
    "QueryFrame",
    "QuerySession",
    "QuerySessionId",
]
