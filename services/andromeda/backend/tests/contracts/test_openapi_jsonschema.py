from __future__ import annotations

from jsonschema import Draft202012Validator, RefResolver
from fastapi.testclient import TestClient

from andromeda.api.main import create_app

from conftest import PROGRAM_A, PROGRAM_B


def test_api_responses_validate_against_generated_openapi_schema(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    app = create_app(database_url)
    client = TestClient(app)
    document = app.openapi()
    resolver = RefResolver.from_schema(document)

    cases = (
        ("/programs/{id}", "/programs/program:09.03.01-02", "get", 200),
        ("/programs/{id}/curriculum", f"/programs/{PROGRAM_A}/curriculum", "get", 200),
        ("/compare", f"/compare?programIds={PROGRAM_A},{PROGRAM_B}", "get", 200),
    )
    for schema_path, request_path, method, status in cases:
        response = client.request(method, request_path)
        assert response.status_code == status
        response_schema = document["paths"][schema_path][method]["responses"][str(status)]["content"]["application/json"]["schema"]
        Draft202012Validator(response_schema, resolver=resolver).validate(response.json())


def test_openapi_publishes_shared_enums_and_required_contract_fields() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    schemas = document["components"]["schemas"]
    assert schemas["AssessmentType"]["enum"] == ["exam", "credit", "graded_credit", "coursework", "course_project", "state_exam"]
    assert schemas["CompareStatus"]["enum"] == ["both", "only_a", "only_b", "different"]
    assert set(schemas["ProgramResponse"]["required"]) == {"program"}
    assert "programIds" in document["paths"]["/compare"]["get"]["parameters"][0]["name"]
    assert document["paths"]["/programs"]["get"]["responses"]["422"]["description"] == "Unprocessable Entity"
