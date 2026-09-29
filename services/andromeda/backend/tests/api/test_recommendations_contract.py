from __future__ import annotations

from andromeda.api.main import create_app


def test_openapi_exposes_strict_recommendation_contract() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    operation = document["paths"]["/recommendations"]["post"]
    request_schema = document["components"]["schemas"]["RecommendationRequest"]
    response_schema = document["components"]["schemas"]["RecommendationsResponse"]

    assert operation["operationId"] == "recommend_recommendations_post"
    assert request_schema["additionalProperties"] is False
    assert response_schema["additionalProperties"] is False
    assert "profile" in request_schema["required"]
