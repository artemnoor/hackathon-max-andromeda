from __future__ import annotations

from hashlib import sha256

from andromeda.modules.disciplines.contracts.public import Discipline
from andromeda.modules.disciplines.contracts.resolution import IdentityResolutionStatus
from andromeda.modules.disciplines.services.identity_resolution import DisciplineIdentityResolverService


def _discipline(normalized: str) -> Discipline:
    return Discipline(
        id=f"discipline:{sha256(normalized.encode()).hexdigest()[:16]}",
        name=normalized,
        normalized_name=normalized,
    )


def test_identity_resolution_matches_only_exact_normalized_names() -> None:
    existing = _discipline("математика")
    resolver = DisciplineIdentityResolverService()
    matched = resolver.resolve(" МАТЕМАТИКА ", (existing,))
    new = resolver.resolve("Математика (профиль)", (existing,))
    ambiguous = resolver.resolve("математика", (existing, existing))
    assert matched.status is IdentityResolutionStatus.MATCHED
    assert new.status is IdentityResolutionStatus.NEW
    assert ambiguous.status is IdentityResolutionStatus.AMBIGUOUS
    assert ambiguous.discipline_id is None
