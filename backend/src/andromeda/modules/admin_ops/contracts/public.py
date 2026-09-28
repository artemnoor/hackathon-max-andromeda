from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass

from pydantic import Field

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import IngestRunId

from ..domain.entities import IngestionRunDetail, IngestionRunStatus, IngestionRunSummary


class IngestionRunFilters(ContractModel):
    status: IngestionRunStatus | None = None
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class IngestionRetrySource(StrEnum):
    BMSTU_FIXTURE = "bmstu_fixture"
    BMSTU_LIVE = "bmstu_live"
    HSE_FIXTURE = "hse_fixture"
    HSE_LIVE = "hse_live"


@dataclass(frozen=True, slots=True)
class IngestionRetryProfile:
    source: IngestionRetrySource
    university: str
    mode: str
    source_revision: str
    configuration_version: str

    @property
    def profile_id(self) -> str:
        return f"{self.university}:{self.mode}:{self.source_revision}:{self.configuration_version}"


_RETRY_PROFILES = {
    IngestionRetrySource.BMSTU_FIXTURE: IngestionRetryProfile(
        source=IngestionRetrySource.BMSTU_FIXTURE,
        university="bmstu",
        mode="fixture",
        source_revision="fixture-manifest-v1",
        configuration_version="mvp023.v1",
    ),
    IngestionRetrySource.BMSTU_LIVE: IngestionRetryProfile(
        source=IngestionRetrySource.BMSTU_LIVE,
        university="bmstu",
        mode="live",
        source_revision="official-live-v1",
        configuration_version="mvp023.v1",
    ),
    IngestionRetrySource.HSE_FIXTURE: IngestionRetryProfile(
        source=IngestionRetrySource.HSE_FIXTURE,
        university="hse",
        mode="fixture",
        source_revision="fixture-manifest-v1",
        configuration_version="mvp023.v1",
    ),
    IngestionRetrySource.HSE_LIVE: IngestionRetryProfile(
        source=IngestionRetrySource.HSE_LIVE,
        university="hse",
        mode="live",
        source_revision="official-live-v1",
        configuration_version="mvp023.v1",
    ),
}


def ingestion_retry_profile(source: IngestionRetrySource) -> IngestionRetryProfile:
    return _RETRY_PROFILES[source]


class IngestionRetryRequest(ContractModel):
    source: IngestionRetrySource = IngestionRetrySource.BMSTU_FIXTURE
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")
    retry_of_run_id: IngestRunId | None = None

    @property
    def profile(self) -> IngestionRetryProfile:
        return ingestion_retry_profile(self.source)


__all__ = [
    "IngestionRunDetail",
    "IngestionRunFilters",
    "IngestionRunStatus",
    "IngestionRunSummary",
    "IngestionRetryRequest",
    "IngestionRetryProfile",
    "IngestionRetrySource",
    "ingestion_retry_profile",
]
