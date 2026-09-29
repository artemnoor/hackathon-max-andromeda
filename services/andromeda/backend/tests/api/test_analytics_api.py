from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402, I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_typed_analytics_endpoint_uses_channel_neutral_executor(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'analytics-api.db').as_posix()}"
    run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())
    app = create_app(database_url)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/analytics/query",
                json={
                    "entity": "program",
                    "metrics": ["math_share"],
                    "scope": "program",
                    "scope_ids": ["program:bmstu:09.03.01-02", "program:bmstu:09.03.01-12"],
                    "limit": 2,
                },
            )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "available"
        assert len(payload["rows"]) == 2
        assert payload["rows"][0]["metrics"]["math_share"]["basis"] == "hours"
    finally:
        app.state.engine.dispose()
