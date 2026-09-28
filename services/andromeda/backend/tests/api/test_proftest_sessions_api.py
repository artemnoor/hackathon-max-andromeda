from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


def _client(tmp_path: Path) -> TestClient:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'proftest-session-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def test_session_start_is_idempotent_and_pins_v3_question_set(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post("/proftest/sessions")
    second = client.post("/proftest/sessions")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["sessionId"] == second.json()["sessionId"]
    assert first.json()["questionSetVersion"] == "proftest-v3"
    assert first.json()["currentQuestion"]["id"] == "core_doing"
    assert first.json()["currentQuestion"]["componentType"] == "MultiChoiceCard"
    assert first.json()["progress"]["maxRemaining"] == 9


def test_session_next_persists_revision_and_rejects_stale_write(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/proftest/sessions").json()
    question = started["currentQuestion"]
    payload = {
        "expectedRevision": started["revision"],
        "questionId": question["id"],
        "optionIds": [question["options"][0]["id"]],
    }

    saved = client.post("/proftest/sessions/current/next", json=payload)
    stale = client.post("/proftest/sessions/current/next", json=payload)

    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == started["revision"] + 1
    assert saved.json()["interactionCount"] == 1
    assert stale.status_code == 409
    assert stale.json()["code"] == "CONFLICT"


def test_session_next_accepts_json_answer_status(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/proftest/sessions").json()
    question = started["currentQuestion"]

    response = client.post(
        "/proftest/sessions/current/next",
        json={
            "expectedRevision": started["revision"],
            "questionId": question["id"],
            "optionIds": [question["options"][0]["id"]],
            "status": "answered",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["interactionCount"] == 1


def test_multi_select_options_count_as_one_rendered_submission(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/proftest/sessions").json()
    question = started["currentQuestion"]

    response = client.post(
        "/proftest/sessions/current/next",
        json={
            "expectedRevision": started["revision"],
            "questionId": question["id"],
            "optionIds": [option["id"] for option in question["options"][:3]],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["interactionCount"] == 1
    assert response.json()["cursor"] == 1


def test_session_rejects_option_id_not_declared_by_question(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/proftest/sessions").json()

    response = client.post(
        "/proftest/sessions/current/next",
        json={
            "expectedRevision": started["revision"],
            "questionId": started["currentQuestion"]["id"],
            "optionIds": ["option-forged-by-client"],
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_session_can_complete_compact_flow_and_resume_completed_result(tmp_path: Path) -> None:
    client = _client(tmp_path)
    state = client.post("/proftest/sessions").json()
    for _ in range(9):
        question = state.get("currentQuestion")
        if question is None:
            break
        payload = {
            "expectedRevision": state["revision"],
            "questionId": question["id"],
            "optionIds": [question["options"][0]["id"]],
        }
        if question["adaptive"]:
            payload["dimension"] = question["declaredDimensions"][0]
        response = client.post("/proftest/sessions/current/next", json=payload)
        assert response.status_code == 200, response.text
        state = response.json()

    completed = client.post("/proftest/sessions/current/complete")
    resumed = client.get("/proftest/sessions/current")

    assert state["cursor"] <= 9
    assert state["interactionCount"] <= 9
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["results"]["recommendations"]
    completed_payload = completed.json()
    first_evidence = completed_payload["results"]["recommendations"][0]["evidence"]
    assert completed_payload["profileRevision"] is not None
    assert first_evidence["profileRevision"] == completed_payload["profileRevision"]
    assert first_evidence["questionSetVersion"] == "proftest-v3"
    assert first_evidence["signalsUsed"] or first_evidence["inferredSignals"]
    assert "missingData" in first_evidence
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["results"]["recommendations"]


def test_session_exposes_preliminary_topics_after_five_core_answers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    state = client.post("/proftest/sessions").json()

    for _ in range(5):
        question = state["currentQuestion"]
        assert question["id"].startswith("core_")
        response = client.post(
            "/proftest/sessions/current/next",
            json={
                "expectedRevision": state["revision"],
                "questionId": question["id"],
                "optionIds": [question["options"][0]["id"]],
            },
        )
        assert response.status_code == 200, response.text
        state = response.json()

    assert state["preliminary"] is not None
    assert len(state["preliminary"]["topics"]) <= 3
    assert all(set(topic) == {"code", "label"} for topic in state["preliminary"]["topics"])
    assert "contentFit" not in state["preliminary"]
    assert "programId" not in state["preliminary"]
    assert state["adaptive"] is not None


def test_analytics_event_replay_is_deduplicated(tmp_path: Path) -> None:
    client = _client(tmp_path)
    session = client.post("/proftest/sessions").json()
    event_id = f"proftest-event:{uuid4().hex}"
    event = {
        "eventId": event_id,
        "sessionId": session["sessionId"],
        "questionSetVersion": "proftest-v2",
        "eventType": "stage_viewed",
        "payload": {"stage": "about"},
        "occurredAt": "2026-09-15T12:00:00Z",
    }

    first = client.post("/proftest/analytics", json={"events": [event]})
    replay = client.post("/proftest/analytics", json={"events": [event]})

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["accepted"] == 1
    assert replay.json()["accepted"] == 0


def test_analytics_rejects_unknown_payload_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)
    event = {
        "eventId": f"proftest-event:{uuid4().hex}",
        "questionSetVersion": "proftest-v2",
        "eventType": "stage_viewed",
        "payload": {"email": "must-not-be-stored"},
        "occurredAt": "2026-09-15T12:00:00Z",
    }

    response = client.post("/proftest/analytics", json={"events": [event]})

    assert response.status_code == 422


def test_registration_binds_anonymous_draft_to_account_without_merging(tmp_path: Path) -> None:
    client = _client(tmp_path)
    started = client.post("/proftest/sessions").json()
    question = started["currentQuestion"]
    saved = client.post(
        "/proftest/sessions/current/next",
        json={
            "expectedRevision": started["revision"],
            "questionId": question["id"],
            "optionIds": [question["options"][0]["id"]],
        },
    )
    assert saved.status_code == 200, saved.text

    registered = client.post("/auth/register", json={"email": "draft-owner@example.com", "password": "a-secure-password"})
    resumed = client.get("/proftest/sessions/current")

    assert registered.status_code == 201, registered.text
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "draft"
    assert resumed.json()["interactionCount"] == 1
    assert resumed.json()["currentQuestion"]["id"] != question["id"]
