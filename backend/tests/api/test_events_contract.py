from __future__ import annotations

from andromeda.api.main import create_app


def test_events_openapi_has_strict_schemas_and_deterministic_operations() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    assert document["paths"]["/events"]["get"]["operationId"] == "list_events"
    assert document["paths"]["/events/{id}"]["get"]["operationId"] == "get_event"
    response_schema = document["components"]["schemas"]["EventResponse"]
    assert response_schema["additionalProperties"] is False
    assert {"id", "title", "kind", "format", "startsAt", "universityIds", "provenance"} <= set(response_schema["required"])
    parameters = {parameter["name"] for parameter in document["paths"]["/events"]["get"]["parameters"]}
    assert {"from", "to", "kind", "format", "universityId", "departmentId", "programId", "recommended", "limit"} <= parameters
