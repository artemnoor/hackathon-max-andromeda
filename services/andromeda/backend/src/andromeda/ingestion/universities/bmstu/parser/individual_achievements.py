from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from andromeda.ingestion.contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitCandidate,
    RawAdmissionBenefitCell,
    RawAdmissionBenefitDocument,
    RawIndividualAchievementDocumentNote,
    RawIndividualAchievementRecord,
    SourceLocator,
)

_ROW_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\s*$")
_TRAILING_SCORE_RE = re.compile(r"^(.*?)(?<![\d-])(\d{1,3})\s*$", re.DOTALL)
_NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_MAX_EXTRACTED_SCORE = 100
logger = logging.getLogger("andromeda.ingestion.bmstu.individual_achievements")


@dataclass(frozen=True)
class _TableColumns:
    number: int = 0
    name: int = 1
    document: int | None = 2
    points_start: int = 3
    headers: tuple[str, ...] = ()


@dataclass
class _SourceRow:
    source_number: int
    table_number: int
    first_page: int
    columns: _TableColumns
    physical_rows: list[tuple[int, list[str]]] = field(default_factory=list)

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({page for page, _ in self.physical_rows}))


@dataclass(frozen=True)
class _PointVariant:
    points: str
    label: str | None
    required_document: str | None
    page: int


def parse_individual_achievement_tables(
    document: RawAdmissionBenefitDocument,
    tables: Iterable[Mapping[str, Any]],
    *,
    document_pages: Iterable[tuple[int, str]] = (),
) -> tuple[
    tuple[RawIndividualAchievementRecord, ...],
    tuple[AdmissionBenefitParserDiagnostic, ...],
]:
    """Parse numbered Appendix 6/7 rows and retain source footnotes verbatim.

    Continuation rows are attached to the preceding numbered item across page
    boundaries. Score variants remain separate raw records, while no legal
    sum/deduplication policy is inferred here.
    """

    notes = _document_policy_notes(document, document_pages)
    rows: list[_SourceRow] = []
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    columns = _TableColumns()
    active: _SourceRow | None = None
    physical_index = 0

    for table_index, table in enumerate(tables, start=1):
        page = _positive_int(table.get("page")) or 1
        table_number = (
            _positive_int(table.get("table"))
            or _positive_int(table.get("index"))
            or table_index
        )
        raw_rows = table.get("rows") or table.get("raw_rows") or ()
        table_rows = [_values(row) for row in raw_rows if _values(row)]
        if not table_rows:
            continue

        start = 0
        if _looks_like_header(table_rows[0]):
            columns = _columns_from_header(table_rows[0])
            start = 1

        source_row_numbers = table.get("row_numbers") or ()
        source_pages = table.get("row_pages") or ()
        for local_index, cells in enumerate(table_rows[start:]):
            physical_index += 1
            mapped_number = _metadata_int(source_row_numbers, local_index)
            source_number = _source_number(cells, columns.number) or mapped_number
            row_page = _metadata_int(source_pages, local_index) or page
            if source_number is not None:
                if active is not None:
                    rows.append(active)
                active = _SourceRow(
                    source_number=source_number,
                    table_number=table_number,
                    first_page=row_page,
                    columns=columns,
                    physical_rows=[(row_page, cells)],
                )
            elif active is not None:
                active.physical_rows.append((row_page, cells))
            elif any(cells):
                locator = SourceLocator(
                    source_url=document.source_url,
                    page=row_page,
                    row=physical_index,
                    field=f"table={table_number}",
                )
                diagnostics.append(
                    _diagnostic(
                        locator,
                        "individual_achievement_continuation_without_parent",
                        "non-empty table row has no source number or preceding numbered row",
                    )
                )

    if active is not None:
        rows.append(active)

    records: list[RawIndividualAchievementRecord] = []
    table_counts: dict[tuple[int, int], list[int]] = {}
    for source_row in rows:
        parsed, row_diagnostics = _records_for_row(
            document,
            source_row,
            notes,
        )
        records.extend(parsed)
        diagnostics.extend(row_diagnostics)
        counts = table_counts.setdefault(
            (source_row.first_page, source_row.table_number), [0, 0]
        )
        counts[0] += 1
        counts[1] += len(parsed)

    for (page, table_number), (source_rows, variants) in sorted(table_counts.items()):
        logger.info(
            "bmstu_individual_achievement_table_parsed source_sha256=%s page=%d "
            "table=%d source_rows=%d variants=%d",
            document.source_snapshot_hash,
            page,
            table_number,
            source_rows,
            variants,
        )
    for diagnostic in diagnostics:
        locator = diagnostic.locator
        logger.warning(
            "bmstu_individual_achievement_parse_gap source_sha256=%s code=%s "
            "page=%s row=%s field=%s",
            document.source_snapshot_hash,
            diagnostic.code,
            locator.page,
            locator.row,
            locator.field,
        )
    return tuple(records), tuple(diagnostics)


