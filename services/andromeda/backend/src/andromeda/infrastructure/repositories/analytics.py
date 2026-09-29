"""Batch SQLAlchemy adapter for rebuildable analytical projections."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import delete, insert, select, update

from andromeda.modules.admissions.contracts.public import AdmissionOffering
from andromeda.modules.analytics.contracts.public import (
    ProgramProjection,
    ProgramProjectionRun,
    ProjectionRunStatus,
    ProjectionBuild,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    ProjectionMetricEvidence,
    ProjectionMaterializationStatus,
    ProjectionTimeline,
    WorkloadSummary,
)
from andromeda.modules.analytics.contracts.query import FilterKind, FilterOperator, QueryScope, QuerySpec
from andromeda.modules.analytics.domain.metric_registry import MetricRegistry
from andromeda.modules.analytics.domain.basis import MetricBasis
from andromeda.modules.analytics.repository.ports import (
    ProgramProjectionReader,
    ProgramProjectionStore,
)
from andromeda.modules.analytics.repository.queries import ProjectionQueryReader
from andromeda.modules.semantic.contracts.public import (
    SemanticClassificationEvidence,
)
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from ..database.models import (
    ProgramMetricEvidenceModel,
    ProgramMetricModel,
    ProgramProjectionModel,
    ProgramProjectionRunModel,
)
from ..database.session import session_factory


class SqlAlchemyProgramProjectionRepository(ProgramProjectionStore, ProgramProjectionReader, ProjectionQueryReader):
    def __init__(self, engine: Any) -> None:
        self._factory = session_factory(engine)

    def save(self, builds: Iterable[ProjectionBuild]) -> None:
        builds_tuple = tuple(builds)
        if not builds_tuple:
            return
        program_ids = tuple(build.projection.program_id for build in builds_tuple)
        with self._factory() as session, session.begin():
            session.execute(delete(ProgramMetricEvidenceModel).where(ProgramMetricEvidenceModel.program_id.in_(program_ids)))
            session.execute(delete(ProgramMetricModel).where(ProgramMetricModel.program_id.in_(program_ids)))
            session.execute(delete(ProgramProjectionModel).where(ProgramProjectionModel.program_id.in_(program_ids)))
            session.execute(insert(ProgramProjectionModel), [_projection_mapping(build.projection) for build in builds_tuple])
            metric_rows = [
                _metric_mapping(build.projection.program_id, build.projection, metric)
                for build in builds_tuple
                for metric in build.projection.semantic_features.values()
            ]
            if metric_rows:
                session.execute(insert(ProgramMetricModel), metric_rows)
            evidence_rows = [
                _evidence_mapping(build, evidence)
                for build in builds_tuple
                for evidence in build.evidence
            ]
            if evidence_rows:
                session.execute(insert(ProgramMetricEvidenceModel), evidence_rows)

    def get(self, program_id: str) -> ProgramProjection | None:
        return next(iter(self.list(program_ids=(program_id,))), None)

    def read_by_program_ids(self, program_ids: tuple[str, ...]) -> tuple[ProgramProjection, ...]:
        return self.list(program_ids=program_ids)

    def query(self, spec: QuerySpec, *, registry: Any | None = None) -> tuple[ProgramProjection, ...]:
        """Select eligible materialized projections in SQL before hydration.

        The executor still performs typed result shaping/aggregation, but this
        boundary ensures scope and metric-threshold predicates never require
        loading unrelated curriculum rows into Python.
        """

        selected_registry = registry or MetricRegistry()
        with self._factory() as session:
            query = select(ProgramProjectionModel).where(
                ProgramProjectionModel.materialization_status == "active"
            )
            if spec.scope is QueryScope.UNIVERSITY:
                query = query.where(ProgramProjectionModel.university_id.in_(spec.scope_ids))
            elif spec.scope is QueryScope.DIRECTION:
                query = query.where(ProgramProjectionModel.direction_id.in_(spec.scope_ids))
            elif spec.scope is QueryScope.PROGRAM:
                query = query.where(ProgramProjectionModel.program_id.in_(spec.scope_ids))
            for query_filter in spec.filters:
                if query_filter.kind is FilterKind.UNIVERSITY:
                    query = query.where(ProgramProjectionModel.university_id.in_(query_filter.ids))
                elif query_filter.kind is FilterKind.DIRECTION:
                    query = query.where(ProgramProjectionModel.direction_id.in_(query_filter.ids))
                elif query_filter.kind is FilterKind.PROGRAM:
                    query = query.where(ProgramProjectionModel.program_id.in_(query_filter.ids))
                elif query_filter.kind is FilterKind.METRIC_THRESHOLD:
                    definition = selected_registry.get(query_filter.metric_code or "", entity_type=spec.entity)
                    source_code = definition.source_feature_code or definition.code
                    query = query.where(
                        select(ProgramMetricModel.program_id)
                        .where(
                            ProgramMetricModel.program_id == ProgramProjectionModel.program_id,
                            ProgramMetricModel.metric_code == source_code,
                            _metric_predicate(ProgramMetricModel.value, query_filter.operator, query_filter.threshold),
                        )
                        .exists()
                    )
                elif query_filter.kind is FilterKind.SEMANTIC_THRESHOLD:
                    query = query.where(
                        select(ProgramMetricModel.program_id)
                        .where(
                            ProgramMetricModel.program_id == ProgramProjectionModel.program_id,
                            ProgramMetricModel.metric_code == (query_filter.feature_code or ""),
                            _metric_predicate(ProgramMetricModel.value, query_filter.operator, query_filter.threshold),
                        )
                        .exists()
                    )
            projection_rows = tuple(session.scalars(query.order_by(ProgramProjectionModel.program_code)).all())
            if not projection_rows:
                return ()
            program_ids = tuple(row.program_id for row in projection_rows)
            metric_rows = session.scalars(
                select(ProgramMetricModel).where(ProgramMetricModel.program_id.in_(program_ids))
            ).all()
        metrics_by_program: dict[str, list[ProgramMetricModel]] = defaultdict(list)
        for row in metric_rows:
            metrics_by_program[row.program_id].append(row)
        return tuple(_to_projection(row, metrics_by_program.get(row.program_id, ())) for row in projection_rows)

    def mark_stale(self, program_ids: tuple[str, ...]) -> None:
        if not program_ids:
            return
        with self._factory() as session, session.begin():
            session.execute(
                update(ProgramProjectionModel)
                .where(ProgramProjectionModel.program_id.in_(program_ids))
                .values(materialization_status="stale")
            )

    def start_run(self, run: ProgramProjectionRun) -> ProgramProjectionRun:
        with self._factory() as session, session.begin():
            row = session.get(ProgramProjectionRunModel, run.id)
            if row is None:
                session.add(_run_mapping(run))
            else:
                row.status = run.status.value
                row.started_at = run.started_at
                row.finished_at = run.finished_at
            session.flush()
            return _to_run(session.get(ProgramProjectionRunModel, run.id))

    def complete_run(self, run_id: str, *, refreshed_program_count: int) -> ProgramProjectionRun:
        return self._finish_run(run_id, ProjectionRunStatus.COMPLETED, refreshed_program_count=refreshed_program_count)

    def fail_run(self, run_id: str, *, error_code: str, error_message: str) -> ProgramProjectionRun:
        with self._factory() as session, session.begin():
            row = session.get(ProgramProjectionRunModel, run_id)
            if row is None:
                raise ValueError(f"projection run does not exist: {run_id}")
            row.status = ProjectionRunStatus.FAILED.value
            row.finished_at = datetime.now(UTC)
            row.error_code = error_code[:64]
            row.error_message = error_message[:512]
            session.flush()
            return _to_run(row)

    def _finish_run(self, run_id: str, status: ProjectionRunStatus, *, refreshed_program_count: int) -> ProgramProjectionRun:
        with self._factory() as session, session.begin():
            row = session.get(ProgramProjectionRunModel, run_id)
            if row is None:
                raise ValueError(f"projection run does not exist: {run_id}")
            row.status = status.value
            row.refreshed_program_count = refreshed_program_count
            row.finished_at = datetime.now(UTC)
            session.flush()
            return _to_run(row)

    def list(self, *, program_ids: tuple[str, ...] = ()) -> tuple[ProgramProjection, ...]:
        with self._factory() as session:
            query = select(ProgramProjectionModel)
            if program_ids:
                query = query.where(ProgramProjectionModel.program_id.in_(program_ids))
            query = query.where(ProgramProjectionModel.materialization_status == ProjectionMaterializationStatus.ACTIVE.value)
            projection_rows = session.scalars(query.order_by(ProgramProjectionModel.program_code)).all()
            if not projection_rows:
                return ()
            ids = tuple(row.program_id for row in projection_rows)
            metric_rows = session.scalars(select(ProgramMetricModel).where(ProgramMetricModel.program_id.in_(ids))).all()
        metrics_by_program: dict[str, list[ProgramMetricModel]] = defaultdict(list)
        for row in metric_rows:
            metrics_by_program[row.program_id].append(row)
        return tuple(_to_projection(row, metrics_by_program.get(row.program_id, ())) for row in projection_rows)

    def evidence(
        self,
        program_ids: tuple[str, ...],
        *,
        metric_codes: tuple[str, ...],
        schema_version: str,
    ) -> tuple[ProjectionMetricEvidence, ...]:
        if not program_ids or not metric_codes:
            return ()
        with self._factory() as session:
            rows = session.scalars(
                select(ProgramMetricEvidenceModel).where(
                    ProgramMetricEvidenceModel.program_id.in_(program_ids),
                    ProgramMetricEvidenceModel.metric_code.in_(metric_codes),
                    ProgramMetricEvidenceModel.schema_version == schema_version,
                )
            ).all()
        return tuple(_to_evidence(row) for row in rows)


def _projection_mapping(projection: ProgramProjection) -> dict[str, object]:
    quality = projection.quality
    return {
        "program_id": projection.program_id,
        "university_id": projection.university_id,
        "direction_id": projection.direction_id,
        "program_code": projection.program_code,
        "program_name": projection.program_name,
        "schema_version": projection.schema_version,
        "basis": projection.workload.basis.value,
        "total_hours": projection.workload.total_hours,
        "total_credits": projection.workload.total_credits,
        "total_workload": projection.workload.total_workload,
        "academic_areas_json": _dump(projection.academic_areas),
        "timeline_json": _dump(projection.timeline),
        "activity_signals_json": _dump(projection.activity_signals),
        "assessment_json": _dump(projection.assessment),
        "admission_offerings_json": _dump(projection.admission_offerings),
        "distinctive_subjects_json": _dump(projection.distinctive_subjects),
        "quality_status": quality.status.value,
        "coverage": quality.coverage,
        "confidence": quality.confidence,
        "freshness_at": quality.freshness_at or datetime.now(UTC),
        "semantic_version": quality.semantic_version,
        "classifier_version": quality.classifier_version,
        "ingest_run_id": projection.ingest_run_id,
        "provenance_json": _dump(projection.provenance),
        "source_gaps_json": _dump(projection.source_gaps),
        "built_at": datetime.now(UTC),
        "projection_run_id": projection.projection_run_id,
        "input_hash": projection.input_hash,
        "materialization_status": projection.materialization_status.value,
    }


def _metric_predicate(column: Any, operator: FilterOperator, threshold: Any) -> Any:
    if threshold is None:
        raise ValueError("metric threshold is required")
    return {
        FilterOperator.EQ: column == threshold,
        FilterOperator.GT: column > threshold,
        FilterOperator.GTE: column >= threshold,
        FilterOperator.LT: column < threshold,
        FilterOperator.LTE: column <= threshold,
    }[operator]


def _run_mapping(run: ProgramProjectionRun) -> ProgramProjectionRunModel:
    return ProgramProjectionRunModel(
        id=run.id,
        ingest_run_id=run.ingest_run_id,
        university_id=run.university_id,
        projection_version=run.projection_version,
        semantic_version=run.semantic_version,
        classifier_version=run.classifier_version,
        input_hash=run.input_hash,
        status=run.status.value,
        affected_program_count=run.affected_program_count,
        refreshed_program_count=run.refreshed_program_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_code=run.error_code,
        error_message=run.error_message,
    )


def _to_run(row: ProgramProjectionRunModel | None) -> ProgramProjectionRun:
    if row is None:
        raise ValueError("projection run does not exist")
    return ProgramProjectionRun(
        id=row.id,
        ingest_run_id=row.ingest_run_id,
        university_id=row.university_id,
        projection_version=row.projection_version,
        semantic_version=row.semantic_version,
        classifier_version=row.classifier_version,
        input_hash=row.input_hash,
        status=ProjectionRunStatus(row.status),
        affected_program_count=row.affected_program_count,
        refreshed_program_count=row.refreshed_program_count,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _metric_mapping(program_id: str, projection: ProgramProjection, metric: ProjectionMetric) -> dict[str, object]:
    return {
        "program_id": program_id,
        "metric_code": metric.code,
        "schema_version": projection.schema_version,
        "value": metric.value,
        "unit": metric.unit,
        "basis": metric.basis.value if metric.basis else None,
        "coverage": metric.coverage,
        "confidence": metric.confidence,
        "status": metric.status.value,
        "semantic_version": projection.quality.semantic_version,
        "classifier_version": projection.quality.classifier_version,
        "provenance_json": _dump(metric.provenance),
        "source_gaps_json": _dump(metric.source_gaps),
        "built_at": datetime.now(UTC),
    }


def _evidence_mapping(build: ProjectionBuild, evidence: ProjectionMetricEvidence) -> dict[str, object]:
    key = f"{build.projection.program_id}:{evidence.metric_code}:{evidence.curriculum_item_id}:{evidence.feature_id}:{evidence.schema_version}"
    return {
        "id": f"projection-evidence:{sha256(key.encode('utf-8')).hexdigest()[:32]}",
        "program_id": evidence.program_id,
        "metric_code": evidence.metric_code,
        "schema_version": evidence.schema_version,
        "curriculum_item_id": evidence.curriculum_item_id,
        "feature_id": evidence.feature_id,
        "contribution": evidence.contribution,
        "source_hash": evidence.source_hash,
        "evidence_json": _dump(evidence.evidence),
        "provenance_json": _dump(evidence.provenance),
    }


def _to_projection(row: ProgramProjectionModel, metrics: Iterable[ProgramMetricModel]) -> ProgramProjection:
    metric_values = {
        metric.metric_code: ProjectionMetric(
            code=metric.metric_code,
            value=metric.value,
            unit=metric.unit,
            basis=MetricBasis(metric.basis) if metric.basis else None,
            coverage=metric.coverage,
            confidence=metric.confidence,
            status=ProjectionDataQualityStatus(metric.status),
            provenance=tuple(SourceAttribution.model_validate(item, strict=False) for item in _load_list(metric.provenance_json)),
            source_gaps=tuple(SourceGapReference.model_validate(item, strict=False) for item in _load_list(metric.source_gaps_json)),
        )
        for metric in metrics
    }
    return ProgramProjection.model_validate(
        {
            "schema_version": row.schema_version,
            "program_id": row.program_id,
            "university_id": row.university_id,
            "direction_id": row.direction_id,
            "program_code": row.program_code,
            "program_name": row.program_name,
            "workload": WorkloadSummary(
                total_hours=row.total_hours,
                total_credits=row.total_credits,
                total_workload=row.total_workload,
                basis=MetricBasis(row.basis),
            ),
            "academic_areas": json.loads(row.academic_areas_json),
            "semantic_features": metric_values,
            "timeline": ProjectionTimeline.model_validate(json.loads(row.timeline_json), strict=False),
            "activity_signals": json.loads(row.activity_signals_json),
            "assessment": json.loads(row.assessment_json),
            "admission_offerings": tuple(
                AdmissionOffering.model_validate(item, strict=False)
                for item in _load_list(row.admission_offerings_json)
            ),
            "distinctive_subjects": tuple(_load_list(row.distinctive_subjects_json)),
            "quality": ProjectionDataQuality(
                status=ProjectionDataQualityStatus(row.quality_status),
                coverage=row.coverage,
                confidence=row.confidence,
                freshness_at=row.freshness_at,
                semantic_version=row.semantic_version,
                classifier_version=row.classifier_version,
            ),
            "provenance": tuple(SourceAttribution.model_validate(item, strict=False) for item in _load_list(row.provenance_json)),
            "source_gaps": tuple(SourceGapReference.model_validate(item, strict=False) for item in _load_list(row.source_gaps_json)),
            "ingest_run_id": row.ingest_run_id,
            "projection_run_id": row.projection_run_id,
            "input_hash": row.input_hash,
            "materialization_status": row.materialization_status,
        },
        strict=False,
    )


def _to_evidence(row: ProgramMetricEvidenceModel) -> ProjectionMetricEvidence:
    if row.curriculum_item_id is None or row.feature_id is None:
        raise ValueError("projection evidence must reference a curriculum item and semantic feature")
    evidence = json.loads(row.evidence_json)
    provenance = json.loads(row.provenance_json)
    return ProjectionMetricEvidence(
        program_id=row.program_id,
        metric_code=row.metric_code,
        schema_version=row.schema_version,
        curriculum_item_id=row.curriculum_item_id,
        feature_id=row.feature_id,
        contribution=row.contribution,
        source_hash=row.source_hash,
        evidence=tuple(SemanticClassificationEvidence.model_validate(item, strict=False) for item in evidence),
        provenance=tuple(SourceAttribution.model_validate(item, strict=False) for item in provenance),
    )


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        value = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("projection JSON value must be a list")
    return parsed


__all__ = ["SqlAlchemyProgramProjectionRepository"]
