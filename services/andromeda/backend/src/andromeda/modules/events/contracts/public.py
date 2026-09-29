"""Public event contracts shared by ingestion, application, and adapters."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import DepartmentId, ProgramId, UniversityId

from ..domain.entities import Event, EventFormat, EventKind, Venue
from .results import EventListResult


class EventFilters(ContractModel):
    from_date: datetime | None = None
    to_date: datetime | None = None
    kind: EventKind | None = None
    format: EventFormat | None = None
    university_id: UniversityId | None = None
    department_id: DepartmentId | None = None
    program_id: ProgramId | None = None
    recommended: bool = False
    recommended_program_ids: tuple[ProgramId, ...] = ()
    limit: int = Field(default=50, strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def validate_window_and_recommendations(self) -> "EventFilters":
        for field_name, value in (("from_date", self.from_date), ("to_date", self.to_date)):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.from_date is not None and self.to_date is not None and self.to_date < self.from_date:
            raise ValueError("to_date must be greater than or equal to from_date")
        if len(self.recommended_program_ids) != len(set(self.recommended_program_ids)):
            raise ValueError("recommended program IDs must be unique")
        if self.recommended and not self.recommended_program_ids:
            raise ValueError("recommended filtering requires canonical recommended program IDs")
        return self


__all__ = ["Event", "EventFilters", "EventFormat", "EventKind", "EventListResult", "Venue"]
