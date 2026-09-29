from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import AccountModel, UniversityModel
from andromeda.infrastructure.repositories.university_events import SqlAlchemyUniversityEditorialEventRepository
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import AgendaItem, EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventStatus
from andromeda.shared.contracts.errors import ConflictError


ACCOUNT_ID = "account:" + "a" * 32
UNIVERSITY_ID = "university:bmstu"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _engine(tmp_path: Path):
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'university-events.db').as_posix()}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        session.add(AccountModel(account_id=ACCOUNT_ID, email="events@example.com", password_hash="hash", created_at=NOW, updated_at=NOW))
        session.add(UniversityModel(id=UNIVERSITY_ID, name="Бауманка", city="Москва", official_site="https://bmstu.ru/", address="Москва"))
        session.commit()
    return engine


def _event(slug: str = "open-day", *, status: EditorialEventStatus = EditorialEventStatus.DRAFT, revision: int = 1) -> EditorialEvent:
    return EditorialEvent(
        eventId="university-event:bmstu:" + ("a" if slug == "open-day" else "b") * 32,
        universityId=UNIVERSITY_ID,
        slug=slug,
        title="День открытых дверей",
        kind=EventKind.OPEN_DAY,
        format=EventFormat.OFFLINE,
        startsAt=NOW + timedelta(days=1),
        endsAt=NOW + timedelta(days=1, hours=2),
        description="Описание",
        registrationUrl=None,
        venueId=None,
        locationLabel="Корпус",
        locationAddress=None,
        onlineUrl=None,
        status=status,
        audienceMode=EditorialAudienceMode.ALL_UNIVERSITY,
        revision=revision,
        createdByAccountId=ACCOUNT_ID,
        updatedByAccountId=ACCOUNT_ID,
        createdAt=NOW,
        updatedAt=NOW,
        publishedAt=NOW if status is EditorialEventStatus.PUBLISHED else None,
        archivedAt=NOW if status is EditorialEventStatus.ARCHIVED else None,
    )


def test_repository_keeps_drafts_out_of_public_and_updates_revision(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityEditorialEventRepository(session)
            draft = _event()
            relations = EditorialEventRelations(eventId=draft.event_id)
            item = AgendaItem(itemId="agenda:1", eventId=draft.event_id, position=1, title="Регистрация", revision=1)
            created = repository.create_event(draft, relations, (item,))
            assert repository.list_events(UNIVERSITY_ID, public_only=True) == ()

            published = draft.model_copy(update={"status": EditorialEventStatus.PUBLISHED, "published_at": NOW})
            saved = repository.update_event(published, relations, (item,), expected_revision=created.revision)
            assert saved.revision == 2
            public = repository.list_snapshots(UNIVERSITY_ID, public_only=True)
            assert len(public) == 1
            assert public[0].agenda[0].position == 1

            archived = saved.model_copy(update={"status": EditorialEventStatus.ARCHIVED, "archived_at": NOW})
            repository.update_event(archived, relations, (item,), expected_revision=saved.revision)
            assert repository.list_snapshots(UNIVERSITY_ID, public_only=True) == ()
    finally:
        engine.dispose()


def test_repository_rejects_stale_revision_and_duplicate_slug(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with session_scope(engine) as session:
            repository = SqlAlchemyUniversityEditorialEventRepository(session)
            first = _event()
            repository.create_event(first, EditorialEventRelations(eventId=first.event_id), ())
            with pytest.raises(ConflictError):
                repository.create_event(first, EditorialEventRelations(eventId=first.event_id), ())
            changed = first.model_copy(update={"title": "Другое"})
            with pytest.raises(ConflictError):
                repository.update_event(changed, EditorialEventRelations(eventId=first.event_id), (), expected_revision=99)
    finally:
        engine.dispose()
