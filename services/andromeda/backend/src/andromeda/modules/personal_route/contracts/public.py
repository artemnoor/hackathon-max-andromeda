"""Stable public contracts for the logical personal-plan use case."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.modules.campus.contracts.public import CampusPointDetail
from andromeda.modules.events.contracts.public import Event
from andromeda.modules.recommendations.contracts.public import Recommendation
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import EventId, NonEmptyText, ProgramId, VenueId


class PersonalRouteStepKind(StrEnum):
    """Logical actions; these values intentionally do not describe movement."""

    EXPLORE_PROGRAM = "explore_program"
    COMPARE_PROGRAMS = "compare_programs"
    ATTEND_EVENT = "attend_event"


class PersonalRouteStatus(StrEnum):
    READY = "ready"
    NO_RECOMMENDATIONS = "no_recommendations"
    NO_EVENTS = "no_events"


class PersonalRouteRequest(ContractModel):
    """Bounded read options for the current-session plan."""

    limit: int = Field(default=10, strict=True, ge=1, le=20)


class PersonalRouteStep(ContractModel):
    """One explainable logical action with existing canonical references."""

    position: int = Field(strict=True, ge=1, le=100)
    kind: PersonalRouteStepKind
    reason: NonEmptyText
    program_ids: tuple[ProgramId, ...] = ()
    recommendation: Recommendation | None = None
    event_id: EventId | None = None
    event: Event | None = None
    venue_id: VenueId | None = None
    point: CampusPointDetail | None = None
    starts_at: datetime | None = None

    @model_validator(mode="after")
    def validate_step_shape(self) -> "PersonalRouteStep":
        if self.starts_at is not None and (self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None):
            raise ValueError("personal route step starts_at must be timezone-aware")
        if self.kind is PersonalRouteStepKind.EXPLORE_PROGRAM:
            if len(self.program_ids) != 1 or self.recommendation is None:
                raise ValueError("explore_program step requires one program and its recommendation")
            if self.recommendation.program_id != self.program_ids[0]:
                raise ValueError("explore_program recommendation must match program_ids")
            self._validate_non_event_fields()
        elif self.kind is PersonalRouteStepKind.COMPARE_PROGRAMS:
            if len(self.program_ids) != 2 or len(set(self.program_ids)) != 2:
                raise ValueError("compare_programs step requires two distinct programs")
            if self.recommendation is not None:
                raise ValueError("compare_programs step cannot carry one recommendation")
            self._validate_non_event_fields()
        else:
            self._validate_event_step()
        return self

    def _validate_non_event_fields(self) -> None:
        if any(value is not None for value in (self.event_id, self.event, self.venue_id, self.point, self.starts_at)):
            raise ValueError("program steps cannot carry event or venue data")

    def _validate_event_step(self) -> None:
        if len(self.program_ids) < 1 or self.event_id is None or self.event is None or self.starts_at is None:
            raise ValueError("attend_event step requires event, time and linked program IDs")
        if self.event_id != self.event.id:
            raise ValueError("attend_event event_id must match event.id")
        if self.starts_at.astimezone(timezone.utc) != self.event.starts_at.astimezone(timezone.utc):
            raise ValueError("attend_event starts_at must match event.starts_at")
        if not set(self.program_ids).intersection(self.event.program_ids):
            raise ValueError("attend_event programs must intersect event.program_ids")
        if self.event.venue is None:
            if self.venue_id is not None or self.point is not None:
                raise ValueError("event without venue cannot carry point data")
        else:
            if self.venue_id != self.event.venue.id:
                raise ValueError("attend_event venue_id must match event.venue.id")
            if self.point is not None and self.point.id != self.venue_id:
                raise ValueError("attend_event point must match venue_id")


class PersonalRoutePlan(ContractModel):
    """Read-only plan assembled from a current profile and source-backed data."""

    status: PersonalRouteStatus
    summary: NonEmptyText
    recommendations: tuple[Recommendation, ...] = ()
    steps: tuple[PersonalRouteStep, ...] = ()

    @model_validator(mode="after")
    def validate_plan_shape(self) -> "PersonalRoutePlan":
        recommendation_ids = tuple(item.program_id for item in self.recommendations)
        if len(recommendation_ids) != len(set(recommendation_ids)):
            raise ValueError("personal route recommendations must have unique program IDs")
        positions = tuple(step.position for step in self.steps)
        if positions != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("personal route steps must have contiguous positions")
        if self.status is PersonalRouteStatus.NO_RECOMMENDATIONS:
            if self.recommendations or self.steps:
                raise ValueError("no_recommendations plan cannot contain recommendations or steps")
        elif not self.recommendations:
            raise ValueError("ready/no_events plan requires recommendations")
        if self.status is PersonalRouteStatus.NO_EVENTS and any(step.kind is PersonalRouteStepKind.ATTEND_EVENT for step in self.steps):
            raise ValueError("no_events plan cannot contain attend_event steps")
        return self


__all__ = [
    "PersonalRoutePlan",
    "PersonalRouteRequest",
    "PersonalRouteStatus",
    "PersonalRouteStep",
    "PersonalRouteStepKind",
]
