from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from andromeda.api.dependencies import get_university_catalog_reader, get_university_catalog_service, get_university_reader
from andromeda.api.dependencies.university_admin import require_university_admin, require_university_editor
from andromeda.api.schemas.university_catalog import (
    EditorialOverlayRequest,
    UniversityCatalogResponse,
    UniversityCatalogLinksRequest,
    UniversityCatalogLinksResponse,
    UniversityCategoryListResponse,
    UniversityCategoryRequest,
    UniversityCategoryResponse,
    UniversityCategoryUpdateRequest,
    UniversityDiscoveryListResponse,
    UniversityDiscoveryResponse,
    UniversityDisciplineEditorialResponse,
    UniversityProgramEditorialResponse,
    UniversityUnitListResponse,
    UniversityUnitRequest,
    UniversityUnitResponse,
    UniversityUnitUpdateRequest,
    category_response,
    discipline_editorial_response,
    discipline_response,
    program_editorial_response,
    program_response,
    unit_response,
)
from andromeda.modules.university_admin.contracts.catalog import EditorialStatus, UniversityCatalogLinks
from andromeda.modules.university_admin.contracts.public import UniversityAdminActor
from andromeda.modules.university_admin.repository.catalog_ports import UniversityCatalogReader
from andromeda.modules.university_admin.services.catalog import UniversityCatalogService
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import DisciplineId, ProgramId, UniversityCategoryId, UniversityId, UniversityUnitId


router = APIRouter(tags=["university-catalog"])


@router.get("/universities", response_model=UniversityDiscoveryListResponse, operation_id="list_universities")
def list_universities(universities: UniversityReader = Depends(get_university_reader)) -> UniversityDiscoveryListResponse:
    return UniversityDiscoveryListResponse(
        items=tuple(UniversityDiscoveryResponse(id=item.id, name=item.name, city=item.city) for item in universities.list())
    )


