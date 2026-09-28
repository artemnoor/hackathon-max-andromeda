from __future__ import annotations

from datetime import datetime, timezone
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    CurriculumItemModel,
    CurriculumModel,
    DirectionModel,
    ProgramModel,
    UniversityCategoryDisciplineLinkModel,
    UniversityCategoryModel,
    UniversityCategoryProgramLinkModel,
    UniversityDisciplineEditorialModel,
    UniversityProgramEditorialModel,
    UniversityUnitDisciplineLinkModel,
    UniversityUnitModel,
    UniversityUnitProgramLinkModel,
)
from andromeda.infrastructure.repositories.disciplines import SqlAlchemyDisciplineRepository
from andromeda.infrastructure.repositories.programs import SqlAlchemyProgramRepository
from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.university_admin.contracts.catalog import (
    CategoryKind,
    EditorialStatus,
    EditorialVisibility,
    UniversityCatalogLinks,
    UniversityCategory,
    UniversityDisciplineEditorial,
    UniversityProgramEditorial,
    UniversityUnit,
    UnitType,
)
from andromeda.modules.university_admin.repository.catalog_ports import (
    UniversityCatalogCanonicalReader,
    UniversityCatalogReader,
    UniversityCatalogWriter,
)
from andromeda.shared.contracts.errors import ConflictError
from andromeda.shared.contracts.ids import AccountId, DisciplineId, ProgramId, UniversityCategoryId, UniversityId, UniversityUnitId


logger = logging.getLogger("andromeda.infrastructure.repositories.university_catalog")
_ContractT = TypeVar("_ContractT")


class SqlAlchemyUniversityCatalogCanonicalReader(UniversityCatalogCanonicalReader):
    def __init__(self, session: Session) -> None:
        self._session = session
        self._programs = SqlAlchemyProgramRepository(session)
        self._disciplines = SqlAlchemyDisciplineRepository(session)

    def list_programs(self, university_id: UniversityId) -> tuple[Program, ...]:
        return self._programs.list(university_id)

    def list_disciplines(self, university_id: UniversityId) -> tuple[Discipline, ...]:
        discipline_ids = tuple(
            self._session.scalars(
                select(CurriculumItemModel.discipline_id)
                .join(CurriculumModel, CurriculumModel.id == CurriculumItemModel.curriculum_id)
                .join(ProgramModel, ProgramModel.id == CurriculumModel.program_id)
                .join(DirectionModel, DirectionModel.id == ProgramModel.direction_id)
                .where(DirectionModel.university_id == university_id)
                .distinct()
                .order_by(CurriculumItemModel.discipline_id)
            ).all()
        )
        by_id = self._disciplines.get_many(discipline_ids)
        return tuple(sorted(by_id.values(), key=lambda item: (item.normalized_name, item.id)))

    def program_belongs(self, university_id: UniversityId, program_id: ProgramId) -> bool:
        return bool(
            self._session.scalar(
                select(
                    exists().where(
                        ProgramModel.id == program_id,
                        ProgramModel.direction_id == DirectionModel.id,
                        DirectionModel.university_id == university_id,
                    )
                )
            )
        )

    def discipline_belongs(self, university_id: UniversityId, discipline_id: DisciplineId) -> bool:
        return bool(
            self._session.scalar(
                select(
                    exists()
                    .where(CurriculumItemModel.discipline_id == discipline_id)
                    .where(CurriculumItemModel.curriculum_id == CurriculumModel.id)
                    .where(CurriculumModel.program_id == ProgramModel.id)
                    .where(ProgramModel.direction_id == DirectionModel.id)
                    .where(DirectionModel.university_id == university_id)
                )
            )
        )


