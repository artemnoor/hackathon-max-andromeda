"""Report recoverable legacy admission-benefit provenance without writing data."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.database.models import (
    AdmissionBenefitOlympiadModel,
    AdmissionBenefitOlympiadProfileModel,
    AdmissionBenefitRuleModel,
    IndividualAchievementPolicyModel,
    IndividualAchievementRuleModel,
    IngestRunModel,
    PolicyRuleRevisionModel,
    SourceSnapshotModel,
)
from andromeda.infrastructure.database.session import session_factory

_BENEFIT_MODELS = (
    AdmissionBenefitOlympiadModel,
    AdmissionBenefitOlympiadProfileModel,
    AdmissionBenefitRuleModel,
    IndividualAchievementPolicyModel,
    IndividualAchievementRuleModel,
)


def collect_report(session: Session) -> dict[str, object]:
    """Summarize existing provenance links; never infer missing source history."""
    table_reports: dict[str, dict[str, int]] = {}
    for model in _BENEFIT_MODELS:
        snapshot = aliased(SourceSnapshotModel)
        ingest_run = aliased(IngestRunModel)
        has_locator = or_(
            model.source_page.is_not(None),
            model.source_table.is_not(None),
            model.source_row.is_not(None),
            model.source_section.is_not(None),
            func.length(func.trim(model.source_locator)) > 0,
        )
        metadata_missing = or_(
            func.length(func.trim(model.source_url)) == 0,
            func.length(func.trim(model.document_title)) == 0,
            func.length(func.trim(model.document_kind)) == 0,
            func.length(func.trim(model.parser_version)) == 0,
        )
        row = session.execute(
            select(
                func.count().label("record_count"),
                func.coalesce(
                    func.sum(case((snapshot.content_sha256.is_(None), 1), else_=0)),
                    0,
                ).label("missing_snapshot_count"),
                func.coalesce(
                    func.sum(case((ingest_run.id.is_(None), 1), else_=0)), 0
                ).label("missing_ingest_run_count"),
                func.coalesce(func.sum(case((~has_locator, 1), else_=0)), 0).label(
                    "missing_locator_count"
                ),
                func.coalesce(func.sum(case((metadata_missing, 1), else_=0)), 0).label(
                    "incomplete_source_metadata_count"
                ),
            )
            .select_from(model)
            .outerjoin(
                snapshot,
                model.source_snapshot_hash == snapshot.content_sha256,
            )
            .outerjoin(ingest_run, model.source_run_id == ingest_run.id)
        ).one()
        table_reports[model.__tablename__] = {
            "records": int(row.record_count or 0),
            "missingSourceSnapshot": int(row.missing_snapshot_count or 0),
            "missingIngestRun": int(row.missing_ingest_run_count or 0),
            "missingDocumentLocator": int(row.missing_locator_count or 0),
            "incompleteSourceMetadata": int(row.incomplete_source_metadata_count or 0),
        }

    policy_revision_count, missing_owner_hash_count = session.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                PolicyRuleRevisionModel.owner_module.in_(
                                    ("admission_benefits", "admissions")
                                ),
                                PolicyRuleRevisionModel.owner_revision_hash.is_(None),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).select_from(PolicyRuleRevisionModel)
    ).one()
    return {
        "schemaVersion": "andromeda.legacy-provenance-report.v1",
        "mode": "read_only",
        "writesPerformed": False,
        "approvalInferred": False,
        "benefitOwnerRows": table_reports,
        "policyOwnerRevisionReferences": {
            "records": int(policy_revision_count or 0),
            "admissionsOwnerRowsMissingExactHash": int(missing_owner_hash_count or 0),
        },
        "limitations": [
            "No source identity, trust tier, publication date, approval, or system history is inferred.",
            "A legacy ACTIVE status is not treated as generic policy approval.",
            "Rows without complete source links require source-owner review; this report does not repair them.",
        ],
    }


def run(database_url: str | None = None) -> dict[str, object]:
    settings = Settings.from_environment(database_url)
    engine = create_engine_for_url(settings.database_url, **settings.engine_options)
    try:
        with session_factory(engine)() as session:
            report = collect_report(session)
        return {
            **report,
            "databaseTarget": redact_database_url(settings.database_url),
        }
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only inventory of recoverable legacy provenance; never backfills"
    )
    parser.add_argument("--database-url")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(run(args.database_url), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
