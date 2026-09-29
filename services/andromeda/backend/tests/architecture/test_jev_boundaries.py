from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src" / "andromeda"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return tuple(values)


def test_provider_packages_are_confined_to_infrastructure_adapters() -> None:
    violations: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        for imported in _imports(path):
            if imported == "typesafe_sdk" or imported.startswith("typesafe_sdk."):
                if not relative.startswith("infrastructure/jev/"):
                    violations.append(f"{relative} -> {imported}")
    assert violations == []


def test_optional_jev_adapters_do_not_leak_into_channels_or_subject_modules() -> None:
    violations: list[str] = []
    for root in (SOURCE_ROOT / "modules", BACKEND_ROOT.parent / "frontend-next" / "src"):
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            for imported in _imports(path):
                if imported == "andromeda.infrastructure.jev" or imported.startswith("andromeda.infrastructure.jev."):
                    violations.append(f"{path} -> {imported}")
    assert violations == []


def test_node_bridge_is_not_a_python_core_dependency() -> None:
    package = BACKEND_ROOT / "jev-tree-bridge" / "package.json"
    assert package.is_file()
    assert not (BACKEND_ROOT / "src" / "andromeda" / "modules" / "entity_resolution" / "services" / "jev_tree.py").exists()

