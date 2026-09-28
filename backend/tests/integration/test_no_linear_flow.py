"""Decision entry points must work without the retired linear funnel."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def _seed_client(tmp_path: Path) -> TestClient:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(
            fixture_dir=fixture_root / "tracer" / "raw",
            event_fixture_dir=fixture_root / "events" / "raw",
            campus_fixture_dir=fixture_root / "campus" / "raw",
        )
    finally:
        adapter.close()

    database_url = f"sqlite:///{(tmp_path / 'no-linear-flow.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
    return TestClient(create_app(database_url))


def test_catalog_compare_admission_and_decision_are_independent_entry_points(tmp_path: Path) -> None:
    client = _seed_client(tmp_path)

    # This fresh guest has no profile and has not visited a route/proftest page.
    context = client.get("/decision/context")
    catalog = client.get("/programs")
    comparison = client.get(
        "/compare",
        params={"programIds": "program:09.03.01-02,program:09.03.01-12", "scope": "semester", "semester": 1},
    )
    admissions = client.get("/programs/program:09.03.01-02/admissions")

    assert context.status_code == 200, context.text
    assert context.json()["preferences"] is None
    assert catalog.status_code == 200, catalog.text
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["rows"]
    assert admissions.status_code == 200, admissions.text

    offering = next(item for item in admissions.json()["offerings"] if item["exams"])
    admission_fit = client.post(
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

    assert admission_fit.status_code == 200, admission_fit.text
    assert admission_fit.json()["dataQuality"] == "complete"
