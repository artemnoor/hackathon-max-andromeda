from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import VenueModel


def _venue(**overrides: object) -> VenueModel:
    values: dict[str, object] = {
        "id": "venue:bmstu:constraint-test",
        "point_type": "building",
        "name": "Test point",
        "latitude": Decimal("55.7"),
        "longitude": Decimal("37.6"),
        "source_kind": "bmstu_campus_points",
        "source_url": "https://bmstu.ru/campus/points",
        "captured_at": datetime.now(timezone.utc),
        "content_sha256": "a" * 64,
    }
    values.update(overrides)
    return VenueModel(**values)


@pytest.mark.parametrize("point_type", ["scene", "mesh", ""])
def test_database_rejects_unknown_campus_point_type(tmp_path, point_type: str) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'campus-constraints.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_venue(point_type=point_type))
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_incomplete_campus_coordinates(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'campus-coordinate-constraints.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(_venue(longitude=None))
        with pytest.raises(IntegrityError):
            session.commit()
