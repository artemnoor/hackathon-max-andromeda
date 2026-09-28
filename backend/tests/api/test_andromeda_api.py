from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import AdmissionOfferingModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
)


def _client(tmp_path: Path) -> TestClient:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=fixture_dir)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def test_program_selector_and_comparison_are_openapi_backed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    programs = client.get("/programs")
    assert programs.status_code == 200
    assert len(programs.json()["items"]) == 2
    comparison = client.get(
        "/compare",
        params={"programIds": "program:bmstu:09.03.01-02,program:bmstu:09.03.01-12", "scope": "semester", "semester": 1},
    )
    assert comparison.status_code == 200
    payload = comparison.json()
    assert payload["scope"] == "semester"
    assert all(row["semester"] == 1 for row in payload["rows"])
    assert "hoursDelta" in payload["rows"][0]
    assert payload["areaBreakdownA"]
    assert sum((Decimal(row["share"]) for row in payload["areaBreakdownA"]), Decimal("0")) == 1
    assert payload["provenance"]
    assert payload["provenance"][0]["contentSha256"]


def test_discipline_area_catalog_and_curriculum_vectors_are_exposed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    areas = client.get("/discipline-areas")
    assert areas.status_code == 200
    assert len(areas.json()["items"]) == 22

    curriculum = client.get("/programs/program:bmstu:09.03.01-02/curriculum")
    assert curriculum.status_code == 200
    discipline = curriculum.json()["items"][0]["discipline"]
    assert discipline["areaWeights"]
    assert discipline["primaryArea"]
    assert sum((Decimal(item["weight"]) for item in discipline["areaWeights"]), Decimal("0")) == 1
    assert curriculum.json()["provenance"]


def test_program_admissions_are_exposed_with_source_backed_offerings(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/programs/program:bmstu:09.03.01-02/admissions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["programId"] == "program:bmstu:09.03.01-02"
    assert payload["program"]["code"] == "09.03.01-02"
    assert payload["offerings"]
    budget = next(item for item in payload["offerings"] if item["admissionYear"] == 2026 and item["fundingType"] == "budget")
    assert budget["places"] == 318
    assert budget["exams"][0]["minimumScore"] == "46.00"
    assert any(item["passingScores"] for item in payload["offerings"])
    assert budget["provenance"][0]["sourceKind"] == "bmstu_major_detail"
    paid = next(item for item in payload["offerings"] if item["admissionYear"] == 2026 and item["fundingType"] == "paid")
    assert paid["tuition"][0]["amount"] == "529000.00"


def test_program_admissions_unknown_program_uses_not_found_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/programs/program:99.99.99-99/admissions")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_program_admissions_exposes_route_aware_numeric_and_bvi_scores(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=fixture_dir)
    finally:
        adapter.close()

    envelope = next(item for item in canonical.admissions if item.program_id == "program:bmstu:09.03.01-02")
    offering = next(item for item in envelope.offerings if item.admission_year == 2026 and item.funding_type.value == "budget")
    source = offering.provenance[0]
    updated_offering = offering.model_copy(
        update={
            "passing_scores": (
                PassingScore(
                    score_type=PassingScoreType.BUDGET,
                    competition_type=AdmissionCompetitionType.TARGETED,
                    score=Decimal("195"),
                    provenance=source,
                ),
                PassingScore(
                    score_type=PassingScoreType.BUDGET,
                    competition_type=AdmissionCompetitionType.SEPARATE_QUOTA,
                    status=PassingScoreStatus.BVI,
                    score=None,
                    provenance=source,
                ),
            )
        }
    )
    updated_envelope = envelope.model_copy(update={"offerings": (updated_offering, *[item for item in envelope.offerings if item.id != offering.id])})
    updated_canonical = canonical.model_copy(
        update={
            "admissions": (updated_envelope, *[item for item in canonical.admissions if item.program_id != envelope.program_id]),
        }
    )
    database_url = f"sqlite:///{(tmp_path / 'route-aware-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, updated_canonical)
    payload = TestClient(create_app(database_url)).get("/programs/program:bmstu:09.03.01-02/admissions").json()

    current = next(item for item in payload["offerings"] if item["id"] == offering.id)
    assert {(item["competitionType"], item["status"], item["score"]) for item in current["passingScores"]} == {
        ("targeted", "numeric", "195.00"),
        ("separate_quota", "bvi", None),
    }
    engine.dispose()


def test_program_admissions_without_source_is_a_stable_empty_response(tmp_path: Path) -> None:
    client = _client(tmp_path)
    with Session(client.app.state.engine) as session:
        session.execute(delete(AdmissionOfferingModel).where(AdmissionOfferingModel.program_id == "program:bmstu:09.03.01-02"))
        session.commit()

    response = client.get("/programs/program:bmstu:09.03.01-02/admissions")

    assert response.status_code == 200
    assert response.json()["programId"] == "program:bmstu:09.03.01-02"
    assert response.json()["offerings"] == []


def test_invalid_comparison_query_returns_strict_error_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/compare", params={"programIds": "program:09.03.01-02"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
