from __future__ import annotations

from pathlib import Path

from sqlalchemy import event as sqlalchemy_event, func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database import Base, create_engine_for_url, session_scope
from andromeda.infrastructure.database.models import VenueModel
from andromeda.infrastructure.repositories.campus import SqlAlchemyCampusPointRepository
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.modules.campus.contracts.public import CampusEventFilters, CampusPointFilters
from andromeda.modules.campus.domain.entities import CampusPointType


TRACER_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
CAMPUS_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "campus" / "raw"


def _seed(tmp_path: Path):
    adapter = BmstuUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=TRACER_FIXTURE_DIR, campus_fixture_dir=CAMPUS_FIXTURE_DIR)
    finally:
        adapter.close()
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'campus.db').as_posix()}")
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    return engine, raw, canonical


def test_campus_repository_lists_filters_detail_and_events(tmp_path: Path) -> None:
    engine, _, canonical = _seed(tmp_path)
    with session_scope(engine) as session:
        repository = SqlAlchemyCampusPointRepository(session)
        all_points = repository.list(CampusPointFilters())
        buildings = repository.list(CampusPointFilters(point_type=CampusPointType.BUILDING))
        program_points = repository.list(CampusPointFilters(program_id="program:09.03.01-02"))
        department_points = repository.list(CampusPointFilters(department_id="department:bmstu:iu7"))
        detail = repository.get("venue:bmstu:main-campus")
        events = repository.events("venue:bmstu:main-campus", CampusEventFilters())

    assert all_points.total == len(canonical.campus_points) == 5
    assert [point.id for point in all_points.items] == sorted(point.id for point in canonical.campus_points)
    assert buildings.items[0].point_type is CampusPointType.BUILDING
    assert {point.id for point in program_points.items} == {"venue:bmstu:lab-iu7", "venue:bmstu:main-campus"}
    assert {point.id for point in department_points.items} == {
        "venue:bmstu:innovation-hub",
        "venue:bmstu:lab-iu7",
        "venue:bmstu:main-campus",
    }
    assert detail is not None
    assert detail.point.programs[0].id == "program:bmstu:09.03.01-02"
    assert detail.point.universities[0].id == "university:bmstu"
    assert events.total == 1
    assert events.items[0].id == "event:bmstu:dod-2026"


def test_campus_repository_uses_batch_reads_for_point_list(tmp_path: Path) -> None:
    engine, _, _ = _seed(tmp_path)
    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sqlalchemy_event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        with session_scope(engine) as session:
            result = SqlAlchemyCampusPointRepository(session).list(CampusPointFilters(limit=100))
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture_statement)

    assert result.total == 5
    assert len(result.items) == 5
    assert len(statements) <= 9  # count, rows, six link batches, event counts


def test_campus_repository_recommendations_use_program_intersection_and_keep_unplaced_events(tmp_path: Path) -> None:
    engine, _, _ = _seed(tmp_path)
    with session_scope(engine) as session:
        result = SqlAlchemyCampusPointRepository(session).recommendations(
            ("program:09.03.01-12",),
            limit=50,
        )

    assert result.recommended_program_ids == ("program:bmstu:09.03.01-12",)
    assert {point.id for point in result.points} == {"venue:bmstu:innovation-hub", "venue:bmstu:main-campus"}
    assert {event.id for event in result.events} == {"event:bmstu:dod-2026"}
    assert {event.id for event in result.events_without_point} == {
        "event:bmstu:career-hybrid-2026",
        "event:bmstu:online-open-lecture-2026",
    }


def test_campus_projection_is_idempotent_updates_and_removes_only_stale_unreferenced_points(tmp_path: Path) -> None:
    engine, raw, canonical = _seed(tmp_path)
    repository = SqlAlchemyIngestionRepository(engine)
    changed = canonical.model_copy(
        update={
            "campus_points": (
                canonical.campus_points[0].model_copy(update={"name": "Обновлённый главный корпус"}),
                *canonical.campus_points[1:4],
            )
        }
    )
    repository.ingest(raw, changed)
    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(VenueModel)) == 4
        point = session.get(VenueModel, "venue:bmstu:main-campus")
        assert point is not None and point.name == "Обновлённый главный корпус"