class SqlAlchemyUniversityCatalogRepository(UniversityCatalogReader, UniversityCatalogWriter):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_unit(self, unit_id: UniversityUnitId) -> UniversityUnit | None:
        model = self._session.get(UniversityUnitModel, unit_id)
        return _to_unit(model) if model is not None else None

    def list_units(self, university_id: UniversityId, *, include_archived: bool = True) -> tuple[UniversityUnit, ...]:
        statement = select(UniversityUnitModel).where(UniversityUnitModel.university_id == university_id)
        if not include_archived:
            statement = statement.where(UniversityUnitModel.status != EditorialStatus.ARCHIVED.value)
        models = self._session.scalars(statement.order_by(UniversityUnitModel.sort_order, UniversityUnitModel.name)).all()
        return tuple(_to_unit(model) for model in models)

    def get_category(self, category_id: UniversityCategoryId) -> UniversityCategory | None:
        model = self._session.get(UniversityCategoryModel, category_id)
        return _to_category(model) if model is not None else None

    def list_categories(self, university_id: UniversityId, *, include_archived: bool = True) -> tuple[UniversityCategory, ...]:
        statement = select(UniversityCategoryModel).where(UniversityCategoryModel.university_id == university_id)
        if not include_archived:
            statement = statement.where(UniversityCategoryModel.status != EditorialStatus.ARCHIVED.value)
        models = self._session.scalars(statement.order_by(UniversityCategoryModel.sort_order, UniversityCategoryModel.name)).all()
        return tuple(_to_category(model) for model in models)

    def get_program_editorial(self, university_id: UniversityId, program_id: ProgramId) -> UniversityProgramEditorial | None:
        model = self._session.get(UniversityProgramEditorialModel, (university_id, program_id))
        return _to_program_editorial(model) if model is not None else None

    def list_program_editorials(self, university_id: UniversityId) -> tuple[UniversityProgramEditorial, ...]:
        models = self._session.scalars(
            select(UniversityProgramEditorialModel)
            .where(UniversityProgramEditorialModel.university_id == university_id)
            .order_by(UniversityProgramEditorialModel.program_id)
        ).all()
        return tuple(_to_program_editorial(model) for model in models)

    def get_discipline_editorial(self, university_id: UniversityId, discipline_id: DisciplineId) -> UniversityDisciplineEditorial | None:
        model = self._session.get(UniversityDisciplineEditorialModel, (university_id, discipline_id))
        return _to_discipline_editorial(model) if model is not None else None

    def list_discipline_editorials(self, university_id: UniversityId) -> tuple[UniversityDisciplineEditorial, ...]:
        models = self._session.scalars(
            select(UniversityDisciplineEditorialModel)
            .where(UniversityDisciplineEditorialModel.university_id == university_id)
            .order_by(UniversityDisciplineEditorialModel.discipline_id)
        ).all()
        return tuple(_to_discipline_editorial(model) for model in models)

    def read_links(self, university_id: UniversityId) -> UniversityCatalogLinks:
        category_programs = self._session.execute(
            select(UniversityCategoryProgramLinkModel.category_id, UniversityCategoryProgramLinkModel.program_id)
            .where(UniversityCategoryProgramLinkModel.university_id == university_id)
            .order_by(UniversityCategoryProgramLinkModel.category_id, UniversityCategoryProgramLinkModel.program_id)
        ).all()
        category_disciplines = self._session.execute(
            select(UniversityCategoryDisciplineLinkModel.category_id, UniversityCategoryDisciplineLinkModel.discipline_id)
            .where(UniversityCategoryDisciplineLinkModel.university_id == university_id)
            .order_by(UniversityCategoryDisciplineLinkModel.category_id, UniversityCategoryDisciplineLinkModel.discipline_id)
        ).all()
        unit_programs = self._session.execute(
            select(UniversityUnitProgramLinkModel.unit_id, UniversityUnitProgramLinkModel.program_id)
            .where(UniversityUnitProgramLinkModel.university_id == university_id)
            .order_by(UniversityUnitProgramLinkModel.unit_id, UniversityUnitProgramLinkModel.program_id)
        ).all()
        unit_disciplines = self._session.execute(
            select(UniversityUnitDisciplineLinkModel.unit_id, UniversityUnitDisciplineLinkModel.discipline_id)
            .where(UniversityUnitDisciplineLinkModel.university_id == university_id)
            .order_by(UniversityUnitDisciplineLinkModel.unit_id, UniversityUnitDisciplineLinkModel.discipline_id)
        ).all()
        return UniversityCatalogLinks(
            categoryPrograms=tuple((row[0], row[1]) for row in category_programs),
            categoryDisciplines=tuple((row[0], row[1]) for row in category_disciplines),
            unitPrograms=tuple((row[0], row[1]) for row in unit_programs),
            unitDisciplines=tuple((row[0], row[1]) for row in unit_disciplines),
        )

    def create_unit(self, unit: UniversityUnit) -> UniversityUnit:
        model = UniversityUnitModel(**_unit_values(unit))
        self._session.add(model)
        return self._commit_and_convert(model, _to_unit)

    def update_unit(self, unit: UniversityUnit, *, expected_revision: int) -> UniversityUnit:
        model = self._session.get(UniversityUnitModel, unit.unit_id)
        if model is None or model.revision != expected_revision:
            raise ConflictError("Unit revision is stale")
        for key, value in _unit_values(unit).items():
            if key not in {"unit_id", "created_at", "created_by_account_id"}:
                setattr(model, key, value)
        model.revision = expected_revision + 1
        return self._commit_and_convert(model, _to_unit)

    def create_category(self, category: UniversityCategory) -> UniversityCategory:
        model = UniversityCategoryModel(**_category_values(category))
        self._session.add(model)
        return self._commit_and_convert(model, _to_category)

    def update_category(self, category: UniversityCategory, *, expected_revision: int) -> UniversityCategory:
        model = self._session.get(UniversityCategoryModel, category.category_id)
        if model is None or model.revision != expected_revision:
            raise ConflictError("Category revision is stale")
        for key, value in _category_values(category).items():
            if key not in {"category_id", "created_at", "created_by_account_id"}:
                setattr(model, key, value)
        model.revision = expected_revision + 1
        return self._commit_and_convert(model, _to_category)

    def save_program_editorial(self, editorial: UniversityProgramEditorial, *, expected_revision: int | None) -> UniversityProgramEditorial:
        model = self._session.get(UniversityProgramEditorialModel, (editorial.university_id, editorial.program_id))
        if model is None:
            if expected_revision is not None:
                raise ConflictError("Editorial revision is stale")
            model = UniversityProgramEditorialModel(**_program_editorial_values(editorial))
            self._session.add(model)
        else:
            if expected_revision is None or model.revision != expected_revision:
                raise ConflictError("Editorial revision is stale")
            for key, value in _program_editorial_values(editorial).items():
                setattr(model, key, value)
            model.revision = expected_revision + 1
        return self._commit_and_convert(model, _to_program_editorial)

    def save_discipline_editorial(self, editorial: UniversityDisciplineEditorial, *, expected_revision: int | None) -> UniversityDisciplineEditorial:
        model = self._session.get(UniversityDisciplineEditorialModel, (editorial.university_id, editorial.discipline_id))
        if model is None:
            if expected_revision is not None:
                raise ConflictError("Editorial revision is stale")
            model = UniversityDisciplineEditorialModel(**_discipline_editorial_values(editorial))
            self._session.add(model)
        else:
            if expected_revision is None or model.revision != expected_revision:
                raise ConflictError("Editorial revision is stale")
            for key, value in _discipline_editorial_values(editorial).items():
                setattr(model, key, value)
            model.revision = expected_revision + 1
        return self._commit_and_convert(model, _to_discipline_editorial)

    def replace_links(self, university_id: UniversityId, links: UniversityCatalogLinks) -> None:
        for model in (
            UniversityCategoryProgramLinkModel,
            UniversityCategoryDisciplineLinkModel,
            UniversityUnitProgramLinkModel,
            UniversityUnitDisciplineLinkModel,
        ):
            self._session.execute(delete(model).where(model.university_id == university_id))
        self._session.add_all(
            [UniversityCategoryProgramLinkModel(university_id=university_id, category_id=category_id, program_id=program_id) for category_id, program_id in links.category_programs]
            + [UniversityCategoryDisciplineLinkModel(university_id=university_id, category_id=category_id, discipline_id=discipline_id) for category_id, discipline_id in links.category_disciplines]
            + [UniversityUnitProgramLinkModel(university_id=university_id, unit_id=unit_id, program_id=program_id) for unit_id, program_id in links.unit_programs]
            + [UniversityUnitDisciplineLinkModel(university_id=university_id, unit_id=unit_id, discipline_id=discipline_id) for unit_id, discipline_id in links.unit_disciplines]
        )
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError("Catalog links could not be saved") from exc

    def _commit_and_convert(self, model: Any, converter: Callable[[Any], _ContractT]) -> _ContractT:
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("catalog_mutation_rejected outcome=conflict")
            raise ConflictError("Catalog mutation conflicts with existing data") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.error("catalog_mutation_failed")
            raise RuntimeError("Catalog persistence failed") from exc
        return converter(model)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_unit(model: UniversityUnitModel) -> UniversityUnit:
    return UniversityUnit(
        unitId=model.unit_id,
        universityId=model.university_id,
        unitType=UnitType(model.unit_type),
        parentUnitId=model.parent_unit_id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        status=EditorialStatus(model.status),
        sortOrder=model.sort_order,
        revision=model.revision,
        createdByAccountId=model.created_by_account_id,
        updatedByAccountId=model.updated_by_account_id,
        createdAt=_utc(model.created_at),
        updatedAt=_utc(model.updated_at),
    )


