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
_RESULT_COLUMN_RE = re.compile(r"побед|призер|призёр|winner|prize", re.IGNORECASE)
_HEADER_RE = re.compile(r"олимпиад|профил|побед|призер|призёр|уровен|предмет|направлен|право", re.IGNORECASE)
_NO_VALUE_RE = re.compile(r"не\s+предостав|не\s+да[её]т|нет|no", re.IGNORECASE)
_GRANT_STATUS_RE = re.compile(r"предоставля|не\s+да[её]т|нет|no", re.IGNORECASE)


def parse_benefit_tables(
    document: RawAdmissionBenefitDocument,
    tables: Iterable[Mapping[str, Any]],
) -> tuple[tuple[RawAdmissionBenefitRecord, ...], tuple[AdmissionBenefitParserDiagnostic, ...]]:
    """Convert extracted table rows into auditable raw candidates.

    This layer deliberately does not resolve a legal rule. It only preserves
    cells and emits typed candidates that a normalizer can accept or review.
    """

    records: list[RawAdmissionBenefitRecord] = []
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    document_scope_context: str | None = None
    for table_index, table in enumerate(tables, start=1):
        page = _positive_int(table.get("page")) or 1
        source_table = _positive_int(table.get("table")) or _positive_int(table.get("index")) or table_index
        raw_rows = table.get("rows") or table.get("raw_rows") or ()
        rows = [_row_values(row) for row in raw_rows if _row_values(row)]
        source_row_numbers = table.get("row_numbers") or ()
        source_pages = table.get("row_pages") or ()
        if not rows:
            continue
        headers, data_rows = _split_headers(rows)
        context_scope: str | None = document_scope_context
        carry: dict[int, str] = {}
        for row_number, row in enumerate(data_rows, start=1):
            row_text = _join(row)
            if not row_text:
                continue
            codes = _DIRECTION_CODE_RE.findall(row_text)
            if codes and _is_scope_context_row(row):
                context_scope = row_text
                document_scope_context = row_text
                continue
            values = _with_carry(row, carry, headers)
            row_text = _join(values)
            source_row = (
                source_row_numbers[row_number - 1]
                if row_number - 1 < len(source_row_numbers) and isinstance(source_row_numbers[row_number - 1], int)
                else row_number
            )
            source_page = (
                source_pages[row_number - 1]
                if row_number - 1 < len(source_pages) and isinstance(source_pages[row_number - 1], int)
                else page
            )
            locator = SourceLocator(source_url=document.source_url, page=source_page, row=source_row, field=f"table:{source_table}")
            candidates = _candidates(document.document_kind, headers, values, context_scope)
            result_types = _result_types(headers, values)
            if document.document_kind == "appendix_5_2" and not result_types:
                # The official 5.2 heading grants BVI to both winners and
                # prize-winners in one combined column.
                result_types = ("winner", "prize_winner")
            if not result_types:
                result_types = (None,)
                if not document.document_kind.startswith("official_"):
                    diagnostics.append(
                        AdmissionBenefitParserDiagnostic(
                            code="ambiguous_table_row",
                            stage="table",
                            message="winner/prize-winner result cell could not be identified",
                            severity="ambiguous",
                            locator=locator,
                        )
                    )
            cells = tuple(
                RawAdmissionBenefitCell(
                    header=_bounded_cell_header(headers[index] if index < len(headers) else f"column_{index + 1}"),
                    value=value,
                )
                for index, value in enumerate(values)
                if value
            )
            for result_type in result_types:
                result_candidates = list(candidates)
                if result_type is not None:
                    result_candidates.append(RawAdmissionBenefitCandidate(field="result_type", value=result_type))
                    result_candidates.append(
                        RawAdmissionBenefitCandidate(
                            field="benefit_granted",
                            value=_result_granted(headers, values, result_type),
                        )
                    )
                record_id = f"raw-admission-benefit:{document.source_snapshot_hash[:16]}:{page}:{source_table}:{row_number}:{result_type or 'unknown'}"
                records.append(
                    RawAdmissionBenefitRecord(
                        record_id=record_id,
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
                        cells=cells,
                        normalized_candidates=tuple(result_candidates),
                        diagnostics=tuple(diagnostic for diagnostic in diagnostics if diagnostic.locator == locator),
                        parser_version=document.parser_version,
                    )
                )
    return tuple(records), tuple(diagnostics)


