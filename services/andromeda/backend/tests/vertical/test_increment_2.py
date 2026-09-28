from __future__ import annotations

from fastapi.testclient import TestClient

from andromeda.api.main import create_app

from conftest import PROGRAM_A, PROGRAM_B


def test_both_real_programs_have_non_empty_curricula(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    client = TestClient(create_app(database_url))

    for program_id in (PROGRAM_A, PROGRAM_B):
        response = client.get(f"/programs/{program_id}/curriculum")
        assert response.status_code == 200
        payload = response.json()
        assert payload["program"]["id"] == program_id
        assert len(payload["items"]) > 0
        assert all("discipline" in item and "hours" in item and "semester" in item for item in payload["items"])
