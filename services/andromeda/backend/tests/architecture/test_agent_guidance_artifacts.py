from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
ANDROMEDA_ROOT = PROJECT_ROOT.parent
MONOREPO_ROOT = PROJECT_ROOT.parents[2]


def _read(relative: str) -> str:
    return (ANDROMEDA_ROOT / relative).read_text(encoding="utf-8")


def test_persistent_guidance_artifacts_exist_and_are_utf8() -> None:
    for path in (
        ANDROMEDA_ROOT / "AGENTS.md",
        MONOREPO_ROOT / "AGENTS.md",
        ANDROMEDA_ROOT / "docs" / "architecture.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert content.strip()
        assert "Andromeda" in content


def test_agents_workflow_and_safety_rules_are_explicit() -> None:
    content = _read("AGENTS.md")
    for required in (
        "context → analysis → plan → implementation → tests → verification",
        "Не меняй product scope",
        "force-push",
        "canonical IDs",
        "git diff --check",
    ):
        assert required in content


def test_public_docs_cover_current_modules_and_multi_university_direction() -> None:
    content = "\n".join(
        _read(relative)
        for relative in (
            "README.md",
            "docs/architecture.md",
            "docs/ingestion-adapters.md",
        )
    )
    normalized = content.casefold()
    for required in (
        "BMSTU",
        "multi-university",
        "adapter",
        "events",
        "campus",
        "admission_fit",
        "recommendations",
        "personal-route",
    ):
        assert required.casefold() in normalized


def test_public_architecture_docs_cover_automatable_invariants() -> None:
    content = "\n".join(
        (_read("AGENTS.md"), _read("docs/architecture.md"))
    )
    normalized = content.casefold()
    for required in (
        "modular monolith",
        "contracts.public",
        "repository/ports.py",
        "SQLAlchemy",
        "Content Fit",
        "Admission Fit",
        "Career Fit",
        "Workload readiness",
        "OpenAPI",
        "generated",
        "микросервисы",
        "Kafka",
        "CQRS",
    ):
        assert required.casefold() in normalized


def test_architecture_doc_matches_current_event_and_campus_scope() -> None:
    content = _read("docs/architecture.md")
    for required in (
        "modules/events",
        "modules/campus",
        "map-agnostic spatial data",
        "route optimizer",
        "compatibility facades",
    ):
        assert required in content
