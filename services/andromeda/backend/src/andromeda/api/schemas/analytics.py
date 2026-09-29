"""HTTP adapters for the strict tuple-based analytics contracts."""

from __future__ import annotations

from decimal import Decimal

from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.modules.analytics.contracts.metrics import (
    MetricAggregation,
    MetricEntityType,
)
from andromeda.modules.analytics.contracts.query import (
    FilterKind,
    FilterOperator,
    QueryFilter,
    QueryScope,
    QuerySort,
    QuerySpec,
)
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import EducationYear, Semester
from pydantic import ConfigDict, Field

from .common import ApiModel, to_camel

_ANALYTICS_API_CONFIG = ConfigDict(
    strict=False,
    extra="forbid",
    populate_by_name=True,
    alias_generator=to_camel,
)


class AnalyticsFilterRequest(ApiModel):
    model_config = _ANALYTICS_API_CONFIG

    kind: FilterKind
    ids: list[str] = Field(default_factory=list, max_length=100)
    education_level: EducationLevel | None = None
    admission_year: EducationYear | None = None
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    semester: Semester | None = None
    course_year: int | None = Field(default=None, ge=1, le=12)
    metric_code: str | None = None
    feature_code: str | None = None
    operator: FilterOperator = FilterOperator.EQ
    threshold: Decimal | None = Field(default=None, ge=Decimal(0))

    def to_contract(self) -> QueryFilter:
        return QueryFilter(
            kind=self.kind,
            ids=tuple(self.ids),
            education_level=self.education_level,
            admission_year=self.admission_year,
            study_form=self.study_form,
            funding_type=self.funding_type,
            semester=self.semester,
            course_year=self.course_year,
            metric_code=self.metric_code,
            feature_code=self.feature_code,
            operator=self.operator,
            threshold=self.threshold,
        )


class AnalyticsSortRequest(ApiModel):
    model_config = _ANALYTICS_API_CONFIG

    metric_code: str
    descending: bool = True

    def to_contract(self) -> QuerySort:
        return QuerySort(metric_code=self.metric_code, descending=self.descending)


class AnalyticsQueryRequest(ApiModel):
    model_config = _ANALYTICS_API_CONFIG

    entity: MetricEntityType
    metrics: list[str] = Field(min_length=1, max_length=8)
    scope: QueryScope = QueryScope.ALL
    scope_ids: list[str] = Field(default_factory=list, max_length=100)
    filters: list[AnalyticsFilterRequest] = Field(default_factory=list, max_length=16)
    group_by: list[MetricEntityType] = Field(default_factory=list, max_length=2)
    aggregation: MetricAggregation = MetricAggregation.VALUE
    sort: AnalyticsSortRequest | None = None
    limit: int = Field(default=20, ge=1, le=100)

    def to_contract(self) -> QuerySpec:
        return QuerySpec(
            entity=self.entity,
            metrics=tuple(self.metrics),
            scope=self.scope,
            scope_ids=tuple(self.scope_ids),
            filters=tuple(item.to_contract() for item in self.filters),
            group_by=tuple(self.group_by),
            aggregation=self.aggregation,
            sort=self.sort.to_contract() if self.sort is not None else None,
            limit=self.limit,
        )


__all__ = ["AnalyticsFilterRequest", "AnalyticsQueryRequest", "AnalyticsSortRequest"]
