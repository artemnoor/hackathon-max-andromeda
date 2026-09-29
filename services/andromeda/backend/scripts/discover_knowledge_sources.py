"""Poll only approved knowledge-source registry entries and stage candidates."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.composition import build_container
from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.session import session_factory
from andromeda.ingestion.knowledge_source_adapters import (
    default_knowledge_source_adapters,
)
from andromeda.ingestion.knowledge_source_discovery import (
    KnowledgeSourceDiscoveryRunner,
)

logger = logging.getLogger("andromeda.knowledge_source_discovery_runner")


def run(*, database_url: str | None = None, max_sources: int = 100) -> dict[str, object]:
    settings = Settings.from_environment(database_url)
    engine = create_engine_for_url(settings.database_url, **settings.engine_options)
    container = build_container(engine, settings)
    factory = session_factory(engine)
    try:
        with factory() as session:
            runner = KnowledgeSourceDiscoveryRunner(
                source_repository=container.knowledge_source_repository(session),
                candidate_repository=container.knowledge_candidate_repository(session),
                capture_audit_writer=container.ingestion,
                adapters=default_knowledge_source_adapters(),
                unit_of_work=session,
            )
            summary = runner.poll_due_sources(max_sources=max_sources)
        result = {
            "databaseTarget": redact_database_url(settings.database_url),
            "canonicalProjectionChanged": False,
            "summary": summary.model_dump(mode="json"),
        }
        logger.info("knowledge_discovery_cli_complete due=%d", summary.sources_due)
        return result
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Poll approved knowledge sources; never accepts arbitrary URLs or writes canonical policy"
    )
    parser.add_argument("--database-url")
    parser.add_argument("--max-sources", type=int, default=100)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s %(message)s",
    )
    print(json.dumps(run(database_url=args.database_url, max_sources=args.max_sources), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
