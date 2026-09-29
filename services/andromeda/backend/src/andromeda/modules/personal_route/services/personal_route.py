"""Deterministic logical personal-plan orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging

from andromeda.modules.campus.contracts.public import CampusPointDetail
from andromeda.modules.events.contracts.public import Event, EventFilters
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.recommendations.contracts.public import Recommendation
from andromeda.shared.contracts.errors import ValidationError
from andromeda.shared.contracts.ids import ProgramId

from ..contracts.public import PersonalRoutePlan, PersonalRouteRequest, PersonalRouteStatus, PersonalRouteStep, PersonalRouteStepKind
from ..contracts.results import PersonalRouteResult
from ..repository.ports import CampusRecommendationReader, CurrentRecommendationReader, PersonalRouteEventReader


logger = logging.getLogger("andromeda.personal_route")


class PersonalRouteService:
    """Assemble optional support suggestions from current recommendations and source reads."""

    def __init__(
        self,
        recommendations: CurrentRecommendationReader,
        events: PersonalRouteEventReader,
        campus: CampusRecommendationReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._recommendations = recommendations
        self._events = events
        self._campus = campus
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build(self, scope: ProfileScope, request: PersonalRouteRequest) -> PersonalRouteResult:
        logger.debug("personal_route_start limit=%d", request.limit)
        recommendation_result = self._recommendations.recommend(scope, limit=request.limit)
        recommendations = _unique_recommendations(recommendation_result.recommendations)
        if not recommendations:
            logger.warning("personal_route_empty status=%s recommendation_count=0", PersonalRouteStatus.NO_RECOMMENDATIONS.value)
            return PersonalRouteResult(
                plan=PersonalRoutePlan(
                    status=PersonalRouteStatus.NO_RECOMMENDATIONS,
                    summary="Дополнительные материалы появятся, когда в системе будут доступны предложения программ.",
                )
            )

        program_ids = tuple(item.program_id for item in recommendations)
        steps = _program_steps(recommendations)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            logger.error("personal_route_rejected reason=clock_not_timezone_aware")
            raise ValidationError("personal route clock must be timezone-aware")

        try:
            events_result = self._events.list(
                EventFilters(
                    from_date=now,
                    recommended=True,
                    recommended_program_ids=program_ids,
                    limit=request.limit,
                )
            )
            campus_result = self._campus.recommendations(program_ids, limit=request.limit)
        except Exception:
            logger.exception("personal_route_dependency_failed program_count=%d", len(program_ids))
            raise

        points_by_id: dict[str, CampusPointDetail] = {point.id: point for point in campus_result.points}
        event_steps = _event_steps(
            events_result.items,
            program_ids,
            points_by_id,
            not_before=now,
            start_position=len(steps) + 1,
        )
        steps.extend(event_steps)
        status = PersonalRouteStatus.READY if event_steps else PersonalRouteStatus.NO_EVENTS
        summary = (
            "Доступны дополнительные материалы по программам и связанные события; порядок действий выбираете вы."
            if event_steps
            else "По программам есть материалы для изучения; подходящих будущих событий пока нет."
        )
        result = PersonalRouteResult(
            plan=PersonalRoutePlan(
                status=status,
                summary=summary,
                recommendations=recommendations,
                steps=tuple(steps),
            )
        )
        logger.info(
            "personal_route_complete status=%s recommendation_count=%d event_count=%d point_count=%d step_count=%d",
            status.value,
            len(recommendations),
            len(event_steps),
            len(points_by_id),
            len(result.plan.steps),
        )
        return result


def _unique_recommendations(recommendations: tuple[Recommendation, ...]) -> tuple[Recommendation, ...]:
    seen: set[str] = set()
    result: list[Recommendation] = []
    for recommendation in recommendations:
        if recommendation.program_id in seen:
            logger.debug("personal_route_recommendation_skipped program_id=%s reason=duplicate", recommendation.program_id)
            continue
        seen.add(recommendation.program_id)
        result.append(recommendation)
    return tuple(result)


def _program_steps(recommendations: tuple[Recommendation, ...]) -> list[PersonalRouteStep]:
    first = recommendations[0]
    steps = [
        PersonalRouteStep(
            position=1,
            kind=PersonalRouteStepKind.EXPLORE_PROGRAM,
            reason=_explore_reason(first),
            program_ids=(first.program_id,),
            recommendation=first,
        )
    ]
    if len(recommendations) >= 2:
        steps.append(
            PersonalRouteStep(
                position=2,
                kind=PersonalRouteStepKind.COMPARE_PROGRAMS,
                reason="Если хотите сузить выбор, сравните два варианта по учебным планам.",
                program_ids=(recommendations[0].program_id, recommendations[1].program_id),
            )
        )
    return steps


def _explore_reason(recommendation: Recommendation) -> str:
    if recommendation.reasons:
        return f"При желании изучите программу: {recommendation.reasons[0].text}"
    return f"При желании изучите программу из подборки Content Fit: {recommendation.program_id}."


def _event_steps(
    events: tuple[Event, ...],
    recommended_program_ids: tuple[ProgramId, ...],
    points_by_id: dict[str, CampusPointDetail],
    *,
    not_before: datetime,
    start_position: int,
) -> list[PersonalRouteStep]:
    recommended = set(recommended_program_ids)
    unique: dict[str, Event] = {}
    for event in events:
        if event.id in unique:
            continue
        if event.starts_at.astimezone(timezone.utc) < not_before.astimezone(timezone.utc):
            logger.debug("personal_route_event_skipped event_id=%s reason=past_event", event.id)
            continue
        linked = tuple(program_id for program_id in recommended_program_ids if program_id in event.program_ids)
        if not linked:
            logger.debug("personal_route_event_skipped event_id=%s reason=no_recommended_program_link", event.id)
            continue
        unique[event.id] = event

    ordered = sorted(unique.values(), key=lambda item: (item.starts_at.astimezone(timezone.utc), item.id))
    result: list[PersonalRouteStep] = []
    for offset, event in enumerate(ordered):
        linked = tuple(program_id for program_id in recommended_program_ids if program_id in event.program_ids and program_id in recommended)
        point = points_by_id.get(event.venue.id) if event.venue is not None else None
        result.append(
            PersonalRouteStep(
                position=start_position + offset,
                kind=PersonalRouteStepKind.ATTEND_EVENT,
                reason="При желании посетите событие, связанное с программой из вашего выбора.",
                program_ids=linked,
                event_id=event.id,
                event=event,
                venue_id=event.venue.id if event.venue is not None else None,
                point=point if event.venue is not None else None,
                starts_at=event.starts_at,
            )
        )
    return result


__all__ = ["PersonalRouteService"]
