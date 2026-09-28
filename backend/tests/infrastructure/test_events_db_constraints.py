from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import EventModel, VenueModel


def test_event_database_rejects_invalid_time_and_coordinate_pair(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'events-constraints.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            VenueModel(
                id="venue:bmstu:invalid",
                name="Invalid",
                latitude=Decimal("55.0"),
                longitude=None,
                source_kind="bmstu_events",
                source_url="https://bmstu.ru/events",
                captured_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(
            EventModel(
                id="event:bmstu:invalid",
                title="Invalid",
                kind="open_day",
                format="offline",
                starts_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ends_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                source_kind="bmstu_events",
                source_url="https://bmstu.ru/events",
                captured_at=datetime.now(timezone.utc),
                content_sha256="a" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
