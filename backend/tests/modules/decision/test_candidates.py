from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.admission_fit.contracts.public import (
    AdmissionFitBreakdown,
    AdmissionFitDataQuality,
    AdmissionFitMetric,
    AdmissionFitMetricStatus,
    AdmissionFitReason,
    AdmissionFitReasonKind,
    AdmissionFitStatus,
    ApplicantAdmissionProfile,
    BatchAdmissionFitOutcome,
    BatchAdmissionFitResult,
)
from andromeda.modules.admissions.contracts.public import AdmissionOffering, AdmissionProvenance, AdmissionScope, FundingType, ProgramAdmissions, StudyForm
from andromeda.modules.decision.contracts.public import (
    AdmissionConstraints,
    DecisionCandidatePartition,
    DecisionContext,
    DecisionContextMetadata,
    DecisionDataCompleteness,
    DecisionState,
    ShortlistRole,
)
from andromeda.modules.decision.domain.entities import DecisionChoice
from andromeda.modules.decision.domain.values import DecisionSourceKind
from andromeda.modules.decision.repository.ports import ProgramCandidateSnapshot
from andromeda.modules.decision.services.candidates import DecisionCandidatePipeline
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, RecommendationEvidence, UserProfile
from andromeda.modules.recommendations.contracts.public import CandidateRankingRequest, CandidateRankingResult
from andromeda.modules.recommendations.services.recommendations import RecommendationService

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def _program(code: str) -> Program:
    return Program(
        id=f"program:{code}",
        direction_id=f"direction:{code[:8]}",
        code=code,
        name=f"Программа {code}",
        education_year=2026,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )


def _candidate(code: str, *, computer: str = "0.8", mathematics: str = "0.2") -> ProgramCandidateSnapshot:
    areas = {
        DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer),
        DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal(mathematics),
    }
    total = sum(areas.values(), Decimal("0"))
    normalized = {area: share / total for area, share in areas.items()}
    item = ProgramFingerprint(
        program_id=f"program:{code}",
        program_code=code,
        program_name=f"Программа {code}",
        basis="hours",
        total_hours=100,
        total_credits=Decimal("10"),
        total_workload=Decimal("100"),
        area_hours={area: share * 100 for area, share in normalized.items()},
        area_share=normalized,
        semester_distribution={"1": Decimal("1")},
        activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")},
    )
    program = _program(code)
    provenance = AdmissionProvenance(
        source_kind="fixture",
        source_url="https://example.test/admissions",
        captured_at=NOW,
        content_sha256="a" * 64,
    )
    admissions = ProgramAdmissions(
        program_id=program.id,
        offerings=(
            AdmissionOffering(
                id=f"admission-offering:{code}:2026:full_time:budget",
                program_id=program.id,
                admission_year=2026,
                study_form=StudyForm.FULL_TIME,
                funding_type=FundingType.BUDGET,
                scope=AdmissionScope.PROGRAM,
                provenance=(provenance,),
            ),
        ),
    )
    return ProgramCandidateSnapshot(program=program, fingerprint=item, admissions=admissions)


class Source:
    def __init__(self, items: tuple[ProgramCandidateSnapshot, ...]) -> None:
        self.items = items

    def list_candidates(self) -> tuple[ProgramCandidateSnapshot, ...]:
        return self.items


class RecordingRecommendations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.inner = RecommendationService(SourceReader())

    def rank_candidates(self, request: CandidateRankingRequest) -> CandidateRankingResult:
        self.calls.append(tuple(item.program_id for item in request.fingerprints))
        return self.inner.rank_candidates(request)

    def build_evidence(
        self,
        profile: UserProfile | None,
        fingerprint: ProgramFingerprint | None,
        *,
        profile_revision: int | None = None,
    ) -> RecommendationEvidence:
        return self.inner.build_evidence(profile, fingerprint, profile_revision=profile_revision)


class SourceReader:
    def list_fingerprints(self):
        return ()


def _admission_result(program_id: str, status: AdmissionFitStatus) -> object:
    metric = AdmissionFitMetric(value=Decimal("100"), status=AdmissionFitMetricStatus.AVAILABLE)
    return {
        "program_id": program_id,
        "offering_id": f"admission-offering:{program_id}:2026:budget",
        "admission_year": 2026,
        "status": status,
        "score": 80 if status is AdmissionFitStatus.REALISTIC else 55,
        "data_quality": AdmissionFitDataQuality.COMPLETE,
        "breakdown": AdmissionFitBreakdown(
            minimum_readiness=metric,
            passing_readiness=metric,
            data_completeness=metric,
        ),
    }


