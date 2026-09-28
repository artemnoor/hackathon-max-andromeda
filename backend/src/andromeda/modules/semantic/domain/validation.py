from __future__ import annotations

from decimal import Decimal

from ..contracts.public import SemanticValueStatus


def validate_semantic_value(value: Decimal | None, status: SemanticValueStatus) -> None:
    """Keep missing values distinct from an explicit zero signal."""

    if status is SemanticValueStatus.AVAILABLE and value is None:
        raise ValueError("available semantic values require a numeric value")
    if status is not SemanticValueStatus.AVAILABLE and value is not None:
        raise ValueError("non-available semantic values must not be coerced to zero")


__all__ = ["validate_semantic_value"]
