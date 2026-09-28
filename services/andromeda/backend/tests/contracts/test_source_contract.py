from __future__ import annotations

from pathlib import Path

import pytest

from andromeda.ingestion.universities.bmstu.capture import BmstuSource
from andromeda.ingestion.universities.bmstu.parser.tracer import parse_captured
from andromeda.shared.contracts.errors import ContractError


def test_missing_selected_curriculum_is_excluded_with_source_gap() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    source = BmstuSource()
    try:
        captured = source.capture(mode="fixture", fixture_dir=fixture_dir)
    finally:
        source.close()
    without_second_document = tuple(snapshot for snapshot in captured.snapshots if "mwXCgDtAGpDWdA" not in str(snapshot.requested_url))

    parsed = parse_captured(type(captured)(without_second_document))

    assert {program.code for program in parsed.programs} == {"09.03.01-02"}
    assert all(row.program_code == "09.03.01-02" for row in parsed.curriculum_rows)
    assert any(gap.entity_key == "program:09.03.01-12" for gap in parsed.source_gaps)


def test_duplicate_selected_curriculum_fails_closed() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    source = BmstuSource()
    try:
        captured = source.capture(mode="fixture", fixture_dir=fixture_dir)
    finally:
        source.close()
    duplicate = captured.snapshots + (captured.snapshots[-1],)

    with pytest.raises(ContractError, match="Could not select curriculum document"):
        parse_captured(type(captured)(duplicate))
