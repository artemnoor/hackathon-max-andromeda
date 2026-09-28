from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
ANDROMEDA_ROOT = PROJECT_ROOT / "src" / "andromeda"
CORE_SUBJECT_MODULES = (
    "universities",
    "programs",
    "curricula",
    "disciplines",
    "comparison",
    "decision",
    "proftest",
    "recommendations",
    "admissions",
    "admission_fit",
    "events",
    "campus",
    "personal_route",
    "admin_ops",
    "auth",
    "university_admin",
    "admission_benefits",
    "knowledge",
    "policy",
)
OPTIONAL_ANALYTICS_MODULES = (
    "semantic",
    "program_analytics",
    "analytics",
    "entity_resolution",
    "conversation",
    "presentation",
)
SUBJECT_MODULES = CORE_SUBJECT_MODULES + OPTIONAL_ANALYTICS_MODULES
SUBJECT_LAYERS = ("domain", "contracts", "services", "repository")
FORBIDDEN_SUBJECT_IMPORTS = (
    "andromeda.infrastructure",
    "andromeda.api",
    "andromeda.composition",
    "andromeda.ingestion",
    "sqlalchemy",
    "bmstu_parser",
    "proftest_spike",
)
COMPATIBILITY_FACADE_IMPORTS = {
    "modules/proftest/services/ranking.py": {
        "andromeda.modules.recommendations.services.ranking": (
            "RankedFingerprint",
            "RankingService",
        ),
    },
    "modules/proftest/services/matching.py": {
        "andromeda.modules.recommendations.services.scoring": (
            "MatchingService",
            "RecommendationScoringService",
        ),
    },
    "modules/proftest/services/explanations.py": {
        "andromeda.modules.recommendations.services.explanations": (
            "ExplanationBuilder",
        ),
    },
}

# The generic assistant is the application-level coordinator: it composes the
# already existing analytics/admission engines and the channel-neutral envelope
# builder. Those three concrete services remain outside domain contracts, but
# the dependency is intentionally isolated to this one orchestration file.
ORCHESTRATOR_IMPORTS = {
    "modules/conversation/services/assistant.py": {
        "andromeda.modules.admission_fit.services.admission_fit",
        "andromeda.modules.analytics.services.executor",
        "andromeda.modules.presentation.services.envelope_builder",
        "andromeda.modules.presentation.services.knowledge_response",
    },
    # The metric resolver is a deliberately thin catalog adapter. Its
    # default registry is the analytics-owned allow-list, while all returned
    # values remain entity-resolution contracts.
    "modules/entity_resolution/services/resolvers.py": {
        "andromeda.modules.analytics.domain.metric_registry",
    },
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ANDROMEDA_ROOT).with_suffix("").parts)


def _subject_module(path: Path) -> str | None:
    relative = path.relative_to(ANDROMEDA_ROOT).parts
    if (
        len(relative) >= 2
        and relative[0] == "modules"
        and relative[1] in SUBJECT_MODULES
    ):
        return relative[1]
    return None


