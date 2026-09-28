from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.domain.areas import DisciplineAreaCode, area_catalog
from andromeda.modules.disciplines.services.classifier import RuleBasedDisciplineClassifier


def _as_dict(name: str) -> dict[DisciplineAreaCode, Decimal]:
    return {item.area: item.weight for item in RuleBasedDisciplineClassifier().classify(name)}


def test_taxonomy_has_exactly_22_ordered_areas() -> None:
    areas = area_catalog()
    assert len(areas) == 22
    assert [area.position for area in areas] == list(range(1, 23))
    assert len({area.code for area in areas}) == 22


def test_classifier_preserves_multidisciplinary_vectors() -> None:
    machine_learning = _as_dict("Машинное обучение")
    assert machine_learning[DisciplineAreaCode.COMPUTER_SCIENCE_DATA] == Decimal("0.75")
    assert machine_learning[DisciplineAreaCode.MATHEMATICS_STATISTICS] == Decimal("0.25")

    bioinformatics = _as_dict("Биоинформатика")
    assert bioinformatics == {
        DisciplineAreaCode.BIOLOGY_BIOTECHNOLOGY: Decimal("0.50"),
        DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.40"),
        DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.10"),
    }


def test_classifier_falls_back_to_universal_without_false_precision() -> None:
    result = RuleBasedDisciplineClassifier().classify("Неизвестный предмет")
    assert result[0].area is DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY
    assert result[0].weight == Decimal("1.0000")


def test_classifier_outcome_records_method_rule_and_taxonomy_version() -> None:
    classifier = RuleBasedDisciplineClassifier(
        {"Каноническое имя": ((DisciplineAreaCode.MATHEMATICS_STATISTICS, Decimal("1.00")),)},
        {"Историческое имя": "Каноническое имя"},
    )

    exact = classifier.classify_with_outcome("Каноническое имя")
    alias = classifier.classify_with_outcome("Историческое имя")
    keyword = classifier.classify_with_outcome("Машинное обучение")
    explicit = RuleBasedDisciplineClassifier(
        {"Практика": ((DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY, Decimal("1.00")),)},
    ).classify_with_outcome("Практика")
    unresolved = classifier.classify_with_outcome("Совершенно неизвестный предмет")

    assert exact.method == "exact_override"
    assert exact.review_status == "reviewed"
    assert exact.rule_id is not None and exact.rule_id.startswith("override:")
    assert alias.method == "alias"
    assert alias.area_weights == exact.area_weights
    assert keyword.method == "keyword_rule"
    assert keyword.review_status == "automatic"
    assert explicit.method == "explicit_universal"
    assert unresolved.method == "unresolved"
    assert unresolved.review_status == "needs_review"
    assert unresolved.area_weights[0].area is DisciplineAreaCode.UNIVERSAL_INTERDISCIPLINARY
    assert unresolved.taxonomy_version == "taxonomy-22.v1"


def test_classifier_matching_normalizes_safe_spelling_variants_without_changing_identity() -> None:
    classifier = RuleBasedDisciplineClassifier({"Теория вероятностей - и статистика": ((DisciplineAreaCode.MATHEMATICS_STATISTICS, Decimal("1.00")),)})

    outcome = classifier.classify_with_outcome("ТЕОРИЯ ВЕРОЯТНОСТЕЙ — И СТАТИСТИКА")

    assert outcome.method == "exact_override"
    assert outcome.normalized_name == "теория вероятностей - и статистика"
