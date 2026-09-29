from __future__ import annotations

from andromeda.ingestion.contracts.raw import RawProgramRecord, SourceLocator
from andromeda.ingestion.universities.bmstu.identity import (
    canonicalize_program_records,
    direction_codes,
    map_source_program_code,
    normalize_source_code,
)


def _program(source_code: str, name: str, plan: str) -> RawProgramRecord:
    return RawProgramRecord(
        code=source_code,
        source_code=source_code,
        name=name,
        direction_code="09.03.01",
        education_level="bachelor",
        education_year=2025,
        study_plan_url=plan,
        source_url="https://api.www.bmstu.ru/majors/example",
        locator=SourceLocator(source_url="https://api.www.bmstu.ru/majors/example"),
    )


def test_identity_normalization_preserves_source_and_is_order_independent() -> None:
    first = _program("09.03.01–02", "Профиль А", "https://disk.yandex.ru/d/a")
    duplicate = _program("09.03.01-02", "Профиль Б", "https://disk.yandex.ru/d/b")

    forward = canonicalize_program_records((first, duplicate))
    reverse = canonicalize_program_records((duplicate, first))

    forward_by_plan = {str(program.study_plan_url): program for program in forward}
    reverse_by_plan = {str(program.study_plan_url): program for program in reverse}
    assert {key: value.code for key, value in forward_by_plan.items()} == {
        key: value.code for key, value in reverse_by_plan.items()
    }
    assert {program.source_code for program in forward} == {"09.03.01–02", "09.03.01-02"}
    assert len({program.code for program in forward}) == 2
    assert all(program.code.startswith("09.03.01-") for program in forward)


def test_identity_helpers_split_directions_and_map_admission_source_code() -> None:
    programs = canonicalize_program_records(
        (
            _program("09.03.01-02", "Профиль А", "https://disk.yandex.ru/d/a"),
            _program("09.03.01-12", "Профиль Б", "https://disk.yandex.ru/d/b"),
        )
    )

    assert normalize_source_code(" 09.03.01—02 ") == "09.03.01-02"
    assert direction_codes("09.03.01 / 40.05.01") == ("09.03.01", "40.05.01")
    assert map_source_program_code("09.03.01–12", "Профиль Б", programs) == "09.03.01-12"
    assert map_source_program_code("09.03.01", None, programs) == "09.03.01"
