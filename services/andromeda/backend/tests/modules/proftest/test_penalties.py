from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, UserProfile
from andromeda.modules.proftest.services.matching import MatchingService


def test_penalty_is_proportional_to_area_share() -> None:
    profile = UserProfile(negative_weights={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("1")}, confidence=Confidence(value=Decimal("1"), answered_base=1, answered_adaptive=0))
    def fingerprint(share: str) -> ProgramFingerprint:
        physics = Decimal(share)
        computer = Decimal("1") - physics
        return ProgramFingerprint(program_id="program:09.03.01-02", program_code="09.03.01-02", program_name="Test", basis="hours", total_hours=100, total_credits=Decimal("10"), total_workload=Decimal("100"), area_hours={DisciplineAreaCode.PHYSICS_ASTRONOMY: physics * 100, DisciplineAreaCode.COMPUTER_SCIENCE_DATA: computer * 100}, area_share={DisciplineAreaCode.PHYSICS_ASTRONOMY: physics, DisciplineAreaCode.COMPUTER_SCIENCE_DATA: computer}, semester_distribution={"1": Decimal("1")}, activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")})
    low = MatchingService().score(profile, fingerprint("0.2"))
    high = MatchingService().score(profile, fingerprint("0.8"))
    assert high.breakdown.anti_penalty > low.breakdown.anti_penalty
