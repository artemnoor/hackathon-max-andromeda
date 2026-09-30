"""Canonical cross-platform verification entrypoint for Andromeda.

This wrapper only orchestrates existing project commands. It does not contain
business logic and is safe to run from a clean checkout on Windows or CI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend-next"


def _uv_prefix() -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        return [sys.executable]
    return [uv, "run", "--project", str(BACKEND), "--locked", "--extra", "dev"]


def _backend_command(
    *arguments: str,
    browser: bool = False,
    evaluation: bool = False,
) -> list[str]:
    command = _uv_prefix()
    if shutil.which("uv") is not None and browser:
        command.extend(("--extra", "browser"))
    if shutil.which("uv") is not None and evaluation:
        command.extend(("--extra", "evaluation"))
    command.extend(("python", *arguments))
    return command


def _run(label: str, command: Sequence[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"[andromeda] {label}: {' '.join(command)}")
    subprocess.run(list(command), cwd=cwd, env=env, check=True)


def _require_environment(name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise SystemExit(
            f"[andromeda] missing prerequisite: set {name} to a disposable PostgreSQL DSN "
            "before running the postgres target"
        )
    return value


def _backend_tests(
    *paths: str,
    coverage: bool = False,
    browser: bool = False,
    evaluation: bool = False,
) -> None:
    command = _backend_command(
        "-m", "pytest", "-q", *paths, browser=browser, evaluation=evaluation
    )
    if coverage:
        report_dir = ROOT / "artifacts" / "coverage" / "backend"
        report_dir.mkdir(parents=True, exist_ok=True)
        command[command.index("-q") + 1:command.index("-q") + 1] = [
            "--cov=src/andromeda",
            "--cov-report=term-missing",
            f"--cov-report=xml:{report_dir / 'coverage.xml'}",
            f"--cov-report=html:{report_dir / 'html'}",
            f"--junitxml={report_dir / 'junit.xml'}",
        ]
    _run("backend tests", command, cwd=BACKEND)


def _frontend(command_name: str, *, env: dict[str, str] | None = None) -> None:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    _run(f"frontend {command_name}", [npm, "run", command_name], cwd=FRONTEND, env=env)


def _openapi() -> None:
    with tempfile.TemporaryDirectory(prefix="andromeda-openapi-") as temp_dir:
        full_spec = Path(temp_dir) / "full-openapi.json"
        public_spec = Path(temp_dir) / "public-v1-openapi.json"
        exporter = _backend_command("backend/scripts/export_openapi.py")
        _run(
            "export full OpenAPI",
            [*exporter, "--surface", "full", "--out", str(full_spec)],
        )
        _run(
            "export Public API v1 OpenAPI",
            [*exporter, "--surface", "public-v1", "--out", str(public_spec)],
        )
        _frontend(
            "check-openapi-snapshot",
            env={
                **os.environ,
                "OPENAPI_FILE": str(full_spec),
                "OPENAPI_SNAPSHOT": str(FRONTEND / "openapi.json"),
            },
        )
        _frontend(
            "check-openapi-snapshot",
            env={
                **os.environ,
                "OPENAPI_FILE": str(public_spec),
                "OPENAPI_SNAPSHOT": str(ROOT / "openapi.json"),
            },
        )
        _frontend("check-api-drift", env={**os.environ, "OPENAPI_FILE": str(full_spec)})
        _frontend(
            "check-public-api-drift",
            env={**os.environ, "OPENAPI_FILE": str(public_spec)},
        )


def _data_api() -> None:
    _run(
        "official DATA-API 1.0 validation",
        _backend_command(
            "scripts/data_api/validate_data_api.py",
            "DATA-API.yaml",
            "--schema",
            "scripts/data_api/DATA-API.schema.json",
            "--openapi",
            "openapi.json",
        ),
    )


def _docs() -> None:
    _run("documentation links", [sys.executable, "scripts/check_docs.py"])


def _deployment_contract() -> None:
    _run("deployment artifact contract", [sys.executable, "scripts/check_deployment_artifacts.py"])


def _python_audit_command() -> list[str]:
    uv = shutil.which("uv")
    if uv is not None:
        # Keep the auditor outside the project runtime environment.  ``uv
        # run --with`` can install the console wrapper without its import
        # package on Windows; ``uv tool run --from`` creates a complete,
        # pinned ephemeral tool environment on every supported platform.
        return [uv, "tool", "run", "--from", "pip-audit==2.9.0", "pip-audit", "--strict", "--progress-spinner", "off"]
    return [sys.executable, "-m", "pip_audit", "--strict", "--progress-spinner", "off"]


def _python_dependency_audit() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("[andromeda] security target requires uv to export the locked Python dependency set")
    with tempfile.TemporaryDirectory(prefix="andromeda-python-audit-") as temp_dir:
        requirements = Path(temp_dir) / "runtime-requirements.txt"
        _run(
            "export locked runtime requirements",
            [
                uv,
                "export",
                "--project",
                str(BACKEND),
                "--locked",
                "--format",
                "requirements.txt",
                "--no-hashes",
                "--no-editable",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                str(requirements),
            ],
        )
        _run(
            "Python dependency audit",
            [*_python_audit_command(), "-r", str(requirements)],
            cwd=BACKEND,
        )


def _migration_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="andromeda-migrations-") as temp_dir:
        database = Path(temp_dir) / "migration.db"
        environment = {**os.environ, "ANDROMEDA_DATABASE_URL": f"sqlite:///{database.as_posix()}"}
        _run(
            "empty database migration upgrade",
            _backend_command("-m", "alembic", "upgrade", "head"),
            cwd=BACKEND,
            env=environment,
        )
        _run(
            "migration drift check",
            _backend_command("-m", "alembic", "check"),
            cwd=BACKEND,
            env=environment,
        )


def _production_smoke() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="andromeda-production-smoke-") as temp_dir,
        tempfile.TemporaryDirectory(prefix=".next-smoke-", dir=FRONTEND) as next_dist_dir,
    ):
        database = Path(temp_dir) / "fixture.db"
        api_port = _free_local_port()
        frontend_port = _free_local_port()
        while frontend_port == api_port:
            frontend_port = _free_local_port()
        tsconfig_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="tsconfig-smoke-",
                suffix=".json",
                dir=FRONTEND,
                delete=False,
            ) as tsconfig_file:
                tsconfig_path = Path(tsconfig_file.name)
            shutil.copyfile(FRONTEND / "tsconfig.json", tsconfig_path)
            environment = {
                **os.environ,
                "ANDROMEDA_NEXT_DEV_DIST_DIR": Path(next_dist_dir).name,
                "ANDROMEDA_NEXT_DEV_TSCONFIG_PATH": tsconfig_path.name,
            }
            _run(
                "production-like fixture smoke",
                _backend_command(
                    "backend/scripts/run_andromeda_demo.py",
                    "--mode",
                    "fixture",
                    "--database-url",
                    f"sqlite:///{database.as_posix()}",
                    "--api-port",
                    str(api_port),
                    "--frontend-port",
                    str(frontend_port),
                    "--check",
                    "--log-level",
                    "INFO",
                    browser=True,
                ),
                env=environment,
            )
        finally:
            if tsconfig_path is not None:
                tsconfig_path.unlink(missing_ok=True)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _release_evidence() -> None:
    _run("release evidence metadata", [sys.executable, "scripts/release_evidence.py"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run canonical Andromeda checks")
    subparsers = parser.add_subparsers(dest="target", required=True)
    for name, help_text in (
        ("fast", "typing, architecture, OpenAPI and documentation checks"),
        ("backend", "all backend tests"),
        ("backend-coverage", "backend tests with XML/HTML coverage and JUnit reports"),
        ("frontend", "frontend unit tests, lint and production build"),
        ("frontend-coverage", "frontend unit tests with V8 coverage"),
        ("ingestion", "BMSTU and HSE fixture ingestion"),
        ("postgres", "PostgreSQL integration tests using the configured test URL"),
        ("playwright", "canonical browser suite"),
        ("openapi", "export public/full OpenAPI and verify snapshot/client drift"),
        ("data-api", "validate DATA-API.yaml with the pinned official validator"),
        ("migrations", "migration/schema regression gate"),
        ("docs", "documentation path and link audit"),
        ("deployment", "tracked Docker/VM/Caddy packaging contract"),
        ("security", "backend security tests and dependency audit"),
        ("release-evidence", "safe release metadata and exit checklist template"),
        ("production-smoke", "fixture production-like API/frontend smoke"),
        ("full", "all local checks that do not require a live university source"),
    ):
        subparsers.add_parser(name, help=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.target == "fast":
        _backend_tests("tests/architecture", "tests/contracts/test_openapi_jsonschema.py", browser=False)
        # Mypy traverses the BMSTU browser policy module, so the typing gate
        # must resolve the same optional Playwright dependency as CI/backend
        # tests.  Keeping this explicit also makes a fresh `fast` checkout
        # behave like the already provisioned local environment.
        _run("backend typing", _backend_command("-m", "mypy", browser=True), cwd=BACKEND)
        _openapi()
        _data_api()
        _docs()
        _deployment_contract()
    elif args.target == "backend":
        _backend_tests(browser=True, evaluation=True)
    elif args.target == "backend-coverage":
        _backend_tests(coverage=True, browser=True, evaluation=True)
    elif args.target == "frontend":
        _frontend("test:unit")
        _frontend("lint")
        _frontend("build")
    elif args.target == "frontend-coverage":
        _frontend("test:unit:coverage")
    elif args.target == "ingestion":
        with tempfile.TemporaryDirectory(prefix="andromeda-fixture-") as temp_dir:
            database = Path(temp_dir) / "fixture.db"
            _run(
                "fixture ingestion",
                _backend_command("backend/scripts/run_andromeda_ingestion.py", "--university", "all", "--mode", "fixture", "--database-url", f"sqlite:///{database.as_posix()}", "--log-level", "ERROR"),
            )
    elif args.target == "postgres":
        _require_environment("ANDROMEDA_POSTGRES_TEST_URL", os.environ.get("ANDROMEDA_POSTGRES_TEST_URL"))
        _backend_tests("tests/integration/test_postgresql_ingestion.py", "tests/integration/test_postgresql_smoke.py", "tests/integration/test_postgresql_user_profile.py", browser=True)
    elif args.target == "playwright":
        _frontend("test:e2e", env={**os.environ, "PLAYWRIGHT_BASE_URL": os.environ.get("PLAYWRIGHT_BASE_URL", "http://127.0.0.1:3000")})
    elif args.target == "openapi":
        _openapi()
    elif args.target == "data-api":
        _data_api()
    elif args.target == "migrations":
        _backend_tests("tests/infrastructure/test_alembic_migrations.py", "tests/infrastructure/test_database_config.py", browser=True)
        _migration_gate()
    elif args.target == "docs":
        _docs()
    elif args.target == "deployment":
        _deployment_contract()
    elif args.target == "security":
        _backend_tests("tests/api/test_security_headers.py", "tests/api/test_request_controls.py", "tests/api/test_auth_api.py", browser=True)
        _python_dependency_audit()
        npm = "npm.cmd" if os.name == "nt" else "npm"
        _run("production JavaScript dependency audit", [npm, "audit", "--omit=dev", "--audit-level=high"], cwd=FRONTEND)
    elif args.target == "production-smoke":
        _production_smoke()
    elif args.target == "release-evidence":
        _release_evidence()
    elif args.target == "full":
        for target in ("fast", "backend", "backend-coverage", "frontend", "frontend-coverage", "ingestion", "migrations", "production-smoke"):
            main((target,))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
