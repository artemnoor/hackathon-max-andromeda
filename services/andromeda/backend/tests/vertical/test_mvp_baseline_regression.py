from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.ingestion.registry import create_adapter

from conftest import PROGRAM_A, PROGRAM_B


BASELINE_PATH = Path(__file__).parents[1] / "fixtures" / "mvp" / "baseline_manifest.json"


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("university", ("bmstu", "hse"))
def test_fixture_source_manifest_is_stable(university: str) -> None:
    expected = _baseline()["universities"][university]
    adapter = create_adapter(university)
    try:
        captured = adapter.capture(mode="fixture")
        raw, canonical = adapter.parse(captured)
    finally:
        adapter.close()

    assert [str(program.id) for program in canonical.programs] == expected["programIds"]
    assert {
        "curricula": len(canonical.curricula),
        "curriculumItems": sum(len(item.items) for item in canonical.curricula),
        "disciplines": len(canonical.disciplines),
        "admissions": len(canonical.admissions),
        "events": len(canonical.events),
        "campusPoints": len(canonical.campus_points),
        "sourceGaps": len(canonical.source_gaps),
    } == expected["counts"]
    assert [
        {"sourceKind": snapshot.source_kind, "statusCode": snapshot.status_code, "sha256": snapshot.content_sha256}
        for snapshot in raw.snapshots
    ] == expected["snapshots"]


def test_public_fixture_read_paths_keep_stable_business_outcomes(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    client = TestClient(create_app(database_url))

    programs = client.get("/programs")
    assert programs.status_code == 200, programs.text
    assert [item["id"] for item in programs.json()["items"]] == [PROGRAM_A, PROGRAM_B]

    expected_curriculum = {
        PROGRAM_A: {"items": 89, "hours": 13516, "credits": "326.00"},
        PROGRAM_B: {"items": 123, "hours": 15892, "credits": "422.00"},
    }
    for program_id, expected in expected_curriculum.items():
        curriculum = client.get(f"/programs/{program_id}/curriculum")
        assert curriculum.status_code == 200, curriculum.text
        payload = curriculum.json()
        assert len(payload["items"]) == expected["items"]
        assert sum(item["hours"] for item in payload["items"]) == expected["hours"]
        assert sum((float(item["credits"] or 0) for item in payload["items"])) == float(expected["credits"])

    admissions = client.get(f"/programs/{PROGRAM_A}/admissions")
    assert admissions.status_code == 200, admissions.text
    budget = next(item for item in admissions.json()["offerings"] if item["admissionYear"] == 2026 and item["fundingType"] == "budget")
    assert budget["places"] == 318
    assert budget["provenance"][0]["sourceKind"] == "bmstu_major_detail"

    comparison = client.get("/compare", params={"programIds": f"{PROGRAM_A},{PROGRAM_B}"})
    assert comparison.status_code == 200, comparison.text
    assert len(comparison.json()["rows"]) == 145
    assert {row["status"] for row in comparison.json()["rows"]} <= {"both", "only_a", "only_b", "different"}


def test_decision_baseline_is_deterministic_and_revision_bound(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    client = TestClient(create_app(database_url))

    first = client.get("/decision/suggestions")
    second = client.get("/decision/suggestions")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["contextRevision"] == 1
    assert first.json()["suggestions"]

    added = client.post("/decision/shortlist", json={"programId": PROGRAM_A, "expectedRevision": 1})
    assert added.status_code == 200, added.text
    revision = added.json()["context"]["state"]["revision"]
    stale = client.post("/decision/shortlist", json={"programId": PROGRAM_B, "expectedRevision": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"
    assert client.get("/decision/context").json()["state"]["choice"]["shortlistEntries"][0]["programId"] == PROGRAM_A
    assert revision > 1
