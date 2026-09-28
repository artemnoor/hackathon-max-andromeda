from __future__ import annotations

from enum import Enum
from typing import Annotated, TypeVar

from pydantic import BeforeValidator, Field, HttpUrl

from andromeda.api.schemas.common import ApiModel
from andromeda.modules.university_admin.contracts.catalog import CategoryKind, EditorialStatus, EditorialVisibility, UnitType
from andromeda.modules.university_admin.contracts.public import UniversityCatalogDiscipline, UniversityCatalogLinks, UniversityCatalogProgram, UniversityCategory, UniversityDisciplineEditorial, UniversityProgramEditorial, UniversityUnit
from andromeda.shared.contracts.ids import DisciplineId, ProgramId, UniversityCategoryId, UniversityId, UniversityUnitId


EnumT = TypeVar("EnumT", bound=Enum)


def _enum_from_json(enum_type: type[EnumT], value: object) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        return enum_type(value)
    raise TypeError(f"{enum_type.__name__} must be a string")


def _unit_type(value: object) -> UnitType:
    return _enum_from_json(UnitType, value)


def _editorial_status(value: object) -> EditorialStatus:
    return _enum_from_json(EditorialStatus, value)


def _category_kind(value: object) -> CategoryKind:
    return _enum_from_json(CategoryKind, value)


def _visibility(value: object) -> EditorialVisibility:
    return _enum_from_json(EditorialVisibility, value)


JsonUnitType = Annotated[UnitType, BeforeValidator(_unit_type)]
JsonEditorialStatus = Annotated[EditorialStatus, BeforeValidator(_editorial_status)]
JsonCategoryKind = Annotated[CategoryKind, BeforeValidator(_category_kind)]
JsonVisibility = Annotated[EditorialVisibility, BeforeValidator(_visibility)]


class UniversityUnitRequest(ApiModel):
    unit_type: JsonUnitType = Field(alias="unitType")
    parent_unit_id: UniversityUnitId | None = Field(default=None, alias="parentUnitId")
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    status: JsonEditorialStatus = EditorialStatus.DRAFT
    sort_order: int = Field(default=0, strict=True, ge=0, alias="sortOrder")


class UniversityUnitUpdateRequest(UniversityUnitRequest):
    expected_revision: int = Field(strict=True, ge=1, alias="expectedRevision")


