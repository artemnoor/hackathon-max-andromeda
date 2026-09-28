"""Capture bounded PostgreSQL query plans and timing for critical read paths.

This diagnostic is intentionally read-only: EXPLAIN does not use ANALYZE and
the timing pass only executes fixed, bounded SELECT statements. Parameters are
kept in-process and the reported database target is redacted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.infrastructure.config import is_postgresql_url, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url


@dataclass(frozen=True, slots=True)
class QueryCase:
    name: str
    statement: str
    parameters: Mapping[str, object]


def _cases() -> tuple[QueryCase, ...]:
    return (
        QueryCase(
            "catalog",
            """
            SELECT p.id, p.code, p.name, d.university_id
            FROM educational_programs AS p
            JOIN directions AS d ON d.id = p.direction_id
            WHERE d.university_id = :university_id
            ORDER BY p.code, p.id
            LIMIT :limit
            """,
            {"university_id": "university:bmstu", "limit": 100},
        ),
        QueryCase(
            "curriculum",
            """
            SELECT id, program_id, education_year
            FROM curricula
            WHERE program_id = :program_id
            ORDER BY education_year DESC, id
            LIMIT 1
            """,
            {"program_id": "program:bmstu:09.03.01-02"},
        ),
        QueryCase(
            "curriculum_items",
            """
            SELECT ci.id, ci.curriculum_id, ci.discipline_id, ci.semester
            FROM curriculum_items AS ci
            JOIN curricula AS c ON c.id = ci.curriculum_id
            WHERE c.program_id = :program_id
            ORDER BY ci.curriculum_id, ci.semester NULLS LAST, ci.source_position NULLS LAST, ci.source_name
            LIMIT :limit
            """,
            {"program_id": "program:bmstu:09.03.01-02", "limit": 500},
        ),
        QueryCase(
            "admissions",
            """
            SELECT ao.id, ao.program_id, ao.admission_year, ao.scope
            FROM admission_offerings AS ao
            WHERE ao.program_id = :program_id
            ORDER BY ao.admission_year DESC, ao.id
            LIMIT :limit
            """,
            {"program_id": "program:bmstu:09.03.01-02", "limit": 100},
        ),
        QueryCase(
            "comparison",
            """
            SELECT ci.curriculum_id, ci.discipline_id, ci.semester, ci.hours, ci.credits
            FROM curriculum_items AS ci
            JOIN curricula AS c ON c.id = ci.curriculum_id
            WHERE c.program_id IN (:program_a, :program_b, :program_c)
            ORDER BY c.program_id, ci.semester NULLS LAST, ci.source_position NULLS LAST
            LIMIT :limit
            """,
            {
                "program_a": "program:bmstu:09.03.01-02",
                "program_b": "program:bmstu:09.03.01-12",
                "program_c": "program:bmstu:09.03.01-14",
                "limit": 1500,
            },
        ),
        QueryCase(
            "proftest_catalog",
            """
            SELECT p.id, p.code, p.name, c.id AS curriculum_id
            FROM educational_programs AS p
            JOIN curricula AS c ON c.program_id = p.id
            ORDER BY p.code, p.id, c.education_year DESC
            LIMIT :limit
            """,
            {"limit": 500},
        ),
        QueryCase(
            "events",
            """
            SELECT e.id, e.starts_at, e.format
            FROM events AS e
            WHERE e.format = :format
            ORDER BY e.starts_at, e.id
            LIMIT :limit
            """,
            {"format": "online", "limit": 100},
        ),
        QueryCase(
            "campus",
            """
            SELECT v.id, v.name
            FROM venues AS v
            JOIN venue_program_links AS vpl ON vpl.venue_id = v.id
            WHERE vpl.program_id = :program_id
            ORDER BY v.id
            LIMIT :limit
            """,
            {"program_id": "program:bmstu:09.03.01-02", "limit": 100},
        ),
        QueryCase(
            "admin_runs",
            """
            SELECT id, status, started_at, finished_at
            FROM ingest_runs
            WHERE status = :status
            ORDER BY started_at DESC, id DESC
            LIMIT :limit
            """,
            {"status": "completed", "limit": 100},
        ),
        QueryCase(
            "knowledge_pollable_sources",
            """
            WITH latest_registry_revision AS (
                SELECT source_id, MAX(revision) AS revision
                FROM knowledge_source_registry_revisions
                GROUP BY source_id
            )
            SELECT r.source_id, r.revision
            FROM knowledge_source_registry_revisions AS r
            JOIN latest_registry_revision AS latest
              ON latest.source_id = r.source_id
             AND latest.revision = r.revision
            WHERE r.enabled IS TRUE
            ORDER BY r.source_id
            LIMIT :limit
            """,
            {"limit": 501},
        ),
        QueryCase(
            "policy_as_known_revision_scan",
            """
            SELECT rule_id, revision, content_hash, family_id, authority_level,
                   scope_level, scope_id, lifecycle, valid_start, valid_end,
                   effective_start, effective_end, recorded_at
            FROM policy_rule_revisions
            WHERE recorded_at <= :as_known_at
            ORDER BY rule_id, revision
            LIMIT :limit
            """,
            {"as_known_at": datetime(2030, 1, 1, tzinfo=UTC), "limit": 501},
        ),
    )


def profile(database_url: str) -> dict[str, object]:
    if not is_postgresql_url(database_url):
        raise ValueError("profile_queries.py requires a PostgreSQL URL")
    engine = create_engine_for_url(database_url, pool_size=2, max_overflow=0)
    results: dict[str, object] = {}
    try:
        with engine.connect() as connection:
            for case in _cases():
                explain = connection.execute(
                    text(f"EXPLAIN (FORMAT JSON) {case.statement}"),
                    dict(case.parameters),
                ).scalar_one()
                started = perf_counter()
                rows = connection.execute(
                    text(case.statement), dict(case.parameters)
                ).all()
                elapsed_ms = (perf_counter() - started) * 1000
                results[case.name] = {
                    "plan": explain,
                    "elapsed_ms": round(elapsed_ms, 3),
                    "row_count": len(rows),
                    "limit": case.parameters.get("limit"),
                }
    finally:
        engine.dispose()
    return {"database_target": redact_database_url(database_url), "queries": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile fixed, bounded PostgreSQL read queries"
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional JSON artifact path"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = (
        args.database_url
        or os.environ.get("ANDROMEDA_POSTGRES_TEST_URL")
        or os.environ.get("ANDROMEDA_DATABASE_URL")
    )
    if not database_url:
        raise SystemExit("set --database-url or ANDROMEDA_POSTGRES_TEST_URL")
    artifact = profile(database_url)
    payload = json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(args.out)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
