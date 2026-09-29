from __future__ import annotations

from collections.abc import Mapping

from andromeda.ingestion.contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
)
from andromeda.ingestion.universities.bmstu.html import parse_page

from .admission_benefit_tables import parse_benefit_tables


def parse_benefit_html(
    document: RawAdmissionBenefitDocument,
    body: bytes,
) -> tuple[tuple[RawAdmissionBenefitRecord, ...], tuple[AdmissionBenefitParserDiagnostic, ...]]:
    page = parse_page(body, str(document.source_url))
    tables = tuple(
        {
            "page": 1,
            "table": table["index"],
            "rows": [list(row.values()) if isinstance(row, Mapping) else list(row) for row in table.get("raw_rows", ())],
        }
        for table in page.tables
    )
    if tables:
        records, diagnostics = parse_benefit_tables(document, tables)
        return records, diagnostics
    diagnostic = AdmissionBenefitParserDiagnostic(
        code="html_table_missing",
        stage="html",
        message="official HTML page has no structured benefit table",
        severity="warning",
        locator=document.locator,
    )
    return (), (diagnostic,)


__all__ = ["parse_benefit_html"]