def _to_category(model: UniversityCategoryModel) -> UniversityCategory:
    return UniversityCategory(
        categoryId=model.category_id,
        universityId=model.university_id,
        slug=model.slug,
        name=model.name,
        description=model.description,
        categoryKind=CategoryKind(model.category_kind),
        status=EditorialStatus(model.status),
        sortOrder=model.sort_order,
        revision=model.revision,
        createdByAccountId=model.created_by_account_id,
        updatedByAccountId=model.updated_by_account_id,
        createdAt=_utc(model.created_at),
        updatedAt=_utc(model.updated_at),
    )


def _to_program_editorial(model: UniversityProgramEditorialModel) -> UniversityProgramEditorial:
    return UniversityProgramEditorial(
        universityId=model.university_id,
        programId=model.program_id,
        displayName=model.display_name,
        publicSummary=model.public_summary,
        visibility=EditorialVisibility(model.visibility),
        revision=model.revision,
        updatedByAccountId=model.updated_by_account_id,
        updatedAt=_utc(model.updated_at),
    )


def _to_discipline_editorial(model: UniversityDisciplineEditorialModel) -> UniversityDisciplineEditorial:
    return UniversityDisciplineEditorial(
        universityId=model.university_id,
        disciplineId=model.discipline_id,
        displayName=model.display_name,
        publicSummary=model.public_summary,
        visibility=EditorialVisibility(model.visibility),
        revision=model.revision,
        updatedByAccountId=model.updated_by_account_id,
        updatedAt=_utc(model.updated_at),
    )


