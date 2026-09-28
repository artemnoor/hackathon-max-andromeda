"""Channel-neutral typed analytics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.services import get_analytics_executor
from andromeda.api.schemas.analytics import AnalyticsQueryRequest
from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.modules.analytics.services.executor import AnalyticsExecutor

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/query", response_model=AnalyticsResult)
def execute_analytics_query(
    request: AnalyticsQueryRequest,
    executor: AnalyticsExecutor = Depends(get_analytics_executor),
) -> AnalyticsResult:
    return executor.execute(request.to_contract())


__all__ = ["router"]