class BatchEvaluator:
    def __init__(self, statuses: dict[str, AdmissionFitStatus]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[str, ...]] = []

    def evaluate_batch(self, request: object) -> BatchAdmissionFitResult:
        self.calls.append(tuple(request.program_ids))
        outcomes: dict[str, BatchAdmissionFitOutcome] = {}
        for program_id in request.program_ids:
            status = self.statuses[program_id]
            if status is AdmissionFitStatus.INSUFFICIENT_DATA:
                outcome = BatchAdmissionFitOutcome(
                    program_id=program_id,
                    status=status,
                    data_gaps=(
                        AdmissionFitReason(
                            kind=AdmissionFitReasonKind.DATA_GAP,
                            message="Нет source-backed offering",
                        ),
                    ),
                )
            else:
                from andromeda.modules.admission_fit.contracts.public import AdmissionFitResult

                outcome = BatchAdmissionFitOutcome(
                    program_id=program_id,
                    status=status,
                    result=AdmissionFitResult.model_validate(_admission_result(program_id, status)),
                )
            outcomes[program_id] = outcome
        return BatchAdmissionFitResult(by_program_id=outcomes)


def _context(
    *,
    preferences: UserProfile | None,
    constraints: AdmissionConstraints | None = None,
    choice: DecisionChoice | None = None,
    profile_revision: int | None = 1,
) -> DecisionContext:
    state = DecisionState(
        admission_constraints=constraints,
        choice=choice or DecisionChoice(),
        created_at=NOW,
        updated_at=NOW,
    )
    decision_id = "decision:" + "a" * 32
    return DecisionContext(
        decision_id=decision_id,
        state=state,
        preferences=preferences,
        profile_revision=profile_revision,
        metadata=DecisionContextMetadata(
            decision_id=decision_id,
            revision=state.revision,
            status=state.status,
            created_at=NOW,
            updated_at=NOW,
            profile_revision=profile_revision,
        ),
    )


def _profile(
    *,
    computer: Decimal = Decimal("1"),
    mathematics: Decimal | None = None,
    subject: dict[DisciplineAreaCode, Decimal] | None = None,
) -> UserProfile:
    if subject is not None:
        subjects = subject
    else:
        subjects = {
            DisciplineAreaCode.COMPUTER_SCIENCE_DATA: computer,
        }
        if mathematics is not None:
            subjects[DisciplineAreaCode.MATHEMATICS_STATISTICS] = mathematics
    return UserProfile(
        preferred_subject_weights=subjects,
        confidence=Confidence(value=Decimal("1"), answered_base=5, answered_adaptive=0),
    )


def test_pipeline_applies_admission_before_content_fit_and_limits_partitions() -> None:
    items = tuple(_candidate(f"09.03.01-0{index}") for index in range(1, 5))
    statuses = {
        items[0].program.id: AdmissionFitStatus.REALISTIC,
        items[1].program.id: AdmissionFitStatus.UNLIKELY,
        items[2].program.id: AdmissionFitStatus.REALISTIC,
        items[3].program.id: AdmissionFitStatus.INSUFFICIENT_DATA,
    }
    recommendations = RecordingRecommendations()
    pipeline = DecisionCandidatePipeline(
        Source(items),
        recommendations,
        BatchEvaluator(statuses),
    )
    result = pipeline.build(
        _context(
            preferences=_profile(),
            constraints=AdmissionConstraints(
                applicant=ApplicantAdmissionProfile(),
                admission_year=2026,
                funding_preference=FundingType.BUDGET,
            ),
        )
    )

    assert {item.program_id for item in result.primary_candidates} | {item.program_id for item in result.alternative_candidates} == {
        items[0].program.id,
        items[2].program.id,
    }
    assert tuple(item.program_id for item in result.ineligible_candidates) == (items[1].program.id,)
    assert tuple(item.program_id for item in result.insufficient_data_candidates) == (items[3].program.id,)
    assert all(items[1].program.id not in call and items[3].program.id not in call for call in recommendations.calls)


