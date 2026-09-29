from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.recommendations.services.scoring import RecommendationScoringService
from .factories import fingerprint, profile


def test_content_fit_exposes_formula_components_and_integer_score() -> None:
    score = RecommendationScoringService().score(profile(), fingerprint(computer="0.8", mathematics="0.2"))
    assert isinstance(score.content_fit, int)
    assert 0 <= score.content_fit <= 100
    assert score.breakdown.subject_fit == Decimal("80")
    assert score.breakdown.anti_penalty == Decimal("0")


def test_optional_metrics_are_not_inputs_to_content_fit() -> None:
    score = RecommendationScoringService().score(profile(), fingerprint())
    assert score.content_fit == 67


def test_subject_axes_are_independently_weighted() -> None:
    math_profile = profile(subject={DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("1")})
    math_score = RecommendationScoringService().score(math_profile, fingerprint(computer="0.2", mathematics="0.8"))
    computer_score = RecommendationScoringService().score(profile(), fingerprint(computer="0.8", mathematics="0.2"))
    assert math_score.breakdown.subject_fit == Decimal("80")
    assert computer_score.breakdown.subject_fit == Decimal("80")
