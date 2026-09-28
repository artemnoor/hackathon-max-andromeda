from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from andromeda.modules.university_admin.contracts.catalog import CategoryKind, EditorialStatus, EditorialVisibility, UniversityCatalogLinks, UnitType
from andromeda.modules.university_admin.services.catalog import UniversityCatalogService
from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError


ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
PROGRAM_ID = "program:bmstu:09.03.01-01"
DISCIPLINE_ID = "discipline:" + "b" * 16


class _Reader:
    def __init__(self) -> None:
        self.units = {}
        self.categories = {}
        self.program_editorials = {}
        self.discipline_editorials = {}
        self.links = UniversityCatalogLinks(categoryPrograms=(), categoryDisciplines=(), unitPrograms=(), unitDisciplines=())

    def get_unit(self, unit_id):
        return self.units.get(unit_id)

    def list_units(self, university_id, *, include_archived=True):
        return tuple(item for item in self.units.values() if item.university_id == university_id and (include_archived or item.status is not EditorialStatus.ARCHIVED))

    def get_category(self, category_id):
        return self.categories.get(category_id)

    def list_categories(self, university_id, *, include_archived=True):
        return tuple(item for item in self.categories.values() if item.university_id == university_id and (include_archived or item.status is not EditorialStatus.ARCHIVED))

    def get_program_editorial(self, university_id, program_id):
        return self.program_editorials.get((university_id, program_id))

    def list_program_editorials(self, university_id):
        return tuple(item for (scope, _), item in self.program_editorials.items() if scope == university_id)

    def get_discipline_editorial(self, university_id, discipline_id):
        return self.discipline_editorials.get((university_id, discipline_id))

    def list_discipline_editorials(self, university_id):
        return tuple(item for (scope, _), item in self.discipline_editorials.items() if scope == university_id)

    def read_links(self, university_id):
        return self.links


class _Writer:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    def create_unit(self, unit):
        self.reader.units[unit.unit_id] = unit
        return unit

    def update_unit(self, unit, *, expected_revision):
        if self.reader.units[unit.unit_id].revision != expected_revision:
            raise ConflictError("Unit revision is stale")
        updated = unit.model_copy(update={"revision": expected_revision + 1})
        self.reader.units[unit.unit_id] = updated
        return updated

    def create_category(self, category):
        self.reader.categories[category.category_id] = category
        return category

    def update_category(self, category, *, expected_revision):
        if self.reader.categories[category.category_id].revision != expected_revision:
            raise ConflictError("Category revision is stale")
        updated = category.model_copy(update={"revision": expected_revision + 1})
        self.reader.categories[category.category_id] = updated
        return updated

    def save_program_editorial(self, editorial, *, expected_revision):
        current = self.reader.program_editorials.get((editorial.university_id, editorial.program_id))
        if current is not None and current.revision != expected_revision:
            raise ConflictError("Editorial revision is stale")
        updated = editorial.model_copy(update={"revision": current.revision + 1 if current else 1})
        self.reader.program_editorials[(editorial.university_id, editorial.program_id)] = updated
        return updated

    def save_discipline_editorial(self, editorial, *, expected_revision):
        current = self.reader.discipline_editorials.get((editorial.university_id, editorial.discipline_id))
        if current is not None and current.revision != expected_revision:
            raise ConflictError("Editorial revision is stale")
        updated = editorial.model_copy(update={"revision": current.revision + 1 if current else 1})
        self.reader.discipline_editorials[(editorial.university_id, editorial.discipline_id)] = updated
        return updated

    def replace_links(self, university_id, links):
        self.reader.links = links


class _Canonical:
    def list_programs(self, university_id):
        return (SimpleNamespace(id=PROGRAM_ID, name="Информатика"),)

    def list_disciplines(self, university_id):
        return (SimpleNamespace(id=DISCIPLINE_ID, name="Математика"),)

    def program_belongs(self, university_id, program_id):
        return university_id == UNIVERSITY_ID and program_id == PROGRAM_ID

    def discipline_belongs(self, university_id, discipline_id):
        return university_id == UNIVERSITY_ID and discipline_id == DISCIPLINE_ID


