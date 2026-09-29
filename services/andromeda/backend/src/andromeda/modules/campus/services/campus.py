"""Campus use cases; no map or recommendation implementation dependencies."""

from __future__ import annotations

import logging

from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import ProgramId, VenueId

from ..contracts.public import CampusEventFilters, CampusPointFilters
from ..contracts.results import CampusPointDetailResult, CampusPointEventsResult, CampusPointListResult, CampusRecommendationResult
from ..repository.ports import CampusPointReader


logger = logging.getLogger("andromeda.campus")


class CampusService:
    """Application boundary for stable campus point reads."""

    def __init__(self, points: CampusPointReader) -> None:
        self._points = points

    def list(self, filters: CampusPointFilters) -> CampusPointListResult:
        logger.debug(
            "campus_points_use_case_start university=%s department=%s program=%s point_type=%s limit=%d",
            filters.university_id,
            filters.department_id,
            filters.program_id,
            filters.point_type.value if filters.point_type else None,
            filters.limit,
        )
        result = self._points.list(filters)
        if not result.items:
            logger.warning("campus_points_use_case_empty total=%d", result.total)
        logger.info("campus_points_use_case_complete result_count=%d total=%d", len(result.items), result.total)
        return result

    def get(self, point_id: VenueId) -> CampusPointDetailResult:
        logger.debug("campus_point_detail_use_case_start point_id=%s", point_id)
        result = self._points.get(point_id)
        if result is None:
            logger.warning("campus_point_detail_not_found point_id=%s", point_id)
            raise NotFoundError("Campus point was not found")
        logger.info("campus_point_detail_use_case_complete point_id=%s", point_id)
        return result

    def events(self, point_id: VenueId, filters: CampusEventFilters) -> CampusPointEventsResult:
        logger.debug(
            "campus_point_events_use_case_start point_id=%s recommended=%s limit=%d",
            point_id,
            filters.recommended,
            filters.limit,
        )
        result = self._points.events(point_id, filters)
        if not result.items:
            logger.warning("campus_point_events_use_case_empty point_id=%s total=%d", point_id, result.total)
        logger.info("campus_point_events_use_case_complete point_id=%s result_count=%d total=%d", point_id, len(result.items), result.total)
        return result

    def recommendations(self, program_ids: tuple[ProgramId, ...], *, limit: int = 50) -> CampusRecommendationResult:
        if not program_ids or len(program_ids) != len(set(program_ids)) or limit < 1 or limit > 100:
            logger.error("campus_recommendations_rejected reason=invalid_program_ids count=%d", len(program_ids))
            raise ValueError("campus recommendations require unique canonical program IDs and a bounded limit")
        logger.debug("campus_recommendations_use_case_start program_count=%d limit=%d", len(program_ids), limit)
        result = self._points.recommendations(program_ids, limit=limit)
        logger.info(
            "campus_recommendations_use_case_complete program_count=%d point_count=%d event_count=%d unplaced_event_count=%d",
            len(result.recommended_program_ids),
            len(result.points),
            len(result.events),
            len(result.events_without_point),
        )
        return result


__all__ = ["CampusService"]
