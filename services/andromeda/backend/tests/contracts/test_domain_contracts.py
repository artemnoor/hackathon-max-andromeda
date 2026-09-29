from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.modules.curricula.contracts.public import CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.ingestion.contracts.raw import RawCurriculumRow as CanonicalRawCurriculumRow


def test_domain_rejects_invalid_identity_and_numeric_ranges() -> None:
    with pytest.raises(ValidationError):
        Discipline(id="discipline:0000000000000000", name="Math", normalized_name="math")
    with pytest.raises(ValidationError):
        Program(
            id="program:09.03.01-02",
            direction_id="direction:09.03.02",
            code="09.03.01-02",
            name="Program",
            education_year=2026,
            study_plan_url="https://example.com/plan.pdf",
            source_url="https://example.com/program",
        )
    with pytest.raises(ValidationError):
        CurriculumItem(id="item", discipline_id="discipline:0000000000000000", semester=1, hours=1, credits=61)


@pytest.mark.parametrize("raw_model", (CanonicalRawCurriculumRow,))
def test_curriculum_contracts_reject_removed_subject_group(raw_model: type) -> None:
    payload = {
        "program_code": "09.03.01-02",
        "discipline": "Математика",
        "semester": 1,
        "hours": 144,
        "credits": "4",
        "assessment": "экзамен",
        "source_url": "https://example.com/plan.pdf",
        "locator": {"source_url": "https://example.com/plan.pdf", "page": 1, "row": 1},
        "subject_group": "Обязательная часть",
    }

    with pytest.raises(ValidationError):
        raw_model.model_validate(payload)
