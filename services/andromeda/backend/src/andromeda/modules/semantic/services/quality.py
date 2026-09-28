"""Deterministic semantic quality reporting; no source data is logged."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from ..contracts.public import SemanticFeatureValue, SemanticReviewStatus, SemanticValueStatus
from ..contracts.quality import SemanticQualityReport


class SemanticQualityService:
    def evaluate(
        self,
        values: Iterable[SemanticFeatureValue],
        *,
        subject_count: int,
        semantic_version: str,
        classifier_version: str,
    ) -> SemanticQualityReport:
        rows = tuple(values)
        available = tuple(value for value in rows if value.status is SemanticValueStatus.AVAILABLE and value.review_status is not SemanticReviewStatus.REJECTED)
        unresolved = tuple(value for value in rows if value.status is not SemanticValueStatus.AVAILABLE)
        low_confidence = tuple(value for value in available if value.confidence < Decimal("0.80"))
        rejected = tuple(value for value in rows if value.review_status is SemanticReviewStatus.REJECTED)
        denominator = Decimal(len(rows))
        return SemanticQualityReport(
            semantic_version=semantic_version,
            classifier_version=classifier_version,
            subject_count=subject_count,
            value_count=len(rows),
            available_count=len(available),
            unresolved_count=len(unresolved),
            low_confidence_count=len(low_confidence),
            rejected_count=len(rejected),
            coverage=Decimal(len(available)) / denominator if denominator else Decimal("0"),
            unresolved_rate=Decimal(len(unresolved)) / denominator if denominator else Decimal("0"),
            low_confidence_rate=Decimal(len(low_confidence)) / Decimal(len(available)) if available else Decimal("0"),
        )


__all__ = ["SemanticQualityService"]
