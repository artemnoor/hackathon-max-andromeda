from __future__ import annotations

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.shared.contracts.errors import ConflictError, ErrorCode


def test_missing_program_uses_structured_error_contract(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    response = TestClient(create_app(database_url)).get("/programs/program:09.03.01-99")

    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "NOT_FOUND"
    assert isinstance(payload["message"], str)
    assert payload["details"] == []


def test_conflict_error_is_a_strict_public_error_code() -> None:
    error = ConflictError("Profile revision is stale")

    assert error.code is ErrorCode.CONFLICT
    assert error.response().model_dump(mode="json")["code"] == "CONFLICT"
