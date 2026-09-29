from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_admin_ops_vertical_contract_exposes_quality_metadata_without_raw_sources(tmp_path: Path, monkeypatch) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admin-ops-vertical-contract.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)

    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "vertical-contract-key")
    client = TestClient(create_app(database_url))
    headers = {"X-Andromeda-Ops-Key": "vertical-contract-key"}
    listing = client.get("/ops/ingestion/runs", headers=headers)
    assert listing.status_code == 200
    run_id = listing.json()["items"][0]["id"]
    detail = client.get(f"/ops/ingestion/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    payload = detail.json()["run"]
    assert payload["sourceHashes"]
    assert payload["sourceKinds"]
    assert payload["sourceCount"] == len(raw.snapshots)
    assert payload["programCount"] == len(canonical.programs)
    assert payload["eventCount"] == len(canonical.events)
    assert payload["campusPointCount"] == len(canonical.campus_points)
    assert all(field not in detail.text for field in ("body", "payload_json", "cookie", "password"))
