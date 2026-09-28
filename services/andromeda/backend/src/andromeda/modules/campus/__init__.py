"""Map-agnostic campus data contracts for external consumers."""

from .contracts.public import (
    CampusEventFilters,
    CampusPoint,
    CampusPointDetail,
    CampusPointFilters,
    CampusPointType,
    CampusRecommendationFilters,
)
from .contracts.results import (
    CampusPointDetailResult,
    CampusPointEventsResult,
    CampusPointListResult,
    CampusRecommendationResult,
)
from .repository.ports import CampusPointReader
from .services.campus import CampusService

__all__ = [
    "CampusEventFilters",
    "CampusPoint",
    "CampusPointDetail",
    "CampusPointDetailResult",
    "CampusPointEventsResult",
    "CampusPointFilters",
    "CampusPointListResult",
    "CampusPointReader",
    "CampusPointType",
    "CampusRecommendationFilters",
    "CampusRecommendationResult",
    "CampusService",
]
