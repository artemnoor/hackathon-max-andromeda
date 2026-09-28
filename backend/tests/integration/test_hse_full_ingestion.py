from __future__ import annotations

from pathlib import Path
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.ingestion.universities.hse import HseUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.database.models import CurriculumModel, DisciplineModel, DirectionModel, ProgramModel
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "hse" / "raw"


def test_hse_fixture_manifest_matches_captured_bodies() -> None:
    manifest = json.loads((FIXTURE_DIR / "source_manifest.json").read_text(encoding="utf-8"))
    snapshots = manifest["snapshots"]
    assert snapshots
    for item in snapshots:
        body = (FIXTURE_DIR / item["body_path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item["content_sha256"]


def test_hse_fixture_is_a_real_repeatable_vertical_slice(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'hse-full-ingestion.db').as_posix()}"
    adapter = HseUniversityAdapter()
    try:
        raw, canonical = adapter.parse_sources(fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()

    assert len(raw.programs) >= 2
    assert len(raw.curriculum_rows) > 0
    assert len(raw.admissions) > 0
    assert {program.id.split(":", 2)[1] for program in canonical.programs} == {"hse"}
    assert all(program.id.startswith("program:hse:") for program in canonical.programs)
    assert all(direction.id.startswith("direction:hse:") for direction in canonical.directions)
    assert all(sum(weight.weight for weight in discipline.area_weights) == 1 for discipline in canonical.disciplines)
    assert all(len(curriculum.items) > 0 for curriculum in canonical.curricula)
    assert all(snapshot.content_sha256 for snapshot in raw.snapshots)

    engine = create_engine_for_url(database_url)
    try:
        Base.metadata.create_all(engine)
        first_run = SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
        second_run = SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
        assert first_run != second_run
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(DirectionModel)) == len(canonical.directions)
            assert session.scalar(select(func.count()).select_from(ProgramModel)) == len(canonical.programs)
            assert session.scalar(select(func.count()).select_from(CurriculumModel)) == len(canonical.curricula)
            assert session.scalar(select(func.count()).select_from(DisciplineModel)) == len(canonical.disciplines)
    finally:
        engine.dispose()


def test_bmstu_and_hse_can_share_direction_and_program_codes(tmp_path: Path) -> None:
    from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter

    database_url = f"sqlite:///{(tmp_path / 'multi-university.db').as_posix()}"
    hse = HseUniversityAdapter()
    bmstu = BmstuUniversityAdapter()
    try:
        hse_raw, hse_canonical = hse.parse_sources(fixture_dir=FIXTURE_DIR)
        bmstu_raw, bmstu_canonical = bmstu.parse_sources(
            fixture_dir=Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"
        )
    finally:
        hse.close()
        bmstu.close()

    engine = create_engine_for_url(database_url)
    try:
        Base.metadata.create_all(engine)
        SqlAlchemyIngestionRepository(engine).ingest(hse_raw, hse_canonical)
        SqlAlchemyIngestionRepository(engine).ingest(bmstu_raw, bmstu_canonical)
        with Session(engine) as session:
            ids = set(session.scalars(select(ProgramModel.id)).all())
            assert any(value.startswith("program:hse:01.03.02-") for value in ids)
            assert any(value.startswith("program:bmstu:09.03.01-") for value in ids)
            assert session.scalar(select(func.count()).select_from(DirectionModel)) == 2
    finally:
        engine.dispose()
