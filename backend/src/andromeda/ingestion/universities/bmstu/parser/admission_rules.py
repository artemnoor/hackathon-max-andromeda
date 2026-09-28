"""Deterministic extraction of cross-cutting admission-rule policies."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from pydantic import HttpUrl

from andromeda.ingestion.contracts.raw import (
    RawAdmissionConfirmationThreshold,
    RawConfirmationThresholdCategory,
    RawSourceSnapshot,
    SourceLocator,
)
from andromeda.shared.contracts.base import ContractModel

from ..pdf import extract_pdf_pages_text, is_pdf


class BmstuAdmissionRulePolicy(ContractModel):
    """Typed facts shared by olympiad rules, with source wording preserved."""

    olympiad_result_max_age_years: int | None = None
    olympiad_result_validity_text: str | None = None
    olympiad_confirmation_min_score: Decimal | None = None
    olympiad_confirmation_text: str | None = None
    confirmation_thresholds: tuple[RawAdmissionConfirmationThreshold, ...] = ()
    validity_locator: SourceLocator | None = None


def parse_admission_rule_policy(snapshot: RawSourceSnapshot) -> BmstuAdmissionRulePolicy | None:
    """Parse policy facts from the official 2026 Rules snapshot.

    Fixture extracts are accepted only when they carry explicitly extracted
    fields.  Live PDFs are read through the existing bounded PDF text policy;
    no legal defaults are applied when the source wording is absent.
    """

    payload = _json_payload(snapshot.body)
    if payload is not None:
        extracted_pages = payload.get("text_layer_pages")
        if isinstance(extracted_pages, list):
            pages = tuple(
                (item.get("page"), item.get("text"))
                for item in extracted_pages
                if isinstance(item, dict)
            )
            parsed = _from_text_pages(snapshot, pages)
            if parsed is not None:
                return parsed
        return _from_json(payload, snapshot)
    if not is_pdf(snapshot.body, snapshot.content_type, str(snapshot.requested_url)):
        return None
    pages = tuple(enumerate(extract_pdf_pages_text(snapshot.body), start=1))
    return _from_text_pages(snapshot, pages)


def _json_payload(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _from_json(
    payload: dict[str, Any], snapshot: RawSourceSnapshot
) -> BmstuAdmissionRulePolicy | None:
    raw_age = payload.get("olympiad_result_max_age_years")
    raw_score = payload.get("olympiad_confirmation_min_score")
    age = raw_age if isinstance(raw_age, int) and raw_age >= 0 else None
    score: Decimal | None = None
    if isinstance(raw_score, (int, str)) and not isinstance(raw_score, bool):
        try:
            score = Decimal(str(raw_score))
        except InvalidOperation:
            score = None
    validity_text = payload.get("olympiad_result_validity_text")
    confirmation_text = payload.get("olympiad_confirmation_text")
    thresholds: list[RawAdmissionConfirmationThreshold] = []
    raw_thresholds = payload.get("confirmation_thresholds")
    if isinstance(raw_thresholds, list):
        for index, raw_threshold in enumerate(raw_thresholds, start=1):
            parsed = _json_threshold(raw_threshold, payload, snapshot, index)
            if parsed is not None:
                thresholds.append(parsed)
    if not thresholds and score is not None:
        excerpt = payload.get("excerpt")
        source_text = confirmation_text if isinstance(confirmation_text, str) and confirmation_text.strip() else str(excerpt or "")
        if source_text:
            thresholds.append(
                RawAdmissionConfirmationThreshold(
                    minimum_score=score,
                    applicant_category=RawConfirmationThresholdCategory.GENERAL,
                    exam_kinds=("ege",),
                    source_text=source_text,
                    locator=_json_locator(
                        payload.get("locator"),
                        snapshot.requested_url,
                        "section=1.12",
                    ),
                )
            )
    if age is None and score is None and not thresholds:
        return None
    return BmstuAdmissionRulePolicy(
        olympiad_result_max_age_years=age,
        olympiad_result_validity_text=validity_text if isinstance(validity_text, str) and validity_text.strip() else None,
        olympiad_confirmation_min_score=score,
        olympiad_confirmation_text=confirmation_text if isinstance(confirmation_text, str) and confirmation_text.strip() else None,
        confirmation_thresholds=tuple(thresholds),
        validity_locator=_json_locator(payload.get("locator"), snapshot.requested_url, "section=1.11"),
    )


def _json_threshold(
    raw: object,
    payload: dict[str, Any],
    snapshot: RawSourceSnapshot,
    index: int,
) -> RawAdmissionConfirmationThreshold | None:
    if not isinstance(raw, dict):
        return None
    try:
        score = Decimal(str(raw["minimum_score"]))
        raw_category = str(raw.get("applicant_category", "unknown"))
        category = (
            RawConfirmationThresholdCategory.GENERAL
            if raw_category == "general"
            else RawConfirmationThresholdCategory.TERRITORIAL_EXCEPTION
            if raw_category in {
                "territorial_exception",
                "graduates_from_DNR_LNR_Zaporizhzhia_Kherson",
            }
            else RawConfirmationThresholdCategory.UNKNOWN
        )
        raw_kinds = raw.get("exam_kinds", ["ege"])
        if not isinstance(raw_kinds, list):
            return None
        exam_kinds = tuple(
            kind for kind in raw_kinds if kind in {"ege", "internal_exam", "unknown"}
        )
        if not exam_kinds:
            exam_kinds = ("unknown",)
        excerpt = raw.get("source_text") or payload.get("excerpt") or payload.get("olympiad_confirmation_text")
        if not isinstance(excerpt, str) or not excerpt.strip():
            return None
        return RawAdmissionConfirmationThreshold(
            minimum_score=score,
            applicant_category=category,
            exam_kinds=exam_kinds,
            source_text=excerpt,
            locator=_json_locator(
                raw.get("locator") or payload.get("locator"),
                snapshot.requested_url,
                f"section=1.12;threshold={index}",
            ),
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return None


def _json_locator(value: object, url: HttpUrl, default_field: str) -> SourceLocator:
    page: int | None = None
    field = default_field
    if isinstance(value, str):
        parts = value.split(";")
        for part in parts:
            if part.startswith("page=") and part[5:].isdigit():
                page = int(part[5:])
            elif part.startswith("section="):
                field = part
    return SourceLocator(source_url=url, page=page, field=field)


def _from_text_pages(
    snapshot: RawSourceSnapshot,
    pages: tuple[tuple[object, object], ...],
) -> BmstuAdmissionRulePolicy | None:
    age_years: int | None = None
    validity_text: str | None = None
    validity_locator: SourceLocator | None = None
    thresholds: list[RawAdmissionConfirmationThreshold] = []
    for raw_page, raw_text in pages:
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        page_number = raw_page if isinstance(raw_page, int) and raw_page >= 1 else None
        page_text = _compact(raw_text)
        validity_match = re.search(
            r"результат(?:ы|а)?олимпиад\w*действительн\w*.*?втечение(четырех|4)лет[,]?следующихзагодомпроведенияолимпиад\w*\.",
            page_text,
        )
        if validity_match is not None:
            age_years = 4
            raw_validity_match = re.search(
                r"Результаты олимпиады действительны.*?проведения олимпиады\.",
                raw_text,
                re.IGNORECASE | re.DOTALL,
            )
            validity_text = (
                re.sub(r"\s+", " ", raw_validity_match.group(0)).strip()
                if raw_validity_match is not None
                else "Результаты олимпиады действительны в течение четырех следующих лет после года проведения олимпиады."
            )
            validity_locator = SourceLocator(
                source_url=snapshot.requested_url,
                page=page_number,
                field="section=1.11",
            )
        section = _section_text(raw_text, "1.12", "1.13")
        if section is None:
            continue
        compact_section = _compact(section)
        if "егэ" in compact_section:
            exam_kinds: tuple[Literal["ege", "internal_exam", "unknown"], ...] = (
                ("ege", "internal_exam")
                if re.search(r"егэили(?:вступительн|внутренн)", compact_section)
                else ("ege",)
            )
        elif re.search(r"(?:вступительн|внутренн).*испытан", compact_section):
            exam_kinds = ("internal_exam",)
        else:
            exam_kinds = ("unknown",)
        threshold_matches = tuple(
            re.finditer(
                r"(?:не\s+ниже|не\s+менее)\s*(\d{2,3})\s*балл\w*",
                section,
                re.IGNORECASE,
            )
        )
        excerpt_start = 0
        for match in threshold_matches:
            prefix = _compact(section[: match.start()])
            is_exception = "длявыпускниковстерриторий" in prefix[-500:]
            category = (
                RawConfirmationThresholdCategory.TERRITORIAL_EXCEPTION
                if is_exception
                else RawConfirmationThresholdCategory.GENERAL
            )
            thresholds.append(
                RawAdmissionConfirmationThreshold(
                    minimum_score=Decimal(match.group(1)),
                    applicant_category=category,
                    exam_kinds=exam_kinds,
                    source_text=re.sub(
                        r"\s+", " ", section[excerpt_start : match.end()]
                    ).strip(),
                    locator=SourceLocator(
                        source_url=snapshot.requested_url,
                        page=page_number,
                        field="section=1.12",
                    ),
                )
            )
            excerpt_start = match.end()
    if age_years is None and not thresholds:
        return None
    general_score = next(
        (
            threshold.minimum_score
            for threshold in thresholds
            if threshold.applicant_category is RawConfirmationThresholdCategory.GENERAL
        ),
        None,
    )
    return BmstuAdmissionRulePolicy(
        olympiad_result_max_age_years=age_years,
        olympiad_result_validity_text=validity_text,
        olympiad_confirmation_min_score=general_score,
        olympiad_confirmation_text=(thresholds[0].source_text if thresholds else None),
        confirmation_thresholds=tuple(thresholds),
        validity_locator=validity_locator,
    )


def _section_text(text: str, start: str, end: str) -> str | None:
    match = re.search(
        rf"(?<!\d){re.escape(start)}\.\s*(.+?)(?<!\d){re.escape(end)}\.\s*",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match is not None else None


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold().replace("ё", "е"))


__all__ = ["BmstuAdmissionRulePolicy", "parse_admission_rule_policy"]
