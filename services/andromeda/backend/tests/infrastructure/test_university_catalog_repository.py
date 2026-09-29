from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import AccountModel, UniversityModel
from andromeda.infrastructure.repositories.university_catalog import SqlAlchemyUniversityCatalogRepository
from andromeda.modules.university_admin.contracts.catalog import CategoryKind, EditorialStatus, UniversityCatalogLinks, UnitType
from andromeda.modules.university_admin.domain.catalog import UniversityCategory, UniversityUnit
from andromeda.shared.contracts.errors import ConflictError


ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _engine(tmp_path: Path):
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'university-catalog.db').as_posix()}" )
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        session.add(AccountModel(account_id=ACCOUNT_ID, email="catalog@example.com", password_hash="hash", created_at=NOW, updated_at=NOW))
        session.add(UniversityModel(id=UNIVERSITY_ID, name="Бауманка", city="Москва", official_site="https://bmstu.ru/", address="Москва"))
        session.commit()
    return engine


def _unit(slug: str, *, revision: int = 1, status: EditorialStatus = EditorialStatus.PUBLISHED) -> UniversityUnit:
    return UniversityUnit(
        unitId=f"unit:bmstu:{slug}",
        universityId=UNIVERSITY_ID,
        unitType=UnitType.FACULTY,
        parentUnitId=None,
        slug=slug,
        name=slug,
        description=None,
        status=status,
        sortOrder=1,
        revision=revision,
        createdByAccountId=ACCOUNT_ID,
        updatedByAccountId=ACCOUNT_ID,
        createdAt=NOW,
        updatedAt=NOW,
    )


def _category(slug: str, *, revision: int = 1, status: EditorialStatus = EditorialStatus.PUBLISHED) -> UniversityCategory:
    return UniversityCategory(
        categoryId=f"category:bmstu:{slug}",
        universityId=UNIVERSITY_ID,
        slug=slug,
        name=slug,
        description=None,
        categoryKind=CategoryKind.PROGRAM,
        status=status,
        sortOrder=1,
        revision=revision,
        createdByAccountId=ACCOUNT_ID,
        updatedByAccountId=ACCOUNT_ID,
        createdAt=NOW,
        updatedAt=NOW,
    )


def test_catalog_repository_enforces_unique_slug_and_expected_revision(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityCatalogRepository(session)
            repository.create_unit(_unit("faculty"))
            with pytest.raises(ConflictError):
                repository.create_unit(_unit("faculty", revision=1))
            changed = _unit("faculty", revision=1)
            changed = changed.model_copy(update={"name": "Новое имя"})
            saved = repository.update_unit(changed, expected_revision=1)
            assert saved.revision == 2
            with pytest.raises(ConflictError):
                repository.update_unit(changed, expected_revision=1)
    finally:
        engine.dispose()


def test_archived_category_keeps_historical_links(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityCatalogRepository(session)
            category = repository.create_category(_category("programs"))
            repository.replace_links(
                UNIVERSITY_ID,
                UniversityCatalogLinks(
                    categoryPrograms=((category.category_id, "program:bmstu:09.03.01-01"),),
                    categoryDisciplines=(),
                    unitPrograms=(),
                    unitDisciplines=(),
                ),
            )
            archived = category.model_copy(update={"status": EditorialStatus.ARCHIVED})
            repository.update_category(archived, expected_revision=1)
            links = repository.read_links(UNIVERSITY_ID)
            assert links.category_programs == ((category.category_id, "program:bmstu:09.03.01-01"),)
            assert repository.list_categories(UNIVERSITY_ID, include_archived=False) == ()
    finally:
        engine.dispose()
