"""Deterministic materialization of shared program analytics projections."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

from andromeda.modules.admissions.contracts.public import ProgramAdmissions
from andromeda.modules.analytics.contracts.public import ACTIVITY_SIGNAL_WEIGHTS
from andromeda.modules.curricula.contracts.public import Curriculum, CurriculumItem
from andromeda.modules.disciplines.contracts.public import Discipline, DisciplineAreaCode
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.semantic.contracts.public import (
    CurriculumItemSemanticFeature,
    SemanticEnrichmentRun,
    SemanticValueStatus,
)
from andromeda.modules.semantic.repository.ports import SemanticEnrichmentStore
from andromeda.shared.contracts.enums import AssessmentType
from andromeda.shared.contracts.ids import DisciplineId, IngestRunId
from andromeda.shared.contracts.provenance import SourceAttribution
from andromeda.shared.contracts.versions import ANALYTICS_PROJECTION_SCHEMA_VERSION

from ..contracts.public import (
    AssessmentSummary,
    ProgramProjection,
    ProjectionBuild,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    ProjectionMetricEvidence,
    ProjectionTimeline,
    WorkloadSummary,
)
from ..repository.ports import ProgramProjectionStore

logger = logging.getLogger("andromeda.program_analytics.projection")
ZERO = Decimal("0")
ONE = Decimal("1")


class ProgramProjectionBuilder:
    """Build one projection from canonical records and semantic assignments."""

    def build(
        self,
        program: Program,
        curriculum: Curriculum,
        disciplines: Mapping[DisciplineId, Discipline],
        semantic_features: Mapping[str, tuple[CurriculumItemSemanticFeature, ...]],
        *,
        ingest_run_id: IngestRunId | None = None,
        admissions: ProgramAdmissions | None = None,
    ) -> ProjectionBuild:
        total_hours = sum(item.hours for item in curriculum.items)
        credits = tuple(item.credits for item in curriculum.items if item.credits is not None)
        total_credits = sum(credits, ZERO) if credits else None
        basis = "hours" if total_hours > 0 else "credits"
        total_workload = Decimal(total_hours) if basis == "hours" else total_credits

        area_workload: dict[DisciplineAreaCode, Decimal] = defaultdict(lambda: ZERO)
        semester_workload: dict[str, Decimal] = defaultdict(lambda: ZERO)
        activity_workload: dict[str, Decimal] = defaultdict(lambda: ZERO)
        assessment_counts: defaultdict[str, int] = defaultdict(int)
        item_workloads: dict[str, Decimal] = {}
        for item in curriculum.items:
            discipline = disciplines.get(item.discipline_id)
            if discipline is None:
                raise ValueError(f"curriculum item discipline is missing: {item.discipline_id}")
            item_workload = Decimal(item.hours) if basis == "hours" else (item.credits or ZERO)
            item_workloads[item.id] = item_workload
            for weight in discipline.area_weights:
                area_workload[weight.area] += item_workload * weight.weight
                for signal, signal_weight in ACTIVITY_SIGNAL_WEIGHTS[weight.area].items():
                    activity_workload[signal.value] += item_workload * weight.weight * signal_weight
            semester_workload[str(item.semester) if item.semester is not None else "unassigned"] += item_workload
            for assessment in item.assessment_types or ():
                assessment_counts[assessment.value] += 1

        semantic_metrics, evidence = self._semantic_metrics(
            program,
            curriculum.items,
            item_workloads,
            semantic_features,
            total_workload,
            basis,
        )
        feature_by_semester, first_feature_semester = _semantic_timeline(
            curriculum.items,
            item_workloads,
            semantic_features,
            total_workload,
        )
        versions = tuple(value.feature.semantic_version for values in semantic_features.values() for value in values)
        classifier_versions = tuple(value.feature.classifier_version for values in semantic_features.values() for value in values)
        coverage = _semantic_coverage(semantic_metrics)
        status = (
            ProjectionDataQualityStatus.UNAVAILABLE
            if not semantic_features
            else ProjectionDataQualityStatus.AVAILABLE
            if coverage == ONE
            else ProjectionDataQualityStatus.PARTIAL
            if coverage > ZERO
            else ProjectionDataQualityStatus.INSUFFICIENT_DATA
        )
        projection = ProgramProjection(
            program_id=program.id,
            university_id=_university_id(program),
            direction_id=program.direction_id,
            program_code=program.code,
            program_name=program.name,
            workload=WorkloadSummary(
                total_hours=total_hours,
                total_credits=total_credits,
                total_workload=total_workload,
                basis=cast(Any, basis),
            ),
            academic_areas=_shares(area_workload, total_workload),
            semantic_features=semantic_metrics,
            timeline=ProjectionTimeline(
                by_semester=_shares(semester_workload, total_workload),
                by_course_year={},
                feature_by_semester=feature_by_semester,
                first_feature_semester=first_feature_semester,
            ),
            activity_signals=_shares(activity_workload, total_workload),
            assessment=AssessmentSummary(
                exam_count=assessment_counts.get(AssessmentType.EXAM.value, 0),
                credit_count=assessment_counts.get(AssessmentType.CREDIT.value, 0),
                graded_count=assessment_counts.get(AssessmentType.GRADED_CREDIT.value, 0),
                unknown_count=None,
            ),
            admission_offerings=admissions.offerings if admissions is not None else (),
            quality=ProjectionDataQuality(
                status=status,
                coverage=coverage,
                confidence=_semantic_confidence(semantic_metrics),
                semantic_version=versions[0] if versions else None,
                classifier_version=classifier_versions[0] if classifier_versions else None,
            ),
            provenance=(*program.provenance, *curriculum.provenance),
            source_gaps=(*program.source_gaps, *curriculum.source_gaps),
            ingest_run_id=ingest_run_id,
        )
        logger.info(
            "program_projection_built program_id=%s item_count=%d basis=%s metric_count=%d quality=%s",
            program.id,
            len(curriculum.items),
            basis,
            len(semantic_metrics),
            status,
        )
        return ProjectionBuild(projection=projection, evidence=tuple(evidence))

    @staticmethod
    def _semantic_metrics(
        program: Program,
        items: tuple[CurriculumItem, ...],
        item_workloads: Mapping[str, Decimal],
        semantic_features: Mapping[str, tuple[CurriculumItemSemanticFeature, ...]],
        total_workload: Decimal | None,
        basis: str,
    ) -> tuple[dict[str, ProjectionMetric], list[ProjectionMetricEvidence]]:
        by_code: dict[str, list[tuple[CurriculumItem, CurriculumItemSemanticFeature]]] = defaultdict(list)
        for item in items:
            for assignment in semantic_features.get(item.id, ()):
                by_code[assignment.feature.feature_id.removeprefix("semantic-feature:")].append((item, assignment))
        metrics: dict[str, ProjectionMetric] = {}
        evidence: list[ProjectionMetricEvidence] = []
        denominator = total_workload or ZERO
        for code in sorted(by_code):
            available_workload = ZERO
            numerator = ZERO
            confidence_numerator = ZERO
            provenance: list[SourceAttribution] = []
            for item, assignment in by_code[code]:
                feature = assignment.feature
                if feature.status is not SemanticValueStatus.AVAILABLE or feature.value is None or feature.review_status.value == "rejected":
                    continue
                item_workload = item_workloads[item.id]
                available_workload += item_workload
                numerator += item_workload * feature.value
                confidence_numerator += item_workload * feature.confidence
                provenance.extend(feature.provenance)
                evidence.append(
                    ProjectionMetricEvidence(
                        program_id=program.id,
                        metric_code=code,
                        schema_version=ANALYTICS_PROJECTION_SCHEMA_VERSION,
                        curriculum_item_id=item.id,
                        feature_id=feature.feature_id,
                        contribution=item_workload * feature.value,
                        source_hash=feature.source_hash,
                        evidence=feature.evidence,
                        provenance=feature.provenance,
                    )
                )
            coverage = available_workload / denominator if denominator > ZERO else ZERO
            metric_status = (
                ProjectionDataQualityStatus.AVAILABLE
                if coverage == ONE
                else ProjectionDataQualityStatus.PARTIAL
                if coverage > ZERO
                else ProjectionDataQualityStatus.INSUFFICIENT_DATA
            )
            metrics[code] = ProjectionMetric(
                code=code,
                value=numerator / denominator if denominator > ZERO and available_workload > ZERO else None,
                basis=cast(Any, basis),
                coverage=min(ONE, coverage),
                confidence=confidence_numerator / available_workload if available_workload > ZERO else ZERO,
                status=metric_status,
                provenance=_unique_provenance(provenance),
            )
        return metrics, evidence


def _semantic_timeline(
    items: tuple[CurriculumItem, ...],
    item_workloads: Mapping[str, Decimal],
    semantic_features: Mapping[str, tuple[CurriculumItemSemanticFeature, ...]],
    total_workload: Decimal | None,
) -> tuple[dict[str, dict[str, Decimal]], dict[str, int]]:
    if total_workload is None or total_workload <= ZERO:
        return {}, {}
    by_semester: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for item in items:
        if item.semester is None:
            continue
        for assignment in semantic_features.get(item.id, ()):
            feature = assignment.feature
            if feature.status is not SemanticValueStatus.AVAILABLE or feature.value is None or feature.review_status.value == "rejected":
                continue
            code = feature.feature_id.removeprefix("semantic-feature:")
            by_semester[code][str(item.semester)] += item_workloads[item.id] * feature.value
    normalized: dict[str, dict[str, Decimal]] = {}
    first: dict[str, int] = {}
    for code, workload in by_semester.items():
        normalized[code] = _shares(dict(workload), total_workload)
        numeric_semesters = tuple(int(value) for value in workload if value.isdigit())
        if numeric_semesters:
            first[code] = min(numeric_semesters)
    return normalized, first


class ProgramProjectionService:
    """Refresh only programs whose semantic inputs changed."""

    def __init__(self, builder: ProgramProjectionBuilder, semantic_reader: SemanticEnrichmentStore, store: ProgramProjectionStore, cache: Any | None = None) -> None:
        self._builder = builder
        self._semantic_reader = semantic_reader
        self._store = store
        self._cache = cache

    def refresh(self, canonical: Any, semantic_run: SemanticEnrichmentRun) -> tuple[ProgramProjection, ...]:
        changed = frozenset(semantic_run.changed_item_ids)
        if not changed:
            logger.info("program_projection_refresh_skipped run_id=%s reason=no_changed_curriculum_items", semantic_run.id)
            return ()
        items = tuple(item for curriculum in canonical.curricula for item in curriculum.items)
        assignments = self._semantic_reader.item_features(tuple(item.id for item in items), semantic_version=semantic_run.semantic_version, classifier_version=semantic_run.classifier_version)
        disciplines = {discipline.id: discipline for discipline in canonical.disciplines}
        programs = {program.id: program for program in canonical.programs}
        admissions = {admission.program_id: admission for admission in canonical.admissions}
        builds: list[ProjectionBuild] = []
        for curriculum in canonical.curricula:
            if not any(item.id in changed for item in curriculum.items):
                continue
            program = programs.get(curriculum.program_id)
            if program is None:
                raise ValueError(f"curriculum program is missing: {curriculum.program_id}")
            builds.append(self._builder.build(program, curriculum, disciplines, assignments, ingest_run_id=semantic_run.ingest_run_id, admissions=admissions.get(program.id)))
        self._store.save(tuple(builds))
        if self._cache is not None:
            self._cache.invalidate(build.projection.program_id for build in builds)
        logger.info("program_projection_refresh_complete run_id=%s program_count=%d", semantic_run.id, len(builds))
        return tuple(build.projection for build in builds)


def _shares(values: Mapping[Any, Decimal], total: Decimal | None) -> dict[Any, Decimal]:
    if total is None or total <= ZERO:
        return {}
    positive = {key: value for key, value in values.items() if value > ZERO}
    if not positive:
        return {}
    result = {key: value / total for key, value in positive.items()}
    last_key = sorted(result, key=str)[-1]
    result[last_key] += ONE - sum(result.values(), ZERO)
    return dict(sorted(result.items(), key=lambda entry: str(entry[0])))


def _university_id(program: Program) -> str:
    parts = program.direction_id.removeprefix("direction:").split(":")
    if len(parts) == 2:
        return f"university:{parts[0]}"
    raise ValueError(f"program has no university-scoped direction: {program.id}")


def _semantic_coverage(metrics: Mapping[str, ProjectionMetric]) -> Decimal:
    return sum((metric.coverage for metric in metrics.values()), ZERO) / Decimal(len(metrics)) if metrics else ZERO


def _semantic_confidence(metrics: Mapping[str, ProjectionMetric]) -> Decimal:
    available = tuple(metric.confidence for metric in metrics.values() if metric.value is not None)
    return sum(available, ZERO) / Decimal(len(available)) if available else ZERO


def _unique_provenance(values: list[SourceAttribution]) -> tuple[SourceAttribution, ...]:
    result: list[SourceAttribution] = []
    seen: set[tuple[object, ...]] = set()
    for value in values:
        key = (str(value.url), value.content_sha256, value.locator, value.field, value.record_key)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result[:100])


__all__ = ["ProgramProjectionBuilder", "ProgramProjectionService"]
