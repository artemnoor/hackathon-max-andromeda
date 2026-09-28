"""Parse BMSTU 2026 appendices 5.4 and 5.5.

These appendices are structurally different from the RSOSH tables in 5.1/5.3:
they map a VOSH or international-olympiad profile to an entrance subject and
to an NPS scope.  Keeping the parser separate prevents generic table heuristics
from treating quota and olympiad documents as the same legal table.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from andromeda.ingestion.contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitCandidate,
    RawAdmissionBenefitCell,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
    RawAdmissionBenefitRecordKind,
    SourceLocator,
)

_DIRECTION_CODE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{2}\b")


def parse_special_olympiad_tables(
    document: RawAdmissionBenefitDocument,
    tables: Iterable[Mapping[str, Any]],
) -> tuple[tuple[RawAdmissionBenefitRecord, ...], tuple[AdmissionBenefitParserDiagnostic, ...]]:
    """Convert 5.4/5.5 profile mappings into auditable raw candidates."""

    route = "vosh" if document.document_kind == "appendix_5_4" else "international"
    olympiad_name = (
        "Всероссийская олимпиада школьников"
        if route == "vosh"
        else "Международная олимпиада школьников"
    )
    result_types = ("winner", "prize_winner") if route == "vosh" else ("team_member",)
    records: list[RawAdmissionBenefitRecord] = []
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    section: str | None = None
    seen: set[tuple[str, str, str]] = set()

    for table_index, table in enumerate(tables, start=1):
        page = _positive_int(table.get("page")) or 1
        source_table = _positive_int(table.get("table")) or _positive_int(table.get("index")) or table_index
        rows = [_values(row) for row in (table.get("rows") or table.get("raw_rows") or ()) if _values(row)]
        if not rows:
            continue
        first_text = _normalize(_join(rows[0]))
        detected = _section_for_header(first_text)
        if detected is not None:
            section = detected
            rows = rows[1:]
        elif section is None:
            # PDF table extraction often drops the repeated heading on a
            # continuation page.  The official table order is stable.
            section = "subject" if table_index <= 2 else "scope"
        source_row_numbers = table.get("row_numbers") or ()
        source_pages = table.get("row_pages") or ()
        carried_profile = ""
        for row_index, row in enumerate(rows, start=1):
            row_text = _join(row)
            if not row_text or _looks_like_header(row_text):
                continue
            # pdfplumber exposes wrapped continuation lines from the
            # international-olympiad tables as one-cell rows.  They do not
            # contain a complete legal mapping by themselves; retaining them
            # as parser warnings would inflate review coverage without adding
            # an actionable source gap.  The complete mapping is captured by
            # the adjacent two-column table rows.
            if len(row) < 2:
                continue
            profile, value = _profile_and_value(row, section)
            if profile:
                carried_profile = profile
            elif carried_profile and value:
                profile = carried_profile
            if not profile or not value:
                # A wrapped PDF line without a legal value is retained as a
                # diagnostic, never guessed into a canonical rule.
                if row_text:
                    locator = _locator(document, source_table, row_index, page, source_row_numbers, source_pages)
                    diagnostics.append(
                        AdmissionBenefitParserDiagnostic(
                            code="special_olympiad_row_review_required",
                            stage="special_olympiad",
                            message="profile or mapped value could not be resolved safely",
                            severity="ambiguous",
                            locator=locator,
                        )
                    )
                continue
            key = (section, _normalize(profile), _normalize(value))
            if key in seen:
                continue
            seen.add(key)
            locator = _locator(document, source_table, row_index, page, source_row_numbers, source_pages)
            for result_type in result_types:
                candidates = [
                    RawAdmissionBenefitCandidate(field="olympiad_name", value=olympiad_name),
                    RawAdmissionBenefitCandidate(field="profile_name", value=profile),
                    RawAdmissionBenefitCandidate(field="route", value=route),
                    RawAdmissionBenefitCandidate(field="result_type", value=result_type),
                    RawAdmissionBenefitCandidate(field="benefit_granted", value="yes"),
                    RawAdmissionBenefitCandidate(field="confirmation_required", value="no"),
                ]
                if section == "subject":
                    candidates.extend(
                        (
                            RawAdmissionBenefitCandidate(field="benefit_type", value="one_hundred_points"),
                            RawAdmissionBenefitCandidate(field="target_subject", value=value),
                            RawAdmissionBenefitCandidate(field="confirmation_subject", value=value),
                            RawAdmissionBenefitCandidate(field="scope_mode", value="all"),
                            RawAdmissionBenefitCandidate(field="scope_text", value="Профиль применяется по соответствующему НП(С); приложение не перечисляет коды НП(С)"),
                            RawAdmissionBenefitCandidate(field="scope_review_required", value="yes"),
                        )
                    )
                else:
                    candidates.extend(
                        (
                            RawAdmissionBenefitCandidate(field="benefit_type", value="bvi"),
                            *_scope_candidates(value),
                        )
                    )
                records.append(
                    RawAdmissionBenefitRecord(
                        record_id=f"raw-special-olympiad:{document.source_snapshot_hash[:16]}:{page}:{source_table}:{row_index}:{section}:{result_type}",
                        record_kind=RawAdmissionBenefitRecordKind.BENEFIT_RULE,
                        document_kind=document.document_kind,
                        document_title=document.document_title,
                        admission_year=document.admission_year,
                        source_url=document.source_url,
                        source_snapshot_hash=document.source_snapshot_hash,
                        source_run_id=document.source_run_id,
                        captured_at=document.captured_at,
                        locator=locator,
                        raw_text=row_text,
                        cells=tuple(
                            RawAdmissionBenefitCell(header=f"column_{index + 1}", value=value)
                            for index, value in enumerate(row)
                            if value
                        ),
                        normalized_candidates=tuple(candidates),
                        parser_version=document.parser_version,
                    )
                )
    return tuple(records), tuple(diagnostics)


def _section_for_header(value: str) -> str | None:
    if "нпс" in value or "направлен" in value or "специальност" in value:
        return "scope"
    if "испытан" in value:
        return "subject"
    return None


def _profile_and_value(row: list[str], section: str) -> tuple[str, str]:
    if section == "subject" and len(row) >= 3:
        profile_values = [value for value in row[:-1] if value]
        return _normalize_text(" ".join(profile_values)), _normalize_text(row[-1])
    if len(row) >= 2:
        return _normalize_text(row[0]), _normalize_text(" ".join(row[1:]))
    return "", ""


def _scope_candidates(value: str) -> list[RawAdmissionBenefitCandidate]:
    normalized = _normalize(value)
    codes = tuple(dict.fromkeys(_DIRECTION_CODE_RE.findall(value)))
    if "любое нпс" in normalized or "любое нп(с)" in normalized:
        return [
            RawAdmissionBenefitCandidate(field="scope_mode", value="all"),
            RawAdmissionBenefitCandidate(field="scope_text", value=value),
        ]
    if codes:
        candidates = [
            RawAdmissionBenefitCandidate(field="scope_mode", value="only"),
            *(RawAdmissionBenefitCandidate(field="scope_direction_code", value=code) for code in codes),
            RawAdmissionBenefitCandidate(field="scope_text", value=value),
        ]
        if "платн" in normalized:
            candidates.append(RawAdmissionBenefitCandidate(field="scope_review_required", value="yes"))
        return candidates
    return [
        RawAdmissionBenefitCandidate(field="scope_mode", value="all"),
        RawAdmissionBenefitCandidate(field="scope_text", value=value),
        RawAdmissionBenefitCandidate(field="scope_review_required", value="yes"),
    ]


def _locator(
    document: RawAdmissionBenefitDocument,
    table: int,
    row: int,
    page: int,
    row_numbers: object,
    row_pages: object,
) -> SourceLocator:
    source_row = row_numbers[row - 1] if isinstance(row_numbers, (list, tuple)) and row - 1 < len(row_numbers) and isinstance(row_numbers[row - 1], int) else row
    source_page = row_pages[row - 1] if isinstance(row_pages, (list, tuple)) and row - 1 < len(row_pages) and isinstance(row_pages[row - 1], int) else page
    return SourceLocator(source_url=document.source_url, page=source_page, row=source_row, field=f"table:{table}")


def _values(row: Any) -> list[str]:
    if isinstance(row, Mapping):
        return [str(value).strip() for value in row.values() if value is not None and str(value).strip()]
    if isinstance(row, (list, tuple)):
        return [str(value or "").strip() for value in row if value is not None and str(value or "").strip()]
    return []


def _looks_like_header(value: str) -> bool:
    normalized = _normalize(value)
    return (
        "профиль вош" in normalized
        or "профиль международ" in normalized
        or "общеобразовательное вступительное" in normalized
        or "нпс для предоставления" in normalized
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\n", " ").split()).strip()


def _normalize(value: str) -> str:
    return _normalize_text(value).casefold().replace("ё", "е")


def _join(values: list[str]) -> str:
    return " | ".join(value for value in values if value)


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 1 else None


__all__ = ["parse_special_olympiad_tables"]
