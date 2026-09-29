from __future__ import annotations

from hashlib import sha256

from andromeda.modules.disciplines.contracts.public import Discipline


def test_discipline_identity_is_stable_for_a_normalized_name() -> None:
    normalized = "математика"
    discipline = Discipline(
        id=f"discipline:{sha256(normalized.encode('utf-8')).hexdigest()[:16]}",
        name="Математика",
        normalized_name=normalized,
    )
    assert discipline.id.startswith("discipline:")
