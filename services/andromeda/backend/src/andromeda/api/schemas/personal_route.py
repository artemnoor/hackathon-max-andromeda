"""Strict HTTP projection for the logical personal-route plan."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from andromeda.modules.personal_route.contracts.public import PersonalRouteStatus, PersonalRouteStep, PersonalRouteStepKind
from andromeda.modules.personal_route.contracts.results import PersonalRouteResult
from andromeda.shared.contracts.ids import EventId, ProgramId, VenueId

from .campus import CampusPointDetailResponse, campus_point_detail_response
from .common import ApiModel
from .events import EventResponse, event_response
from .proftest import RecommendationResponse, recommendation_response


class PersonalRouteStepResponse(ApiModel):
    position: int = Field(strict=True, ge=1, le=100)
    kind: PersonalRouteStepKind
    reason: str = Field(min_length=1, max_length=512)
    program_ids: tuple[ProgramId, ...] = ()
    recommendation: RecommendationResponse | None = None
    event_id: EventId | None = None
    event: EventResponse | None = None
    venue_id: VenueId | None = None
    point: CampusPointDetailResponse | None = None
    starts_at: datetime | None = None


class PersonalRouteResponse(ApiModel):
    status: PersonalRouteStatus
    summary: str = Field(min_length=1, max_length=512)
    recommendations: tuple[RecommendationResponse, ...] = ()
    steps: tuple[PersonalRouteStepResponse, ...] = ()


def personal_route_response(result: PersonalRouteResult) -> PersonalRouteResponse:
    return PersonalRouteResponse(
        status=result.plan.status,
        summary=result.plan.summary,
        recommendations=tuple(recommendation_response(item) for item in result.plan.recommendations),
        steps=tuple(personal_route_step_response(item) for item in result.plan.steps),
    )


def personal_route_step_response(step: PersonalRouteStep) -> PersonalRouteStepResponse:
    return PersonalRouteStepResponse(
        position=step.position,
        kind=step.kind,
        reason=step.reason,
        program_ids=step.program_ids,
        recommendation=recommendation_response(step.recommendation) if step.recommendation is not None else None,
        event_id=step.event_id,
        event=event_response(step.event) if step.event is not None else None,
        venue_id=step.venue_id,
        point=campus_point_detail_response(step.point) if step.point is not None else None,
        starts_at=step.starts_at,
    )


__all__ = ["PersonalRouteResponse", "PersonalRouteStepResponse", "personal_route_response", "personal_route_step_response"]
