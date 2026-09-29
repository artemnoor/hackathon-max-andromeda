"""Strict HTTP contracts for the map-agnostic campus data surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, HttpUrl

from andromeda.modules.campus.domain.entities import (
    CampusDepartmentReference,
    CampusPoint,
    CampusPointDetail,
    CampusPointType,
    CampusProgramReference,
    CampusUniversityReference,
)
from andromeda.modules.campus.contracts.results import CampusPointEventsResult, CampusPointListResult, CampusRecommendationResult
from andromeda.modules.events.domain.entities import Event
from andromeda.modules.proftest.contracts.public import Recommendation
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.ids import DepartmentId, DirectionId, EventId, ProgramId, UniversityId, VenueId

from .common import ApiModel
from .events import EventResponse, event_response
from .proftest import RecommendationResponse, recommendation_response


class CampusProvenanceResponse(ApiModel):
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


class CampusUniversityReferenceResponse(ApiModel):
    id: UniversityId
    name: str = Field(min_length=1, max_length=512)
    city: str = Field(min_length=1, max_length=256)
    address: str = Field(min_length=1, max_length=512)
    official_site: HttpUrl


class CampusProgramReferenceResponse(ApiModel):
    id: ProgramId
    direction_id: DirectionId
    code: str = Field(pattern=r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$")
    name: str = Field(min_length=1, max_length=512)
    education_year: int = Field(strict=True, ge=2000, le=2100)
    study_plan_url: HttpUrl
    source_url: HttpUrl


class CampusDepartmentReferenceResponse(ApiModel):
    id: DepartmentId


class CampusPointResponse(ApiModel):
    id: VenueId
    point_type: CampusPointType
    name: str = Field(min_length=1, max_length=512)
    address: str | None = Field(default=None, min_length=1, max_length=1024)
    latitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-90"), le=Decimal("90"), max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, strict=True, ge=Decimal("-180"), le=Decimal("180"), max_digits=9, decimal_places=6)
    university_ids: tuple[UniversityId, ...] = Field(min_length=1)
    department_ids: tuple[DepartmentId, ...] = ()
    program_ids: tuple[ProgramId, ...] = ()
    event_count: int = Field(strict=True, ge=0)
    provenance: tuple[CampusProvenanceResponse, ...] = Field(min_length=1)


class CampusPointDetailResponse(CampusPointResponse):
    universities: tuple[CampusUniversityReferenceResponse, ...] = ()
    departments: tuple[CampusDepartmentReferenceResponse, ...] = ()
    programs: tuple[CampusProgramReferenceResponse, ...] = ()


class CampusPointListResponse(ApiModel):
    items: tuple[CampusPointResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class CampusPointEventsResponse(ApiModel):
    point_id: VenueId
    items: tuple[EventResponse, ...] = ()
    total: int = Field(strict=True, ge=0)


class CampusRecommendationsResponse(ApiModel):
    recommended_program_ids: tuple[ProgramId, ...] = ()
    recommendations: tuple[RecommendationResponse, ...] = ()
    points: tuple[CampusPointDetailResponse, ...] = ()
    events: tuple[EventResponse, ...] = ()
    events_without_point: tuple[EventResponse, ...] = ()


def campus_point_response(point: CampusPoint) -> CampusPointResponse:
    return CampusPointResponse.model_validate(point.model_dump(mode="python"))


def campus_point_detail_response(point: CampusPointDetail) -> CampusPointDetailResponse:
    return CampusPointDetailResponse.model_validate(point.model_dump(mode="python"))


def campus_point_list_response(result: CampusPointListResult) -> CampusPointListResponse:
    return CampusPointListResponse(items=tuple(campus_point_response(item) for item in result.items), total=result.total)


def campus_point_events_response(result: CampusPointEventsResult) -> CampusPointEventsResponse:
    return CampusPointEventsResponse(
        point_id=result.point_id,
        items=tuple(event_response(item) for item in result.items),
        total=result.total,
    )


def campus_recommendations_response(
    result: CampusRecommendationResult,
    recommendations: tuple[Recommendation, ...],
) -> CampusRecommendationsResponse:
    return CampusRecommendationsResponse(
        recommended_program_ids=result.recommended_program_ids,
        recommendations=tuple(recommendation_response(item) for item in recommendations),
        points=tuple(campus_point_detail_response(item) for item in result.points),
        events=tuple(event_response(item) for item in result.events),
        events_without_point=tuple(event_response(item) for item in result.events_without_point),
    )


__all__ = [
    "CampusPointDetailResponse",
    "CampusPointEventsResponse",
    "CampusPointListResponse",
    "CampusPointResponse",
    "CampusRecommendationsResponse",
    "campus_point_detail_response",
    "campus_point_events_response",
    "campus_point_list_response",
    "campus_recommendations_response",
]
