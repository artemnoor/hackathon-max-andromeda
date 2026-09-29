from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import IngestRunModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.shared.contracts.errors import ContractError


def test_fixture_ingestion_audit_reaches_protected_api_and_failed_run_is_retained(tmp_path: Path, monkeypatch) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admin-ops-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    successful_run_id = repository.ingest(raw, canonical)

    conflict = canonical.model_copy(
        update={"programs": (canonical.programs[0].model_copy(update={"code": "09.03.01-99"}), *canonical.programs[1:])}
    )
    with pytest.raises(ContractError):
        repository.ingest(raw, conflict)

    with Session(engine) as session:
        runs = session.scalars(select(IngestRunModel).order_by(IngestRunModel.started_at.asc())).all()
        assert [run.status for run in runs] == ["completed", "failed"]
        assert runs[0].id == successful_run_id
        assert runs[0].source_count == len(raw.snapshots)
        assert runs[0].program_count == len(canonical.programs)
        assert runs[0].event_count == len(canonical.events)
        assert runs[0].campus_point_count == len(canonical.campus_points)
        assert runs[1].error_code == "SOURCE_CONTRACT_ERROR"

    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "vertical-admin-ops-key")
    client = TestClient(create_app(database_url))
    headers = {"X-Andromeda-Ops-Key": "vertical-admin-ops-key"}
    failed = client.get("/ops/ingestion/runs", params={"status": "failed"}, headers=headers)
    assert failed.status_code == 200, failed.text
    failed_id = failed.json()["items"][0]["id"]
    detail = client.get(f"/ops/ingestion/runs/{failed_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["errorCode"] == "SOURCE_CONTRACT_ERROR"
    assert "payload_json" not in detail.text