def test_pipeline_without_profile_remains_usable_and_declares_missing_preferences() -> None:
    items = (_candidate("09.03.01-01"), _candidate("09.03.01-02"))
    recommendations = RecordingRecommendations()
    result = DecisionCandidatePipeline(Source(items), recommendations, BatchEvaluator({})).build(
    _context(preferences=None, profile_revision=None)
    )

    assert tuple(item.program_id for item in result.primary_candidates) == tuple(item.program.id for item in items)
    assert not recommendations.calls
    assert result.data_completeness is DecisionDataCompleteness.PARTIAL
    assert any("Профиль предпочтений" in item for item in result.missing_data)


def test_unavailable_admission_keeps_active_shortlist_entry_visible_without_mutation() -> None:
    item = _candidate("09.03.01-01")
    choice = DecisionChoice().add_shortlist(
        item.program.id,
        role=ShortlistRole.PRIMARY,
        origin=DecisionSourceKind.USER,
        now=NOW,
    )
    context = _context(
        preferences=_profile(),
        constraints=AdmissionConstraints(applicant=ApplicantAdmissionProfile(), admission_year=2026),
        choice=choice,
    )
    before = context.state.model_dump(mode="json")
    result = DecisionCandidatePipeline(
        Source((item,)),
        RecordingRecommendations(),
        BatchEvaluator({item.program.id: AdmissionFitStatus.UNLIKELY}),
    ).build(context)

    assert result.active_shortlist[0].program_id == item.program.id
    assert result.active_shortlist[0].admission_status is AdmissionFitStatus.UNLIKELY
    assert result.active_shortlist[0].role is ShortlistRole.PRIMARY
    assert context.state.model_dump(mode="json") == before


def test_refinement_question_is_only_returned_for_close_candidates_with_clear_difference() -> None:
    first = _candidate("09.03.01-01", computer="0.65", mathematics="0.35")
    second = _candidate("09.03.01-02", computer="0.35", mathematics="0.65")
    result = DecisionCandidatePipeline(Source((first, second)), RecordingRecommendations(), BatchEvaluator({})).build(
        _context(
            preferences=_profile(
                subject={
                    DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.5"),
                    DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.5"),
                }
            )
        )
    )

    assert result.refinement_question is not None
    assert len(result.refinement_question.options) == 2
    assert result.refinement_question.discriminating_dimensions


def test_refinement_dimensions_are_ranked_by_subject_activity_and_content_gap() -> None:
    first = _candidate("09.03.01-01", computer="0.8", mathematics="0.2")
    second = _candidate("09.03.01-02", computer="0.2", mathematics="0.8")
    first_fingerprint = first.fingerprint
    second_fingerprint = second.fingerprint
    assert first_fingerprint is not None
    assert second_fingerprint is not None
    first_fingerprint = first_fingerprint.model_copy(
        update={
            "activity_signals": {
                ActivityCode.SOFTWARE_CREATION: Decimal("0.1"),
                ActivityCode.RESEARCH: Decimal("0.9"),
            }
        }
    )
    second_fingerprint = second_fingerprint.model_copy(
        update={
            "activity_signals": {
                ActivityCode.SOFTWARE_CREATION: Decimal("0.9"),
                ActivityCode.RESEARCH: Decimal("0.1"),
            }
        }
    )
    first = ProgramCandidateSnapshot(program=first.program, fingerprint=first_fingerprint)
    second = ProgramCandidateSnapshot(program=second.program, fingerprint=second_fingerprint)

    result = DecisionCandidatePipeline(Source((first, second)), RecordingRecommendations(), BatchEvaluator({})).build(
        _context(
            preferences=_profile(
                subject={
                    DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.5"),
                    DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.5"),
                }
            )
        )
    )

    assert result.refinement_question is not None
    dimensions = result.refinement_question.discriminating_dimensions
    assert dimensions[0] in {"activity:research", "activity:software_creation"}
    assert all(dimension.startswith(("subject:", "activity:", "content:")) for dimension in dimensions)


def test_refinement_stops_when_candidate_difference_is_below_threshold() -> None:
    first = _candidate("09.03.01-01", computer="0.53", mathematics="0.47")
    second = _candidate("09.03.01-02", computer="0.50", mathematics="0.50")

    result = DecisionCandidatePipeline(Source((first, second)), RecordingRecommendations(), BatchEvaluator({})).build(
        _context(
            preferences=_profile(
                subject={
                    DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.5"),
                    DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.5"),
                }
            )
        )
    )

    assert result.refinement_question is None
