from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
ANDROMEDA_ROOT = PROJECT_ROOT / "src" / "andromeda"
SUBJECT_MODULES = {
    path.name
    for path in (ANDROMEDA_ROOT / "modules").iterdir()
    if path.is_dir() and not path.name.startswith("_")
}


def _subject_files() -> tuple[Path, ...]:
    return tuple((ANDROMEDA_ROOT / "modules").glob("*/*/*.py"))


def _resolved_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    relative_parts = path.relative_to(ANDROMEDA_ROOT).with_suffix("").parts
    package_parts = ("andromeda",) + relative_parts[:-1]
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level == 0:
            if node.module:
                imports.append(node.module)
            continue
        base_length = len(package_parts) - (node.level - 1)
        if base_length < 1:
            continue
        base = package_parts[:base_length]
        if node.module:
            imports.append(".".join(base + tuple(node.module.split("."))))
        else:
            imports.extend(".".join(base + (alias.name,)) for alias in node.names)
    return tuple(imports)


def _layer(path: Path) -> tuple[str, str] | None:
    relative = path.relative_to(ANDROMEDA_ROOT).parts
    if len(relative) < 3 or relative[0] != "modules" or relative[1] not in SUBJECT_MODULES:
        return None
    return relative[1], relative[2]


def _is_layer_violation(relative_path: str, imported: str) -> bool:
    parts = Path(relative_path).as_posix().split("/")
    if len(parts) < 4 or parts[0] != "modules":
        return False
    module, layer = parts[1], parts[2]
    if layer == "domain" and (
        imported.startswith(f"andromeda.modules.{module}.services")
        or imported.startswith(f"andromeda.modules.{module}.repository")
    ):
        return True
    if layer == "contracts" and (
        imported.startswith("andromeda.infrastructure")
        or imported.startswith("andromeda.api")
        or imported == "sqlalchemy"
        or imported.startswith("sqlalchemy.")
    ):
        return True
    if layer == "repository" and parts[3] == "ports.py" and (
        imported.startswith("andromeda.infrastructure")
        or imported == "sqlalchemy"
        or imported.startswith("sqlalchemy.")
    ):
        return True
    return False


def test_subject_layer_direction_is_explicit_and_clean() -> None:
    violations: list[str] = []
    for path in _subject_files():
        layer_info = _layer(path)
        if layer_info is None:
            continue
        for imported in _resolved_imports(path):
            if _is_layer_violation(path.relative_to(ANDROMEDA_ROOT).as_posix(), imported):
                violations.append(f"{path.relative_to(ANDROMEDA_ROOT)} -> {imported}")
    assert violations == []


def test_layer_gate_rejects_a_deliberate_illegal_domain_import() -> None:
    assert _is_layer_violation(
        "modules/programs/domain/entities.py",
        "andromeda.modules.programs.services.programs",
    )
    assert _is_layer_violation(
        "modules/programs/contracts/public.py",
        "andromeda.infrastructure.database.models",
    )
    assert _is_layer_violation(
        "modules/programs/repository/ports.py",
        "sqlalchemy.orm",
    )
