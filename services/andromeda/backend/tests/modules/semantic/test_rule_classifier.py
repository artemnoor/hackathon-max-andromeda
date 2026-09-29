from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from andromeda.modules.disciplines.domain.identity import discipline_id_for
from andromeda.modules.semantic.contracts.inputs import SemanticClassificationInput
from andromeda.modules.semantic.contracts.public import (
    DisciplineSemanticDefault,
    SemanticClassificationMethod,
    SemanticClassificationResult,
    SemanticFeatureValue,
    SemanticValueStatus,
)
from andromeda.modules.semantic.services.classifier import RuleBasedSemanticClassifier
from andromeda.modules.semantic.services.rules import SemanticRule
from andromeda.shared.contracts.errors import ContractError

DISCIPLINE_ID = discipline_id_for("математическая статистика и машинное обучение")
ITEM_ID = "curriculum-item:program:bmstu:09.03.01-02:discipline:0123456789abcdef:1"


def _input(name: str, *, item_id: str | None = None, taxonomy_version: str | None = None) -> SemanticClassificationInput:
    return SemanticClassificationInput(
        discipline_id=DISCIPLINE_ID,
        curriculum_item_id=item_id,
        normalized_name=name,
        semantic_version=taxonomy_version,
    )


def _by_code(result: SemanticClassificationResult, code: str) -> SemanticFeatureValue:
    feature_id = f"semantic-feature:{code}"
    return next(value for value in result.values if value.feature_id == feature_id)


def test_classifier_emits_overlapping_independent_features_and_evidence() -> None:
    result = RuleBasedSemanticClassifier().classify(_input("Математическая статистика и машинное обучение"))

    math = _by_code(result, "mathematics")
    statistics = _by_code(result, "statistics")
    ai = _by_code(result, "ai_ml")

    assert math.status is SemanticValueStatus.AVAILABLE
    assert statistics.status is SemanticValueStatus.AVAILABLE
    assert ai.status is SemanticValueStatus.AVAILABLE
    assert math.value is not None and statistics.value is not None and ai.value is not None
    assert len(math.evidence) == 1
    assert any("машинное обуч" in evidence.matched_terms for evidence in ai.evidence)
    assert sum(value for value in (math.value, statistics.value, ai.value)) > Decimal("1")

def test_classifier_keeps_unknown_distinct_from_explicit_zero() -> None:
    result = RuleBasedSemanticClassifier().classify(_input("История древнего мира"))

    assert all(value.status is SemanticValueStatus.UNKNOWN for value in result.values)
    assert all(value.value is None for value in result.values)
    assert result.source_gaps and result.source_gaps[0].code == "semantic-classification-insufficient"


def test_classifier_alias_and_version_are_deterministic() -> None:
    classifier = RuleBasedSemanticClassifier(aliases={"матан": "математический анализ"})
    first = classifier.classify(_input("матан"))
    second = classifier.classify(_input("матан"))

    assert _by_code(first, "mathematics").status is SemanticValueStatus.AVAILABLE
    assert first.model_dump(exclude={"created_at"}) == second.model_dump(exclude={"created_at"})


def test_classifier_rejects_unsupported_rule_feature() -> None:
    with pytest.raises(ValueError, match="unsupported semantic feature code"):
        RuleBasedSemanticClassifier(
            rules=(
                SemanticRule(
                    rule_id="bad",
                    feature_code="unicorn_quality",
                    keywords=("unicorn",),
                    value=Decimal("1"),
                    confidence=Decimal("1"),
                    rationale="unsupported",
                ),
            )
        )


def test_classifier_rejects_unsupported_taxonomy_version() -> None:
    with pytest.raises(ContractError):
        RuleBasedSemanticClassifier().classify(_input("математика", taxonomy_version="semantic-taxonomy.v9"))


def test_item_rules_override_defaults_and_unknown_values_can_inherit() -> None:
    classifier = RuleBasedSemanticClassifier()
    result = classifier.classify(_input("проектная деятельность", item_id=ITEM_ID))
    default = SemanticFeatureValue(
        feature_id="semantic-feature:mathematics",
        value=Decimal("0.65"),
        confidence=Decimal("0.70"),
        classification_method=SemanticClassificationMethod.DICTIONARY,
        created_at=datetime.now(UTC),
    )

    merged = classifier.merge_with_discipline_defaults(
        defaults=(DisciplineSemanticDefault(discipline_id=DISCIPLINE_ID, feature=default),),
        item_result=result,
        allow_inheritance=True,
    )
    math = next(value for value in merged if value.feature.feature_id == default.feature_id)
    assert math.feature.classification_method is SemanticClassificationMethod.INHERITED
    assert math.overrides_discipline_default is False

    explicit_zero = default.model_copy(
        update={
            "value": Decimal("0"),
            "status": SemanticValueStatus.AVAILABLE,
            "classification_method": SemanticClassificationMethod.RULE,
        }
    )
    explicit_result = SemanticClassificationResult(
        discipline_id=DISCIPLINE_ID,
        curriculum_item_id=ITEM_ID,
        values=(explicit_zero,),
    )
    overridden = classifier.merge_with_discipline_defaults(
        defaults=(DisciplineSemanticDefault(discipline_id=DISCIPLINE_ID, feature=default),),
        item_result=explicit_result,
        allow_inheritance=True,
    )
    assert overridden[0].feature.value == Decimal("0")
    assert overridden[0].overrides_discipline_default is True
