"""One-cycle compatibility wrapper for the retired tracer demo name."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Sequence

_canonical = importlib.import_module("run_andromeda_demo")
_canonical_start_process = _canonical._start_process
_canonical_stop_process = _canonical._stop_process
logger = logging.getLogger("andromeda.compatibility.tracer_demo")

DemoError = _canonical.DemoError
BACKEND_ROOT = _canonical.BACKEND_ROOT
FRONTEND_ROOT = _canonical.FRONTEND_ROOT
REPO_ROOT = _canonical.REPO_ROOT
build_parser = _canonical.build_parser
configure_logging = _canonical.configure_logging
default_database_url = _canonical.default_database_url
discover_program_codes = _canonical.discover_program_codes
resolve_database_url = _canonical.resolve_database_url
run_ingest = _canonical.run_ingest
selected_program_codes = _canonical.selected_program_codes
verify_admissions = _canonical.verify_admissions
verify_campus_data = _canonical.verify_campus_data
verify_compare = _canonical.verify_compare
verify_events = _canonical.verify_events
verify_og = _canonical.verify_og
wait_for_http = _canonical.wait_for_http


def _sync_compatibility_overrides() -> None:
    """Keep old test/script monkeypatches effective for one migration cycle."""

    for name in (
        "BACKEND_ROOT",
        "FRONTEND_ROOT",
        "REPO_ROOT",
        "discover_program_codes",
        "resolve_database_url",
        "run_ingest",
        "selected_program_codes",
        "verify_admissions",
        "verify_campus_data",
        "verify_compare",
        "verify_events",
        "verify_og",
        "wait_for_http",
        "_start_process",
        "_stop_process",
    ):
        if name in globals():
            setattr(_canonical, name, globals()[name])
    setattr(_canonical, "sys", sys)
    setattr(_canonical, "os", os)


def _start_process(*args: object, **kwargs: object) -> object:
    return _canonical_start_process(*args, **kwargs)


def _stop_process(*args: object, **kwargs: object) -> None:
    _canonical_stop_process(*args, **kwargs)


def run_demo(args: Namespace):
    _sync_compatibility_overrides()
    return _canonical.run_demo(args)


def main(argv: Sequence[str] | None = None) -> int:
    logger.warning("deprecated_entrypoint name=run_tracer_demo replacement=run_andromeda_demo")
    _sync_compatibility_overrides()
    return _canonical.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DemoError",
    "ArgumentParser",
    "BACKEND_ROOT",
    "FRONTEND_ROOT",
    "REPO_ROOT",
    "build_parser",
    "configure_logging",
    "default_database_url",
    "discover_program_codes",
    "main",
    "os",
    "resolve_database_url",
    "run_demo",
    "run_ingest",
    "selected_program_codes",
    "sys",
    "verify_admissions",
    "verify_campus_data",
    "verify_compare",
    "verify_events",
    "verify_og",
    "wait_for_http",
]
