from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


PROGRAM_ID = "program:09.03.01-02"


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admission-fit-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def _offering(client: TestClient) -> dict[str, object]:
    payload = client.get(f"/programs/{PROGRAM_ID}/admissions").json()
    return next(item for item in payload["offerings"] if item["admissionYear"] == 2026 and item["fundingType"] == "budget")


def _request(offering: dict[str, object], score: int = 90, *, omit: set[str] | None = None) -> dict[str, object]:
    omitted = omit or set()
    exams = offering["exams"]
    return {
        "offeringId": offering["id"],
        "applicant": {
            "scores": [
                {"subject": exam["subject"], "score": score}
                for exam in exams
                if exam["subject"] not in omitted
            ]
        },
    }


def test_admission_fit_returns_real_source_backed_facts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offering = _offering(client)

    response = client.post(f"/programs/{PROGRAM_ID}/admission-fit", json=_request(offering))

    assert response.status_code == 200
    payload = response.json()
    assert payload["programId"] == "program:bmstu:09.03.01-02"
    assert payload["offeringId"] == offering["id"]
    assert payload["status"] == "realistic"
    assert payload["score"] == 100
    assert payload["breakdown"]["minimumReadiness"]["value"] == "100.00"
    assert payload["dataGaps"]
    assert "contentFit" not in payload
    assert payload["reasons"][0]["provenance"][0]["sourceKind"] == "bmstu_major_detail"
    assert payload["reasons"][0]["provenance"][0]["universityId"] == "university:bmstu"


def test_below_real_minimum_is_unlikely_with_an_anti_reason(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offering = _offering(client)
    first_exam = offering["exams"][0]["subject"]
    request = _request(offering, omit=set())
    request["applicant"]["scores"][0]["score"] = 30

    response = client.post(f"/programs/{PROGRAM_ID}/admission-fit", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unlikely"
    assert any(reason["subject"] == first_exam for reason in payload["antiReasons"])


def test_missing_scores_are_insufficient_data_and_not_a_fake_zero(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offering = _offering(client)
    request = _request(offering, omit={exam["subject"] for exam in offering["exams"][1:]})

    response = client.post(f"/programs/{PROGRAM_ID}/admission-fit", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_data"
    assert payload["dataQuality"] == "partial"
    assert len(payload["dataGaps"]) >= 2


def test_api_keeps_strict_validation_and_not_found_contracts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offering = _offering(client)
    request = _request(offering)
    request["unexpected"] = True

    extra = client.post(f"/programs/{PROGRAM_ID}/admission-fit", json=request)
    unknown_offering = client.post(
        f"/programs/{PROGRAM_ID}/admission-fit",
        json={"offeringId": "admission-offering:missing", "applicant": {"scores": []}},
    )
    unknown_program = client.post(
        "/programs/program:99.99.99-99/admission-fit",
        json={"offeringId": offering["id"], "applicant": {"scores": []}},
    )

    assert extra.status_code == 422
    assert extra.json()["code"] == "VALIDATION_ERROR"
    assert unknown_offering.status_code == 404
    assert unknown_offering.json()["code"] == "NOT_FOUND"
    assert unknown_program.status_code == 404
    assert unknown_program.json()["code"] == "NOT_FOUND"
