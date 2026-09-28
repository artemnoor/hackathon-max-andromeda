"""Choose a channel-neutral response format using an already computed result."""

from __future__ import annotations

from ..contracts.policy import (
    PresentationCapabilities,
    ResponseFormat,
    ResponsePolicyResult,
    ResponseRequest,
)


class RuleBasedResponsePolicy:
    def choose(self, request: ResponseRequest, *, capabilities: PresentationCapabilities | None = None) -> ResponsePolicyResult:
        caps = capabilities or PresentationCapabilities()
        result = request.result
        if request.report_requested and caps.pdf:
            return ResponsePolicyResult(response_format=ResponseFormat.PDF, template="analytics-report", reason="The caller requested a report")
        if request.interactive_requested and caps.mini_app:
            return ResponsePolicyResult(response_format=ResponseFormat.MINI_APP, template="analytics-explorer", reason="The channel supports interactive exploration")
        if result is None or len(result.rows) <= 1 or not caps.image:
            return ResponsePolicyResult(response_format=ResponseFormat.TEXT, template="analytics-summary", reason="A short or non-visual response is sufficient")
        if request.comparison_requested or len(result.rows) == 2:
            return ResponsePolicyResult(response_format=ResponseFormat.IMAGE, template="metric-comparison", reason="A bounded comparison is easier to scan visually")
        if len(result.rows) <= 10:
            return ResponsePolicyResult(response_format=ResponseFormat.IMAGE_COLLECTION, template="metric-cards", reason="Several bounded rows fit a collection of cards")
        if caps.pdf:
            return ResponsePolicyResult(response_format=ResponseFormat.PDF, template="analytics-report", reason="A larger result needs a paged report")
        return ResponsePolicyResult(response_format=ResponseFormat.TEXT, template="analytics-summary", reason="The channel has no suitable large-result format")


__all__ = ["RuleBasedResponsePolicy"]
