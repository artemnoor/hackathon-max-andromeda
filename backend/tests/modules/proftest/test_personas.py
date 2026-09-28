from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, UserProfile
from andromeda.modules.proftest.services.matching import MatchingService
from andromeda.modules.proftest.services.ranking import RankingService


def _fingerprint(code: str, areas: dict[DisciplineAreaCode, Decimal], activities: dict[ActivityCode, Decimal]) -> ProgramFingerprint:
    return ProgramFingerprint(
        program_id=f"program:09.03.01-{code}", program_code=f"09.03.01-{code}", program_name=code, basis="hours", total_hours=100, total_credits=Decimal("10"), total_workload=Decimal("100"),
        area_hours={area: share * 100 for area, share in areas.items()}, area_share=areas, semester_distribution={"1": Decimal("1")}, activity_signals=activities,
    )


def _profile(**values: Decimal) -> UserProfile:
    return UserProfile(preferred_subject_weights=values, confidence=Confidence(value=Decimal("1"), answered_base=6, answered_adaptive=0))


def test_synthetic_personas_preserve_content_direction_properties() -> None:
    it = _fingerprint("02", {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.8"), DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.2")}, {ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    engineering = _fingerprint("12", {DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.7"), DisciplineAreaCode.ENGINEERING_TECHNOLOGY: Decimal("0.3")}, {ActivityCode.PHYSICAL_ENGINEERING: Decimal("1")})
    economics = _fingerprint("22", {DisciplineAreaCode.ECONOMICS_FINANCE: Decimal("0.7"), DisciplineAreaCode.BUSINESS_MANAGEMENT: Decimal("0.3")}, {ActivityCode.BUSINESS: Decimal("1")})
    data = _fingerprint("32", {DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.6"), DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.4")}, {ActivityCode.DATA: Decimal("1")})

    it_profile = _profile(**{DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")})
    engineering_profile = _profile(**{DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.6"), DisciplineAreaCode.ENGINEERING_TECHNOLOGY: Decimal("0.4")})
    economics_profile = _profile(**{DisciplineAreaCode.ECONOMICS_FINANCE: Decimal("0.7"), DisciplineAreaCode.BUSINESS_MANAGEMENT: Decimal("0.3")})
    data_profile = _profile(**{DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.6"), DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.4")})

    scorer = MatchingService()
    assert scorer.score(it_profile, it).content_fit > scorer.score(it_profile, engineering).content_fit
    assert scorer.score(engineering_profile, engineering).content_fit > scorer.score(engineering_profile, it).content_fit
    assert scorer.score(economics_profile, economics).content_fit > scorer.score(economics_profile, it).content_fit
    assert RankingService().rank(data_profile, (it, data))[0][0].program_code == data.program_code
