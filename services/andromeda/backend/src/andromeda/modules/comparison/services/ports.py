from __future__ import annotations

from typing import Protocol

from ..contracts.public import ComparisonRequest, ComparisonResult


class ComparisonService(Protocol):
    def compare(self, request: ComparisonRequest) -> ComparisonResult: ...


__all__ = ["ComparisonService"]
