from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawSourceSnapshot, RawTracerBundle
from andromeda.ingestion.contracts.source import CapturedSources
from andromeda.ingestion.quality import (
    PreviousProjection,
    QualityOutcome,
    is_critical_gap,
)
from andromeda.modules.analytics.services.projection_builder import (
    ProgramProjectionService,
)
from andromeda.modules.disciplines.contracts.public import (
    DisciplineAreaWeight,
    area_catalog,
)
from andromeda.modules.program_analytics.contracts.public import (
    DerivedRefreshOutcome,
    DerivedRefreshPort,
    DerivedRefreshRequest,
    DerivedRefreshStatus,
)
from andromeda.modules.semantic.domain import DEFAULT_SEMANTIC_FEATURES
from andromeda.modules.semantic.services.enrichment import SemanticEnrichmentService
from andromeda.shared.contracts.enums import AssessmentType, EducationLevel
from andromeda.shared.contracts.errors import (
    AndromedaError,
    ConflictError,
    ContractError,
    ErrorCode,
    ErrorDetail,
)
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference
from andromeda.shared.contracts.versions import (
    ANALYTICS_PROJECTION_SCHEMA_VERSION,
    SEMANTIC_CLASSIFIER_VERSION,
    SEMANTIC_TAXONOMY_VERSION,
)

from ..database.models import (
    AssessmentTypeModel,
    CurriculumItemAssessmentModel,
    CurriculumItemModel,
    CurriculumItemSourceLinkModel,
    CurriculumModel,
    DirectionModel,
    DisciplineAreaModel,
    DisciplineAreaWeightModel,
    DisciplineModel,
    EducationLevelModel,
    IngestRunModel,
    ProgramModel,
    RawSourceRecordModel,
    SemanticFeatureModel,
    SourceSnapshotModel,
    UniversityModel,
)
from ..database.session import session_factory
from .admission_benefits import SqlAlchemyAdmissionBenefitsRepository
from .admissions import SqlAlchemyAdmissionRepository
from .campus import SqlAlchemyCampusPointRepository
from .events import SqlAlchemyEventRepository

logger = logging.getLogger("andromeda.infrastructure.repositories.ingestion")
_LEGACY_UNIVERSITY_ID = "university:legacy"
_DEFAULT_PROJECTION_TARGET = "canonical"


@dataclass(slots=True)
class _SyncStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0

    def record(self, outcome: str) -> None:
        if outcome == "inserted":
            self.inserted += 1
        elif outcome == "updated":
            self.updated += 1
        else:
            self.unchanged += 1


