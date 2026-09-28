from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import AccountModel, UniversityEditorialEventModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.university_events import SqlAlchemyUniversityEditorialEventRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventStatus


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
ACCOUNT_ID = "account:" + "a" * 32
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def test_source_ingestion_does_not_remove_editorial_event(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'editorial-projection.db').as_posix()}")
    Base.metadata.create_all(engine)
    ingestion = SqlAlchemyIngestionRepository(engine)
    ingestion.ingest(raw, canonical)
    with session_scope(engine) as session:
        session.add(AccountModel(account_id=ACCOUNT_ID, email="projection@example.com", password_hash="hash", created_at=NOW, updated_at=NOW))
        session.commit()
        repository = SqlAlchemyUniversityEditorialEventRepository(session)
        event = EditorialEvent(
            eventId="university-event:bmstu:" + "a" * 32,
            universityId="university:bmstu",
            slug="projection-safe",
            title="Не удалять ingestion-ом",
            kind=EventKind.OPEN_DAY,
            format=EventFormat.OFFLINE,
            startsAt=NOW + timedelta(days=1),
            endsAt=NOW + timedelta(days=1, hours=1),
            status=EditorialEventStatus.PUBLISHED,
            audienceMode=EditorialAudienceMode.ALL_UNIVERSITY,
            revision=1,
            createdByAccountId=ACCOUNT_ID,
            updatedByAccountId=ACCOUNT_ID,
            createdAt=NOW,
            updatedAt=NOW,
            publishedAt=NOW,
        )
        repository.create_event(event, EditorialEventRelations(eventId=event.event_id), ())
    ingestion.ingest(raw, canonical.model_copy(update={"events": ()}))
    with session_scope(engine) as session:
        row = session.scalar(select(UniversityEditorialEventModel).where(UniversityEditorialEventModel.event_id == event.event_id))
        assert row is not None
        assert row.title == "Не удалять ingestion-ом"
    engine.dispose()
