"""Field-level references from knowledge candidates to captured evidence."""

from __future__ import annotations

from pydantic import Field, HttpUrl, field_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import SourceHash

from .sources import SourceId, SourceObservationId


class EvidenceLocator(ContractModel):
    page: int | None = Field(default=None, strict=True, ge=1)
    table: str | None = Field(default=None, min_length=1, max_length=256)
    row: int | None = Field(default=None, strict=True, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=512)
    field: str | None = Field(default=None, min_length=1, max_length=128)
    record_key: str | None = Field(default=None, min_length=1, max_length=256)


class EvidenceRef(ContractModel):
    source_id: SourceId
    source_observation_id: SourceObservationId
    snapshot_sha256: SourceHash
    source_url: HttpUrl
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    inferred: bool = False

    @field_validator("source_url")
    @classmethod
    def require_safe_https_source_url(cls, value: HttpUrl) -> HttpUrl:
        if (
            value.scheme != "https"
            or value.username
            or value.password
            or value.port not in (None, 443)
            or value.query
            or value.fragment
        ):
            raise ValueError("evidence URL must be HTTPS without credentials, query, or fragment")
        return value

    @property
    def has_structured_locator(self) -> bool:
        return any(
            (
                self.locator.page,
                self.locator.table,
                self.locator.row,
                self.locator.section,
                self.locator.field,
                self.locator.record_key,
            )
        )


__all__ = ["EvidenceLocator", "EvidenceRef"]
