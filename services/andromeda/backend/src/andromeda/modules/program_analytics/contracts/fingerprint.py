"""Reusable curriculum fingerprint contracts.

These contracts are intentionally independent from proftest.  Proftest keeps
compatibility imports, while analytics/recommendations can consume the same
source-backed representation.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight
from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.enums import AssessmentType
from andromeda.shared.contracts.ids import Credits, HourCount, NonEmptyText, ProgramCode, ProgramId, Semester, ShortText
from andromeda.shared.contracts.provenance import SourceAttribution, SourceGapReference


ZERO = Decimal("0")
ONE = Decimal("1")


class ActivityCode(StrEnum):
    ANALYTICAL = "analytical"
    SOFTWARE_CREATION = "software_creation"
    SYSTEM_DESIGN = "system_design"
    RESEARCH = "research"
    PHYSICAL_ENGINEERING = "physical_engineering"
    COMMUNICATION = "communication"
    CREATIVE = "creative"
    BUSINESS = "business"
    DATA = "data"


class CurriculumEvidence(ContractModel):
    source_name: NonEmptyText
    normalized_name: ShortText
    hours: HourCount
    credits: Credits | None = None
    semester: Semester | None = None
    assessment_types: tuple[AssessmentType, ...] | None = None
    workload: Decimal = Field(strict=True, ge=ZERO)
    area_weights: tuple[DisciplineAreaWeight, ...] = Field(min_length=1)
    provenance: tuple[SourceAttribution, ...] = ()
    source_gaps: tuple[SourceGapReference, ...] = ()

    @model_validator(mode="after")
    def validate_area_weights(self) -> Self:
        if sum((weight.weight for weight in self.area_weights), ZERO) != ONE:
            raise ValueError("evidence area weights must sum to one")
        return self


class DistinctiveSubject(ContractModel):
    source_name: NonEmptyText
    normalized_name: ShortText
    primary_area: DisciplineAreaCode
    workload: Decimal = Field(strict=True, ge=ZERO)
    share: Decimal = Field(strict=True, ge=ZERO, le=ONE, max_digits=7, decimal_places=4)
    rarity: Decimal = Field(strict=True, ge=ZERO, le=ONE, max_digits=7, decimal_places=4)
    distinctiveness: Decimal = Field(strict=True, ge=ZERO, le=ONE, max_digits=7, decimal_places=4)


class ProgramFingerprint(ContractModel):
    """Legacy-compatible analytical fingerprint owned by program analytics."""

    program_id: ProgramId
    program_code: ProgramCode
    program_name: NonEmptyText
    basis: Literal["hours", "credits"]
    total_hours: int = Field(strict=True, ge=0)
    total_credits: Decimal = Field(strict=True, ge=ZERO)
    total_workload: Decimal = Field(strict=True, ge=ZERO)
    area_hours: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    area_share: dict[DisciplineAreaCode, Decimal] = Field(default_factory=dict)
    semester_distribution: dict[str, Decimal] = Field(default_factory=dict)
    activity_signals: dict[ActivityCode, Decimal] = Field(default_factory=dict)
    evidence: tuple[CurriculumEvidence, ...] = ()
    distinctive_subjects: tuple[DistinctiveSubject, ...] = ()
    provenance: tuple[SourceAttribution, ...] = ()
    source_gaps: tuple[SourceGapReference, ...] = ()

    @model_validator(mode="after")
    def validate_vectors(self) -> Self:
        if self.total_workload > ZERO:
            for name, vector in (
                ("area_share", self.area_share),
                ("semester_distribution", self.semester_distribution),
                ("activity_signals", self.activity_signals),
            ):
                if not vector or abs(sum(vector.values(), ZERO) - ONE) > Decimal("0.001"):
                    raise ValueError(f"{name} must sum to one for a non-empty fingerprint")
        if self.basis == "hours" and self.total_workload != Decimal(self.total_hours):
            raise ValueError("hours basis must use total_hours as total_workload")
        if self.basis == "credits" and self.total_workload != self.total_credits:
            raise ValueError("credits basis must use total_credits as total_workload")
        return self


__all__ = ["ActivityCode", "CurriculumEvidence", "DistinctiveSubject", "ONE", "ProgramFingerprint", "ZERO"]
