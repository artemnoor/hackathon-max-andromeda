"""Channel-neutral response envelope and allow-listed user actions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.versions import RESPONSE_POLICY_VERSION

from .knowledge_response import KnowledgeResponseSection, ResponseMode
from .policy import ResponseFormat, ResponsePlan


class ResponseAction(StrEnum):
    SHOW_DETAILS = "show_details"
    COMPARE = "compare"
    ADD_TO_SHORTLIST = "add_to_shortlist"
    CHANGE_SCOPE = "change_scope"
    SHOW_CURRICULUM = "show_curriculum"
    DOWNLOAD_REPORT = "download_report"
    OPEN_MINI_APP = "open_mini_app"


class ResponseActionItem(ContractModel):
    action: ResponseAction
    label: str = Field(min_length=1, max_length=128)
    payload: dict[str, str] = Field(default_factory=dict, max_length=8)


class EvidenceSummary(ContractModel):
    metric_code: str = Field(min_length=1, max_length=64)
    evidence_count: int = Field(strict=True, ge=0, le=1000)
    coverage: str = Field(min_length=1, max_length=32)


class ResponseEnvelope(ContractModel):
    response_type: ResponseFormat
    response_mode: ResponseMode = ResponseMode.DETERMINISTIC
    text: str = Field(default="", max_length=20_000)
    template: str = Field(min_length=1, max_length=128)
    data: dict[str, object] = Field(default_factory=dict, max_length=64)
    actions: tuple[ResponseActionItem, ...] = Field(default=(), max_length=20)
    deep_link: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, object] = Field(default_factory=dict, max_length=32)
    query_reference: str | None = Field(default=None, max_length=256)
    result_reference: str | None = Field(default=None, max_length=256)
    evidence: tuple[EvidenceSummary, ...] = Field(default=(), max_length=32)
    knowledge: KnowledgeResponseSection | None = None
    policy_version: str = RESPONSE_POLICY_VERSION
    plan: ResponsePlan | None = None


__all__ = [
    "EvidenceSummary",
    "ResponseAction",
    "ResponseActionItem",
    "ResponseEnvelope",
]
