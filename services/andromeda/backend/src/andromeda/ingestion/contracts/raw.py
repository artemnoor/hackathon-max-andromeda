from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self, TypeAlias

from pydantic import Field, HttpUrl, model_validator

from ...modules.admission_benefits.contracts.coverage import AdmissionBenefitCoverage
from ...shared.contracts.base import ContractModel
from ...shared.contracts.ids import (
    AdmissionCampusId,
    AdmissionExamChoiceGroupId,
    IngestRunId,
    SourceHash,
    UniversityId,
)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class RawSourceSnapshot(ContractModel):
    source_kind: str = Field(min_length=1, max_length=128)
    requested_url: HttpUrl
    final_url: HttpUrl
    status_code: int = Field(strict=True, ge=200, le=599)
    content_type: str | None = Field(default=None, max_length=256)
    captured_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    body: bytes = Field(min_length=1)
    response_class: str = Field(default="success", min_length=1, max_length=64)
    access_mode: str = Field(default="http", min_length=1, max_length=32)
    truncated: bool = False


class SourceLocator(ContractModel):
    source_url: HttpUrl
    page: int | None = Field(default=None, strict=True, ge=1)
    row: int | None = Field(default=None, strict=True, ge=1)
    field: str | None = Field(default=None, min_length=1, max_length=128)


class RawAdmissionBenefitRecordKind(StrEnum):
    OLYMPIAD = "olympiad"
    OLYMPIAD_PROFILE = "olympiad_profile"
    BENEFIT_RULE = "benefit_rule"
    INDIVIDUAL_ACHIEVEMENT = "individual_achievement"
    ACHIEVEMENT_POLICY = "achievement_policy"
    SOURCE_GAP = "source_gap"


class RawConfirmationThresholdCategory(StrEnum):
    """Source-defined scope for an Olympiad confirmation threshold."""

    GENERAL = "general"
    TERRITORIAL_EXCEPTION = "territorial_exception"
    UNKNOWN = "unknown"


class RawAdmissionConfirmationThreshold(ContractModel):
    minimum_score: Decimal = Field(strict=True, ge=0, le=100, max_digits=5, decimal_places=2)
    applicant_category: RawConfirmationThresholdCategory
    exam_kinds: tuple[Literal["ege", "internal_exam", "unknown"], ...] = Field(min_length=1)
    source_text: str = Field(min_length=1, max_length=2_000)
    locator: SourceLocator


class RawAdmissionBenefitCell(ContractModel):
    header: str = Field(min_length=1, max_length=512)
    value: str = Field(min_length=1, max_length=10_000)


class RawAdmissionBenefitCandidate(ContractModel):
    field: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=2_000)
    confidence: Decimal | None = Field(default=None, strict=True, ge=Decimal("0"), le=Decimal("1"), max_digits=3, decimal_places=2)


class AdmissionBenefitParserDiagnostic(ContractModel):
    code: str = Field(min_length=1, max_length=128)
    stage: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    severity: Literal["info", "warning", "ambiguous", "error"] = "warning"
    locator: SourceLocator
    candidates: tuple[str, ...] = ()


class RawAdmissionBenefitDocument(ContractModel):
    document_kind: str = Field(min_length=1, max_length=128)
    document_title: str = Field(min_length=1, max_length=512)
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    source_url: HttpUrl
    source_snapshot_hash: SourceHash
    source_run_id: IngestRunId
    captured_at: datetime
    locator: SourceLocator
    parser_version: str = Field(min_length=1, max_length=128)
    raw_page_text: str | None = Field(default=None, max_length=100_000)


class RawIndividualAchievementDocumentNote(ContractModel):
    """Verbatim document-level footnote with its own source locator."""

    marker: str = Field(min_length=1, max_length=32)
    source_text: str = Field(min_length=1, max_length=2_000)
    locator: SourceLocator


class RawAdmissionBenefitRecord(ContractModel):
    record_id: str = Field(min_length=1, max_length=384)
    record_kind: RawAdmissionBenefitRecordKind
    document_kind: str = Field(min_length=1, max_length=128)
    document_title: str = Field(min_length=1, max_length=512)
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    source_url: HttpUrl
    source_snapshot_hash: SourceHash
    source_run_id: IngestRunId
    captured_at: datetime
    locator: SourceLocator
    raw_text: str = Field(min_length=1, max_length=100_000)
    cells: tuple[RawAdmissionBenefitCell, ...] = ()
    normalized_candidates: tuple[RawAdmissionBenefitCandidate, ...] = ()
    diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()
    parser_version: str = Field(min_length=1, max_length=128)


