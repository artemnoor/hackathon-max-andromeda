"""Human-gated jev-align proposal workflow for semantic artifacts."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from andromeda.modules.semantic.contracts.review import SemanticReviewQueueItem
from andromeda.modules.semantic.contracts.review_artifacts import SemanticMappingProposal, SemanticReviewAction
from andromeda.modules.semantic.services.review_workflow import SemanticReviewWorkflow
from andromeda.infrastructure.jev.align import JevAlignConfig, JevAlignSession, JevAlignStoryInput, create_typesafe_backend


logger = logging.getLogger("andromeda.scripts.jev_align_workflow")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run explicit export/review/publish jev-align workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--queue", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--feature-id", required=True)
    export.add_argument("--tool-version", default="jev-align.v1")
    review = subparsers.add_parser("review")
    review.add_argument("--manifest", type=Path, required=True)
    review.add_argument("--proposal-id", required=True)
    review.add_argument("--action", choices=tuple(action.value for action in SemanticReviewAction), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--source-hash")
    publish = subparsers.add_parser("publish")
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    publish.add_argument("--artifact-id", required=True)
    publish.add_argument("--diff-report", action="store_true")
    align_init = subparsers.add_parser("align-init", help="initialize a real upstream jev-align run")
    align_init.add_argument("--stories", type=Path, required=True, help="JSONL rows with id and fields")
    align_init.add_argument("--features", type=Path, required=True, help="JSON object: feature -> [true, false]")
    align_init.add_argument("--instructions", required=True)
    align_init.add_argument("--run-dir", type=Path, required=True)
    align_init.add_argument("--model", default="jev-1.13.0")
    align_init.add_argument("--batch-size", type=int, default=5)
    align_acquire = subparsers.add_parser("align-acquire", help="run upstream uncertainty acquisition")
    align_acquire.add_argument("--run-dir", type=Path, required=True)
    align_acquire.add_argument("--model", default="jev-1.13.0")
    align_label = subparsers.add_parser("align-label", help="persist a human label in the upstream run")
    align_label.add_argument("--run-dir", type=Path, required=True)
    align_label.add_argument("--story-id", required=True)
    align_label.add_argument("--labels", required=True, help="comma-separated semantic feature IDs")
    align_label.add_argument("--rationale")
    align_label.add_argument("--acquired-by", choices=("ambiguous", "exploration", "holdout"), required=True)
    align_label.add_argument("--probability", type=float, required=True)
    align_label.add_argument("--model", default="jev-1.13.0")
    align_optimize = subparsers.add_parser("align-optimize", help="run upstream GEPA optimization")
    align_optimize.add_argument("--run-dir", type=Path, required=True)
    align_optimize.add_argument("--model", default="jev-1.13.0")
    align_decide = subparsers.add_parser("align-decide", help="accept/reject upstream candidate")
    align_decide.add_argument("--run-dir", type=Path, required=True)
    align_decide.add_argument("--decision", choices=("accept", "reject"), required=True)
    align_decide.add_argument("--model", default="jev-1.13.0")
    args = parser.parse_args(argv)

    if args.command.startswith("align-"):
        return _run_upstream_align(args)

    workflow = SemanticReviewWorkflow()
    if args.command == "export":
        queue = SemanticReviewQueueItem.model_validate(
            json.loads(args.queue.read_text(encoding="utf-8")), strict=False
        )
        feature = next((value for value in queue.values if value.feature_id == args.feature_id), None)
        if feature is None:
            parser.error("the requested feature must be present in the typed review queue row")
        proposal = workflow.propose(queue, feature_id=args.feature_id, feature=feature, tool_version=args.tool_version)
        _write_manifest(args.output, (proposal,))
        return 0

    proposals = _read_manifest(args.manifest)
    if args.command == "review":
        selected = next((proposal for proposal in proposals if proposal.proposal_id == args.proposal_id), None)
        if selected is None:
            parser.error("proposal was not found")
        updated = workflow.review(
            selected,
            SemanticReviewAction(args.action),
            reviewer=args.reviewer,
            current_source_hash=args.source_hash,
        )
        _write_manifest(args.manifest, tuple(updated if proposal.proposal_id == args.proposal_id else proposal for proposal in proposals))
        return 0

    artifact = workflow.publish(
        proposals,
        artifact_id=args.artifact_id,
        semantic_version=proposals[0].semantic_version if proposals else "semantic-taxonomy.v1",
        classifier_version=proposals[0].classifier_version if proposals else "semantic-classifier.v1",
        diff_report_present=args.diff_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


def _write_manifest(path: Path, proposals: tuple[SemanticMappingProposal, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([proposal.model_dump(mode="json") for proposal in proposals], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_manifest(path: Path) -> tuple[SemanticMappingProposal, ...]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("review manifest must be a list")
    return tuple(SemanticMappingProposal.model_validate(row, strict=False) for row in rows)


def _run_upstream_align(args: argparse.Namespace) -> int:
    if args.command == "align-init":
        rows = [json.loads(line) for line in args.stories.read_text(encoding="utf-8").splitlines() if line.strip()]
        stories = tuple(
            JevAlignStoryInput(story_id=str(row["id"]), fields={str(k): str(v) for k, v in row["fields"].items()})
            for row in rows
        )
        criteria_raw = json.loads(args.features.read_text(encoding="utf-8"))
        criteria = {str(key): (str(value[0]), str(value[1])) for key, value in criteria_raw.items()}
        backend = create_typesafe_backend(model=args.model, concurrency=1)
        JevAlignSession.create(
            stories,
            config=JevAlignConfig(
                run_directory=args.run_dir,
                task_instructions=args.instructions,
                feature_criteria=criteria,
                model=args.model,
                batch_size=args.batch_size,
            ),
            backend=backend,
        )
        logger.info("jev_align_upstream_run_initialized run_dir=%s stories=%d", args.run_dir, len(stories))
        return 0

    backend = create_typesafe_backend(model=args.model, concurrency=1)
    session = JevAlignSession.open(args.run_dir, backend=backend)
    if args.command == "align-acquire":
        acquisitions, _ = session.acquire()
        print(json.dumps([item.model_dump(mode="json") for item in acquisitions], ensure_ascii=False, indent=2))
        return 0
    if args.command == "align-label":
        session.add_label(
            story_id=args.story_id,
            label=[item.strip() for item in args.labels.split(",") if item.strip()],
            rationale=args.rationale,
            acquired_by=args.acquired_by,
            probability=args.probability,
        )
        return 0
    if args.command == "align-optimize":
        report = session.optimize()
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0
    session.decide(args.decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
