from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from andromeda.api.dependencies import get_university_catalog_canonical_reader, get_university_catalog_reader, get_university_editorial_event_service, get_university_reader
from andromeda.api.dependencies.university_admin import require_university_admin, require_university_editor
from andromeda.api.schemas.university_events import AgendaItemRequest, AgendaReplaceRequest, UniversityEditorialEventAdminDetailResponse, UniversityEditorialEventAdminListResponse, UniversityEditorialEventPublicDetailResponse, UniversityEditorialEventPublicListResponse, UniversityEditorialEventRequest, UniversityEditorialEventUpdateRequest, admin_event_response, public_event_response
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import AgendaItem, EditorialAudienceMode, EditorialEventStatus
from andromeda.modules.university_admin.repository.catalog_ports import UniversityCatalogCanonicalReader, UniversityCatalogReader
from andromeda.modules.university_admin.services.events import UniversityEditorialEventService
from andromeda.modules.universities.repository.ports import UniversityReader
from andromeda.shared.contracts.errors import NotFoundError
from andromeda.shared.contracts.ids import UniversityEventId, UniversityId
from andromeda.modules.university_admin.contracts.public import UniversityAdminActor


router = APIRouter(tags=["university-events"])


@router.get("/university-admin/universities/{university_id}/events", response_model=UniversityEditorialEventAdminListResponse, operation_id="list_university_editorial_events")
def list_admin_events(
    university_id: UniversityId,
    status_filter: EditorialEventStatus | None = Query(default=None, alias="status"),
    _actor: UniversityAdminActor = Depends(require_university_admin),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminListResponse:
    snapshots = service.list_admin_events(university_id, status=status_filter)
    labels = _labels(university_id, catalog, canonical)
    return UniversityEditorialEventAdminListResponse(items=tuple(admin_event_response(item, labels) for item in snapshots), total=len(snapshots))


@router.post("/university-admin/universities/{university_id}/events", response_model=UniversityEditorialEventAdminDetailResponse, status_code=status.HTTP_201_CREATED, operation_id="create_university_editorial_event")
def create_admin_event(
    university_id: UniversityId,
    body: UniversityEditorialEventRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.create_event(
        university_id=university_id,
        account_id=actor.account_id,
        slug=body.slug,
        title=body.title,
        kind=body.kind,
        format=body.format,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        description=body.description,
        registration_url=body.registration_url,
        venue_id=body.venue_id,
        location_label=body.location_label,
        location_address=body.location_address,
        online_url=body.online_url,
        audience_mode=body.audience_mode,
        unit_ids=body.unit_ids,
        program_ids=body.program_ids,
        category_ids=body.category_ids,
        agenda=(),
    )
    if body.agenda:
        snapshot = service.replace_agenda(
            university_id=university_id,
            event_id=snapshot.event.event_id,
            account_id=actor.account_id,
            expected_revision=snapshot.event.revision,
            agenda=_agenda(snapshot.event.event_id, body.agenda),
        )
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.get("/university-admin/universities/{university_id}/events/{event_id}", response_model=UniversityEditorialEventAdminDetailResponse, operation_id="get_university_editorial_event")
def get_admin_event(
    university_id: UniversityId,
    event_id: UniversityEventId,
    _actor: UniversityAdminActor = Depends(require_university_admin),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.get_admin_event(university_id, event_id)
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.patch("/university-admin/universities/{university_id}/events/{event_id}", response_model=UniversityEditorialEventAdminDetailResponse, operation_id="update_university_editorial_event")
def update_admin_event(
    university_id: UniversityId,
    event_id: UniversityEventId,
    body: UniversityEditorialEventUpdateRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.update_event(
        university_id=university_id,
        event_id=event_id,
        account_id=actor.account_id,
        expected_revision=body.expected_revision,
        title=body.title,
        kind=body.kind,
        format=body.format,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        description=body.description,
        registration_url=body.registration_url,
        venue_id=body.venue_id,
        location_label=body.location_label,
        location_address=body.location_address,
        online_url=body.online_url,
        audience_mode=body.audience_mode,
        unit_ids=body.unit_ids,
        program_ids=body.program_ids,
        category_ids=body.category_ids,
        agenda=_agenda(event_id, body.agenda),
    )
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.post("/university-admin/universities/{university_id}/events/{event_id}/publish", response_model=UniversityEditorialEventAdminDetailResponse, operation_id="publish_university_editorial_event")
def publish_admin_event(
    university_id: UniversityId,
    event_id: UniversityEventId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.publish_event(university_id=university_id, event_id=event_id, account_id=actor.account_id, expected_revision=expected_revision)
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.delete("/university-admin/universities/{university_id}/events/{event_id}", response_model=UniversityEditorialEventAdminDetailResponse, operation_id="archive_university_editorial_event")
def archive_admin_event(
    university_id: UniversityId,
    event_id: UniversityEventId,
    expected_revision: int = Query(alias="expectedRevision", ge=1),
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.archive_event(university_id=university_id, event_id=event_id, account_id=actor.account_id, expected_revision=expected_revision)
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.put("/university-admin/universities/{university_id}/events/{event_id}/agenda", response_model=UniversityEditorialEventAdminDetailResponse, operation_id="replace_university_editorial_event_agenda")
def replace_admin_agenda(
    university_id: UniversityId,
    event_id: UniversityEventId,
    body: AgendaReplaceRequest,
    actor: UniversityAdminActor = Depends(require_university_editor),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventAdminDetailResponse:
    snapshot = service.replace_agenda(university_id=university_id, event_id=event_id, account_id=actor.account_id, expected_revision=body.expected_revision, agenda=_agenda(event_id, body.agenda))
    return UniversityEditorialEventAdminDetailResponse(event=admin_event_response(snapshot, _labels(university_id, catalog, canonical)))


@router.get("/universities/{university_id}/events", response_model=UniversityEditorialEventPublicListResponse, operation_id="list_university_public_editorial_events")
def list_public_events(
    university_id: UniversityId,
    kind: EventKind | None = None,
    format: EventFormat | None = None,
    universities: UniversityReader = Depends(get_university_reader),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventPublicListResponse:
    _require_university(universities, university_id)
    snapshots = service.list_public_events(university_id, kind=kind, format=format)
    labels = _labels(university_id, catalog, canonical)
    return UniversityEditorialEventPublicListResponse(items=tuple(public_event_response(item, labels) for item in snapshots), total=len(snapshots))


@router.get("/universities/{university_id}/events/{event_id}", response_model=UniversityEditorialEventPublicDetailResponse, operation_id="get_university_public_editorial_event")
def get_public_event(
    university_id: UniversityId,
    event_id: UniversityEventId,
    universities: UniversityReader = Depends(get_university_reader),
    service: UniversityEditorialEventService = Depends(get_university_editorial_event_service),
    catalog: UniversityCatalogReader = Depends(get_university_catalog_reader),
    canonical: UniversityCatalogCanonicalReader = Depends(get_university_catalog_canonical_reader),
) -> UniversityEditorialEventPublicDetailResponse:
    _require_university(universities, university_id)
    snapshot = service.get_public_event(university_id, event_id)
    return UniversityEditorialEventPublicDetailResponse(event=public_event_response(snapshot, _labels(university_id, catalog, canonical)))


def _agenda(event_id: UniversityEventId, items: tuple[AgendaItemRequest, ...]) -> tuple[AgendaItem, ...]:
    return tuple(
        AgendaItem(
            itemId=item.item_id,
            eventId=event_id,
            position=item.position,
            title=item.title,
            description=item.description,
            startsAt=item.starts_at,
            endsAt=item.ends_at,
            locationLabel=item.location_label,
            speakerLabel=item.speaker_label,
            revision=1,
        )
        for item in items
    )


def _labels(university_id: UniversityId, catalog: UniversityCatalogReader, canonical: UniversityCatalogCanonicalReader) -> dict[str, str]:
    labels = {item.unit_id: item.name for item in catalog.list_units(university_id)}
    labels.update({item.category_id: item.name for item in catalog.list_categories(university_id)})
    labels.update({item.id: item.name for item in canonical.list_programs(university_id)})
    return labels


def _require_university(universities: UniversityReader, university_id: UniversityId) -> None:
    if universities.get(university_id) is None:
        raise NotFoundError("Resource was not found")


__all__ = ["router"]
