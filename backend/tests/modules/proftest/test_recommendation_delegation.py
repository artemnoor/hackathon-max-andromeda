from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, AdaptiveAnswer, AdaptiveStatus, Answer, AnswerSet, ProgramFingerprint, UserProfile
from andromeda.modules.recommendations.contracts.public import RankedFingerprint, RecommendationRequest, RecommendationResult, RecommendationServicePort
from andromeda.modules.proftest.services.proftest import ProftestService
from andromeda.modules.recommendations.services.scoring import RecommendationScoringService


def _fingerprint() -> ProgramFingerprint:
    return ProgramFingerprint(
        program_id="program:09.03.01-02", program_code="09.03.01-02", program_name="Test", basis="hours", total_hours=100, total_credits=Decimal("10"), total_workload=Decimal("100"),
        area_hours={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("80"), DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("20")},
        area_share={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.8"), DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.2")}, semester_distribution={"1": Decimal("1")}, activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")},
    )


class _Catalog:
    def __init__(self, fingerprints: tuple[ProgramFingerprint, ...]) -> None:
        self.fingerprints = fingerprints

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        return self.fingerprints


class _RecommendationSpy:
    def __init__(self) -> None:
        self.requests: list[RecommendationRequest] = []
        self.scorer = RecommendationScoringService()

    def rank_fingerprints(self, profile: UserProfile, fingerprints: Iterable[ProgramFingerprint], *, limit: int | None = None) -> tuple[RankedFingerprint, ...]:
        return tuple(RankedFingerprint(fingerprint, self.scorer.score(profile, fingerprint)) for fingerprint in fingerprints)

    def recommend_from_fingerprints(
        self,
        request: RecommendationRequest,
        fingerprints: tuple[ProgramFingerprint, ...],
        *,
        profile_revision: int | None = None,
        question_set_version: str | None = None,
    ) -> RecommendationResult:
        self.requests.append(request)
        return RecommendationResult(profile=request.profile, recommendations=())


def _as_recommendation_port(service: RecommendationServicePort) -> RecommendationServicePort:
    return service


def test_final_proftest_ranking_is_delegated_as_profile_contract() -> None:
    spy = _RecommendationSpy()
    service = ProftestService(_Catalog((_fingerprint(),)), recommendations=_as_recommendation_port(spy))
    questionnaire = service.questionnaire()
    answers = AnswerSet(answers=tuple(Answer(question_id=question.id, option_ids=(question.options[0].id,)) for question in questionnaire.questions))

    preview = service.preview(answers)
    result = service.results(answers)

    assert len(preview.candidates) == 1
    assert result.recommendations == ()
    assert len(spy.requests) == 1
    assert spy.requests[0].profile == result.profile
    assert not hasattr(spy.requests[0], "answers")


def test_adaptive_answers_are_accepted_for_the_question_selected_from_catalog() -> None:
    spy = _RecommendationSpy()
    second = _fingerprint().model_copy(
        update={
            "program_id": "program:09.03.01-03",
            "program_code": "09.03.01-03",
            "area_hours": {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("20"), DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("80")},
            "area_share": {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.2"), DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.8")},
        },
    )
    service = ProftestService(_Catalog((_fingerprint(), second)), recommendations=_as_recommendation_port(spy))
    questionnaire = service.questionnaire()
    answers = AnswerSet(answers=tuple(Answer(question_id=question.id, option_ids=(question.options[0].id,)) for question in questionnaire.questions))

    preview = service.preview(answers)

    assert preview.adaptive.status is AdaptiveStatus.READY
    assert preview.question is not None
    adaptive_answers = AnswerSet(
        answers=answers.answers,
        adaptive_answers=(AdaptiveAnswer(question_id=preview.question.id, option_id=preview.question.options[0].id, dimension=preview.adaptive.dimensions[0].code),),
    )
    result = service.results(adaptive_answers)

    assert result.profile.confidence.answered_adaptive == 1
    assert spy.requests[0].profile == result.profile
