"""Build bounded envelopes from already computed policy/result objects."""

from __future__ import annotations

from andromeda.modules.analytics.contracts.results import AnalyticsResult

from ..contracts.envelope import EvidenceSummary, ResponseActionItem, ResponseEnvelope
from ..contracts.policy import ResponsePolicyResult


def build_response_envelope(
    result: AnalyticsResult,
    policy: ResponsePolicyResult,
    *,
    text: str = "",
    actions: tuple[ResponseActionItem, ...] = (),
    query_reference: str | None = None,
    result_reference: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ResponseEnvelope:
    evidence_by_metric: dict[str, int] = {}
    for row in result.rows:
        for evidence in row.evidence:
            evidence_by_metric[evidence.metric_code] = evidence_by_metric.get(evidence.metric_code, 0) + 1
    payload: dict[str, object] = {"rows": [row.model_dump(mode="json") for row in result.rows]}
    plan = policy.to_plan(
        text=text,
        data=payload,
        result_reference=result_reference,
        evidence_available=bool(evidence_by_metric),
        has_source_gaps=bool(result.source_gaps),
    )
    return ResponseEnvelope(
        response_type=policy.response_format,
        text=text,
        template=policy.template,
        data=payload,
        actions=actions,
        query_reference=query_reference,
        result_reference=result_reference,
        evidence=tuple(
            EvidenceSummary(metric_code=metric.code, evidence_count=evidence_by_metric.get(metric.code, 0), coverage=str(result.coverage))
            for metric in result.metric_definitions
        ),
        metadata={"status": result.status.value, "reason": policy.reason, **(metadata or {})},
        plan=plan,
    )


__all__ = ["build_response_envelope"]
