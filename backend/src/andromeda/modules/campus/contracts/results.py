from __future__ import annotations

from pydantic import Field, model_validator

from andromeda.modules.events.contracts.public import Event, EventListResult
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import ProgramId, VenueId

from ..domain.entities import CampusPoint, CampusPointDetail


class CampusPointListResult(ContractModel):
    items: tuple[CampusPoint, ...] = ()
    total: int = Field(strict=True, ge=0)


class CampusPointDetailResult(ContractModel):
    point: CampusPointDetail


class CampusPointEventsResult(ContractModel):
    point_id: VenueId
    events: EventListResult

    @property
    def items(self) -> tuple[Event, ...]:
        return self.events.items

    @property
    def total(self) -> int:
        return self.events.total


class CampusRecommendationResult(ContractModel):
    """Campus data selected by canonical recommended program IDs only."""

    recommended_program_ids: tuple[ProgramId, ...] = Field(min_length=1)
    points: tuple[CampusPointDetail, ...] = ()
    events: tuple[Event, ...] = ()
    events_without_point: tuple[Event, ...] = ()

    @model_validator(mode="after")
    def validate_program_ids(self) -> "CampusRecommendationResult":
        if len(self.recommended_program_ids) != len(set(self.recommended_program_ids)):
            raise ValueError("recommended program IDs must be unique")
        return self

    @classmethod
    def from_parts(
        cls,
        recommended_program_ids: tuple[ProgramId, ...],
        *,
        points: tuple[CampusPointDetail, ...],
        events: tuple[Event, ...],
        events_without_point: tuple[Event, ...],
    ) -> "CampusRecommendationResult":
        return cls(
            recommended_program_ids=recommended_program_ids,
            points=points,
            events=events,
            events_without_point=events_without_point,
        )


__all__ = [
    "CampusPointDetailResult",
    "CampusPointEventsResult",
    "CampusPointListResult",
    "CampusRecommendationResult",
]
