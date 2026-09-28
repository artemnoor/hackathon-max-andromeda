"""Cross-platform orchestration for the Andromeda MAX monorepo."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_ROOT = ROOT / "apps" / "max"
ANDROMEDA_ROOT = ROOT / "services" / "andromeda"
ANDROMEDA_BACKEND = ANDROMEDA_ROOT / "backend"


@dataclass(frozen=True)
class Command:
    label: str
    argv: tuple[str, ...]
    cwd: Path


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
        "e2e": (
            Command("Andromeda production-like fixture smoke", (python, "scripts/andromeda.py", "production-smoke"), ANDROMEDA_ROOT),
            Command("Andromeda browser suite", (python, "scripts/andromeda.py", "playwright"), ANDROMEDA_ROOT),
            Command("MAX browser suite", (npm, "run", "test:browser"), MAX_ROOT),
        ),
        "stack": (Command("Fixture-backed Andromeda/MAX stack", ("docker", "compose", "up", "--build", *arguments), ROOT),),
    }
    if target not in targets:
        raise ValueError(f"Unknown monorepo target: {target}")
    if target == "stack":
        return targets[target]
    if arguments:
        raise ValueError(f"Target {target} does not accept additional arguments")
    return targets[target]


def run_commands(
    commands: Sequence[Command],
    *,
    runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> int:
    for command in commands:
        print(f"[monorepo] {command.label} (cwd={command.cwd})")
        result = runner(list(command.argv), cwd=command.cwd, check=False)
        if result.returncode != 0:
            return int(result.returncode or 1)
    return 0


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
    stack = subparsers.add_parser("stack", help="Build and run the local fixture-backed stack")
    stack.add_argument("compose_args", nargs=argparse.REMAINDER, help="Arguments forwarded to docker compose up")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        arguments = args.compose_args if args.target == "stack" else ()
        commands = resolve_target(args.target, arguments)
    except ValueError as error:
        parser.error(str(error))
    return run_commands(commands)


if __name__ == "__main__":
    raise SystemExit(main())
