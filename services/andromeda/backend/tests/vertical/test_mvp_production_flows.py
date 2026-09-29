from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

sys.path.insert(0, str(Path(__file__).parents[1].parent / "scripts"))

from run_andromeda_ingestion import AndromedaRunResult, run_university  # noqa: E402


PROGRAM_A = "program:bmstu:09.03.01-02"
PROGRAM_B = "program:bmstu:09.03.01-12"


def _fixture_client(tmp_path: Path) -> tuple[TestClient, tuple[AndromedaRunResult, ...]]:
    database_url = f"sqlite:///{(tmp_path / 'mvp-production-smoke.db').as_posix()}"
    runs = tuple(
        run_university(
            university=university,
            mode="fixture",
            fixture_dir=None,
            database_url=database_url,
            program_codes=None,
        )
        for university in ("bmstu", "hse")
    )
    return TestClient(create_app(database_url)), runs


def _complete_proftest(client: TestClient) -> dict[str, object]:
    state = client.post("/proftest/sessions")
    assert state.status_code == 200, state.text
    payload = state.json()
    for _ in range(9):
        question = payload.get("currentQuestion")
        if question is None:
            break
        request: dict[str, object] = {
            "expectedRevision": payload["revision"],
            "questionId": question["id"],
            "optionIds": [question["options"][0]["id"]],
        }
        if question.get("adaptive"):
            request["dimension"] = question["declaredDimensions"][0]
        next_state = client.post("/proftest/sessions/current/next", json=request)
        assert next_state.status_code == 200, next_state.text
        payload = next_state.json()

    completed = client.post("/proftest/sessions/current/complete")
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["status"] == "completed"
    assert result["results"]["recommendations"]
    return result


def test_mvp_anonymous_journey_covers_data_gaps_choice_and_ingestion_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "mvp-smoke-ops-key")
    client, runs = _fixture_client(tmp_path)

    assert tuple(run.university for run in runs) == ("bmstu", "hse")
    assert all(run.run_id.startswith("ingest:") for run in runs)
    assert all(run.program_ids for run in runs)
    assert runs[1].source_gap_count > 0

    with client:
        catalog = client.get("/programs")
        assert catalog.status_code == 200, catalog.text
        program_ids = {item["id"] for item in catalog.json()["items"]}
        assert {PROGRAM_A, PROGRAM_B, *runs[1].program_ids} <= program_ids

        started = client.post("/proftest/sessions")
        resumed = client.get("/proftest/sessions/current")
        assert started.status_code == resumed.status_code == 200
        assert started.json()["sessionId"] == resumed.json()["sessionId"]
        results = _complete_proftest(client)
        recommendation = results["results"]["recommendations"][0]
        assert recommendation["reasons"]
        assert all(reason["text"] and "sourceNames" in reason for reason in recommendation["reasons"])
        assert "contentFit" in recommendation and "admissionFit" in recommendation

        suggestions = client.get("/decision/suggestions")
        assert suggestions.status_code == 200, suggestions.text
        assert suggestions.json()["suggestions"]
        assert any(item["contentFit"] is not None for item in suggestions.json()["suggestions"])

        admissions = client.get(f"/programs/{PROGRAM_A}/admissions")
        assert admissions.status_code == 200, admissions.text
        offering = next(item for item in admissions.json()["offerings"] if item["admissionYear"] == 2026 and item["exams"])
        incomplete_fit = client.post(
            f"/programs/{PROGRAM_A}/admission-fit",
            json={
                "offeringId": offering["id"],
                "applicant": {"scores": [{"subject": offering["exams"][0]["subject"], "score": 90}]},
            },
        )
        assert incomplete_fit.status_code == 200, incomplete_fit.text
        assert incomplete_fit.json()["status"] == "insufficient_data"
        assert incomplete_fit.json()["dataQuality"] == "partial"
        assert incomplete_fit.json()["dataGaps"]

        initial_context = client.get("/decision/context")
        assert initial_context.status_code == 200, initial_context.text
        initial_revision = initial_context.json()["state"]["revision"]
        added_a = client.post(
            "/decision/shortlist",
            json={"programId": PROGRAM_A, "role": "primary", "expectedRevision": initial_revision},
        )
        assert added_a.status_code == 200, added_a.text
        stale = client.post(
            "/decision/shortlist",
            json={"programId": PROGRAM_B, "role": "alternative", "expectedRevision": initial_revision},
        )
        assert stale.status_code == 409, stale.text
        added_b = client.post(
            "/decision/shortlist",
            json={
                "programId": PROGRAM_B,
                "role": "alternative",
                "expectedRevision": added_a.json()["context"]["state"]["revision"],
            },
        )
        assert added_b.status_code == 200, added_b.text

        comparison = client.get("/compare", params={"programIds": f"{PROGRAM_A},{PROGRAM_B}"})
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["rows"]

        selected = client.post(
            "/decision/final-choice",
            json={
                "programId": PROGRAM_A,
                "expectedRevision": added_b.json()["context"]["state"]["revision"],
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["context"]["state"]["selectedProgramId"] == PROGRAM_A
        reloaded = client.get("/decision/context")
        assert reloaded.json()["state"]["selectedProgramId"] == PROGRAM_A

        registered = client.post(
            "/auth/register",
            headers={"Origin": "http://127.0.0.1:3000"},
            json={"email": "mvp-smoke@example.com", "password": "mvp-smoke-password"},
        )
        assert registered.status_code == 201, registered.text
        assert client.get("/decision/context").json()["state"]["selectedProgramId"] == PROGRAM_A
        logged_out = client.post("/auth/logout", headers={"Origin": "http://127.0.0.1:3000"})
        assert logged_out.status_code == 200
        assert client.get("/auth/session").json() == {"authenticated": False, "account": None}

        ops_headers = {"X-Andromeda-Ops-Key": "mvp-smoke-ops-key"}

        def fail_capture(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("fixture capture failed for smoke")

        with monkeypatch.context() as patch:
            patch.setattr(BmstuUniversityAdapter, "capture", fail_capture)
            failed_retry = client.post("/ops/ingestion/runs/retry", headers=ops_headers, json={"source": "bmstu_fixture"})

        assert failed_retry.status_code == 200, failed_retry.text
        assert failed_retry.json()["run"]["status"] == "failed"
        successful_retry = client.post("/ops/ingestion/runs/retry", headers=ops_headers, json={"source": "bmstu_fixture"})
        assert successful_retry.status_code == 200, successful_retry.text
        assert successful_retry.json()["run"]["status"] == "completed"
        assert successful_retry.json()["run"]["id"] != failed_retry.json()["run"]["id"]
