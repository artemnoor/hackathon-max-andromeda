from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, HttpUrl

from .base import ContractModel
from .enums import SourceKind
from .ids import IngestRunId, ShortText, SourceHash, UniversityId


class GapSeverity(StrEnum):
    BLOCKING = "blocking"
    DEGRADABLE = "degradable"
    INFORMATIONAL = "informational"


class SourceAttribution(ContractModel):
    kind: SourceKind
    url: HttpUrl
    captured_at: datetime
    content_sha256: SourceHash
    locator: ShortText | None = None
    university_id: UniversityId | None = None
    run_id: IngestRunId | None = None
    field: ShortText | None = None
    record_key: ShortText | None = None
    inferred: bool = False


class SourceGapReference(ContractModel):
    """Safe field-level gap exposed to application consumers."""

    code: ShortText
    severity: GapSeverity
    message: ShortText
    source_url: HttpUrl | None = None
    field: ShortText | None = None
    record_key: ShortText | None = None
    can_continue: bool = True


__all__ = ["GapSeverity", "SourceAttribution", "SourceGapReference"]
