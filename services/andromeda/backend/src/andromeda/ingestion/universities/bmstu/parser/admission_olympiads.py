from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import Field, HttpUrl

from andromeda.ingestion.contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawSourceSnapshot,
    SourceLocator,
)
from andromeda.ingestion.universities.bmstu.html import clean_text, parse_page
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import IngestRunId


class BmstuOlympiadProfileSource(ContractModel):
    """Source-backed mapping from an official olympiad profile to subjects."""

    olympiad_name: str = Field(min_length=1, max_length=512)
    profile_name: str = Field(min_length=1, max_length=256)
    corresponding_subjects: tuple[str, ...] = Field(min_length=1)
    rsosh_level: int | None = Field(default=None, strict=True, ge=1, le=3)
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    captured_at: datetime
    source_url: HttpUrl
    source_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_run_id: IngestRunId
    locator: SourceLocator
    source_title: str = Field(min_length=1, max_length=512)


class BmstuOlympiadProfileParseResult(ContractModel):
    source: BmstuOlympiadProfileSource | None = None
    diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()


def parse_olympiad_profile_source(
    snapshot: RawSourceSnapshot,
    *,
    source_run_id: IngestRunId,
    admission_year: int,
) -> BmstuOlympiadProfileParseResult:
    """Parse a minimized official extract or the official profile HTML.

    This parser only extracts claims present in the source.  It does not map
    an olympiad name to a subject from a local lookup table.
    """

    payload = _json_extract(snapshot)
    if payload is not None:
        expected = payload.get("expected")
        if isinstance(expected, dict):
            return _from_extract(snapshot, source_run_id, admission_year, expected, payload.get("locator"))

    try:
        text = snapshot.body.decode("utf-8")
    except UnicodeDecodeError:
        return _failed(snapshot, "profile_source_not_utf8", "official profile source is not UTF-8 text")

    page = parse_page(text, str(snapshot.requested_url))
    title = clean_text(page.soup.title.get_text(" ", strip=True) if page.soup.title else "")
    heading_node = page.soup.find("h1")
    heading = clean_text(heading_node.get_text(" ", strip=True) if heading_node is not None else "")
    visible_text = page.text
    olympiad_match = re.search(r"Олимпиада школьников\s+«([^»]+)»", title or visible_text, re.IGNORECASE)
    profile_match = re.search(r"профил(?:ю|ь)\s+«([^»]+)»", title, re.IGNORECASE)
    subject_match = re.search(
        r"Академическое соревнование по предмету\s*\(([^)]+)\)",
        visible_text,
        re.IGNORECASE,
    )
    level_match = re.search(r"Уровень Олимпиады РСОШ\s*[—-]\s*(\d)", visible_text, re.IGNORECASE)
    if olympiad_match is None or profile_match is None or subject_match is None:
        return _failed(
            snapshot,
            "profile_source_fields_unresolved",
            "official olympiad profile does not expose olympiad, profile and subject fields together",
        )
    subjects = _subjects(subject_match.group(1))
    if not subjects:
        return _failed(snapshot, "profile_source_subjects_empty", "official profile subject list is empty")
    locator = SourceLocator(source_url=snapshot.requested_url, field="profile=official;section=about")
    return BmstuOlympiadProfileParseResult(
        source=BmstuOlympiadProfileSource(
            olympiad_name=f"Олимпиада школьников «{clean_text(olympiad_match.group(1))}»",
            profile_name=clean_text(profile_match.group(1)),
            corresponding_subjects=subjects,
            rsosh_level=int(level_match.group(1)) if level_match else None,
            admission_year=admission_year,
            captured_at=snapshot.captured_at,
            source_url=snapshot.requested_url,
            source_snapshot_hash=snapshot.content_sha256,
            source_run_id=source_run_id,
            locator=locator,
            source_title=title or heading or str(snapshot.requested_url),
        )
    )


def _from_extract(
    snapshot: RawSourceSnapshot,
    source_run_id: IngestRunId,
    admission_year: int,
    expected: dict[str, object],
    raw_locator: object,
) -> BmstuOlympiadProfileParseResult:
    olympiad_name = _text(expected.get("olympiad_name"))
    profile_name = _text(expected.get("profile_name"))
    raw_subjects = expected.get("corresponding_subjects")
    subjects_list: list[str] = []
    if isinstance(raw_subjects, list):
        for item in raw_subjects:
            value = _text(item)
            if value:
                subjects_list.append(value.casefold())
    subjects = tuple(dict.fromkeys(subjects_list))
    if not olympiad_name or not profile_name or not subjects:
        return _failed(snapshot, "profile_extract_fields_unresolved", "official profile extract is incomplete")
    locator = SourceLocator(source_url=snapshot.requested_url, field=_locator_field(raw_locator))
    raw_level = expected.get("rsosh_level")
    level = raw_level if isinstance(raw_level, int) else None
    return BmstuOlympiadProfileParseResult(
        source=BmstuOlympiadProfileSource(
            olympiad_name=olympiad_name,
            profile_name=profile_name,
            corresponding_subjects=subjects,
            rsosh_level=level,
            admission_year=admission_year,
            captured_at=snapshot.captured_at,
            source_url=snapshot.requested_url,
            source_snapshot_hash=snapshot.content_sha256,
            source_run_id=source_run_id,
            locator=locator,
            source_title=f"Официальная страница профиля {profile_name}",
        )
    )


def _json_extract(snapshot: RawSourceSnapshot) -> dict[str, object] | None:
    try:
        value = json.loads(snapshot.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _subjects(value: str) -> tuple[str, ...]:
    parts = re.split(r"\s*(?:,|;|\s+или\s+)\s*", clean_text(value), flags=re.IGNORECASE)
    return tuple(dict.fromkeys(part.strip().casefold() for part in parts if part.strip()))


def _text(value: object) -> str | None:
    return clean_text(value) if isinstance(value, str) and clean_text(value) else None


def _locator_field(value: object) -> str:
    field = _text(value) or "official profile extract"
    return field[:128]


def _failed(
    snapshot: RawSourceSnapshot,
    code: str,
    message: str,
) -> BmstuOlympiadProfileParseResult:
    return BmstuOlympiadProfileParseResult(
        diagnostics=(
            AdmissionBenefitParserDiagnostic(
                code=code,
                stage="olympiad_profile",
                message=message,
                severity="warning",
                locator=SourceLocator(source_url=snapshot.requested_url),
            ),
        )
    )


__all__ = [
    "BmstuOlympiadProfileParseResult",
    "BmstuOlympiadProfileSource",
    "parse_olympiad_profile_source",
]
