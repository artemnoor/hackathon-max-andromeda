"""Strict HTTP schemas for the Andromeda proftest flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, AdaptiveAnswer, AdaptiveSelection, AdaptiveStatus, AnalyticsEventType, Answer, AnswerSet, AnswerStatus, AntiInterest, Confidence, EvidenceSignal, EvidenceStatus, MatchReason, MatchScore, ProftestAnalyticsEvent, ProftestPreview, ProftestResults, ProftestSessionView, Question, Questionnaire, QuestionBlock, QuestionComponentType, Recommendation, RecommendationEvidence, ReasonKind, SessionAnswer, SessionProgress, SessionStatus, UserProfile, UserProfileSnapshot

from .common import ApiModel, SourceAttributionResponse, SourceGapReferenceResponse


def _decimal_from_json(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return value
    return value


def _datetime_from_json(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


JsonDecimal = Annotated[Decimal, BeforeValidator(_decimal_from_json), Field(strict=True, ge=0, le=1, max_digits=5, decimal_places=4)]
JsonDateTime = Annotated[datetime, BeforeValidator(_datetime_from_json)]


def _discipline_area_from_json(value: object) -> DisciplineAreaCode:
    if isinstance(value, DisciplineAreaCode):
        return value
    if isinstance(value, str):
        return DisciplineAreaCode(value)
    raise TypeError("discipline area must be a string")


def _activity_code_from_json(value: object) -> ActivityCode:
    if isinstance(value, ActivityCode):
        return value
    if isinstance(value, str):
        return ActivityCode(value)
    raise TypeError("activity code must be a string")


def _analytics_event_type_from_json(value: object) -> AnalyticsEventType:
    if isinstance(value, AnalyticsEventType):
        return value
    if isinstance(value, str):
        return AnalyticsEventType(value)
    raise TypeError("analytics event type must be a string")


def _answer_status_from_json(value: object) -> AnswerStatus:
    if isinstance(value, AnswerStatus):
        return value
    if isinstance(value, str):
        return AnswerStatus(value)
    raise TypeError("answer status must be a string")


JsonDisciplineAreaCode = Annotated[DisciplineAreaCode, BeforeValidator(_discipline_area_from_json)]
JsonActivityCode = Annotated[ActivityCode, BeforeValidator(_activity_code_from_json)]
JsonAnalyticsEventType = Annotated[AnalyticsEventType, BeforeValidator(_analytics_event_type_from_json)]
JsonAnswerStatus = Annotated[AnswerStatus, BeforeValidator(_answer_status_from_json)]


class ProftestAnswerRequest(ApiModel):
    question_id: str = Field(alias="questionId", min_length=1, max_length=256)
    option_ids: list[str] = Field(alias="optionIds", default_factory=list, max_length=6)
    intensity: JsonDecimal | None = None
    status: JsonAnswerStatus = AnswerStatus.ANSWERED

    def to_contract(self) -> Answer:
        return Answer(question_id=self.question_id, option_ids=tuple(self.option_ids), intensity=self.intensity, status=self.status)


class ProftestAdaptiveAnswerRequest(ApiModel):
    question_id: str = Field(alias="questionId", min_length=1, max_length=256)
    option_id: str = Field(alias="optionId", min_length=1, max_length=256)
    dimension: str = Field(min_length=3, max_length=128)

    def to_contract(self) -> AdaptiveAnswer:
        return AdaptiveAnswer(question_id=self.question_id, option_id=self.option_id, dimension=self.dimension)


class ProftestSubmissionRequest(ApiModel):
    answers: list[ProftestAnswerRequest] = Field(default_factory=list)
    adaptive_answers: list[ProftestAdaptiveAnswerRequest] = Field(default_factory=list, alias="adaptiveAnswers")

    def to_contract(self) -> AnswerSet:
        return AnswerSet(answers=tuple(answer.to_contract() for answer in self.answers), adaptive_answers=tuple(answer.to_contract() for answer in self.adaptive_answers))


class ProftestSessionAnswerRequest(ApiModel):
    question_id: str = Field(alias="questionId", min_length=1, max_length=256)
    option_ids: list[str] = Field(alias="optionIds", default_factory=list, max_length=6)
    intensity: JsonDecimal | None = None
    status: JsonAnswerStatus = AnswerStatus.ANSWERED
    dimension: str | None = Field(default=None, min_length=3, max_length=128)

    def to_contract(self) -> SessionAnswer:
        return SessionAnswer(question_id=self.question_id, option_ids=tuple(self.option_ids), intensity=self.intensity, status=self.status, dimension=self.dimension)


class ProftestSessionPatchRequest(ApiModel):
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=1)
    answers: list[ProftestSessionAnswerRequest] = Field(min_length=1, max_length=6)


class ProftestSessionNextRequest(ProftestSessionAnswerRequest):
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=1)


class ProftestAnalyticsEventRequest(ApiModel):
    event_id: str = Field(alias="eventId", pattern=r"^proftest-event:[0-9a-f]{32}$")
    session_id: str | None = Field(default=None, alias="sessionId", pattern=r"^proftest-session:[0-9a-f]{32}$")
    question_set_version: str = Field(alias="questionSetVersion", min_length=1, max_length=128)
    event_type: JsonAnalyticsEventType = Field(alias="eventType")
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=16)
    occurred_at: JsonDateTime = Field(alias="occurredAt")

    @model_validator(mode="after")
    def validate_payload(self) -> "ProftestAnalyticsEventRequest":
        allowed_keys = {"stage", "questionId", "component", "device", "durationMs", "uncertainty", "adaptiveCount", "changed", "top3Changed", "reason"}
        if set(self.payload) - allowed_keys:
            raise ValueError("analytics payload contains unsupported fields")
        if len(json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))) > 2048:
            raise ValueError("analytics payload is too large")
        device = self.payload.get("device")
        if device is not None and device not in {"mobile", "desktop", "unknown"}:
            raise ValueError("analytics device must be coarse")
        if any(isinstance(value, str) and len(value) > 128 for value in self.payload.values()):
            raise ValueError("analytics payload text is too long")
        return self

    def to_contract(self) -> ProftestAnalyticsEvent:
        from datetime import timedelta, timezone

        occurred_at = self.occurred_at if self.occurred_at.tzinfo is not None else self.occurred_at.replace(tzinfo=timezone.utc)
        return ProftestAnalyticsEvent(event_id=self.event_id, session_id=self.session_id, question_set_version=self.question_set_version, event_type=self.event_type, payload=self.payload, occurred_at=occurred_at, expires_at=occurred_at + timedelta(days=180))


class ProftestAnalyticsBatchRequest(ApiModel):
    events: list[ProftestAnalyticsEventRequest] = Field(min_length=1, max_length=50)


class QuestionOptionResponse(ApiModel):
    id: str
    label: str


class QuestionResponse(ApiModel):
    id: str
    block: QuestionBlock
    prompt: str
    options: tuple[QuestionOptionResponse, ...]
    required: bool
    adaptive: bool
    multi_select: bool
    max_selected: int
    stage: str | None = None
    component_type: QuestionComponentType = QuestionComponentType.SINGLE_CHOICE
    order: int = 0
    helper_text: str | None = None
    declared_dimensions: tuple[str, ...] = ()
    allow_uncertain: bool = False
    allow_skip: bool = False


class QuestionnaireResponse(ApiModel):
    version: Literal[1]
    question_set_version: str = "proftest-v2"
    questions: tuple[QuestionResponse, ...]


class ConfidenceResponse(ApiModel):
    value: JsonDecimal
    answered_base: int
    answered_adaptive: int


class AntiInterestResponse(ApiModel):
    area: JsonDisciplineAreaCode
    intensity: JsonDecimal


class AdaptiveAnswerResponse(ApiModel):
    question_id: str
    option_id: str
    dimension: str


class UserProfileResponse(ApiModel):
    version: Literal[1]
    interests: list[JsonDisciplineAreaCode]
    activity_preferences: list[JsonActivityCode]
    anti_interests: list[AntiInterestResponse]
    preferred_subject_weights: dict[JsonDisciplineAreaCode, JsonDecimal]
    preferred_activity_weights: dict[JsonActivityCode, JsonDecimal]
    negative_weights: dict[JsonDisciplineAreaCode, JsonDecimal]
    confidence: ConfidenceResponse
    adaptive_answers: list[AdaptiveAnswerResponse]
    decision_context: list[str] = Field(default_factory=list)
    hard_filters: list[str] = Field(default_factory=list)
    format_preferences: list[str] = Field(default_factory=list)
    load_tolerance: JsonDecimal | None = None
    confidence_by_dimension: dict[str, JsonDecimal] = Field(default_factory=dict)
    consistency_flags: list[str] = Field(default_factory=list)


class UserProfileCreateRequest(ApiModel):
    profile: UserProfileResponse

    def to_contract(self) -> UserProfile:
        return profile_contract(self.profile)


class UserProfileUpdateRequest(ApiModel):
    profile: UserProfileResponse
    expected_revision: int = Field(alias="expectedRevision", strict=True, ge=1)

    def to_contract(self) -> UserProfile:
        return profile_contract(self.profile)


class UserProfileSnapshotResponse(ApiModel):
    profile_id: str = Field(alias="profileId", min_length=1, max_length=96)
    profile: UserProfileResponse
    revision: int = Field(strict=True, ge=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    expires_at: datetime = Field(alias="expiresAt")


class AdaptiveDimensionResponse(ApiModel):
    code: str
    label: str
    kind: str
    spread: Decimal
    significance: Decimal


class AdaptiveSelectionResponse(ApiModel):
    status: AdaptiveStatus
    reason: str | None = None
    candidate_count: int
    top_candidate_count: int
    dimensions: tuple[AdaptiveDimensionResponse, ...]
    asked_question_ids: tuple[str, ...] = ()
    uncertain_dimensions: tuple[str, ...] = ()
    adaptive_count: int = 0
    stop_reason: str | None = None


class PreviewCandidateResponse(ApiModel):
    program_id: str
    program_code: str
    content_fit: int


class ProftestPreviewResponse(ApiModel):
    profile: UserProfileResponse
    adaptive: AdaptiveSelectionResponse
    question: QuestionResponse | None = None
    candidates: tuple[PreviewCandidateResponse, ...]


class ScoreBreakdownResponse(ApiModel):
    subject_fit: Decimal
    activity_fit: Decimal
    distinctive_fit: Decimal
    anti_penalty: Decimal
    raw_content_fit: Decimal


class MatchScoreResponse(ApiModel):
    program_id: str
    program_code: str
    content_fit: int
    breakdown: ScoreBreakdownResponse


class ReasonResponse(ApiModel):
    kind: ReasonKind
    area: DisciplineAreaCode | None = None
    activity: ActivityCode | None = None
    text: str
    workload: Decimal
    share: Decimal
    source_names: tuple[str, ...]
    provenance: tuple[SourceAttributionResponse, ...] = ()


class OptionalMetricResponse(ApiModel):
    status: str
    value: int | None = None


class EvidenceMetricResponse(ApiModel):
    value: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)
    status: EvidenceStatus


class SourceFreshnessResponse(EvidenceMetricResponse):
    latest_captured_at: datetime | None = None
    run_ids: tuple[str, ...] = ()
    snapshot_consistent: bool | None = None


class RecommendationEvidenceResponse(ApiModel):
    profile_confidence: EvidenceMetricResponse
    catalog_completeness: EvidenceMetricResponse
    source_freshness: SourceFreshnessResponse
    reliability: EvidenceMetricResponse
    signals_used: tuple[EvidenceSignal, ...] = ()
    inferred_signals: tuple[EvidenceSignal, ...] = ()
    missing_data: tuple[SourceGapReferenceResponse, ...] = ()
    policy_version: str
    taxonomy_version: str
    question_set_version: str | None = Field(default=None, alias="questionSetVersion")
    profile_revision: int | None = Field(default=None, ge=1)
    catalog_run_ids: tuple[str, ...] = ()


class RecommendationResponse(ApiModel):
    program_id: str
    program_code: str
    program_name: str
    content_fit: int
    score: MatchScoreResponse
    reasons: tuple[ReasonResponse, ...]
    anti_fit_reasons: tuple[ReasonResponse, ...]
    area_share: dict[DisciplineAreaCode, Decimal]
    semester_distribution: dict[str, Decimal]
    distinctive_subjects: tuple[str, ...]
    admission_fit: OptionalMetricResponse
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gaps: tuple[SourceGapReferenceResponse, ...] = ()
    evidence: RecommendationEvidenceResponse


class ProftestResultsResponse(ApiModel):
    profile: UserProfileResponse
    recommendations: tuple[RecommendationResponse, ...]


class SessionProgressResponse(ApiModel):
    stage: str
    stage_index: int
    stage_count: int
    answer_count: int
    min_remaining: int
    max_remaining: int


class PreliminaryTopicResponse(ApiModel):
    code: str
    label: str


class PreliminaryProfileResponse(ApiModel):
    topics: tuple[PreliminaryTopicResponse, ...] = ()


class ProftestSessionResponse(ApiModel):
    session_id: str
    question_set_version: str
    status: SessionStatus
    cursor: int
    interaction_count: int
    revision: int
    current_question: QuestionResponse | None = None
    stale_question_ids: tuple[str, ...] = ()
    progress: SessionProgressResponse
    adaptive: AdaptiveSelectionResponse | None = None
    preliminary: PreliminaryProfileResponse | None = None
    results: ProftestResultsResponse | None = None
    profile_revision: int | None = Field(default=None, ge=1)


class ProftestAnalyticsAcceptedResponse(ApiModel):
    accepted: int


def questionnaire_response(questionnaire: Questionnaire) -> QuestionnaireResponse:
    return QuestionnaireResponse(version=questionnaire.version, question_set_version=questionnaire.question_set_version, questions=tuple(_question_response(question) for question in questionnaire.questions))


def preview_response(preview: ProftestPreview) -> ProftestPreviewResponse:
    return ProftestPreviewResponse(
        profile=profile_response(preview.profile),
        adaptive=AdaptiveSelectionResponse.model_validate(preview.adaptive.model_dump()),
        question=_question_response(preview.question) if preview.question is not None else None,
        candidates=tuple(PreviewCandidateResponse.model_validate(candidate.model_dump()) for candidate in preview.candidates),
    )


def results_response(results: ProftestResults) -> ProftestResultsResponse:
    return ProftestResultsResponse(profile=profile_response(results.profile), recommendations=tuple(recommendation_response(recommendation) for recommendation in results.recommendations))


def session_response(view: ProftestSessionView) -> ProftestSessionResponse:
    return ProftestSessionResponse(
        session_id=view.session.session_id,
        question_set_version=view.session.question_set_version,
        status=view.session.status,
        cursor=view.session.cursor,
        interaction_count=view.session.interaction_count,
        revision=view.session.revision,
        current_question=_question_response(view.current_question) if view.current_question is not None else None,
        stale_question_ids=view.session.stale_question_ids,
        progress=SessionProgressResponse.model_validate(view.progress.model_dump()),
        adaptive=AdaptiveSelectionResponse.model_validate(view.adaptive.model_dump()) if view.adaptive is not None else None,
        preliminary=PreliminaryProfileResponse.model_validate(view.preliminary.model_dump()) if view.preliminary is not None else None,
        results=results_response(view.results) if view.results is not None else None,
        profile_revision=view.profile_revision,
    )


def _question_response(question: Question) -> QuestionResponse:
    return QuestionResponse(id=question.id, block=question.block, prompt=question.prompt, options=tuple(QuestionOptionResponse(id=option.id, label=option.label) for option in question.options), required=question.required, adaptive=question.adaptive, multi_select=question.multi_select, max_selected=question.max_selected, stage=question.stage.value if question.stage is not None else None, component_type=question.component_type, order=question.order, helper_text=question.helper_text, declared_dimensions=question.declared_dimensions, allow_uncertain=question.allow_uncertain, allow_skip=question.allow_skip)


def profile_response(profile: UserProfile) -> UserProfileResponse:
    return UserProfileResponse(
        version=profile.version,
        interests=list(profile.interests),
        activity_preferences=list(profile.activity_preferences),
        anti_interests=[AntiInterestResponse(area=item.area, intensity=item.intensity) for item in profile.anti_interests],
        preferred_subject_weights=profile.preferred_subject_weights,
        preferred_activity_weights=profile.preferred_activity_weights,
        negative_weights=profile.negative_weights,
        confidence=ConfidenceResponse.model_validate(profile.confidence.model_dump()),
        adaptive_answers=[AdaptiveAnswerResponse.model_validate(answer.model_dump()) for answer in profile.adaptive_answers],
        decision_context=list(profile.decision_context),
        hard_filters=list(profile.hard_filters),
        format_preferences=list(profile.format_preferences),
        load_tolerance=profile.load_tolerance,
        confidence_by_dimension=profile.confidence_by_dimension,
        consistency_flags=list(profile.consistency_flags),
    )


def profile_contract(profile: UserProfileResponse) -> UserProfile:
    """Convert the sole HTTP profile shape to the stable module contract."""

    return UserProfile(
        version=profile.version,
        interests=tuple(DisciplineAreaCode(value) for value in profile.interests),
        activity_preferences=tuple(ActivityCode(value) for value in profile.activity_preferences),
        anti_interests=tuple(AntiInterest(area=DisciplineAreaCode(item.area), intensity=item.intensity) for item in profile.anti_interests),
        preferred_subject_weights={
            DisciplineAreaCode(area): weight
            for area, weight in profile.preferred_subject_weights.items()
        },
        preferred_activity_weights={
            ActivityCode(activity): weight
            for activity, weight in profile.preferred_activity_weights.items()
        },
        negative_weights={
            DisciplineAreaCode(area): weight
            for area, weight in profile.negative_weights.items()
        },
        confidence=Confidence(**profile.confidence.model_dump()),
        adaptive_answers=tuple(AdaptiveAnswer(**answer.model_dump()) for answer in profile.adaptive_answers),
        decision_context=tuple(profile.decision_context),
        hard_filters=tuple(profile.hard_filters),
        format_preferences=tuple(profile.format_preferences),
        load_tolerance=profile.load_tolerance,
        confidence_by_dimension=profile.confidence_by_dimension,
        consistency_flags=tuple(profile.consistency_flags),
    )


def snapshot_response(snapshot: UserProfileSnapshot) -> UserProfileSnapshotResponse:
    return UserProfileSnapshotResponse(
        profileId=snapshot.profile_id,
        profile=profile_response(snapshot.profile),
        revision=snapshot.revision,
        createdAt=snapshot.created_at,
        updatedAt=snapshot.updated_at,
        expiresAt=snapshot.expires_at,
    )


def recommendation_response(recommendation: Recommendation) -> RecommendationResponse:
    return RecommendationResponse(
        program_id=recommendation.program_id,
        program_code=recommendation.program_code,
        program_name=recommendation.program_name,
        content_fit=recommendation.content_fit,
        score=MatchScoreResponse.model_validate(recommendation.score.model_dump()),
        reasons=tuple(_reason_response(reason) for reason in recommendation.reasons),
        anti_fit_reasons=tuple(_reason_response(reason) for reason in recommendation.anti_fit_reasons),
        area_share=recommendation.area_share,
        semester_distribution=recommendation.semester_distribution,
        distinctive_subjects=recommendation.distinctive_subjects,
        admission_fit=OptionalMetricResponse.model_validate(recommendation.admission_fit.model_dump()),
        provenance=tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in recommendation.provenance),
        source_gaps=tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in recommendation.source_gaps),
        evidence=recommendation_evidence_response(recommendation.evidence),
    )


def recommendation_evidence_response(value: RecommendationEvidence) -> RecommendationEvidenceResponse:
    return RecommendationEvidenceResponse(
        profile_confidence=EvidenceMetricResponse.model_validate(value.profile_confidence.model_dump()),
        catalog_completeness=EvidenceMetricResponse.model_validate(value.catalog_completeness.model_dump()),
        source_freshness=SourceFreshnessResponse.model_validate(value.source_freshness.model_dump()),
        reliability=EvidenceMetricResponse.model_validate(value.reliability.model_dump()),
        signals_used=value.signals_used,
        inferred_signals=value.inferred_signals,
        missing_data=tuple(SourceGapReferenceResponse.model_validate(item.model_dump()) for item in value.missing_data),
        policy_version=value.policy_version,
        taxonomy_version=value.taxonomy_version,
        questionSetVersion=value.question_set_version,
        profile_revision=value.profile_revision,
        catalog_run_ids=value.catalog_run_ids,
    )


def _reason_response(reason: MatchReason) -> ReasonResponse:
    return ReasonResponse(
        kind=reason.kind,
        area=reason.area,
        activity=reason.activity,
        text=reason.text,
        workload=reason.workload,
        share=reason.share,
        source_names=reason.source_names,
        provenance=tuple(SourceAttributionResponse.model_validate(item.model_dump()) for item in reason.provenance),
    )


_profile_response = profile_response
_recommendation_response = recommendation_response


__all__ = [
    "ProftestAnalyticsBatchRequest",
    "ProftestAnalyticsAcceptedResponse",
    "ProftestSubmissionRequest",
    "ProftestSessionAnswerRequest",
    "ProftestSessionNextRequest",
    "ProftestSessionPatchRequest",
    "ProftestSessionResponse",
    "ProftestPreviewResponse",
    "ProftestResultsResponse",
    "QuestionnaireResponse",
    "RecommendationEvidenceResponse",
    "SessionProgressResponse",
    "UserProfileCreateRequest",
    "UserProfileResponse",
    "UserProfileSnapshotResponse",
    "UserProfileUpdateRequest",
    "questionnaire_response",
    "preview_response",
    "results_response",
    "session_response",
    "profile_contract",
    "profile_response",
    "snapshot_response",
    "recommendation_response",
    "recommendation_evidence_response",
]
