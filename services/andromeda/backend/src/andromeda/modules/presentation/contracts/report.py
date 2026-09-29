"""Report input/output contracts; renderers never query the database."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.shared.contracts.base import ContractModel


class ReportFormat(StrEnum):
    PDF = "pdf"
    HTML = "html"


class ReportSpec(ContractModel):
    title: str = Field(min_length=1, max_length=256)
    result: AnalyticsResult
    output_format: ReportFormat = ReportFormat.PDF
    include_evidence: bool = True
    filename: str = Field(default="andromeda-report", min_length=1, max_length=128)


class RenderedReport(ContractModel):
    content: bytes
    media_type: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=128)
    output_format: ReportFormat


class ReportRendererPort(Protocol):
    def render(self, spec: ReportSpec) -> RenderedReport: ...


__all__ = ["RenderedReport", "ReportFormat", "ReportRendererPort", "ReportSpec"]
