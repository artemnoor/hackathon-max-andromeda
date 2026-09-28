from pathlib import Path

from andromeda.api.main import create_app


def test_personal_route_openapi_is_read_only_strict_and_has_camel_case_fields(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'openapi.db').as_posix()}"
    schema = create_app(database_url).openapi()
    operation = schema["paths"]["/personal-route"]["get"]

    assert operation["operationId"] == "get_personal_route"
    assert "requestBody" not in operation
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 20

    response_schema = schema["components"]["schemas"]["PersonalRouteResponse"]
    assert {"status", "summary", "recommendations", "steps"} <= set(response_schema["properties"])
    step_schema = schema["components"]["schemas"]["PersonalRouteStepResponse"]
    assert {"programIds", "eventId", "venueId", "startsAt", "point"} <= set(step_schema["properties"])
    assert not {"route", "edges", "geometry", "distance", "directions", "profileId", "revision"} & set(response_schema["properties"])
