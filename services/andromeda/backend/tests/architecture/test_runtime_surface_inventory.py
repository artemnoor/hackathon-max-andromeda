from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = PROJECT_ROOT
RUNTIME_ROOTS = (
    BACKEND_ROOT / "src" / "andromeda",
    BACKEND_ROOT / "scripts",
)

# Legacy parser imports are forbidden in every executable backend root.
LEGACY_IMPORT_ALLOWLIST: set[str] = set()


def _python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for root in RUNTIME_ROOTS
        for path in root.rglob("*.py")
        if path.is_file()
    )


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def test_canonical_runtime_roots_exist() -> None:
    assert (PROJECT_ROOT / "src" / "andromeda" / "api" / "main.py").is_file()
    assert (PROJECT_ROOT / "src" / "andromeda" / "ingestion" / "universities" / "bmstu" / "adapter.py").is_file()
    assert (PROJECT_ROOT.parent / "frontend-next" / "package.json").is_file()


def test_duplicate_runtime_roots_are_removed() -> None:
    retired_manifests = (
        PROJECT_ROOT.parent / "frontend" / "package.json",
        PROJECT_ROOT.parent / "frontend" / "vite.config.ts",
        PROJECT_ROOT.parent / "proftest-spike" / "README.md",
        PROJECT_ROOT.parent / "proftest-spike" / "backend" / "pyproject.toml",
        PROJECT_ROOT.parent / "proftest-spike" / "scripts" / "run_spike_demo.py",
        PROJECT_ROOT / "src" / "bmstu_parser" / "__init__.py",
    )
    assert all(not path.exists() for path in retired_manifests)


def test_legacy_runtime_imports_are_explicitly_scoped() -> None:
    violations: list[str] = []
    for path in _python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        has_legacy_import = any(
            imported == "bmstu_parser" or imported.startswith("bmstu_parser.")
            for imported in _imports(path)
        )
        if has_legacy_import and relative not in LEGACY_IMPORT_ALLOWLIST:
            violations.append(relative)
    assert violations == []
