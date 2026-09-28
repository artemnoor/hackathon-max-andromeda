"""One-cycle compatibility wrapper for the retired tracer CLI name.

New code must import :mod:`run_andromeda_bmstu`. This wrapper remains until
the canonical runner parity checkpoint is complete so existing local scripts
and regression tests do not fail silently.
"""

from __future__ import annotations

import logging

from run_andromeda_bmstu import (
    AndromedaRunResult,
    build_parser,
    configure_logging,
    main,
    result_payload,
    run_ingest,
    selected_program_codes,
)


logger = logging.getLogger("andromeda.compatibility.tracer_runner")
TracerRunResult = AndromedaRunResult


def _compatibility_notice() -> None:
    logger.warning("deprecated_entrypoint name=run_tracer_bullet replacement=run_andromeda_bmstu")


if __name__ == "__main__":
    _compatibility_notice()
    raise SystemExit(main())


__all__ = [
    "TracerRunResult",
    "build_parser",
    "configure_logging",
    "main",
    "result_payload",
    "run_ingest",
    "selected_program_codes",
]
