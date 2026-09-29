"""Jev adapter for choosing only among persisted Olympiad/profile candidates."""

from __future__ import annotations

import logging

from andromeda.modules.conversation.contracts.policy import (
    CandidateResolutionOption,
    DecisionModelPort,
    DecisionModelSource,
)
from andromeda.modules.entity_resolution.contracts.public import (
    EntityResolutionCandidate,
)

logger = logging.getLogger("andromeda.infrastructure.jev.admission_resolution")


class JevAdmissionCandidateSelector:
    """Return a candidate only when calibrated Jev selected a supplied id."""

    def __init__(self, model: DecisionModelPort) -> None:
        self._model = model

    def select(
        self,
        query: str,
        candidates: tuple[EntityResolutionCandidate, ...],
    ) -> str | None:
        if not 1 < len(candidates) <= 8:
            return None
        options = tuple(
            CandidateResolutionOption(
                candidate_id=candidate.canonical_id,
                label=candidate.label,
            )
            for candidate in candidates
        )
        decision = self._model.resolve_olympiad_profile(query, candidates=options)
        candidate_ids = {item.canonical_id for item in candidates}
        selected_id = decision.candidate_id
        accepted = (
            decision.source is DecisionModelSource.JEV
            and selected_id is not None
            and selected_id in candidate_ids
        )
        logger.info(
            "admission_candidate_selection source=%s outcome=%s candidates=%d",
            decision.source.value,
            "selected" if accepted else "unresolved",
            len(candidates),
        )
        return selected_id if accepted else None


__all__ = ["JevAdmissionCandidateSelector"]
