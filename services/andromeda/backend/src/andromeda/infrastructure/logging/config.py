from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    selected = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=selected, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger().setLevel(selected)
