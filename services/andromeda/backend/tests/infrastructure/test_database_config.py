from __future__ import annotations

import logging

import pytest
from andromeda.infrastructure.config import (
    Settings,
    database_dialect,
    redact_database_url,
)
from andromeda.infrastructure.database import create_engine_for_url


def test_settings_keep_sqlite_for_explicit_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("BMSTU_DATABASE_URL", raising=False)

    settings = Settings.from_environment()

    assert settings.database_url.startswith("sqlite:///")
    assert settings.environment == "test"
    assert settings.knowledge_policy_assistant_enabled is False


def test_knowledge_policy_assistant_rollout_flag_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED", "true")

    settings = Settings.from_environment()

    assert settings.knowledge_policy_assistant_enabled is True


def test_presentation_model_is_disabled_and_optional_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("PRESENTATION_LLM_ENABLED", raising=False)
    monkeypatch.delenv("POLZA_AI_API_KEY", raising=False)

    settings = Settings.from_environment()

    assert settings.presentation_llm_enabled is False
    assert settings.polza_api_key is None
    assert settings.deepseek_model == "deepseek/deepseek-v4.1-flash"
    assert "polza_api_key" not in repr(settings)


def test_conversation_ai_timeout_is_separate_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("CONVERSATION_AI_TIMEOUT_SECONDS", raising=False)

    assert Settings.from_environment().conversation_ai_timeout_seconds == 6.5

    monkeypatch.setenv("CONVERSATION_AI_TIMEOUT_SECONDS", "22")
    assert Settings.from_environment().conversation_ai_timeout_seconds == 22.0


def test_conversation_ai_rate_limit_is_separate_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("CONVERSATION_AI_RATE_LIMIT_MAX", raising=False)

    assert Settings.from_environment().conversation_ai_rate_limit_max == 12

    monkeypatch.setenv("CONVERSATION_AI_RATE_LIMIT_MAX", "18")
    assert Settings.from_environment().conversation_ai_rate_limit_max == 18

    monkeypatch.setenv("CONVERSATION_AI_RATE_LIMIT_MAX", "31")
    with pytest.raises(ValueError, match="CONVERSATION_AI_RATE_LIMIT_MAX"):
        Settings.from_environment()


def test_presentation_model_can_be_enabled_without_a_key_and_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("PRESENTATION_LLM_ENABLED", "true")
    monkeypatch.delenv("POLZA_AI_API_KEY", raising=False)

    settings = Settings.from_environment()

    assert settings.presentation_llm_enabled is True
    assert settings.polza_api_key is None


@pytest.mark.parametrize(
    ("name", "value", "match"),
    [
        ("POLZA_API_BASE_URL", "https://attacker.invalid/api/v1", "must be https"),
        ("POLZA_API_BASE_URL", "https://polza.ai/api/v1?key=secret", "must be https"),
        ("DEEPSEEK_MODEL", "other-provider/model", "DeepSeek model identifier"),
    ],
)
def test_presentation_provider_configuration_is_allowlisted_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    match: str,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("PRESENTATION_LLM_ENABLED", "true")
    monkeypatch.setenv("POLZA_AI_API_KEY", "disposable-provider-test-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=match):
        Settings.from_environment()


def test_development_requires_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "development")
    monkeypatch.setenv("BMSTU_DATABASE_URL", "sqlite:///./data/not-dev.db")

    with pytest.raises(ValueError, match="requires a PostgreSQL"):
        Settings.from_environment()


def test_andromeda_database_environment_takes_precedence_over_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("BMSTU_DATABASE_URL", "sqlite:///./data/legacy.db")
    monkeypatch.setenv("ANDROMEDA_DATABASE_URL", "sqlite:///./data/current.db")
    monkeypatch.setenv("BMSTU_DB_POOL_SIZE", "2")
    monkeypatch.setenv("ANDROMEDA_DB_POOL_SIZE", "7")

    settings = Settings.from_environment()

    assert settings.database_url.endswith("current.db")
    assert settings.pool_size == 7


def test_legacy_environment_is_supported_as_deprecated_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.delenv("ANDROMEDA_DATABASE_URL", raising=False)
    monkeypatch.setenv("BMSTU_DATABASE_URL", "sqlite:///./data/legacy.db")
    monkeypatch.delenv("ANDROMEDA_DB_MAX_OVERFLOW", raising=False)
    monkeypatch.setenv("BMSTU_DB_MAX_OVERFLOW", "3")

    settings = Settings.from_environment()

    assert settings.database_url.endswith("legacy.db")
    assert settings.max_overflow == 3


def test_postgresql_settings_are_redacted_and_parseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "staging")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "staging-test-ops-key-001")
    database_url = "postgresql+psycopg://user:p%40ss@example.test:5432/andromeda_staging?sslmode=require"
    monkeypatch.setenv("BMSTU_DATABASE_URL", database_url)

    settings = Settings.from_environment()

    assert database_dialect(settings.database_url) == "postgresql"
    assert (
        redact_database_url(settings.database_url)
        == "postgresql+psycopg://example.test:5432/andromeda_staging"
    )
    assert "p%40ss" not in redact_database_url(settings.database_url)


def test_sqlite_engine_keeps_foreign_key_pragma(tmp_path) -> None:
    engine = create_engine_for_url(f"sqlite:///{(tmp_path / 'config.db').as_posix()}")
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose()


def test_settings_emit_safe_debug_diagnostic(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "staging")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "staging-test-ops-key-001")
    monkeypatch.setenv(
        "BMSTU_DATABASE_URL", "postgresql+psycopg://user:secret@example.test/andromeda"
    )
    with caplog.at_level(logging.DEBUG, logger="andromeda.infrastructure.config"):
        Settings.from_environment()

    assert "secret" not in caplog.text
    assert "settings_loaded" in caplog.text


def test_profile_cookie_settings_are_environment_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "staging")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "staging-test-ops-key-001")
    monkeypatch.setenv(
        "BMSTU_DATABASE_URL", "postgresql+psycopg://user:secret@example.test/andromeda"
    )
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_NAME", "andromeda_staging_session")
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_MAX_AGE", "7200")
    monkeypatch.setenv("ANDROMEDA_PROFILE_TTL_SECONDS", "86400")
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_SECURE", "true")
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_SAMESITE", "strict")

    settings = Settings.from_environment()

    assert settings.profile_cookie_name == "andromeda_staging_session"
    assert settings.profile_cookie_max_age == 7200
    assert settings.profile_ttl_seconds == 86400
    assert settings.profile_cookie_secure is True
    assert settings.profile_cookie_samesite == "strict"


def test_profile_cookie_none_requires_secure_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_SECURE", "false")

    with pytest.raises(ValueError, match="SameSite=None"):
        Settings.from_environment()


def test_staging_requires_explicit_origin_and_ops_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "staging")
    database_url = "postgresql+psycopg://user:secret@example.test/andromeda"
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("ANDROMEDA_OPS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="explicit FRONTEND_ORIGIN"):
        Settings.from_environment(database_url)

    monkeypatch.setenv("FRONTEND_ORIGIN", "https://andromeda.example.test")
    with pytest.raises(ValueError, match="ANDROMEDA_OPS_API_KEY"):
        Settings.from_environment(database_url)


def test_production_requires_https_and_uses_secure_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDROMEDA_ENV", "production")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://andromeda.example.test")
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "production-test-ops-key-001")

    settings = Settings.from_environment(
        "postgresql+psycopg://user:secret@example.test/andromeda"
    )

    assert settings.environment == "production"
    assert settings.profile_cookie_secure is True
    assert settings.auth_cookie_secure is True
