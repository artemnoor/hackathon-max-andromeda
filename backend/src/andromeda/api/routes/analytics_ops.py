"""Protected, privacy-safe decision funnel for operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from andromeda.api.dependencies import require_ops_access
from andromeda.api.dependencies.services import get_decision_analytics_reader
from andromeda.api.schemas.admin_ops import DecisionAnalyticsFunnelResponse
from andromeda.modules.decision.repository.ports import DecisionAnalyticsReader


router = APIRouter(prefix="/ops/analytics", tags=["admin-ops"])


@router.get(
    "/funnel",
    response_model=DecisionAnalyticsFunnelResponse,
    operation_id="get_decision_analytics_funnel",
    dependencies=[Depends(require_ops_access)],
)
def get_decision_analytics_funnel(
    reader: DecisionAnalyticsReader = Depends(get_decision_analytics_reader),
) -> DecisionAnalyticsFunnelResponse:
    return DecisionAnalyticsFunnelResponse.model_validate(reader.funnel().model_dump())


__all__ = ["router"]
