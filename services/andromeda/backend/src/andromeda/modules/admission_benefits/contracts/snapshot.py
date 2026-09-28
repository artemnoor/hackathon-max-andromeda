"""Canonical admission-benefit snapshot independent from ingestion adapters."""

from __future__ import annotations

from pydantic import Field, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import UniversityId
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference

from .coverage import AdmissionBenefitCoverage
from .public import (
    AdmissionBenefitRule,
    IndividualAchievementPolicy,
    Olympiad,
    OlympiadProfile,
)


class AdmissionBenefitsSnapshot(ContractModel):
    """Versioned canonical projection for one university and admission year."""

    university_id: UniversityId | None = None
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    sources: tuple[SourceAttribution, ...] = ()
    olympiads: tuple[Olympiad, ...] = ()
    olympiad_profiles: tuple[OlympiadProfile, ...] = ()
    benefit_rules: tuple[AdmissionBenefitRule, ...] = ()
    individual_achievement_policy: IndividualAchievementPolicy | None = None
    coverage: AdmissionBenefitCoverage
    source_gaps: tuple[SourceGapReference, ...] = ()

    @model_validator(mode="after")
    def validate_source_evidence(self) -> AdmissionBenefitsSnapshot:
        if not self.sources and not self.source_gaps:
            raise ValueError(
                "an admission-benefit snapshot without sources must retain a source gap"
            )
        return self


__all__ = ["AdmissionBenefitsSnapshot"]