def _import_names(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def _import_bindings(path: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bindings: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            bindings.append((node.module, tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings.append(
                    (alias.name, (alias.asname or alias.name.split(".")[-1],))
                )
    return tuple(bindings)


def _subject_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in ANDROMEDA_ROOT.glob("modules/**/*.py")
        if _subject_module(path) is not None
    )


def _resolved_import_names(path: Path, tree: ast.AST) -> tuple[str, ...]:
    names = list(_import_names(tree))
    relative_parts = path.relative_to(ANDROMEDA_ROOT).with_suffix("").parts
    package_parts = ("andromeda",) + relative_parts[:-1]
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        base_length = len(package_parts) - (node.level - 1)
        if base_length < 1:
            continue
        base = package_parts[:base_length]
        if node.module:
            names.append(".".join(base + tuple(node.module.split("."))))
        else:
            names.extend(".".join(base + (alias.name,)) for alias in node.names)
    return tuple(names)


def _cross_module_imports(path: Path) -> tuple[str, ...]:
    current = _subject_module(path)
    if current is None:
        return ()
    imports = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for imported in _resolved_import_names(path, tree):
        prefix = "andromeda.modules."
        if not imported.startswith(prefix):
            continue
        target = imported[len(prefix) :].split(".", 1)[0]
        if target != current:
            imports.append(imported)
    return tuple(imports)


def _is_allowed_cross_module_import(path: Path, imported: str) -> bool:
    relative = path.relative_to(ANDROMEDA_ROOT).as_posix()
    parts = imported.split(".")
    if (
        len(parts) == 5
        and tuple(parts[:2]) == ("andromeda", "modules")
        and parts[3] == "contracts"
    ):
        return True
    if (
        len(parts) == 5
        and tuple(parts[:2]) == ("andromeda", "modules")
        and tuple(parts[-2:]) == ("repository", "ports")
    ):
        return True
    if imported in ORCHESTRATOR_IMPORTS.get(relative, set()):
        return True
    return imported in COMPATIBILITY_FACADE_IMPORTS.get(relative, {})


def test_subject_module_registry_covers_all_current_modules_and_layers() -> None:
    modules_root = ANDROMEDA_ROOT / "modules"
    actual_modules = {
        path.name
        for path in modules_root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    }
    expected_modules = set(CORE_SUBJECT_MODULES) | {
        module
        for module in OPTIONAL_ANALYTICS_MODULES
        if (modules_root / module).is_dir()
    }
    assert actual_modules == expected_modules

    expected_layers = {
        f"modules/{module}/{layer}"
        for module in expected_modules
        for layer in SUBJECT_LAYERS
    }
    actual_layers = {
        path.relative_to(ANDROMEDA_ROOT).as_posix()
        for path in modules_root.glob("*/*")
        if path.is_dir() and path.name in SUBJECT_LAYERS
    }
    assert actual_layers == expected_layers


def test_subject_modules_do_not_import_outer_boundaries_or_legacy_packages() -> None:
    violations: list[str] = []
    for path in _subject_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = _resolved_import_names(path, tree)
        for imported in imports:
            if any(
                imported == forbidden or imported.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_SUBJECT_IMPORTS
            ):
                violations.append(f"{_module_name(path)} -> {imported}")
    assert violations == []


def test_subject_modules_use_only_public_cross_module_surfaces() -> None:
    violations: list[str] = []
    for path in _subject_python_files():
        for imported in _cross_module_imports(path):
            if not _is_allowed_cross_module_import(path, imported):
                violations.append(f"{_module_name(path)} -> {imported}")
    assert violations == []


def test_cross_module_policy_is_narrow_and_explicit() -> None:
    comparison_file = (
        ANDROMEDA_ROOT / "modules" / "comparison" / "services" / "aggregation.py"
    )
    facade_file = ANDROMEDA_ROOT / "modules" / "proftest" / "services" / "ranking.py"

    assert _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.contracts.public",
    )
    assert _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.repository.ports",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.domain.areas",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.services.reader",
    )
    assert _is_allowed_cross_module_import(
        facade_file,
        "andromeda.modules.recommendations.services.ranking",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.recommendations.services.ranking",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.contracts.public.internal",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.repository.ports.internal",
    )
    assert not _is_allowed_cross_module_import(
        comparison_file,
        "andromeda.modules.disciplines.domain.foo.contracts.public",
    )
    relative_import = ast.parse(
        "from ...recommendations.services import RecommendationService"
    )
    assert "andromeda.modules.recommendations.services" in _resolved_import_names(
        comparison_file, relative_import
    )


def test_compatibility_facades_have_exact_documented_imports() -> None:
    for relative, expected in COMPATIBILITY_FACADE_IMPORTS.items():
        path = ANDROMEDA_ROOT / relative
        assert dict(_import_bindings(path)) == expected


def test_jev_and_max_imports_are_adapter_only() -> None:
    violations: list[str] = []
    for path in ANDROMEDA_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(ANDROMEDA_ROOT).parts
        allowed = "composition" in relative_parts or "adapters" in relative_parts
        for imported in _resolved_import_names(
            path, ast.parse(path.read_text(encoding="utf-8"))
        ):
            normalized = imported.lower()
            if (
                normalized in {"jev", "max"} or normalized.startswith(("jev.", "max."))
            ) and not allowed:
                violations.append(f"{_module_name(path)} -> {imported}")
    assert violations == []


def test_query_contracts_and_response_envelopes_do_not_contain_raw_sql_or_transport_types() -> (
    None
):
    violations: list[str] = []
    transport_prefixes = (
        "fastapi",
        "sqlalchemy",
        "max",
        "jev",
    )
    sql_tokens = ("select ", "insert ", "update ", "delete ", " from ")
    for module in SUBJECT_MODULES:
        module_root = ANDROMEDA_ROOT / "modules" / module
        if not module_root.is_dir():
            continue
        for path in module_root.rglob("*.py"):
            relative = path.relative_to(module_root).as_posix().lower()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = _resolved_import_names(path, tree)
            if (
                "queryspec" in path.name.lower()
                or "response" in path.name.lower()
                or "policy" in relative
            ):
                for imported in imports:
                    if any(
                        imported == prefix or imported.startswith(f"{prefix}.")
                        for prefix in transport_prefixes
                    ):
                        violations.append(f"{_module_name(path)} -> {imported}")
                source = path.read_text(encoding="utf-8").lower()
                if any(token in source for token in sql_tokens):
                    violations.append(f"{_module_name(path)} contains raw SQL text")
    assert violations == []
