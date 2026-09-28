from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.programs.contracts.public import Program
from andromeda.shared.contracts.ids import AccountId, DisciplineId, ProgramId, UniversityCategoryId, UniversityId, UniversityUnitId

from ..contracts.catalog import (
    CategoryKind,
    EditorialStatus,
    EditorialVisibility,
    UniversityCatalogLinks,
    UniversityCategory,
    UniversityDisciplineEditorial,
    UniversityProgramEditorial,
    UniversityUnit,
)


class UniversityCatalogCanonicalReader(Protocol):
    def list_programs(self, university_id: UniversityId) -> tuple[Program, ...]: ...

    def list_disciplines(self, university_id: UniversityId) -> tuple[Discipline, ...]: ...

    def program_belongs(self, university_id: UniversityId, program_id: ProgramId) -> bool: ...

    def discipline_belongs(self, university_id: UniversityId, discipline_id: DisciplineId) -> bool: ...


class UniversityCatalogReader(Protocol):
    def get_unit(self, unit_id: UniversityUnitId) -> UniversityUnit | None: ...

    def list_units(self, university_id: UniversityId, *, include_archived: bool = True) -> tuple[UniversityUnit, ...]: ...

    def get_category(self, category_id: UniversityCategoryId) -> UniversityCategory | None: ...

    def list_categories(self, university_id: UniversityId, *, include_archived: bool = True) -> tuple[UniversityCategory, ...]: ...

    def get_program_editorial(self, university_id: UniversityId, program_id: ProgramId) -> UniversityProgramEditorial | None: ...

    def list_program_editorials(self, university_id: UniversityId) -> tuple[UniversityProgramEditorial, ...]: ...

    def get_discipline_editorial(self, university_id: UniversityId, discipline_id: DisciplineId) -> UniversityDisciplineEditorial | None: ...

    def list_discipline_editorials(self, university_id: UniversityId) -> tuple[UniversityDisciplineEditorial, ...]: ...

    def read_links(self, university_id: UniversityId) -> UniversityCatalogLinks: ...


class UniversityCatalogWriter(Protocol):
    def create_unit(self, unit: UniversityUnit) -> UniversityUnit: ...

    def update_unit(self, unit: UniversityUnit, *, expected_revision: int) -> UniversityUnit: ...

    def create_category(self, category: UniversityCategory) -> UniversityCategory: ...

    def update_category(self, category: UniversityCategory, *, expected_revision: int) -> UniversityCategory: ...

    def save_program_editorial(self, editorial: UniversityProgramEditorial, *, expected_revision: int | None) -> UniversityProgramEditorial: ...

    def save_discipline_editorial(self, editorial: UniversityDisciplineEditorial, *, expected_revision: int | None) -> UniversityDisciplineEditorial: ...

    def replace_links(self, university_id: UniversityId, links: UniversityCatalogLinks) -> None: ...


__all__ = ["UniversityCatalogCanonicalReader", "UniversityCatalogReader", "UniversityCatalogWriter"]
