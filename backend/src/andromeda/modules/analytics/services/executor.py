"""Typed analytics execution over materialized projections."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from hashlib import sha256

from andromeda.modules.admissions.contracts.public import AdmissionOffering, FundingType
from andromeda.shared.contracts.versions import ANALYTICS_PROJECTION_SCHEMA_VERSION

from ..contracts.metrics import MetricAggregation, MetricDefinition, MetricEntityType
from ..contracts.public import (
    ProgramProjection,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    ProjectionMetricEvidence,
)
from ..contracts.query import (
    FilterKind,
    FilterOperator,
    QueryFilter,
    QueryScope,
    QuerySpec,
)
from ..contracts.results import AnalyticsResult, AnalyticsResultStatus, AnalyticsRow, MetricExplanation
from ..contracts.semantic_predicate import (
    SemanticPredicateEvidence,
    SemanticPredicateFailureReason,
    SemanticPredicatePort,
    SemanticPredicateRequest,
    SemanticPredicateResult,
    SemanticPredicateRow,
    SemanticPredicateStatus,
)
from ..domain.metric_registry import MetricRegistry
from ..repository.queries import ProjectionQueryReader
from .aggregation import aggregate_metrics
from .cache import AnalyticsResultCache


class AnalyticsExecutor:
    def __init__(
        self,
        reader: ProjectionQueryReader,
        registry: MetricRegistry | None = None,
        cache: AnalyticsResultCache | None = None,
        semantic_predicate_port: SemanticPredicatePort | None = None,
    ) -> None:
        self._reader = reader
        self._registry = registry or MetricRegistry()
        self._cache = cache
        self._semantic_predicate_port = semantic_predicate_port

    def execute(self, spec: QuerySpec) -> AnalyticsResult:
        from ..domain.query_validation import validate_query_spec

        validate_query_spec(spec, self._registry)
        cache_key = _cache_key(spec, self._registry.version)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        definitions = tuple(self._registry.get(metric, entity_type=spec.entity, aggregation=spec.aggregation) for metric in spec.metrics)
        query_method = getattr(self._reader, "query", None)
        if callable(query_method):
            candidate_projections = query_method(spec, registry=self._registry)
        else:
            candidate_projections = self._reader.list(program_ids=spec.scope_ids if spec.scope is QueryScope.PROGRAM else ())
        projections = tuple(projection for projection in candidate_projections if _matches_scope(projection, spec) and _matches_filters(projection, spec.filters, self._registry, spec.entity))
        predicate_result = self._evaluate_predicate(projections, spec)
        if predicate_result is not None:
            projections = tuple(
                projection
                for projection in projections
                if predicate_result.matches.get(projection.program_id) is True
            )
        storage_codes = tuple(definition.source_feature_code or definition.code for definition in definitions)
        evidence = self._reader.evidence(
            tuple(projection.program_id for projection in projections),
            metric_codes=storage_codes,
            schema_version=projections[0].schema_version if projections else ANALYTICS_PROJECTION_SCHEMA_VERSION,
        )
        rows = self._rows(projections, evidence, spec, definitions)
        rows = tuple(sorted(rows, key=lambda row: _sort_value(row, spec.sort.metric_code if spec.sort else None), reverse=bool(spec.sort and spec.sort.descending))[: spec.limit])
        status = _result_status(rows)
        metrics = tuple(metric for row in rows for metric in row.metrics.values())
        coverage = sum((metric.coverage for metric in metrics), Decimal("0")) / Decimal(len(metrics)) if metrics else Decimal("0")
        confidence = sum((metric.confidence for metric in metrics), Decimal("0")) / Decimal(len(metrics)) if metrics else Decimal("0")
        result = AnalyticsResult(
            query=spec,
            rows=rows,
            metric_definitions=definitions,
            status=status,
            coverage=coverage,
            confidence=confidence,
            semantic_versions=tuple(sorted({value.quality.semantic_version for value in projections if value.quality.semantic_version})),
            classifier_versions=tuple(sorted({value.quality.classifier_version for value in projections if value.quality.classifier_version})),
            provenance=tuple(value for projection in projections for value in projection.provenance)[:1000],
            source_gaps=tuple(value for projection in projections for value in projection.source_gaps)[:1000],
            population_size=len(projections),
            included_count=sum(1 for row in rows if any(metric.value is not None for metric in row.metrics.values())),
            missing_count=sum(1 for row in rows if any(metric.value is None for metric in row.metrics.values())),
            calculation_metadata={
                "basis_policy": "projection_basis",
                "aggregation": spec.aggregation.value,
                "missing_policy": "exclude_missing_mark_partial",
                "projection_status": "active_only",
                "semantic_predicate_status": predicate_result.status.value if predicate_result is not None else "not_requested",
            },
            explanations=_explanations(definitions, rows, len(projections)),
            semantic_predicate_evidence=predicate_result.evidence if predicate_result is not None else (),
        )
        if self._cache is not None:
            self._cache.put(
                cache_key,
                result,
                program_ids=frozenset(projection.program_id for projection in projections),
            )
        return result

    def _evaluate_predicate(
        self,
        projections: tuple[ProgramProjection, ...],
        spec: QuerySpec,
    ) -> SemanticPredicateResult | None:
        if spec.predicate is None:
            return None
        if self._semantic_predicate_port is None:
            return self._predicate_unavailable(spec, SemanticPredicateFailureReason.CAPABILITY_UNAVAILABLE, projections)
        if len(projections) > spec.predicate.max_rows:
            return self._predicate_unavailable(spec, SemanticPredicateFailureReason.BUDGET, projections)
        rows = tuple(
            SemanticPredicateRow(
                canonical_id=projection.program_id,
                fields={
                    field: value
                    for field, value in {
                        "program_name": projection.program_name,
                        "program_code": projection.program_code,
                        "university_id": projection.university_id,
                        "direction_id": projection.direction_id,
                    }.items()
                    if field in spec.predicate.allowed_fields
                },
            )
            for projection in projections
        )
        request = SemanticPredicateRequest(
            predicate=spec.predicate,
            rows=rows,
            batch_size=min(spec.predicate.max_rows, 32),
        )
        try:
            return self._semantic_predicate_port.evaluate(request)
        except (TypeError, ValueError):
            return self._predicate_unavailable(spec, SemanticPredicateFailureReason.INTERNAL, projections)


    @staticmethod
    def _predicate_unavailable(
        spec: QuerySpec,
        reason: SemanticPredicateFailureReason,
        projections: tuple[ProgramProjection, ...],
    ) -> SemanticPredicateResult:
        evidence = tuple(
            SemanticPredicateEvidence(
                canonical_id=projection.program_id,
                definition_id=spec.predicate.definition_id if spec.predicate is not None else "unknown",
                definition_version=spec.predicate.definition_version if spec.predicate is not None else "unknown",
                status=SemanticPredicateStatus.UNAVAILABLE,
                reason=reason,
            )
            for projection in projections
        )
        return SemanticPredicateResult(
            status=SemanticPredicateStatus.UNAVAILABLE,
            matches={projection.program_id: None for projection in projections},
            evaluated_population=0,
            failure_reason=reason,
            evidence=evidence,
        )

    def _rows(self, projections: tuple[ProgramProjection, ...], evidence: tuple[ProjectionMetricEvidence, ...], spec: QuerySpec, definitions: tuple[MetricDefinition, ...]) -> tuple[AnalyticsRow, ...]:
        group_by = spec.group_by[0] if spec.group_by else None
        if group_by is None and spec.aggregation is MetricAggregation.VALUE:
            return tuple(_row_for_projection(projection, evidence, definitions, spec.filters) for projection in projections)
        grouped: dict[str, list[ProgramProjection]] = defaultdict(list)
        for projection in projections:
            grouped[_group_key(projection, group_by or spec.entity)].append(projection)
        rows: list[AnalyticsRow] = []
        for entity_id, group in grouped.items():
            metric_values: dict[str, ProjectionMetric] = {}
            for definition in definitions:
                values = tuple(_metric_for_projection(projection, definition, spec.filters) for projection in group)
                weights = tuple(projection.workload.total_workload or Decimal("0") for projection in group)
                metric_values[definition.code] = aggregate_metrics(values, spec.aggregation, weights=weights)
                metric_values[definition.code] = metric_values[definition.code].model_copy(update={"code": definition.code})
            rows.append(
                AnalyticsRow(
                    entity_id=entity_id,
                    university_id=group[0].university_id if group_by is not MetricEntityType.DIRECTION else None,
                    direction_id=group[0].direction_id if group_by is MetricEntityType.DIRECTION else None,
                    program_ids=tuple(projection.program_id for projection in group),
                    metrics=metric_values,
                    quality=_row_quality(metric_values.values()),
                    evidence=tuple(value for value in evidence if value.program_id in {projection.program_id for projection in group}),
                    population_size=len(group),
                    included_count=sum(1 for metric in metric_values.values() if metric.value is not None),
                    missing_count=sum(1 for metric in metric_values.values() if metric.value is None),
                    evidence_status="available" if evidence else "partial",
                )
            )
        return tuple(rows)


def _row_for_projection(projection: ProgramProjection, evidence: tuple[ProjectionMetricEvidence, ...], definitions: tuple[MetricDefinition, ...], filters: tuple[QueryFilter, ...]) -> AnalyticsRow:
    metric_values = {definition.code: _metric_for_projection(projection, definition, filters) for definition in definitions}
    storage_codes = {definition.source_feature_code or definition.code for definition in definitions}
    row_evidence = tuple(value.model_copy(update={"metric_code": next((definition.code for definition in definitions if (definition.source_feature_code or definition.code) == value.metric_code), value.metric_code)}) for value in evidence if value.program_id == projection.program_id and value.metric_code in storage_codes)
    return AnalyticsRow(
        entity_id=projection.program_id,
        university_id=projection.university_id,
        direction_id=projection.direction_id,
        program_ids=(projection.program_id,),
        metrics=metric_values,
        quality=_row_quality(metric_values.values()),
        evidence=row_evidence,
        population_size=1,
        included_count=sum(1 for metric in metric_values.values() if metric.value is not None),
        missing_count=sum(1 for metric in metric_values.values() if metric.value is None),
        evidence_status="available" if row_evidence else "partial",
    )


def _explanations(
    definitions: tuple[MetricDefinition, ...],
    rows: tuple[AnalyticsRow, ...],
    population_size: int,
) -> tuple[MetricExplanation, ...]:
    result: list[MetricExplanation] = []
    for definition in definitions:
        observations = tuple(row.metrics.get(definition.code) for row in rows)
        available = tuple(metric for metric in observations if metric is not None and metric.value is not None)
        basis = next((metric.basis.value for metric in available if metric.basis is not None), None)
        evidence_count = sum(
            1
            for row in rows
            for evidence in row.evidence
            if evidence.metric_code == (definition.source_feature_code or definition.code)
        )
        result.append(
            MetricExplanation(
                metric_code=definition.code,
                definition=definition,
                basis=basis,
                population_size=population_size,
                included_count=len(available),
                missing_count=population_size - len(available),
                evidence_count=evidence_count,
            )
        )
    return tuple(result)


def _metric_for_projection(projection: ProgramProjection, definition: MetricDefinition, filters: tuple[QueryFilter, ...]) -> ProjectionMetric:
    code = definition.code
    source = definition.source_feature_code
    if code in {"first_programming_semester", "first_ai_semester"}:
        feature_code = "programming" if code == "first_programming_semester" else "ai_ml"
        semester = projection.timeline.first_feature_semester.get(feature_code)
        if semester is None:
            return ProjectionMetric(code=code, unit=definition.unit, status=ProjectionDataQualityStatus.INSUFFICIENT_DATA)
        return ProjectionMetric(
            code=code,
            value=Decimal(semester),
            unit=definition.unit,
            basis=projection.workload.basis,
            coverage=Decimal("1"),
            confidence=projection.quality.confidence,
            status=ProjectionDataQualityStatus.AVAILABLE,
            provenance=projection.provenance,
        )
    if code in {"math_first_year_share", "math_late_year_share"}:
        by_semester = projection.timeline.feature_by_semester.get("mathematics", {})
        selected = {
            semester: value
            for semester, value in by_semester.items()
            if semester.isdigit() and (int(semester) <= 2 if code == "math_first_year_share" else int(semester) >= 5)
        }
        if not selected:
            return ProjectionMetric(code=code, unit=definition.unit, status=ProjectionDataQualityStatus.INSUFFICIENT_DATA)
        value = sum(selected.values(), Decimal("0"))
        return ProjectionMetric(
            code=code,
            value=value,
            unit=definition.unit,
            basis=projection.workload.basis,
            coverage=Decimal("1"),
            confidence=projection.quality.confidence,
            status=ProjectionDataQualityStatus.AVAILABLE,
            provenance=projection.provenance,
        )
    if source:
        metric = projection.semantic_features.get(source)
        if metric is None:
            return ProjectionMetric(code=code, unit=definition.unit)
        return ProjectionMetric(code=code, value=metric.value, unit=definition.unit, basis=metric.basis, coverage=metric.coverage, confidence=metric.confidence, status=metric.status, provenance=metric.provenance, source_gaps=metric.source_gaps)
    if code == "total_hours":
        return _scalar_metric(code, definition.unit, projection.workload.total_hours, projection)
    if code == "total_credits":
        return _scalar_metric(code, definition.unit, projection.workload.total_credits, projection)
    if code == "exam_count":
        return _scalar_metric(code, definition.unit, projection.assessment.exam_count, projection)
    if code in {"passing_score", "historical_passing_score", "tuition", "budget_places"}:
        return _admission_metric(code, definition.unit, projection, filters)
    return ProjectionMetric(code=code, unit=definition.unit)


def _scalar_metric(code: str, unit: str, value: int | Decimal | None, projection: ProgramProjection) -> ProjectionMetric:
    if value is None:
        return ProjectionMetric(code=code, unit=unit)
    return ProjectionMetric(code=code, value=Decimal(value), unit=unit, basis=projection.workload.basis, coverage=Decimal("1"), confidence=projection.quality.confidence, status=ProjectionDataQualityStatus.AVAILABLE, provenance=projection.provenance)


def _admission_metric(code: str, unit: str, projection: ProgramProjection, filters: tuple[QueryFilter, ...]) -> ProjectionMetric:
    offerings = tuple(offering for offering in projection.admission_offerings if _offering_matches(offering, filters))
    values: list[Decimal] = []
    for offering in offerings:
        if code in {"passing_score", "historical_passing_score"}:
            values.extend(score.score for score in offering.passing_scores if score.score is not None)
        elif code == "tuition":
            values.extend(cost.amount for cost in offering.tuition)
        elif code == "budget_places" and offering.funding_type is FundingType.BUDGET and offering.places is not None:
            values.append(Decimal(offering.places))
    if len(values) != 1:
        return ProjectionMetric(code=code, unit=unit, status=ProjectionDataQualityStatus.INSUFFICIENT_DATA, source_gaps=())
    return ProjectionMetric(code=code, value=values[0], unit=unit, coverage=Decimal("1"), confidence=projection.quality.confidence, status=ProjectionDataQualityStatus.AVAILABLE, provenance=projection.provenance)


def _matches_scope(projection: ProgramProjection, spec: QuerySpec) -> bool:
    if spec.scope is QueryScope.UNIVERSITY:
        return projection.university_id in spec.scope_ids
    if spec.scope is QueryScope.DIRECTION:
        return projection.direction_id in spec.scope_ids
    if spec.scope is QueryScope.PROGRAM:
        return projection.program_id in spec.scope_ids
    return True


def _matches_filters(projection: ProgramProjection, filters: tuple[QueryFilter, ...], registry: MetricRegistry, entity: MetricEntityType) -> bool:
    for query_filter in filters:
        if query_filter.kind is FilterKind.UNIVERSITY and projection.university_id not in query_filter.ids:
            return False
        if query_filter.kind is FilterKind.DIRECTION and projection.direction_id not in query_filter.ids:
            return False
        if query_filter.kind is FilterKind.PROGRAM and projection.program_id not in query_filter.ids:
            return False
        if query_filter.kind in {FilterKind.METRIC_THRESHOLD, FilterKind.SEMANTIC_THRESHOLD}:
            definition = registry.get(query_filter.metric_code or "", entity_type=entity) if query_filter.kind is FilterKind.METRIC_THRESHOLD else None
            metric = _metric_for_projection(projection, definition, filters) if definition else projection.semantic_features.get(query_filter.feature_code or "")
            if metric is None or metric.value is None or not _compare(metric.value, query_filter.operator, query_filter.threshold or Decimal("0")):
                return False
        if query_filter.kind in {FilterKind.ADMISSION_YEAR, FilterKind.STUDY_FORM, FilterKind.FUNDING_TYPE} and not any(_offering_matches(offering, (query_filter,)) for offering in projection.admission_offerings):
            return False
    return True


def _offering_matches(offering: AdmissionOffering, filters: tuple[QueryFilter, ...]) -> bool:
    for query_filter in filters:
        if query_filter.kind is FilterKind.ADMISSION_YEAR and offering.admission_year != query_filter.admission_year:
            return False
        if query_filter.kind is FilterKind.STUDY_FORM and offering.study_form is not query_filter.study_form:
            return False
        if query_filter.kind is FilterKind.FUNDING_TYPE and offering.funding_type is not query_filter.funding_type:
            return False
    return True


def _compare(value: Decimal, operator: FilterOperator, threshold: Decimal) -> bool:
    return {FilterOperator.EQ: value == threshold, FilterOperator.GT: value > threshold, FilterOperator.GTE: value >= threshold, FilterOperator.LT: value < threshold, FilterOperator.LTE: value <= threshold}[operator]


def _group_key(projection: ProgramProjection, entity: MetricEntityType) -> str:
    if entity is MetricEntityType.UNIVERSITY:
        return projection.university_id
    if entity is MetricEntityType.DIRECTION:
        return projection.direction_id
    return projection.program_id


def _row_quality(metrics: Iterable[ProjectionMetric]) -> ProjectionDataQuality:
    values = tuple(metrics)
    available = tuple(metric for metric in values if metric.value is not None)
    coverage = sum((metric.coverage for metric in values), Decimal("0")) / Decimal(len(values)) if values else Decimal("0")
    confidence = sum((metric.confidence for metric in values), Decimal("0")) / Decimal(len(values)) if values else Decimal("0")
    status = ProjectionDataQualityStatus.AVAILABLE if values and len(available) == len(values) else ProjectionDataQualityStatus.PARTIAL if available else ProjectionDataQualityStatus.INSUFFICIENT_DATA
    return ProjectionDataQuality(status=status, coverage=coverage, confidence=confidence)


def _result_status(rows: tuple[AnalyticsRow, ...]) -> AnalyticsResultStatus:
    if not rows:
        return AnalyticsResultStatus.INSUFFICIENT_DATA
    statuses = {row.quality.status for row in rows}
    if statuses == {ProjectionDataQualityStatus.AVAILABLE}:
        return AnalyticsResultStatus.AVAILABLE
    if ProjectionDataQualityStatus.AVAILABLE in statuses or ProjectionDataQualityStatus.PARTIAL in statuses:
        return AnalyticsResultStatus.PARTIAL
    return AnalyticsResultStatus.INSUFFICIENT_DATA


def _sort_value(row: AnalyticsRow, metric_code: str | None) -> str | Decimal:
    if metric_code is None:
        return row.entity_id
    metric = row.metrics.get(metric_code)
    return metric.value if metric is not None and metric.value is not None else Decimal("-1")


def _cache_key(spec: QuerySpec, registry_version: str) -> str:
    payload = json.dumps(
        {
            "registry": registry_version,
            "projection": ANALYTICS_PROJECTION_SCHEMA_VERSION,
            "query": spec.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["AnalyticsExecutor"]