@router.get(
    "/universities/{university_id}/catalog",
    response_model=UniversityCatalogResponse,
    operation_id="get_university_public_catalog",
)
def get_public_catalog(
    university_id: UniversityId,
    universities: UniversityReader = Depends(get_university_reader),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityCatalogResponse:
    university = universities.get(university_id)
    if university is None:
        raise NotFoundError("Resource was not found")
    catalog = service.public_catalog(university_id)
    return UniversityCatalogResponse(
        universityId=university.id,
        universityName=university.name,
        city=university.city,
        officialSite=university.official_site,
        address=university.address,
        sourceState="complete",
        units=tuple(unit_response(item) for item in catalog.units),
        categories=tuple(category_response(item) for item in catalog.categories),
        programs=tuple(program_response(item) for item in catalog.programs),
        disciplines=tuple(discipline_response(item) for item in catalog.disciplines),
    )


@router.get("/university-admin/universities/{university_id}/units", response_model=UniversityUnitListResponse, operation_id="list_university_units")
def list_units(
    university_id: UniversityId,
    _actor: UniversityAdminActor = Depends(require_university_admin),
    reader: UniversityCatalogReader = Depends(get_university_catalog_reader),
) -> UniversityUnitListResponse:
    items = reader.list_units(university_id)
    return UniversityUnitListResponse(items=tuple(unit_response(item) for item in items), total=len(items))


@router.post("/university-admin/universities/{university_id}/units", response_model=UniversityUnitResponse, status_code=status.HTTP_201_CREATED, operation_id="create_university_unit")
def create_unit(
    university_id: UniversityId,
    body: UniversityUnitRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityUnitResponse:
    unit = service.create_unit(
        university_id=university_id,
        account_id=actor.account_id,
        unit_type=body.unit_type,
        slug=body.slug,
        name=body.name,
        description=body.description,
        parent_unit_id=body.parent_unit_id,
        status=body.status,
        sort_order=body.sort_order,
    )
    return unit_response(unit)


@router.patch("/university-admin/universities/{university_id}/units/{unit_id}", response_model=UniversityUnitResponse, operation_id="update_university_unit")
def update_unit(
    university_id: UniversityId,
    unit_id: UniversityUnitId,
    body: UniversityUnitUpdateRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityUnitResponse:
    unit = service.update_unit(
        university_id=university_id,
        unit_id=unit_id,
        account_id=actor.account_id,
        expected_revision=body.expected_revision,
        name=body.name,
        description=body.description,
        status=body.status,
        sort_order=body.sort_order,
        parent_unit_id=body.parent_unit_id,
    )
    return unit_response(unit)


@router.delete("/university-admin/universities/{university_id}/units/{unit_id}", response_model=UniversityUnitResponse, operation_id="archive_university_unit")
def archive_unit(
    university_id: UniversityId,
    unit_id: UniversityUnitId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityUnitResponse:
    return unit_response(service.archive_unit(university_id=university_id, unit_id=unit_id, account_id=actor.account_id, expected_revision=expected_revision))


@router.get("/university-admin/universities/{university_id}/categories", response_model=UniversityCategoryListResponse, operation_id="list_university_categories")
def list_categories(
    university_id: UniversityId,
    _actor: UniversityAdminActor = Depends(require_university_admin),
    reader: UniversityCatalogReader = Depends(get_university_catalog_reader),
) -> UniversityCategoryListResponse:
    items = reader.list_categories(university_id)
    return UniversityCategoryListResponse(items=tuple(category_response(item) for item in items), total=len(items))


@router.post("/university-admin/universities/{university_id}/categories", response_model=UniversityCategoryResponse, status_code=status.HTTP_201_CREATED, operation_id="create_university_category")
def create_category(
    university_id: UniversityId,
    body: UniversityCategoryRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityCategoryResponse:
    category = service.create_category(
        university_id=university_id,
        account_id=actor.account_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        category_kind=body.category_kind,
        status=body.status,
        sort_order=body.sort_order,
    )
    return category_response(category)


@router.patch("/university-admin/universities/{university_id}/categories/{category_id}", response_model=UniversityCategoryResponse, operation_id="update_university_category")
def update_category(
    university_id: UniversityId,
    category_id: UniversityCategoryId,
    body: UniversityCategoryUpdateRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityCategoryResponse:
    category = service.update_category(
        university_id=university_id,
        category_id=category_id,
        account_id=actor.account_id,
        expected_revision=body.expected_revision,
        name=body.name,
        description=body.description,
        category_kind=body.category_kind,
        status=body.status,
        sort_order=body.sort_order,
    )
    return category_response(category)


@router.delete("/university-admin/universities/{university_id}/categories/{category_id}", response_model=UniversityCategoryResponse, operation_id="archive_university_category")
def archive_category(
    university_id: UniversityId,
    category_id: UniversityCategoryId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityCategoryResponse:
    return category_response(service.archive_category(university_id=university_id, category_id=category_id, account_id=actor.account_id, expected_revision=expected_revision))


@router.put(
    "/university-admin/universities/{university_id}/catalog-links",
    response_model=UniversityCatalogLinksResponse,
    operation_id="replace_university_catalog_links",
)
def replace_catalog_links(
    university_id: UniversityId,
    body: UniversityCatalogLinksRequest,
    _actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityCatalogLinksResponse:
    links = UniversityCatalogLinks(
        categoryPrograms=body.category_programs,
        categoryDisciplines=body.category_disciplines,
        unitPrograms=body.unit_programs,
        unitDisciplines=body.unit_disciplines,
    )
    service.replace_links(university_id, links)
    return UniversityCatalogLinksResponse.model_validate(links.model_dump(mode="python"))


@router.get("/university-admin/universities/{university_id}/programs/{program_id}", response_model=UniversityProgramEditorialResponse, operation_id="get_university_program_editorial")
def get_program_editorial(
    university_id: UniversityId,
    program_id: ProgramId,
    _actor: UniversityAdminActor = Depends(require_university_admin),
    reader: UniversityCatalogReader = Depends(get_university_catalog_reader),
) -> UniversityProgramEditorialResponse:
    editorial = reader.get_program_editorial(university_id, program_id)
    if editorial is None:
        raise NotFoundError("Resource was not found")
    return program_editorial_response(editorial)


@router.patch("/university-admin/universities/{university_id}/programs/{program_id}", response_model=UniversityProgramEditorialResponse, operation_id="update_university_program_editorial")
def update_program_editorial(
    university_id: UniversityId,
    program_id: ProgramId,
    body: EditorialOverlayRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityProgramEditorialResponse:
    return program_editorial_response(service.save_program_editorial(university_id=university_id, program_id=program_id, account_id=actor.account_id, display_name=body.display_name, public_summary=body.public_summary, visibility=body.visibility, expected_revision=body.expected_revision))


@router.get("/university-admin/universities/{university_id}/disciplines/{discipline_id}", response_model=UniversityDisciplineEditorialResponse, operation_id="get_university_discipline_editorial")
def get_discipline_editorial(
    university_id: UniversityId,
    discipline_id: DisciplineId,
    _actor: UniversityAdminActor = Depends(require_university_admin),
    reader: UniversityCatalogReader = Depends(get_university_catalog_reader),
) -> UniversityDisciplineEditorialResponse:
    editorial = reader.get_discipline_editorial(university_id, discipline_id)
    if editorial is None:
        raise NotFoundError("Resource was not found")
    return discipline_editorial_response(editorial)


@router.patch("/university-admin/universities/{university_id}/disciplines/{discipline_id}", response_model=UniversityDisciplineEditorialResponse, operation_id="update_university_discipline_editorial")
def update_discipline_editorial(
    university_id: UniversityId,
    discipline_id: DisciplineId,
    body: EditorialOverlayRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityCatalogService = Depends(get_university_catalog_service),
) -> UniversityDisciplineEditorialResponse:
    return discipline_editorial_response(service.save_discipline_editorial(university_id=university_id, discipline_id=discipline_id, account_id=actor.account_id, display_name=body.display_name, public_summary=body.public_summary, visibility=body.visibility, expected_revision=body.expected_revision))


__all__ = ["router"]
