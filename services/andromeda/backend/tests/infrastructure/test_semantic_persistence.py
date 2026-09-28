from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.models import (
    CurriculumItemSourceLinkModel,
    SemanticFeatureModel,
    SourceSnapshotModel,
)
from andromeda.infrastructure.repositories.curricula import (
    SqlAlchemyCurriculumRepository,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.modules.semantic.domain import DEFAULT_SEMANTIC_FEATURES
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_ingestion_persists_semantic_seed_and_item_source_evidence(
    ingested_db: tuple[str, object, object],
) -> None:
    database_url, _raw, canonical = ingested_db
    engine = create_engine_for_url(database_url)
    try:
        with Session(engine) as session:
            features = session.scalars(select(SemanticFeatureModel).order_by(SemanticFeatureModel.code)).all()
            links = session.scalars(select(CurriculumItemSourceLinkModel)).all()
            snapshots = {row.content_sha256 for row in session.scalars(select(SourceSnapshotModel)).all()}

            assert {feature.code for feature in features} == {feature.code for feature in DEFAULT_SEMANTIC_FEATURES}
            assert links
            assert all(link.source_sha256 in snapshots for link in links)
            assert {link.curriculum_item_id for link in links} == {
                item.id
                for curriculum in canonical.curricula
                for item in curriculum.items
                if item.provenance
            }

            curriculum = SqlAlchemyCurriculumRepository(session).get_for_program(canonical.programs[0].id)
            assert curriculum is not None
            expected_items = {
                item.id: item
                for source_curriculum in canonical.curricula
                if source_curriculum.program_id == canonical.programs[0].id
                for item in source_curriculum.items
            }
            actual_item = next(item for item in curriculum.items if item.id in expected_items)
            expected_item = expected_items[actual_item.id]
            assert actual_item.provenance
            assert {value.content_sha256 for value in actual_item.provenance} == {
                value.content_sha256 for value in expected_item.provenance
            }
            assert {value.university_id for value in actual_item.provenance} == {
                value.university_id for value in expected_item.provenance
            }
            assert {value.inferred for value in actual_item.provenance} == {
                value.inferred for value in expected_item.provenance
            }
            assert actual_item.lecture_hours == expected_item.lecture_hours
            assert actual_item.practice_hours == expected_item.practice_hours
            assert actual_item.lab_hours == expected_item.lab_hours
            assert actual_item.self_study_hours == expected_item.self_study_hours
            assert actual_item.is_elective == expected_item.is_elective
            assert actual_item.course_block == expected_item.course_block
            assert actual_item.practice_type == expected_item.practice_type
    finally:
        engine.dispose()


def test_reingestion_does_not_duplicate_semantic_seed_or_item_source_links(
    ingested_db: tuple[str, object, object],
) -> None:
    database_url, raw, canonical = ingested_db
    engine = create_engine_for_url(database_url)
    try:
        repository = SqlAlchemyIngestionRepository(engine)
        with Session(engine) as session:
            initial_features = len(session.scalars(select(SemanticFeatureModel)).all())
            initial_links = len(session.scalars(select(CurriculumItemSourceLinkModel)).all())

        repository.ingest(raw, canonical)

        with Session(engine) as session:
            assert len(session.scalars(select(SemanticFeatureModel)).all()) == initial_features
            assert len(session.scalars(select(CurriculumItemSourceLinkModel)).all()) == initial_links
    finally:
        engine.dispose()


def test_semantic_migration_round_trip_keeps_previous_canonical_schema(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'semantic-migration.db').as_posix()}"
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)
    config = _alembic_config("sqlite:///ignored-by-environment.db")

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "curriculum_item_source_links",
            "semantic_features",
            "discipline_semantic_features",
            "curriculum_item_semantic_features",
        }.issubset(tables)
        assert {
            "lecture_hours",
            "practice_hours",
            "lab_hours",
            "self_study_hours",
            "is_elective",
            "course_block",
            "practice_type",
        }.issubset({column["name"] for column in inspector.get_columns("curriculum_items")})
    finally:
        engine.dispose()

    command.downgrade(config, "0025_uni_events")
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "semantic_features" not in tables
        assert "curriculum_item_source_links" not in tables
        assert "curriculum_items" in tables
    finally:
        engine.dispose()
