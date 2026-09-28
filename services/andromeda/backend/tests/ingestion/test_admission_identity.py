from __future__ import annotations

import pytest

from andromeda.ingestion.universities.bmstu.identity import resolve_programs
from andromeda.modules.programs.contracts.public import Program


def _program(code: str, name: str) -> Program:
    return Program(
        id=f"program:{code}",
        direction_id="direction:09.03.01",
        code=code,
        name=name,
        education_year=2026,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )


def test_direction_scope_resolves_only_profiles_under_that_direction() -> None:
    programs = (_program("09.03.01-02", "Профиль A"), _program("09.03.01-12", "Профиль B"))
    assert resolve_programs("09.03.01", source_name=None, scope="direction", programs=programs) == programs


def test_program_scope_requires_exact_profile_identity() -> None:
    programs = (_program("09.03.01-02", "Профиль A"), _program("09.03.01-12", "Профиль B"))
    assert resolve_programs("09.03.01", source_name="Профиль B", scope="program", programs=programs) == (programs[1],)
    with pytest.raises(Exception, match="ambiguous program identity"):
        resolve_programs("09.03.01", source_name=None, scope="program", programs=programs)
