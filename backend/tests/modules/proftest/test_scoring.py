from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, UserProfile
from andromeda.modules.proftest.services.matching import MatchingService
from andromeda.modules.proftest.services.ranking import RankingService


def _fingerprint(code: str, computer_share: str, physics_share: str) -> ProgramFingerprint:
    return ProgramFingerprint(
        program_id=f"program:09.03.01-{code}", program_code=f"09.03.01-{code}", program_name=code, basis="hours", total_hours=100, total_credits=Decimal("10"), total_workload=Decimal("100"),
        area_hours={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer_share) * 100, DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal(physics_share) * 100},
        area_share={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer_share), DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal(physics_share)}, semester_distribution={"1": Decimal("1")}, activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")},
    )


def _profile(negative_physics: str = "0") -> UserProfile:
    return UserProfile(
        preferred_subject_weights={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        negative_weights={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal(negative_physics)} if negative_physics != "0" else {},
        confidence=Confidence(value=Decimal("1"), answered_base=6, answered_adaptive=0),
    )


def test_content_fit_is_integer_and_exposes_components() -> None:
    score = MatchingService().score(_profile(), _fingerprint("02", "0.8", "0.2"))

    assert isinstance(score.content_fit, int)
    assert 0 <= score.content_fit <= 100
    assert score.breakdown.subject_fit == Decimal("80")
    assert score.breakdown.anti_penalty == Decimal("0")


def test_stronger_anti_interest_cannot_improve_high_area_program() -> None:
    physics_program = _fingerprint("02", "0.2", "0.8")
    neutral = MatchingService().score(_profile("0.2"), physics_program)
    strong = MatchingService().score(_profile("1"), physics_program)

    assert strong.content_fit < neutral.content_fit
    assert strong.breakdown.anti_penalty > neutral.breakdown.anti_penalty


def test_ranking_is_deterministic_for_equal_inputs() -> None:
    fingerprints = (_fingerprint("12", "0.8", "0.2"), _fingerprint("02", "0.8", "0.2"))

    first = RankingService().rank(_profile(), fingerprints)
    second = RankingService().rank(_profile(), fingerprints)

    assert [item[0].program_code for item in first] == ["09.03.01-02", "09.03.01-12"]
    assert first == second
