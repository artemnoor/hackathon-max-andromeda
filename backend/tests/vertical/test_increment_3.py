from __future__ import annotations

from fastapi.testclient import TestClient

from andromeda.api.main import create_app

from conftest import PROGRAM_A, PROGRAM_B


def test_compare_returns_typed_rows_and_statuses(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    response = TestClient(create_app(database_url)).get(f"/compare?programIds={PROGRAM_A},{PROGRAM_B}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["programA"]["id"] == PROGRAM_A
    assert payload["programB"]["id"] == PROGRAM_B
    assert payload["rows"]
    assert {row["status"] for row in payload["rows"]} <= {"both", "only_a", "only_b", "different"}
    assert all("discipline" in row and "semester" in row and "status" in row for row in payload["rows"])


def test_compare_rejects_invalid_query_with_error_contract(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    response = TestClient(create_app(database_url)).get("/compare?programIds=not-an-id")

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Request validation failed",
        "details": [{"path": "query", "message": "Value error, programIds must contain exactly two distinct program ids", "type": "value_error"}],
    }
