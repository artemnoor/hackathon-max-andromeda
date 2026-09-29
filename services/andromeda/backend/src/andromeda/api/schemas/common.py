from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaDefinition
from andromeda.shared.contracts.enums import AssessmentType, CompareStatus, ComparisonScope, EducationLevel, SourceKind
from andromeda.shared.contracts.provenance import GapSeverity


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True, alias_generator=to_camel)


class SourceAttributionResponse(ApiModel):
    kind: SourceKind
    url: HttpUrl
    captured_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str | None = None
    university_id: str | None = None
    run_id: str | None = None
    field: str | None = None
    record_key: str | None = None
    inferred: bool = False


class SourceGapReferenceResponse(ApiModel):
    code: str
    severity: GapSeverity
    message: str
    source_url: HttpUrl | None = None
    field: str | None = None
    record_key: str | None = None
    can_continue: bool = True


class ProgramSummaryResponse(ApiModel):
    id: str
    direction_id: str
    code: str
    name: str
    education_year: int
    study_plan_url: HttpUrl
    source_url: HttpUrl
    university_id: str | None = None
    university_name: str | None = None
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gaps: tuple[SourceGapReferenceResponse, ...] = ()


class ProgramListResponse(ApiModel):
    items: tuple[ProgramSummaryResponse, ...]


class ProgramResponse(ApiModel):
    program: ProgramSummaryResponse


class DisciplineAreaResponse(ApiModel):
    code: DisciplineAreaCode
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=512)
    weight: Decimal = Field(strict=True, gt=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)


class DisciplineAreaCatalogResponse(ApiModel):
    items: tuple[DisciplineAreaDefinition, ...]


class DisciplineResponse(ApiModel):
    id: str
    name: str
    normalized_name: str
    area_weights: tuple[DisciplineAreaResponse, ...]
    primary_area: DisciplineAreaCode


class DisciplineAreaSummaryResponse(ApiModel):
    area: DisciplineAreaCode
    name: str = Field(min_length=1, max_length=256)
    share: Decimal = Field(strict=True, ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4)


class CurriculumItemResponse(ApiModel):
    id: str
    discipline: DisciplineResponse
    source_name: str
    semester: int | None = None
    hours: int
    credits: Decimal | None = None
    assessment_types: tuple[AssessmentType, ...] | None = None
    source_position: int | None = None


class CurriculumResponse(ApiModel):
    program: ProgramSummaryResponse
    curriculum_id: str
    education_year: int
    source_url: HttpUrl
    captured_at: datetime
    items: tuple[CurriculumItemResponse, ...]
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gaps: tuple[SourceGapReferenceResponse, ...] = ()


class WorkloadResponse(ApiModel):
    semester: int | None = None
    hours: int
    credits: Decimal | None = None
    assessment_types: tuple[AssessmentType, ...] | None = None


class ComparisonRowResponse(ApiModel):
    discipline: DisciplineResponse
    semester: int | None = None
    a: WorkloadResponse | None = None
    b: WorkloadResponse | None = None
    status: CompareStatus
    hours_delta: int | None = None
    credits_delta: Decimal | None = None


class ComparisonTotalsResponse(ApiModel):
    hours: int
    credits: Decimal


class ComparisonResponse(ApiModel):
    program_a: ProgramSummaryResponse
    program_b: ProgramSummaryResponse
    scope: ComparisonScope
    semester: int | None = None
    rows: tuple[ComparisonRowResponse, ...]
    totals_a: ComparisonTotalsResponse
    totals_b: ComparisonTotalsResponse
    area_breakdown_a: tuple[DisciplineAreaSummaryResponse, ...] = ()
    area_breakdown_b: tuple[DisciplineAreaSummaryResponse, ...] = ()
    provenance: tuple[SourceAttributionResponse, ...] = ()
    source_gap_details: tuple[SourceGapReferenceResponse, ...] = ()
