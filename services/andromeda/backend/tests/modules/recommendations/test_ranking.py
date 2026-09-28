from __future__ import annotations

from andromeda.modules.recommendations.services.ranking import RankingService
from .factories import fingerprint, profile


def test_ranking_uses_score_then_subject_then_program_code() -> None:
    programs = (fingerprint("09.03.01-12"), fingerprint("09.03.01-02"))
    first = RankingService().rank(profile(), programs)
    second = RankingService().rank(profile(), programs)
    assert [item.fingerprint.program_code for item in first] == ["09.03.01-02", "09.03.01-12"]
    assert first == second


def test_ranking_returns_empty_catalog_without_synthetic_recommendations() -> None:
    assert RankingService().rank(profile(), ()) == ()
