from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

DEFAULT_DATABASE_URL = "sqlite:///./data/andromeda.db"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000,http://127.0.0.1:3000"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_ENVIRONMENT = "test"
DEFAULT_PROFILE_COOKIE_NAME = "andromeda_profile_session"
DEFAULT_PROFILE_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
DEFAULT_PROFILE_TTL_SECONDS = 60 * 60 * 24 * 30
DEFAULT_AUTH_COOKIE_NAME = "andromeda_auth_session"
DEFAULT_AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
DEFAULT_AUTH_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
DEFAULT_AUTH_PASSWORD_MIN_LENGTH = 12
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_AUTH_RATE_LIMIT_MAX = 10
DEFAULT_SENSITIVE_RATE_LIMIT_MAX = 120
DEFAULT_OPS_RATE_LIMIT_MAX = 10
DEFAULT_JEV_ENDPOINT = "https://api.typesafe.ai"
DEFAULT_JEV_TIMEOUT_SECONDS = 2.0
DEFAULT_JEV_MAX_ROWS = 100
DEFAULT_JEV_MAX_CHARS = 32_000
DEFAULT_JEV_MAX_CONCURRENCY = 4
VALID_ENVIRONMENTS = frozenset(("test", "development", "staging", "production"))
VALID_SAMESITE_VALUES = frozenset(("lax", "strict", "none"))
JEV_ALLOWED_ENDPOINTS = frozenset(("https://api.typesafe.ai", "https://polza.ai/api"))