def _records_for_row(
    document: RawAdmissionBenefitDocument,
    source_row: _SourceRow,
    notes: tuple[RawIndividualAchievementDocumentNote, ...],
) -> tuple[
    tuple[RawIndividualAchievementRecord, ...],
    tuple[AdmissionBenefitParserDiagnostic, ...],
]:
    columns = source_row.columns
    merged = _merge_cells(source_row.physical_rows)
    name = _clean_text(merged[columns.name] if columns.name < len(merged) else "")
    base_document = _clean_text(
        merged[columns.document]
        if columns.document is not None and columns.document < len(merged)
        else ""
    )
    variants = _point_variants(source_row, columns, base_document)
    locator = SourceLocator(
        source_url=document.source_url,
        page=source_row.first_page,
        row=source_row.source_number,
        field=f"table={source_row.table_number}",
    )
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    if not name or not variants:
        diagnostics.append(
            _diagnostic(
                locator,
                "individual_achievement_row_review_required",
                "achievement name or one or more point variants could not be extracted safely",
            )
        )
    if not variants:
        variants = (_PointVariant(points="", label=None, required_document=base_document or None, page=source_row.first_page),)

    raw_text = "\n".join(
        _join(cells) for _, cells in source_row.physical_rows if _join(cells)
    )
    output: list[RawIndividualAchievementRecord] = []
    for variant_index, variant in enumerate(variants, start=1):
        variant_locator = locator.model_copy(
            update={
                "page": variant.page,
                "field": (
                    f"table={source_row.table_number};variant={variant_index}"
                ),
            }
        )
        candidates: list[RawAdmissionBenefitCandidate] = []
        if name:
            candidates.append(
                RawAdmissionBenefitCandidate(
                    field="official_name", value=_bounded_candidate(name, 2_000)
                )
            )
        if variant.label:
            candidates.append(
                RawAdmissionBenefitCandidate(
                    field="variant_label",
                    value=_bounded_candidate(variant.label, 2_000),
                )
            )
        if variant.points:
            candidates.append(
                RawAdmissionBenefitCandidate(field="points", value=variant.points)
            )
        if variant.required_document:
            candidates.append(
                RawAdmissionBenefitCandidate(
                    field="required_document",
                    value=_bounded_candidate(variant.required_document, 2_000),
                )
            )
        candidates.append(
            RawAdmissionBenefitCandidate(
                field="education_level",
                value=(
                    "master"
                    if document.document_kind == "appendix_7"
                    else "bachelor_or_specialist"
                ),
            )
        )
        raw_policy_text = _policy_text(raw_text)
        if raw_policy_text:
            candidates.append(
                RawAdmissionBenefitCandidate(
                    field="combination_text",
                    value=_bounded_candidate(raw_policy_text, 2_000),
                )
            )

        variant_diagnostics = (
            tuple(diagnostics)
            if not name or not variant.points
            else ()
        )
        cell_values = _variant_cells(
            merged,
            columns,
            name,
            variant.required_document,
            variant,
        )
        cells = tuple(
            RawAdmissionBenefitCell(
                header=(
                    columns.headers[index]
                    if index < len(columns.headers) and columns.headers[index]
                    else f"column_{index + 1}"
                ),
                value=value,
            )
            for index, value in enumerate(cell_values)
            if value
        )
        output.append(
            RawIndividualAchievementRecord(
                record_id=(
                    f"raw-individual-achievement:{document.source_snapshot_hash[:16]}:"
                    f"{source_row.first_page}:{source_row.table_number}:"
                    f"{source_row.source_number}:{variant_index}"
                ),
                document_kind=document.document_kind,
                document_title=document.document_title,
                admission_year=document.admission_year,
                source_url=document.source_url,
                source_snapshot_hash=document.source_snapshot_hash,
                source_run_id=document.source_run_id,
                captured_at=document.captured_at,
                locator=variant_locator,
                raw_text=_bounded_candidate(raw_text, 100_000),
                cells=cells,
                normalized_candidates=tuple(candidates),
                diagnostics=variant_diagnostics,
                parser_version=document.parser_version,
                achievement_code_candidate=None,
                official_name_candidate=_bounded_candidate(name, 512) if name else None,
                variant_label=_bounded_candidate(variant.label, 256) if variant.label else None,
                source_pages=source_row.pages,
                document_notes=notes,
                points_text=variant.points or None,
                required_document_text=(
                    _bounded_candidate(variant.required_document, 2_000)
                    if variant.required_document
                    else None
                ),
                combination_text=_bounded_candidate(raw_policy_text, 2_000)
                if raw_policy_text
                else None,
            )
        )
    return tuple(output), tuple(diagnostics)