class SqlAlchemyIngestionRepository:
    """Atomic write adapter from canonical DTOs to infrastructure models."""

    def __init__(
        self,
        engine: Any,
        *,
        derived_refresh: DerivedRefreshPort | None = None,
        semantic_enrichment: SemanticEnrichmentService | None = None,
        projection_service: ProgramProjectionService | None = None,
    ) -> None:
        self._factory = session_factory(engine)
        self._derived_refresh = derived_refresh
        self._semantic_enrichment = semantic_enrichment
        self._projection_service = projection_service

    def start_run(
        self,
        run_id: str | None = None,
        *,
        source_profile: str = "legacy",
        source_revision: str = "legacy",
        configuration_version: str = "legacy",
        retry_of_run_id: str | None = None,
        idempotency_key: str | None = None,
        university_id: str = _LEGACY_UNIVERSITY_ID,
        projection_target: str = _DEFAULT_PROJECTION_TARGET,
    ) -> str:
        resolved_run_id = run_id or f"ingest:{uuid4().hex}"
        if idempotency_key:
            existing_id = self.find_run_by_idempotency_key(idempotency_key)
            if existing_id is not None:
                return existing_id
        try:
            self._create_run(
                resolved_run_id,
                datetime.now(timezone.utc),
                source_count=0,
                source_hashes=(),
                source_kinds=(),
                program_count=0,
                curriculum_item_count=0,
                event_count=0,
                campus_point_count=0,
                source_profile=source_profile,
                source_revision=source_revision,
                configuration_version=configuration_version,
                retry_of_run_id=retry_of_run_id,
                idempotency_key=idempotency_key,
                university_id=university_id,
                projection_target=projection_target,
            )
        except IntegrityError as exc:
            existing_id = self.find_run_by_idempotency_key(idempotency_key) if idempotency_key else None
            if existing_id is not None:
                return existing_id
            running_id = self._active_run_id(
                university_id=university_id,
                source_profile=source_profile,
                projection_target=projection_target,
            )
            if running_id is not None:
                raise ConflictError(
                    "An ingestion run is already in progress",
                    (ErrorDetail(path="run_id", message=running_id, type="ingestion_in_progress"),),
                ) from exc
            raise
        logger.info("ingest_audit_started run_id=%s", resolved_run_id)
        return resolved_run_id

    def find_run_by_idempotency_key(self, idempotency_key: str | None) -> str | None:
        if not idempotency_key:
            return None
        with self._factory() as session:
            return session.scalar(
                select(IngestRunModel.id)
                .where(IngestRunModel.idempotency_key == idempotency_key)
                .limit(1)
            )

    def latest_run_id(self, source_profile: str) -> str | None:
        with self._factory() as session:
            return session.scalar(
                select(IngestRunModel.id)
                .where(IngestRunModel.source_profile == source_profile)
                .order_by(IngestRunModel.started_at.desc(), IngestRunModel.id.desc())
                .limit(1)
            )

    def _active_run_id(self, *, university_id: str, source_profile: str, projection_target: str) -> str | None:
        with self._factory() as session:
            return session.scalar(
                select(IngestRunModel.id)
                .where(
                    IngestRunModel.status == "running",
                    IngestRunModel.university_id == university_id,
                    IngestRunModel.source_profile == source_profile,
                    IngestRunModel.projection_target == projection_target,
                )
                .order_by(IngestRunModel.started_at.asc(), IngestRunModel.id.asc())
                .limit(1)
            )

    def heartbeat(self, run_id: str) -> None:
        """Refresh the lease without changing ingestion metadata."""
        self._update_run_metadata(run_id)

    def record_source_metadata(self, run_id: str, raw: RawTracerBundle) -> None:
        self.record_captured_metadata(run_id, raw.snapshots)
        logger.info(
            "ingest_source_batch_observed run_id=%s snapshots=%d source_bytes=%d records=%d",
            run_id,
            len(raw.snapshots),
            sum(len(snapshot.body) for snapshot in raw.snapshots),
            len(raw.programs)
            + len(raw.curriculum_rows)
            + len(raw.admissions)
            + len(raw.events)
            + len(raw.campus_points)
            + len(raw.admission_benefit_records),
        )
        self._update_run_metadata(
            run_id,
            source_count=len(raw.snapshots),
            source_hashes=tuple(snapshot.content_sha256 for snapshot in raw.snapshots),
            source_kinds=tuple(snapshot.source_kind for snapshot in raw.snapshots),
            program_count=len(raw.programs),
            curriculum_item_count=len(raw.curriculum_rows),
            event_count=len(raw.events),
            campus_point_count=len(raw.campus_points),
            source_gap_count=len(raw.source_gaps),
            critical_gap_count=_critical_gap_count(raw.source_gaps),
            quality_metrics_json=json.dumps(
                {
                    "source_gap_reasons": [gap.reason for gap in raw.source_gaps],
                    "diagnostic_count": len(raw.diagnostics),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    def record_captured_metadata(self, run_id: str, captured: CapturedSources | tuple[RawSourceSnapshot, ...]) -> None:
        snapshots = captured.snapshots if isinstance(captured, CapturedSources) else captured
        self._update_run_metadata(
            run_id,
            source_count=len(snapshots),
            source_hashes=tuple(snapshot.content_sha256 for snapshot in snapshots),
            source_kinds=tuple(snapshot.source_kind for snapshot in snapshots),
        )

    def record_staged_source_snapshots(
        self, run_id: str, snapshots: tuple[RawSourceSnapshot, ...]
    ) -> None:
        """Persist immutable captures without starting a canonical projection."""
        logger.info("staged_source_snapshot_batch_start run_id=%s count=%d", run_id, len(snapshots))
        with self._factory() as session, session.begin():
            run = session.get(IngestRunModel, run_id)
            if run is None or run.status != "running":
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Source discovery ingest run is not running")
            for snapshot in snapshots:
                self._insert_snapshot(session, run_id, snapshot)
            run.source_count = len(snapshots)
            run.source_hashes_json = json.dumps(
                tuple(item.content_sha256 for item in snapshots), separators=(",", ":")
            )
            run.source_kinds_json = json.dumps(
                tuple(item.source_kind for item in snapshots), separators=(",", ":")
            )
            run.heartbeat_at = datetime.now(timezone.utc)
        logger.info("staged_source_snapshot_batch_complete run_id=%s count=%d", run_id, len(snapshots))

    def finish_source_capture_run(self, run_id: str) -> None:
        """Close a capture-only audit run without changing canonical projections."""
        with self._factory() as session, session.begin():
            run = session.get(IngestRunModel, run_id)
            if run is None or run.status != "running":
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Source discovery ingest run is not running")
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = _duration_ms(run.started_at, run.finished_at)
            run.status = "completed"
            run.heartbeat_at = run.finished_at
        logger.info("source_capture_run_complete run_id=%s", run_id)

    def ingest(self, raw: RawTracerBundle, canonical: CanonicalSnapshot, *, run_id: str | None = None) -> str:
        resolved_run_id = run_id or self.start_run(university_id=str(canonical.university.id))
        raw = _bind_admission_benefit_raw_run(raw, resolved_run_id)
        canonical = _bind_admission_benefit_run(canonical, resolved_run_id)
        source_hashes = tuple(snapshot.content_sha256 for snapshot in raw.snapshots)
        source_kinds = tuple(snapshot.source_kind for snapshot in raw.snapshots)
        self._update_run_metadata(
            resolved_run_id,
            source_count=len(source_hashes),
            source_hashes=source_hashes,
            source_kinds=source_kinds,
            program_count=len(canonical.programs),
            curriculum_item_count=sum(len(curriculum.items) for curriculum in canonical.curricula),
            event_count=len(canonical.events),
            campus_point_count=len(canonical.campus_points),
            university_id=canonical.university.id,
            source_gap_count=len(canonical.source_gaps),
            critical_gap_count=_critical_gap_count(canonical.source_gaps),
            drift_status="passed",
            program_ids=tuple(str(program.id) for program in canonical.programs),
            projection_status="running",
        )
        logger.info("ingest_transaction_start run_id=%s", resolved_run_id)
        stats = _SyncStats()
        projection_started = perf_counter()
        with self._factory() as session:
            try:
                with session.begin():
                    self._seed_reference_tables(session)
                    session.flush()
                    for snapshot in raw.snapshots:
                        self._insert_snapshot(session, resolved_run_id, snapshot)
                    session.flush()
                    self._insert_raw_records(session, raw)
                    stats = self._insert_domain(
                        session,
                        canonical,
                        run_id=resolved_run_id,
                        event_source_present=any(snapshot.source_kind == "bmstu_events" for snapshot in raw.snapshots),
                        campus_source_present=any(snapshot.source_kind == "bmstu_campus_points" for snapshot in raw.snapshots),
                    )
                    run = session.get(IngestRunModel, resolved_run_id)
                    if run is None or run.status != "running":
                        raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingest audit row is not running")
                    run.projection_status = "committed"
                    run.heartbeat_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.warning(
                    "ingest_transaction_rollback run_id=%s error_code=%s projection_duration_ms=%d",
                    resolved_run_id,
                    _safe_error_code(exc),
                    _elapsed_ms(projection_started),
                )
                self._mark_failed(resolved_run_id, exc)
                raise
        logger.info(
            "ingest_projection_commit_observed run_id=%s projection_duration_ms=%d source_bytes=%d",
            resolved_run_id,
            _elapsed_ms(projection_started),
            sum(len(snapshot.body) for snapshot in raw.snapshots),
        )
        try:
            self._mark_completed(resolved_run_id, stats)
        except Exception:
            logger.exception("ingest_audit_complete_failed run_id=%s", resolved_run_id)
            raise
        if self._derived_refresh is not None:
            try:
                derived_request = DerivedRefreshRequest(
                    ingest_run_id=resolved_run_id,
                    university_id=canonical.university.id,
                    affected_program_ids=tuple(program.id for program in canonical.programs),
                    source_hashes=tuple(source.content_sha256 for source in canonical.sources if source.content_sha256),
                    semantic_version=SEMANTIC_TAXONOMY_VERSION,
                    classifier_version=SEMANTIC_CLASSIFIER_VERSION,
                    projection_version=ANALYTICS_PROJECTION_SCHEMA_VERSION,
                    programs=canonical.programs,
                    disciplines=canonical.disciplines,
                    curricula=canonical.curricula,
                    admissions=canonical.admissions,
                )
                derived_outcome = self._derived_refresh.refresh(derived_request)
                self._mark_derived_refresh(resolved_run_id, derived_outcome)
                logger.info(
                    "ingest_derived_refresh_observed ingest_run_id=%s status=%s refreshed_programs=%d",
                    resolved_run_id,
                    derived_outcome.status,
                    derived_outcome.refreshed_program_count,
                )
            except Exception as exc:
                self._mark_derived_refresh_failed(resolved_run_id, exc)
                logger.exception("ingest_derived_refresh_failed ingest_run_id=%s", resolved_run_id)
        elif self._semantic_enrichment is not None:
            try:
                derived_run = self._semantic_enrichment.enrich(
                    university_id=canonical.university.id,
                    ingest_run_id=resolved_run_id,
                    curricula=canonical.curricula,
                    disciplines=canonical.disciplines,
                )
                logger.info(
                    "ingest_semantic_enrichment_observed ingest_run_id=%s semantic_run_id=%s status=%s",
                    resolved_run_id,
                    derived_run.id,
                    derived_run.status,
                )
                if self._projection_service is not None:
                    projections = self._projection_service.refresh(canonical, derived_run)
                    logger.info(
                        "ingest_program_projection_observed ingest_run_id=%s program_count=%d",
                        resolved_run_id,
                        len(projections),
                    )
                self._mark_derived_refresh_legacy(resolved_run_id)
            except Exception:
                self._mark_derived_refresh_failed(resolved_run_id, RuntimeError("legacy_derived_refresh_failed"))
                logger.exception("ingest_derived_projection_failed ingest_run_id=%s", resolved_run_id)
        logger.info(
            "ingest_transaction_commit run_id=%s programs=%d curriculum_items=%d inserted=%d updated=%d unchanged=%d removed=%d",
            resolved_run_id,
            len(canonical.programs),
            sum(len(curriculum.items) for curriculum in canonical.curricula),
            stats.inserted,
            stats.updated,
            stats.unchanged,
            stats.removed,
        )
        return resolved_run_id

    def record_quality(
        self,
        run_id: str,
        outcome: QualityOutcome,
        *,
        university_id: str,
        program_ids: tuple[str, ...],
    ) -> None:
        self._update_run_metadata(
            run_id,
            university_id=university_id,
            quality_status=outcome.status,
            quality_metrics_json=json.dumps(dict(outcome.metrics), ensure_ascii=False, separators=(",", ":")),
            previous_good_run_id=outcome.previous_good_run_id,
            program_ids=program_ids,
            drift_status="rejected" if outcome.status == "rejected" else "passed",
        )

    def previous_projection(self, university_id: str) -> PreviousProjection | None:
        with self._factory() as session:
            row = session.scalar(
                select(IngestRunModel)
                .where(IngestRunModel.university_id == university_id, IngestRunModel.status == "completed")
                .order_by(IngestRunModel.finished_at.desc(), IngestRunModel.id.desc())
                .limit(1)
            )
            if row is None:
                return None
            try:
                program_ids = json.loads(row.program_ids_json)
            except json.JSONDecodeError:
                program_ids = []
            if not isinstance(program_ids, list) or not all(isinstance(item, str) for item in program_ids):
                program_ids = []
            return PreviousProjection(
                run_id=row.id,
                university_id=university_id,
                program_count=row.program_count,
                curriculum_item_count=row.curriculum_item_count,
                source_count=row.source_count,
                program_ids=frozenset(program_ids),
            )

    def _update_run_metadata(
        self,
        run_id: str,
        *,
        source_count: int | None = None,
        source_hashes: tuple[str, ...] | None = None,
        source_kinds: tuple[str, ...] | None = None,
        program_count: int | None = None,
        curriculum_item_count: int | None = None,
        event_count: int | None = None,
        campus_point_count: int | None = None,
        university_id: str | None = None,
        source_gap_count: int | None = None,
        critical_gap_count: int | None = None,
        drift_status: str | None = None,
        quality_status: str | None = None,
        quality_metrics_json: str | None = None,
        previous_good_run_id: str | None = None,
        program_ids: tuple[str, ...] | None = None,
        projection_status: str | None = None,
    ) -> None:
        with self._factory() as session:
            with session.begin():
                run = session.get(IngestRunModel, run_id)
                if run is None or run.status != "running":
                    raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingest audit row is not running")
                run.heartbeat_at = datetime.now(timezone.utc)
                if source_count is not None:
                    run.source_count = source_count
                if source_hashes is not None:
                    run.source_hashes_json = json.dumps(source_hashes, separators=(",", ":"))
                if source_kinds is not None:
                    run.source_kinds_json = json.dumps(source_kinds, separators=(",", ":"))
                if program_count is not None:
                    run.program_count = program_count
                if curriculum_item_count is not None:
                    run.curriculum_item_count = curriculum_item_count
                if event_count is not None:
                    run.event_count = event_count
                if campus_point_count is not None:
                    run.campus_point_count = campus_point_count
                if university_id is not None:
                    run.university_id = university_id
                if source_gap_count is not None:
                    run.source_gap_count = source_gap_count
                if critical_gap_count is not None:
                    run.critical_gap_count = critical_gap_count
                if drift_status is not None:
                    run.drift_status = drift_status
                if quality_status is not None:
                    run.quality_status = quality_status
                if quality_metrics_json is not None:
                    run.quality_metrics_json = quality_metrics_json
                if previous_good_run_id is not None:
                    run.previous_good_run_id = previous_good_run_id
                if program_ids is not None:
                    run.program_ids_json = json.dumps(program_ids, separators=(",", ":"))
                if projection_status is not None:
                    run.projection_status = projection_status

    def _create_run(
        self,
        run_id: str,
        started_at: datetime,
        *,
        source_count: int,
        source_hashes: tuple[str, ...],
        source_kinds: tuple[str, ...],
        program_count: int,
        curriculum_item_count: int,
        event_count: int,
        campus_point_count: int,
        source_profile: str,
        source_revision: str,
        configuration_version: str,
        retry_of_run_id: str | None,
        idempotency_key: str | None,
        university_id: str,
        projection_target: str,
    ) -> None:
        with self._factory() as session:
            with session.begin():
                session.add(
                    IngestRunModel(
                        id=run_id,
                        started_at=started_at,
                        status="running",
                        source_count=source_count,
                        source_hashes_json=json.dumps(source_hashes, separators=(",", ":")),
                        source_kinds_json=json.dumps(source_kinds, separators=(",", ":")),
                        program_count=program_count,
                        curriculum_item_count=curriculum_item_count,
                        event_count=event_count,
                        campus_point_count=campus_point_count,
                        university_id=university_id,
                        duration_ms=None,
                        source_gap_count=0,
                        critical_gap_count=0,
                        drift_status="not_checked",
                        source_profile=source_profile,
                        source_revision=source_revision,
                        configuration_version=configuration_version,
                        retry_of_run_id=retry_of_run_id,
                        idempotency_key=idempotency_key,
                        projection_target=projection_target,
                        heartbeat_at=started_at,
                        projection_status="not_started",
                    )
                )

    def _mark_completed(self, run_id: str, stats: _SyncStats) -> None:
        with self._factory() as session:
            with session.begin():
                run = session.get(IngestRunModel, run_id)
                if run is None:
                    raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingest audit row disappeared")
                if run.status != "running":
                    raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingest audit row is not running")
                previous_status = run.projection_status
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)
                run.duration_ms = _duration_ms(run.started_at, run.finished_at)
                run.inserted_count = stats.inserted
                run.updated_count = stats.updated
                run.unchanged_count = stats.unchanged
                run.removed_count = stats.removed
                run.projection_status = "reconciled"
                run.recovery_reason = None
                run.heartbeat_at = run.finished_at
                logger.info(
                    "ingest_run_transition run_id=%s from=running to=completed projection=%s",
                    run_id,
                    previous_status,
                )

    def _mark_derived_refresh(self, run_id: str, outcome: DerivedRefreshOutcome) -> None:
        with self._factory() as session, session.begin():
            run = session.get(IngestRunModel, run_id)
            if run is None:
                raise ContractError(ErrorCode.CONTRACT_ERROR, "Ingest audit row disappeared after derived refresh")
            if outcome.status is DerivedRefreshStatus.COMPLETED:
                run.projection_status = "reconciled"
                run.recovery_reason = None
            else:
                run.projection_status = "failed"
                run.recovery_reason = outcome.recovery_reason or "derived_refresh_incomplete"

    def _mark_derived_refresh_legacy(self, run_id: str) -> None:
        with self._factory() as session, session.begin():
            run = session.get(IngestRunModel, run_id)
            if run is not None:
                run.projection_status = "reconciled"
                run.recovery_reason = None

    def _mark_derived_refresh_failed(self, run_id: str, error: Exception) -> None:
        with self._factory() as session, session.begin():
            run = session.get(IngestRunModel, run_id)
            if run is not None:
                run.projection_status = "failed"
                run.recovery_reason = "derived_refresh_failed"
        logger.warning(
            "ingest_derived_refresh_status_failed run_id=%s error_code=%s",
            run_id,
            type(error).__name__,
        )

    def _mark_failed(self, run_id: str, error: Exception) -> None:
        error_code = _safe_error_code(error)
        error_message = _safe_error_message(error)
        try:
            with self._factory() as session:
                with session.begin():
                    run = session.get(IngestRunModel, run_id)
                    if run is None:
                        logger.error("ingest_audit_failure_missing run_id=%s error_code=%s", run_id, error_code)
                        return
                    run.status = "failed"
                    run.finished_at = datetime.now(timezone.utc)
                    run.duration_ms = _duration_ms(run.started_at, run.finished_at)
                    run.drift_status = "rejected" if error_code == "INGESTION_DRIFT_REJECTED" else run.drift_status
                    run.error_code = error_code
                    run.error_message = error_message
                    if run.projection_status == "committed":
                        run.recovery_reason = "terminal_update_failed"
                    else:
                        run.projection_status = "failed"
                        run.recovery_reason = "projection_transaction_failed"
                    run.heartbeat_at = run.finished_at
                    logger.info(
                        "ingest_run_transition run_id=%s from=running to=failed projection=%s error_code=%s",
                        run_id,
                        run.projection_status,
                        error_code,
                    )
        except Exception:
            logger.exception("ingest_audit_failure_update_failed run_id=%s error_code=%s", run_id, error_code)

    def mark_failed(self, run_id: str, error: Exception) -> None:
        self._mark_failed(run_id, error)

    @staticmethod
    def _seed_reference_tables(session: Session) -> None:
        for level_value in EducationLevel:
            if session.get(EducationLevelModel, level_value.value) is None:
                session.add(EducationLevelModel(id=level_value.value))
        for assessment_value in AssessmentType:
            if session.get(AssessmentTypeModel, assessment_value.value) is None:
                session.add(AssessmentTypeModel(id=assessment_value.value))
        for definition in area_catalog():
            existing = session.get(DisciplineAreaModel, definition.code.value)
            if existing is None:
                session.add(
                    DisciplineAreaModel(
                        id=definition.code.value,
                        name=definition.name,
                        description=definition.description,
                        position=definition.position,
                    )
                )
            elif (
                existing.name != definition.name
                or existing.description != definition.description
                or existing.position != definition.position
            ):
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Identity conflict for discipline area {definition.code.value}")
        for feature in DEFAULT_SEMANTIC_FEATURES:
            semantic_existing = session.get(SemanticFeatureModel, feature.id)
            values = {
                "id": feature.id,
                "code": feature.code,
                "name": feature.name,
                "description": feature.description,
                "feature_group": feature.feature_group.value,
                "value_type": feature.value_type.value,
                "semantic_version": feature.semantic_version,
            }
            if semantic_existing is None:
                session.add(SemanticFeatureModel(**values))
            elif any(getattr(semantic_existing, key) != value for key, value in values.items() if key != "id"):
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Identity conflict for semantic feature {feature.code}")

    @staticmethod
    def _insert_snapshot(session: Session, run_id: str, snapshot: RawSourceSnapshot) -> None:
        existing = session.get(SourceSnapshotModel, snapshot.content_sha256)
        if existing is not None:
            if existing.body != snapshot.body:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Source hash collision with different body")
            return
        session.add(
            SourceSnapshotModel(
                content_sha256=snapshot.content_sha256,
                ingest_run_id=run_id,
                source_kind=snapshot.source_kind,
                requested_url=str(snapshot.requested_url),
                final_url=str(snapshot.final_url),
                status_code=snapshot.status_code,
                content_type=snapshot.content_type,
                captured_at=snapshot.captured_at,
                body=snapshot.body,
            )
        )

    @staticmethod
    def _insert_raw_records(session: Session, raw: RawTracerBundle) -> None:
        hashes_by_url = {str(snapshot.requested_url): snapshot.content_sha256 for snapshot in raw.snapshots}
        raw_directions = raw.directions or (raw.direction,)
        records: list[tuple[str, str, str]] = [
            ("University", raw.university.model_dump_json(), str(raw.university.locator.source_url)),
        ]
        records.extend(("Direction", direction.model_dump_json(), str(direction.locator.source_url)) for direction in raw_directions)
        records.extend(("Program", program.model_dump_json(), str(program.source_url)) for program in raw.programs)
        records.extend(("CurriculumRow", row.model_dump_json(), str(row.source_url)) for row in raw.curriculum_rows)
        records.extend(("Admission", admission.model_dump_json(), str(admission.source_url)) for admission in raw.admissions)
        records.extend(("Event", event.model_dump_json(), str(event.source_url)) for event in raw.events)
        records.extend(("CampusPoint", point.model_dump_json(), str(point.source_url)) for point in raw.campus_points)
        records.extend(
            ("AdmissionBenefit", record.model_dump_json(), str(record.source_url))
            for record in raw.admission_benefit_records
        )
        records.extend(
            ("AdmissionBenefitDiagnostic", diagnostic.model_dump_json(), str(diagnostic.locator.source_url))
            for diagnostic in raw.admission_benefit_diagnostics
        )
        records.extend(
            ("SourceGap", gap.model_dump_json(), str(gap.locator.source_url))
            for gap in raw.source_gaps
            if str(gap.locator.source_url) in hashes_by_url
        )
        skipped_gaps = sum(1 for gap in raw.source_gaps if str(gap.locator.source_url) not in hashes_by_url)
        if skipped_gaps:
            logger.warning("ingest_unlinked_source_gaps count=%d", skipped_gaps)
        for index, (record_type, payload, source_url) in enumerate(records):
            snapshot_hash = hashes_by_url.get(source_url)
            if snapshot_hash is None:
                raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, "Raw record source is not captured")
            record_id = f"{snapshot_hash}:{record_type}:{index}"
            if session.get(RawSourceRecordModel, record_id) is None:
                session.add(RawSourceRecordModel(id=record_id, snapshot_sha256=snapshot_hash, record_type=record_type, payload_json=payload))

    @classmethod
    def _insert_domain(
        cls,
        session: Session,
        canonical: CanonicalSnapshot,
        *,
        run_id: str,
        event_source_present: bool = False,
        campus_source_present: bool = False,
    ) -> _SyncStats:
        stats = _SyncStats()
        stats.record(
            cls._upsert(
                session,
                UniversityModel,
                canonical.university.id,
                {
                    "id": canonical.university.id,
                    "name": canonical.university.name,
                    "city": canonical.university.city,
                    "official_site": str(canonical.university.official_site),
                    "address": canonical.university.address,
                },
                immutable_fields=(),
            )
        )
        session.flush()
        directions = canonical.directions or (canonical.direction,)
        for direction in directions:
            stats.record(
                cls._upsert(
                    session,
                    DirectionModel,
                    direction.id,
                    {
                        "id": direction.id,
                        "university_id": direction.university_id,
                        "code": direction.code,
                        "name": direction.name,
                        "education_level": direction.education_level.value,
                    },
                    immutable_fields=("university_id", "code"),
                )
            )
        session.flush()
        for program in canonical.programs:
            stats.record(
                cls._upsert(
                    session,
                    ProgramModel,
                    program.id,
                    {
                        "id": program.id,
                        "direction_id": program.direction_id,
                        "code": program.code,
                        "name": program.name,
                        "education_year": program.education_year,
                        "study_plan_url": str(program.study_plan_url),
                        "source_url": str(program.source_url),
                        "provenance_json": _provenance_json(program.provenance),
                        "source_gaps_json": _source_gaps_json(program.source_gaps),
                    },
                    immutable_fields=("direction_id", "code"),
                )
            )
        session.flush()
        SqlAlchemyAdmissionRepository(session).sync(canonical.admissions)
        session.flush()
        if canonical.admission_benefits is not None:
            benefit_stats = SqlAlchemyAdmissionBenefitsRepository(session).sync_snapshot(
                canonical.admission_benefits,
                source_run_id=run_id,
            )
            stats.inserted += (
                benefit_stats.olympiads_inserted
                + benefit_stats.profiles_inserted
                + benefit_stats.rules_inserted
                + benefit_stats.achievement_rules_inserted
            )
            stats.unchanged += benefit_stats.unchanged_rows
            stats.removed += benefit_stats.stale_rows
            logger.info(
                "ingest_admission_benefits_projected run_id=%s year=%d rules=%d achievement_rules=%d stale=%d conflicts=%d",
                run_id,
                canonical.admission_benefits.admission_year,
                benefit_stats.rules_inserted,
                benefit_stats.achievement_rules_inserted,
                benefit_stats.stale_rows,
                benefit_stats.conflict_rows,
            )
        session.flush()
        event_stats = SqlAlchemyEventRepository(session).sync(
            canonical.events,
            source_scope="bmstu_events" if event_source_present else None,
        )
        stats.inserted += event_stats.inserted + event_stats.venues
        stats.updated += event_stats.updated
        stats.unchanged += event_stats.unchanged
        stats.removed += event_stats.removed
        session.flush()
        campus_stats = SqlAlchemyCampusPointRepository(session).sync(
            canonical.campus_points,
            source_scope="bmstu_campus_points" if campus_source_present else None,
        )
        stats.inserted += campus_stats.inserted
        stats.updated += campus_stats.updated
        stats.unchanged += campus_stats.unchanged
        stats.removed += campus_stats.removed
        session.flush()
        disciplines_by_id = {discipline.id: discipline for discipline in canonical.disciplines}
        for discipline in canonical.disciplines:
            stats.record(
                cls._upsert(
                    session,
                    DisciplineModel,
                    discipline.id,
                    {"id": discipline.id, "name": discipline.name, "normalized_name": discipline.normalized_name},
                    immutable_fields=("normalized_name",),
                )
            )
        session.flush()
        for discipline in canonical.disciplines:
            cls._sync_discipline_area_weights(session, discipline.id, discipline.area_weights, stats)
        session.flush()
        expected_item_ids: dict[str, set[str]] = {}
        pending_assessments: dict[str, set[str]] = {}
        for curriculum in canonical.curricula:
            stats.record(
                cls._upsert(
                    session,
                    CurriculumModel,
                    curriculum.id,
                    {
                        "id": curriculum.id,
                        "program_id": curriculum.program_id,
                        "education_year": curriculum.education_year,
                        "source_url": str(curriculum.source_url),
                        "captured_at": curriculum.captured_at,
                        "provenance_json": _provenance_json(curriculum.provenance),
                        "source_gaps_json": _source_gaps_json(curriculum.source_gaps),
                    },
                    immutable_fields=("program_id", "education_year"),
                )
            )
            expected_item_ids[curriculum.id] = set()
        # Models intentionally have no ORM relationships. Flush all parent
        # curricula before inserting child items so SQLite and PostgreSQL see
        # the same FK ordering.
        session.flush()
        for curriculum in canonical.curricula:
            for item in curriculum.items:
                if item.discipline_id not in disciplines_by_id:
                    raise ContractError(ErrorCode.CONTRACT_ERROR, "Curriculum item discipline is missing")
                expected_item_ids[curriculum.id].add(item.id)
                stats.record(
                    cls._upsert(
                        session,
                        CurriculumItemModel,
                        item.id,
                        {
                            "id": item.id,
                            "curriculum_id": curriculum.id,
                            "discipline_id": item.discipline_id,
                            "source_name": item.source_name,
                            "semester": item.semester,
                            "semester_identity": _semester_identity(item.semester),
                            "hours": item.hours,
                            "credits": item.credits,
                            "source_position": item.source_position,
                            "lecture_hours": item.lecture_hours,
                            "practice_hours": item.practice_hours,
                            "lab_hours": item.lab_hours,
                            "self_study_hours": item.self_study_hours,
                            "is_elective": item.is_elective,
                            "course_block": item.course_block,
                            "practice_type": item.practice_type,
                        },
                        immutable_fields=("curriculum_id", "discipline_id", "semester", "semester_identity"),
                    )
                )
                pending_assessments[item.id] = {assessment.value for assessment in item.assessment_types or ()}
        session.flush()
        cls._remove_stale_items(session, expected_item_ids, stats)
        session.flush()
        cls._sync_item_source_links(session, canonical, run_id)
        session.flush()
        cls._sync_assessments(session, pending_assessments, stats)
        return stats

    @staticmethod
    def _sync_item_source_links(session: Session, canonical: CanonicalSnapshot, run_id: str) -> None:
        inserted = 0
        updated = 0
        for curriculum in canonical.curricula:
            for item in curriculum.items:
                for attribution in item.provenance:
                    link_id = _curriculum_item_source_link_id(item.id, attribution)
                    existing = session.get(CurriculumItemSourceLinkModel, link_id)
                    link_run_id = attribution.run_id or run_id
                    if existing is None:
                        session.add(
                            CurriculumItemSourceLinkModel(
                                link_id=link_id,
                                curriculum_item_id=item.id,
                                source_sha256=attribution.content_sha256,
                                source_url=str(attribution.url),
                                locator=attribution.locator,
                                university_id=attribution.university_id,
                                field=attribution.field,
                                record_key=attribution.record_key,
                                inferred=attribution.inferred,
                                ingest_run_id=link_run_id,
                                created_at=datetime.now(timezone.utc),
                            )
                        )
                        inserted += 1
                    elif existing.ingest_run_id != link_run_id:
                        existing.ingest_run_id = link_run_id
                        updated += 1
        logger.info("ingest_curriculum_source_links_sync run_id=%s inserted=%d updated=%d", run_id, inserted, updated)

    @staticmethod
    def _upsert(
        session: Session,
        model: type[Any],
        identity: str,
        values: dict[str, object],
        *,
        immutable_fields: tuple[str, ...],
    ) -> str:
        existing = session.get(model, identity)
        if existing is None:
            session.add(model(**values))
            logger.debug("ingest_projection_insert model=%s identity=%s", model.__name__, identity)
            return "inserted"
        immutable = set(immutable_fields)
        changed: list[str] = []
        for field, expected in values.items():
            if field == "id":
                continue
            actual = getattr(existing, field)
            if not _values_equal(actual, expected):
                if field in immutable:
                    logger.error("ingest_identity_conflict model=%s identity=%s field=%s", model.__name__, identity, field)
                    raise ContractError(ErrorCode.SOURCE_CONTRACT_ERROR, f"Identity conflict for {identity}: {field}")
                setattr(existing, field, expected)
                changed.append(field)
        if changed:
            logger.debug("ingest_projection_update model=%s identity=%s fields=%s", model.__name__, identity, ",".join(changed))
            return "updated"
        return "unchanged"

    @staticmethod
    def _remove_stale_items(session: Session, expected_item_ids: dict[str, set[str]], stats: _SyncStats) -> None:
        for curriculum_id, expected_ids in expected_item_ids.items():
            existing_ids = set(
                session.scalars(
                    select(CurriculumItemModel.id).where(CurriculumItemModel.curriculum_id == curriculum_id)
                ).all()
            )
            stale_ids = existing_ids - expected_ids
            if stale_ids:
                session.execute(delete(CurriculumItemAssessmentModel).where(CurriculumItemAssessmentModel.curriculum_item_id.in_(stale_ids)))
                session.execute(delete(CurriculumItemModel).where(CurriculumItemModel.id.in_(stale_ids)))
                stats.removed += len(stale_ids)
                logger.warning("ingest_projection_remove_stale curriculum_id=%s count=%d", curriculum_id, len(stale_ids))

    @staticmethod
    def _sync_assessments(session: Session, expected: dict[str, set[str]], stats: _SyncStats) -> None:
        for item_id, expected_types in expected.items():
            current_rows = session.execute(
                select(CurriculumItemAssessmentModel).where(CurriculumItemAssessmentModel.curriculum_item_id == item_id)
            ).scalars().all()
            current_types = {row.assessment_type_id for row in current_rows}
            stale_types = current_types - expected_types
            if stale_types:
                session.execute(
                    delete(CurriculumItemAssessmentModel).where(
                        CurriculumItemAssessmentModel.curriculum_item_id == item_id,
                        CurriculumItemAssessmentModel.assessment_type_id.in_(stale_types),
                    )
                )
                stats.removed += len(stale_types)
            for assessment_type_id in expected_types - current_types:
                session.add(CurriculumItemAssessmentModel(curriculum_item_id=item_id, assessment_type_id=assessment_type_id))
                stats.inserted += 1

    @staticmethod
    def _sync_discipline_area_weights(
        session: Session,
        discipline_id: str,
        area_weights: tuple[DisciplineAreaWeight, ...],
        stats: _SyncStats,
    ) -> None:
        expected = {weight.area.value: weight.weight for weight in area_weights}
        existing_rows = session.execute(
            select(DisciplineAreaWeightModel).where(DisciplineAreaWeightModel.discipline_id == discipline_id)
        ).scalars().all()
        existing = {row.area_id: row for row in existing_rows}
        for area_id in set(existing) - set(expected):
            session.delete(existing[area_id])
            stats.removed += 1
        for area_id, weight in expected.items():
            row = existing.get(area_id)
            if row is None:
                session.add(DisciplineAreaWeightModel(discipline_id=discipline_id, area_id=area_id, weight=weight))
                stats.inserted += 1
            elif not _values_equal(row.weight, weight):
                row.weight = weight
                stats.updated += 1
        logger.debug("ingest_taxonomy_sync discipline_id=%s expected_areas=%d", discipline_id, len(expected))

    @staticmethod
    def _insert_or_validate(session: Session, model: type[Any], identity: str, values: dict[str, object]) -> None:
        """Compatibility shim for older callers; new writes use _upsert."""
        SqlAlchemyIngestionRepository._upsert(session, model, identity, values, immutable_fields=tuple(values))


def _semester_identity(semester: int | None) -> str:
    return "unassigned" if semester is None else f"semester:{semester}"


def _bind_admission_benefit_raw_run(raw: RawTracerBundle, run_id: str) -> RawTracerBundle:
    if not raw.admission_benefit_records:
        return raw
    return raw.model_copy(
        update={
            "admission_benefit_records": tuple(
                record.model_copy(update={"source_run_id": run_id})
                for record in raw.admission_benefit_records
            )
        }
    )


def _bind_admission_benefit_run(canonical: CanonicalSnapshot, run_id: str) -> CanonicalSnapshot:
    snapshot = canonical.admission_benefits
    if snapshot is None:
        return canonical

    def bind_provenance(value: Any) -> Any:
        return value.model_copy(
            update={
                "source_run_id": run_id,
                "source": value.source.model_copy(update={"run_id": run_id}),
            }
        )

    olympiads = tuple(
        value.model_copy(update={"provenance": tuple(bind_provenance(item) for item in value.provenance)})
        for value in snapshot.olympiads
    )
    profiles = tuple(
        value.model_copy(update={"provenance": tuple(bind_provenance(item) for item in value.provenance)})
        for value in snapshot.olympiad_profiles
    )
    rules = tuple(
        value.model_copy(update={"provenance": bind_provenance(value.provenance)})
        for value in snapshot.benefit_rules
    )
    policy = snapshot.individual_achievement_policy
    if policy is not None:
        policy = policy.model_copy(
            update={
                "provenance": bind_provenance(policy.provenance),
                "rules": tuple(
                    value.model_copy(update={"provenance": bind_provenance(value.provenance)})
                    for value in policy.rules
                ),
            }
        )
    rebound = snapshot.model_copy(
        update={
            "sources": tuple(source.model_copy(update={"run_id": run_id}) for source in snapshot.sources),
            "olympiads": olympiads,
            "olympiad_profiles": profiles,
            "benefit_rules": rules,
            "individual_achievement_policy": policy,
        }
    )
    return canonical.model_copy(update={"admission_benefits": rebound})


def _curriculum_item_source_link_id(item_id: str, attribution: SourceAttribution) -> str:
    identity = "|".join(
        (
            item_id,
            attribution.content_sha256,
            str(attribution.url),
            attribution.locator or "",
            attribution.university_id or "",
            attribution.field or "",
            attribution.record_key or "",
            str(attribution.inferred),
        )
    )
    return f"curriculum-item-source:{sha256(identity.encode('utf-8')).hexdigest()}"


def _provenance_json(values: tuple[SourceAttribution, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _source_gaps_json(values: tuple[SourceGapReference, ...]) -> str:
    return json.dumps([value.model_dump(mode="json") for value in values], ensure_ascii=False, separators=(",", ":"))


def _values_equal(actual: object, expected: object) -> bool:
    """Compare persisted values without treating SQLite's timezone loss as drift."""
    if expected == "unassigned" and isinstance(actual, str) and actual.startswith("legacy:"):
        # 0002 preserves pre-existing nullable-semester duplicates with a stable
        # legacy identity. The canonical snapshot has one unassigned item, so
        # the primary key remains the authoritative identity on re-ingest.
        return True
    if isinstance(actual, datetime) and isinstance(expected, datetime):
        actual_utc = actual.replace(tzinfo=timezone.utc) if actual.tzinfo is None else actual.astimezone(timezone.utc)
        expected_utc = expected.replace(tzinfo=timezone.utc) if expected.tzinfo is None else expected.astimezone(timezone.utc)
        return actual_utc == expected_utc
    return actual == expected or str(actual) == str(expected)


def _safe_error_code(error: Exception) -> str:
    if "INGESTION_DRIFT_REJECTED" in str(error):
        return "INGESTION_DRIFT_REJECTED"
    if isinstance(error, AndromedaError):
        return error.code.value
    return "INGESTION_FAILED"


def _safe_error_message(error: Exception) -> str:
    del error
    return "Ingestion failed"


def _critical_gap_count(gaps: tuple[Any, ...]) -> int:
    return sum(1 for gap in gaps if is_critical_gap(gap.reason))


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    started = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=timezone.utc)
    finished = finished_at if finished_at.tzinfo is not None else finished_at.replace(tzinfo=timezone.utc)
    return max(0, int((finished - started).total_seconds() * 1000))


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))
