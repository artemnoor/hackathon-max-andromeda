"""Thin HTTP adapter for the recommendation application service."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_current_recommendation_service, get_recommendation_service
from andromeda.api.schemas.recommendations import CurrentRecommendationsResponse, RecommendationRequest, RecommendationsResponse, recommendations_response
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.recommendations.services.current import CurrentRecommendationService
from andromeda.modules.recommendations.services.recommendations import RecommendationService


logger = logging.getLogger("andromeda.api.recommendations")
router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("", response_model=RecommendationsResponse)
def recommend(request: RecommendationRequest, service: RecommendationService = Depends(get_recommendation_service)) -> RecommendationsResponse:
    logger.debug("recommendations_request_accepted limit=%d subject_axes=%d", request.limit, len(request.profile.preferred_subject_weights))
    result = service.recommend(request.to_contract())
    logger.info("recommendations_http_complete status=200 result_count=%d top_fit=%s", len(result.recommendations), result.recommendations[0].content_fit if result.recommendations else "none")
    return recommendations_response(result)


@router.get("/current", response_model=CurrentRecommendationsResponse)
def current_recommendations(
    limit: int = Query(default=10, ge=1, le=20),
    scope: ProfileScope = Depends(get_profile_scope),
    service: CurrentRecommendationService = Depends(get_current_recommendation_service),
) -> CurrentRecommendationsResponse:
    logger.debug("current_recommendations_request_accepted limit=%d", limit)
    result = service.recommend(scope, limit=limit)
    logger.info("current_recommendations_http_complete status=200 result_count=%d", len(result.recommendations))
    return recommendations_response(result)


__all__ = ["router"]
