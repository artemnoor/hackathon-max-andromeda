"""Thin read-only HTTP adapter for external campus/map consumers."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from andromeda.api.dependencies import get_campus_service, get_current_recommendation_service
from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.schemas.campus import (
    CampusPointDetailResponse,
    CampusPointEventsResponse,
    CampusPointListResponse,
    CampusRecommendationsResponse,
    campus_point_detail_response,
    campus_point_events_response,
    campus_point_list_response,
    campus_recommendations_response,
)
from andromeda.modules.campus.contracts.public import CampusEventFilters, CampusPointFilters
from andromeda.modules.campus.domain.entities import CampusPointType
from andromeda.modules.campus.services.campus import CampusService
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.recommendations.services.current import CurrentRecommendationService
from andromeda.shared.contracts.ids import DepartmentId, ProgramId, UniversityId, VenueId


logger = logging.getLogger("andromeda.api.campus")
router = APIRouter(prefix="/campus", tags=["campus"])


@router.get("/points", response_model=CampusPointListResponse, operation_id="list_campus_points")
def list_campus_points(
    university_id: UniversityId | None = Query(default=None, alias="universityId"),
    department_id: DepartmentId | None = Query(default=None, alias="departmentId"),
    program_id: ProgramId | None = Query(default=None, alias="programId"),
    point_type: CampusPointType | None = Query(default=None, alias="pointType"),
    limit: int = Query(default=50, ge=1, le=100),
    service: CampusService = Depends(get_campus_service),
) -> CampusPointListResponse:
    try:
        filters = CampusPointFilters(
            university_id=university_id,
            department_id=department_id,
            program_id=program_id,
            point_type=point_type,
            limit=limit,
        )
    except PydanticValidationError as exc:
        logger.warning("campus_points_http_rejected reason=invalid_filters field_count=%d", len(exc.errors()))
        raise RequestValidationError(exc.errors()) from exc
    logger.debug(
        "campus_points_http_request_accepted university=%s department=%s program=%s point_type=%s limit=%d",
        university_id,
        department_id,
        program_id,
        point_type.value if point_type else None,
        limit,
    )
    result = service.list(filters)
    response = campus_point_list_response(result)
    logger.info("campus_points_http_complete status=200 result_count=%d total=%d", len(response.items), response.total)
    return response


@router.get("/recommendations", response_model=CampusRecommendationsResponse, operation_id="get_campus_recommendations")
def get_campus_recommendations(
    limit: int = Query(default=50, ge=1, le=100),
    scope: ProfileScope = Depends(get_profile_scope),
    service: CampusService = Depends(get_campus_service),
    current_recommendations: CurrentRecommendationService = Depends(get_current_recommendation_service),
) -> CampusRecommendationsResponse:
    logger.debug("campus_recommendations_http_request_accepted limit=%d", limit)
    recommendation_result = current_recommendations.recommend(scope, limit=min(limit, 20))
    recommended_program_ids = tuple(item.program_id for item in recommendation_result.recommendations)
    result = service.recommendations(recommended_program_ids, limit=limit)
    response = campus_recommendations_response(result, recommendation_result.recommendations)
    logger.info(
        "campus_recommendations_http_complete status=200 program_count=%d point_count=%d event_count=%d unplaced_event_count=%d",
        len(response.recommended_program_ids),
        len(response.points),
        len(response.events),
        len(response.events_without_point),
    )
    return response


@router.get("/points/{id}", response_model=CampusPointDetailResponse, operation_id="get_campus_point")
def get_campus_point(
    id: VenueId,
    service: CampusService = Depends(get_campus_service),
) -> CampusPointDetailResponse:
    logger.debug("campus_point_detail_http_request_accepted point_id=%s", id)
    result = service.get(id)
    response = campus_point_detail_response(result.point)
    logger.info("campus_point_detail_http_complete status=200 point_id=%s", id)
    return response


@router.get("/points/{id}/events", response_model=CampusPointEventsResponse, operation_id="list_campus_point_events")
def list_campus_point_events(
    id: VenueId,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    recommended: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    scope: ProfileScope = Depends(get_profile_scope),
    service: CampusService = Depends(get_campus_service),
    current_recommendations: CurrentRecommendationService = Depends(get_current_recommendation_service),
) -> CampusPointEventsResponse:
    recommended_program_ids: tuple[str, ...] = ()
    if recommended:
        recommendation_result = current_recommendations.recommend(scope, limit=20)
        recommended_program_ids = tuple(item.program_id for item in recommendation_result.recommendations)
    try:
        filters = CampusEventFilters(
            from_date=from_date,
            to_date=to_date,
            recommended=recommended,
            recommended_program_ids=recommended_program_ids,
            limit=limit,
        )
    except PydanticValidationError as exc:
        logger.warning("campus_point_events_http_rejected reason=invalid_filters field_count=%d", len(exc.errors()))
        raise RequestValidationError(exc.errors()) from exc
    logger.debug(
        "campus_point_events_http_request_accepted point_id=%s recommended=%s limit=%d recommended_program_count=%d",
        id,
        recommended,
        limit,
        len(recommended_program_ids),
    )
    result = service.events(id, filters)
    response = campus_point_events_response(result)
    logger.info(
        "campus_point_events_http_complete status=200 point_id=%s result_count=%d total=%d recommended=%s",
        id,
        len(response.items),
        response.total,
        recommended,
    )
    return response


__all__ = ["router"]