def _split_headers(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    index = 0
    while index < len(rows) and index < 3:
        if index > 0 and (rows[index][0].strip() if rows[index] else ""):
            break
        if index > 0 and not _looks_like_header(rows[index]):
            break
        if any(value for value in rows[index]):
            if not header:
                header = list(rows[index])
            else:
                header = [f"{header[column]} {rows[index][column]}".strip() if column < len(rows[index]) and rows[index][column] else header[column] for column in range(max(len(header), len(rows[index])))]
        index += 1
    if not header:
        header = [f"column_{column + 1}" for column in range(max((len(row) for row in rows), default=1))]
        index = 0
    header = [value.strip() or f"column_{column + 1}" for column, value in enumerate(header)]
    return header, rows[index:]


def _bounded_cell_header(header: str) -> str:
    """Keep extracted PDF headers within the raw-cell contract boundary.

    Some official BMSTU PDFs repeat merged multi-line headings and pdfplumber
    returns a value longer than the 512-character cell limit.  The complete
    heading remains available in the unbounded local ``headers`` list while
    candidates are extracted; the persisted cell projection only needs a
    deterministic bounded label, while the source snapshot remains available
    for full-fidelity audit.
    """
    if len(header) <= 512:
        return header
    return f"{header[:509]}..."


def _candidates(document_kind: str, headers: list[str], values: list[str], context_scope: str | None) -> list[RawAdmissionBenefitCandidate]:
    result: list[RawAdmissionBenefitCandidate] = []
    for index, value in enumerate(values):
        if not value:
            continue
        header = headers[index] if index < len(headers) else f"column_{index + 1}"
        normalized_header = _normalize(header)
        if "олимпиад" in normalized_header and index == 1:
            result.append(RawAdmissionBenefitCandidate(field="olympiad_name", value=value))
        elif "профил" in normalized_header and index in {2, 3}:
            result.append(RawAdmissionBenefitCandidate(field="profile_name", value=value))
        elif "уровен" in normalized_header:
            result.append(RawAdmissionBenefitCandidate(field="rsosh_level", value=value))
        elif document_kind == "appendix_5_3" and "профильные общеобразовательные предмет" in normalized_header:
            result.append(RawAdmissionBenefitCandidate(field="target_subject", value=value))
            result.append(RawAdmissionBenefitCandidate(field="confirmation_subject", value=value))
            result.append(RawAdmissionBenefitCandidate(field="confirmation_text", value=value))
        elif "подтверж" in normalized_header or "егэ" in normalized_header:
            result.append(RawAdmissionBenefitCandidate(field="confirmation_text", value=value))
            if "профильные общеобразовательные предмет" in normalized_header:
                result.append(RawAdmissionBenefitCandidate(field="confirmation_subject", value=value))
            score = _confirmation_score_from_header(header)
            if score is not None:
                result.append(RawAdmissionBenefitCandidate(field="confirmation_min_score", value=score))
        elif "направлен" in normalized_header or "специальност" in normalized_header:
            result.extend(_scope_candidates(value))
    if document_kind == "appendix_5_1":
        result.append(RawAdmissionBenefitCandidate(field="benefit_type", value="bvi"))
    elif document_kind == "appendix_5_3":
        result.append(RawAdmissionBenefitCandidate(field="benefit_type", value="one_hundred_points"))
    elif document_kind in {"appendix_5_4", "appendix_5_5"}:
        result.append(RawAdmissionBenefitCandidate(field="route", value=document_kind))
    elif document_kind == "appendix_5_2":
        result.append(RawAdmissionBenefitCandidate(field="benefit_type", value="bvi"))
        if values:
            scope_text = values[-1]
            if scope_text:
                result.append(RawAdmissionBenefitCandidate(field="scope_text", value=scope_text))
                normalized_scope = _normalize(scope_text)
                if "все нп" in normalized_scope and "кф" in normalized_scope and "мф" in normalized_scope:
                    result.extend(
                        (
                            RawAdmissionBenefitCandidate(field="scope_mode", value="only"),
                            RawAdmissionBenefitCandidate(field="scope_campus_id", value="campus:bmstu-kaluga"),
                            RawAdmissionBenefitCandidate(field="scope_campus_id", value="campus:bmstu-mytishchi"),
                        )
                    )
                elif "все" in normalized_scope:
                    result.append(RawAdmissionBenefitCandidate(field="scope_mode", value="all"))
        result.append(RawAdmissionBenefitCandidate(field="benefit_granted", value="yes"))
    if context_scope:
        result.extend(_scope_candidates(context_scope))
    for header in headers:
        score = _confirmation_score_from_header(header)
        if score is not None:
            result.append(RawAdmissionBenefitCandidate(field="confirmation_min_score", value=score))
    return result


def _confirmation_score_from_header(header: str) -> str | None:
    """Return the confirmation threshold, not the granted 100-point value.

    Appendix 5.3 headers mention both values (``100 points ... confirmed by
    75 EGE points``).  The last score is the confirmation threshold.  Keeping
    this extraction here prevents the parser from accidentally treating the
    benefit value as the applicant's required EGE score.
    """

    normalized = _normalize(header)
    if not any(token in normalized for token in ("подтверж", "егэ")):
        return None
    scores = re.findall(r"\b(\d{2,3})\s*бал", header, re.IGNORECASE)
    return scores[-1] if scores else None


def _scope_candidates(value: str) -> list[RawAdmissionBenefitCandidate]:
    normalized = _normalize(value)
    codes = _DIRECTION_CODE_RE.findall(value)
    if not codes:
        if "все" in normalized or "all" in normalized:
            return [RawAdmissionBenefitCandidate(field="scope_text", value=value)]
        names = tuple(
            part.strip()
            for part in re.split(r"\s*,\s*", value)
            if part.strip()
        )
        return [
            RawAdmissionBenefitCandidate(field="scope_mode", value="only"),
            *(RawAdmissionBenefitCandidate(field="scope_direction_name", value=name) for name in names),
            RawAdmissionBenefitCandidate(field="scope_text", value=value),
        ]
    if any(marker in normalized for marker in ("кроме", "за исключением", "except", "excluding")):
        mode = "all_except"
    elif any(marker in normalized for marker in ("только", "only")):
        mode = "only"
    else:
        mode = "only"
    return [
        RawAdmissionBenefitCandidate(field="scope_mode", value=mode),
        *(RawAdmissionBenefitCandidate(field="scope_direction_code", value=code) for code in codes),
        RawAdmissionBenefitCandidate(field="scope_text", value=value),
    ]


def _result_types(headers: list[str], values: list[str]) -> tuple[str | None, ...]:
    result: list[str] = []
    for index, header in enumerate(headers):
        if index >= len(values) or not _RESULT_COLUMN_RE.search(header):
            continue
        normalized = _normalize(header)
        if "побед" in normalized or "winner" in normalized:
            result.append("winner")
        if "призер" in normalized or "призёр" in normalized or "prize" in normalized:
            result.append("prize_winner")
    if result:
        return tuple(dict.fromkeys(result))
    text = _normalize(_join(values))
    inferred: list[str] = []
    if "победител" in text or "winner" in text:
        inferred.append("winner")
    if "призер" in text or "призёр" in text or "prize" in text:
        inferred.append("prize_winner")
    if not inferred and len(values) >= 2 and all(_GRANT_STATUS_RE.search(value) for value in values[-2:]):
        # Continuation pages of the official BMSTU tables omit the repeated
        # header. Their final two cells retain the documented winner/prize
        # column order from the first page.
        return "winner", "prize_winner"
    return tuple(dict.fromkeys(inferred))


def _result_granted(headers: list[str], values: list[str], result_type: str) -> str:
    for index, header in enumerate(headers):
        normalized = _normalize(header)
        if result_type == "winner" and "побед" not in normalized and "winner" not in normalized:
            continue
        if result_type == "prize_winner" and not any(token in normalized for token in ("призер", "призёр", "prize")):
            continue
        if index < len(values):
            return "no" if _NO_VALUE_RE.search(values[index]) else "yes"
    if len(values) >= 2 and all(_GRANT_STATUS_RE.search(value) for value in values[-2:]):
        index = -2 if result_type == "winner" else -1
        return "no" if _NO_VALUE_RE.search(values[index]) else "yes"
    return "unknown"


def _with_carry(row: list[str], carry: dict[int, str], headers: list[str]) -> list[str]:
    values = list(row) + [""] * max(0, len(headers) - len(row))
    for index in range(min(4, len(values))):
        if values[index]:
            carry[index] = values[index]
        elif index in carry:
            values[index] = carry[index]
    return values[: max(len(headers), len(values))]


def _looks_like_header(row: list[str]) -> bool:
    return bool(_HEADER_RE.search(_join(row)))


def _looks_like_data_row(row: list[str], headers: list[str]) -> bool:
    text = _join(row)
    return bool(_DIRECTION_CODE_RE.search(text) or re.match(r"^\d{1,4}$", row[0] if row else "") or len(text) > 50)


def _is_scope_context_row(row: list[str]) -> bool:
    """Recognize a PDF row that introduces scope for following rows."""
    first_value = next((value for value in row if value), "")
    normalized_first = _normalize(first_value)
    return bool(_DIRECTION_CODE_RE.search(_join(row))) and "направлен" in normalized_first and not re.match(r"^\d{1,4}$", first_value)


def _row_values(row: Any) -> list[str]:
    if isinstance(row, Mapping):
        return [str(value).strip() for value in row.values() if value is not None and str(value).strip()]
    if isinstance(row, (list, tuple)):
        return [str(value or "").strip() for value in row]
    return []


def _join(values: list[str]) -> str:
    return " | ".join(value for value in values if value)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 1 else None


__all__ = ["parse_benefit_tables"]
