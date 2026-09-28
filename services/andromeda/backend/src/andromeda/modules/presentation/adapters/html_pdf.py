"""HTML-to-PDF adapter seam with an explicit optional dependency."""

from __future__ import annotations

from andromeda.shared.contracts.errors import ContractError, ErrorCode

from ..contracts.report import RenderedReport, ReportFormat, ReportSpec


class HtmlPdfReportRenderer:
    """Render a ReportSpec with WeasyPrint when the deployment provides it."""

    def render(self, spec: ReportSpec) -> RenderedReport:
        html = _html_document(spec)
        if spec.output_format is ReportFormat.HTML:
            return RenderedReport(content=html.encode("utf-8"), media_type="text/html", filename=f"{spec.filename}.html", output_format=ReportFormat.HTML)
        try:
            from weasyprint import HTML  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ContractError(ErrorCode.INTERNAL_ERROR, "PDF rendering dependency is not installed") from exc
        content = HTML(string=html).write_pdf()
        return RenderedReport(content=content, media_type="application/pdf", filename=f"{spec.filename}.pdf", output_format=ReportFormat.PDF)


def _html_document(spec: ReportSpec) -> str:
    rows = []
    for row in spec.result.rows:
        values = ", ".join(f"{code}: {metric.value if metric.value is not None else 'unknown'}" for code, metric in row.metrics.items())
        rows.append(f"<li><strong>{row.entity_id}</strong>: {values}</li>")
    return f"<html><head><meta charset='utf-8'><title>{spec.title}</title></head><body><h1>{spec.title}</h1><ul>{''.join(rows)}</ul></body></html>"


__all__ = ["HtmlPdfReportRenderer"]
