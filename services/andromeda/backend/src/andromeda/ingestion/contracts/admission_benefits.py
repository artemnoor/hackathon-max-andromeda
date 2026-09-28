"""Canonical ingestion envelope for university admission-benefit data."""

from __future__ import annotations

from pydantic import Field

from ...modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
)
from ...modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    IndividualAchievementPolicy,
    Olympiad,
    OlympiadProfile,
)
from ...modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot as CanonicalAdmissionBenefitsSnapshot,
)
from ...shared.contracts.provenance import SourceAttribution, SourceGapReference
from .raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitCandidate,
    RawAdmissionBenefitCell,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
    RawAdmissionBenefitRecordKind,
    RawAdmissionConfirmationThreshold,
    RawConfirmationThresholdCategory,
    RawIndividualAchievementDocumentNote,
    RawIndividualAchievementRecord,
)


class AdmissionBenefitsSnapshot(CanonicalAdmissionBenefitsSnapshot):
    """Partial or complete canonical projection for one university/year."""

    admission_year: int = Field(strict=True, ge=2000, le=2100)
    sources: tuple[SourceAttribution, ...] = ()
    olympiads: tuple[Olympiad, ...] = ()
    olympiad_profiles: tuple[OlympiadProfile, ...] = ()
    benefit_rules: tuple[AdmissionBenefitRule, ...] = ()
    individual_achievement_policy: IndividualAchievementPolicy | None = None
    coverage: AdmissionBenefitCoverage
    source_gaps: tuple[SourceGapReference, ...] = ()
    diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()


__all__ = [
    "AdmissionBenefitCoverage",
    "AdmissionBenefitCoverageStatus",
    "AdmissionBenefitParserDiagnostic",
    "AdmissionBenefitsSnapshot",
    "RawAdmissionBenefitCandidate",
    "RawAdmissionBenefitCell",
    "RawAdmissionBenefitDocument",
    "RawAdmissionBenefitRecord",
    "RawAdmissionBenefitRecordKind",
    "RawAdmissionConfirmationThreshold",
    "RawConfirmationThresholdCategory",
    "RawIndividualAchievementDocumentNote",
    "RawIndividualAchievementRecord",
]
