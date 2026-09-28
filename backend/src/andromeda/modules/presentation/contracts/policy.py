"""Response selection independent of channel rendering."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.versions import RESPONSE_POLICY_VERSION


class ResponseFormat(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    IMAGE_COLLECTION = "image_collection"
    PDF = "pdf"
    MINI_APP = "mini_app"


ALLOWED_RESPONSE_TEMPLATES = frozenset(
    {
        "analytics-summary",
        "metric-comparison",
        "metric-cards",
        "analytics-report",
        "analytics-explorer",
        "admission-fit-summary",
    }
)


class ResponsePlan(ContractModel):
    """Prepared presentation input; it contains no query or aggregation logic."""

    response_format: ResponseFormat
    template: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=20_000)
    data: dict[str, object] = Field(default_factory=dict, max_length=64)
    actions: tuple[str, ...] = Field(default=(), max_length=20)
    result_reference: str | None = Field(default=None, max_length=256)
    evidence_available: bool = False
    has_source_gaps: bool = False
    policy_version: str = RESPONSE_POLICY_VERSION

    @field_validator("template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        if value not in ALLOWED_RESPONSE_TEMPLATES:
            raise ValueError("unknown response template")
        return value


class PresentationCapabilities(ContractModel):
    text: bool = True
    image: bool = True
    pdf: bool = True
    mini_app: bool = False


class ResponseRequest(ContractModel):
    result: AnalyticsResult | None = None
    comparison_requested: bool = False
    report_requested: bool = False
    interactive_requested: bool = False
    evidence_requested: bool = False


class ResponsePolicyResult(ContractModel):
    response_format: ResponseFormat
    template: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=512)
    policy_version: str = RESPONSE_POLICY_VERSION

    def to_plan(
        self,
        *,
        text: str = "",
        data: dict[str, object] | None = None,
        result_reference: str | None = None,
        evidence_available: bool = False,
        has_source_gaps: bool = False,
    ) -> ResponsePlan:
        return ResponsePlan(
            response_format=self.response_format,
            template=self.template,
            text=text,
            data=data or {},
            result_reference=result_reference,
            evidence_available=evidence_available,
            has_source_gaps=has_source_gaps,
            policy_version=self.policy_version,
        )


class ResponsePolicyPort(Protocol):
    def choose(
        self,
        request: ResponseRequest,
        *,
        capabilities: PresentationCapabilities | None = None,
    ) -> ResponsePolicyResult: ...


__all__ = [
    "ALLOWED_RESPONSE_TEMPLATES",
    "PresentationCapabilities",
    "ResponseFormat",
    "ResponsePlan",
    "ResponsePolicyPort",
    "ResponsePolicyResult",
    "ResponseRequest",
]
