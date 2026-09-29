from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import (
    ActivityCode,
    AnswerSet,
    MatchScore,
    ProfileScope,
    ProgramFingerprint,
    ProftestAnswerSession,
    ScoreBreakdown,
    SessionAnswer,
    SessionStatus,
    UserProfileSnapshot,
)
from andromeda.modules.proftest.services.session import ProftestSessionService
from andromeda.modules.recommendations.domain.entities import RankedFingerprint
from andromeda.shared.contracts.errors import ValidationError


AREAS = (
    DisciplineAreaCode.COMPUTER_SCIENCE_DATA,
    DisciplineAreaCode.MATHEMATICS_STATISTICS,
    DisciplineAreaCode.ENGINEERING_TECHNOLOGY,
    DisciplineAreaCode.PHYSICS_ASTRONOMY,
    DisciplineAreaCode.CHEMISTRY_MATERIALS,
    DisciplineAreaCode.BUSINESS_MANAGEMENT,
    DisciplineAreaCode.ECONOMICS_FINANCE,
    DisciplineAreaCode.PSYCHOLOGY_COGNITIVE,
    DisciplineAreaCode.SOCIETY_SOCIAL_SCIENCES,
)


def _fingerprints() -> tuple[ProgramFingerprint, ...]:
    result = []
    for index, dominant in enumerate(AREAS, start=1):
        share = {area: (Decimal("0.6") if area is dominant else Decimal("0.05")) for area in AREAS}
        result.append(
            ProgramFingerprint(
                program_id=f"program:09.03.01-{index:02d}",
                program_code=f"09.03.01-{index:02d}",
                program_name=f"Program {index}",
                basis="hours",
                total_hours=100,
                total_credits=Decimal("10"),
                total_workload=Decimal("100"),
                area_hours={area: value * 100 for area, value in share.items()},
                area_share=share,
                semester_distribution={"1": Decimal("1")},
                activity_signals={ActivityCode.ANALYTICAL: Decimal("0.5"), ActivityCode.SOFTWARE_CREATION: Decimal("0.5")},
            )
        )
    return tuple(result)


class _Catalog:
    def __init__(self, fingerprints: tuple[ProgramFingerprint, ...]) -> None:
        self.fingerprints = fingerprints

    def list_fingerprints(self) -> tuple[ProgramFingerprint, ...]:
        return self.fingerprints


class _Recommendations:
    def __init__(self, scores: tuple[int, ...]) -> None:
        self.scores = scores

    def rank_fingerprints(self, profile, fingerprints, *, limit=None):
        adaptive_count = len(profile.adaptive_answers)
        score = self.scores[min(adaptive_count, len(self.scores) - 1)]
        ranked = tuple(
            RankedFingerprint(
                fingerprint=fingerprint,
                score=MatchScore(
                    program_id=fingerprint.program_id,
                    program_code=fingerprint.program_code,
                    content_fit=score,
                    breakdown=ScoreBreakdown(
                        subject_fit=Decimal(score),
                        activity_fit=Decimal(score),
                        distinctive_fit=Decimal(score),
                        anti_penalty=Decimal("0"),
                        raw_content_fit=Decimal(score),
                    ),
                ),
            )
            for fingerprint in fingerprints
        )
        return ranked[:limit] if limit is not None else ranked

    def recommend_from_fingerprints(self, request, fingerprints, *, profile_revision=None, question_set_version=None):
        raise AssertionError("completion is not part of the session policy fixture")


class _Store:
    def __init__(self) -> None:
        self.current = None

    def get_current(self, scope):
        return self.current

    def start(self, scope, *, question_set_version, current_question_id, expires_at):
        if self.current is not None and self.current.status is SessionStatus.DRAFT:
            return self.current
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        self.current = ProftestAnswerSession(
            session_id="proftest-session:" + "e" * 32,
            question_set_version=question_set_version,
            cursor=0,
            interaction_count=0,
            current_question_id=current_question_id,
            revision=1,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=1),
        )
        return self.current

    def save(self, scope, session, *, expected_revision):
        assert self.current is not None
        assert self.current.revision == expected_revision
        self.current = session.model_copy(update={"revision": expected_revision + 1})
        return self.current

    def complete(self, scope, session, profile, *, expires_at):
        raise AssertionError("completion is not part of the session policy fixture")


def _answer(view) -> SessionAnswer:
    question = view.current_question
    assert question is not None
    return SessionAnswer(
        question_id=question.id,
        option_ids=(question.options[0].id,),
        dimension=question.declared_dimensions[0] if question.adaptive else None,
    )


def _run_until_stop(scores: tuple[int, ...]) -> tuple[object, int]:
    fingerprints = _fingerprints()
    service = ProftestSessionService(_Catalog(fingerprints), _Recommendations(scores), _Store())
    scope = ProfileScope(session_key_hash="e" * 64)
    view = service.start(scope)
    submissions = 0
    while view.current_question is not None:
        view = service.next(scope, _answer(view), expected_revision=view.session.revision)
        submissions += 1
        assert submissions <= 9
    return view, submissions


def test_v3_stable_profile_stops_after_seven_submissions() -> None:
    view, submissions = _run_until_stop((80, 80, 80, 80))

    assert submissions == 7
    assert view.session.question_set_version == "proftest-v3"
    assert view.adaptive is not None
    assert view.adaptive.stop_reason.value == "top_three_stable"
    assert view.preliminary is not None
    assert len(view.preliminary.topics) <= 3


def test_v3_ordinary_profile_stops_after_eight_submissions() -> None:
    view, submissions = _run_until_stop((80, 70, 60, 58))

    assert submissions == 8
    assert view.adaptive is not None
    assert view.adaptive.stop_reason.value == "low_ranking_impact"


def test_v3_ambiguous_profile_is_capped_at_nine_submissions() -> None:
    view, submissions = _run_until_stop((80, 70, 60, 50, 40))

    assert submissions == 9
    assert view.adaptive is not None
    assert view.adaptive.stop_reason.value == "max_questions"


def test_pinned_v2_draft_is_resolved_without_being_reinterpreted_as_v3() -> None:
    store = _Store()
    scope = ProfileScope(session_key_hash="f" * 64)
    store.start(
        scope,
        question_set_version="proftest-v2",
        current_question_id="context_goal",
        expires_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    service = ProftestSessionService(_Catalog(_fingerprints()), _Recommendations((80,)), store)

    view = service.current(scope)

    assert view.session.question_set_version == "proftest-v2"
    assert view.current_question is not None
    assert view.current_question.id == "context_goal"
    assert view.progress.max_remaining <= 38


def test_unknown_pinned_question_set_is_rejected() -> None:
    store = _Store()
    scope = ProfileScope(session_key_hash="f" * 64)
    store.start(
        scope,
        question_set_version="proftest-v9",
        current_question_id="core_doing",
        expires_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    service = ProftestSessionService(_Catalog(_fingerprints()), _Recommendations((80,)), store)

    try:
        service.current(scope)
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown question set must be rejected")
