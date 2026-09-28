from __future__ import annotations

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.services import get_compare_service, get_compare_summary_service
from andromeda.api.schemas.common import ComparisonResponse
from andromeda.api.schemas.compare import (
    CompareQuery,
    CompareSummaryQuery,
    ComparisonSummaryResponse,
    comparison_response,
    comparison_summary_response,
    parse_compare_query,
    parse_compare_summary_query,
)
from andromeda.modules.comparison.services.compare_programs import CompareProgramsService
from andromeda.modules.comparison.services.compare_summary import ComparisonSummaryService

router = APIRouter(tags=["comparison"])


@router.get("/compare", response_model=ComparisonResponse)
def compare(
    query: CompareQuery = Depends(parse_compare_query),
    service: CompareProgramsService = Depends(get_compare_service),
) -> ComparisonResponse:
    result = service.compare(query.to_request())
    return comparison_response(result)


@router.get("/compare/summary", response_model=ComparisonSummaryResponse)
def compare_summary(
    query: CompareSummaryQuery = Depends(parse_compare_summary_query),
    service: ComparisonSummaryService = Depends(get_compare_summary_service),
) -> ComparisonSummaryResponse:
    result = service.summarize(query.to_request())
    return comparison_summary_response(result)
