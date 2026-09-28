from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import result_payload, run_ingest  # noqa: E402


def test_fixture_runner_reports_campus_point_count_and_contract_endpoints(tmp_path: Path) -> None:
    result = run_ingest(
        mode="fixture",
        fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw",
        event_fixture_dir=Path(__file__).parents[1] / "fixtures" / "events" / "raw",
        campus_fixture_dir=Path(__file__).parents[1] / "fixtures" / "campus" / "raw",
        database_url=f"sqlite:///{(tmp_path / 'runner-campus.db').as_posix()}",
        program_codes=("09.03.01-02", "09.03.01-12"),
    )
    payload = result_payload(result, "sqlite:///runner-campus.db")
    assert result.campus_point_count == 5
    assert payload["api"]["campusPoints"] == "/campus/points"
    assert payload["api"]["campusRecommendations"] == "/campus/recommendations"
