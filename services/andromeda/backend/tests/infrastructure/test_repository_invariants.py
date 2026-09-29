from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import DirectionModel, EducationLevelModel, ProgramModel, UniversityModel


def test_university_scoped_direction_and_program_identity_is_database_owned(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'identity.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(EducationLevelModel(id="bachelor"))
        session.add_all(
            [
                UniversityModel(id="university:bmstu", name="BMSTU", city="Москва", official_site="https://bmstu.ru/", address="Москва"),
                UniversityModel(id="university:hse", name="HSE", city="Москва", official_site="https://hse.ru/", address="Москва"),
            ]
        )
        session.flush()
        session.add_all(
            [
                DirectionModel(id="direction:bmstu:09.03.01", university_id="university:bmstu", code="09.03.01", name="Информатика", education_level="bachelor"),
                DirectionModel(id="direction:hse:09.03.01", university_id="university:hse", code="09.03.01", name="Информатика", education_level="bachelor"),
            ]
        )
        session.flush()
        session.add_all(
            [
                ProgramModel(id="program:bmstu:09.03.01-01", direction_id="direction:bmstu:09.03.01", code="09.03.01-01", name="BMSTU", education_year=2026, study_plan_url="https://bmstu.ru/plan", source_url="https://bmstu.ru/program"),
                ProgramModel(id="program:hse:09.03.01-01", direction_id="direction:hse:09.03.01", code="09.03.01-01", name="HSE", education_year=2026, study_plan_url="https://hse.ru/plan", source_url="https://hse.ru/program"),
            ]
        )
        session.commit()

        session.add(DirectionModel(id="direction:bmstu:09.03.01-duplicate", university_id="university:bmstu", code="09.03.01", name="Duplicate", education_level="bachelor"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(ProgramModel(id="program:bmstu:09.03.01-02", direction_id="direction:bmstu:09.03.01", code="09.03.01-01", name="Duplicate", education_year=2026, study_plan_url="https://bmstu.ru/plan-2", source_url="https://bmstu.ru/program-2"))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_lifecycle_indexes_cover_expiry_and_reverse_link_predicates(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'indexes.db').as_posix()}")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert {item["name"] for item in inspector.get_indexes("auth_sessions")} >= {"ix_auth_sessions_expiry"}
    assert {item["name"] for item in inspector.get_indexes("user_profiles")} >= {"ix_user_profiles_expiry"}
    assert {item["name"] for item in inspector.get_indexes("event_university_links")} >= {"ix_event_university_links_university_id"}
    assert {item["name"] for item in inspector.get_indexes("event_department_links")} >= {"ix_event_department_links_department_id"}
    engine.dispose()
