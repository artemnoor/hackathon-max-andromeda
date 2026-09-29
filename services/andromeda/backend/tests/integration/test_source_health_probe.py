from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from source_health import probe_university  # noqa: E402


def test_source_health_fixture_probe_is_read_only_and_keeps_diagnostics() -> None:
    result = probe_university(university="hse", mode="fixture", database_url=None)

    assert result.run_id.startswith("probe:")
    assert result.status == "degraded"
    assert result.source_hashes
    assert result.source_gap_count == 4
    assert result.critical_gap_count == 0
    source = Path(__file__).parents[2] / "scripts" / "source_health.py"
    text = source.read_text(encoding="utf-8")
    assert "run_university" not in text
    assert ".ingest(" not in text
