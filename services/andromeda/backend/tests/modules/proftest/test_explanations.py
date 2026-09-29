from __future__ import annotations

from decimal import Decimal

from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode, DisciplineAreaWeight
from andromeda.modules.proftest.contracts.public import ActivityCode, Confidence, CurriculumEvidence, DistinctiveSubject, ProgramFingerprint, ReasonKind, UserProfile
from andromeda.modules.proftest.services.explanations import ExplanationBuilder


def test_explanations_reference_real_area_and_distinctive_evidence() -> None:
    evidence = CurriculumEvidence(source_name="Алгоритмы", normalized_name="алгоритмы", hours=60, workload=Decimal("60"), area_weights=(DisciplineAreaWeight(area=DisciplineAreaCode.COMPUTER_SCIENCE_DATA, weight=Decimal("1")),))
    fingerprint = ProgramFingerprint(program_id="program:09.03.01-02", program_code="09.03.01-02", program_name="Test", basis="hours", total_hours=100, total_credits=Decimal("10"), total_workload=Decimal("100"), area_hours={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("100")}, area_share={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, semester_distribution={"1": Decimal("1")}, activity_signals={ActivityCode.SOFTWARE_CREATION: Decimal("1")}, evidence=(evidence,), distinctive_subjects=(DistinctiveSubject(source_name="Алгоритмы", normalized_name="алгоритмы", primary_area=DisciplineAreaCode.COMPUTER_SCIENCE_DATA, workload=Decimal("60"), share=Decimal("0.6"), rarity=Decimal("0.5"), distinctiveness=Decimal("0.3")),))
    profile = UserProfile(preferred_subject_weights={DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("1")}, confidence=Confidence(value=Decimal("1"), answered_base=1, answered_adaptive=0))

    reasons = ExplanationBuilder().build(profile, fingerprint)

    assert any(reason.kind is ReasonKind.FIT and reason.area is DisciplineAreaCode.COMPUTER_SCIENCE_DATA for reason in reasons)
    assert any("Алгоритмы" in reason.text for reason in reasons)
    assert all(reason.workload >= 0 and 0 <= reason.share <= 1 for reason in reasons)
