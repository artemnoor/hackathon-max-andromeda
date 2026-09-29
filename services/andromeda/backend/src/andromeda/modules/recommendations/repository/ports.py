"""Compatibility exports for recommendation storage ports.

The canonical public Protocols live in ``contracts.public``. This module keeps
the established repository import path for infrastructure adapters.
"""

from __future__ import annotations

from ..contracts.public import ProgramFingerprintReader, RecommendationCatalogReader

__all__ = ["ProgramFingerprintReader", "RecommendationCatalogReader"]
