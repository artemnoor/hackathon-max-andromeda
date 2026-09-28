from datetime import datetime, timedelta, timezone

import pytest

from andromeda.modules.campus.contracts.public import CampusRecommendationResult
from andromeda.modules.events.contracts.public import Event, EventFormat, EventListResult
from andromeda.modules.personal_route.contracts.public import PersonalRouteRequest, PersonalRouteStatus, PersonalRouteStepKind
from andromeda.modules.personal_route.services.personal_route import PersonalRouteService
from andromeda.modules.proftest.contracts.public import ProfileScope, UserProfile
from andromeda.modules.recommendations.contracts.public import RecommendationResult
from andromeda.shared.contracts.errors import NotFoundError

from .test_contracts import PROGRAM_A, PROGRAM_B, _event, _recommendation


NOW = datetime(2026, 9, 14, 0, tzinfo=timezone.utc)
SCOPE = ProfileScope(session_key_hash="a" * 64)


class FakeRecommendations:
    def __init__(self, result: RecommendationResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.limits: list[int] = []

    def recommend(self, scope: ProfileScope, *, limit: int) -> RecommendationResult:
        del scope
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeEvents:
    def __init__(self, events: tuple[Event, ...]) -> None:
        self.events = events
        self.filters = None

    def list(self, filters) -> EventListResult:  # type: ignore[no-untyped-def]
        self.filters = filters
        return EventListResult(items=self.events, total=len(self.events))


class FakeCampus:
    def __init__(self) -> None:
        self.program_ids = None
        self.limit = None

    def recommendations(self, program_ids, *, limit: int) -> CampusRecommendationResult:  # type: ignore[no-untyped-def]
        self.program_ids = program_ids
        self.limit = limit
        return CampusRecommendationResult(recommended_program_ids=program_ids)


def _result(*recommendations) -> RecommendationResult:  # type: ignore[no-untyped-def]
    return RecommendationResult(profile=UserProfile(), recommendations=tuple(recommendations))


def _service(recommendations, events: tuple[Event, ...], *, clock=lambda: NOW):  # type: ignore[no-untyped-def]
    recommendation_reader = FakeRecommendations(_result(*recommendations))
    event_reader = FakeEvents(events)
    campus_reader = FakeCampus()
    service = PersonalRouteService(recommendation_reader, event_reader, campus_reader, clock=clock)
    return service, recommendation_reader, event_reader, campus_reader


def test_build_is_deterministic_and_preserves_logical_order_and_canonical_ids() -> None:
    first = _event().model_copy(update={"id": "event:bmstu:z-event", "starts_at": datetime(2026, 10, 17, 11, tzinfo=timezone.utc)})
    same_instant = _event().model_copy(
        update={"id": "event:bmstu:a-event", "starts_at": datetime(2026, 10, 17, 14, tzinfo=timezone(timedelta(hours=3)))}
    )
    service, recommendations, events, campus = _service(
        (_recommendation(), _recommendation(PROGRAM_B, "09.03.01-12"), _recommendation()),
        (first, same_instant, first),
    )

    result = service.build(SCOPE, PersonalRouteRequest(limit=5))
    repeated = service.build(SCOPE, PersonalRouteRequest(limit=5))

    assert result == repeated
    assert recommendations.limits == [5, 5]
    assert events.filters.recommended is True
    assert events.filters.recommended_program_ids == (PROGRAM_A, PROGRAM_B)
    assert campus.program_ids == (PROGRAM_A, PROGRAM_B)
    assert [step.kind for step in result.plan.steps] == [
        PersonalRouteStepKind.EXPLORE_PROGRAM,
        PersonalRouteStepKind.COMPARE_PROGRAMS,
        PersonalRouteStepKind.ATTEND_EVENT,
        PersonalRouteStepKind.ATTEND_EVENT,
    ]
    assert [step.event_id for step in result.plan.steps[2:]] == ["event:bmstu:a-event", "event:bmstu:z-event"]
    assert result.plan.steps[0].program_ids == (PROGRAM_A,)
    assert result.plan.steps[1].program_ids == (PROGRAM_A, PROGRAM_B)


def test_past_unrelated_and_programless_events_are_not_plan_steps() -> None:
    past = _event().model_copy(update={"id": "event:bmstu:past", "starts_at": datetime(2026, 9, 13, tzinfo=timezone.utc)})
    unrelated = _event().model_copy(update={"id": "event:bmstu:unrelated", "program_ids": (PROGRAM_B,)})
    programless = _event().model_copy(update={"id": "event:bmstu:programless", "program_ids": ()})
    service, _, _, _ = _service((_recommendation(),), (past, unrelated, programless))

    result = service.build(SCOPE, PersonalRouteRequest(limit=3))

    assert result.plan.status is PersonalRouteStatus.NO_EVENTS
    assert len(result.plan.steps) == 1


def test_online_event_without_venue_is_kept_as_logical_event_step() -> None:
    online = _event(venue=False).model_copy(
        update={
            "id": "event:bmstu:online",
            "format": EventFormat.ONLINE,
            "starts_at": datetime(2026, 12, 5, tzinfo=timezone.utc),
            "ends_at": datetime(2026, 12, 5, 1, 30, tzinfo=timezone.utc),
        }
    )
    service, _, _, _ = _service((_recommendation(),), (online,))

    result = service.build(SCOPE, PersonalRouteRequest(limit=3))

    step = result.plan.steps[-1]
    assert step.kind is PersonalRouteStepKind.ATTEND_EVENT
    assert step.event_id == "event:bmstu:online"
    assert step.venue_id is None and step.point is None


def test_empty_recommendations_and_missing_profile_are_explicit() -> None:
    empty_service, _, _, _ = _service((), ())
    empty = empty_service.build(SCOPE, PersonalRouteRequest())
    assert empty.plan.status is PersonalRouteStatus.NO_RECOMMENDATIONS
    assert empty.plan.steps == ()

    missing_recommendations = FakeRecommendations(error=NotFoundError("Current profile was not found"))
    service = PersonalRouteService(missing_recommendations, FakeEvents(()), FakeCampus(), clock=lambda: NOW)
    with pytest.raises(NotFoundError):
        service.build(SCOPE, PersonalRouteRequest())


def test_naive_clock_is_rejected() -> None:
    service, _, _, _ = _service((_recommendation(),), (), clock=lambda: datetime(2026, 9, 14))

    with pytest.raises(Exception, match="timezone-aware"):
        service.build(SCOPE, PersonalRouteRequest())
