"""Vendor-neutral semantic classification seams."""

from __future__ import annotations

from typing import Protocol

from .inputs import SemanticClassificationInput
from .public import SemanticClassificationResult, SemanticClassifierPort


class ManualSemanticClassificationPort(SemanticClassifierPort, Protocol):
    """Import/review boundary for versioned human corrections."""

    def classify_manual(self, input: SemanticClassificationInput) -> SemanticClassificationResult: ...


class JevSemanticClassifierPort(SemanticClassifierPort, Protocol):
    """Future decision-model adapter contract; no Jev SDK dependency."""


__all__ = ["JevSemanticClassifierPort", "ManualSemanticClassificationPort"]