def _point_variants(
    source_row: _SourceRow,
    columns: _TableColumns,
    base_document: str,
) -> tuple[_PointVariant, ...]:
    points_start = min(columns.points_start, min((len(cells) for _, cells in source_row.physical_rows), default=columns.points_start))
    pending_labels: list[str] = []
    variants: list[_PointVariant] = []
    for page, cells in source_row.physical_rows:
        row_document = (
            _clean_text(cells[columns.document])
            if columns.document is not None and columns.document < len(cells)
            else ""
        )
        for value in cells[points_start:]:
            lines = [line.strip() for line in value.splitlines() if line.strip()]
            for line in lines:
                if re.fullmatch(r"\d{1,3}", line):
                    score = int(line)
                    if 0 <= score <= _MAX_EXTRACTED_SCORE:
                        variants.append(
                            _PointVariant(
                                points=str(score),
                                label=_combine_label(pending_labels) or None,
                                required_document=row_document or base_document or None,
                                page=page,
                            )
                        )
                        pending_labels.clear()
                        continue
                match = _TRAILING_SCORE_RE.fullmatch(line)
                if match is not None and 0 <= int(match.group(2)) <= _MAX_EXTRACTED_SCORE:
                    label = [*pending_labels]
                    prefix = match.group(1).strip(" \t\n:;–—-")
                    if prefix:
                        label.append(prefix)
                    variants.append(
                        _PointVariant(
                            points=str(int(match.group(2))),
                            label=_combine_label(label) or None,
                            required_document=row_document or base_document or None,
                            page=page,
                        )
                    )
                    pending_labels.clear()
                    continue
                pending_labels.append(line)
    return tuple(variants)


def _document_policy_notes(
    document: RawAdmissionBenefitDocument,
    pages: Iterable[tuple[int, str]],
) -> tuple[RawIndividualAchievementDocumentNote, ...]:
    notes: list[RawIndividualAchievementDocumentNote] = []
    in_notes_section = False
    seen: set[tuple[str, str]] = set()
    for page, text in pages:
        if not text.strip():
            continue
        heading = re.search(r"Вниманию\s+абитуриентов\s*!", text, re.IGNORECASE)
        if not in_notes_section:
            star = re.search(
                r"(?ms)^\s*\*\s*(.+?)(?=^\s*Вниманию\s+абитуриентов\s*!|\Z)",
                text,
            )
            if star is not None:
                _append_note(
                    notes,
                    seen,
                    document,
                    page,
                    "*",
                    star.group(1),
                )
        if heading is not None:
            in_notes_section = True
            text = text[heading.end() :]
        if not in_notes_section:
            continue
        text = re.split(
            r"(?im)^\s*(?:Заместитель\s+председателя|Ответственный\s+секретарь)\b",
            text,
            maxsplit=1,
        )[0]
        for match in re.finditer(
            r"(?ms)^\s*(\d{1,2})\.\s*(.+?)(?=^\s*\d{1,2}\.\s|\Z)",
            text,
        ):
            _append_note(
                notes,
                seen,
                document,
                page,
                match.group(1),
                match.group(2),
            )
    return tuple(notes)