logger = logging.getLogger("andromeda.infrastructure.config")


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    frontend_origin: str = DEFAULT_FRONTEND_ORIGIN
    log_level: str = DEFAULT_LOG_LEVEL
    environment: str = DEFAULT_ENVIRONMENT
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    profile_cookie_name: str = DEFAULT_PROFILE_COOKIE_NAME
    profile_cookie_max_age: int = DEFAULT_PROFILE_COOKIE_MAX_AGE
    profile_cookie_secure: bool = False
    profile_cookie_samesite: str = "lax"
    profile_ttl_seconds: int = DEFAULT_PROFILE_TTL_SECONDS
    auth_cookie_name: str = DEFAULT_AUTH_COOKIE_NAME
    auth_cookie_max_age: int = DEFAULT_AUTH_COOKIE_MAX_AGE
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_session_ttl_seconds: int = DEFAULT_AUTH_SESSION_TTL_SECONDS
    auth_password_min_length: int = DEFAULT_AUTH_PASSWORD_MIN_LENGTH
    rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    auth_rate_limit_max: int = DEFAULT_AUTH_RATE_LIMIT_MAX
    sensitive_rate_limit_max: int = DEFAULT_SENSITIVE_RATE_LIMIT_MAX
    ops_rate_limit_max: int = DEFAULT_OPS_RATE_LIMIT_MAX
    ops_api_key: str | None = None
    knowledge_policy_assistant_enabled: bool = False
    knowledge_source_steward_account_ids: tuple[str, ...] = ()
    knowledge_reviewer_account_ids: tuple[str, ...] = ()
    policy_steward_account_ids: tuple[str, ...] = ()
    ingestion_min_relative_count: float = 0.25
    ingestion_run_timeout_seconds: int = 30 * 60
    jev_enabled: bool = False
    jev_shadow_enabled: bool = False
    jev_calibration_enabled: bool = False
    jev_calibration_lock_path: str | None = None
    jev_calibration_mode: str = "fixture_only"
    jev_calibration_min_support: int = 30
    jev_calibration_min_heldout: int = 30
    jev_calibration_max_age_seconds: int | None = None
    jev_allow_fixture_runtime: bool = False
    jev_runtime_provider: str = "typesafe"
    jev_endpoint: str = DEFAULT_JEV_ENDPOINT
    jev_model: str = "jev-latest"
    jev_api_key: str | None = field(default=None, repr=False)
    jev_admission_resolution_enabled: bool = False
    jev_admission_resolution_lock_path: str | None = None
    jev_align_capture_enabled: bool = False
    jevql_enabled: bool = False
    jevql_endpoint: str | None = None
    jevql_token: str | None = field(default=None, repr=False)
    jev_tree_enabled: bool = False
    jev_tree_endpoint: str | None = None
    jev_max_rows: int = DEFAULT_JEV_MAX_ROWS
    jev_max_chars: int = DEFAULT_JEV_MAX_CHARS
    jev_timeout_seconds: float = DEFAULT_JEV_TIMEOUT_SECONDS
    jev_max_concurrency: int = DEFAULT_JEV_MAX_CONCURRENCY

    @classmethod
    def from_environment(cls, database_url: str | None = None) -> Settings:
        environment = (
            os.environ.get("ANDROMEDA_ENV", DEFAULT_ENVIRONMENT).strip().lower()
        )
        if environment not in VALID_ENVIRONMENTS:
            raise ValueError(
                "ANDROMEDA_ENV must be one of: test, development, staging, production"
            )
        selected_database_url = database_url or _environment_with_legacy_fallback(
            "ANDROMEDA_DATABASE_URL",
            "BMSTU_DATABASE_URL",
            DEFAULT_DATABASE_URL,
        )
        if environment in {"development", "staging"} and not is_postgresql_url(
            selected_database_url
        ):
            raise ValueError(
                f"ANDROMEDA_ENV={environment} requires a PostgreSQL ANDROMEDA_DATABASE_URL"
            )
        if environment == "production" and not is_postgresql_url(selected_database_url):
            raise ValueError(
                "ANDROMEDA_ENV=production requires a PostgreSQL ANDROMEDA_DATABASE_URL"
            )

        configured_frontend_origin = os.environ.get("FRONTEND_ORIGIN")
        ops_api_key = _optional_secret_from_environment("ANDROMEDA_OPS_API_KEY")
        if environment in {"staging", "production"}:
            if not configured_frontend_origin or not configured_frontend_origin.strip():
                raise ValueError(
                    f"ANDROMEDA_ENV={environment} requires an explicit FRONTEND_ORIGIN"
                )
            if ops_api_key is None:
                raise ValueError(
                    f"ANDROMEDA_ENV={environment} requires ANDROMEDA_OPS_API_KEY"
                )
            if len(ops_api_key) < 16:
                raise ValueError(
                    "ANDROMEDA_OPS_API_KEY must contain at least 16 characters"
                )

        settings = cls(
            database_url=selected_database_url,
            frontend_origin=configured_frontend_origin or DEFAULT_FRONTEND_ORIGIN,
            log_level=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
            environment=environment,
            pool_size=_int_from_environment_with_legacy(
                "ANDROMEDA_DB_POOL_SIZE", "BMSTU_DB_POOL_SIZE", 5
            ),
            max_overflow=_int_from_environment_with_legacy(
                "ANDROMEDA_DB_MAX_OVERFLOW", "BMSTU_DB_MAX_OVERFLOW", 10
            ),
            pool_timeout=_int_from_environment_with_legacy(
                "ANDROMEDA_DB_POOL_TIMEOUT", "BMSTU_DB_POOL_TIMEOUT", 30
            ),
            pool_recycle=_int_from_environment_with_legacy(
                "ANDROMEDA_DB_POOL_RECYCLE", "BMSTU_DB_POOL_RECYCLE", 1800
            ),
            profile_cookie_name=os.environ.get(
                "ANDROMEDA_PROFILE_COOKIE_NAME", DEFAULT_PROFILE_COOKIE_NAME
            ),
            profile_cookie_max_age=_positive_int_from_environment(
                "ANDROMEDA_PROFILE_COOKIE_MAX_AGE", DEFAULT_PROFILE_COOKIE_MAX_AGE
            ),
            profile_cookie_secure=_bool_from_environment(
                "ANDROMEDA_PROFILE_COOKIE_SECURE",
                environment in {"staging", "production"},
            ),
            profile_cookie_samesite=_samesite_from_environment(
                "ANDROMEDA_PROFILE_COOKIE_SAMESITE"
            ),
            profile_ttl_seconds=_positive_int_from_environment(
                "ANDROMEDA_PROFILE_TTL_SECONDS", DEFAULT_PROFILE_TTL_SECONDS
            ),
            auth_cookie_name=os.environ.get(
                "ANDROMEDA_AUTH_COOKIE_NAME", DEFAULT_AUTH_COOKIE_NAME
            ),
            auth_cookie_max_age=_positive_int_from_environment(
                "ANDROMEDA_AUTH_COOKIE_MAX_AGE", DEFAULT_AUTH_COOKIE_MAX_AGE
            ),
            auth_cookie_secure=_bool_from_environment(
                "ANDROMEDA_AUTH_COOKIE_SECURE", environment in {"staging", "production"}
            ),
            auth_cookie_samesite=_samesite_from_environment(
                "ANDROMEDA_AUTH_COOKIE_SAMESITE"
            ),
            auth_session_ttl_seconds=_positive_int_from_environment(
                "ANDROMEDA_AUTH_SESSION_TTL_SECONDS", DEFAULT_AUTH_SESSION_TTL_SECONDS
            ),
            auth_password_min_length=_positive_int_from_environment(
                "ANDROMEDA_AUTH_PASSWORD_MIN_LENGTH", DEFAULT_AUTH_PASSWORD_MIN_LENGTH
            ),
            rate_limit_window_seconds=_positive_int_from_environment(
                "ANDROMEDA_RATE_LIMIT_WINDOW_SECONDS", DEFAULT_RATE_LIMIT_WINDOW_SECONDS
            ),
            auth_rate_limit_max=_positive_int_from_environment(
                "ANDROMEDA_AUTH_RATE_LIMIT_MAX", DEFAULT_AUTH_RATE_LIMIT_MAX
            ),
            sensitive_rate_limit_max=_positive_int_from_environment(
                "ANDROMEDA_SENSITIVE_RATE_LIMIT_MAX", DEFAULT_SENSITIVE_RATE_LIMIT_MAX
            ),
            ops_rate_limit_max=_positive_int_from_environment(
                "ANDROMEDA_OPS_RATE_LIMIT_MAX", DEFAULT_OPS_RATE_LIMIT_MAX
            ),
            ops_api_key=ops_api_key,
            knowledge_policy_assistant_enabled=_bool_from_environment(
                "ANDROMEDA_KNOWLEDGE_POLICY_ASSISTANT_ENABLED", False
            ),
            knowledge_source_steward_account_ids=_account_ids_from_environment(
                "ANDROMEDA_KNOWLEDGE_SOURCE_STEWARD_ACCOUNT_IDS"
            ),
            knowledge_reviewer_account_ids=_account_ids_from_environment(
                "ANDROMEDA_KNOWLEDGE_REVIEWER_ACCOUNT_IDS"
            ),
            policy_steward_account_ids=_account_ids_from_environment(
                "ANDROMEDA_POLICY_STEWARD_ACCOUNT_IDS"
            ),
            ingestion_min_relative_count=_ratio_from_environment(
                "ANDROMEDA_INGEST_MIN_RELATIVE_COUNT", 0.25
            ),
            ingestion_run_timeout_seconds=_positive_int_from_environment(
                "ANDROMEDA_INGEST_RUN_TIMEOUT_SECONDS", 30 * 60
            ),
            jev_enabled=_bool_from_environment("JEV_ENABLED", False),
            jev_shadow_enabled=_bool_from_environment("JEV_SHADOW_ENABLED", False),
            jev_calibration_enabled=_bool_from_environment(
                "JEV_CALIBRATION_ENABLED", False
            ),
            jev_calibration_lock_path=_optional_text_from_environment(
                "JEV_CALIBRATION_LOCK_PATH"
            ),
            jev_calibration_mode=os.environ.get("JEV_CALIBRATION_MODE", "fixture_only")
            .strip()
            .lower(),
            jev_calibration_min_support=_bounded_int_from_environment(
                "JEV_CALIBRATION_MIN_SUPPORT", 30, 1, 1_000_000
            ),
            jev_calibration_min_heldout=_bounded_int_from_environment(
                "JEV_CALIBRATION_MIN_HELDOUT", 30, 1, 1_000_000
            ),
            jev_calibration_max_age_seconds=_optional_bounded_int_from_environment(
                "JEV_CALIBRATION_MAX_AGE_SECONDS", 1, 31_536_000
            ),
            jev_allow_fixture_runtime=_bool_from_environment(
                "JEV_ALLOW_FIXTURE_RUNTIME", False
            ),
            jev_runtime_provider=os.environ.get("JEV_RUNTIME_PROVIDER", "typesafe")
            .strip()
            .lower(),
            jev_endpoint=os.environ.get(
                "JEV_ENDPOINT",
                os.environ.get("JEV_BASE_URL", DEFAULT_JEV_ENDPOINT),
            ).strip(),
            jev_model=os.environ.get("JEV_MODEL", "jev-latest").strip(),
            jev_api_key=(
                _optional_secret_from_environment("TYPESAFE_API_KEY")
                or _optional_secret_from_environment("JEV_API_KEY")
            ),
            jev_admission_resolution_enabled=_bool_from_environment(
                "JEV_ADMISSION_RESOLUTION_ENABLED", False
            ),
            jev_admission_resolution_lock_path=_optional_text_from_environment(
                "JEV_ADMISSION_RESOLUTION_LOCK_PATH"
            ),
            jev_align_capture_enabled=_bool_from_environment(
                "JEV_ALIGN_CAPTURE_ENABLED", False
            ),
            jevql_enabled=_bool_from_environment("JEVQL_ENABLED", False),
            jevql_endpoint=_optional_text_from_environment("JEVQL_ENDPOINT"),
            jevql_token=_optional_secret_from_environment("JEVQL_TOKEN"),
            jev_tree_enabled=_bool_from_environment("JEV_TREE_ENABLED", False),
            jev_tree_endpoint=_optional_text_from_environment("JEV_TREE_ENDPOINT"),
            jev_max_rows=_bounded_int_from_environment(
                "JEV_MAX_ROWS", DEFAULT_JEV_MAX_ROWS, 1, 10_000
            ),
            jev_max_chars=_bounded_int_from_environment(
                "JEV_MAX_CHARS", DEFAULT_JEV_MAX_CHARS, 1, 1_000_000
            ),
            jev_timeout_seconds=_bounded_float_from_environment(
                "JEV_TIMEOUT_SECONDS", DEFAULT_JEV_TIMEOUT_SECONDS, 0.1, 30.0
            ),
            jev_max_concurrency=_bounded_int_from_environment(
                "JEV_MAX_CONCURRENCY", DEFAULT_JEV_MAX_CONCURRENCY, 1, 32
            ),
        )
        _validate_jev_settings(settings)
        _validate_cookie_settings(
            settings.profile_cookie_name,
            settings.profile_cookie_samesite,
            settings.profile_cookie_secure,
            "ANDROMEDA_PROFILE_COOKIE_NAME",
        )
        _validate_cookie_settings(
            settings.auth_cookie_name,
            settings.auth_cookie_samesite,
            settings.auth_cookie_secure,
            "ANDROMEDA_AUTH_COOKIE_NAME",
        )
        if environment in {"staging", "production"}:
            if not settings.profile_cookie_secure or not settings.auth_cookie_secure:
                raise ValueError(
                    f"ANDROMEDA_ENV={environment} requires secure profile and auth cookies"
                )
            if environment == "production" and any(
                not origin.strip().lower().startswith("https://")
                for origin in settings.frontend_origin.split(",")
                if origin.strip()
            ):
                raise ValueError(
                    "ANDROMEDA_ENV=production requires HTTPS FRONTEND_ORIGIN values"
                )
        logger.debug(
            "settings_loaded environment=%s dialect=%s database_target=%s log_level=%s profile_cookie_secure=%s profile_cookie_samesite=%s profile_ttl_seconds=%d",
            settings.environment,
            database_dialect(settings.database_url),
            redact_database_url(settings.database_url),
            settings.log_level,
            settings.profile_cookie_secure,
            settings.profile_cookie_samesite,
            settings.profile_ttl_seconds,
        )
        logger.debug(
            "jev_settings_loaded enabled=%s shadow=%s provider=%s endpoint=%s model=%s calibration_mode=%s key_configured=%s",
            settings.jev_enabled,
            settings.jev_shadow_enabled,
            settings.jev_runtime_provider,
            settings.jev_endpoint,
            settings.jev_model,
            settings.jev_calibration_mode,
            settings.jev_api_key is not None,
        )
        return settings

    @property
    def engine_options(self) -> dict[str, int]:
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
        }


