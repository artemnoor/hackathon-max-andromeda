from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AccountId,
    DisciplineId,
    NonEmptyText,
    ProgramId,
    UniversityCategoryId,
    UniversityId,
    UniversityUnitId,
)


class UnitType(StrEnum):
    FACULTY = "faculty"
    DEPARTMENT = "department"


class EditorialStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EditorialVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"


class CategoryKind(StrEnum):
    SUBJECT = "subject"
    PROGRAM = "program"
    EVENT = "event"
    GENERAL = "general"


class UniversityUnit(ContractModel):
    unit_id: UniversityUnitId = Field(alias="unitId")
    university_id: UniversityId = Field(alias="universityId")
    unit_type: UnitType = Field(alias="unitType")
    parent_unit_id: UniversityUnitId | None = Field(default=None, alias="parentUnitId")
    slug: str = Field(min_length=1, max_length=64)
    name: NonEmptyText
    description: str | None = Field(default=None, max_length=4000)
    status: EditorialStatus
    sort_order: int = Field(default=0, ge=0, alias="sortOrder")
    revision: int = Field(ge=1)
    created_by_account_id: AccountId = Field(alias="createdByAccountId")
    updated_by_account_id: AccountId = Field(alias="updatedByAccountId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @model_validator(mode="after")
    def validate_parent_shape(self) -> UniversityUnit:
        if self.unit_type is UnitType.FACULTY and self.parent_unit_id is not None:
            raise ValueError("faculty cannot have a parent unit")
        return self


class UniversityCategory(ContractModel):
    category_id: UniversityCategoryId = Field(alias="categoryId")
    university_id: UniversityId = Field(alias="universityId")
    slug: str = Field(min_length=1, max_length=64)
    name: NonEmptyText
    description: str | None = Field(default=None, max_length=4000)
    category_kind: CategoryKind = Field(alias="categoryKind")
    status: EditorialStatus
    sort_order: int = Field(default=0, ge=0, alias="sortOrder")
    revision: int = Field(ge=1)
    created_by_account_id: AccountId = Field(alias="createdByAccountId")
    updated_by_account_id: AccountId = Field(alias="updatedByAccountId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UniversityProgramEditorial(ContractModel):
    university_id: UniversityId = Field(alias="universityId")
    program_id: ProgramId = Field(alias="programId")
    display_name: str | None = Field(default=None, max_length=512, alias="displayName")
    public_summary: str | None = Field(default=None, max_length=4000, alias="publicSummary")
    visibility: EditorialVisibility
    revision: int = Field(ge=1)
    updated_by_account_id: AccountId = Field(alias="updatedByAccountId")
    updated_at: datetime = Field(alias="updatedAt")


class UniversityDisciplineEditorial(ContractModel):
    university_id: UniversityId = Field(alias="universityId")
    discipline_id: DisciplineId = Field(alias="disciplineId")
    display_name: str | None = Field(default=None, max_length=256, alias="displayName")
    public_summary: str | None = Field(default=None, max_length=4000, alias="publicSummary")
    visibility: EditorialVisibility
    revision: int = Field(ge=1)
    updated_by_account_id: AccountId = Field(alias="updatedByAccountId")
    updated_at: datetime = Field(alias="updatedAt")


class UniversityCatalogLinks(ContractModel):
    category_programs: tuple[tuple[UniversityCategoryId, ProgramId], ...] = Field(alias="categoryPrograms")
    category_disciplines: tuple[tuple[UniversityCategoryId, DisciplineId], ...] = Field(alias="categoryDisciplines")
    unit_programs: tuple[tuple[UniversityUnitId, ProgramId], ...] = Field(alias="unitPrograms")
    unit_disciplines: tuple[tuple[UniversityUnitId, DisciplineId], ...] = Field(alias="unitDisciplines")


class UniversityCatalogProgram(ContractModel):
    program_id: ProgramId = Field(alias="programId")
    name: NonEmptyText
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    category_ids: tuple[UniversityCategoryId, ...] = Field(default=(), alias="categoryIds")
    unit_ids: tuple[UniversityUnitId, ...] = Field(default=(), alias="unitIds")


class UniversityCatalogDiscipline(ContractModel):
    discipline_id: DisciplineId = Field(alias="disciplineId")
    name: NonEmptyText
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    category_ids: tuple[UniversityCategoryId, ...] = Field(default=(), alias="categoryIds")
    unit_ids: tuple[UniversityUnitId, ...] = Field(default=(), alias="unitIds")


class UniversityPublicCatalog(ContractModel):
    units: tuple[UniversityUnit, ...] = ()
    categories: tuple[UniversityCategory, ...] = ()
    programs: tuple[UniversityCatalogProgram, ...] = ()
    disciplines: tuple[UniversityCatalogDiscipline, ...] = ()


__all__ = [
    "CategoryKind",
    "EditorialStatus",
    "EditorialVisibility",
    "UnitType",
    "UniversityCatalogLinks",
    "UniversityCatalogDiscipline",
    "UniversityCatalogProgram",
    "UniversityPublicCatalog",
    "UniversityCategory",
    "UniversityDisciplineEditorial",
    "UniversityProgramEditorial",
    "UniversityUnit",
]
