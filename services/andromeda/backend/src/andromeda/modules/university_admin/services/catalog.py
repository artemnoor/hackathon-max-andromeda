from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError
from andromeda.shared.contracts.ids import AccountId, DisciplineId, ProgramId, UniversityCategoryId, UniversityId, UniversityUnitId

from ..contracts.catalog import (
    CategoryKind,
    EditorialStatus,
    EditorialVisibility,
    UniversityCatalogDiscipline,
    UniversityCatalogLinks,
    UniversityCatalogProgram,
    UniversityCategory,
    UniversityDisciplineEditorial,
    UniversityProgramEditorial,
    UniversityPublicCatalog,
    UniversityUnit,
    UnitType,
)
from ..repository.catalog_ports import UniversityCatalogCanonicalReader, UniversityCatalogReader, UniversityCatalogWriter


logger = logging.getLogger("andromeda.modules.university_admin.catalog")


class UniversityCatalogService:
    def __init__(
        self,
        reader: UniversityCatalogReader,
        writer: UniversityCatalogWriter,
        canonical: UniversityCatalogCanonicalReader,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._canonical = canonical

    def create_unit(
        self,
        *,
        university_id: UniversityId,
        account_id: AccountId,
        unit_type: UnitType,
        slug: str,
        name: str,
        description: str | None,
        parent_unit_id: UniversityUnitId | None,
        status: EditorialStatus,
        sort_order: int,
    ) -> UniversityUnit:
        self._validate_parent(university_id, unit_type, parent_unit_id)
        unit = UniversityUnit(
            unitId=f"unit:{university_id.removeprefix('university:')}:{slug}",
            universityId=university_id,
            unitType=unit_type,
            parentUnitId=parent_unit_id,
            slug=slug,
            name=name,
            description=description,
            status=status,
            sortOrder=sort_order,
            revision=1,
            createdByAccountId=account_id,
            updatedByAccountId=account_id,
            createdAt=_now(),
            updatedAt=_now(),
        )
        result = self._writer.create_unit(unit)
        logger.info("catalog_unit_mutation university_id=%s target_id=%s operation=create revision=%d", university_id, unit.unit_id, result.revision)
        return result

    def update_unit(
        self,
        *,
        university_id: UniversityId,
        unit_id: UniversityUnitId,
        account_id: AccountId,
        expected_revision: int,
        name: str,
        description: str | None,
        status: EditorialStatus,
        sort_order: int,
        parent_unit_id: UniversityUnitId | None,
    ) -> UniversityUnit:
        current = self._require_unit(university_id, unit_id)
        self._validate_parent(university_id, current.unit_type, parent_unit_id, current_id=unit_id)
        updated = current.model_copy(
            update={
                "name": name,
                "description": description,
                "status": status,
                "sort_order": sort_order,
                "parent_unit_id": parent_unit_id,
                "updated_by_account_id": account_id,
                "updated_at": _now(),
            }
        )
        result = self._writer.update_unit(updated, expected_revision=expected_revision)
        logger.info("catalog_unit_mutation university_id=%s target_id=%s operation=update revision=%d", university_id, unit_id, result.revision)
        return result

    def archive_unit(self, *, university_id: UniversityId, unit_id: UniversityUnitId, account_id: AccountId, expected_revision: int) -> UniversityUnit:
        current = self._require_unit(university_id, unit_id)
        return self.update_unit(
            university_id=university_id,
            unit_id=unit_id,
            account_id=account_id,
            expected_revision=expected_revision,
            name=current.name,
            description=current.description,
            status=EditorialStatus.ARCHIVED,
            sort_order=current.sort_order,
            parent_unit_id=current.parent_unit_id,
        )

    def create_category(
        self,
        *,
        university_id: UniversityId,
        account_id: AccountId,
        slug: str,
        name: str,
        description: str | None,
        category_kind: CategoryKind,
        status: EditorialStatus,
        sort_order: int,
    ) -> UniversityCategory:
        category = UniversityCategory(
            categoryId=f"category:{university_id.removeprefix('university:')}:{slug}",
            universityId=university_id,
            slug=slug,
            name=name,
            description=description,
            categoryKind=category_kind,
            status=status,
            sortOrder=sort_order,
            revision=1,
            createdByAccountId=account_id,
            updatedByAccountId=account_id,
            createdAt=_now(),
            updatedAt=_now(),
        )
        result = self._writer.create_category(category)
        logger.info("catalog_category_mutation university_id=%s target_id=%s operation=create revision=%d", university_id, category.category_id, result.revision)
        return result

    def update_category(
        self,
        *,
        university_id: UniversityId,
        category_id: UniversityCategoryId,
        account_id: AccountId,
        expected_revision: int,
        name: str,
        description: str | None,
        category_kind: CategoryKind,
        status: EditorialStatus,
        sort_order: int,
    ) -> UniversityCategory:
        current = self._require_category(university_id, category_id)
        updated = current.model_copy(
            update={
                "name": name,
                "description": description,
                "category_kind": category_kind,
                "status": status,
                "sort_order": sort_order,
                "updated_by_account_id": account_id,
                "updated_at": _now(),
            }
        )
        result = self._writer.update_category(updated, expected_revision=expected_revision)
        logger.info("catalog_category_mutation university_id=%s target_id=%s operation=update revision=%d", university_id, category_id, result.revision)
        return result

    def archive_category(self, *, university_id: UniversityId, category_id: UniversityCategoryId, account_id: AccountId, expected_revision: int) -> UniversityCategory:
        current = self._require_category(university_id, category_id)
        return self.update_category(
            university_id=university_id,
            category_id=category_id,
            account_id=account_id,
            expected_revision=expected_revision,
            name=current.name,
            description=current.description,
            category_kind=current.category_kind,
            status=EditorialStatus.ARCHIVED,
            sort_order=current.sort_order,
        )

    def save_program_editorial(
        self,
        *,
        university_id: UniversityId,
        program_id: ProgramId,
        account_id: AccountId,
        display_name: str | None,
        public_summary: str | None,
        visibility: EditorialVisibility,
        expected_revision: int | None,
    ) -> UniversityProgramEditorial:
        if not self._canonical.program_belongs(university_id, program_id):
            raise NotFoundError("Resource was not found")
        current_program = self._reader.get_program_editorial(university_id, program_id)
        editorial = UniversityProgramEditorial(
            universityId=university_id,
            programId=program_id,
            displayName=display_name,
            publicSummary=public_summary,
            visibility=visibility,
            revision=current_program.revision if current_program is not None else 1,
            updatedByAccountId=account_id,
            updatedAt=_now(),
        )
        result = self._writer.save_program_editorial(editorial, expected_revision=expected_revision)
        logger.info("catalog_overlay_mutation university_id=%s target_id=%s operation=program revision=%d", university_id, program_id, result.revision)
        return result

    def save_discipline_editorial(
        self,
        *,
        university_id: UniversityId,
        discipline_id: DisciplineId,
        account_id: AccountId,
        display_name: str | None,
        public_summary: str | None,
        visibility: EditorialVisibility,
        expected_revision: int | None,
    ) -> UniversityDisciplineEditorial:
        if not self._canonical.discipline_belongs(university_id, discipline_id):
            raise NotFoundError("Resource was not found")
        current_discipline = self._reader.get_discipline_editorial(university_id, discipline_id)
        editorial = UniversityDisciplineEditorial(
            universityId=university_id,
            disciplineId=discipline_id,
            displayName=display_name,
            publicSummary=public_summary,
            visibility=visibility,
            revision=current_discipline.revision if current_discipline is not None else 1,
            updatedByAccountId=account_id,
            updatedAt=_now(),
        )
        result = self._writer.save_discipline_editorial(editorial, expected_revision=expected_revision)
        logger.info("catalog_overlay_mutation university_id=%s target_id=%s operation=discipline revision=%d", university_id, discipline_id, result.revision)
        return result

    def replace_links(self, university_id: UniversityId, links: UniversityCatalogLinks) -> None:
        self._validate_links(university_id, links)
        self._writer.replace_links(university_id, links)
        logger.info("catalog_links_replaced university_id=%s operation=replace", university_id)

    def public_catalog(self, university_id: UniversityId) -> UniversityPublicCatalog:
        units = tuple(item for item in self._reader.list_units(university_id, include_archived=False) if item.status is EditorialStatus.PUBLISHED)
        categories = tuple(item for item in self._reader.list_categories(university_id, include_archived=False) if item.status is EditorialStatus.PUBLISHED)
        links = self._reader.read_links(university_id)
        published_category_ids = {item.category_id for item in categories}
        published_unit_ids = {item.unit_id for item in units}
        program_links: dict[ProgramId, tuple[tuple[UniversityCategoryId, ...], tuple[UniversityUnitId, ...]]] = {}
        for program_id in {item[1] for item in links.category_programs} | {item[1] for item in links.unit_programs}:
            program_links[program_id] = (
                tuple(sorted(category_id for category_id, target_id in links.category_programs if target_id == program_id and category_id in published_category_ids)),
                tuple(sorted(unit_id for unit_id, target_id in links.unit_programs if target_id == program_id and unit_id in published_unit_ids)),
            )
        discipline_links: dict[DisciplineId, tuple[tuple[UniversityCategoryId, ...], tuple[UniversityUnitId, ...]]] = {}
        for discipline_id in {item[1] for item in links.category_disciplines} | {item[1] for item in links.unit_disciplines}:
            discipline_links[discipline_id] = (
                tuple(sorted(category_id for category_id, target_id in links.category_disciplines if target_id == discipline_id and category_id in published_category_ids)),
                tuple(sorted(unit_id for unit_id, target_id in links.unit_disciplines if target_id == discipline_id and unit_id in published_unit_ids)),
            )
        program_overlays = {item.program_id: item for item in self._reader.list_program_editorials(university_id)}
        discipline_overlays = {item.discipline_id: item for item in self._reader.list_discipline_editorials(university_id)}
        programs = []
        for program in self._canonical.list_programs(university_id):
            overlay_program = program_overlays.get(program.id)
            if overlay_program is not None and overlay_program.visibility is EditorialVisibility.HIDDEN:
                continue
            category_ids, unit_ids = program_links.get(program.id, ((), ()))
            programs.append(
                UniversityCatalogProgram(
                    programId=program.id,
                    name=program.name,
                    displayName=overlay_program.display_name if overlay_program else None,
                    publicSummary=overlay_program.public_summary if overlay_program else None,
                    categoryIds=category_ids,
                    unitIds=unit_ids,
                )
            )
        disciplines = []
        for discipline in self._canonical.list_disciplines(university_id):
            overlay_discipline = discipline_overlays.get(discipline.id)
            if overlay_discipline is not None and overlay_discipline.visibility is EditorialVisibility.HIDDEN:
                continue
            category_ids, unit_ids = discipline_links.get(discipline.id, ((), ()))
            disciplines.append(
                UniversityCatalogDiscipline(
                    disciplineId=discipline.id,
                    name=discipline.name,
                    displayName=overlay_discipline.display_name if overlay_discipline else None,
                    publicSummary=overlay_discipline.public_summary if overlay_discipline else None,
                    categoryIds=category_ids,
                    unitIds=unit_ids,
                )
            )
        return UniversityPublicCatalog(units=units, categories=categories, programs=tuple(programs), disciplines=tuple(disciplines))

    def _require_unit(self, university_id: UniversityId, unit_id: UniversityUnitId) -> UniversityUnit:
        unit = self._reader.get_unit(unit_id)
        if unit is None or unit.university_id != university_id:
            raise NotFoundError("Resource was not found")
        return unit

    def _require_category(self, university_id: UniversityId, category_id: UniversityCategoryId) -> UniversityCategory:
        category = self._reader.get_category(category_id)
        if category is None or category.university_id != university_id:
            raise NotFoundError("Resource was not found")
        return category

    def _validate_parent(
        self,
        university_id: UniversityId,
        unit_type: UnitType,
        parent_unit_id: UniversityUnitId | None,
        *,
        current_id: UniversityUnitId | None = None,
    ) -> None:
        if parent_unit_id is None:
            if unit_type is UnitType.DEPARTMENT:
                raise ValidationError("Department must have a faculty parent")
            return
        if current_id == parent_unit_id:
            raise ValidationError("A unit cannot be its own parent")
        parent = self._reader.get_unit(parent_unit_id)
        if parent is None or parent.university_id != university_id or parent.unit_type is not UnitType.FACULTY:
            raise ValidationError("Department parent must be a faculty in the same university")
        if unit_type is UnitType.FACULTY:
            raise ValidationError("Faculty cannot have a parent unit")

    def _validate_links(self, university_id: UniversityId, links: UniversityCatalogLinks) -> None:
        if any(len(set(group)) != len(group) for group in (links.category_programs, links.category_disciplines, links.unit_programs, links.unit_disciplines)):
            raise ValidationError("Catalog links must be unique")
        units = {item.unit_id: item for item in self._reader.list_units(university_id)}
        categories = {item.category_id: item for item in self._reader.list_categories(university_id)}
        if any(unit_id not in units for unit_id, _ in links.unit_programs + links.unit_disciplines):
            raise ValidationError("Unit link is outside university scope")
        if any(category_id not in categories for category_id, _ in links.category_programs + links.category_disciplines):
            raise ValidationError("Category link is outside university scope")
        if any(not self._canonical.program_belongs(university_id, program_id) for _, program_id in links.category_programs + links.unit_programs):
            raise NotFoundError("Resource was not found")
        if any(not self._canonical.discipline_belongs(university_id, discipline_id) for _, discipline_id in links.category_disciplines + links.unit_disciplines):
            raise NotFoundError("Resource was not found")
        if any(categories[category_id].category_kind not in {CategoryKind.PROGRAM, CategoryKind.GENERAL} for category_id, _ in links.category_programs):
            raise ValidationError("Category kind does not accept program links")
        if any(categories[category_id].category_kind not in {CategoryKind.SUBJECT, CategoryKind.GENERAL} for category_id, _ in links.category_disciplines):
            raise ValidationError("Category kind does not accept discipline links")


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["UniversityCatalogService"]