class RawIndividualAchievementRecord(RawAdmissionBenefitRecord):
    record_kind: Literal[RawAdmissionBenefitRecordKind.INDIVIDUAL_ACHIEVEMENT] = RawAdmissionBenefitRecordKind.INDIVIDUAL_ACHIEVEMENT
    achievement_code_candidate: str | None = Field(default=None, min_length=1, max_length=256)
    official_name_candidate: str | None = Field(default=None, min_length=1, max_length=512)
    variant_label: str | None = Field(default=None, min_length=1, max_length=256)
    source_pages: tuple[int, ...] = ()
    document_notes: tuple[RawIndividualAchievementDocumentNote, ...] = ()
    points_text: str | None = Field(default=None, min_length=1, max_length=512)
    cap_text: str | None = Field(default=None, min_length=1, max_length=512)
    combination_text: str | None = Field(default=None, min_length=1, max_length=2_000)
    required_document_text: str | None = Field(default=None, min_length=1, max_length=2_000)


class RawUniversityRecord(ContractModel):
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    address: str = Field(min_length=1)
    official_site: HttpUrl
    locator: SourceLocator


class RawDirectionRecord(ContractModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    education_level: str = Field(min_length=1)
    locator: SourceLocator


class RawSourceGap(ContractModel):
    """Published source fact that could not be projected into a domain row."""

    id: str = Field(min_length=1, max_length=384)
    entity_type: str = Field(min_length=1, max_length=64)
    entity_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=512)
    source_url: HttpUrl
    locator: SourceLocator


class RawParserDiagnostic(ContractModel):
    """Structured parser warning retained alongside raw source evidence."""

    code: str = Field(min_length=1, max_length=128)
    stage: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    severity: Literal["info", "warning", "ambiguous"] = "warning"
    source_url: HttpUrl | None = None
    candidates: tuple[str, ...] = ()
    count: int = Field(default=1, strict=True, ge=1, le=100_000)


