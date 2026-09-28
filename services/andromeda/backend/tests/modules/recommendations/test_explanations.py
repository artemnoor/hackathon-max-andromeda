from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.contracts.public import Confidence, CurriculumEvidence, DistinctiveSubject
from andromeda.modules.recommendations.services.explanations import ExplanationBuilder
from .factories import fingerprint, profile


def test_explanations_reference_area_and_distinctive_evidence() -> None:
    evidence = CurriculumEvidence(source_name="Алгоритмы", normalized_name="алгоритмы", hours=60, workload=Decimal("60"), area_weights=(DisciplineAreaWeight(area=DisciplineAreaCode.COMPUTER_SCIENCE_DATA, weight=Decimal("1")),))
    value = fingerprint()
    value = value.model_copy(update={
        "evidence": (evidence,),
        "distinctive_subjects": (DistinctiveSubject(source_name="Алгоритмы", normalized_name="алгоритмы", primary_area=DisciplineAreaCode.COMPUTER_SCIENCE_DATA, workload=Decimal("60"), share=Decimal("0.6"), rarity=Decimal("0.5"), distinctiveness=Decimal("0.3")),),
    })
    reasons = ExplanationBuilder().build(profile(), value)
    assert any("Алгоритмы" in reason.text for reason in reasons)
    assert all(reason.workload >= 0 and 0 <= reason.share <= 1 for reason in reasons)
