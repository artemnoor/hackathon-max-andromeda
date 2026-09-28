"""HTTP contracts for source-backed admission rights and achievements."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal, TypeVar

from pydantic import BeforeValidator, Field

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
    ApplicantIndividualAchievement,
    ApplicantInternalExamScore,
    ApplicantOlympiadAchievement,
)
from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitConditionKind,
    BenefitScope,
    BenefitTarget,
    BenefitTargetKind,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AchievementCombinationPolicy,
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitCondition,
    BenefitType,
    ConfirmationApplicantCategory,
    ConfirmationExamKind,
    ConfirmationRequirement,
    ConfirmationSubjectRule,
    IndividualAchievementRule,
    OlympiadResultType,
)
from andromeda.modules.admission_benefits.contracts.results import (
    AdmissionBenefitEvaluation,
    AdmissionBenefitEvidence,
    AdmissionDecisionResult,
    CompetitiveExamScore,
    CompetitiveScoreStatus,
    EffectiveCompetitiveScore,
    EligibilityStatus,
    IndividualAchievementEvaluation,
)
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.services.evaluator import (
    AdmissionBenefitEvaluationInput,
)
from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.shared.contracts.enums import EducationLevel

from .admissions import AdmissionProvenanceResponse
from .common import ApiModel, SourceAttributionResponse, SourceGapReferenceResponse


def _decimal_from_json(value: object) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


JsonScore = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_json),
    Field(strict=True, ge=Decimal(0), le=Decimal(100), max_digits=5, decimal_places=2),
]


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    """Convert JSON enum strings before strict API-model validation."""

    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


JsonOlympiadResultType = Annotated[
    OlympiadResultType,
    BeforeValidator(lambda value: _enum_from_json(OlympiadResultType, value)),
]
JsonEducationLevel = Annotated[
    EducationLevel,
    BeforeValidator(lambda value: _enum_from_json(EducationLevel, value)),
]
JsonStudyForm = Annotated[StudyForm, BeforeValidator(lambda value: _enum_from_json(StudyForm, value))]
JsonFundingType = Annotated[FundingType, BeforeValidator(lambda value: _enum_from_json(FundingType, value))]
JsonConfirmationApplicantCategory = Annotated[
    ConfirmationApplicantCategory,
    BeforeValidator(
        lambda value: _enum_from_json(ConfirmationApplicantCategory, value)
    ),
]


class BenefitProvenanceResponse(ApiModel):
    source: SourceAttributionResponse
    source_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_run_id: str = Field(pattern=r"^ingest:[a-f0-9]{32}$")
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    document_title: str = Field(min_length=1, max_length=512)
    document_kind: str = Field(min_length=1, max_length=128)
    appendix_number: str | None = None
    page: int | None = Field(default=None, ge=1)
    table: str | None = None
    row: int | None = Field(default=None, ge=1)
    section: str | None = None
    parser_version: str = Field(min_length=1, max_length=128)


class BenefitTargetResponse(ApiModel):
    kind: BenefitTargetKind
    value: str
    original_text: str
    resolution: str


class BenefitScopeResponse(ApiModel):
    mode: str
    targets: tuple[BenefitTargetResponse, ...]
    excluded_targets: tuple[BenefitTargetResponse, ...]
    original_text: str


class ConfirmationSubjectResponse(ApiModel):
    subject: str
    minimum_score: Decimal | None = None
    exam_kind: ConfirmationExamKind
    applicant_category: ConfirmationApplicantCategory | None = None
    source_text: str


class ValidityPolicyResponse(ApiModel):
    valid_from_result_year: int | None = None
    valid_until_result_year: int | None = None
    max_age_years: int | None = None
    source_text: str


class BenefitConditionResponse(ApiModel):
    kind: BenefitConditionKind
    source_text: str
    normalized_value: str | None = None
    provenance: BenefitProvenanceResponse | None = None


class OlympiadProfileSubjectResponse(ApiModel):
    subject: str
    source_text: str


class OlympiadResponse(ApiModel):
    id: str
    official_name: str
    organizer: str | None = None
    rsosh_level: int | None = None
    admission_year: int
    provenance: tuple[BenefitProvenanceResponse, ...]


class OlympiadProfileResponse(ApiModel):
    id: str
    olympiad_id: str
    profile_name: str
    corresponding_subjects: tuple[OlympiadProfileSubjectResponse, ...]
    admission_year: int
    provenance: tuple[BenefitProvenanceResponse, ...]


class AdmissionBenefitRuleResponse(ApiModel):
    id: str
    university_id: str
    admission_year: int
    education_level: EducationLevel | None = None
    route: AdmissionRoute
    benefit_type: BenefitType
    olympiad_id: str | None = None
    olympiad_profile_id: str | None = None
    result_type: OlympiadResultType | None = None
    scope: BenefitScopeResponse
    confirmation_requirement: ConfirmationRequirement
    confirmation_subjects: tuple[ConfirmationSubjectResponse, ...]
    validity: ValidityPolicyResponse
    target_subject: str | None = None
    points: Decimal | None = None
    conditions: tuple[BenefitConditionResponse, ...]
    source_text: str
    status: str
    policy_version: dict[str, str]
    provenance: BenefitProvenanceResponse


class IndividualAchievementRuleResponse(ApiModel):
    id: str
    university_id: str
    admission_year: int
    education_level: EducationLevel | None = None
    achievement_code: str
    category: str
    official_name: str
    description: str | None = None
    points: Decimal
    category_cap: Decimal | None = None
    combination_group: str | None = None
    combination_policy: AchievementCombinationPolicy
    required_document: str | None = None
    conditions: tuple[BenefitConditionResponse, ...]
    source_text: str
    status: str
    policy_version: dict[str, str]
    provenance: BenefitProvenanceResponse


class IndividualAchievementPolicyResponse(ApiModel):
    university_id: str
    admission_year: int
    education_level: EducationLevel | None = None
    global_max_points: Decimal | None = None
    default_combination_policy: AchievementCombinationPolicy
    rules: tuple[IndividualAchievementRuleResponse, ...]
    source_text: str
    status: str
    policy_version: dict[str, str]
    provenance: BenefitProvenanceResponse


class AdmissionBenefitCoverageResponse(ApiModel):
    status: AdmissionBenefitCoverageStatus
    documents_discovered: int
    documents_selected: int
    documents_captured: int
    documents_parsed: int
    required_documents_expected: int
    required_documents_discovered: int
    required_documents_captured: int
    records_normalized: int
    targets_resolved: int
    unresolved_targets: int
    conflicts: int
    review_required_rows: int
    manifest_hash: str | None
    source_hashes: tuple[str, ...]


class AdmissionBenefitsResponse(ApiModel):
    admission_year: int
    sources: tuple[SourceAttributionResponse, ...]
    olympiads: tuple[OlympiadResponse, ...]
    olympiad_profiles: tuple[OlympiadProfileResponse, ...]
    benefit_rules: tuple[AdmissionBenefitRuleResponse, ...]
    individual_achievement_policy: IndividualAchievementPolicyResponse | None = None
    coverage: AdmissionBenefitCoverageResponse
    source_gaps: tuple[SourceGapReferenceResponse, ...]


class AdmissionBenefitRuleListResponse(ApiModel):
    admission_year: int
    rules: tuple[AdmissionBenefitRuleResponse, ...]
    source_gaps: tuple[str, ...] = ()


class ApplicantExamScoreRequest(ApiModel):
    subject: str = Field(min_length=1, max_length=256)
    score: JsonScore


class ApplicantInternalExamScoreRequest(ApiModel):
    subject: str = Field(min_length=1, max_length=256)
    score: JsonScore


class ApplicantOlympiadAchievementRequest(ApiModel):
    olympiad_id: str = Field(pattern=r"^olympiad:[a-z0-9][a-z0-9-]{0,127}$")
    olympiad_profile_id: str | None = Field(
        default=None, pattern=r"^olympiad-profile:[a-z0-9][a-z0-9-]{0,127}$"
    )
    result_year: int = Field(strict=True, ge=2000, le=2100)
    result_type: JsonOlympiadResultType
    confirmation_subject: str | None = Field(default=None, min_length=1, max_length=256)
    grade_or_class: str | None = Field(default=None, min_length=1, max_length=128)
    evidence_reference: str | None = Field(default=None, min_length=1, max_length=256)


class ApplicantIndividualAchievementRequest(ApiModel):
    achievement_code: str = Field(min_length=1, max_length=256)
    year: int | None = Field(default=None, ge=2000, le=2100)
    details: str | None = Field(default=None, min_length=1, max_length=512)
    evidence_reference: str | None = Field(default=None, min_length=1, max_length=256)


class ApplicantAdmissionFactsRequest(ApiModel):
    ege_scores: list[ApplicantExamScoreRequest] = Field(
        default_factory=list, max_length=20
    )
    internal_exam_scores: list[ApplicantInternalExamScoreRequest] = Field(
        default_factory=list, max_length=20
    )
    olympiad_achievements: list[ApplicantOlympiadAchievementRequest] = Field(
        default_factory=list, max_length=100
    )
    individual_achievements: list[ApplicantIndividualAchievementRequest] = Field(
        default_factory=list, max_length=100
    )
    confirmation_category: JsonConfirmationApplicantCategory | None = None


class AdmissionEligibilityRequest(ApiModel):
    version: Literal[1] = 1
    university_id: str = Field(pattern=r"^university:[a-z0-9][a-z0-9-]{0,127}$")
    direction_code: str = Field(pattern=r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}$")
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    education_level: JsonEducationLevel | None = None
    nps: str | None = Field(default=None, min_length=1, max_length=256)
    offering_id: str | None = Field(default=None, min_length=1, max_length=512)
    study_form: JsonStudyForm | None = None
    funding_type: JsonFundingType | None = None
    campus_id: str | None = Field(default=None, pattern=r"^campus:[a-z0-9][a-z0-9-]{0,62}$")
    applicant: ApplicantAdmissionFactsRequest


class AdmissionBenefitEvidenceResponse(ApiModel):
    rule_id: str
    provenance: BenefitProvenanceResponse
    excerpt: str | None = None


class AdmissionBenefitEvaluationResponse(ApiModel):
    rule_id: str
    benefit_type: BenefitType
    route: AdmissionRoute | None = None
    status: EligibilityStatus
    result_type: OlympiadResultType | None = None
    matched_applicant_fact: str | None = None
    rejection_reason: str | None = None
    effective_score_change: Decimal | None = None
    points_contribution: Decimal | None = None
    evidence: tuple[AdmissionBenefitEvidenceResponse, ...]


class IndividualAchievementEvaluationResponse(ApiModel):
    rule_id: str | None = None
    achievement_code: str
    status: str
    applicant_year: int | None = None
    rule_points: Decimal | None = None
    awarded_points: Decimal
    combination_policy: AchievementCombinationPolicy | None = None
    reason: str
    evidence: tuple[AdmissionBenefitEvidenceResponse, ...]


class IndividualAchievementBreakdownResponse(ApiModel):
    status: EligibilityStatus
    total_points: Decimal
    uncapped_points: Decimal
    global_cap: Decimal | None = None
    evaluations: tuple[IndividualAchievementEvaluationResponse, ...]
    source_gaps: tuple[str, ...]


class CompetitiveExamScoreResponse(ApiModel):
    subject: str
    source_name: str
    raw_score: Decimal | None = None
    effective_score: Decimal | None = None
    minimum_score: Decimal | None = None
    applied_benefit_rule_ids: tuple[str, ...]
    provenance: tuple[AdmissionProvenanceResponse, ...]


class EffectiveCompetitiveScoreResponse(ApiModel):
    status: CompetitiveScoreStatus
    offering_id: str | None = None
    available_offering_ids: tuple[str, ...]
    selected_exam_combination: tuple[str, ...]
    exam_scores_before: tuple[CompetitiveExamScoreResponse, ...]
    exam_scores_after_benefits: tuple[CompetitiveExamScoreResponse, ...]
    candidate_exams_considered: int
    base_exam_score: Decimal | None = None
    post_benefit_exam_score: Decimal | None = None
    individual_achievement_points: Decimal | None = None
    effective_total: Decimal | None = None
    source_gaps: tuple[str, ...]


class AdmissionEligibilityResponse(ApiModel):
    program_id: str
    admission_year: int
    status: EligibilityStatus
    route: AdmissionRoute | None = None
    evaluations: tuple[AdmissionBenefitEvaluationResponse, ...]
    base_competitive_score: Decimal | None = None
    individual_achievement_points: Decimal | None = None
    effective_competitive_score: Decimal | None = None
    individual_achievements: IndividualAchievementBreakdownResponse | None = None
    competitive_score: EffectiveCompetitiveScoreResponse | None = None
    source_gaps: tuple[str, ...]


def provenance_response(value: BenefitProvenance) -> BenefitProvenanceResponse:
    return BenefitProvenanceResponse(
        source=SourceAttributionResponse.model_validate(value.source.model_dump()),
        source_snapshot_hash=value.source_snapshot_hash,
        source_run_id=value.source_run_id,
        admission_year=value.admission_year,
        document_title=value.document_title,
        document_kind=value.document_kind,
        appendix_number=value.appendix_number,
        page=value.page,
        table=value.table,
        row=value.row,
        section=value.section,
        parser_version=value.parser_version,
    )


def _target(value: BenefitTarget) -> BenefitTargetResponse:
    return BenefitTargetResponse(
        kind=value.kind,
        value=value.value,
        original_text=value.original_text,
        resolution=value.resolution.value,
    )


def _scope(value: BenefitScope) -> BenefitScopeResponse:
    return BenefitScopeResponse(
        mode=value.mode.value,
        targets=tuple(_target(item) for item in value.targets),
        excluded_targets=tuple(_target(item) for item in value.excluded_targets),
        original_text=value.original_text,
    )


def _condition(value: BenefitCondition) -> BenefitConditionResponse:
    return BenefitConditionResponse(
        kind=value.kind,
        source_text=value.source_text,
        normalized_value=value.normalized_value,
        provenance=(provenance_response(value.provenance) if value.provenance else None),
    )


def _rule(value: AdmissionBenefitRule) -> AdmissionBenefitRuleResponse:
    return AdmissionBenefitRuleResponse(
        id=value.id,
        university_id=value.university_id,
        admission_year=value.admission_year,
        education_level=value.education_level,
        route=value.route,
        benefit_type=value.benefit_type,
        olympiad_id=value.olympiad_id,
        olympiad_profile_id=value.olympiad_profile_id,
        result_type=value.result_type,
        scope=_scope(value.scope),
        confirmation_requirement=value.confirmation_requirement,
        confirmation_subjects=tuple(
            _confirmation_subject(item) for item in value.confirmation_subjects
        ),
        validity=ValidityPolicyResponse.model_validate(value.validity.model_dump()),
        target_subject=value.target_subject,
        points=value.points,
        conditions=tuple(_condition(item) for item in value.conditions),
        source_text=value.source_text,
        status=value.status.value,
        policy_version=value.policy_version.model_dump(mode="json"),
        provenance=provenance_response(value.provenance),
    )


def _confirmation_subject(
    value: ConfirmationSubjectRule,
) -> ConfirmationSubjectResponse:
    return ConfirmationSubjectResponse.model_validate(value.model_dump())


def _achievement_rule(
    value: IndividualAchievementRule,
) -> IndividualAchievementRuleResponse:
    return IndividualAchievementRuleResponse(
        id=value.id,
        university_id=value.university_id,
        admission_year=value.admission_year,
        education_level=value.education_level,
        achievement_code=value.achievement_code,
        category=value.category,
        official_name=value.official_name,
        description=value.description,
        points=value.points,
        category_cap=value.category_cap,
        combination_group=value.combination_group,
        combination_policy=value.combination_policy,
        required_document=value.required_document,
        conditions=tuple(_condition(item) for item in value.conditions),
        source_text=value.source_text,
        status=value.status.value,
        policy_version=value.policy_version.model_dump(mode="json"),
        provenance=provenance_response(value.provenance),
    )


def coverage_response(
    value: AdmissionBenefitCoverage,
) -> AdmissionBenefitCoverageResponse:
    return AdmissionBenefitCoverageResponse.model_validate(value.model_dump())


def admission_benefits_response(
    value: AdmissionBenefitsSnapshot,
) -> AdmissionBenefitsResponse:
    policy = value.individual_achievement_policy
    return AdmissionBenefitsResponse(
        admission_year=value.admission_year,
        sources=tuple(
            SourceAttributionResponse.model_validate(item.model_dump())
            for item in value.sources
        ),
        olympiads=tuple(
            OlympiadResponse(
                id=item.id,
                official_name=item.official_name,
                organizer=item.organizer,
                rsosh_level=item.rsosh_level,
                admission_year=item.admission_year,
                provenance=tuple(provenance_response(row) for row in item.provenance),
            )
            for item in value.olympiads
        ),
        olympiad_profiles=tuple(
            OlympiadProfileResponse(
                id=item.id,
                olympiad_id=item.olympiad_id,
                profile_name=item.profile_name,
                corresponding_subjects=tuple(
                    OlympiadProfileSubjectResponse.model_validate(subject.model_dump())
                    for subject in item.corresponding_subjects
                ),
                admission_year=item.admission_year,
                provenance=tuple(provenance_response(row) for row in item.provenance),
            )
            for item in value.olympiad_profiles
        ),
        benefit_rules=tuple(_rule(item) for item in value.benefit_rules),
        individual_achievement_policy=(
            IndividualAchievementPolicyResponse(
                university_id=policy.university_id,
                admission_year=policy.admission_year,
                education_level=policy.education_level,
                global_max_points=policy.global_max_points,
                default_combination_policy=policy.default_combination_policy,
                rules=tuple(_achievement_rule(item) for item in policy.rules),
                source_text=policy.source_text,
                status=policy.status.value,
                policy_version=policy.policy_version.model_dump(mode="json"),
                provenance=provenance_response(policy.provenance),
            )
            if policy is not None
            else None
        ),
        coverage=coverage_response(value.coverage),
        source_gaps=tuple(
            SourceGapReferenceResponse.model_validate(item.model_dump())
            for item in value.source_gaps
        ),
    )


def rule_list_response(
    admission_year: int, rules: tuple[AdmissionBenefitRule, ...]
) -> AdmissionBenefitRuleListResponse:
    return AdmissionBenefitRuleListResponse(
        admission_year=admission_year, rules=tuple(_rule(item) for item in rules)
    )


def admission_facts(value: ApplicantAdmissionFactsRequest) -> ApplicantAdmissionFacts:
    return ApplicantAdmissionFacts(
        ege_scores=tuple(
            ApplicantExamScore(subject=item.subject, score=item.score)
            for item in value.ege_scores
        ),
        internal_exam_scores=tuple(
            ApplicantInternalExamScore(subject=item.subject, score=item.score)
            for item in value.internal_exam_scores
        ),
        olympiad_achievements=tuple(
            ApplicantOlympiadAchievement.model_validate(item.model_dump())
            for item in value.olympiad_achievements
        ),
        individual_achievements=tuple(
            ApplicantIndividualAchievement.model_validate(item.model_dump())
            for item in value.individual_achievements
        ),
        confirmation_category=value.confirmation_category,
    )


def eligibility_request(
    program_id: str, value: AdmissionEligibilityRequest
) -> AdmissionBenefitEvaluationInput:
    return AdmissionBenefitEvaluationInput(
        program_id=program_id,
        direction_code=value.direction_code,
        admission_year=value.admission_year,
        education_level=value.education_level,
        nps=value.nps,
        campus_id=None,
        applicant=admission_facts(value.applicant),
    )


def _competitive_exam_score(value: CompetitiveExamScore) -> CompetitiveExamScoreResponse:
    return CompetitiveExamScoreResponse(
        subject=value.subject,
        source_name=value.source_name,
        raw_score=value.raw_score,
        effective_score=value.effective_score,
        minimum_score=value.minimum_score,
        applied_benefit_rule_ids=value.applied_benefit_rule_ids,
        provenance=tuple(AdmissionProvenanceResponse.model_validate(item.model_dump()) for item in value.provenance),
    )


def _competitive_score(value: EffectiveCompetitiveScore | None) -> EffectiveCompetitiveScoreResponse | None:
    if value is None:
        return None
    return EffectiveCompetitiveScoreResponse(
        status=value.status,
        offering_id=value.offering_id,
        available_offering_ids=value.available_offering_ids,
        selected_exam_combination=value.selected_exam_combination,
        exam_scores_before=tuple(_competitive_exam_score(item) for item in value.exam_scores_before),
        exam_scores_after_benefits=tuple(_competitive_exam_score(item) for item in value.exam_scores_after_benefits),
        candidate_exams_considered=value.candidate_exams_considered,
        base_exam_score=value.base_exam_score,
        post_benefit_exam_score=value.post_benefit_exam_score,
        individual_achievement_points=value.individual_achievement_points,
        effective_total=value.effective_total,
        source_gaps=value.source_gaps,
    )


def _evidence(value: AdmissionBenefitEvidence) -> AdmissionBenefitEvidenceResponse:
    return AdmissionBenefitEvidenceResponse(
        rule_id=value.rule_id,
        provenance=provenance_response(value.provenance),
        excerpt=value.excerpt,
    )


def _evaluation(
    value: AdmissionBenefitEvaluation,
) -> AdmissionBenefitEvaluationResponse:
    return AdmissionBenefitEvaluationResponse(
        rule_id=value.rule_id,
        benefit_type=value.benefit_type,
        route=value.route,
        status=value.status,
        result_type=value.result_type,
        matched_applicant_fact=value.matched_applicant_fact,
        rejection_reason=value.rejection_reason,
        effective_score_change=value.effective_score_change,
        points_contribution=value.points_contribution,
        evidence=tuple(_evidence(item) for item in value.evidence),
    )


def _achievement_evaluation(
    value: IndividualAchievementEvaluation,
) -> IndividualAchievementEvaluationResponse:
    return IndividualAchievementEvaluationResponse(
        rule_id=value.rule_id,
        achievement_code=value.achievement_code,
        status=value.status.value,
        applicant_year=value.applicant_year,
        rule_points=value.rule_points,
        awarded_points=value.awarded_points,
        combination_policy=value.combination_policy,
        reason=value.reason,
        evidence=tuple(_evidence(item) for item in value.evidence),
    )


def eligibility_response(
    value: AdmissionDecisionResult,
) -> AdmissionEligibilityResponse:
    breakdown = value.individual_achievements
    return AdmissionEligibilityResponse(
        program_id=value.program_id,
        admission_year=value.admission_year,
        status=value.status,
        route=value.route,
        evaluations=tuple(_evaluation(item) for item in value.eligibility.evaluations)
        if value.eligibility
        else (),
        base_competitive_score=value.base_competitive_score,
        individual_achievement_points=value.individual_achievement_points,
        effective_competitive_score=value.effective_competitive_score,
        individual_achievements=(
            IndividualAchievementBreakdownResponse(
                status=breakdown.status,
                total_points=breakdown.total_points,
                uncapped_points=breakdown.uncapped_points,
                global_cap=breakdown.global_cap,
                evaluations=tuple(
                    _achievement_evaluation(item) for item in breakdown.evaluations
                ),
                source_gaps=breakdown.source_gaps,
            )
            if breakdown is not None
            else None
        ),
        competitive_score=_competitive_score(value.competitive_score),
        source_gaps=value.source_gaps,
    )


__all__ = [
    "AdmissionBenefitRuleListResponse",
    "AdmissionBenefitsResponse",
    "AdmissionEligibilityRequest",
    "AdmissionEligibilityResponse",
    "admission_benefits_response",
    "eligibility_request",
    "eligibility_response",
    "rule_list_response",
]
