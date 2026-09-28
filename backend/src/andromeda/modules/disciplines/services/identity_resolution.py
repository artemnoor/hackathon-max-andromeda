from __future__ import annotations

from collections.abc import Sequence

from ..contracts.public import Discipline
from ..contracts.resolution import IdentityResolution, IdentityResolutionStatus
from ..domain.identity import discipline_id_for, normalize_discipline_name


class DisciplineIdentityResolverService:
    """Resolve only exact canonical identities; never fuzzy-merges subjects."""

    def resolve(self, source_name: str, candidates: Sequence[Discipline] = ()) -> IdentityResolution:
        normalized_name = normalize_discipline_name(source_name)
        matches = tuple(candidate for candidate in candidates if candidate.normalized_name == normalized_name)
        if len(matches) == 1:
            return IdentityResolution(
                source_name=source_name,
                normalized_name=normalized_name,
                status=IdentityResolutionStatus.MATCHED,
                discipline_id=matches[0].id,
                candidate_ids=(matches[0].id,),
            )
        if len(matches) > 1:
            return IdentityResolution(
                source_name=source_name,
                normalized_name=normalized_name,
                status=IdentityResolutionStatus.AMBIGUOUS,
                candidate_ids=tuple(candidate.id for candidate in matches),
            )
        return IdentityResolution(
            source_name=source_name,
            normalized_name=normalized_name,
            status=IdentityResolutionStatus.NEW,
            discipline_id=discipline_id_for(normalized_name),
        )


__all__ = ["DisciplineIdentityResolverService"]
