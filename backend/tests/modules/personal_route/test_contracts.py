from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.events.contracts.public import Event, EventFormat, EventKind, Venue
from andromeda.modules.personal_route.contracts.public import (
    PersonalRoutePlan,
    PersonalRouteStatus,
    PersonalRouteStep,
    PersonalRouteStepKind,
)
from andromeda.modules.proftest.contracts.public import MatchScore, Recommendation, ScoreBreakdown
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution


PROGRAM_A = "program:09.03.01-02"
PROGRAM_B = "program:09.03.01-12"
EVENT_ID = "event:bmstu:dod-2026"
VENUE_ID = "venue:bmstu:main-campus"
START = datetime(2026, 10, 17, 8, tzinfo=timezone.utc)


def _recommendation(program_id: str = PROGRAM_A, code: str = "09.03.01-02") -> Recommendation:
    return Recommendation(
        program_id=program_id,
        program_code=code,
        program_name="Информатика и вычислительная техника",
        content_fit=88,
        score=MatchScore(
            program_id=program_id,
            program_code=code,
            content_fit=88,
            breakdown=ScoreBreakdown(
                subject_fit=Decimal("80"),
                activity_fit=Decimal("80"),
                distinctive_fit=Decimal("80"),
                anti_penalty=Decimal("0"),
                raw_content_fit=Decimal("88"),
            ),
        ),
    )


def _event(*, venue: bool = True) -> Event:
    return Event(
        id=EVENT_ID,
        title="День открытых дверей ИУ",
        kind=EventKind.ADDITIONAL_EDUCATION,
        format=EventFormat.OFFLINE,
        starts_at=START,
        ends_at=datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
        university_ids=("university:bmstu",),
        program_ids=(PROGRAM_A,),
        venue=Venue(
            id=VENUE_ID,
            name="Главный корпус",
            address="Москва",
            latitude=Decimal("55.7666"),
            longitude=Decimal("37.6855"),
        )
        if venue
        else None,
        provenance=(
            SourceAttribution(
                kind=SourceKind.BMSTU_EVENTS,
                url="https://bmstu.ru/events",
                captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                content_sha256="a" * 64,
            ),
        ),
    )


def test_program_steps_and_plan_positions_are_strict() -> None:
    explore = PersonalRouteStep(
        position=1,
        kind=PersonalRouteStepKind.EXPLORE_PROGRAM,
        reason="Content Fit показывает сильное совпадение.",
        program_ids=(PROGRAM_A,),
        recommendation=_recommendation(),
    )
    compare = PersonalRouteStep(
        position=2,
        kind=PersonalRouteStepKind.COMPARE_PROGRAMS,
        reason="Сопоставьте две верхние рекомендации.",
        program_ids=(PROGRAM_A, PROGRAM_B),
    )

    plan = PersonalRoutePlan(
        status=PersonalRouteStatus.READY,
        summary="Начните с рекомендованной программы.",
        recommendations=(_recommendation(), _recommendation(PROGRAM_B, "09.03.01-12")),
        steps=(explore, compare),
    )

    assert plan.model_dump(mode="json")["steps"][0]["program_ids"] == [PROGRAM_A]


def test_attend_event_requires_matching_existing_event_and_aware_time() -> None:
    event = _event()
    step = PersonalRouteStep(
        position=1,
        kind=PersonalRouteStepKind.ATTEND_EVENT,
        reason="Событие связано с рекомендованной программой.",
        program_ids=(PROGRAM_A,),
        event_id=EVENT_ID,
        event=event,
        venue_id=VENUE_ID,
        starts_at=START,
    )
    assert step.event_id == event.id

    with pytest.raises(ValidationError, match="must match event.starts_at"):
        PersonalRouteStep(
            position=1,
            kind=PersonalRouteStepKind.ATTEND_EVENT,
            reason="Некорректное время.",
            program_ids=(PROGRAM_A,),
            event_id=EVENT_ID,
            event=event,
            venue_id=VENUE_ID,
            starts_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )


def test_no_recommendations_plan_cannot_hide_steps_or_route_fields() -> None:
    with pytest.raises(ValidationError, match="cannot contain recommendations or steps"):
        PersonalRoutePlan(
            status=PersonalRouteStatus.NO_RECOMMENDATIONS,
            summary="Пройдите профтест.",
            recommendations=(_recommendation(),),
        )

    with pytest.raises(ValidationError):
        PersonalRouteStep.model_validate(
            {
                "position": 1,
                "kind": "compare_programs",
                "reason": "Сравнение",
                "programIds": [PROGRAM_A, PROGRAM_B],
                "route": {"distance": 10},
            }
        )
