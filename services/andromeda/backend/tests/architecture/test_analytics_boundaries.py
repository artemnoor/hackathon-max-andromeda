from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
MODULES_ROOT = PROJECT_ROOT / "src" / "andromeda" / "modules"
FUTURE_MODULES = (
    "semantic",
    "program_analytics",
    "analytics",
    "entity_resolution",
    "conversation",
    "presentation",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "andromeda.api",
    "andromeda.composition",
    "andromeda.infrastructure",
    "andromeda.ingestion",
    "jev",
    "max",
    "sqlalchemy",
    "andromeda.modules.decision",
)


def _resolved_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def _future_module_files() -> tuple[Path, ...]:
    return tuple(
        path
        for module in FUTURE_MODULES
        for path in (MODULES_ROOT / module).rglob("*.py")
        if path.is_file()
    )


def test_future_subject_modules_do_not_cross_transport_or_infrastructure_boundary() -> None:
    violations: list[str] = []
    for path in _future_module_files():
        for imported in _resolved_imports(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_future_subject_module_allowlist_is_explicit() -> None:
    assert FUTURE_MODULES == (
        "semantic",
        "program_analytics",
        "analytics",
        "entity_resolution",
        "conversation",
        "presentation",
    )


def test_future_subject_modules_do_not_reuse_decision_telemetry_or_choice_state() -> None:
    violations: list[str] = []
    forbidden_tokens = ("decision_analytics", "decision_analytics_events", "DecisionContext")
    for path in _future_module_files():
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in source:
                violations.append(f"{path.relative_to(MODULES_ROOT)} contains {token}")
    assert violations == []


def test_future_query_contracts_have_no_raw_sql_call_sites() -> None:
    violations: list[str] = []
    raw_sql_names = {"text", "select", "insert", "update", "delete"}
    for path in _future_module_files():
        relative = path.relative_to(MODULES_ROOT).as_posix().lower()
        if "query" not in relative and "analytics" not in relative:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = node.func.id if isinstance(node.func, ast.Name) else None
            if function_name in raw_sql_names:
                violations.append(f"{path.relative_to(MODULES_ROOT)} calls {function_name}()")
    assert violations == []
