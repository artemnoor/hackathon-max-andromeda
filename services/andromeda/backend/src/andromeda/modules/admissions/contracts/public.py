"""Stable contracts shared by the admissions module and its adapters."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, HttpUrl, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import (
    AdmissionCampusId,
    AdmissionExamChoiceGroupId,
    EducationYear,
    NonEmptyText,
    ProgramId,
    ShortText,
    SourceHash,
)

from .admission_cycles import (
    AdmissionCycle,
    AdmissionCycleId,
    AdmissionCycleResolution,
    AdmissionCycleResolutionStatus,
    AdmissionCycleState,
    InclusiveDateWindow,
    admission_cycle_id,
)

ZERO = Decimal(0)


class StudyForm(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    EVENING = "evening"
    ONLINE = "online"
    UNKNOWN = "unknown"


class FundingType(StrEnum):
    BUDGET = "budget"
    PAID = "paid"
    TARGETED = "targeted"
    UNKNOWN = "unknown"


class AdmissionScope(StrEnum):
    PROGRAM = "program"
    DIRECTION = "direction"


class QuotaType(StrEnum):
    SPECIAL = "special"
    SEPARATE = "separate"
    TARGETED = "targeted"
    OTHER = "other"


class PassingScoreType(StrEnum):
    BUDGET = "budget"
    PAID = "paid"
    AVERAGE = "average"
    OTHER = "other"


class AdmissionCompetitionType(StrEnum):
    GENERAL = "general"
    SPECIAL_QUOTA = "special_quota"
    SEPARATE_QUOTA = "separate_quota"
    TARGETED = "targeted"
    BVI = "bvi"
    OTHER = "other"


class PassingScoreStatus(StrEnum):
    NUMERIC = "numeric"
    BVI = "bvi"


class AdmissionProvenance(ContractModel):
    source_kind: ShortText
    source_url: HttpUrl
    captured_at: datetime
    content_sha256: SourceHash
    locator: ShortText | None = None
    source_name: NonEmptyText | None = None
    university_id: str | None = None
    run_id: str | None = None
    field: ShortText | None = None
    record_key: ShortText | None = None
    inferred: bool = False


class ExamRequirement(ContractModel):
    subject: NonEmptyText
    source_name: NonEmptyText
    minimum_score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=Decimal(100), max_digits=5, decimal_places=2)
    is_choice: bool = False
    is_required: bool = True
    choice_group_id: AdmissionExamChoiceGroupId | None = None
    choice_group_min: int | None = Field(default=None, strict=True, ge=1, le=20)
    choice_group_max: int | None = Field(default=None, strict=True, ge=1, le=20)
    provenance: AdmissionProvenance

    @model_validator(mode="after")
    def validate_choice_metadata(self) -> ExamRequirement:
        if self.choice_group_id is None and (
            self.choice_group_min is not None or self.choice_group_max is not None
        ):
            raise ValueError("exam choice cardinality requires a choice group")
        if (
            self.choice_group_min is not None
            and self.choice_group_max is not None
            and self.choice_group_min > self.choice_group_max
        ):
            raise ValueError("exam choice group minimum cannot exceed its maximum")
        if self.choice_group_id is not None and not self.is_choice:
            raise ValueError("exam choice group members must be marked as choices")
        return self


class Quota(ContractModel):
    quota_type: QuotaType
    source_name: NonEmptyText
    places: int = Field(strict=True, ge=0, le=100_000)
    provenance: AdmissionProvenance


class PassingScore(ContractModel):
    score_type: PassingScoreType
    competition_type: AdmissionCompetitionType = AdmissionCompetitionType.GENERAL
    status: PassingScoreStatus = PassingScoreStatus.NUMERIC
    score: Decimal | None = Field(default=None, strict=True, ge=ZERO, le=Decimal(400), max_digits=6, decimal_places=2)
    provenance: AdmissionProvenance

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status is PassingScoreStatus.NUMERIC and self.score is None:
            raise ValueError("numeric passing score must contain score")
        if self.status is PassingScoreStatus.BVI:
            if self.score is not None:
                raise ValueError("BVI passing score must not contain score")
            if self.competition_type not in {
                AdmissionCompetitionType.BVI,
                AdmissionCompetitionType.SPECIAL_QUOTA,
                AdmissionCompetitionType.SEPARATE_QUOTA,
                AdmissionCompetitionType.TARGETED,
            }:
                raise ValueError("BVI passing score must use a BVI or quota competition type")
        return self


class TuitionCost(ContractModel):
    amount: Decimal = Field(strict=True, ge=ZERO, max_digits=12, decimal_places=2)
    currency: ShortText
    academic_year: str | None = Field(default=None, min_length=4, max_length=32)
    period: NonEmptyText | None = None
    study_form: StudyForm | None = None
    is_discounted: bool = False
    provenance: AdmissionProvenance


class AdmissionOffering(ContractModel):
    id: NonEmptyText
    program_id: ProgramId
    admission_year: EducationYear
    study_form: StudyForm | None = None
    funding_type: FundingType | None = None
    campus_id: AdmissionCampusId | None = None
    scope: AdmissionScope
    places: int | None = Field(default=None, strict=True, ge=0, le=100_000)
    exams: tuple[ExamRequirement, ...] = ()
    quotas: tuple[Quota, ...] = ()
    passing_scores: tuple[PassingScore, ...] = ()
    tuition: tuple[TuitionCost, ...] = ()
    provenance: tuple[AdmissionProvenance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.id.startswith("admission-offering:"):
            raise ValueError("admission offering id must use the admission-offering namespace")
        if self.funding_type is FundingType.BUDGET and self.tuition:
            raise ValueError("budget offering cannot contain tuition costs")
        if self.funding_type is FundingType.PAID and self.places is not None and self.places < 0:
            raise ValueError("paid offering places cannot be negative")
        choice_groups: dict[str, list[ExamRequirement]] = {}
        for exam in self.exams:
            if exam.choice_group_id is not None:
                choice_groups.setdefault(exam.choice_group_id, []).append(exam)
        for group_id, members in choice_groups.items():
            cardinalities = {
                (member.choice_group_min, member.choice_group_max) for member in members
            }
            if len(cardinalities) != 1:
                raise ValueError(f"choice group {group_id} has inconsistent cardinality")
            minimum, maximum = next(iter(cardinalities))
            if minimum is not None and maximum is not None and maximum > len(members):
                raise ValueError(f"choice group {group_id} exceeds its member count")
        return self


class ProgramAdmissions(ContractModel):
    """All source-backed admission facts currently known for one program."""

    program_id: ProgramId
    offerings: tuple[AdmissionOffering, ...] = ()

    @model_validator(mode="after")
    def validate_program_identity(self) -> Self:
        if any(offering.program_id != self.program_id for offering in self.offerings):
            raise ValueError("all admission offerings must belong to the envelope program")
        ids = tuple(offering.id for offering in self.offerings)
        if len(ids) != len(set(ids)):
            raise ValueError("admission offerings must have unique ids")
        return self


__all__ = [
    "AdmissionCampusId",
    "AdmissionCompetitionType",
    "AdmissionCycle",
    "AdmissionCycleId",
    "AdmissionCycleResolution",
    "AdmissionCycleResolutionStatus",
    "AdmissionCycleState",
    "AdmissionExamChoiceGroupId",
    "AdmissionOffering",
    "AdmissionProvenance",
    "AdmissionScope",
    "ExamRequirement",
    "FundingType",
    "InclusiveDateWindow",
    "PassingScore",
    "PassingScoreStatus",
    "PassingScoreType",
    "ProgramAdmissions",
    "Quota",
    "QuotaType",
    "StudyForm",
    "TuitionCost",
    "admission_cycle_id",
]
