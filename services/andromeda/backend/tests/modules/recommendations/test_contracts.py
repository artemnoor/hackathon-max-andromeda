from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.recommendations.contracts.public import RecommendationRequest, RecommendationResult
from .factories import profile


def test_request_has_bounded_default_limit_and_strict_extras() -> None:
    request = RecommendationRequest(profile=profile())
    assert request.limit == 10
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate({"profile": profile().model_dump(), "limit": 21})
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate({"profile": profile().model_dump(), "unexpected": True})


def test_result_keeps_profile_and_ordered_recommendations() -> None:
    request = RecommendationRequest(profile=profile(), limit=2)
    result = RecommendationResult(profile=request.profile, recommendations=())
    assert result.profile.preferred_subject_weights
    assert result.recommendations == ()
    assert Decimal("1") in result.profile.preferred_subject_weights.values()
