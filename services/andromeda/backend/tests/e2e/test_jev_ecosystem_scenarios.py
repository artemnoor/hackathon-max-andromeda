from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from scripts.run_andromeda_bmstu import run_ingest

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def _client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{(tmp_path / 'jev-ecosystem.db').as_posix()}"
    run_ingest(
        mode="fixture",
        fixture_dir=FIXTURE_DIR,
        database_url=database_url,
        program_codes=(),
    )
    return TestClient(create_app(database_url))


def test_math_comparison_is_deterministic_and_channel_neutral(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/assistant/query",
            json={
                "text": "Где больше математики между program:bmstu:09.03.01-02 и program:bmstu:09.03.01-12?",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "complete"
    assert payload["response"]["template"] == "metric-comparison"
    assert payload["query"]["metrics"] == ["math_share"]
    assert payload["query"]["scope_ids"] == [
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    ]
    rows = payload["response"]["data"]["rows"]
    assert {row["entity_id"] for row in rows} == set(payload["query"]["scope_ids"])
    assert all(row["metrics"]["math_share"]["value"] is not None for row in rows)
    assert all(
        row["metrics"]["math_share"]["basis"] in {"hours", "credits"} for row in rows
    )
    assert all(row["evidence"] for row in rows)
    assert payload["response"]["evidence"][0]["evidence_count"] > 0


@pytest.mark.parametrize(
    "text, expected_slot",
    (
        ("Какие программы похожи?", "metric"),
        ("А где лучше?", "metric"),
        ("Сравни эти две программы", "metric"),
        ("Где больше математики: ИУ5 или ИУ7?", "entity"),
    ),
)
def test_unsupported_or_incomplete_prompts_clarify_without_inventing_programs(
    tmp_path: Path,
    text: str,
    expected_slot: str,
) -> None:
    with _client(tmp_path) as client:
        response = client.post("/assistant/query", json={"text": text})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "needs_clarification"
    assert payload["missing_slots"] == [expected_slot]
    assert payload["response"] is None
    assert payload["query"] is None
    assert payload["admission_result"] is None
    assert payload["admission_request"] is None


def test_complete_admission_request_does_not_add_clarification_turn(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/assistant/query",
            json={
                "text": "Куда я прохожу с 270: русский 90, математика 90, информатика 90, university:bmstu, бюджет",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "complete"
    assert payload["missing_slots"] == []
    assert payload["admission_request"]["program_ids"]
