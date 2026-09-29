from __future__ import annotations

import ast
from pathlib import Path
import re

from andromeda.composition.compatibility import PROFTEST_COMPATIBILITY_SURFACES


BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src" / "andromeda"
PUBLIC_SURFACE_DECISIONS = {
    "ComparisonService": {
        "path": "modules/comparison/services/ports.py",
        "decision": "retain; consumed by ComparisonSummaryService",
    },
}

REMOVED_PUBLIC_SURFACES = {
    "ComparisonSummaryServicePort": "summary service is consumed as a concrete application service",
    "CurriculumRepository": "reader/writer split is the actual repository boundary",
    "ProgramRepository": "reader/writer split is the actual repository boundary",
    "DisciplineRepository": "reader/writer split is the actual repository boundary",
    "DisciplineIdentityResolver": "identity resolution is owned by DisciplineIdentityResolverService, not storage",
}


def _source_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "graphify-out" not in path.parts and "__pycache__" not in path.parts
    )


def _consumer_count(symbol: str, definition_path: Path) -> int:
    count = 0
    for path in _source_files():
        if path == definition_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count += sum(isinstance(node, ast.Name) and node.id == symbol for node in ast.walk(tree))
    return count


def test_dead_public_surface_report_has_an_explicit_decision() -> None:
    report: list[str] = []
    for symbol, metadata in PUBLIC_SURFACE_DECISIONS.items():
        definition_path = SOURCE_ROOT / metadata["path"]
        assert definition_path.is_file(), symbol
        consumer_count = _consumer_count(symbol, definition_path)
        decision = metadata["decision"]
        report.append(f"{symbol}: consumer_count={consumer_count}; decision={decision}")
        assert decision, report[-1]
    assert len(report) == len(PUBLIC_SURFACE_DECISIONS)


def test_mvp013_removed_surfaces_are_absent_from_runtime_source() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in _source_files())
    for symbol, reason in REMOVED_PUBLIC_SURFACES.items():
        assert re.search(rf"\bclass\s+{re.escape(symbol)}\s*(?:\(|:)", source) is None, (symbol, reason)
        assert re.search(rf"\b{re.escape(symbol)}\b", source) is None, (symbol, reason)


def test_compatibility_surfaces_are_finite_owned_and_expiring() -> None:
    assert {surface.module for surface in PROFTEST_COMPATIBILITY_SURFACES} == {
        "andromeda.modules.proftest.services.ranking",
        "andromeda.modules.proftest.services.matching",
        "andromeda.modules.proftest.services.explanations",
    }
    for surface in PROFTEST_COMPATIBILITY_SURFACES:
        relative = Path(*surface.module.split(".")).with_suffix(".py")
        path = SOURCE_ROOT / relative.relative_to("andromeda")
        source = path.read_text(encoding="utf-8")
        assert surface.owner
        assert surface.target
        assert surface.reason
        assert surface.removal_condition.startswith("Remove after MVP-012")
        assert surface.target.rsplit(".", 1)[0] in source
