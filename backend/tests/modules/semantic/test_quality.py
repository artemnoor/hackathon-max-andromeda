from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from andromeda.modules.semantic.contracts.public import (
    SemanticClassificationMethod,
    SemanticFeatureValue,
    SemanticReviewStatus,
    SemanticValueStatus,
)
from andromeda.modules.semantic.services.quality import SemanticQualityService
from andromeda.modules.semantic.contracts.inputs import SemanticClassificationInput
from andromeda.modules.semantic.services.classifier import RuleBasedSemanticClassifier


def _value(*, value: str | None, status: SemanticValueStatus, confidence: str, review: SemanticReviewStatus = SemanticReviewStatus.UNREVIEWED) -> SemanticFeatureValue:
    return SemanticFeatureValue(
        feature_id="semantic-feature:mathematics",
        value=Decimal(value) if value is not None else None,
        status=status,
        confidence=Decimal(confidence),
        classification_method=SemanticClassificationMethod.RULE,
        review_status=review,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_quality_keeps_unresolved_and_low_confidence_separate() -> None:
    report = SemanticQualityService().evaluate(
        (
            _value(value="0.8", status=SemanticValueStatus.AVAILABLE, confidence="0.90"),
            _value(value="0.2", status=SemanticValueStatus.AVAILABLE, confidence="0.70"),
            _value(value=None, status=SemanticValueStatus.UNKNOWN, confidence="0"),
        ),
        subject_count=1,
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-classifier.v1",
    )

    assert report.available_count == 2
    assert report.unresolved_count == 1
    assert report.low_confidence_count == 1
    assert report.coverage == Decimal("0.6666666666666666666666666667")


def test_rejected_values_are_not_user_facing_coverage() -> None:
    report = SemanticQualityService().evaluate(
        (_value(value="0.8", status=SemanticValueStatus.AVAILABLE, confidence="0.90", review=SemanticReviewStatus.REJECTED),),
        subject_count=1,
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-classifier.v1",
    )
    assert report.available_count == 0
    assert report.rejected_count == 1
    assert report.coverage == Decimal("0")


def test_semantic_corpus_v1_replays_deterministically() -> None:
    corpus_path = Path(__file__).parents[2] / "fixtures" / "semantic" / "discipline-feature-corpus-v1.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    classifier = RuleBasedSemanticClassifier()
    for index, case in enumerate(corpus):
        result = classifier.classify(
            SemanticClassificationInput(
                discipline_id=f"discipline:{index:016x}",
                normalized_name=case["source_name"],
            )
        )
        available = {value.feature_id.removeprefix("semantic-feature:") for value in result.values if value.value is not None}
        assert set(case["expected_available"]).issubset(available)
        assert bool(result.source_gaps) is case["expected_unresolved"]
