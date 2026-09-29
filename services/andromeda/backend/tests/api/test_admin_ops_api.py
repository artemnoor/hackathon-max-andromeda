from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


OPS_KEY = "test-only-admin-ops-key"


def _database_with_fixture(tmp_path: Path) -> str:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admin-ops-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return database_url


def test_admin_ops_api_is_not_discoverable_without_configured_key(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.delenv("ANDROMEDA_OPS_API_KEY", raising=False)
    client = TestClient(create_app(_database_with_fixture(tmp_path)))
    response = client.get("/ops/ingestion/runs")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert OPS_KEY not in caplog.text


def test_admin_ops_api_exposes_bounded_read_contract_only_with_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    client = TestClient(create_app(database_url))

    headers = {"X-Andromeda-Ops-Key": OPS_KEY}
    listing = client.get("/ops/ingestion/runs", params={"limit": 1}, headers=headers)
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    run_id = payload["items"][0]["id"]

    detail = client.get(f"/ops/ingestion/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    run = detail.json()["run"]
    assert run["status"] == "completed"
    assert run["sourceHashes"]
    assert "body" not in detail.text
    assert "payload_json" not in detail.text

    wrong_key = client.get("/ops/ingestion/runs", headers={"X-Andromeda-Ops-Key": "wrong"})
    invalid_limit = client.get("/ops/ingestion/runs", params={"limit": 101}, headers=headers)
    missing = client.get("/ops/ingestion/runs/ingest:" + "f" * 32, headers=headers)
    assert wrong_key.status_code == 404
    assert invalid_limit.status_code == 422
    assert missing.status_code == 404


def test_admin_ops_retry_uses_fixture_profile_and_creates_audited_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    client = TestClient(create_app(database_url))
    headers = {"X-Andromeda-Ops-Key": OPS_KEY}

    response = client.post("/ops/ingestion/runs/retry", json={"source": "bmstu_fixture"}, headers=headers)

    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["status"] == "completed"
    assert run["sourceKinds"]
    assert "body" not in response.text
    assert "payload_json" not in response.text

    listing = client.get("/ops/ingestion/runs", headers=headers)
    assert listing.json()["total"] == 2
    assert listing.json()["items"][0]["id"] == run["id"]


def test_admin_ops_supports_hse_fixture_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    client = TestClient(create_app(database_url))

    response = client.post(
        "/ops/ingestion/runs/retry",
        json={"source": "hse_fixture", "idempotencyKey": "hse-fixture-test-001"},
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
    )

    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["status"] == "completed"
    assert run["sourceProfile"].startswith("hse:fixture:")
    assert run["sourceRevision"] == "fixture-manifest-v1"
    assert run["qualityStatus"] == "degraded"


def test_admin_ops_retry_idempotency_returns_the_same_audit_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    client = TestClient(create_app(database_url))
    headers = {"X-Andromeda-Ops-Key": OPS_KEY}
    body = {"source": "bmstu_fixture", "idempotencyKey": "bmstu-retry-test-001"}

    first = client.post("/ops/ingestion/runs/retry", json=body, headers=headers)
    second = client.post("/ops/ingestion/runs/retry", json=body, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["run"]["id"] == second.json()["run"]["id"]
    assert client.get("/ops/ingestion/runs", headers=headers).json()["total"] == 2


def test_admin_ops_retry_rejects_when_a_run_is_running(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    from andromeda.infrastructure.database import create_engine_for_url
    from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository

    engine = create_engine_for_url(database_url)
    SqlAlchemyIngestionRepository(engine).start_run(
        university_id="university:bmstu",
        source_profile="bmstu:fixture:fixture-manifest-v1:mvp023.v1",
        source_revision="fixture-manifest-v1",
        configuration_version="mvp023.v1",
    )
    client = TestClient(create_app(database_url))

    response = client.post(
        "/ops/ingestion/runs/retry",
        json={"source": "bmstu_fixture"},
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_admin_ops_live_retry_is_staging_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    database_url = _database_with_fixture(tmp_path)
    client = TestClient(create_app(database_url))

    response = client.post(
        "/ops/ingestion/runs/retry",
        json={"source": "bmstu_live"},
        headers={"X-Andromeda-Ops-Key": OPS_KEY},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "CONTRACT_ERROR"


def test_admin_ops_exposes_privacy_safe_decision_funnel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", OPS_KEY)
    client = TestClient(create_app(_database_with_fixture(tmp_path)))
    response = client.get("/ops/analytics/funnel", headers={"X-Andromeda-Ops-Key": OPS_KEY})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decisionSessions"] == 0
    assert "payload" not in response.text
    assert "scores" not in response.text
