from __future__ import annotations

from pathlib import Path
from decimal import Decimal

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
    database_url = f"sqlite:///{(tmp_path / 'proftest-api.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return TestClient(create_app(database_url))


def _answers() -> dict[str, object]:
    return {
        "answers": [
            {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
            {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
            {"questionId": "activity_build", "optionIds": ["system_scheme"]},
            {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
            {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
            {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
        ]
    }


def test_questions_are_public_without_internal_weight_payload(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/proftest/questions")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["questions"]) == 6
    assert "subjectWeights" not in payload["questions"][0]["options"][0]
    assert payload["questions"][4]["multiSelect"] is True


def test_preview_and_results_use_real_catalog(tmp_path: Path) -> None:
    client = _client(tmp_path)
    preview = client.post("/proftest/preview", json=_answers())

    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["profile"]["negativeWeights"]["physics_astronomy"] == "0.9"
    assert preview_payload["candidates"]
    assert preview_payload["adaptive"]["status"] in {"ready", "skipped"}

    results_payload = _answers()
    if preview_payload["adaptive"]["status"] == "ready":
        question = preview_payload["question"]
        assert question is not None
        results_payload["adaptiveAnswers"] = [{"questionId": question["id"], "optionId": "prefer_first", "dimension": preview_payload["adaptive"]["dimensions"][0]["code"]}]
    results = client.post("/proftest/results", json=results_payload)

    assert results.status_code == 200
    payload = results.json()
    assert payload["recommendations"]
    recommendation = payload["recommendations"][0]
    assert isinstance(recommendation["contentFit"], int)
    assert Decimal(recommendation["score"]["breakdown"]["antiPenalty"]) >= 0
    assert "workloadReadiness" not in recommendation
    assert "careerFit" not in recommendation


def test_submission_rejects_unknown_fields_with_strict_contract(tmp_path: Path) -> None:
    payload = _answers()
    payload["unexpected"] = True

    response = _client(tmp_path).post("/proftest/preview", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
