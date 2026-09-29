from __future__ import annotations

from andromeda.ingestion.contracts.admission_benefits import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
    RawAdmissionBenefitRecord,
)
from andromeda.shared.contracts.provenance import SourceGapReference


def build_coverage(
    *,
    documents_discovered: int,
    documents_captured: int,
    records: tuple[RawAdmissionBenefitRecord, ...],
    normalized_count: int,
    documents_selected: int | None = None,
    documents_parsed: int | None = None,
    required_documents_expected: int = 0,
    required_documents_discovered: int = 0,
    required_documents_captured: int = 0,
    manifest_hash: str | None = None,
    source_hashes: tuple[str, ...] = (),
    source_gaps: tuple[SourceGapReference, ...] = (),
    resolved_targets: int = 0,
    unresolved_targets: int = 0,
    conflicts: int = 0,
    review_required_rows: int = 0,
) -> AdmissionBenefitCoverage:
    selected_count = (
        documents_discovered if documents_selected is None else documents_selected
    )
    parsed_count = (
        len({record.source_snapshot_hash for record in records})
        if documents_parsed is None
        else documents_parsed
    )
    incomplete = (
        bool(source_gaps)
        or documents_captured < selected_count
        or required_documents_discovered < required_documents_expected
        or required_documents_captured < required_documents_expected
    )
    status = (
        AdmissionBenefitCoverageStatus.PARTIAL
        if incomplete
        else AdmissionBenefitCoverageStatus.REVIEW_REQUIRED
        if conflicts
        or review_required_rows
        or unresolved_targets
        or normalized_count < len(records)
        else AdmissionBenefitCoverageStatus.COMPLETE
    )
    return AdmissionBenefitCoverage(
        status=status,
        documents_discovered=documents_discovered,
        documents_selected=selected_count,
        documents_captured=documents_captured,
        documents_parsed=parsed_count,
        required_documents_expected=required_documents_expected,
        required_documents_discovered=required_documents_discovered,
        required_documents_captured=required_documents_captured,
        records_normalized=normalized_count,
        targets_resolved=resolved_targets,
        unresolved_targets=unresolved_targets,
        conflicts=conflicts,
        review_required_rows=review_required_rows,
        manifest_hash=manifest_hash,
        source_hashes=tuple(
            dict.fromkeys(
                source_hashes
                or tuple(record.source_snapshot_hash for record in records)
            )
        ),
    )


__all__ = ["build_coverage"]
