from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.ingestion.contracts.raw import RawSourceSnapshot
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
BENEFIT_FIXTURE_DIR = Path(__file__).parents[1] / "ingestion" / "fixtures" / "bmstu" / "admission_benefits"
RUN_ID = "ingest:" + "f" * 32
PROGRAM_ID = "program:bmstu:09.03.01-02"


def _benefit_snapshot(file_name: str, document_kind: str, *, source_prefix: str = "bmstu_admission_document") -> RawSourceSnapshot:
    payload = json.loads((BENEFIT_FIXTURE_DIR / file_name).read_text(encoding="utf-8"))
    url = payload["source_url"]
    return RawSourceSnapshot(
        source_kind=f"{source_prefix}:{document_kind}",
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="application/json",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=payload["content_sha256"],
        body=(BENEFIT_FIXTURE_DIR / file_name).read_bytes(),
        access_mode="fixture",
    )


def _rules_snapshot() -> RawSourceSnapshot:
    return _benefit_snapshot("rules-2026.extract.json", "rules")


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(mode="fixture", fixture_dir=TRACER_FIXTURE_DIR)
        captured = CapturedSources(
            snapshots=(
                *captured.snapshots,
                _rules_snapshot(),
                _benefit_snapshot("appendix-5-1-extract.json", "appendix_5_1"),
                _benefit_snapshot("appendix-5-2-extract.json", "appendix_5_2"),
                _benefit_snapshot("appendix-5-3-extract.json", "appendix_5_3"),
                _benefit_snapshot("appendix-5-4-extract.json", "appendix_5_4"),
                _benefit_snapshot("appendix-5-5-extract.json", "appendix_5_5"),
                _benefit_snapshot("appendix-6-extract.json", "appendix_6"),
                _benefit_snapshot(
                    "shag-engineering.html.extract.json",
                    "engineering",
                    source_prefix="bmstu_olympiad_profile",
                ),
                _benefit_snapshot(
                    "shag-programming.html.extract.json",
                    "programming",
                    source_prefix="bmstu_olympiad_profile",
                ),
            ),
            source_gaps=captured.source_gaps,
        )
        raw, canonical = adapter.parse(captured, source_run_id=RUN_ID, admission_year=2026)
    finally:
        adapter.close()

    database_url = f"sqlite:///{(tmp_path / 'admission-benefits-vertical.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyIngestionRepository(engine)
    repository.start_run(run_id=RUN_ID, university_id=canonical.university.id)
    repository.ingest(raw, canonical, run_id=RUN_ID)
    engine.dispose()
    return TestClient(create_app(database_url))


