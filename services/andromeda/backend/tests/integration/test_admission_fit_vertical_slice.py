from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def test_andromeda_db_repository_service_api_admission_fit_slice(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admission-fit-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    client = TestClient(create_app(database_url))

    admissions = client.get("/programs/program:09.03.01-02/admissions").json()
    offering = next(item for item in admissions["offerings"] if item["exams"])
    response = client.post(
        "/programs/program:09.03.01-02/admission-fit",
        json={
            "offeringId": offering["id"],
            "applicant": {
                "scores": [
                    {"subject": exam["subject"], "score": 90}
                    for exam in offering["exams"]
                ]
            },
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["programId"] == "program:bmstu:09.03.01-02"
    assert result["reasons"]
    assert any(
        provenance["sourceKind"] == "bmstu_major_detail"
        for reason in result["reasons"]
        for provenance in reason["provenance"]
    )
