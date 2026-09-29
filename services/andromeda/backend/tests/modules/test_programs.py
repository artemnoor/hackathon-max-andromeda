from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.modules.programs.contracts.public import Program


def test_program_rejects_a_code_from_another_direction() -> None:
    with pytest.raises(ValidationError):
        Program(
            id="program:09.03.01-02",
            direction_id="direction:09.03.02",
            code="09.03.01-02",
            name="Информатика",
            education_year=2026,
            study_plan_url="https://example.com/plan.pdf",
            source_url="https://example.com/program",
        )