class RawProgramRecord(ContractModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    direction_code: str = Field(min_length=1)
    education_level: str = Field(min_length=1)
    education_year: int = Field(strict=True, ge=2000, le=2100)
    study_plan_url: HttpUrl
    source_url: HttpUrl
    locator: SourceLocator
    source_code: str | None = Field(default=None, min_length=1, max_length=256)


class RawCurriculumRow(ContractModel):
    program_code: str = Field(min_length=1)
    discipline: str = Field(min_length=1)
    semester: int | None = Field(default=None, strict=True, ge=1, le=12)
    hours: int = Field(strict=True, ge=0, le=2_000)
    credits: str | float | int | None = None
    assessment: str | None = None
    source_position: int | None = Field(default=None, strict=True, ge=1, le=10_000)
    source_url: HttpUrl
    locator: SourceLocator
    source_program_code: str | None = Field(default=None, min_length=1, max_length=256)
    lecture_hours: int | None = Field(default=None, strict=True, ge=0, le=2_000)
    practice_hours: int | None = Field(default=None, strict=True, ge=0, le=2_000)
    lab_hours: int | None = Field(default=None, strict=True, ge=0, le=2_000)
    self_study_hours: int | None = Field(default=None, strict=True, ge=0, le=2_000)
    is_elective: bool | None = None
    course_block: str | None = Field(default=None, min_length=1, max_length=128)
    practice_type: str | None = Field(default=None, min_length=1, max_length=128)


class RawAdmissionExamRequirement(ContractModel):
    subject: str = Field(min_length=1, max_length=256)
    source_name: str = Field(min_length=1, max_length=256)
    minimum_score: Decimal | None = Field(default=None, strict=True, ge=0, le=100, max_digits=5, decimal_places=2)
    is_choice: bool = False
    is_required: bool = True
    choice_group_id: AdmissionExamChoiceGroupId | None = None
    choice_group_min: int | None = Field(default=None, strict=True, ge=1, le=20)
    choice_group_max: int | None = Field(default=None, strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def validate_choice_metadata(self) -> RawAdmissionExamRequirement:
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


class RawAdmissionQuota(ContractModel):
    quota_type: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=256)
    places: int = Field(strict=True, ge=0, le=100_000)


class RawAdmissionPassingScore(ContractModel):
    score_type: str = Field(min_length=1, max_length=64)
    competition_type: str = Field(default="general", min_length=1, max_length=64)
    status: str = Field(default="numeric", min_length=1, max_length=32)
    score: Decimal | None = Field(default=None, strict=True, ge=0, le=400, max_digits=6, decimal_places=2)

    @model_validator(mode="after")
    def validate_score_status(self) -> Self:
        if self.status == "numeric" and self.score is None:
            raise ValueError("numeric admission passing score must contain score")
        if self.status == "bvi" and self.score is not None:
            raise ValueError("BVI admission passing score must not contain score")
        if self.status not in {"numeric", "bvi"}:
            raise ValueError("unsupported admission passing score status")
        if self.status == "bvi" and self.competition_type not in {
            "bvi",
            "special_quota",
            "separate_quota",
            "targeted",
        }:
            raise ValueError("BVI admission passing score must use a BVI or quota competition type")
        return self


class RawAdmissionTuition(ContractModel):
    amount: Decimal = Field(strict=True, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=1, max_length=16)
    academic_year: str | None = Field(default=None, min_length=4, max_length=32)
    period: str | None = Field(default=None, min_length=1, max_length=512)
    study_form: str | None = Field(default=None, min_length=1, max_length=64)
    is_discounted: bool = False


class RawAdmissionRecord(ContractModel):
    id: str = Field(min_length=1, max_length=384)
    program_code: str = Field(min_length=1, max_length=64)
    program_name: str | None = Field(default=None, min_length=1, max_length=512)
    admission_year: int = Field(strict=True, ge=2000, le=2100)
    study_form: str | None = Field(default=None, min_length=1, max_length=64)
    funding_type: str | None = Field(default=None, min_length=1, max_length=64)
    scope: str = Field(default="program", min_length=1, max_length=32)
    campus_id: AdmissionCampusId | None = None
    places: int | None = Field(default=None, strict=True, ge=0, le=100_000)
    exams: tuple[RawAdmissionExamRequirement, ...] = ()
    quotas: tuple[RawAdmissionQuota, ...] = ()
    passing_scores: tuple[RawAdmissionPassingScore, ...] = ()
    tuition: tuple[RawAdmissionTuition, ...] = ()
    source_kind: str = Field(min_length=1, max_length=256)
    source_url: HttpUrl
    locator: SourceLocator
    source_program_code: str | None = Field(default=None, min_length=1, max_length=256)


class RawVenueRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)


class RawCampusPointRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    point_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_codes: tuple[str, ...] = ()
    program_codes: tuple[str, ...] = ()
    source_kind: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("campus point latitude and longitude must be provided together")
        return self


class RawEventRecord(ContractModel):
    external_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    format: str = Field(min_length=1, max_length=32)
    starts_at: datetime
    ends_at: datetime | None = None
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    registration_url: HttpUrl | None = None
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_codes: tuple[str, ...] = ()
    program_codes: tuple[str, ...] = ()
    venue: RawVenueRecord | None = None
    source_kind: str = Field(min_length=1, max_length=128)
    source_url: HttpUrl
    locator: SourceLocator


class RawTracerBundle(ContractModel):
    snapshots: tuple[RawSourceSnapshot, ...] = Field(min_length=1)
    university: RawUniversityRecord
    direction: RawDirectionRecord
    programs: tuple[RawProgramRecord, ...] = Field(min_length=1)
    curriculum_rows: tuple[RawCurriculumRow, ...] = ()
    directions: tuple[RawDirectionRecord, ...] = ()
    source_gaps: tuple[RawSourceGap, ...] = ()
    diagnostics: tuple[RawParserDiagnostic, ...] = ()
    admissions: tuple[RawAdmissionRecord, ...] = ()
    events: tuple[RawEventRecord, ...] = ()
    campus_points: tuple[RawCampusPointRecord, ...] = ()
    admission_benefit_records: tuple[RawAdmissionBenefitRecord, ...] = ()
    admission_benefit_diagnostics: tuple[AdmissionBenefitParserDiagnostic, ...] = ()
    admission_benefit_coverage: AdmissionBenefitCoverage | None = None
