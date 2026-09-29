from __future__ import annotations

from pathlib import Path

from sqlalchemy import event as sqlalchemy_event, func, select

from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database.models import VenueModel
from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.repositories.events import SqlAlchemyEventRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.modules.events.contracts.public import EventFilters, EventKind


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
EVENT_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "events" / "raw"


def _seed(tmp_path: Path):
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, event_fixture_dir=EVENT_FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'events.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return engine, raw, canonical


def test_event_repository_lists_filters_and_detail_contracts(tmp_path: Path) -> None:
    engine, _, canonical = _seed(tmp_path)
    with session_scope(engine) as session:
        repository = SqlAlchemyEventRepository(session)
        all_events = repository.list(EventFilters())
        program_events = repository.list(EventFilters(program_id="program:09.03.01-02"))
        recommended = repository.list(
            EventFilters(
                recommended=True,
                recommended_program_ids=("program:09.03.01-12",),
                kind=EventKind.ADDITIONAL_EDUCATION,
            )
        )
        detail = repository.get("event:bmstu:dod-2026")

    assert all_events.total == len(canonical.events) == 5
    expected_ids = [event.id for event in sorted(canonical.events, key=lambda event: (event.starts_at, event.id))]
    assert [item.id for item in all_events.items] == expected_ids
    assert {item.id for item in program_events.items} == {"event:bmstu:dod-2026", "event:bmstu:robotics-workshop-2026"}
    assert [item.id for item in recommended.items] == ["event:bmstu:dod-2026"]
    assert detail is not None and detail.venue is not None
    assert detail.venue.address == "Москва, 2-я Бауманская улица, 5"


def test_event_list_batch_loads_links_and_venues(tmp_path: Path) -> None:
    engine, _, _ = _seed(tmp_path)
    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sqlalchemy_event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with session_scope(engine) as session:
            result = SqlAlchemyEventRepository(session).list(EventFilters(limit=100))
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture_statement)

    assert result.total == 5
    assert len(result.items) == 5
    assert len(statements) == 6  # count + event rows + three link batches + one venue batch


def test_event_projection_is_idempotent_updates_and_reconciles_stale_source(tmp_path: Path) -> None:
    engine, raw, canonical = _seed(tmp_path)
    changed = canonical.model_copy(
        update={
            "events": (
                canonical.events[0].model_copy(update={"title": "Обновлённый день открытых дверей"}),
                *canonical.events[1:4],
            )
        }
    )
    repository = SqlAlchemyIngestionRepository(engine)
    repository.ingest(raw, changed)
    with session_scope(engine) as session:
        result = SqlAlchemyEventRepository(session).list(EventFilters())
    assert result.total == 4
    assert result.items[0].title == "Обновлённый день открытых дверей"

    repository.ingest(raw, canonical.model_copy(update={"events": ()}))
    with session_scope(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(VenueModel).where(VenueModel.source_kind == "bmstu_events")
        ) == 0
