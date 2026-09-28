from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, ProgramFingerprint, UserProfile


def fingerprint(
    code: str = "09.03.01-02",
    *,
    computer: str = "0.8",
    mathematics: str = "0.2",
    physics: str = "0",
    activities: dict[ActivityCode, Decimal] | None = None,
) -> ProgramFingerprint:
    areas = {
        DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal(computer),
        DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal(mathematics),
    }
    if Decimal(physics) > 0:
        areas[DisciplineAreaCode.PHYSICS_ASTRONOMY] = Decimal(physics)
    total = sum(areas.values(), Decimal("0"))
    areas = {area: share / total for area, share in areas.items()}
    return ProgramFingerprint(
        program_id=f"program:{code}",
        program_code=code,
        program_name=f"Программа {code}",
        basis="hours",
        total_hours=100,
        total_credits=Decimal("10"),
        total_workload=Decimal("100"),
        area_hours={area: share * 100 for area, share in areas.items()},
        area_share=areas,
        semester_distribution={"1": Decimal("1")},
        activity_signals=activities or {ActivityCode.SOFTWARE_CREATION: Decimal("1")},
    )


def fingerprint_from_areas(
    code: str,
    areas: dict[DisciplineAreaCode, Decimal],
    activities: dict[ActivityCode, Decimal],
) -> ProgramFingerprint:
    total = sum(areas.values(), Decimal("0"))
    normalized = {area: share / total for area, share in areas.items()}
    return ProgramFingerprint(
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
        activity_signals=activities,
    )


def profile(
    *,
    subject: dict[DisciplineAreaCode, Decimal] | None = None,
    activity: dict[ActivityCode, Decimal] | None = None,
    negative: dict[DisciplineAreaCode, Decimal] | None = None,
) -> UserProfile:
    return UserProfile(
        preferred_subject_weights=subject or {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        preferred_activity_weights=activity or {},
        negative_weights=negative or {},
        confidence=Confidence(value=Decimal("1"), answered_base=6, answered_adaptive=0),
    )
