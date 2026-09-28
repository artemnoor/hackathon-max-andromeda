from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from andromeda.modules.disciplines.contracts.public import (
    DisciplineAreaCode,
    DisciplineAreaWeight,
)
from andromeda.modules.semantic.contracts.public import (
    SemanticClassificationInput,
    SemanticClassificationMethod,
    SemanticFeatureGroup,
    SemanticFeatureValue,
    SemanticValueStatus,
)
from andromeda.modules.semantic.domain.entities import DEFAULT_SEMANTIC_FEATURES
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution
from andromeda.shared.contracts.versions import (
    SEMANTIC_CLASSIFIER_VERSION,
    SEMANTIC_TAXONOMY_VERSION,
)
from pydantic import ValidationError


def _source() -> SourceAttribution:
    return SourceAttribution(
        kind=SourceKind.BMSTU_CURRICULUM_DOCUMENT,
        url="https://example.test/source.pdf",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_sha256="a" * 64,
        locator="page=1;row=2",
    )


def test_semantic_features_are_extensible_and_seeded_without_enum_codes() -> None:
    codes = {feature.code for feature in DEFAULT_SEMANTIC_FEATURES}
    assert {"mathematics", "programming", "ai_ml", "physics", "project_work"} <= codes
    assert all(feature.feature_group in SemanticFeatureGroup for feature in DEFAULT_SEMANTIC_FEATURES)
    assert len(codes) == len(DEFAULT_SEMANTIC_FEATURES)


def test_semantic_value_accepts_zero_but_keeps_unknown_distinct() -> None:
    available_zero = SemanticFeatureValue(
        feature_id="semantic-feature:mathematics",
        value=Decimal("0"),
        status=SemanticValueStatus.AVAILABLE,
        confidence=Decimal("0.9"),
        classification_method=SemanticClassificationMethod.RULE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        provenance=(_source(),),
    )
    unknown = available_zero.model_copy(update={"value": None, "status": SemanticValueStatus.UNKNOWN})
    assert available_zero.value == 0
    assert unknown.value is None
    assert unknown.status is SemanticValueStatus.UNKNOWN


def test_semantic_value_rejects_missing_and_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        SemanticFeatureValue(
            feature_id="semantic-feature:mathematics",
            value=None,
            status=SemanticValueStatus.AVAILABLE,
            confidence=Decimal("0.9"),
            classification_method=SemanticClassificationMethod.RULE,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        SemanticFeatureValue(
            feature_id="semantic-feature:mathematics",
            value=Decimal("1.1"),
            confidence=Decimal("0.9"),
            classification_method=SemanticClassificationMethod.RULE,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_semantic_input_keeps_item_context_and_provenance() -> None:
    value = SemanticClassificationInput(
        discipline_id="discipline:" + "a" * 16,
        curriculum_item_id="curriculum-item:program:bmstu:09.03.01-02:discipline:" + "a" * 16 + ":1",
        program_id="program:bmstu:09.03.01-02",
        normalized_name="машинное обучение",
        source_text="Машинное обучение",
        source_hash="b" * 64,
        provenance=(_source(),),
    )
    assert value.curriculum_item_id is not None
    assert value.provenance[0].content_sha256 == "a" * 64


def test_existing_area_taxonomy_remains_independent() -> None:
    area = DisciplineAreaWeight(area=DisciplineAreaCode.MATHEMATICS_STATISTICS, weight=Decimal("1"))
    assert area.area is DisciplineAreaCode.MATHEMATICS_STATISTICS
    assert SEMANTIC_CLASSIFIER_VERSION == "semantic-classifier.v1"
    assert SEMANTIC_TAXONOMY_VERSION == "semantic-taxonomy.v1"
