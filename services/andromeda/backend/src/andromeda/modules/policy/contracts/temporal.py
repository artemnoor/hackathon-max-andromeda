"""Policy applicability time, separate from source trust and source milestones."""

from __future__ import annotations

from datetime import UTC

from pydantic import model_validator

from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    SourceMilestones,
)
from andromeda.shared.contracts.base import ContractModel


class PolicyTemporalRevision(ContractModel):
    """Immutable policy revision with valid-time and system-time semantics."""

    clock: BitemporalRevision
    source_milestones: SourceMilestones

    @model_validator(mode="after")
    def knowledge_time_follows_capture(self) -> PolicyTemporalRevision:
        captured_at = self.source_milestones.captured_at
        if captured_at is not None and self.clock.recorded_at.astimezone(UTC) < captured_at.astimezone(UTC):
            raise ValueError("policy revision recorded_at cannot precede source capture")
        return self


__all__ = ["PolicyTemporalRevision"]
