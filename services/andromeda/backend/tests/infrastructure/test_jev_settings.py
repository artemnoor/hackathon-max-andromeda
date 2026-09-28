import pytest

from andromeda.infrastructure.config.settings import Settings


def _clear_jev(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JEV_ENABLED",
        "JEV_SHADOW_ENABLED",
        "JEV_CALIBRATION_ENABLED",
        "JEV_CALIBRATION_LOCK_PATH",
        "JEV_CALIBRATION_MODE",
        "JEV_CALIBRATION_MIN_SUPPORT",
        "JEV_CALIBRATION_MIN_HELDOUT",
        "JEV_CALIBRATION_MAX_AGE_SECONDS",
        "JEV_ALLOW_FIXTURE_RUNTIME",
        "JEV_ENDPOINT",
        "JEV_BASE_URL",
        "JEV_RUNTIME_PROVIDER",
        "JEV_MODEL",
        "TYPESAFE_API_KEY",
        "JEV_API_KEY",
        "JEVQL_ENABLED",
        "JEVQL_ENDPOINT",
        "JEVQL_TOKEN",
        "JEV_TREE_ENABLED",
        "JEV_TREE_ENDPOINT",
        "JEV_ADMISSION_RESOLUTION_ENABLED",
        "JEV_ADMISSION_RESOLUTION_LOCK_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_test_defaults_keep_all_external_runtimes_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jev(monkeypatch)
    monkeypatch.setenv("ANDROMEDA_ENV", "test")

    settings = Settings.from_environment()

    assert settings.jev_enabled is False
    assert settings.jev_shadow_enabled is False
    assert settings.jevql_enabled is False
    assert settings.jev_tree_enabled is False
    assert settings.jev_admission_resolution_enabled is False
    assert settings.jev_admission_resolution_lock_path is None
    assert settings.jev_api_key is None
    assert "secret" not in repr(Settings(jev_api_key="secret"))


def test_enabled_production_jev_requires_calibration_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jev(monkeypatch)
    monkeypatch.setenv("ANDROMEDA_ENV", "production")
    monkeypatch.setenv("ANDROMEDA_DATABASE_URL", "postgresql+psycopg://user:pass@example.test/andromeda")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example")
    monkeypatch.setenv("ANDROMEDA_OPS_API_KEY", "x" * 32)
    monkeypatch.setenv("ANDROMEDA_PROFILE_COOKIE_SECURE", "true")
    monkeypatch.setenv("ANDROMEDA_AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("TYPESAFE_API_KEY", "x" * 32)
    monkeypatch.setenv("JEV_ENABLED", "true")

    with pytest.raises(ValueError, match="calibration gate"):
        Settings.from_environment()


def test_jev_endpoint_is_allow_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jev(monkeypatch)
    monkeypatch.setenv("JEV_ENDPOINT", "https://169.254.169.254/latest")

    with pytest.raises(ValueError, match="approved TypeSafe-compatible endpoint"):
        Settings.from_environment()


def test_jev_alias_environment_variables_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_jev(monkeypatch)
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("JEV_API_KEY", "jev-alias-secret")
    monkeypatch.setenv("JEV_BASE_URL", "https://polza.ai/api")
    monkeypatch.setenv("JEV_MODEL", "typesafe/jev")

    settings = Settings.from_environment()

    assert settings.jev_api_key == "jev-alias-secret"
    assert settings.jev_endpoint == "https://polza.ai/api"
    assert settings.jev_model == "typesafe/jev"
    assert "jev-alias-secret" not in repr(settings)


def test_official_environment_variables_take_precedence_over_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_jev(monkeypatch)
    monkeypatch.setenv("ANDROMEDA_ENV", "test")
    monkeypatch.setenv("TYPESAFE_API_KEY", "official-secret")
    monkeypatch.setenv("JEV_API_KEY", "alias-secret")
    monkeypatch.setenv("JEV_ENDPOINT", "https://api.typesafe.ai")
    monkeypatch.setenv("JEV_BASE_URL", "https://polza.ai/api")

    settings = Settings.from_environment()

    assert settings.jev_api_key == "official-secret"
    assert settings.jev_endpoint == "https://api.typesafe.ai"
