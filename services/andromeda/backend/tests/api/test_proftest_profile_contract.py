from __future__ import annotations

from andromeda.api.main import create_app


def test_profile_and_current_recommendation_operations_are_openapi_strict() -> None:
    document = create_app("sqlite:///:memory:").openapi()

    assert set(document["paths"]["/proftest/profile"]) == {"get", "post", "put"}
    assert "get" in document["paths"]["/recommendations/current"]
    snapshot_schema = document["components"]["schemas"]["UserProfileSnapshotResponse"]
    create_schema = document["components"]["schemas"]["UserProfileCreateRequest"]
    update_schema = document["components"]["schemas"]["UserProfileUpdateRequest"]
    assert snapshot_schema["additionalProperties"] is False
    assert create_schema["additionalProperties"] is False
    assert update_schema["additionalProperties"] is False
    assert "expectedRevision" in update_schema["required"]
    assert all("409" in document["paths"]["/proftest/profile"][method]["responses"] for method in ("get", "post", "put"))
