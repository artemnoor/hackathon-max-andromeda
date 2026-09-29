from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import result_payload, run_ingest, selected_program_codes


def test_fixture_runner_reports_event_count_and_endpoint(tmp_path: Path) -> None:
    result = run_ingest(
        mode="fixture",
        fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw",
        event_fixture_dir=Path(__file__).parents[1] / "fixtures" / "events" / "raw",
        database_url=f"sqlite:///{(tmp_path / 'runner.db').as_posix()}",
        program_codes=("09.03.01-02", "09.03.01-12"),
    )
    payload = result_payload(result, "sqlite:///runner.db")
    assert payload["eventCount"] == 5
    assert payload["campusPointCount"] == 5
    assert payload["api"]["events"] == "/events"
    assert payload["api"]["campusPoints"] == "/campus/points"


@pytest.mark.parametrize(
    ("program_codes", "program_ids"),
    [
        (("09.03.01-02",), None),
        (None, ("program:09.03.01-02",)),
    ],
    ids=("program-code", "program-id"),
)
def test_fixture_runner_preserves_single_program_scope_for_events(
    tmp_path: Path,
    program_codes: tuple[str, ...] | None,
    program_ids: tuple[str, ...] | None,
) -> None:
    selected = selected_program_codes(program_codes, program_ids)
    result = run_ingest(
        mode="fixture",
        fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw",
        event_fixture_dir=Path(__file__).parents[1] / "fixtures" / "events" / "raw",
        database_url=f"sqlite:///{(tmp_path / f'runner-subset-{selected[0]}.db').as_posix()}",
        program_codes=selected,
    )

    assert result.program_ids == ("program:bmstu:09.03.01-02",)
    assert result.event_count == 3