def _append_note(
    output: list[RawIndividualAchievementDocumentNote],
    seen: set[tuple[str, str]],
    document: RawAdmissionBenefitDocument,
    page: int,
    marker: str,
    text: str,
) -> None:
    normalized = re.sub(r"\s+", " ", text).strip()
    identity = (marker, normalized)
    if not normalized or identity in seen:
        return
    seen.add(identity)
    output.append(
        RawIndividualAchievementDocumentNote(
            marker=marker,
            source_text=_bounded_candidate(normalized, 2_000),
            locator=SourceLocator(
                source_url=document.source_url,
                page=page,
                field=f"document_note={marker}",
            ),
        )
    )


def _columns_from_header(header: list[str]) -> _TableColumns:
    normalized = [_normalize(value) for value in header]
    number = next(
        (index for index, value in enumerate(normalized) if value in {"№", "n", "номер"}),
        0,
    )
    document = next(
        (
            index
            for index, value in enumerate(normalized)
            if any(token in value for token in ("документ", "подтверж", "основан"))
        ),
        None,
    )
    points = next(
        (index for index, value in enumerate(normalized) if "балл" in value),
        None,
    )
    name = next(
        (
            index
            for index, value in enumerate(normalized)
            if index != number
            and index != document
            and index != points
            and value
        ),
        1,
    )
    points_start = points if points is not None else (document + 1 if document is not None else name + 1)
    return _TableColumns(
        number=number,
        name=name,
        document=document,
        points_start=points_start,
        headers=tuple(header),
    )


def _source_number(cells: list[str], number_index: int) -> int | None:
    if number_index >= len(cells):
        return None
    match = _ROW_NUMBER_RE.fullmatch(cells[number_index])
    return int(match.group(1)) if match is not None else None


def _merge_cells(physical_rows: list[tuple[int, list[str]]]) -> list[str]:
    column_count = max((len(cells) for _, cells in physical_rows), default=0)
    merged: list[str] = []
    for index in range(column_count):
        values = [cells[index].strip() for _, cells in physical_rows if index < len(cells) and cells[index].strip()]
        merged.append("\n".join(values))
    return merged


def _variant_cells(
    merged: list[str],
    columns: _TableColumns,
    name: str,
    required_document: str | None,
    variant: _PointVariant,
) -> list[str]:
    result = list(merged)
    if columns.name < len(result):
        result[columns.name] = name
    if columns.document is not None:
        while len(result) <= columns.document:
            result.append("")
        result[columns.document] = required_document or ""
    while len(result) <= columns.points_start:
        result.append("")
    result[columns.points_start] = " ".join(
        part for part in (variant.label, variant.points) if part
    )
    return result


def _metadata_int(values: object, index: int) -> int | None:
    if isinstance(values, (list, tuple)) and index < len(values):
        value = values[index]
        if isinstance(value, int) and value >= 1:
            return value
    return None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 1 else None


def _diagnostic(
    locator: SourceLocator,
    code: str,
    message: str,
) -> AdmissionBenefitParserDiagnostic:
    return AdmissionBenefitParserDiagnostic(
        code=code,
        stage="individual_achievements",
        message=message,
        severity="ambiguous",
        locator=locator,
    )


def _looks_like_header(row: list[str]) -> bool:
    if not row or _normalize(row[0]) not in {"№", "n", "номер"}:
        return False
    normalized = [_normalize(value) for value in row[1:]]
    has_name = any(
        any(token in value for token in ("наименование", "достиж", "вид достиж"))
        for value in normalized
    )
    has_points = any("балл" in value for value in normalized)
    return has_name and has_points


def _values(row: Any) -> list[str]:
    if isinstance(row, Mapping):
        if "cells" in row and isinstance(row["cells"], (list, tuple)):
            return [str(value or "").strip() for value in row["cells"]]
        return [str(value or "").strip() for value in row.values()]
    if isinstance(row, (list, tuple)):
        return [str(value or "").strip() for value in row]
    return []


def _combine_label(parts: Iterable[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip(" \t\n:;–—-")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _join(values: list[str]) -> str:
    return " | ".join(value for value in values if value)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _bounded_candidate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _policy_text(value: str) -> str | None:
    return value if any(token in _normalize(value) for token in ("сумм", "учитыва", "максимум", "не более", "одноврем")) else None


__all__ = ["parse_individual_achievement_tables"]
