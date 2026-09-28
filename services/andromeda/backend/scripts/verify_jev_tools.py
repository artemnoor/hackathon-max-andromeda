"""Verify the pinned Jev ecosystem manifest against the current checkout."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("andromeda.scripts.verify_jev_tools")
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "evals" / "jev" / "TOOLS.lock"

EXPECTED_BRANCH = "feature/jev-ecosystem-stage-2"
# The tool manifest pins upstream tool commits, not an implementation commit.
# Keep checkout-head verification opt-in so every valid remediation commit does
# not require editing this verifier or bypassing it with a stale hash.
EXPECTED_HEAD: str | None = None


class ToolManifestError(RuntimeError):
    """Raised when the repository or optional tool manifest is inconsistent."""


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _load_manifest() -> dict[str, Any]:
    try:
        document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolManifestError(f"cannot read Jev tool manifest: {MANIFEST_PATH}") from exc
    if document.get("schema_version") != "jev-tools.v1" or not isinstance(
        document.get("tools"), dict
    ):
        raise ToolManifestError("invalid Jev tool manifest schema")
    return cast(dict[str, Any], document)


def _installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def verify(*, expected_branch: str = EXPECTED_BRANCH, expected_head: str | None = EXPECTED_HEAD) -> None:
    logger.debug("jev_tool_manifest_verification_started path=%s", MANIFEST_PATH)
    manifest = _load_manifest()
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    if branch != expected_branch:
        raise ToolManifestError(f"branch drift: expected {expected_branch}, observed {branch}")
    if expected_head is not None and head != expected_head:
        raise ToolManifestError(f"HEAD drift: expected {expected_head}, observed {head}")
    if expected_head is None:
        logger.info("jev_tool_manifest_head_check_skipped reason=manifest_pins_tool_commits")

    required = {"jevcal", "jev-align", "system-one-adapter", "typesafe-sdk", "jevql", "jev-tree"}
    tools = manifest["tools"]
    missing = required.difference(tools)
    if missing:
        raise ToolManifestError(f"manifest missing tools: {sorted(missing)}")

    for name, raw_tool in tools.items():
        if not isinstance(raw_tool, dict):
            raise ToolManifestError(f"tool entry must be an object: {name}")
        for field in ("source", "commit", "role", "runtime_dependency", "canonical_import_allowed"):
            if field not in raw_tool:
                raise ToolManifestError(f"tool entry missing {field}: {name}")
        if raw_tool["canonical_import_allowed"] is not False:
            raise ToolManifestError(f"optional Jev tool may not enter canonical imports: {name}")

    logger.info(
        "jev_tool_manifest_verified branch=%s head=%s tools=%s",
        branch,
        head[:12],
        len(tools),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", help="optionally require a specific checkout HEAD")
    parser.add_argument("--allow-head", help="legacy alias for --expected-head")
    parser.add_argument("--allow-branch", help="override expected branch for a controlled audit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        verify(
            expected_branch=args.allow_branch or EXPECTED_BRANCH,
            expected_head=(
                args.expected_head
                or args.allow_head
                or os.environ.get("ANDROMEDA_JEV_EXPECTED_HEAD")
                or EXPECTED_HEAD
            ),
        )
    except ToolManifestError as exc:
        logger.error("jev_tool_manifest_verification_failed reason=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