def _unit_values(unit: UniversityUnit) -> dict[str, object]:
    return {
        "unit_id": unit.unit_id,
        "university_id": unit.university_id,
        "unit_type": unit.unit_type.value,
        "parent_unit_id": unit.parent_unit_id,
        "slug": unit.slug,
        "name": unit.name,
        "description": unit.description,
        "status": unit.status.value,
        "sort_order": unit.sort_order,
        "revision": unit.revision,
        "created_by_account_id": unit.created_by_account_id,
        "updated_by_account_id": unit.updated_by_account_id,
        "created_at": _utc(unit.created_at),
        "updated_at": _utc(unit.updated_at),
    }


def _category_values(category: UniversityCategory) -> dict[str, object]:
    return {
        "category_id": category.category_id,
        "university_id": category.university_id,
        "slug": category.slug,
        "name": category.name,
        "description": category.description,
        "category_kind": category.category_kind.value,
        "status": category.status.value,
        "sort_order": category.sort_order,
        "revision": category.revision,
        "created_by_account_id": category.created_by_account_id,
        "updated_by_account_id": category.updated_by_account_id,
        "created_at": _utc(category.created_at),
        "updated_at": _utc(category.updated_at),
    }


def _program_editorial_values(editorial: UniversityProgramEditorial) -> dict[str, object]:
    return {
        "university_id": editorial.university_id,
        "program_id": editorial.program_id,
        "display_name": editorial.display_name,
        "public_summary": editorial.public_summary,
        "visibility": editorial.visibility.value,
        "revision": editorial.revision,
        "updated_by_account_id": editorial.updated_by_account_id,
        "updated_at": _utc(editorial.updated_at),
    }


def _discipline_editorial_values(editorial: UniversityDisciplineEditorial) -> dict[str, object]:
    return {
        "university_id": editorial.university_id,
        "discipline_id": editorial.discipline_id,
        "display_name": editorial.display_name,
        "public_summary": editorial.public_summary,
        "visibility": editorial.visibility.value,
        "revision": editorial.revision,
        "updated_by_account_id": editorial.updated_by_account_id,
        "updated_at": _utc(editorial.updated_at),
    }


__all__ = ["SqlAlchemyUniversityCatalogCanonicalReader", "SqlAlchemyUniversityCatalogRepository"]
