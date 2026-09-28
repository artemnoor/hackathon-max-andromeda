"""Thin HTTP adapter for the Admission Fit use case."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.services import get_admission_fit_service
from andromeda.api.schemas.admission_fit import AdmissionFitRequestBody, AdmissionFitResponse, admission_fit_request, admission_fit_response
from andromeda.modules.admission_fit.services.admission_fit import AdmissionFitService
from andromeda.shared.contracts.ids import ProgramId, canonical_program_id


logger = logging.getLogger("andromeda.api.admission_fit")
router = APIRouter(prefix="/programs", tags=["admission-fit"])


@router.post("/{id}/admission-fit", response_model=AdmissionFitResponse)
def calculate_program_admission_fit(
    id: ProgramId,
    request: AdmissionFitRequestBody,
    service: AdmissionFitService = Depends(get_admission_fit_service),
) -> AdmissionFitResponse:
    logger.debug(
        "admission_fit_http_request_accepted program_id=%s offering_id=%s subject_count=%d",
        id,
        request.offering_id,
        len(request.applicant.scores),
    )
    result = service.evaluate(id, admission_fit_request(request)).model_copy(update={"program_id": canonical_program_id(id)})
    response = admission_fit_response(result)
    logger.info(
        "admission_fit_http_complete status=200 program_id=%s offering_id=%s fit_status=%s score=%d",
        id,
        request.offering_id,
        response.status.value,
        response.score,
    )
    return response


__all__ = ["router"]
