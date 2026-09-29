from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.services.catalog import ProftestCatalogService
from andromeda.modules.programs.contracts.public import Program


class FakeCanonicalReader:
    def __init__(self, program: Program, curriculum: Curriculum, discipline: Discipline) -> None:
        self._program = program
        self._curriculum = curriculum
        self._discipline = discipline

    def list_programs(self) -> tuple[Program, ...]:
        return (self._program,)

    def get_curriculum(self, program_id: str) -> Curriculum | None:
        return self._curriculum if program_id == self._program.id else None

    def get_discipline(self, discipline_id: str) -> Discipline | None:
        return self._discipline if discipline_id == self._discipline.id else None


def test_catalog_reader_contract_accepts_only_canonical_module_contracts() -> None:
    program = Program(
        id="program:09.03.01-02",
        direction_id="direction:09.03.01",
        code="09.03.01-02",
        name="Fixture program",
        education_year=2026,
        study_plan_url="https://example.com/plan.pdf",
        source_url="https://example.com/",
    )
    normalized_name = "математика"
    discipline = Discipline(
        id=f"discipline:{sha256(normalized_name.encode()).hexdigest()[:16]}",
        name="Математика",
        normalized_name=normalized_name,
        area_weights=(DisciplineAreaWeight(area=DisciplineAreaCode.MATHEMATICS_STATISTICS, weight=Decimal("1")),),
    )
    item = CurriculumItem(
        id=f"curriculum-item:{program.id}:{discipline.id}:1",
        discipline_id=discipline.id,
        source_name="Математика (источник)",
        semester=1,
        hours=72,
        credits=Decimal("2.00"),
    )
    curriculum = Curriculum(
        id="curriculum:09.03.01-02-2026",
        program_id=program.id,
        education_year=2026,
        source_url="https://example.com/plan.pdf",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=(item,),
    )

    fingerprints = ProftestCatalogService(FakeCanonicalReader(program, curriculum, discipline)).list_fingerprints()

    assert len(fingerprints) == 1
    assert fingerprints[0].program_id == program.id
    assert fingerprints[0].evidence[0].source_name == "Математика (источник)"
