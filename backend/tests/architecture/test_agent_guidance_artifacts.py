from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def _read(relative: str) -> str:
    return (PROJECT_ROOT.parent / relative).read_text(encoding="utf-8")


def test_persistent_guidance_artifacts_exist_and_are_utf8() -> None:
    for relative in ("AGENTS.md", ".ai-factory/DESCRIPTION.md", ".ai-factory/RULES.md"):
        content = _read(relative)
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


def test_description_covers_current_modules_and_multi_university_direction() -> None:
    content = _read(".ai-factory/DESCRIPTION.md")
    for required in (
        "BMSTU",
        "multi-university",
        "ingestion/universities/<university>",
        "events",
        "campus",
        "admission_fit",
        "recommendations",
        "Personal Route",
    ):
        assert required in content


def test_rules_cover_automatable_architecture_invariants() -> None:
    content = _read(".ai-factory/RULES.md")
    for required in (
        "modular monolith",
        "domain`, `contracts`, `services`, `repository",
        "contracts.public",
        "repository.ports",
        "SQLAlchemy",
        "Новый вуз = новый adapter",
        "Content Fit",
        "Admission Fit",
        "Career Fit",
        "Workload Readiness",
        "OpenAPI",
        "generated frontend clients",
        "Microservices",
        "Kafka",
        "CQRS",
    ):
        assert required in content


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
