from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


PROGRAM_A = "program:bmstu:09.03.01-02"
PROGRAM_B = "program:bmstu:09.03.01-12"


def _client(tmp_path: Path) -> TestClient:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=fixture_dir)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'decision-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def test_decision_context_and_suggestions_are_available_without_proftest(tmp_path: Path) -> None:
    client = _client(tmp_path)

    context = client.get("/decision/context")
    assert context.status_code == 200, context.text
    assert context.json()["state"]["revision"] == 1
    first = client.get("/decision/suggestions")
    second = client.get("/decision/suggestions")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert first.json()["contextRevision"] == 1
    assert first.json()["missingData"]


def test_shortlist_mutations_use_revision_and_never_hide_explicit_choice(tmp_path: Path) -> None:
    client = _client(tmp_path)

    added = client.post(
        "/decision/shortlist",
        json={"programId": PROGRAM_A, "role": "primary", "expectedRevision": 1},
    )
    assert added.status_code == 200, added.text
    assert added.json()["changed"] is True
    revision = added.json()["context"]["state"]["revision"]

    stale = client.post(
        "/decision/shortlist",
        json={"programId": PROGRAM_B, "role": "alternative", "expectedRevision": 1},
    )
    assert stale.status_code == 409, stale.text

    removed = client.request(
        "DELETE",
        f"/decision/shortlist/{PROGRAM_A}",
        json={"expectedRevision": revision},
    )
    assert removed.status_code == 200, removed.text
    removed_revision = removed.json()["context"]["state"]["revision"]
    restored = client.post(
        f"/decision/programs/{PROGRAM_A}/restore",
        json={"expectedRevision": removed_revision},
    )
    assert restored.status_code == 200, restored.text
    entry = restored.json()["context"]["state"]["choice"]["shortlistEntries"][0]
    assert entry["programId"] == PROGRAM_A
    assert entry["state"] == "active"


def test_decision_suggestions_report_source_backed_constraint_outcomes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    updated = client.put(
        "/decision/constraints",
        json={
            "constraints": {
                "admissionYear": 2026,
                "fundingPreference": "paid",
                "studyForm": "full_time",
                "maxTuition": 100000,
                "location": "Москва",
            },
            "expectedRevision": 1,
        },
    )
    assert updated.status_code == 200, updated.text

    suggestions = client.get("/decision/suggestions")
    assert suggestions.status_code == 200, suggestions.text
    candidates = (
        suggestions.json()["primaryCandidates"]
        + suggestions.json()["alternativeCandidates"]
        + suggestions.json()["ineligibleCandidates"]
        + suggestions.json()["insufficientDataCandidates"]
    )
    assert candidates
    outcomes = {item["dimension"]: item for item in candidates[0]["constraintOutcomes"]}
    assert outcomes["admission_year"]["applicability"] == "applied"
    assert outcomes["funding"]["applicability"] == "applied"
    assert outcomes["study_form"]["applicability"] == "applied"
    assert outcomes["max_tuition"]["applicability"] == "applied"
    assert outcomes["location"]["satisfied"] is True


def test_final_choice_requires_explicit_shortlist_entry_and_survives_reopen(tmp_path: Path) -> None:
    client = _client(tmp_path)
    rejected = client.post("/decision/final-choice", json={"programId": PROGRAM_A, "expectedRevision": 1})
    assert rejected.status_code == 400, rejected.text

    added = client.post("/decision/shortlist", json={"programId": PROGRAM_A, "expectedRevision": 1})
    revision = added.json()["context"]["state"]["revision"]
    selected = client.post("/decision/final-choice", json={"programId": PROGRAM_A, "expectedRevision": revision})
    assert selected.status_code == 200, selected.text
    assert selected.json()["context"]["state"]["selectedProgramId"] == PROGRAM_A
    assert selected.json()["context"]["metadata"]["status"] == "finalized"

    reopened = client.request("DELETE", "/decision/final-choice", json={"expectedRevision": selected.json()["context"]["state"]["revision"]})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["context"]["state"]["selectedProgramId"] is None


def test_unknown_program_is_not_accepted_into_shortlist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/decision/shortlist",
        json={"programId": "program:09.03.01-99", "expectedRevision": 1},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_decision_context_isolated_between_anonymous_sessions(tmp_path: Path) -> None:
    # The database is shared intentionally; each client receives its own
    # profile-session cookie and therefore a separate owner key.
    first = _client(tmp_path)
    second = TestClient(create_app(first.app.state.settings.database_url))

    added = first.post(
        "/decision/shortlist",
        json={"programId": PROGRAM_A, "expectedRevision": 1},
    )
    assert added.status_code == 200, added.text
    isolated = second.get("/decision/context")

    assert isolated.status_code == 200, isolated.text
    assert isolated.json()["state"]["choice"]["shortlistEntries"] == []


def test_decision_routes_and_contract_schemas_are_in_openapi(tmp_path: Path) -> None:
    document = create_app(f"sqlite:///{(tmp_path / 'openapi.db').as_posix()}").openapi()
    paths = document["paths"]

    assert "/decision/context" in paths
    assert "/decision/suggestions" in paths
    assert "/decision/shortlist/{program_id}" in paths
    assert "/decision/suggestions/{program_id}/accept" in paths
    assert "/decision/analytics" in paths
    assert "DecisionSuggestionsResponse" in document["components"]["schemas"]


def test_client_decision_analytics_is_bounded_and_idempotent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    event = {
        "eventId": "decision-event:" + "a" * 32,
        "eventType": "decision_session_started",
        "payload": {"source": "decision", "action": "start"},
    }

    first = client.post("/decision/analytics", json=event)
    duplicate = client.post("/decision/analytics", json=event)
    forbidden = client.post(
        "/decision/analytics",
        json={**event, "eventId": "decision-event:" + "b" * 32, "payload": {"email": "private@example.test"}},
    )
    server_event = client.post(
        "/decision/analytics",
        json={**event, "eventId": "decision-event:" + "c" * 32, "eventType": "program_added_to_shortlist"},
    )

    assert first.status_code == 200, first.text
    assert first.json() == {"accepted": 1}
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == {"accepted": 0}
    assert forbidden.status_code == 422, forbidden.text
    assert server_event.status_code == 422, server_event.text
