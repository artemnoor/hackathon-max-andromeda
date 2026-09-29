"""Thin HTTP adapter for the admissions read use case."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.services import get_admission_service
from andromeda.api.schemas.admissions import ProgramAdmissionsResponse, admissions_response
from andromeda.modules.admissions.services.admissions import AdmissionService
from andromeda.shared.contracts.ids import ProgramId


logger = logging.getLogger("andromeda.api.admissions")
router = APIRouter(prefix="/programs", tags=["admissions"])


@router.get("/{id}/admissions", response_model=ProgramAdmissionsResponse)
def get_program_admissions(
    id: ProgramId,
    service: AdmissionService = Depends(get_admission_service),
) -> ProgramAdmissionsResponse:
    logger.debug("admissions_http_request_accepted program_id=%s", id)
    result = service.get_for_program(id)
    response = admissions_response(result)
    logger.info("admissions_http_complete status=200 program_id=%s offerings=%d", id, len(response.offerings))
    return response


__all__ = ["router"]
