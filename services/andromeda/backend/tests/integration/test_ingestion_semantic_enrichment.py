from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import (
    CurriculumItemSemanticFeatureModel,
    DisciplineSemanticFeatureModel,
    IngestRunModel,
    ProgramMetricEvidenceModel,
    ProgramMetricModel,
    ProgramProjectionModel,
    SemanticEnrichmentRunModel,
)
from andromeda.infrastructure.repositories.analytics import (
    SqlAlchemyProgramProjectionRepository,
)
from andromeda.infrastructure.repositories.ingestion import (
    SqlAlchemyIngestionRepository,
)
from andromeda.infrastructure.repositories.semantic_enrichment import (
    SqlAlchemySemanticEnrichmentRepository,
)
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.semantic.services.classifier import RuleBasedSemanticClassifier
from andromeda.modules.semantic.domain import DEFAULT_SEMANTIC_FEATURES
from andromeda.modules.semantic.services.enrichment import SemanticEnrichmentService
from sqlalchemy import func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402, I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_ingestion_runs_semantic_enrichment_and_reclassifies_only_changed_items(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'semantic-enrichment.db').as_posix()}"
    first = run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())
    second = run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())

    engine = create_engine_for_url(database_url)
    try:
        with Session(engine) as session:
            runs = session.scalars(select(SemanticEnrichmentRunModel).order_by(SemanticEnrichmentRunModel.started_at)).all()
            assert len(runs) == 2
            assert runs[0].status == "completed"
            assert runs[0].classified_item_count == first.curriculum_item_count
            assert runs[0].unchanged_item_count == 0
            assert len(json.loads(runs[0].changed_item_ids_json)) == first.curriculum_item_count
            assert runs[1].status == "completed"
            assert runs[1].classified_item_count == 0
            assert runs[1].unchanged_item_count == second.curriculum_item_count
            assert json.loads(runs[1].changed_item_ids_json) == []
            feature_count = len(DEFAULT_SEMANTIC_FEATURES)
            assert session.scalar(select(func.count()).select_from(CurriculumItemSemanticFeatureModel)) == first.curriculum_item_count * feature_count
            assert session.scalar(select(func.count()).select_from(DisciplineSemanticFeatureModel)) == first.unique_discipline_count * feature_count
            assert session.scalar(
                select(func.count()).select_from(CurriculumItemSemanticFeatureModel).where(
                    CurriculumItemSemanticFeatureModel.source_hash.is_(None)
                )
            ) == 0
            assert session.scalar(
                select(func.count()).select_from(CurriculumItemSemanticFeatureModel).where(
                    CurriculumItemSemanticFeatureModel.source_run_id == first.run_id
                )
            ) == first.curriculum_item_count * feature_count
            assert session.scalar(select(func.count()).select_from(ProgramProjectionModel)) == len(first.program_ids)
            assert session.scalar(select(func.count()).select_from(ProgramMetricModel)) == len(first.program_ids) * feature_count
            assert session.scalar(select(func.count()).select_from(ProgramMetricEvidenceModel)) > 0
        projection = SqlAlchemyProgramProjectionRepository(engine).get(first.program_ids[0])
        assert projection is not None
        assert projection.semantic_features["mathematics"].value is not None
        assert projection.quality.semantic_version == "semantic-taxonomy.v1"
        assert projection.admission_offerings
        assert {offering.admission_year for offering in projection.admission_offerings}
        assert {offering.funding_type for offering in projection.admission_offerings}
    finally:
        engine.dispose()


def test_semantic_failure_is_retryable_without_changing_canonical_health(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(mode="fixture", fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    database_url = f"sqlite:///{(tmp_path / 'semantic-failure.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    ingest_run_id = SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)

    class FailingClassifier:
        semantic_version = "semantic-taxonomy.v1"
        classifier_version = "semantic-classifier.v99"

        def classify(self, _input):
            raise RuntimeError("classifier unavailable")

    service = SemanticEnrichmentService(
        FailingClassifier(),
        SqlAlchemySemanticEnrichmentRepository(engine),
    )
    with pytest.raises(RuntimeError, match="classifier unavailable"):
        service.enrich(
            university_id=canonical.university.id,
            ingest_run_id=ingest_run_id,
            curricula=canonical.curricula,
            disciplines=canonical.disciplines,
        )

    try:
        with Session(engine) as session:
            canonical_run = session.get(IngestRunModel, ingest_run_id)
            derived_run = session.scalar(select(SemanticEnrichmentRunModel))
            assert canonical_run is not None and canonical_run.status == "completed"
            assert derived_run is not None and derived_run.status == "failed"
            assert derived_run.failed_item_count == 1

        retry_service = SemanticEnrichmentService(
            RuleBasedSemanticClassifier(classifier_version="semantic-classifier.v99"),
            SqlAlchemySemanticEnrichmentRepository(engine),
        )
        retried = retry_service.enrich(
            university_id=canonical.university.id,
            ingest_run_id=ingest_run_id,
            curricula=canonical.curricula,
            disciplines=canonical.disciplines,
            retry_of_run_id=derived_run.id,
        )
        assert retried.status == "completed"
        assert retried.retry_of_run_id == derived_run.id
    finally:
        engine.dispose()


def test_canonical_failure_does_not_create_a_derived_semantic_run(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(mode="fixture", fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    invalid_item = canonical.curricula[0].items[0].model_copy(update={"discipline_id": "discipline:missing"})
    invalid_curriculum = canonical.curricula[0].model_copy(
        update={"items": (invalid_item, *canonical.curricula[0].items[1:])}
    )
    invalid_canonical = canonical.model_copy(
        update={"curricula": (invalid_curriculum, *canonical.curricula[1:])}
    )
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'canonical-failure.db').as_posix()}")
    Base.metadata.create_all(engine)
    service = SemanticEnrichmentService(
        RuleBasedSemanticClassifier(),
        SqlAlchemySemanticEnrichmentRepository(engine),
    )
    repository = SqlAlchemyIngestionRepository(engine, semantic_enrichment=service)
    with pytest.raises(Exception):
        repository.ingest(raw, invalid_canonical)
    try:
        with Session(engine) as session:
            ingest_run = session.scalar(select(IngestRunModel))
            assert ingest_run is not None and ingest_run.status == "failed"
            assert session.scalar(select(func.count()).select_from(SemanticEnrichmentRunModel)) == 0
            assert session.scalar(select(func.count()).select_from(CurriculumItemSemanticFeatureModel)) == 0
    finally:
        engine.dispose()


def test_post_commit_derived_failure_keeps_canonical_rows_and_marks_recovery(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(mode="fixture", fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()

    class FailingDerivedRefresh:
        def refresh(self, _request):
            raise RuntimeError("derived store unavailable")

    database_url = f"sqlite:///{(tmp_path / 'post-commit-derived-failure.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    try:
        run_id = SqlAlchemyIngestionRepository(engine, derived_refresh=FailingDerivedRefresh()).ingest(raw, canonical)
        with Session(engine) as session:
            run = session.get(IngestRunModel, run_id)
            assert run is not None
            assert run.status == "completed"
            assert run.projection_status == "failed"
            assert run.recovery_reason == "derived_refresh_failed"
            assert session.scalar(select(func.count()).select_from(ProgramProjectionModel)) == 0
    finally:
        engine.dispose()
