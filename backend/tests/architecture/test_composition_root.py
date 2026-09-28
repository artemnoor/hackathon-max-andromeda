from __future__ import annotations

import ast
from pathlib import Path

from andromeda.api.main import create_app
from andromeda.composition import AndromedaContainer


BACKEND_ROOT = Path(__file__).parents[2]
SERVICES_PATH = BACKEND_ROOT / "src" / "andromeda" / "api" / "dependencies" / "services.py"
INGESTION_RUNNER_PATH = BACKEND_ROOT / "scripts" / "run_andromeda_ingestion.py"

EXPECTED_CONTAINER_METHODS = {
    "program_reader",
    "university_reader",
    "curriculum_reader",
    "discipline_reader",
    "admission_reader",
    "admission_service",
    "admission_fit_reader",
    "admission_fit_service",
    "comparison_service",
    "comparison_summary_service",
    "proftest_catalog_reader",
    "proftest_catalog_service",
    "user_profile_repository",
    "profile_persistence_service",
    "current_user_profile_reader",
    "recommendation_service",
    "decision_context_repository",
    "decision_candidate_source",
    "decision_candidate_pipeline",
    "decision_analytics_writer",
    "decision_analytics_reader",
    "decision_analytics_service",
    "decision_service",
    "proftest_service",
    "proftest_session_repository",
    "proftest_session_service",
    "current_recommendation_service",
    "event_reader",
    "event_service",
    "campus_point_reader",
    "campus_service",
    "personal_route_service",
    "account_repository",
    "auth_service",
    "ingestion_run_reader",
    "ingestion_retry_executor",
    "ingestion_run_service",
}


def _function_nodes(path: Path) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _contains_composition_dependency(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "get_composition_root"
        for node in ast.walk(function)
    )


def test_application_installs_one_container_for_the_existing_engine_and_settings() -> None:
    app = create_app("sqlite:///:memory:")
    try:
        assert isinstance(app.state.container, AndromedaContainer)
        assert app.state.container.engine is app.state.engine
        assert app.state.container.settings is app.state.settings
    finally:
        app.state.engine.dispose()


def test_container_owns_every_api_service_provider_surface() -> None:
    methods = {
        name
        for name in dir(AndromedaContainer)
        if not name.startswith("_") and callable(getattr(AndromedaContainer, name, None))
    }
    assert EXPECTED_CONTAINER_METHODS <= methods

    providers = tuple(node for node in _function_nodes(SERVICES_PATH) if node.name.startswith("get_"))
    assert providers
    assert all(_contains_composition_dependency(provider) for provider in providers)


def test_ingestion_runner_uses_the_same_composition_boundary() -> None:
    source = INGESTION_RUNNER_PATH.read_text(encoding="utf-8")
    assert "from andromeda.composition import build_container" in source
    assert "container = build_container(engine, settings)" in source
    assert "container.ingestion" in source
    assert "SqlAlchemyIngestionRepository" not in source
