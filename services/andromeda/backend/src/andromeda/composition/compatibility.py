from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompatibilitySurface:
    """One bounded compatibility alias with an explicit removal trigger."""

    module: str
    target: str
    owner: str
    reason: str
    removal_condition: str


PROFTEST_COMPATIBILITY_SURFACES = (
    CompatibilitySurface(
        module="andromeda.modules.proftest.services.ranking",
        target="andromeda.modules.recommendations.services.ranking",
        owner="recommendations",
        reason="Preserve one migration cycle for existing proftest callers.",
        removal_condition="Remove after MVP-012 canonical runner parity and repository-wide import scan are green.",
    ),
    CompatibilitySurface(
        module="andromeda.modules.proftest.services.matching",
        target="andromeda.modules.recommendations.services.scoring",
        owner="recommendations",
        reason="Preserve legacy matching imports while recommendation scoring remains canonical.",
        removal_condition="Remove after MVP-012 compatibility parity tests pass and no runtime consumer remains.",
    ),
    CompatibilitySurface(
        module="andromeda.modules.proftest.services.explanations",
        target="andromeda.modules.recommendations.services.explanations",
        owner="recommendations",
        reason="Preserve legacy explanation imports without granting new code access to internals.",
        removal_condition="Remove after MVP-012 explanation parity evidence and import inventory are complete.",
    ),
)


__all__ = ["CompatibilitySurface", "PROFTEST_COMPATIBILITY_SURFACES"]
