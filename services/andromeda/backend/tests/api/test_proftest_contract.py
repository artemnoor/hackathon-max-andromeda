from __future__ import annotations

from decimal import Decimal

from andromeda.api.main import create_app
from andromeda.api.schemas.proftest import ProftestSubmissionRequest


def test_http_contract_uses_camel_case_and_forbids_extra_fields() -> None:
    request = ProftestSubmissionRequest.model_validate({"answers": [{"questionId": "q", "optionIds": ["a"], "intensity": Decimal("0.5")}], "adaptiveAnswers": []})

    assert request.answers[0].question_id == "q"
    assert request.model_dump(by_alias=True)["adaptiveAnswers"] == []


def test_legacy_proftest_routes_are_explicitly_deprecated_in_openapi() -> None:
    schema = create_app("sqlite:///./data/proftest-contract-openapi.db").openapi()

    for path, method in (
        ("/proftest/questions", "get"),
        ("/proftest/preview", "post"),
        ("/proftest/results", "post"),
    ):
        operation = schema["paths"][path][method]
        assert operation["deprecated"] is True
        assert "session" in operation["description"].lower()

    for path, method in (
        ("/proftest/sessions", "post"),
        ("/proftest/sessions/current", "get"),
        ("/proftest/sessions/current/next", "post"),
        ("/proftest/sessions/current/complete", "post"),
    ):
        assert schema["paths"][path][method].get("deprecated") is not True
