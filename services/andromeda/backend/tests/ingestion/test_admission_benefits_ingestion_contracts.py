from __future__ import annotations

from datetime import datetime, timezone

from andromeda.ingestion.contracts.admission_benefits import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
    AdmissionBenefitsSnapshot,
    RawAdmissionBenefitCell,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
    RawAdmissionBenefitRecordKind,
)
from andromeda.ingestion.contracts.raw import SourceLocator
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution


def test_raw_benefit_record_keeps_snapshot_identity_and_table_shape() -> None:
    source_url = "https://api.www.bmstu.ru/file/122150/download"
    locator = SourceLocator(source_url=source_url, page=4, row=7)
    document = RawAdmissionBenefitDocument(
        document_kind="appendix_5_3",
        document_title="Приложение 5.3",
        admission_year=2026,
        source_url=source_url,
        source_snapshot_hash="a" * 64,
        source_run_id="ingest:" + "b" * 32,
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        locator=locator,
        parser_version="bmstu-admission-parser.v1",
        raw_page_text="Победитель олимпиады получает 100 баллов по физике",
    )
    record = RawAdmissionBenefitRecord(
        record_id="raw-admission-benefit:appendix-5-3-row-7",
        record_kind=RawAdmissionBenefitRecordKind.BENEFIT_RULE,
        document_kind=document.document_kind,
        document_title=document.document_title,
        admission_year=document.admission_year,
        source_url=document.source_url,
        source_snapshot_hash=document.source_snapshot_hash,
        source_run_id=document.source_run_id,
        captured_at=document.captured_at,
        locator=locator,
        raw_text=document.raw_page_text or "",
        cells=(RawAdmissionBenefitCell(header="Результат", value="победитель"),),
        parser_version=document.parser_version,
    )

    assert record.source_snapshot_hash == document.source_snapshot_hash
    assert record.cells[0].header == "Результат"


def test_canonical_snapshot_can_be_partial_and_preserves_source_gaps() -> None:
    source_url = "https://api.www.bmstu.ru/file/122150/download"
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url=source_url,
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256="c" * 64,
        locator="appendix=5.3;page=1",
        run_id="ingest:" + "d" * 32,
    )
    snapshot = AdmissionBenefitsSnapshot(
        admission_year=2026,
        sources=(source,),
        coverage=AdmissionBenefitCoverage(
            status=AdmissionBenefitCoverageStatus.REVIEW_REQUIRED,
            documents_discovered=8,
            documents_captured=7,
            documents_parsed=6,
            unresolved_targets=2,
            review_required_rows=3,
            source_hashes=("c" * 64,),
        ),
    )

    assert snapshot.coverage.status is AdmissionBenefitCoverageStatus.REVIEW_REQUIRED
    assert snapshot.benefit_rules == ()
    assert snapshot.coverage.unresolved_targets == 2
