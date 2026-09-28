from __future__ import annotations

import ast
from pathlib import Path

MODULE_ROOT = Path(__file__).parents[2] / "src" / "andromeda" / "modules" / "admission_benefits"
FORBIDDEN_PREFIXES = (
    "andromeda.api",
    "andromeda.composition",
    "andromeda.infrastructure",
    "andromeda.ingestion",
    "fastapi",
    "sqlalchemy",
    "jev",
    "openai",
)


def test_admission_benefits_domain_has_no_transport_or_external_decision_dependency() -> None:
    violations: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = None
            if isinstance(node, ast.Import):
                imported = node.names[0].name if node.names else None
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported = node.module
            if imported and any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(MODULE_ROOT)} -> {imported}")
    assert violations == []


def test_eligibility_services_are_deterministic_and_do_not_execute_external_expressions() -> None:
    service_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (MODULE_ROOT / "services").glob("*.py")
    ).casefold()
    assert "sqlalchemy" not in service_text
    assert "jev" not in service_text
    assert "execute_sql" not in service_text
