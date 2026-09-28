from __future__ import annotations

from fastapi import APIRouter

from andromeda.api.schemas.common import DisciplineAreaCatalogResponse
from andromeda.modules.disciplines.contracts.public import area_catalog


router = APIRouter(prefix="/discipline-areas", tags=["disciplines"])


@router.get("", response_model=DisciplineAreaCatalogResponse)
def list_discipline_areas() -> DisciplineAreaCatalogResponse:
    return DisciplineAreaCatalogResponse(items=area_catalog())
