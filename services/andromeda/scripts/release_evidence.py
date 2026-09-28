"""Create a safe, metadata-only release evidence ledger.

The command deliberately never promotes a release by itself. It records the
immutable inputs that a reviewer must compare with passing CI, deployment,
restore, and (when explicitly authorized) live-source artifacts.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "release" / "mvp-production-level-evidence.json"

CHECKLIST = (
    (1, "Primary user flows are end-to-end"),
    (2, "No misleading product-visible placeholders"),
    (3, "BMSTU/HSE ingestion is reproducible"),
    (4, "Ingestion failures are diagnosable and recoverable"),
    (5, "PostgreSQL schema/migrations/readiness are stable"),
    (6, "Critical business rules have meaningful tests"),
    (7, "Full CI passes from a clean checkout"),
    (8, "Production-like deployment is runnable"),
    (9, "Frontend states are handled honestly"),
    (10, "Recommendations explain evidence and uncertainty"),
    (11, "Missing data is typed and actionable"),
    (12, "Security baseline passes"),
    (13, "Documentation matches current code and operations"),
    (14, "Critical paths have no unowned tracer shortcut"),
    (15, "Production smoke passes after clean deploy/restore"),
    (16, "New university onboarding stays adapter/data scoped"),
)


def _git(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_bytes(*arguments: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _worktree_state() -> dict[str, Any]:
    """Return secret-free, attributable state for the release candidate.

    A release report must not make a dirty worktree look like ``HEAD`` is the
    release revision.  We retain counts and hashes only; path names and diff
    contents are intentionally excluded from the artifact.
    """

    status = _git_bytes("status", "--porcelain=v1", "-z")
    diff = _git_bytes("diff", "--binary")
    untracked_manifest = _git_bytes("ls-files", "--others", "--exclude-standard", "-z")
    if status is None or diff is None or untracked_manifest is None:
        return {
            "clean": None,
            "statusAvailable": False,
        }

    entries = [entry for entry in status.split(b"\0") if entry]
    tracked_changes = sum(not entry.startswith(b"??") for entry in entries)
    untracked_paths = sum(bool(path) for path in untracked_manifest.split(b"\0"))
    return {
        "clean": not entries,
        "statusAvailable": True,
        "trackedChangeCount": tracked_changes,
        "untrackedPathCount": untracked_paths,
        "trackedDiffSha256": _bytes_sha256(diff),
        "untrackedPathManifestSha256": _bytes_sha256(untracked_manifest),
    }


def _sha256(relative_path: str) -> str | None:
    path = ROOT / relative_path
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report() -> dict[str, Any]:
    return {
        "generatedAtUtc": datetime.now(UTC).isoformat(),
        "repository": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "migrationHistoryTip": _git("-C", "backend", "log", "-1", "--format=%s", "--", "alembic/versions"),
            "worktree": _worktree_state(),
        },
        "immutableInputs": {
            "backendUvLockSha256": _sha256("backend/uv.lock"),
            "frontendPackageLockSha256": _sha256("frontend-next/package-lock.json"),
            "mvpBaselineManifestSha256": _sha256("backend/tests/fixtures/mvp/baseline_manifest.json"),
            "recommendationCorpusSha256": _sha256("backend/tests/fixtures/recommendations/regression-v1.json"),
            "proftestCorpusSha256": _sha256("backend/tests/fixtures/proftest/signal-corpus-v3.json"),
        },
        "releaseDecision": "NOT_READY",
        "checklist": [
            {"id": item_id, "criterion": criterion, "status": "UNKNOWN", "evidence": [], "owner": "release owner"}
            for item_id, criterion in CHECKLIST
        ],
        "rule": "UNKNOWN is not PASS; change the decision only after attaching safe CI/deployment evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Write safe MVP Production Level release metadata")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="fail after writing metadata unless the release worktree is clean",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_report()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    display = output.relative_to(ROOT) if output.is_relative_to(ROOT) else output
    print(f"Release evidence metadata written to {display}")
    print("Decision remains NOT_READY until every checklist item has attached evidence.")
    if args.require_clean and report["repository"]["worktree"].get("clean") is not True:
        print("Release evidence refused: candidate worktree is not clean.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
