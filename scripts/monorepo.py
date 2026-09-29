"""Cross-platform orchestration for the Andromeda MAX monorepo."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_ROOT = ROOT / "apps" / "max"
ANDROMEDA_ROOT = ROOT / "services" / "andromeda"
ANDROMEDA_BACKEND = ANDROMEDA_ROOT / "backend"


@dataclass(frozen=True)
class Command:
    label: str
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str] | None = None


def _npm() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def resolve_target(target: str, arguments: Sequence[str] = ()) -> tuple[Command, ...]:
    npm = _npm()
    python = sys.executable
    targets: dict[str, tuple[Command, ...]] = {
        "max": (Command("MAX verification", (npm, "run", "verify"), MAX_ROOT),),
        "andromeda": (
            Command("Andromeda full local gate", (python, "scripts/andromeda.py", "full"), ANDROMEDA_ROOT),
        ),
        "contracts": (
            Command("OpenAPI snapshot and generated web client drift", (python, "scripts/andromeda.py", "openapi"), ANDROMEDA_ROOT),
            Command("Official DATA-API validation", (python, "scripts/andromeda.py", "data-api"), ANDROMEDA_ROOT),
            Command("Generated MAX client drift", (npm, "run", "check:andromeda-client-drift"), MAX_ROOT),
            Command("MAX to Andromeda architecture boundary", (npm, "run", "check:architecture"), MAX_ROOT),
        ),
        "full": (
            Command("MAX full verification", (npm, "run", "verify"), MAX_ROOT),
            Command("Andromeda full local gate", (python, "scripts/andromeda.py", "full"), ANDROMEDA_ROOT),
            Command("OpenAPI, DATA-API and MAX contract checks", (python, "scripts/monorepo.py", "contracts"), ROOT),
            Command("Root Compose validation", ("docker", "compose", "config", "--quiet"), ROOT),
        ),
    }
    if target not in targets:
        raise ValueError(f"Unknown monorepo target: {target}")
    if arguments:
        raise ValueError(f"Target {target} does not accept additional arguments")
    return targets[target]


def resolve_stack_action(
    action: str,
    *,
    fixtures: bool = False,
    max_profile: bool = False,
    volumes: bool = False,
) -> Command:
    argv: list[str] = ["docker", "compose"]
    if max_profile:
        argv.extend(("--profile", "max"))
    if action == "up":
        if not fixtures:
            raise ValueError("stack up requires explicit --fixtures; this stack always seeds local development data")
        argv.extend(("up", "--build", "--detach", "--wait"))
        label = "Fixture-backed Andromeda/MAX stack"
    elif action == "down":
        argv.append("down")
        if volumes:
            argv.append("--volumes")
        label = "Stop Andromeda/MAX stack"
    elif action == "status":
        argv.extend(("ps", "--all"))
        label = "Andromeda/MAX stack status"
    else:
        raise ValueError("stack action must be up, down, or status")
    return Command(label, tuple(argv), ROOT)


def run_commands(
    commands: Sequence[Command],
    *,
    runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> int:
    for command in commands:
        print(f"[monorepo] {command.label} (cwd={command.cwd})")
        result = runner(
            list(command.argv),
            cwd=command.cwd,
            check=False,
            env=_command_environment(command.environment),
        )
        if result.returncode != 0:
            return int(result.returncode or 1)
    return 0


def _command_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    return {**os.environ, **(overrides or {})}


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run_e2e(
    *,
    runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> int:
    """Run real MAX-to-Andromeda HTTP scenarios against an isolated fixture stack."""
    api_port = _free_local_port()
    redis_port = _free_local_port()
    while redis_port == api_port:
        redis_port = _free_local_port()
    project = f"andromeda-max-e2e-{os.getpid()}"
    environment = {
        "ANDROMEDA_HOST_PORT": str(api_port),
        "MAX_TEST_REDIS_PORT": str(redis_port),
        "MAX_E2E_ANDROMEDA_URL": f"http://127.0.0.1:{api_port}",
        "MAX_TEST_REDIS_URL": f"redis://127.0.0.1:{redis_port}/1",
    }
    compose = ("docker", "compose", "--project-name", project)
    commands = (
        Command(
            "Start isolated PostgreSQL/Redis and fixture-backed Andromeda API",
            (*compose, "up", "--build", "--detach", "--wait", "andromeda"),
            ROOT,
            environment,
        ),
        Command("Run MAX Redis and real assistant HTTP integration scenarios", (_npm(), "run", "test:integration"), MAX_ROOT, environment),
        Command(
            "Andromeda production-like fixture smoke",
            (sys.executable, "scripts/andromeda.py", "production-smoke"),
            ANDROMEDA_ROOT,
        ),
        Command(
            "Andromeda browser suite",
            (sys.executable, "scripts/andromeda.py", "playwright"),
            ANDROMEDA_ROOT,
        ),
        Command("MAX browser suite", (_npm(), "run", "test:browser"), MAX_ROOT),
    )
    status = 0
    try:
        for command in commands:
            print(f"[monorepo] {command.label} (cwd={command.cwd})")
            result = runner(
                list(command.argv),
                cwd=command.cwd,
                check=False,
                env=_command_environment(command.environment),
            )
            if result.returncode != 0:
                status = int(result.returncode or 1)
                break
    finally:
        cleanup = Command(
            "Remove only the isolated E2E Compose project and its temporary volumes",
            (*compose, "down", "--volumes", "--remove-orphans"),
            ROOT,
            environment,
        )
        print(f"[monorepo] {cleanup.label}")
        result = runner(
            list(cleanup.argv),
            cwd=cleanup.cwd,
            check=False,
            env=_command_environment(cleanup.environment),
        )
        if status == 0 and result.returncode != 0:
            status = int(result.returncode or 1)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MAX/Andromeda monorepo checks or local stack")
    subparsers = parser.add_subparsers(dest="target", required=True)
    for target, help_text in (
        ("max", "MAX unit, integration, browser and package checks"),
        ("andromeda", "Andromeda full deterministic local gate"),
        ("contracts", "Canonical OpenAPI, DATA-API and generated MAX client drift"),
        ("full", "All deterministic MAX and Andromeda checks plus Compose validation"),
        ("e2e", "Fixture-backed API and browser smoke checks"),
    ):
        subparsers.add_parser(target, help=help_text)
    stack = subparsers.add_parser("stack", help="Manage the local fixture-backed stack")
    stack_actions = stack.add_subparsers(dest="stack_action", required=True)
    stack_up = stack_actions.add_parser("up", help="Build/start local Postgres, Redis and fixture-backed Andromeda")
    stack_up.add_argument("--fixtures", action="store_true", required=True, help="Confirm that local fixture data may be seeded")
    stack_up.add_argument("--max", dest="max_profile", action="store_true", help="Also start MAX Bot and Mini App; requires MAX_BOT_TOKEN")
    stack_down = stack_actions.add_parser("down", help="Stop services while preserving named data volumes")
    stack_down.add_argument("--max", dest="max_profile", action="store_true", help="Include the optional MAX profile")
    stack_down.add_argument("--volumes", action="store_true", help="Delete local Postgres/Redis data volumes")
    stack_status = stack_actions.add_parser("status", help="Show local Compose service status")
    stack_status.add_argument("--max", dest="max_profile", action="store_true", help="Include the optional MAX profile")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.target == "stack":
            command = resolve_stack_action(
                args.stack_action,
                fixtures=bool(getattr(args, "fixtures", False)),
                max_profile=bool(getattr(args, "max_profile", False)),
                volumes=bool(getattr(args, "volumes", False)),
            )
            commands = (command,)
        elif args.target == "e2e":
            return run_e2e()
        else:
            commands = resolve_target(args.target)
    except ValueError as error:
        parser.error(str(error))
    return run_commands(commands)


if __name__ == "__main__":
    raise SystemExit(main())
