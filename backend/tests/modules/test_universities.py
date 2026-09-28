from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.modules.universities.contracts.public import Direction


def test_direction_identity_is_derived_from_code() -> None:
    with pytest.raises(ValidationError):
        Direction(
            id="direction:09.03.02",
            university_id="university:bmstu",
            code="09.03.01",
            name="Информатика",
            education_level="bachelor",
        )
