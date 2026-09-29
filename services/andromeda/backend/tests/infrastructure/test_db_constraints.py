from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import CurriculumItemModel, CurriculumModel, DirectionModel, DisciplineModel, EducationLevelModel, ProgramModel, UniversityModel, UserProfileModel


def test_curriculum_item_identity_is_non_null_and_unique(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'constraints.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                EducationLevelModel(id="bachelor"),
                UniversityModel(id="university:bmstu", name="BMSTU", city="Москва", official_site="https://bmstu.ru/", address="Москва"),
                DisciplineModel(id="discipline:0123456789abcdef", name="Математика", normalized_name="математика"),
            ]
        )
        session.flush()
        session.add(DirectionModel(id="direction:bmstu:09.03.01", university_id="university:bmstu", code="09.03.01", name="Информатика", education_level="bachelor"))
        session.flush()
        session.add(ProgramModel(id="program:bmstu:09.03.01-02", direction_id="direction:bmstu:09.03.01", code="09.03.01-02", name="Программа", education_year=2026, study_plan_url="https://example.com/plan.pdf", source_url="https://example.com/"))
        session.flush()
        session.add(CurriculumModel(id="curriculum:bmstu:09.03.01-02-2026", program_id="program:bmstu:09.03.01-02", education_year=2026, source_url="https://example.com/plan.pdf", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        session.flush()
        session.add(
            CurriculumItemModel(
                id="item-a",
                curriculum_id="curriculum:bmstu:09.03.01-02-2026",
                discipline_id="discipline:0123456789abcdef",
                source_name="Математика",
                semester=None,
                semester_identity="unassigned",
                hours=1,
                credits=None,
            )
        )
        session.commit()
        session.add(
            CurriculumItemModel(
                id="item-b",
                curriculum_id="curriculum:bmstu:09.03.01-02-2026",
                discipline_id="discipline:0123456789abcdef",
                source_name="Математика",
                semester=None,
                semester_identity="unassigned",
                hours=1,
                credits=None,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate semester identity must be rejected")


def test_user_profile_revision_and_session_hash_constraints(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'profile-constraints.db').as_posix()}")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    values = {
        "profile_id": "profile:" + "a" * 32,
        "session_key_hash": "b" * 64,
        "profile_json": {"version": 1},
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "expires_at": now.replace(year=now.year + 1),
    }
    with Session(engine) as session:
        session.add(UserProfileModel(**values))
        session.commit()
        session.add(UserProfileModel(**{**values, "profile_id": "profile:" + "c" * 32, "revision": 0}))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(UserProfileModel(**{**values, "profile_id": "profile:" + "d" * 32, "session_key_hash": "short"}))
        with pytest.raises(IntegrityError):
            session.commit()
