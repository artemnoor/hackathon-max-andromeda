from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.services.fingerprint import FingerprintBuilder
from andromeda.modules.programs.contracts.public import Program


def _program(code: str) -> Program:
    return Program(id=f"program:{code}", direction_id="direction:09.03.01", code=code, name=code, education_year=2026, study_plan_url="https://example.com/plan.pdf", source_url="https://example.com/")


def _discipline(name: str, area: DisciplineAreaCode, weight: str = "1") -> Discipline:
    normalized = name.casefold()
    return Discipline(
        id=f"discipline:{sha256(normalized.encode()).hexdigest()[:16]}",
        name=name,
        normalized_name=normalized,
        area_weights=(DisciplineAreaWeight(area=area, weight=Decimal(weight)),),
    )


def test_builder_uses_hours_and_preserves_canonical_evidence() -> None:
    program = _program("09.03.01-02")
    math = _discipline("Математика", DisciplineAreaCode.MATHEMATICS_STATISTICS)
    item = CurriculumItem(id=f"curriculum-item:{program.id}:{math.id}:1", discipline_id=math.id, source_name="Математика (углублённо)", semester=1, hours=40, credits=Decimal("4.00"))
    curriculum = Curriculum(id=f"curriculum:{program.code}-2026", program_id=program.id, education_year=2026, source_url="https://example.com/plan.pdf", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), items=(item,))

    fingerprint = FingerprintBuilder().build(program, curriculum, {math.id: math})

    assert fingerprint.basis == "hours"
    assert fingerprint.total_workload == Decimal("40")
    assert fingerprint.area_share == {DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("1.0000")}
    assert fingerprint.evidence[0].source_name == "Математика (углублённо)"
    assert fingerprint.semester_distribution == {"1": Decimal("1.0000")}


def test_builder_falls_back_to_credits_when_hours_are_zero() -> None:
    program = _program("09.03.01-02")
    universal = _discipline("Проект", DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY)
    item = CurriculumItem(id=f"curriculum-item:{program.id}:{universal.id}:1", discipline_id=universal.id, source_name="Проект", semester=1, hours=0, credits=Decimal("3.00"))
    curriculum = Curriculum(id=f"curriculum:{program.code}-2026", program_id=program.id, education_year=2026, source_url="https://example.com/plan.pdf", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), items=(item,))

    fingerprint = FingerprintBuilder().build(program, curriculum, {universal.id: universal})

    assert fingerprint.basis == "credits"
    assert fingerprint.total_workload == Decimal("3.00")


def test_distinctive_subjects_are_catalog_relative() -> None:
    builder = FingerprintBuilder()
    programs = (_program("09.03.01-02"), _program("09.03.01-12"))
    disciplines = [_discipline("Общая математика", DisciplineAreaCode.MATHEMATICS_STATISTICS), _discipline("Уникальная практика", DisciplineAreaCode.COMPUTER_SCIENCE_DATA)]
    fingerprints = []
    for program, discipline in zip(programs, disciplines, strict=True):
        item = CurriculumItem(id=f"curriculum-item:{program.id}:{discipline.id}:1", discipline_id=discipline.id, source_name=discipline.name, semester=1, hours=20, credits=Decimal("2.00"))
        curriculum = Curriculum(id=f"curriculum:{program.code}-2026", program_id=program.id, education_year=2026, source_url="https://example.com/plan.pdf", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), items=(item,))
        fingerprints.append(builder.build(program, curriculum, {discipline.id: discipline}))

    enriched = builder.add_distinctive_subjects(fingerprints)

    assert all(enriched_item.distinctive_subjects for enriched_item in enriched)
    assert enriched[0].distinctive_subjects[0].source_name == "Общая математика"
