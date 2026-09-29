"""Allow-listed versioned metric definitions."""

from __future__ import annotations

from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.versions import METRIC_REGISTRY_VERSION

from ..contracts.metrics import (
    MetricAggregation,
    MetricDefinition,
    MetricDomain,
    MetricEntityType,
)
from .basis import MetricBasis

_PROGRAM = (MetricEntityType.PROGRAM,)
_PROGRAM_GROUPABLE = (MetricEntityType.PROGRAM, MetricEntityType.UNIVERSITY, MetricEntityType.DIRECTION)
_VALUE = (MetricAggregation.VALUE,)
_DISTRIBUTIVE = (MetricAggregation.VALUE, MetricAggregation.MEAN, MetricAggregation.WEIGHTED_MEAN, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEDIAN, MetricAggregation.DISTRIBUTION)


def _semantic(code: str, name: str, source: str) -> MetricDefinition:
    return MetricDefinition(
        code=code,
        name=name,
        description=f"Workload-weighted {name.lower()} intensity from versioned semantic assignments.",
        unit="share",
        domain=MetricDomain.SEMANTIC,
        supported_entity_types=_PROGRAM_GROUPABLE,
        allowed_aggregations=_DISTRIBUTIVE,
        preferred_basis=MetricBasis.CREDITS,
        fallback_basis=(MetricBasis.HOURS,),
        source_feature_code=source,
    )


DEFAULT_METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    _semantic("math_share", "Математика", "mathematics"),
    _semantic("mathematics_share", "Математика", "mathematics"),
    _semantic("statistics_share", "Статистика", "statistics"),
    _semantic("programming_share", "Программирование", "programming"),
    _semantic("ai_share", "Искусственный интеллект", "ai_ml"),
    _semantic("physics_share", "Физика", "physics"),
    _semantic("business_share", "Бизнес", "business"),
    _semantic("analytics_share", "Аналитика", "analytics"),
    _semantic("data_analysis_share", "Анализ данных", "data_analysis"),
    MetricDefinition(code="total_hours", name="Всего часов", description="Total curriculum hours.", unit="hours", domain=MetricDomain.WORKLOAD, supported_entity_types=_PROGRAM, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.SUM, MetricAggregation.MEAN, MetricAggregation.WEIGHTED_MEAN, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEDIAN), preferred_basis=MetricBasis.HOURS, fallback_basis=(MetricBasis.CREDITS,)),
    MetricDefinition(code="total_credits", name="Всего кредитов", description="Total curriculum credits.", unit="credits", domain=MetricDomain.WORKLOAD, supported_entity_types=_PROGRAM, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.SUM, MetricAggregation.MEAN, MetricAggregation.WEIGHTED_MEAN, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEDIAN), preferred_basis=MetricBasis.CREDITS, fallback_basis=(MetricBasis.HOURS,)),
    MetricDefinition(code="course_count", name="Количество дисциплин", description="Number of curriculum items when source records are complete.", unit="count", domain=MetricDomain.WORKLOAD, supported_entity_types=_PROGRAM, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.SUM, MetricAggregation.MEAN, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEDIAN), preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="exam_count", name="Экзамены", description="Number of exam assessments.", unit="count", domain=MetricDomain.ASSESSMENT, supported_entity_types=_PROGRAM, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.SUM, MetricAggregation.MEAN, MetricAggregation.MIN, MetricAggregation.MAX), preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="passing_score", name="Проходной балл", description="Offering-scoped passing score; never flattened across dimensions.", unit="score", domain=MetricDomain.ADMISSIONS, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=_DISTRIBUTIVE, preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="tuition", name="Стоимость обучения", description="Offering-scoped tuition amount.", unit="RUB", domain=MetricDomain.ADMISSIONS, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=_DISTRIBUTIVE, preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="budget_places", name="Бюджетные места", description="Budget places for a selected admission offering.", unit="places", domain=MetricDomain.ADMISSIONS, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.SUM, MetricAggregation.MEAN, MetricAggregation.MIN, MetricAggregation.MAX), preferred_basis=MetricBasis.COURSE_COUNT),
    _semantic("math_first_year_share", "Математика на первом курсе", "mathematics"),
    _semantic("math_late_year_share", "Математика на старших курсах", "mathematics"),
    _semantic("project_work_share", "Проектная работа", "project_work"),
    _semantic("practice_share", "Практика", "practice"),
    _semantic("theory_share", "Теория", "theory"),
    MetricDefinition(code="first_programming_semester", name="Первый семестр программирования", description="First known semester containing programming signal.", unit="semester", domain=MetricDomain.STRUCTURE, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEAN, MetricAggregation.MEDIAN), preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="first_ai_semester", name="Первый семестр AI", description="First known semester containing AI/ML signal.", unit="semester", domain=MetricDomain.STRUCTURE, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=(MetricAggregation.VALUE, MetricAggregation.MIN, MetricAggregation.MAX, MetricAggregation.MEAN, MetricAggregation.MEDIAN), preferred_basis=MetricBasis.COURSE_COUNT),
    MetricDefinition(code="historical_passing_score", name="Исторический проходной балл", description="Historical source-backed passing score for a selected offering.", unit="score", domain=MetricDomain.ADMISSIONS, supported_entity_types=_PROGRAM_GROUPABLE, allowed_aggregations=_DISTRIBUTIVE, preferred_basis=MetricBasis.COURSE_COUNT),
)


class MetricRegistry:
    def __init__(self, definitions: tuple[MetricDefinition, ...] = DEFAULT_METRIC_DEFINITIONS) -> None:
        codes = [definition.code for definition in definitions]
        if len(codes) != len(set(codes)):
            raise ValueError("metric registry contains duplicate codes")
        self._definitions = {definition.code: definition for definition in definitions}
        self.version = METRIC_REGISTRY_VERSION

    def get(
        self,
        code: str,
        *,
        entity_type: MetricEntityType | None = None,
        aggregation: MetricAggregation | None = None,
    ) -> MetricDefinition:
        definition = self._definitions.get(code)
        if definition is None:
            raise ContractError(ErrorCode.UNSUPPORTED_METRIC, f"Unsupported metric: {code}")
        if entity_type is not None and entity_type not in definition.supported_entity_types:
            raise ContractError(ErrorCode.CONTRACT_ERROR, f"Metric {code} does not support entity {entity_type}")
        if aggregation is not None and aggregation not in definition.allowed_aggregations:
            raise ContractError(ErrorCode.UNSUPPORTED_AGGREGATION, f"Metric {code} does not support aggregation {aggregation}")
        return definition

    def all(self) -> tuple[MetricDefinition, ...]:
        return tuple(self._definitions.values())


__all__ = ["DEFAULT_METRIC_DEFINITIONS", "MetricRegistry"]
