from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_current_recommendation_service, get_event_service
from andromeda.api.schemas.events import EventDetailResponse, EventListResponse, event_detail_response, event_list_response
from andromeda.modules.events.contracts.public import EventFilters, EventFormat, EventKind
from andromeda.modules.events.services.events import EventService
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.recommendations.services.current import CurrentRecommendationService
from andromeda.shared.contracts.ids import DepartmentId, EventId, ProgramId, UniversityId


logger = logging.getLogger("andromeda.api.events")
router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventListResponse, operation_id="list_events")
def list_events(
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    kind: EventKind | None = None,
    format: EventFormat | None = None,
    university_id: UniversityId | None = Query(default=None, alias="universityId"),
    department_id: DepartmentId | None = Query(default=None, alias="departmentId"),
    program_id: ProgramId | None = Query(default=None, alias="programId"),
    recommended: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    scope: ProfileScope = Depends(get_profile_scope),
    service: EventService = Depends(get_event_service),
    current_recommendations: CurrentRecommendationService = Depends(get_current_recommendation_service),
) -> EventListResponse:
    recommended_program_ids: tuple[str, ...] = ()
    if recommended:
        recommendation_result = current_recommendations.recommend(scope, limit=20)
        recommended_program_ids = tuple(item.program_id for item in recommendation_result.recommendations)
    try:
        filters = EventFilters(
            from_date=from_date,
            to_date=to_date,
            kind=kind,
            format=format,
            university_id=university_id,
            department_id=department_id,
            program_id=program_id,
            recommended=recommended,
            recommended_program_ids=recommended_program_ids,
            limit=limit,
        )
    except PydanticValidationError as exc:
        logger.warning("events_http_rejected reason=invalid_filters field_count=%d", len(exc.errors()))
        raise RequestValidationError(exc.errors()) from exc
    logger.debug(
        "events_http_request_accepted recommended=%s kind=%s format=%s limit=%d recommended_program_count=%d",
        recommended,
        kind.value if kind else None,
        format.value if format else None,
        limit,
        len(recommended_program_ids),
    )
    result = service.list(filters)
    response = event_list_response(result)
    logger.info("events_http_complete status=200 result_count=%d total=%d recommended=%s", len(response.items), response.total, recommended)
    return response


@router.get("/{id}", response_model=EventDetailResponse, operation_id="get_event")
def get_event(
    id: EventId,
    service: EventService = Depends(get_event_service),
) -> EventDetailResponse:
    logger.debug("events_detail_http_request_accepted event_id=%s", id)
    result = service.get(id)  # EventService validates the repository boundary.
    response = event_detail_response(result.event)
    logger.info("events_detail_http_complete status=200 event_id=%s", id)
    return response


__all__ = ["router"]
