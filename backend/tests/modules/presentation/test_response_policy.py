from __future__ import annotations

from decimal import Decimal

from andromeda.modules.analytics.contracts.metrics import MetricEntityType
from andromeda.modules.analytics.contracts.public import (
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
)
from andromeda.modules.analytics.contracts.query import QuerySpec
from andromeda.modules.analytics.contracts.results import (
    AnalyticsResult,
    AnalyticsResultStatus,
    AnalyticsRow,
)
from andromeda.modules.presentation.contracts.policy import (
    PresentationCapabilities,
    ResponseFormat,
    ResponseRequest,
)
from andromeda.modules.presentation.services.rule_response_policy import (
    RuleBasedResponsePolicy,
)


def _result(row_count: int) -> AnalyticsResult:
    query = QuerySpec(entity=MetricEntityType.PROGRAM, metrics=("math_share",))
    quality = ProjectionDataQuality(status=ProjectionDataQualityStatus.INSUFFICIENT_DATA, coverage=Decimal("0"), confidence=Decimal("0"))
    rows = tuple(AnalyticsRow(entity_id=f"program:bmstu:09.03.01-{index:02d}", metrics={}, quality=quality) for index in range(1, row_count + 1))
    return AnalyticsResult(query=query, rows=rows, status=AnalyticsResultStatus.PARTIAL, coverage=Decimal("0"), confidence=Decimal("0"))


def test_response_policy_selects_text_comparison_and_report_without_recomputing() -> None:
    policy = RuleBasedResponsePolicy()
    assert policy.choose(ResponseRequest()).response_format is ResponseFormat.TEXT
    comparison = policy.choose(ResponseRequest(result=_result(2), comparison_requested=True))
    assert comparison.response_format is ResponseFormat.IMAGE
    report = policy.choose(ResponseRequest(result=_result(2), report_requested=True))
    assert report.response_format is ResponseFormat.PDF


def test_response_policy_respects_channel_capabilities() -> None:
    decision = RuleBasedResponsePolicy().choose(
        ResponseRequest(result=_result(2), interactive_requested=True),
        capabilities=PresentationCapabilities(image=False, pdf=False, mini_app=False),
    )
    assert decision.response_format is ResponseFormat.TEXT
