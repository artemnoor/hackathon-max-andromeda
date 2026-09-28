from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.recommendations.services.scoring import RecommendationScoringService
from .factories import fingerprint, profile


def test_stronger_anti_interest_cannot_improve_high_share_program() -> None:
    program = fingerprint(computer="0.1", mathematics="0.1", physics="0.8")
    weak = profile(negative={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("0.2")})
    strong = profile(negative={DisciplineAreaCode.PHYSICS_ASTRONOMY: Decimal("1")})
    scorer = RecommendationScoringService()
    weak_score = scorer.score(weak, program)
    strong_score = scorer.score(strong, program)
    assert strong_score.content_fit < weak_score.content_fit
    assert strong_score.breakdown.anti_penalty > weak_score.breakdown.anti_penalty
