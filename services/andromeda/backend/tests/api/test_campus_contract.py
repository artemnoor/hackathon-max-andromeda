from __future__ import annotations

from andromeda.api.main import create_app


def test_campus_openapi_has_strict_schemas_and_deterministic_operations() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    assert document["paths"]["/campus/points"]["get"]["operationId"] == "list_campus_points"
    assert document["paths"]["/campus/points/{id}"]["get"]["operationId"] == "get_campus_point"
    assert document["paths"]["/campus/points/{id}/events"]["get"]["operationId"] == "list_campus_point_events"
    assert document["paths"]["/campus/recommendations"]["get"]["operationId"] == "get_campus_recommendations"
    point_schema = document["components"]["schemas"]["CampusPointResponse"]
    detail_schema = document["components"]["schemas"]["CampusPointDetailResponse"]
    assert point_schema["additionalProperties"] is False
    assert detail_schema["additionalProperties"] is False
    assert {"id", "pointType", "name", "universityIds", "eventCount", "provenance"} <= set(point_schema["required"])
    parameters = {parameter["name"] for parameter in document["paths"]["/campus/points"]["get"]["parameters"]}
    assert {"universityId", "departmentId", "programId", "pointType", "limit"} <= parameters
    event_parameters = {parameter["name"] for parameter in document["paths"]["/campus/points/{id}/events"]["get"]["parameters"]}
    assert {"id", "from", "to", "recommended", "limit"} <= event_parameters
