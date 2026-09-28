"""Storage ports consumed by the campus application service."""

from __future__ import annotations

from typing import Protocol

from andromeda.shared.contracts.ids import ProgramId, VenueId

from ..contracts.public import CampusEventFilters, CampusPointFilters
from ..contracts.results import CampusPointDetailResult, CampusPointEventsResult, CampusPointListResult, CampusRecommendationResult


class CampusPointReader(Protocol):
    def list(self, filters: CampusPointFilters) -> CampusPointListResult: ...

    def get(self, point_id: VenueId) -> CampusPointDetailResult | None: ...

    def events(self, point_id: VenueId, filters: CampusEventFilters) -> CampusPointEventsResult: ...

    def recommendations(self, program_ids: tuple[ProgramId, ...], *, limit: int) -> CampusRecommendationResult: ...


__all__ = ["CampusPointReader"]
