from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from andromeda.infrastructure.config import Settings, redact_database_url
from andromeda.infrastructure.database import create_engine_for_url
from andromeda.infrastructure.repositories.admission_benefits import (
    SqlAlchemyAdmissionBenefitsRepository,
)
from andromeda.ingestion.universities.bmstu.admission_benefits.release_gate import (
    evaluate_bmstu_admission_benefits_release,
)
from andromeda.shared.contracts.enums import EducationLevel

logger = logging.getLogger("andromeda.bmstu_admission_benefits_release_gate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check persisted BMSTU admission-benefit data before production serving"
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--education-level",
        choices=tuple(item.value for item in EducationLevel),
    )
    parser.add_argument("--database-url")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_environment(args.database_url)
    engine = create_engine_for_url(settings.database_url, **settings.engine_options)
    try:
        with Session(engine) as session:
            snapshot = SqlAlchemyAdmissionBenefitsRepository(session).get_catalog(
                "university:bmstu",
                args.year,
                EducationLevel(args.education_level) if args.education_level else None,
            )
        if snapshot is None:
            logger.error(
                "bmstu_admission_benefits_release_gate_missing_snapshot year=%d",
                args.year,
            )
            return 2
        report = evaluate_bmstu_admission_benefits_release(
            snapshot,
            education_level=EducationLevel(args.education_level)
            if args.education_level
            else None,
        )
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "databaseTarget": redact_database_url(settings.database_url),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        logger.info(
            "bmstu_admission_benefits_release_gate_complete year=%d ready=%s blockers=%d active=%d review=%d",
            args.year,
            report.production_ready,
            len(report.blockers),
            report.active_rules,
            report.review_required_rules,
        )
        return 0 if report.production_ready else 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
