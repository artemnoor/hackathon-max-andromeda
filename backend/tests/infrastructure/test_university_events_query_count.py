from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import event as sqlalchemy_event

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import AccountModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.infrastructure.repositories.university_catalog import SqlAlchemyUniversityCatalogCanonicalReader, SqlAlchemyUniversityCatalogRepository
from andromeda.infrastructure.repositories.university_events import SqlAlchemyUniversityEditorialEventRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.events.contracts.public import EventFormat, EventKind
from andromeda.modules.university_admin.contracts.events import EditorialAudienceMode, EditorialEvent, EditorialEventRelations, EditorialEventStatus
from andromeda.modules.university_admin.services.events import UniversityEditorialEventService


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
ACCOUNT_ID = "account:" + "a" * 32
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def test_public_editorial_event_feed_batch_loads_relations_and_agenda(tmp_path: Path) -> None:
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'event-query-count.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    with session_scope(engine) as session:
        session.add(AccountModel(account_id=ACCOUNT_ID, email="batch-event@example.com", password_hash="hash", created_at=NOW, updated_at=NOW))
        session.commit()
        repository = SqlAlchemyUniversityEditorialEventRepository(session)
        event = EditorialEvent(
            eventId="university-event:bmstu:" + "a" * 32,
            universityId="university:bmstu",
            slug="batch-event",
            title="Batch event",
            kind=EventKind.LECTURE,
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
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        sqlalchemy_event.listen(engine, "before_cursor_execute", capture)
        try:
            service = UniversityEditorialEventService(
                repository,
                repository,
                SqlAlchemyUniversityCatalogRepository(session),
                SqlAlchemyUniversityCatalogCanonicalReader(session),
            )
            result = service.list_public_events("university:bmstu")
        finally:
            sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
    engine.dispose()

    assert len(result) == 1
    assert len(statements) <= 12
