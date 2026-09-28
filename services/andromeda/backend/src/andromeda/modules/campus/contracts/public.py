"""Public, transport-independent contracts for campus reads."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import DepartmentId, ProgramId, UniversityId, VenueId

from ..domain.entities import CampusPoint, CampusPointDetail, CampusPointType

# Result envelopes are re-exported from the public module so consumers use the
# same public-surface rule as the other subject modules. The results module
# imports only domain types, so this late import does not form a cycle.
from .results import CampusRecommendationResult


class CampusPointFilters(ContractModel):
    university_id: UniversityId | None = None
    department_id: DepartmentId | None = None
    program_id: ProgramId | None = None
    point_type: CampusPointType | None = None
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class CampusEventFilters(ContractModel):
    from_date: datetime | None = None
    to_date: datetime | None = None
    recommended: bool = False
    recommended_program_ids: tuple[ProgramId, ...] = ()
    limit: int = Field(default=50, strict=True, ge=1, le=100)

    @model_validator(mode="after")
    def validate_window_and_recommendations(self) -> "CampusEventFilters":
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


class CampusRecommendationFilters(ContractModel):
    limit: int = Field(default=50, strict=True, ge=1, le=100)


__all__ = [
    "CampusEventFilters",
    "CampusPoint",
    "CampusPointDetail",
    "CampusPointFilters",
    "CampusPointType",
    "CampusRecommendationFilters",
    "CampusRecommendationResult",
]