def test_official_fixture_reaches_catalog_and_provenance_api(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/universities/university:bmstu/admission-benefits?year=2026")

    assert response.status_code == 200
    payload = response.json()
    assert payload["admissionYear"] == 2026
    assert payload["coverage"]["recordsNormalized"] > 0
    assert payload["coverage"]["sourceHashes"]
    assert payload["benefitRules"]
    assert payload["individualAchievementPolicy"]["rules"]
    evidence = payload["benefitRules"][0]["provenance"]
    assert evidence["source"]["url"].startswith("https://api.www.bmstu.ru/file/")
    assert len(evidence["sourceSnapshotHash"]) == 64
    assert evidence["sourceRunId"] == RUN_ID
    assert evidence["row"] is not None
    shag_olympiad_id = next(
        item["id"]
        for item in payload["olympiads"]
        if "шаг в будущее" in item["officialName"].casefold()
    )
    bvi_rule = next(
        rule
        for rule in payload["benefitRules"]
        if rule["benefitType"] == "bvi"
        and rule["route"] == "olympiad"
        and rule["olympiadId"] == shag_olympiad_id
    )
    assert bvi_rule["validity"]["maxAgeYears"] == 4
    assert any(
        str(subject["minimumScore"]) in {"75", "75.00"}
        for subject in bvi_rule["confirmationSubjects"]
    )
    infochemistry = next(
        rule
        for rule in payload["benefitRules"]
        if rule["benefitType"] == "one_hundred_points"
        and "информатика и вычислительная техника" in rule["sourceText"].casefold()
    )
    assert infochemistry["status"] == "active"
    assert "09.03.01" in {target["value"] for target in infochemistry["scope"]["targets"]}


def test_reverse_queries_and_non_excluded_program_are_source_backed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    catalog = client.get("/universities/university:bmstu/admission-benefits?year=2026").json()
    bvi_rule = next(rule for rule in catalog["benefitRules"] if rule["benefitType"] == "bvi")
    hundred_rule = next(
        rule for rule in catalog["benefitRules"] if rule["benefitType"] == "one_hundred_points"
    )

    bvi_reverse = client.get(
        f"/admission-benefits/olympiads/{bvi_rule['olympiadId']}/programs",
        params={"university_id": "university:bmstu", "year": 2026, "includeReview": True},
    )
    hundred_reverse = client.get(
        f"/admission-benefits/olympiads/{hundred_rule['olympiadId']}/programs",
        params={
            "university_id": "university:bmstu",
            "year": 2026,
            "benefitType": "one_hundred_points",
            "includeReview": True,
        },
    )
    excluded_program = client.get(
        f"/programs/{PROGRAM_ID}/admission-benefits",
        params={"year": 2026},
    )

    assert bvi_reverse.status_code == 200
    assert hundred_reverse.status_code == 200
    assert bvi_reverse.json()["rules"]
    assert hundred_reverse.json()["rules"]
    assert all(rule["provenance"]["sourceSnapshotHash"] for rule in bvi_reverse.json()["rules"])
    assert excluded_program.status_code == 200
    assert excluded_program.json()["rules"]


def test_applicant_request_keeps_historical_bvi_separate_from_eligibility(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        f"/programs/{PROGRAM_ID}/admission-eligibility",
        json={
            "universityId": "university:bmstu",
            "directionCode": "09.03.01",
            "admissionYear": 2026,
            "applicant": {
                "egeScores": [{"subject": "Информатика", "score": 95}],
                "olympiadAchievements": [
                    {
                        "olympiadId": "olympiad:olimpiada-shag-v-budushchee",
                        "resultYear": 2026,
                        "resultType": "winner",
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "review_required"
    assert payload["route"] is None
    assert payload["evaluations"]
    assert not any(item["status"] == "eligible" for item in payload["evaluations"])
    assert payload["effectiveCompetitiveScore"] is None
    assert payload["competitiveScore"]["status"] == "insufficient_data"


def test_source_backed_active_bvi_rule_reaches_program_and_eligibility_api(tmp_path: Path) -> None:
    client = _client(tmp_path)
    catalog = client.get("/universities/university:bmstu/admission-benefits?year=2026").json()
    shag_winner = next(
        rule
        for rule in catalog["benefitRules"]
        if rule["benefitType"] == "bvi"
        and rule["resultType"] == "winner"
        and rule["scope"]["mode"] == "all_except"
    )

    program_rules = client.get(
        f"/programs/{PROGRAM_ID}/admission-benefits",
        params={"year": 2026},
    )
    assert program_rules.status_code == 200
    assert shag_winner["id"] in {rule["id"] for rule in program_rules.json()["rules"]}
    confirmation_subject = shag_winner["confirmationSubjects"][0]["subject"]

    response = client.post(
        f"/programs/{PROGRAM_ID}/admission-eligibility",
        json={
            "universityId": "university:bmstu",
            "directionCode": "09.03.01",
            "admissionYear": 2026,
            "applicant": {
                "egeScores": [{"subject": confirmation_subject, "score": 95}],
                "olympiadAchievements": [
                    {
                        "olympiadId": shag_winner["olympiadId"],
                        "olympiadProfileId": shag_winner["olympiadProfileId"],
                        "resultYear": 2026,
                        "resultType": "winner",
                        "confirmationSubject": confirmation_subject,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "eligible"
    assert payload["route"] == "olympiad"
    matched = [item for item in payload["evaluations"] if item["matchedApplicantFact"] == shag_winner["olympiadId"]]
    assert matched
    assert matched[0]["status"] == "eligible"
    assert not any("confirmation" in gap.casefold() for gap in payload["sourceGaps"])
    assert matched[0]["evidence"][0]["provenance"]["sourceSnapshotHash"] == (
        "f76eb91353b83c0fdf7773fffa768c5d9fde69ade6ff94bb3192f70b29f47941"
    )


def test_special_olympiad_routes_reach_eligibility_api(tmp_path: Path) -> None:
    client = _client(tmp_path)
    catalog = client.get("/universities/university:bmstu/admission-benefits?year=2026").json()
    vosh_rule = next(
        rule
        for rule in catalog["benefitRules"]
        if rule["route"] == "vosh" and rule["benefitType"] == "bvi" and rule["resultType"] == "winner"
    )
    international_rule = next(
        rule
        for rule in catalog["benefitRules"]
        if rule["route"] == "international" and rule["benefitType"] == "bvi"
    )

    response = client.post(
        f"/programs/{PROGRAM_ID}/admission-eligibility",
        json={
            "universityId": "university:bmstu",
            "directionCode": "09.03.01",
            "admissionYear": 2026,
            "applicant": {
                "olympiadAchievements": [
                    {
                        "olympiadId": vosh_rule["olympiadId"],
                        "olympiadProfileId": vosh_rule["olympiadProfileId"],
                        "resultYear": 2026,
                        "resultType": "winner",
                    }
                ]
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "eligible"
    assert payload["route"] == "vosh"
    assert any(item["route"] == "vosh" and item["status"] == "eligible" for item in payload["evaluations"])
    assert international_rule["resultType"] == "team_member"
    assert international_rule["provenance"]["sourceSnapshotHash"] == (
        "d70e0bd66e233d458b4ce1d37856f1460781fdc988a68b66be231cce1e7a0266"
    )
