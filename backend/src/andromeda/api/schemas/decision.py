"""Strict HTTP schemas for the decision context and shortlist API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, TypeVar

from pydantic import BeforeValidator, Field, model_validator

from andromeda.modules.admission_fit.contracts.public import (
    ApplicantAdmissionProfile,
    ApplicantSubjectScore,
)
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.decision.contracts.public import (
    AdmissionConstraints,
    AnalyticsToken,
    DecisionAnalyticsAction,
    DecisionAnalyticsClientEvent,
    DecisionAnalyticsClientEventType,
    DecisionAnalyticsEventId,
    DecisionAnalyticsEventType,
    DecisionAnalyticsPayload,
    DecisionAnalyticsSource,
    DecisionAnalyticsStatus,
    DecisionConstraintsUpdate,
    DecisionContext,
    DecisionContextResult,
    DecisionConstraintOutcome,
    DecisionMutationResult,
    DecisionRefinementAnswer,
    DecisionRefinementResult,
    DecisionShortlistItem,
    DecisionSuggestion,
    DecisionSuggestionsResult,
    ProgramCommand,
    ShortlistCommand,
    ShortlistRole,
    ShortlistEntry,
)
from andromeda.shared.contracts.ids import EducationYear, ProgramId

from .admission_fit import AdmissionFitResponse, admission_fit_response
from .common import ApiModel, SourceAttributionResponse, SourceGapReferenceResponse
from .proftest import MatchScoreResponse, RecommendationEvidenceResponse, UserProfileResponse, profile_response, recommendation_evidence_response


def _decimal_from_json(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return value
    return value


JsonScore = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_json),
    Field(strict=True, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2),
]
JsonTuition = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_json),
    Field(strict=True, ge=Decimal("0"), max_digits=12, decimal_places=2),
]


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    """Convert JSON enum values before the strict API model validates them."""

    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


def _funding_type_from_json(value: object) -> FundingType:
    return _enum_from_json(FundingType, value)


def _study_form_from_json(value: object) -> StudyForm:
    return _enum_from_json(StudyForm, value)


def _shortlist_role_from_json(value: object) -> ShortlistRole:
    return _enum_from_json(ShortlistRole, value)


def _analytics_source_from_json(value: object) -> DecisionAnalyticsSource:
    return _enum_from_json(DecisionAnalyticsSource, value)


def _analytics_action_from_json(value: object) -> DecisionAnalyticsAction:
    return _enum_from_json(DecisionAnalyticsAction, value)


def _analytics_status_from_json(value: object) -> DecisionAnalyticsStatus:
    return _enum_from_json(DecisionAnalyticsStatus, value)


def _analytics_client_event_type_from_json(value: object) -> DecisionAnalyticsClientEventType:
    return _enum_from_json(DecisionAnalyticsClientEventType, value)


JsonFundingType = Annotated[FundingType, BeforeValidator(_funding_type_from_json)]
JsonStudyForm = Annotated[StudyForm, BeforeValidator(_study_form_from_json)]
JsonShortlistRole = Annotated[ShortlistRole, BeforeValidator(_shortlist_role_from_json)]
JsonAnalyticsSource = Annotated[DecisionAnalyticsSource, BeforeValidator(_analytics_source_from_json)]
JsonAnalyticsAction = Annotated[DecisionAnalyticsAction, BeforeValidator(_analytics_action_from_json)]
JsonAnalyticsStatus = Annotated[DecisionAnalyticsStatus, BeforeValidator(_analytics_status_from_json)]
JsonAnalyticsClientEventType = Annotated[
    DecisionAnalyticsClientEventType,
    BeforeValidator(_analytics_client_event_type_from_json),
]


class DecisionApplicantScoreRequest(ApiModel):
    subject: str = Field(min_length=1, max_length=512)
    score: JsonScore


class DecisionApplicantRequest(ApiModel):
    version: Literal[1] = 1
    scores: list[DecisionApplicantScoreRequest] = Field(default_factory=list, max_length=64)

    def to_contract(self) -> ApplicantAdmissionProfile:
        return ApplicantAdmissionProfile(
            version=self.version,
            scores=tuple(ApplicantSubjectScore(subject=item.subject, score=item.score) for item in self.scores),
        )


class DecisionConstraintsRequest(ApiModel):
    version: Literal[1] = 1
    applicant: DecisionApplicantRequest | None = None
    admission_year: EducationYear | None = None
    funding_preference: JsonFundingType | None = None
    study_form: JsonStudyForm | None = None
    max_tuition: JsonTuition | None = None
    location: str | None = Field(default=None, min_length=1, max_length=256)

    def to_contract(self) -> AdmissionConstraints:
        return AdmissionConstraints(
            version=self.version,
            applicant=self.applicant.to_contract() if self.applicant is not None else None,
            admission_year=self.admission_year,
            funding_preference=self.funding_preference,
            study_form=self.study_form,
            max_tuition=self.max_tuition,
            location=self.location,
        )


class DecisionConstraintsUpdateRequest(ApiModel):
    version: Literal[1] = 1
    constraints: DecisionConstraintsRequest | None
    expected_revision: int | None = Field(default=None, alias="expectedRevision", strict=True, ge=1)

    def to_contract(self) -> DecisionConstraintsUpdate:
        return DecisionConstraintsUpdate(
            version=self.version,
            constraints=self.constraints.to_contract() if self.constraints is not None else None,
            expected_revision=self.expected_revision,
        )


class DecisionProgramCommandRequest(ApiModel):
    version: Literal[1] = 1
    program_id: ProgramId
    expected_revision: int | None = Field(default=None, alias="expectedRevision", strict=True, ge=1)

    def to_contract(self) -> ProgramCommand:
        return ProgramCommand(version=self.version, program_id=self.program_id, expected_revision=self.expected_revision)


class DecisionShortlistCommandRequest(DecisionProgramCommandRequest):
    role: JsonShortlistRole = ShortlistRole.PRIMARY

    def to_contract(self) -> ShortlistCommand:
        return ShortlistCommand(
            version=self.version,
            program_id=self.program_id,
            expected_revision=self.expected_revision,
            role=self.role,
        )


class DecisionShortlistRoleRequest(ApiModel):
    version: Literal[1] = 1
    role: JsonShortlistRole
    expected_revision: int | None = Field(default=None, alias="expectedRevision", strict=True, ge=1)


class DecisionRevisionRequest(ApiModel):
    expected_revision: int | None = Field(default=None, alias="expectedRevision", strict=True, ge=1)


class DecisionRefinementAnswerRequest(ApiModel):
    version: Literal[1] = 1
    question_id: str = Field(min_length=1, max_length=128)
    option_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=1)

    def to_contract(self) -> DecisionRefinementAnswer:
        return DecisionRefinementAnswer(
            version=self.version,
            question_id=self.question_id,
            option_id=self.option_id,
            expected_revision=self.expected_revision,
        )


class DecisionAnalyticsPayloadRequest(ApiModel):
    """Camel-case HTTP adapter for the bounded analytics payload."""

    source: JsonAnalyticsSource | None = None
    action: JsonAnalyticsAction | None = None
    status: JsonAnalyticsStatus | None = None
    program_id: ProgramId | None = None
    program_ids: list[ProgramId] = Field(default_factory=list, max_length=3)
    role: JsonShortlistRole | None = None
    count: int | None = Field(default=None, strict=True, ge=0, le=50)
    question_id: AnalyticsToken | None = None
    option_id: AnalyticsToken | None = None

    def to_contract(self) -> DecisionAnalyticsPayload:
        return DecisionAnalyticsPayload(
            source=self.source,
            action=self.action,
            status=self.status,
            program_id=self.program_id,
            program_ids=tuple(self.program_ids),
            role=self.role,
            count=self.count,
            question_id=self.question_id,
            option_id=self.option_id,
        )


class DecisionAnalyticsEventRequest(ApiModel):
    event_id: DecisionAnalyticsEventId
    event_type: JsonAnalyticsClientEventType
    payload: DecisionAnalyticsPayloadRequest = Field(default_factory=DecisionAnalyticsPayloadRequest)

    @model_validator(mode="after")
    def validate_contract_shape(self) -> "DecisionAnalyticsEventRequest":
        # Run the domain contract at the HTTP validation boundary so malformed
        # event shapes become 422 responses and never reach persistence.
        DecisionAnalyticsClientEvent(
            event_id=self.event_id,
            event_type=DecisionAnalyticsEventType(self.event_type.value),
            payload=self.payload.to_contract(),
        )
        return self

    def to_contract(self) -> DecisionAnalyticsClientEvent:
        return DecisionAnalyticsClientEvent(
            event_id=self.event_id,
            event_type=DecisionAnalyticsEventType(self.event_type.value),
            payload=self.payload.to_contract(),
        )


class DecisionAnalyticsAcceptedResponse(ApiModel):
    accepted: int = Field(strict=True, ge=0, le=1)


class DecisionApplicantResponse(ApiModel):
    version: Literal[1]
    scores: tuple[DecisionApplicantScoreRequest, ...]


class DecisionConstraintsResponse(ApiModel):
    version: Literal[1]
    applicant: DecisionApplicantResponse | None = None
    admission_year: int | None = None
    funding_preference: FundingType | None = None
    study_form: StudyForm | None = None
    max_tuition: Decimal | None = None
    location: str | None = None


class DecisionShortlistEntryResponse(ApiModel):
    program_id: ProgramId
    role: str
    state: str
    origin: str
    revision: int
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None


class DecisionChoiceResponse(ApiModel):
    considered_program_ids: tuple[ProgramId, ...]
    shortlist_entries: tuple[DecisionShortlistEntryResponse, ...]
    excluded_program_ids: tuple[ProgramId, ...]


class DecisionStateResponse(ApiModel):
    version: Literal[1]
    admission_constraints: DecisionConstraintsResponse | None = None
    choice: DecisionChoiceResponse
    selected_program_id: ProgramId | None = None
    selected_at: datetime | None = None
    explicit_priorities: tuple[str, ...]
    revision: int
    created_at: datetime
    updated_at: datetime


class DecisionMetadataResponse(ApiModel):
    decision_id: str
    revision: int
    status: str
    created_at: datetime
    updated_at: datetime
    profile_revision: int | None = None


class DecisionContextResponse(ApiModel):
    decision_id: str
    state: DecisionStateResponse
    preferences: UserProfileResponse | None = None
    profile_revision: int | None = None
    missing_data: tuple[str, ...]
    metadata: DecisionMetadataResponse


class DecisionContextEnvelopeResponse(ApiModel):
    decision_id: str
    context: DecisionContextResponse


class DecisionMutationResponse(ApiModel):
    decision_id: str
    context: DecisionContextResponse
    changed: bool


class DecisionSuggestionReasonsResponse(ApiModel):
    why_included: tuple[str, ...]
    why_may_not_fit: tuple[str, ...]
    admission_risk: tuple[str, ...]
    content_differences: tuple[str, ...]
    missing_data: tuple[str, ...]


class DecisionConstraintOutcomeResponse(ApiModel):
    dimension: str
    applicability: str
    satisfied: bool | None = None
    message: str
    source_gaps: tuple[str, ...]


class DecisionSuggestionResponse(ApiModel):
    program_id: ProgramId
    program_code: str
    program_name: str
    partition: str
    admission_status: str | None = None
    admission_risk: str
    admission_fit: AdmissionFitResponse | None = None
    content_fit: MatchScoreResponse | None = None
    evidence: RecommendationEvidenceResponse | None = None
    constraint_outcomes: tuple[DecisionConstraintOutcomeResponse, ...]
    reasons: DecisionSuggestionReasonsResponse
    source_gaps: tuple[str, ...]
    source_hashes: tuple[str, ...]
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gap_details: tuple[SourceGapReferenceResponse, ...] = ()


class DecisionShortlistItemResponse(ApiModel):
    program_id: ProgramId
    program_code: str | None = None
    program_name: str | None = None
    partition: str
    admission_status: str | None = None
    admission_risk: str
    admission_fit: AdmissionFitResponse | None = None
    content_fit: MatchScoreResponse | None = None
    evidence: RecommendationEvidenceResponse | None = None
    constraint_outcomes: tuple[DecisionConstraintOutcomeResponse, ...]
    reasons: DecisionSuggestionReasonsResponse
    source_gaps: tuple[str, ...]
    source_hashes: tuple[str, ...]
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gap_details: tuple[SourceGapReferenceResponse, ...] = ()
    role: str
    state: str


class DecisionRefinementOptionResponse(ApiModel):
    id: str
    label: str
    affected_dimension: str
    effect: str


class DecisionRefinementQuestionResponse(ApiModel):
    id: str
    prompt: str
    candidate_program_ids: tuple[ProgramId, ...]
    options: tuple[DecisionRefinementOptionResponse, ...]
    discriminating_dimensions: tuple[str, ...]


class DecisionSuggestionsResponse(ApiModel):
    decision_id: str
    context_revision: int
    data_completeness: str
    active_shortlist: tuple[DecisionShortlistItemResponse, ...]
    primary_candidates: tuple[DecisionSuggestionResponse, ...]
    alternative_candidates: tuple[DecisionSuggestionResponse, ...]
    ineligible_candidates: tuple[DecisionSuggestionResponse, ...]
    insufficient_data_candidates: tuple[DecisionSuggestionResponse, ...]
    suggestions: tuple[DecisionSuggestionResponse, ...]
    refinement_question: DecisionRefinementQuestionResponse | None = None
    source_gaps: tuple[str, ...]
    missing_data: tuple[str, ...]


class DecisionRefinementResponse(ApiModel):
    suggestions: DecisionSuggestionsResponse
    profile_revision: int


def decision_context_response(value: DecisionContext) -> DecisionContextResponse:
    state = value.state
    return DecisionContextResponse(
        decision_id=value.decision_id,
        state=DecisionStateResponse(
            version=state.version,
            admission_constraints=_constraints_response(state.admission_constraints),
            choice=DecisionChoiceResponse(
                considered_program_ids=state.choice.considered_program_ids,
                shortlist_entries=tuple(_shortlist_entry_response(item) for item in state.choice.shortlist_entries),
                excluded_program_ids=state.choice.excluded_program_ids,
            ),
            selected_program_id=state.selected_program_id,
            selected_at=state.selected_at,
            explicit_priorities=state.explicit_priorities,
            revision=state.revision,
            created_at=state.created_at,
            updated_at=state.updated_at,
        ),
        preferences=profile_response(value.preferences) if value.preferences is not None else None,
        profile_revision=value.profile_revision,
        missing_data=value.missing_data,
        metadata=DecisionMetadataResponse.model_validate(value.metadata.model_dump()),
    )


def decision_context_envelope_response(value: DecisionContextResult) -> DecisionContextEnvelopeResponse:
    context = value.context
    return DecisionContextEnvelopeResponse(decision_id=value.decision_id, context=decision_context_response(context))


def decision_mutation_response(value: DecisionMutationResult) -> DecisionMutationResponse:
    return DecisionMutationResponse(
        decision_id=value.decision_id,
        context=decision_context_response(value.context),
        changed=value.changed,
    )


def decision_suggestions_response(value: DecisionSuggestionsResult) -> DecisionSuggestionsResponse:
    return DecisionSuggestionsResponse(
        decision_id=value.decision_id,
        context_revision=value.context_revision,
        data_completeness=value.data_completeness.value,
        active_shortlist=tuple(_shortlist_item_response(item) for item in value.active_shortlist),
        primary_candidates=tuple(_suggestion_response(item) for item in value.primary_candidates),
        alternative_candidates=tuple(_suggestion_response(item) for item in value.alternative_candidates),
        ineligible_candidates=tuple(_suggestion_response(item) for item in value.ineligible_candidates),
        insufficient_data_candidates=tuple(_suggestion_response(item) for item in value.insufficient_data_candidates),
        suggestions=tuple(_suggestion_response(item) for item in value.suggestions),
        refinement_question=(
            DecisionRefinementQuestionResponse.model_validate(value.refinement_question.model_dump())
            if value.refinement_question is not None
            else None
        ),
        source_gaps=value.source_gaps,
        missing_data=value.missing_data,
    )


def decision_refinement_response(value: DecisionRefinementResult) -> DecisionRefinementResponse:
    return DecisionRefinementResponse(
        suggestions=decision_suggestions_response(value.suggestions),
        profile_revision=value.profile_revision,
    )


def _constraints_response(value: AdmissionConstraints | None) -> DecisionConstraintsResponse | None:
    if value is None:
        return None
    applicant = None
    if value.applicant is not None:
        applicant = DecisionApplicantResponse(
            version=value.applicant.version,
            scores=tuple(
                DecisionApplicantScoreRequest(subject=item.subject, score=item.score)
                for item in value.applicant.scores
            ),
        )
    return DecisionConstraintsResponse(
        version=value.version,
        applicant=applicant,
        admission_year=value.admission_year,
        funding_preference=value.funding_preference,
        study_form=value.study_form,
        max_tuition=value.max_tuition,
        location=value.location,
    )


def _shortlist_entry_response(value: ShortlistEntry) -> DecisionShortlistEntryResponse:
    return DecisionShortlistEntryResponse.model_validate(value.model_dump())


def _suggestion_response(value: DecisionSuggestion) -> DecisionSuggestionResponse:
    return DecisionSuggestionResponse(
        program_id=value.program_id,
        program_code=value.program_code,
        program_name=value.program_name,
        partition=value.partition.value,
        admission_status=value.admission_status.value if value.admission_status is not None else None,
        admission_risk=value.admission_risk.value,
        admission_fit=admission_fit_response(value.admission_fit) if value.admission_fit is not None else None,
        content_fit=MatchScoreResponse.model_validate(value.content_fit.model_dump()) if value.content_fit is not None else None,
        evidence=recommendation_evidence_response(value.evidence) if value.evidence is not None else None,
        constraint_outcomes=tuple(_constraint_outcome_response(item) for item in value.constraint_outcomes),
        reasons=DecisionSuggestionReasonsResponse.model_validate(value.reasons.model_dump()),
        source_gaps=value.source_gaps,
        source_hashes=value.source_hashes,
        provenance=tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in value.provenance),
        source_gap_details=tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in value.source_gap_details),
    )


def _shortlist_item_response(value: DecisionShortlistItem) -> DecisionShortlistItemResponse:
    return DecisionShortlistItemResponse(
        program_id=value.program_id,
        program_code=value.program_code,
        program_name=value.program_name,
        partition="shortlist",
        admission_status=value.admission_status.value if value.admission_status is not None else None,
        admission_risk=value.admission_risk.value,
        admission_fit=admission_fit_response(value.admission_fit) if value.admission_fit is not None else None,
        content_fit=MatchScoreResponse.model_validate(value.content_fit.model_dump()) if value.content_fit is not None else None,
        evidence=recommendation_evidence_response(value.evidence) if value.evidence is not None else None,
        constraint_outcomes=tuple(_constraint_outcome_response(item) for item in value.constraint_outcomes),
        reasons=DecisionSuggestionReasonsResponse.model_validate(value.reasons.model_dump()),
        source_gaps=value.source_gaps,
        source_hashes=value.source_hashes,
        provenance=tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in value.provenance),
        source_gap_details=tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in value.source_gap_details),
        role=value.role.value,
        state=value.state.value,
    )


def _constraint_outcome_response(value: DecisionConstraintOutcome) -> DecisionConstraintOutcomeResponse:
    return DecisionConstraintOutcomeResponse(
        dimension=value.dimension.value,
        applicability=value.applicability.value,
        satisfied=value.satisfied,
        message=value.message,
        source_gaps=value.source_gaps,
    )


__all__ = [
    "DecisionConstraintsRequest",
    "DecisionConstraintsUpdateRequest",
    "DecisionAnalyticsAcceptedResponse",
    "DecisionAnalyticsEventRequest",
    "DecisionAnalyticsPayloadRequest",
    "DecisionContextEnvelopeResponse",
    "DecisionContextResponse",
    "DecisionMutationResponse",
    "DecisionProgramCommandRequest",
    "DecisionRevisionRequest",
    "DecisionShortlistCommandRequest",
    "DecisionShortlistRoleRequest",
    "DecisionSuggestionsResponse",
    "decision_context_envelope_response",
    "decision_context_response",
    "decision_mutation_response",
    "decision_suggestions_response",
]
