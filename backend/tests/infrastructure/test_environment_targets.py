from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]
COMPOSE_FILE = REPOSITORY_ROOT / "ops" / "postgres" / "docker-compose.yml"


def test_compose_defines_isolated_development_and_staging_targets() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "postgres-dev:" in compose
    assert "postgres-staging:" in compose
    assert "andromeda-dev-data" in compose
    assert "andromeda-staging-data" in compose
    assert "ANDROMEDA_DEV_DB" in compose
    assert "ANDROMEDA_STAGING_DB" in compose
    assert 'profiles: ["development"]' in compose
    assert 'profiles: ["staging"]' in compose


def test_environment_examples_use_distinct_postgresql_databases() -> None:
    development = (REPOSITORY_ROOT / ".env.development.example").read_text(encoding="utf-8")
    staging = (REPOSITORY_ROOT / ".env.staging.example").read_text(encoding="utf-8")

    assert "ANDROMEDA_ENV=development" in development
    assert "andromeda_dev" in development
    assert "ANDROMEDA_ENV=staging" in staging
    assert "andromeda_staging" in staging
    assert "andromeda_dev" not in staging
    assert "andromeda_staging" not in development


def test_production_like_runtime_uses_the_8020_internal_contract() -> None:
    compose = (REPOSITORY_ROOT / "deploy" / "yc" / "compose.yaml").read_text(encoding="utf-8")
    server_api = (REPOSITORY_ROOT / "frontend-next" / "src" / "lib" / "server-api.ts").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8")

    assert "ANDROMEDA_INTERNAL_API_URL: http://backend:8020" in compose
    assert "ANDROMEDA_OPS_API_KEY: ${ANDROMEDA_OPS_API_KEY}" in compose
    assert "backend:8000" not in server_api
    assert "!data/tracer.db" not in dockerignore
