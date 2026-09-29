from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem


def test_curriculum_contract_preserves_source_name_and_decimal_credits() -> None:
    item = CurriculumItem(
        id="curriculum-item:program:09.03.01-02:discipline:0123456789abcdef:1",
        discipline_id="discipline:0123456789abcdef",
        source_name=" Математика (высшая) ",
        semester=1,
        hours=144,
        credits=Decimal("4.00"),
    )
    curriculum = Curriculum(
        id="curriculum:09.03.01-02-2026",
        program_id="program:09.03.01-02",
        education_year=2026,
        source_url="https://example.com/plan.pdf",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        items=(item,),
    )
    assert curriculum.items[0].source_name == " Математика (высшая) "
    assert curriculum.items[0].credits == Decimal("4.00")
