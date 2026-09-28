from __future__ import annotations

from pathlib import Path

import pytest

from andromeda.ingestion.contracts.normalized import CanonicalSnapshot
from andromeda.ingestion.contracts.raw import RawTracerBundle
from andromeda.ingestion.universities.bmstu import BmstuUniversityAdapter
from andromeda.infrastructure.database import Base, create_engine_for_url
from andromeda.infrastructure.repositories.ingestion import SqlAlchemyIngestionRepository

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tracer" / "raw"
PROGRAM_A = "program:bmstu:09.03.01-02"
PROGRAM_B = "program:bmstu:09.03.01-12"


@pytest.fixture
def parsed_bundle() -> tuple[RawTracerBundle, CanonicalSnapshot]:
    adapter = BmstuUniversityAdapter()
    try:
        return adapter.parse_sources(mode="fixture", fixture_dir=FIXTURE_DIR)
    finally:
        adapter.close()


@pytest.fixture
def ingested_db(tmp_path: Path, parsed_bundle: tuple[RawTracerBundle, CanonicalSnapshot]) -> tuple[str, RawTracerBundle, CanonicalSnapshot]:
    raw, canonical = parsed_bundle
    database_url = f"sqlite:///{(tmp_path / 'tracer.db').as_posix()}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    SqlAlchemyIngestionRepository(engine).ingest(raw, canonical)
    engine.dispose()
    return database_url, raw, canonical
