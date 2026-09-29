"""Rebuild semantic assignments and program projections from canonical storage.

This operator command is deliberately bounded: it accepts canonical scope and
version parameters only. It never accepts source URLs, prompts or model output.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import logging
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.infrastructure.config import Settings  # noqa: E402
from andromeda.infrastructure.database import create_engine_for_url  # noqa: E402
from andromeda.infrastructure.database.models import IngestRunModel  # noqa: E402
from andromeda.infrastructure.repositories.admissions import SqlAlchemyAdmissionRepository  # noqa: E402
from andromeda.infrastructure.repositories.analytics import SqlAlchemyProgramProjectionRepository  # noqa: E402
from andromeda.infrastructure.repositories.curricula import SqlAlchemyCurriculumRepository  # noqa: E402
from andromeda.infrastructure.repositories.disciplines import SqlAlchemyDisciplineRepository  # noqa: E402
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository  # noqa: E402
from andromeda.infrastructure.repositories.semantic_enrichment import SqlAlchemySemanticEnrichmentRepository  # noqa: E402
from andromeda.modules.analytics.services.projection_builder import ProgramProjectionBuilder, ProgramProjectionService  # noqa: E402
from andromeda.modules.admissions.contracts.public import ProgramAdmissions  # noqa: E402
from andromeda.modules.curricula.contracts.public import Curriculum  # noqa: E402
from andromeda.modules.disciplines.contracts.public import Discipline  # noqa: E402
from andromeda.modules.programs.contracts.public import Program  # noqa: E402
from andromeda.modules.semantic.contracts.review_artifacts import ReviewedSemanticArtifact  # noqa: E402
from andromeda.modules.semantic.services.classifier import ReviewedMappingSemanticClassifier, RuleBasedSemanticClassifier  # noqa: E402
from andromeda.modules.semantic.contracts.review import SemanticReviewCandidate, SemanticReviewQueueItem, build_review_queue  # noqa: E402
from andromeda.modules.semantic.services.enrichment import SemanticEnrichmentService  # noqa: E402
from andromeda.shared.contracts.ids import UniversityId  # noqa: E402

logger = logging.getLogger("andromeda.scripts.rebuild_semantics")


@dataclass(slots=True)
class CanonicalRebuildSnapshot:
    programs: tuple[Program, ...]
    disciplines: tuple[Discipline, ...]
    curricula: tuple[Curriculum, ...]
    admissions: tuple[ProgramAdmissions, ...]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild canonical semantic assignments and projections")
    parser.add_argument("--database-url", default=Settings.from_environment().database_url)
    parser.add_argument("--university", help="canonical university id, for example university:bmstu")
    parser.add_argument("--ingest-run-id", help="use a specific canonical ingest run")
    parser.add_argument("--definition-version", default="semantic-taxonomy.v1")
    parser.add_argument("--classifier-version", default="semantic-classifier.v1")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--retry-of-run-id", help="record this run as a retry of a failed semantic run")
    reviewed_group = parser.add_mutually_exclusive_group()
    reviewed_group.add_argument("--reviewed-artifact", type=Path, help="apply an accepted reviewed semantic artifact")
    reviewed_group.add_argument("--rollback-reviewed-artifact", type=Path, help="explicitly select a previous reviewed artifact")
    parser.add_argument("--export-review-queue", type=Path, help="write an idempotent semantic review queue as JSONL")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.batch_size > 5000:
        parser.error("--batch-size must be between 1 and 5000")

    engine = create_engine_for_url(args.database_url)
    try:
        with Session(engine) as session:
            run = _select_run(session, args.university, args.ingest_run_id)
            university_id: UniversityId = args.university or run.university_id
            programs = SqlAlchemyProgramRepository(session).list(university_id=university_id)
            curricula_by_program = SqlAlchemyCurriculumRepository(session).list_for_programs(tuple(program.id for program in programs))
            curricula = tuple(curricula_by_program.values())
            disciplines = SqlAlchemyDisciplineRepository(session).list()
            admissions = SqlAlchemyAdmissionRepository(session).get_for_programs(tuple(program.id for program in programs))
            item_count = sum(len(curriculum.items) for curriculum in curricula)
            input_hash = _snapshot_hash(programs, curricula)
            logger.info(
                "semantic_rebuild_selected ingest_run_id=%s university_id=%s programs=%d items=%d input_hash=%s batch_size=%d dry_run=%s",
                run.id,
                university_id,
                len(programs),
                item_count,
                input_hash,
                args.batch_size,
                args.dry_run,
            )
            if args.dry_run:
                print(json.dumps({"status": "dry_run", "ingestRunId": run.id, "programCount": len(programs), "itemCount": item_count, "inputHash": input_hash}))
                return 0

            semantic_store = SqlAlchemySemanticEnrichmentRepository(engine)
            if args.export_review_queue is not None:
                queue = _build_review_queue(
                    curricula,
                    disciplines,
                    semantic_store,
                    semantic_version=args.definition_version,
                    classifier_version=args.classifier_version,
                    output_path=args.export_review_queue,
                )
                print(json.dumps({"status": "review_queue_exported", "count": len(queue), "path": str(args.export_review_queue)}))
                return 0
            base_classifier = RuleBasedSemanticClassifier(
                taxonomy_version=args.definition_version,
                classifier_version=args.classifier_version,
            )
            artifact_path = args.reviewed_artifact or args.rollback_reviewed_artifact
            classifier = base_classifier
            if artifact_path is not None:
                artifact = _load_reviewed_artifact(artifact_path)
                classifier = ReviewedMappingSemanticClassifier(base_classifier, artifact)
                logger.info(
                    "semantic_reviewed_artifact_selected artifact_id=%s classifier_version=%s rollback=%s",
                    artifact.artifact_id,
                    artifact.classifier_version,
                    args.rollback_reviewed_artifact is not None,
                )
            service = SemanticEnrichmentService(
                classifier,
                semantic_store,
            )
            semantic_run = service.enrich(
                university_id=university_id,
                ingest_run_id=run.id,
                curricula=curricula,
                disciplines=disciplines,
                retry_of_run_id=args.retry_of_run_id,
            )
            projection_service = ProgramProjectionService(
                ProgramProjectionBuilder(),
                semantic_store,
                SqlAlchemyProgramProjectionRepository(engine),
            )
            snapshot = CanonicalRebuildSnapshot(programs, disciplines, curricula, admissions)
            projections = projection_service.refresh(snapshot, semantic_run)
            result = {
                "status": semantic_run.status.value,
                "semanticRunId": semantic_run.id,
                "ingestRunId": run.id,
                "programCount": len(programs),
                "refreshedProgramCount": len(projections),
                "classifiedItemCount": semantic_run.classified_item_count,
                "unchangedItemCount": semantic_run.unchanged_item_count,
                "inputHash": input_hash,
                "retryOfRunId": args.retry_of_run_id,
            }
            print(json.dumps(result, ensure_ascii=False))
            return 0
    finally:
        engine.dispose()


def _select_run(session: Session, university_id: str | None, ingest_run_id: str | None) -> IngestRunModel:
    if ingest_run_id:
        run = session.get(IngestRunModel, ingest_run_id)
    else:
        query = select(IngestRunModel).where(IngestRunModel.status == "completed").order_by(IngestRunModel.finished_at.desc())
        if university_id:
            query = query.where(IngestRunModel.university_id == university_id)
        run = session.scalar(query)
    if run is None or run.status != "completed":
        raise RuntimeError("A completed canonical ingest run is required for semantic rebuild")
    if university_id and run.university_id != university_id:
        raise RuntimeError("The ingest run does not belong to the requested university")
    return run


def _snapshot_hash(programs: tuple[Program, ...], curricula: tuple[Curriculum, ...]) -> str:
    """Return a stable, content-light checkpoint hash for operator verification."""

    values = [program.id for program in programs]
    for curriculum in curricula:
        values.append(curriculum.id)
        values.extend(
            f"{item.id}:{item.discipline_id}:{item.source_name}:{item.semester}:{item.hours}:{item.credits}"
            for item in curriculum.items
        )
    payload = "\n".join(sorted(values)).encode("utf-8")
    return sha256(payload).hexdigest()


def _load_reviewed_artifact(path: Path) -> ReviewedSemanticArtifact:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ReviewedSemanticArtifact.model_validate(payload, strict=False)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"reviewed semantic artifact is invalid: {path}") from exc


def _build_review_queue(
    curricula: tuple[Curriculum, ...],
    disciplines: tuple[Discipline, ...],
    semantic_store: SqlAlchemySemanticEnrichmentRepository,
    *,
    semantic_version: str,
    classifier_version: str,
    output_path: Path,
) -> tuple[SemanticReviewQueueItem, ...]:
    items = tuple(item for curriculum in curricula for item in curriculum.items)
    features = semantic_store.item_features(
        tuple(item.id for item in items),
        semantic_version=semantic_version,
        classifier_version=classifier_version,
    )
    disciplines_by_id = {discipline.id: discipline for discipline in disciplines}
    candidates = tuple(
        SemanticReviewCandidate(
            discipline_id=item.discipline_id,
            curriculum_item_id=item.id,
            discipline_name=disciplines_by_id.get(item.discipline_id).name if item.discipline_id in disciplines_by_id else item.source_name,
            values=tuple(value.feature for value in features.get(item.id, ())),
            source_hash=item.provenance[0].content_sha256 if item.provenance else None,
            semantic_version=semantic_version,
            classifier_version=classifier_version,
            created_at=item.provenance[0].captured_at if item.provenance else datetime.now(UTC),
        )
        for item in items
    )
    reviewed_ids = frozenset(
        json.loads(line)["queue_id"]
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ) if output_path.exists() else frozenset()
    queue = build_review_queue(candidates, reviewed_queue_ids=reviewed_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(item.model_dump_json() + "\n" for item in queue),
        encoding="utf-8",
    )
    logger.info("semantic_review_queue_exported count=%d path=%s", len(queue), output_path)
    return queue


if __name__ == "__main__":
    raise SystemExit(main())
