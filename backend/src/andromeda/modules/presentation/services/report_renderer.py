"""Presentation service boundary for future HTML/PDF implementations."""

from __future__ import annotations

from ..contracts.report import RenderedReport, ReportRendererPort, ReportSpec


class ReportRendererService:
    def __init__(self, renderer: ReportRendererPort) -> None:
        self._renderer = renderer

    def render(self, spec: ReportSpec) -> RenderedReport:
        return self._renderer.render(spec)


__all__ = ["ReportRendererService"]
