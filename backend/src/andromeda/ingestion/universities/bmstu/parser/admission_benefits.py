from __future__ import annotations

import logging
from datetime import datetime

from andromeda.ingestion.contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
    RawAdmissionBenefitRecordKind,
    RawSourceSnapshot,
    SourceLocator,
)
from andromeda.ingestion.universities.bmstu.html import extract_text
from andromeda.ingestion.universities.bmstu.pdf import extract_pdf_tables, extract_pdf_text, is_pdf
from andromeda.shared.contracts.ids import IngestRunId

from .admission_benefit_html import parse_benefit_html
from .admission_benefit_tables import parse_benefit_tables

logger = logging.getLogger("andromeda.ingestion.bmstu.parser.admission_benefits")
PARSER_VERSION = "bmstu-admission-parser.v1"


class BmstuAdmissionBenefitsParser:
    """Parse official BMSTU rows while keeping unresolved facts auditable."""

    def parse_snapshot(
        self,
        snapshot: RawSourceSnapshot,
        *,
        document_kind: str,
        document_title: str,
        source_run_id: IngestRunId,
        tables: tuple[dict[str, object], ...] | None = None,
    ) -> tuple[tuple[RawAdmissionBenefitRecord, ...], tuple[AdmissionBenefitParserDiagnostic, ...]]:
        document = RawAdmissionBenefitDocument(
            document_kind=document_kind,
            document_title=document_title,
            admission_year=_year(document_title),
            source_url=snapshot.requested_url,
            source_snapshot_hash=snapshot.content_sha256,
            source_run_id=source_run_id,
            captured_at=snapshot.captured_at,
            locator=SourceLocator(source_url=snapshot.requested_url),
            parser_version=PARSER_VERSION,
        )
        logger.info(
            "bmstu_admission_parser_start document_kind=%s snapshot_hash=%s bytes=%d",
            document_kind,
            snapshot.content_sha256,
            len(snapshot.body),
        )
        if tables is not None:
            result = parse_benefit_tables(document, tables)
        elif is_pdf(snapshot.body, snapshot.content_type, str(snapshot.requested_url)):
            result = self._parse_pdf(document, snapshot.body)
        else:
            result = parse_benefit_html(document, snapshot.body)
        logger.info(
            "bmstu_admission_parser_complete document_kind=%s records=%d diagnostics=%d",
            document_kind,
            len(result[0]),
            len(result[1]),
        )
        return result

    @staticmethod
    def _parse_pdf(
        document: RawAdmissionBenefitDocument,
        body: bytes,
    ) -> tuple[tuple[RawAdmissionBenefitRecord, ...], tuple[AdmissionBenefitParserDiagnostic, ...]]:
        diagnostics: list[AdmissionBenefitParserDiagnostic] = []
        try:
            tables = extract_pdf_tables(body)
        except Exception as exc:
            logger.warning("bmstu_admission_pdf_table_extract_failed kind=%s error_type=%s", document.document_kind, type(exc).__name__)
            tables = []
            diagnostics.append(
                AdmissionBenefitParserDiagnostic(
                    code="pdf_table_extract_failed",
                    stage="pdf",
                    message="PDF table extraction failed; text retained for review",
                    severity="warning",
                    locator=document.locator,
                )
            )
        if tables:
            records, table_diagnostics = parse_benefit_tables(document, tables)
            return records, tuple((*diagnostics, *table_diagnostics))
        try:
            text = extract_pdf_text(body)
        except Exception as exc:
            logger.warning("bmstu_admission_pdf_text_extract_failed kind=%s error_type=%s", document.document_kind, type(exc).__name__)
            text = ""
        if not text:
            diagnostics.append(
                AdmissionBenefitParserDiagnostic(
                    code="pdf_text_missing",
                    stage="pdf",
                    message="PDF has no extractable text layer",
                    severity="error",
                    locator=document.locator,
                )
            )
            return (), tuple(diagnostics)
        record = RawAdmissionBenefitRecord(
            record_id=f"raw-admission-benefit:{document.source_snapshot_hash[:16]}:text",
            record_kind=RawAdmissionBenefitRecordKind.SOURCE_GAP,
            document_kind=document.document_kind,
            document_title=document.document_title,
            admission_year=document.admission_year,
            source_url=document.source_url,
            source_snapshot_hash=document.source_snapshot_hash,
            source_run_id=document.source_run_id,
            captured_at=document.captured_at,
            locator=document.locator,
            raw_text=text[:100_000],
            diagnostics=tuple(diagnostics),
            parser_version=document.parser_version,
        )
        return (record,), tuple(diagnostics)


def _year(title: str) -> int:
    import re

    match = re.search(r"20\d{2}", title)
    return int(match.group(0)) if match else 2026


__all__ = ["BmstuAdmissionBenefitsParser", "PARSER_VERSION"]
