"""Bounded typed analytics query contracts; never raw SQL."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.admissions.contracts.public import FundingType, StudyForm
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.ids import EducationYear, Semester

from .metrics import MetricAggregation, MetricEntityType
from .semantic_predicate import SemanticPredicate


class QueryScope(StrEnum):
    ALL = "all"
    UNIVERSITY = "university"
    DIRECTION = "direction"
    PROGRAM = "program"
    EDUCATION_LEVEL = "education_level"
    ADMISSION_YEAR = "admission_year"
    STUDY_FORM = "study_form"
    FUNDING_TYPE = "funding_type"
    SEMESTER = "semester"
    COURSE_YEAR = "course_year"


class FilterKind(StrEnum):
    UNIVERSITY = "university"
    DIRECTION = "direction"
    PROGRAM = "program"
    EDUCATION_LEVEL = "education_level"
    ADMISSION_YEAR = "admission_year"
    STUDY_FORM = "study_form"
    FUNDING_TYPE = "funding_type"
    SEMESTER = "semester"
    COURSE_YEAR = "course_year"
    METRIC_THRESHOLD = "metric_threshold"
    SEMANTIC_THRESHOLD = "semantic_threshold"
    ADMISSION_FIT = "admission_fit"


class FilterOperator(StrEnum):
    EQ = "eq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class QueryFilter(ContractModel):
    kind: FilterKind
    ids: tuple[str, ...] = Field(default=(), max_length=100)
    education_level: EducationLevel | None = None
    admission_year: EducationYear | None = None
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    semester: Semester | None = None
    course_year: int | None = Field(default=None, strict=True, ge=1, le=12)
    metric_code: str | None = None
    feature_code: str | None = None
    operator: FilterOperator = FilterOperator.EQ
    threshold: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"))

    @model_validator(mode="after")
    def validate_shape(self) -> QueryFilter:
        id_kinds = {FilterKind.UNIVERSITY, FilterKind.DIRECTION, FilterKind.PROGRAM}
        if self.kind in id_kinds and not self.ids:
            raise ValueError(f"{self.kind.value} filter requires canonical ids")
        if self.kind is FilterKind.METRIC_THRESHOLD and (not self.metric_code or self.threshold is None):
            raise ValueError("metric threshold requires metric_code and threshold")
        if self.kind is FilterKind.SEMANTIC_THRESHOLD and (not self.feature_code or self.threshold is None):
            raise ValueError("semantic threshold requires feature_code and threshold")
        if self.kind is FilterKind.ADMISSION_YEAR and self.admission_year is None:
            raise ValueError("admission year filter requires admission_year")
        if self.kind is FilterKind.STUDY_FORM and self.study_form is None:
            raise ValueError("study form filter requires study_form")
        if self.kind is FilterKind.FUNDING_TYPE and self.funding_type is None:
            raise ValueError("funding filter requires funding_type")
        if self.kind is FilterKind.EDUCATION_LEVEL and self.education_level is None:
            raise ValueError("education level filter requires education_level")
        if self.kind is FilterKind.SEMESTER and self.semester is None:
            raise ValueError("semester filter requires semester")
        if self.kind is FilterKind.COURSE_YEAR and self.course_year is None:
            raise ValueError("course year filter requires course_year")
        if self.kind not in {FilterKind.METRIC_THRESHOLD, FilterKind.SEMANTIC_THRESHOLD} and self.threshold is not None:
            raise ValueError("threshold is only valid for metric or semantic filters")
        return self


class QuerySort(ContractModel):
    metric_code: str | None = None
    descending: bool = True

    @model_validator(mode="after")
    def validate_metric(self) -> QuerySort:
        if self.metric_code is None:
            raise ValueError("sort must name an allow-listed metric")
        return self


class QuerySpec(ContractModel):
    entity: MetricEntityType
    metrics: tuple[str, ...] = Field(min_length=1, max_length=8)
    scope: QueryScope = QueryScope.ALL
    scope_ids: tuple[str, ...] = Field(default=(), max_length=100)
    filters: tuple[QueryFilter, ...] = Field(default=(), max_length=16)
    group_by: tuple[MetricEntityType, ...] = Field(default=(), max_length=2)
    aggregation: MetricAggregation = MetricAggregation.VALUE
    sort: QuerySort | None = None
    limit: int = Field(default=20, strict=True, ge=1, le=100)
    predicate: SemanticPredicate | None = None

    def validate_and_normalize(self) -> QuerySpec:
        """Return the validated immutable-by-convention query boundary."""

        return self


__all__ = [
    "FilterKind",
    "FilterOperator",
    "QueryFilter",
    "QueryScope",
    "QuerySort",
    "QuerySpec",
]
