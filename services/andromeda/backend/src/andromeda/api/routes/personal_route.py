"""Thin HTTP adapter for the current user's logical personal plan."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_personal_route_service
from andromeda.api.schemas.personal_route import PersonalRouteResponse, personal_route_response
from andromeda.modules.personal_route.contracts.public import PersonalRouteRequest
from andromeda.modules.personal_route.services.personal_route import PersonalRouteService
from andromeda.modules.proftest.contracts.public import ProfileScope


logger = logging.getLogger("andromeda.api.personal_route")
router = APIRouter(prefix="/personal-route", tags=["personal-route"])


@router.get("", response_model=PersonalRouteResponse, operation_id="get_personal_route")
def get_personal_route(
    limit: int = Query(default=10, ge=1, le=20),
    scope: ProfileScope = Depends(get_profile_scope),
    service: PersonalRouteService = Depends(get_personal_route_service),
) -> PersonalRouteResponse:
    logger.debug("personal_route_http_request_accepted limit=%d", limit)
    result = service.build(scope, PersonalRouteRequest(limit=limit))
    response = personal_route_response(result)
    logger.info(
        "personal_route_http_complete status=200 plan_status=%s recommendation_count=%d step_count=%d",
        response.status.value,
        len(response.recommendations),
        len(response.steps),
    )
    return response


__all__ = ["router"]
