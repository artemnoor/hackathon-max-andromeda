"""Versioned metric registry contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SemanticFeatureCode, SemanticVersion
from andromeda.shared.contracts.versions import METRIC_REGISTRY_VERSION

from ..domain.basis import MetricBasis


class MetricEntityType(StrEnum):
    UNIVERSITY = "university"
    DIRECTION = "direction"
    PROGRAM = "program"
    CURRICULUM = "curriculum"
    DISCIPLINE = "discipline"


class MetricAggregation(StrEnum):
    VALUE = "value"
    SUM = "sum"
    MEAN = "mean"
    WEIGHTED_MEAN = "weighted_mean"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    COUNT = "count"
    DISTRIBUTION = "distribution"


class MetricDomain(StrEnum):
    SEMANTIC = "semantic"
    WORKLOAD = "workload"
    ASSESSMENT = "assessment"
    ADMISSIONS = "admissions"
    STRUCTURE = "structure"


class MetricDefinition(ContractModel):
    code: SemanticFeatureCode
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    unit: str = Field(min_length=1, max_length=32)
    domain: MetricDomain
    supported_entity_types: tuple[MetricEntityType, ...] = Field(min_length=1, max_length=8)
    allowed_aggregations: tuple[MetricAggregation, ...] = Field(min_length=1, max_length=8)
    preferred_basis: MetricBasis | None = None
    fallback_basis: tuple[MetricBasis, ...] = Field(default=(), max_length=4)
    semantic_version: SemanticVersion = METRIC_REGISTRY_VERSION
    source_feature_code: SemanticFeatureCode | None = None
    predicate_definition_id: str | None = Field(default=None, max_length=128)
    minimum_coverage: Decimal = Field(default=Decimal("0.8"), strict=True, ge=Decimal("0"), le=Decimal("1"))
    include_missing_in_aggregate: bool = False


__all__ = [
    "MetricAggregation",
    "MetricDefinition",
    "MetricDomain",
    "MetricEntityType",
]
