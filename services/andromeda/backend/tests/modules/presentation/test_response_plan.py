from __future__ import annotations

import pytest
from pydantic import ValidationError

from andromeda.modules.presentation.contracts.policy import (
    ResponseFormat,
    ResponsePlan,
    ResponsePolicyResult,
)


def test_response_plan_is_typed_and_template_allow_listed() -> None:
    policy = ResponsePolicyResult(
        response_format=ResponseFormat.IMAGE,
        template="metric-comparison",
        reason="comparison",
    )
    plan = policy.to_plan(data={"rows": []}, evidence_available=True)

    assert isinstance(plan, ResponsePlan)
    assert plan.template == "metric-comparison"
    assert plan.evidence_available is True

    with pytest.raises(ValidationError):
        ResponsePlan(response_format=ResponseFormat.TEXT, template="raw-html")
