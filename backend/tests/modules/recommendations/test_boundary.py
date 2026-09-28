from __future__ import annotations

import ast
from pathlib import Path


MODULE_ROOT = Path(__file__).parents[3] / "src" / "andromeda" / "modules" / "recommendations"


def test_recommendation_module_does_not_import_storage_api_or_parser() -> None:
    forbidden = ("andromeda.infrastructure", "andromeda.api", "sqlalchemy", "bmstu_parser", "proftest_spike")
    violations: list[str] = []
    for path in MODULE_ROOT.glob("**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = ""
            if isinstance(node, ast.Import):
                imported = ",".join(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported = node.module or ""
            if any(fragment in imported for fragment in forbidden):
                violations.append(f"{path.name} -> {imported}")
    assert violations == []
