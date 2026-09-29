from decimal import Decimal

import pytest
from andromeda.modules.analytics.contracts.public import (
    ActivitySignalCode,
    ProgramProjection,
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
    ProjectionMetric,
    ProjectionTimeline,
    WorkloadSummary,
)
from andromeda.modules.analytics.domain.basis import MetricBasis, select_workload_basis
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from pydantic import ValidationError


def _projection() -> ProgramProjection:
    return ProgramProjection(
        program_id="program:bmstu:09.03.01-02",
        university_id="university:bmstu",
        direction_id="direction:bmstu:09.03.01",
        program_code="09.03.01-02",
        program_name="Информатика и вычислительная техника",
        workload=WorkloadSummary(
            total_hours=100,
            total_credits=Decimal("10"),
            total_workload=Decimal("100"),
            basis=MetricBasis.HOURS,
        ),
        academic_areas={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")},
        semantic_features={
            "mathematics": ProjectionMetric(
                code="mathematics",
                value=Decimal("0.65"),
                coverage=Decimal("1"),
                confidence=Decimal("0.9"),
                status=ProjectionDataQualityStatus.AVAILABLE,
            ),
            "physics": ProjectionMetric(code="physics"),
        },
        activity_signals={ActivitySignalCode.SOFTWARE_CREATION: Decimal("1")},
        quality=ProjectionDataQuality(
            status=ProjectionDataQualityStatus.AVAILABLE,
            coverage=Decimal("1"),
            confidence=Decimal("0.9"),
            semantic_version="semantic-taxonomy.v1",
            classifier_version="semantic-classifier.v1",
        ),
    )


def test_program_projection_keeps_semantic_metrics_and_missing_values_explicit() -> None:
    projection = _projection()

    assert projection.semantic_features["mathematics"].value == Decimal("0.65")
    assert projection.semantic_features["physics"].value is None
    assert projection.semantic_features["physics"].status is ProjectionDataQualityStatus.UNAVAILABLE
    assert projection.model_dump(mode="json")["schema_version"] == "analytics-projection.v1"


def test_program_projection_rejects_incomplete_workload_distribution() -> None:
    with pytest.raises(ValidationError, match="academic_areas"):
        values = _projection().model_dump()
        values["academic_areas"] = {DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.5")}
        ProgramProjection(**values)


def test_basis_selection_has_no_zero_fallback_for_missing_workload() -> None:
    assert select_workload_basis(total_hours=0, total_credits=Decimal("12")) is MetricBasis.CREDITS
    assert select_workload_basis(total_hours=120, total_credits=None) is MetricBasis.HOURS
    assert select_workload_basis(total_hours=None, total_credits=None) is MetricBasis.NORMALIZED_WORKLOAD


def test_projection_timeline_keeps_feature_distribution_and_first_semester() -> None:
    timeline = ProjectionTimeline(
        by_semester={"1": Decimal("0.5"), "2": Decimal("0.5")},
        feature_by_semester={"programming": {"2": Decimal("1")}},
        first_feature_semester={"programming": 2},
    )
    assert timeline.feature_by_semester["programming"]["2"] == Decimal("1")
    assert timeline.first_feature_semester["programming"] == 2
