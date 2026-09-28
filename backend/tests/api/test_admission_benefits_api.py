from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.api.schemas.admission_benefits import (
    ApplicantAdmissionFactsRequest,
    admission_facts,
)
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
BENEFIT_FIXTURE_DIR = Path(__file__).parents[1] / "ingestion" / "fixtures" / "bmstu" / "admission_benefits"
RUN_ID = "ingest:" + "c" * 32
PROGRAM_ID = "program:bmstu:09.03.01-02"


def _benefit_snapshot(file_name: str, document_kind: str) -> RawSourceSnapshot:
    payload = json.loads((BENEFIT_FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    url = payload["source_url"]
    return RawSourceSnapshot(
        source_kind=f"bmstu_admission_document:{document_kind}",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=payload["content_sha256"],
        body=(BENEFIT_FIXTURE_DIR / file_name).read_bytes(),
        access_mode="fixture",
    )


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(mode="fixture", fixture_dir=TRACER_FIXTURE_DIR)
        captured = CapturedSources(
            snapshots=(
                *captured.snapshots,
                _benefit_snapshot("appendix-5-1-extract.json", "appendix_5_1"),
                _benefit_snapshot("appendix-5-3-extract.json", "appendix_5_3"),
                _benefit_snapshot("appendix-6-extract.json", "appendix_6"),
            ),
            source_gaps=captured.source_gaps,
        )
        raw, canonical = adapter.parse(captured, source_run_id=RUN_ID, admission_year=2026)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'admission-benefits-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.start_run(run_id=RUN_ID, university_id=canonical.university.id)
    repository.ingest(raw, canonical, run_id=RUN_ID)
    engine.dispose()
    return TestClient(create_app(database_url))


def test_catalog_and_reverse_benefit_queries_return_provenance(tmp_path: Path) -> None:
    client = _client(tmp_path)
    catalog = client.get("/universities/university:bmstu/admission-benefits?year=2026")
    reverse = client.get(
        "/admission-benefits/olympiads/olympiad:olimpiada-shag-v-budushchee/programs?university_id=university:bmstu&year=2026"
    )
    assert catalog.status_code == 200
    assert catalog.json()["coverage"]["recordsNormalized"] > 0
    assert catalog.json()["benefitRules"][0]["provenance"]["sourceSnapshotHash"]
    achievement_policy = catalog.json()["individualAchievementPolicy"]
    assert Decimal(achievement_policy["globalMaxPoints"]) == 10
    assert achievement_policy["defaultCombinationPolicy"] == "additive"
    gto_rules = [
        rule
        for rule in achievement_policy["rules"]
        if rule["provenance"]["row"] == 5
    ]
    assert {Decimal(rule["points"]) for rule in gto_rules} == {3, 4, 5}
    note_four = next(
        condition
        for rule in gto_rules
        for condition in rule["conditions"]
        if condition["normalizedValue"] == "appendix_6_note:4"
    )
    assert note_four["provenance"]["page"] == 8
    assert "document_note=4" in note_four["provenance"]["source"]["locator"]
    assert reverse.status_code == 200


def test_program_eligibility_is_typed_and_does_not_use_historical_bvi(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        f"/programs/{PROGRAM_ID}/admission-eligibility",
        json={
            "universityId": "university:bmstu",
            "directionCode": "09.03.01",
            "admissionYear": 2026,
            "applicant": {"olympiadAchievements": []},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"insufficient_data", "not_eligible", "review_required"}
    assert "sourceGaps" in payload


def test_invalid_applicant_contract_uses_existing_validation_error(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        f"/programs/{PROGRAM_ID}/admission-eligibility",
        json={
            "universityId": "university:bmstu",
            "directionCode": "not-a-direction",
            "admissionYear": 2026,
            "applicant": {},
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_applicant_confirmation_facts_are_typed_and_preserved() -> None:
    request = ApplicantAdmissionFactsRequest.model_validate(
        {
            "olympiadAchievements": [
                {
                    "olympiadId": "olympiad:step-in-future",
                    "olympiadProfileId": "olympiad-profile:engineering",
                    "resultYear": 2024,
                    "resultType": "prize_winner",
                    "confirmationSubject": "физика",
                }
            ],
            "confirmationCategory": "territorial_exception",
        }
    )

    facts = admission_facts(request)

    assert facts.confirmation_category.value == "territorial_exception"
    assert facts.olympiad_achievements[0].confirmation_subject == "физика"
