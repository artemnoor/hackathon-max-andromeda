from __future__ import annotations

from andromeda.api.main import create_app


def test_admin_ops_openapi_contract_is_protected_and_excludes_raw_fields() -> None:
    document = create_app("sqlite:///:memory:").openapi()
    paths = document["paths"]
    assert set(paths["/ops/ingestion/runs"]) == {"get"}
    assert set(paths["/ops/ingestion/runs/{id}"]) == {"get"}
    assert set(paths["/ops/ingestion/runs/retry"]) == {"post"}
    assert paths["/ops/ingestion/runs"]["get"]["operationId"] == "list_ingestion_runs"
    assert paths["/ops/ingestion/runs/{id}"]["get"]["operationId"] == "get_ingestion_run"
    assert paths["/ops/ingestion/runs/retry"]["post"]["operationId"] == "retry_ingestion_run"
    serialized = str(document)
    assert "payload_json" not in serialized
    assert "source_snapshots" not in serialized
    assert "RawSource" not in serialized
