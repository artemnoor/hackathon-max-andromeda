"""HTTP adapter for source-backed admission benefits."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from andromeda.api.dependencies import (
    get_admission_benefit_catalog_service,
    get_admission_eligibility_service,
)
from andromeda.api.schemas.admission_benefits import (
    AdmissionBenefitRuleListResponse,
    AdmissionBenefitsResponse,
    AdmissionEligibilityRequest,
    AdmissionEligibilityResponse,
    admission_benefits_response,
    eligibility_request,
    eligibility_response,
    rule_list_response,
)
from andromeda.modules.admission_benefits.services.facade import (
    AdmissionBenefitCatalogService,
    AdmissionEligibilityService,
)
from andromeda.shared.contracts.enums import EducationLevel
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import OlympiadId, ProgramId, UniversityId

logger = logging.getLogger("andromeda.api.admission_benefits")
router = APIRouter(tags=["admission-benefits"])


@router.get(
    "/universities/{university_id}/admission-benefits",
    response_model=AdmissionBenefitsResponse,
    operation_id="get_university_admission_benefits",
)
def get_university_admission_benefits(
    university_id: UniversityId,
    admission_year: int = Query(alias="year", ge=2000, le=2100),
    education_level: EducationLevel | None = Query(default=None),
    service: AdmissionBenefitCatalogService = Depends(get_admission_benefit_catalog_service),
) -> AdmissionBenefitsResponse:
    catalog = service.university_catalog(university_id, admission_year, education_level)
    if catalog is None:
        raise NotFoundError("Admission-benefit source data was not found")
    response = admission_benefits_response(catalog)
    logger.info(
        "admission_benefits_catalog_http_complete university_id=%s year=%d rules=%d status=%s",
        university_id,
        admission_year,
        len(response.benefit_rules),
        response.coverage.status,
    )
    return response


@router.get(
    "/programs/{program_id}/admission-benefits",
    response_model=AdmissionBenefitRuleListResponse,
    operation_id="get_program_admission_benefits",
)
def get_program_admission_benefits(
    program_id: ProgramId,
    admission_year: int = Query(alias="year", ge=2000, le=2100),
    include_review: bool = Query(default=False, alias="includeReview"),
    service: AdmissionBenefitCatalogService = Depends(get_admission_benefit_catalog_service),
) -> AdmissionBenefitRuleListResponse:
    rules = service.program_rules(program_id, admission_year, include_review=include_review)
    return rule_list_response(admission_year, rules)


@router.get(
    "/admission-benefits/olympiads/{olympiad_id}/programs",
    response_model=AdmissionBenefitRuleListResponse,
    operation_id="get_olympiad_admission_benefit_programs",
)
def get_olympiad_admission_benefit_programs(
    olympiad_id: OlympiadId,
    university_id: UniversityId,
    admission_year: int = Query(alias="year", ge=2000, le=2100),
    benefit_type: str | None = Query(default=None, alias="benefitType", max_length=64),
    include_review: bool = Query(default=False, alias="includeReview"),
    service: AdmissionBenefitCatalogService = Depends(get_admission_benefit_catalog_service),
) -> AdmissionBenefitRuleListResponse:
    rules = service.olympiad_rules(
        olympiad_id,
        university_id,
        admission_year,
        benefit_type=benefit_type,
        include_review=include_review,
    )
    return rule_list_response(admission_year, rules)


@router.post(
    "/programs/{program_id}/admission-eligibility",
    response_model=AdmissionEligibilityResponse,
    operation_id="evaluate_program_admission_eligibility",
)
def evaluate_program_admission_eligibility(
    program_id: ProgramId,
    body: AdmissionEligibilityRequest,
    service: AdmissionEligibilityService = Depends(get_admission_eligibility_service),
) -> AdmissionEligibilityResponse:
    result = service.evaluate(
        eligibility_request(program_id, body),
        university_id=body.university_id,
        offering_id=body.offering_id,
        study_form=body.study_form,
        funding_type=body.funding_type,
        campus_id=body.campus_id,
    )
    response = eligibility_response(result)
    logger.info(
        "admission_eligibility_http_complete program_id=%s year=%d status=%s route=%s",
        program_id,
        body.admission_year,
        response.status,
        response.route,
    )
    return response


__all__ = ["router"]
