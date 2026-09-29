from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from andromeda.api.main import create_app
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.curricula import SqlAlchemyCurriculumRepository
from andromeda.infrastructure.repositories.disciplines import SqlAlchemyDisciplineRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter


BACKEND_ROOT = Path(__file__).parents[2]


def _migrate(database_url: str, monkeypatch) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def _seed(tmp_path: Path, monkeypatch) -> tuple[str, TestClient]:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw")
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'storage-parity.db').as_posix()}"
    _migrate(database_url, monkeypatch)
    engine = create_engine_for_url(database_url)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
    return database_url, TestClient(create_app(database_url))


def test_alembic_sqlite_path_preserves_public_readers_and_api_flow(tmp_path: Path, monkeypatch) -> None:
    database_url, client = _seed(tmp_path, monkeypatch)
    engine = create_engine_for_url(database_url)
    try:
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            programs = SqlAlchemyProgramRepository(session).list()
            curriculum = SqlAlchemyCurriculumRepository(session).get_for_program(programs[0].id)
            disciplines = SqlAlchemyDisciplineRepository(session).list()

        assert len(programs) == 2
        assert curriculum is not None
        assert curriculum.items
        assert len(disciplines) == 101
    finally:
        engine.dispose()

    programs_response = client.get("/programs")
    comparison = client.get(
        "/compare",
        params={"programIds": "program:09.03.01-02,program:09.03.01-12", "scope": "semester", "semester": 1},
    )
    admissions = client.get("/programs/program:09.03.01-02/admissions")
    offering = next(item for item in admissions.json()["offerings"] if item["exams"])
    admission_fit = client.post(
        "/programs/program:09.03.01-02/admission-fit",
        json={
            "offeringId": offering["id"],
            "applicant": {
                "scores": [
                    {"subject": exam["subject"], "score": 90}
                    for exam in offering["exams"]
                ]
            },
        },
    )
    assert programs_response.status_code == 200
    assert comparison.status_code == 200
    assert admission_fit.status_code == 200
    assert admission_fit.json()["dataQuality"] == "complete"
    assert comparison.json()["rows"]


def test_alembic_seed_keeps_proftest_and_recommendation_services_unchanged(tmp_path: Path, monkeypatch) -> None:
    _, client = _seed(tmp_path, monkeypatch)
    answers = {
        "answers": [
            {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
            {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
            {"questionId": "activity_build", "optionIds": ["system_scheme"]},
            {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
            {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
            {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
        ]
    }
    results = client.post("/proftest/results", json=answers)
    assert results.status_code == 200
    recommendation = client.post("/recommendations", json={"profile": results.json()["profile"], "limit": 2})
    assert recommendation.status_code == 200
    assert recommendation.json()["recommendations"]
