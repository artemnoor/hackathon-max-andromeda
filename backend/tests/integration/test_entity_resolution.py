from __future__ import annotations

import sys
from pathlib import Path

from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.entity_resolution import (
    SqlAlchemyEntityResolutionRepository,
)
from andromeda.modules.entity_resolution.contracts.public import (
    ResolutionContext,
    ResolutionStatus,
)
from andromeda.modules.entity_resolution.services.resolvers import (
    CachedEntityCatalog,
    DirectionResolverService,
    MetricResolverService,
    ProgramResolverService,
    UniversityResolverService,
)

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from run_andromeda_bmstu import run_ingest  # noqa: E402, I001


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "tracer" / "raw"


def test_real_canonical_catalog_is_resolved_without_transport_dependency(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'entity-resolution.db').as_posix()}"
    run_ingest(mode="fixture", fixture_dir=FIXTURE_DIR, database_url=database_url, program_codes=())
    engine = create_engine_for_url(database_url)
    try:
        catalog = CachedEntityCatalog(SqlAlchemyEntityResolutionRepository(engine))
        university = UniversityResolverService(catalog).resolve("Бауманка")
        assert university.status is ResolutionStatus.RESOLVED
        assert university.selected_id == "university:bmstu"

        direction = DirectionResolverService(catalog).resolve(
            "09.03.01",
            context=ResolutionContext(university_id="university:bmstu"),
        )
        assert direction.status in {ResolutionStatus.RESOLVED, ResolutionStatus.EXACT}
        assert direction.selected_id == "direction:bmstu:09.03.01"

        program = ProgramResolverService(catalog).resolve(
            "09.03.01-02",
            context=ResolutionContext(direction_id=direction.selected_id),
        )
        assert program.status in {ResolutionStatus.RESOLVED, ResolutionStatus.EXACT}
        assert program.selected_id == "program:bmstu:09.03.01-02"

        metric = MetricResolverService().resolve("матан")
        assert metric.status is ResolutionStatus.RESOLVED
        assert metric.selected_id == "metric:math_share"
    finally:
        engine.dispose()