class UniversityCategoryRequest(ApiModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    category_kind: JsonCategoryKind = Field(alias="categoryKind")
    status: JsonEditorialStatus = EditorialStatus.DRAFT
    sort_order: int = Field(default=0, strict=True, ge=0, alias="sortOrder")


class UniversityCategoryUpdateRequest(UniversityCategoryRequest):
    expected_revision: int = Field(strict=True, ge=1, alias="expectedRevision")


class EditorialOverlayRequest(ApiModel):
    display_name: str | None = Field(default=None, max_length=512, alias="displayName")
    public_summary: str | None = Field(default=None, max_length=4000, alias="publicSummary")
    visibility: JsonVisibility = EditorialVisibility.VISIBLE
    expected_revision: int | None = Field(default=None, strict=True, ge=1, alias="expectedRevision")


def _pairs_from_json(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(tuple(pair) for pair in value)
    return value


JsonCategoryProgramLinks = Annotated[tuple[tuple[UniversityCategoryId, ProgramId], ...], BeforeValidator(_pairs_from_json)]
JsonCategoryDisciplineLinks = Annotated[tuple[tuple[UniversityCategoryId, DisciplineId], ...], BeforeValidator(_pairs_from_json)]
JsonUnitProgramLinks = Annotated[tuple[tuple[UniversityUnitId, ProgramId], ...], BeforeValidator(_pairs_from_json)]
JsonUnitDisciplineLinks = Annotated[tuple[tuple[UniversityUnitId, DisciplineId], ...], BeforeValidator(_pairs_from_json)]


class UniversityCatalogLinksRequest(ApiModel):
    category_programs: JsonCategoryProgramLinks = Field(alias="categoryPrograms")
    category_disciplines: JsonCategoryDisciplineLinks = Field(alias="categoryDisciplines")
    unit_programs: JsonUnitProgramLinks = Field(alias="unitPrograms")
    unit_disciplines: JsonUnitDisciplineLinks = Field(alias="unitDisciplines")


class UniversityCatalogLinksResponse(UniversityCatalogLinksRequest):
    pass


class UniversityProgramEditorialResponse(ApiModel):
    program_id: ProgramId = Field(alias="programId")
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    visibility: EditorialVisibility
    revision: int


class UniversityDisciplineEditorialResponse(ApiModel):
    discipline_id: DisciplineId = Field(alias="disciplineId")
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    visibility: EditorialVisibility
    revision: int


class UniversityUnitResponse(ApiModel):
    unit_id: UniversityUnitId = Field(alias="unitId")
    university_id: UniversityId = Field(alias="universityId")
    unit_type: UnitType = Field(alias="unitType")
    parent_unit_id: UniversityUnitId | None = Field(default=None, alias="parentUnitId")
    slug: str
    name: str
    description: str | None = None
    status: EditorialStatus
    sort_order: int = Field(alias="sortOrder")
    revision: int


class UniversityCategoryResponse(ApiModel):
    category_id: UniversityCategoryId = Field(alias="categoryId")
    university_id: UniversityId = Field(alias="universityId")
    slug: str
    name: str
    description: str | None = None
    category_kind: CategoryKind = Field(alias="categoryKind")
    status: EditorialStatus
    sort_order: int = Field(alias="sortOrder")
    revision: int


class UniversityUnitListResponse(ApiModel):
    items: tuple[UniversityUnitResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class UniversityCategoryListResponse(ApiModel):
    items: tuple[UniversityCategoryResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class UniversityCatalogProgramResponse(ApiModel):
    program_id: ProgramId = Field(alias="programId")
    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    category_ids: tuple[UniversityCategoryId, ...] = Field(default=(), alias="categoryIds")
    unit_ids: tuple[UniversityUnitId, ...] = Field(default=(), alias="unitIds")


class UniversityCatalogDisciplineResponse(ApiModel):
    discipline_id: DisciplineId = Field(alias="disciplineId")
    name: str
    display_name: str | None = Field(default=None, alias="displayName")
    public_summary: str | None = Field(default=None, alias="publicSummary")
    category_ids: tuple[UniversityCategoryId, ...] = Field(default=(), alias="categoryIds")
    unit_ids: tuple[UniversityUnitId, ...] = Field(default=(), alias="unitIds")


class UniversityCatalogResponse(ApiModel):
    university_id: UniversityId = Field(alias="universityId")
    university_name: str = Field(alias="universityName")
    city: str
    official_site: HttpUrl = Field(alias="officialSite")
    address: str
    source_state: str = Field(alias="sourceState")
    units: tuple[UniversityUnitResponse, ...] = ()
    categories: tuple[UniversityCategoryResponse, ...] = ()
    programs: tuple[UniversityCatalogProgramResponse, ...] = ()
    disciplines: tuple[UniversityCatalogDisciplineResponse, ...] = ()


class UniversityDiscoveryResponse(ApiModel):
    id: UniversityId
    name: str
    city: str


class UniversityDiscoveryListResponse(ApiModel):
    items: tuple[UniversityDiscoveryResponse, ...] = ()


def unit_response(unit: UniversityUnit) -> UniversityUnitResponse:
    return UniversityUnitResponse(
        unitId=unit.unit_id,
        universityId=unit.university_id,
        unitType=unit.unit_type,
        parentUnitId=unit.parent_unit_id,
        slug=unit.slug,
        name=unit.name,
        description=unit.description,
        status=unit.status,
        sortOrder=unit.sort_order,
        revision=unit.revision,
    )


def category_response(category: UniversityCategory) -> UniversityCategoryResponse:
    return UniversityCategoryResponse(
        categoryId=category.category_id,
        universityId=category.university_id,
        slug=category.slug,
        name=category.name,
        description=category.description,
        categoryKind=category.category_kind,
        status=category.status,
        sortOrder=category.sort_order,
        revision=category.revision,
    )


def program_response(program: UniversityCatalogProgram) -> UniversityCatalogProgramResponse:
    return UniversityCatalogProgramResponse.model_validate(program.model_dump(mode="python"))


def discipline_response(discipline: UniversityCatalogDiscipline) -> UniversityCatalogDisciplineResponse:
    return UniversityCatalogDisciplineResponse.model_validate(discipline.model_dump(mode="python"))


def program_editorial_response(editorial: UniversityProgramEditorial) -> UniversityProgramEditorialResponse:
    return UniversityProgramEditorialResponse(
        programId=editorial.program_id,
        displayName=editorial.display_name,
        publicSummary=editorial.public_summary,
        visibility=editorial.visibility,
        revision=editorial.revision,
    )


def discipline_editorial_response(editorial: UniversityDisciplineEditorial) -> UniversityDisciplineEditorialResponse:
    return UniversityDisciplineEditorialResponse(
        disciplineId=editorial.discipline_id,
        displayName=editorial.display_name,
        publicSummary=editorial.public_summary,
        visibility=editorial.visibility,
        revision=editorial.revision,
    )


__all__ = [
    "EditorialOverlayRequest",
    "UniversityCatalogDisciplineResponse",
    "UniversityCatalogProgramResponse",
    "UniversityCatalogResponse",
    "UniversityCatalogLinksRequest",
    "UniversityCatalogLinksResponse",
    "UniversityDisciplineEditorialResponse",
    "UniversityCategoryListResponse",
    "UniversityCategoryRequest",
    "UniversityCategoryResponse",
    "UniversityCategoryUpdateRequest",
    "UniversityDiscoveryListResponse",
    "UniversityDiscoveryResponse",
    "UniversityUnitListResponse",
    "UniversityUnitRequest",
    "UniversityUnitResponse",
    "UniversityUnitUpdateRequest",
    "UniversityProgramEditorialResponse",
    "category_response",
    "discipline_response",
    "program_response",
    "program_editorial_response",
    "discipline_editorial_response",
    "unit_response",
]
