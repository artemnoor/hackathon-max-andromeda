"""Typed read ports consumed by the personal-route application service."""

from __future__ import annotations

from typing import Protocol

from andromeda.modules.campus.contracts.public import CampusRecommendationResult
from andromeda.modules.events.contracts.public import EventFilters, EventListResult
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.recommendations.contracts.public import RecommendationResult
from andromeda.shared.contracts.ids import ProgramId


class CurrentRecommendationReader(Protocol):
    """Read current-session Content Fit without exposing storage details."""

    def recommend(self, scope: ProfileScope, *, limit: int) -> RecommendationResult: ...


class PersonalRouteEventReader(Protocol):
    """Read source-backed events through the existing event filter contract."""

    def list(self, filters: EventFilters) -> EventListResult: ...


class CampusRecommendationReader(Protocol):
    """Read existing point cards associated with canonical program IDs."""

    def recommendations(self, program_ids: tuple[ProgramId, ...], *, limit: int) -> CampusRecommendationResult: ...


__all__ = ["CampusRecommendationReader", "CurrentRecommendationReader", "PersonalRouteEventReader"]
