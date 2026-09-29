from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.jev.runtime import (
    _admission_registry_path,
    _registry_path,
    build_admission_candidate_selector,
)


def test_runtime_registries_resolve_from_backend_config_directory() -> None:
    assert _registry_path().is_file()
    assert _admission_registry_path().is_file()


def test_admission_selector_is_off_by_default() -> None:
    selector, report = build_admission_candidate_selector(Settings())

    assert selector is None
    assert report.enabled is False
    assert report.reason == "admission_resolution_disabled_by_config"


def test_admission_selector_fails_closed_without_dedicated_production_lock() -> None:
    selector, report = build_admission_candidate_selector(
        Settings(jev_admission_resolution_enabled=True)
    )

    assert selector is None
    assert report.enabled is False
    assert report.reason == "RuntimeError"