def _service() -> tuple[UniversityCatalogService, _Reader]:
    reader = _Reader()
    return UniversityCatalogService(reader, _Writer(reader), _Canonical()), reader


def test_catalog_service_enforces_faculty_department_hierarchy() -> None:
    service, _ = _service()

    faculty = service.create_unit(
        university_id=UNIVERSITY_ID,
        account_id=ACCOUNT_ID,
        unit_type=UnitType.FACULTY,
        slug="fakultet-ikt",
        name="Факультет ИУ",
        description=None,
        parent_unit_id=None,
        status=EditorialStatus.PUBLISHED,
        sort_order=1,
    )
    department = service.create_unit(
        university_id=UNIVERSITY_ID,
        account_id=ACCOUNT_ID,
        unit_type=UnitType.DEPARTMENT,
        slug="kafedra-iu1",
        name="Кафедра ИУ-1",
        description=None,
        parent_unit_id=faculty.unit_id,
        status=EditorialStatus.PUBLISHED,
        sort_order=1,
    )
    assert department.parent_unit_id == faculty.unit_id

    with pytest.raises(ValidationError):
        service.create_unit(
            university_id=UNIVERSITY_ID,
            account_id=ACCOUNT_ID,
            unit_type=UnitType.DEPARTMENT,
            slug="orphan",
            name="Без факультета",
            description=None,
            parent_unit_id=None,
            status=EditorialStatus.DRAFT,
            sort_order=1,
        )


def test_catalog_service_rejects_invalid_category_kind_and_stale_revision() -> None:
    service, _ = _service()
    category = service.create_category(
        university_id=UNIVERSITY_ID,
        account_id=ACCOUNT_ID,
        slug="programs",
        name="Программы",
        description=None,
        category_kind=CategoryKind.PROGRAM,
        status=EditorialStatus.PUBLISHED,
        sort_order=1,
    )
    with pytest.raises(ConflictError):
        service.update_category(
            university_id=UNIVERSITY_ID,
            category_id=category.category_id,
            account_id=ACCOUNT_ID,
            expected_revision=9,
            name=category.name,
            description=None,
            category_kind=CategoryKind.PROGRAM,
            status=EditorialStatus.PUBLISHED,
            sort_order=1,
        )

    with pytest.raises(ValidationError):
        service.replace_links(
            UNIVERSITY_ID,
            UniversityCatalogLinks(
                categoryPrograms=((category.category_id, PROGRAM_ID),),
                categoryDisciplines=((category.category_id, DISCIPLINE_ID),),
                unitPrograms=(),
                unitDisciplines=(),
            ),
        )


def test_catalog_service_accepts_curriculum_owned_discipline_and_filters_hidden_orphans() -> None:
    service, reader = _service()
    category = service.create_category(
        university_id=UNIVERSITY_ID,
        account_id=ACCOUNT_ID,
        slug="subjects",
        name="Предметы",
        description=None,
        category_kind=CategoryKind.SUBJECT,
        status=EditorialStatus.PUBLISHED,
        sort_order=1,
    )
    service.replace_links(
        UNIVERSITY_ID,
        UniversityCatalogLinks(
            categoryPrograms=(),
            categoryDisciplines=((category.category_id, DISCIPLINE_ID),),
            unitPrograms=(),
            unitDisciplines=(),
        ),
    )
    service.save_discipline_editorial(
        university_id=UNIVERSITY_ID,
        discipline_id=DISCIPLINE_ID,
        account_id=ACCOUNT_ID,
        display_name="Математика для ИТ",
        public_summary="Базовый курс",
        visibility=EditorialVisibility.HIDDEN,
        expected_revision=None,
    )

    catalog = service.public_catalog(UNIVERSITY_ID)

    assert catalog.disciplines == ()
    assert reader.links.category_disciplines == ((category.category_id, DISCIPLINE_ID),)
    with pytest.raises(NotFoundError):
        service.save_discipline_editorial(
            university_id=UNIVERSITY_ID,
            discipline_id="discipline:" + "c" * 16,
            account_id=ACCOUNT_ID,
            display_name=None,
            public_summary=None,
            visibility=EditorialVisibility.VISIBLE,
            expected_revision=None,
        )
