from __future__ import annotations

from andromeda.api.main import create_app


def test_openapi_exposes_strict_admission_fit_operation() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    operation = document["paths"]["/programs/{id}/admission-fit"]["post"]
    request_schema = document["components"]["schemas"]["AdmissionFitRequestBody"]
    response_schema = document["components"]["schemas"]["AdmissionFitResponse"]

    assert operation["operationId"] == "calculate_program_admission_fit_programs__id__admission_fit_post"
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/AdmissionFitRequestBody")
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AdmissionFitResponse")
    assert request_schema["additionalProperties"] is False
    assert response_schema["additionalProperties"] is False
    assert {"offeringId", "applicant"} <= set(request_schema["required"])
    assert {"status", "score", "breakdown", "reasons", "antiReasons", "dataGaps"} <= set(response_schema["required"])
    assert "contentFit" not in response_schema["properties"]


def test_admission_fit_schema_publishes_separate_status_values() -> None:
    document = create_app("sqlite:///:memory:").openapi()

    assert document["components"]["schemas"]["AdmissionFitStatus"]["enum"] == [
        "realistic",
        "borderline",
        "unlikely",
        "insufficient_data",
    ]
