from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.disciplines.domain.identity import discipline_id_for
from andromeda.modules.program_analytics.services.fingerprint import FingerprintBuilder
from andromeda.modules.proftest.services.fingerprint import FingerprintBuilder as LegacyFingerprintBuilder
from andromeda.modules.programs.contracts.public import Program


def test_shared_builder_matches_legacy_fingerprint_shape() -> None:
    program = Program(
        id="program:09.03.01-02",
        direction_id="direction:09.03.01",
        code="09.03.01-02",
        name="Прикладная информатика",
        education_year=2026,
        study_plan_url="https://example.com/plan.pdf",
        source_url="https://example.com/",
    )
    name = "Математика"
    discipline = Discipline(
        id=discipline_id_for(name.casefold()),
        name=name,
        normalized_name=name.casefold(),
        area_weights=(DisciplineAreaWeight(area=DisciplineAreaCode.MATHEMATICS_STATISTICS, weight=Decimal("1")),),
    )
    item = CurriculumItem(
        id=f"curriculum-item:{program.id}:{discipline.id}:1",
        discipline_id=discipline.id,
        source_name=name,
        semester=1,
        hours=40,
        credits=Decimal("4"),
    )
    curriculum = Curriculum(
        id="curriculum:09.03.01-02-2026",
        program_id=program.id,
        education_year=2026,
        source_url="https://example.com/plan.pdf",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=(item,),
    )
    source = LegacyFingerprintBuilder().build(program, curriculum, {discipline.id: discipline})
    shared = FingerprintBuilder().build(program, curriculum, {discipline.id: discipline})

    assert shared.model_dump(mode="json") == source.model_dump(mode="json")