def _int_from_environment(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _environment_with_legacy_fallback(primary: str, legacy: str, default: str) -> str:
    value = os.environ.get(primary)
    if value is not None:
        return value
    legacy_value = os.environ.get(legacy)
    if legacy_value is not None:
        logger.warning(
            "deprecated_environment_used primary=%s legacy=%s", primary, legacy
        )
        return legacy_value
    return default


def _int_from_environment_with_legacy(primary: str, legacy: str, default: int) -> int:
    value = _environment_with_legacy_fallback(primary, legacy, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{primary} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{primary} must be non-negative")
    return parsed


def _positive_int_from_environment(name: str, default: int) -> int:
    value = _int_from_environment(name, default)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _bounded_int_from_environment(
    name: str, default: int, minimum: int, maximum: int
) -> int:
    value = _int_from_environment(name, default)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float_from_environment(
    name: str, default: float, minimum: float, maximum: float
) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _optional_bounded_int_from_environment(
    name: str, minimum: int, maximum: int
) -> int | None:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _ratio_from_environment(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _bool_from_environment(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _samesite_from_environment(name: str) -> str:
    value = os.environ.get(name, "lax").strip().lower()
    if value not in VALID_SAMESITE_VALUES:
        raise ValueError(f"{name} must be one of: lax, strict, none")
    return value


def _optional_secret_from_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _account_ids_from_environment(name: str) -> tuple[str, ...]:
    raw_value = os.environ.get(name, "")
    values = tuple(
        sorted({item.strip() for item in raw_value.split(",") if item.strip()})
    )
    if any(re.fullmatch(r"account:[a-f0-9]{32}", item) is None for item in values):
        raise ValueError(f"{name} must contain comma-separated canonical account IDs")
    return values


def _optional_text_from_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_jev_settings(settings: Settings) -> None:
    if settings.jev_runtime_provider != "typesafe":
        raise ValueError("JEV_RUNTIME_PROVIDER must be typesafe")
    if not settings.jev_model:
        raise ValueError("JEV_MODEL must not be empty")
    if settings.jev_calibration_mode not in {
        "fixture_only",
        "shadow_only",
        "production",
    }:
        raise ValueError(
            "JEV_CALIBRATION_MODE must be fixture_only, shadow_only or production"
        )
    if settings.jev_allow_fixture_runtime and settings.environment == "production":
        raise ValueError("JEV_ALLOW_FIXTURE_RUNTIME is forbidden in production")
    if settings.jev_endpoint not in JEV_ALLOWED_ENDPOINTS:
        raise ValueError(
            "JEV_ENDPOINT must match an approved TypeSafe-compatible endpoint"
        )
    if settings.jevql_enabled and settings.jevql_endpoint is not None:
        _validate_endpoint(
            "JEVQL_ENDPOINT",
            settings.jevql_endpoint,
            frozenset(("localhost", "127.0.0.1", "jevql")),
            allow_internal=True,
        )
    if settings.jev_tree_enabled and settings.jev_tree_endpoint is not None:
        _validate_endpoint(
            "JEV_TREE_ENDPOINT",
            settings.jev_tree_endpoint,
            frozenset(("localhost", "127.0.0.1", "jev-tree")),
            allow_internal=True,
        )
    if settings.jev_enabled or settings.jev_shadow_enabled:
        if settings.jev_api_key is None:
            raise ValueError("JEV_ENABLED/JEV_SHADOW_ENABLED requires TYPESAFE_API_KEY")
        if settings.jev_enabled and (
            not settings.jev_calibration_enabled
            or not settings.jev_calibration_lock_path
        ):
            raise ValueError("JEV_ENABLED requires calibration gate and lock path")
    if settings.environment == "test" and (
        settings.jev_enabled or settings.jev_shadow_enabled
    ):
        raise ValueError("Jev runtime must remain disabled in test environment")
    if settings.jev_admission_resolution_enabled:
        if settings.jev_api_key is None:
            raise ValueError(
                "JEV_ADMISSION_RESOLUTION_ENABLED requires TYPESAFE_API_KEY"
            )
        if not settings.jev_calibration_enabled:
            raise ValueError(
                "JEV_ADMISSION_RESOLUTION_ENABLED requires JEV_CALIBRATION_ENABLED"
            )
        if not settings.jev_admission_resolution_lock_path:
            raise ValueError(
                "JEV_ADMISSION_RESOLUTION_ENABLED requires JEV_ADMISSION_RESOLUTION_LOCK_PATH"
            )
        if settings.environment == "test":
            raise ValueError(
                "Jev admission resolution must remain disabled in test environment"
            )


def _validate_endpoint(
    name: str,
    value: str,
    allowed_hosts: frozenset[str],
    *,
    allow_internal: bool = False,
) -> None:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{name} must be an absolute endpoint without credentials or query parameters"
        )
    allowed = host in allowed_hosts or (
        allow_internal and (host.endswith(".internal") or host in allowed_hosts)
    )
    if not allowed:
        raise ValueError(f"{name} host is not allow-listed")
    if parsed.scheme != "https" and not allow_internal:
        raise ValueError(f"{name} requires HTTPS")


def _validate_cookie_settings(
    name: str, samesite: str, secure: bool, env_name: str
) -> None:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None:
        raise ValueError(f"{env_name} must contain only safe cookie name characters")
    if samesite == "none" and not secure:
        raise ValueError(
            f"{env_name.removesuffix('_NAME')}_SECURE must be true when SameSite=None"
        )


def database_dialect(database_url: str) -> str:
    return urlsplit(database_url).scheme.split("+", 1)[0].lower()


def is_postgresql_url(database_url: str) -> bool:
    return database_dialect(database_url) == "postgresql"


def redact_database_url(database_url: str) -> str:
    """Return a diagnostic target without credentials, query parameters, or SQLite paths."""
    parsed = urlsplit(database_url)
    dialect = database_dialect(database_url)
    if dialect == "sqlite":
        return "sqlite:///"
    if parsed.hostname is None:
        return f"{parsed.scheme}://<invalid-target>"
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    database = unquote(parsed.path.removeprefix("/") or "<default>")
    return f"{parsed.scheme}://{host}{port}/{database}"
