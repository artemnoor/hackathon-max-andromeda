from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.api.public_api_v1 import (
    PUBLIC_API_V1_OPERATIONS,
    project_public_api_v1_openapi,
)

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "trace"})
_PUBLIC_PREFIX = "/api/v1"
_ERROR_STATUSES = ("400", "401", "403", "404", "409", "422", "429", "500")


def test_public_v1_openapi_matches_the_exact_operation_allowlist() -> None:
    document = project_public_api_v1_openapi(create_app("sqlite:///:memory:"))
    actual = {
        (method.upper(), path.removeprefix(_PUBLIC_PREFIX))
        for path, path_item in document["paths"].items()
        if path.startswith(f"{_PUBLIC_PREFIX}/")
        for method, operation in path_item.items()
        if method in _HTTP_METHODS and isinstance(operation, dict)
    }

    assert actual == PUBLIC_API_V1_OPERATIONS
    public_operations = [
        operation
        for path, path_item in document["paths"].items()
        if path.startswith(f"{_PUBLIC_PREFIX}/")
        for method, operation in path_item.items()
        if method in _HTTP_METHODS and isinstance(operation, dict)
    ]
    operation_ids = [operation["operationId"] for operation in public_operations]
    assert all(operation_id.startswith("public_v1_") for operation_id in operation_ids)
    assert len(operation_ids) == len(set(operation_ids))
    for operation in public_operations:
        assert operation["x-andromeda-api-surface"] == "public"
        assert operation["x-andromeda-api-version"] == 1
        for status in _ERROR_STATUSES:
            response = operation["responses"][status]
            assert response["content"]["application/json"]["schema"]["$ref"].endswith(
                "/ErrorResponse"
            )
        rate_limit = operation["responses"]["429"]
        assert rate_limit["headers"]["Retry-After"]["schema"] == {"type": "string"}

    assistant = document["paths"]["/api/v1/assistant/query"]["post"]
    assistant_schema_ref = assistant["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assistant_schema = document["components"]["schemas"][assistant_schema_ref.rsplit("/", 1)[-1]]
    assert "interactive" not in assistant_schema["properties"]
    assert assistant["security"][-1] == {}
    assert document["paths"]["/api/v1/auth/session"]["get"]["security"][-1] == {}
    assert document["paths"]["/api/v1/auth/decision/import-guest"]["post"]["security"] == [
        {"AndromedaAuthSession": []}
    ]


def test_internal_routes_stay_outside_public_v1_and_full_docs_remain_available(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(f"sqlite:///{(tmp_path / 'public-docs.db').as_posix()}"))

    full_document = client.get("/openapi.json").json()
    public_document = create_app("sqlite:///:memory:").openapi()
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert "/health/ready" in full_document["paths"]
    assert "/ops/knowledge/review-queue" in full_document["paths"]
    assert "/university-admin/universities/{university_id}/events" in full_document["paths"]
    assert "/analytics/query" in full_document["paths"]
    assert "/proftest/questions" in full_document["paths"]
    assert "/proftest/preview" in full_document["paths"]
    assert "/proftest/results" in full_document["paths"]
    assert "/api/v1/analytics/query" in public_document["paths"]
    assert not any(
        path.startswith(f"{_PUBLIC_PREFIX}/health/ready")
        or path.startswith(f"{_PUBLIC_PREFIX}/ops/")
        or path.startswith(f"{_PUBLIC_PREFIX}/university-admin/")
        or path.startswith(f"{_PUBLIC_PREFIX}/ops/knowledge/")
        for path in public_document["paths"]
    )
    assert "/api/v1/proftest/questions" not in public_document["paths"]
    assert "/api/v1/proftest/preview" not in public_document["paths"]
    assert "/api/v1/proftest/results" not in public_document["paths"]


def test_public_v1_aliases_use_the_existing_fixture_backed_handlers(
    ingested_db: tuple[str, object, object],
) -> None:
    database_url, _, _ = ingested_db
    with TestClient(create_app(database_url)) as client:
        legacy_health = client.get("/health/live")
        public_health = client.get("/api/v1/health/live")
        legacy_programs = client.get("/programs")
        public_programs = client.get("/api/v1/programs")

    assert legacy_health.status_code == public_health.status_code == 200
    assert public_health.json() == legacy_health.json() == {"status": "live"}
    assert legacy_programs.status_code == public_programs.status_code == 200
    assert public_programs.json() == legacy_programs.json()
    assert len(public_programs.json()["items"]) == 2


def test_public_v1_assistant_preserves_guest_cookie_and_query_revision_semantics(
    ingested_db: tuple[str, object, object],
) -> None:
    database_url, _, _ = ingested_db
    query = "Где больше математики между program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12?"
    with TestClient(create_app(database_url)) as client:
        first = client.post("/api/v1/assistant/query", json={"text": query})
        first_payload = first.json()
        second = client.post(
            "/api/v1/assistant/query",
            json={
                "text": query,
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )
        stale = client.post(
            "/api/v1/assistant/query",
            json={
                "text": query,
                "sessionId": first_payload["session_id"],
                "expectedRevision": first_payload["revision"],
            },
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first_payload["state"] == "complete"
    assert first_payload["response"]["template"]
    assert first_payload["session_id"]
    assert second.json()["revision"] > first_payload["revision"]
    assert any(
        cookie.startswith("andromeda_profile_session=")
        for cookie in first.headers.get_list("set-cookie")
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"


def test_data_api_reference_flow_uses_fixture_data_and_deterministic_assistant(
    ingested_db: tuple[str, object, object],
) -> None:
    database_url, _, _ = ingested_db
    with patch.dict(
        os.environ,
        {
            "JEV_ENABLED": "false",
            "JEV_SHADOW_ENABLED": "false",
            "ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED": "true",
        },
    ):
        app = create_app(database_url)

    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "live"}
        universities = client.get("/api/v1/universities")
        assert universities.status_code == 200
        assert any(item["id"] == "university:bmstu" for item in universities.json()["items"])

        catalog = client.get("/api/v1/programs")
        assert catalog.status_code == 200
        program_ids = {item["id"] for item in catalog.json()["items"]}
        assert program_ids == {
            "program:bmstu:09.03.01-02",
            "program:bmstu:09.03.01-12",
        }

        program_a, program_b = sorted(program_ids)
        details = client.get(f"/api/v1/programs/{program_a}")
        assert details.status_code == 200
        selected_program_id = details.json()["program"]["id"]
        assert selected_program_id == program_a

        curriculum = client.get(f"/api/v1/programs/{selected_program_id}/curriculum")
        assert curriculum.status_code == 200
        assert curriculum.json()["program"]["id"] == selected_program_id

        admissions = client.get(f"/api/v1/programs/{selected_program_id}/admissions")
        assert admissions.status_code == 200
        assert admissions.json()["programId"] == selected_program_id

        comparison = client.get(
            "/api/v1/compare",
            params={"programIds": f"{program_a},{program_b}", "scope": "all"},
        )
        assert comparison.status_code == 200
        assert comparison.json()["programA"]["id"] == program_a
        assert comparison.json()["programB"]["id"] == program_b

        assistant = client.post(
            "/api/v1/assistant/query",
            json={"text": "Правда ли, что с 2028 года введут четвертый ЕГЭ?"},
        )
        assert assistant.status_code == 200
        assistant_payload = assistant.json()
        assert assistant_payload["state"] == "complete"
        assert assistant_payload["response"]["response_mode"] == "deterministic"
