"""Transparent mapping from canonical subject areas to activity signals."""

from __future__ import annotations

from decimal import Decimal

from andromeda.modules.analytics.contracts.public import (
    ACTIVITY_SIGNAL_WEIGHTS as _ANALYTICS_ACTIVITY_SIGNAL_WEIGHTS,
)
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode

from .entities import ActivityCode

ACTIVITY_SIGNAL_WEIGHTS: dict[DisciplineAreaCode, dict[ActivityCode, Decimal]] = {
    area: {ActivityCode(signal.value): weight for signal, weight in values.items()}
    for area, values in _ANALYTICS_ACTIVITY_SIGNAL_WEIGHTS.items()
}

__all__ = ["ACTIVITY_SIGNAL_WEIGHTS"]
