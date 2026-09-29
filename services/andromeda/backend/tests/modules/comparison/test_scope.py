from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from andromeda.modules.comparison.contracts.public import ComparisonRequest
from andromeda.modules.comparison.services.compare_programs import CompareProgramsService
from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.enums import ComparisonScope, EducationLevel


def _program(code: str) -> Program:
    return Program(
        id=f"program:{code}", direction_id="direction:09.03.01", code=code, name=code,
        education_year=2026, study_plan_url="https://example.com/plan.pdf", source_url="https://example.com/",
    )


def _discipline(name: str) -> Discipline:
    normalized = name.casefold()
    return Discipline(id=f"discipline:{sha256(normalized.encode()).hexdigest()[:16]}", name=name, normalized_name=normalized)


def _curriculum(program: Program, item: CurriculumItem) -> Curriculum:
    return Curriculum(
        id=f"curriculum:{program.code}-2026", program_id=program.id, education_year=2026,
        source_url="https://example.com/plan.pdf", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), items=(item,),
    )


def test_comparison_scope_filters_by_semester() -> None:
    a = _program("09.03.01-02")
    b = _program("09.03.01-12")
    math = _discipline("Математика")
    item_a = CurriculumItem(id=f"curriculum-item:{a.id}:{math.id}:2", discipline_id=math.id, source_name="Математика", semester=2, hours=10, credits=Decimal("1.00"))
    item_b = CurriculumItem(id=f"curriculum-item:{b.id}:{math.id}:2", discipline_id=math.id, source_name="Математика", semester=2, hours=20, credits=Decimal("2.00"))

    class Programs:
        def get(self, program_id):
            return {a.id: a, b.id: b}.get(program_id)

    class Curricula:
        def get_for_program(self, program_id):
            return {a.id: _curriculum(a, item_a), b.id: _curriculum(b, item_b)}.get(program_id)

    class Disciplines:
        def get(self, discipline_id):
            return math if discipline_id == math.id else None

    result = CompareProgramsService(Programs(), Curricula(), Disciplines()).compare(
        ComparisonRequest(program_a_id=a.id, program_b_id=b.id, scope=ComparisonScope.SEMESTER, semester=2)
    )
    assert len(result.rows) == 1
    assert result.rows[0].hours_delta == -10
