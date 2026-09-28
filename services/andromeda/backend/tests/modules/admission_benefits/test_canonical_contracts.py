from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
    ApplicantExamScore,
)
from andromeda.modules.admission_benefits.contracts.policy import BenefitScope, BenefitScopeMode
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
    ConfirmationRequirement,
    IndividualAchievementPolicy,
    IndividualAchievementRule,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import BenefitPolicyVersion, RuleDataStatus
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution


RUN_ID = "ingest:" + "c" * 32
VERSIONS = BenefitPolicyVersion(
    schema_version="admission-benefits-schema.v1",
    parser_version="admission-benefits-parser.v1",
    policy_version="admission-benefits-policy.v1",
)


def _provenance() -> BenefitProvenance:
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url="https://api.www.bmstu.ru/file/122150/download",
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256="d" * 64,
        locator="appendix=5.3;page=2;table=1;row=4",
        run_id=RUN_ID,
    )
    return BenefitProvenance(
        source=source,
        source_snapshot_hash="d" * 64,
        source_run_id=RUN_ID,
        admission_year=2026,
        document_title="Приложение 5.3",
        document_kind="appendix_5_3",
        appendix_number="5.3",
        page=2,
        table="1",
        row=4,
        parser_version="bmstu-admission-parser.v1",
    )


def _bvi_rule(**overrides: object) -> AdmissionBenefitRule:
    payload: dict[str, object] = {
        "id": "admission-benefit:bmstu-2026-shag-physics-winner",
        "university_id": "university:bmstu",
        "admission_year": 2026,
        "route": AdmissionRoute.OLYMPIAD,
        "benefit_type": BenefitType.BVI,
        "olympiad_id": "olympiad:shag-v-budushchee",
        "result_type": OlympiadResultType.WINNER,
        "scope": BenefitScope(mode=BenefitScopeMode.ALL, original_text="все направления"),
        "validity": ValidityPolicy(source_text="действует по правилам приема 2026"),
        "source_text": "Победитель получает БВИ",
        "status": RuleDataStatus.ACTIVE,
        "policy_version": VERSIONS,
        "provenance": _provenance(),
    }
    payload.update(overrides)
    return AdmissionBenefitRule(**payload)


def test_bvi_and_100_points_are_distinct_typed_rules() -> None:
    bvi = _bvi_rule()
    assert bvi.points is None

    hundred = _bvi_rule(
        id="admission-benefit:bmstu-2026-shag-physics-prize-100",
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        target_subject="физика",
        points=Decimal("100"),
        result_type=OlympiadResultType.PRIZE_WINNER,
    )
    assert hundred.target_subject == "физика"


def test_bvi_numeric_score_and_hundred_without_subject_are_rejected() -> None:
    with pytest.raises(ValidationError, match="bvi_numeric_value_forbidden"):
        _bvi_rule(points=Decimal("100"))
    with pytest.raises(ValidationError, match="hundred_point_subject_missing"):
        _bvi_rule(
            benefit_type=BenefitType.ONE_HUNDRED_POINTS,
            points=Decimal("100"),
        )


def test_required_confirmation_cannot_have_an_unknown_subject() -> None:
    with pytest.raises(ValidationError, match="confirmation_subject_missing"):
        _bvi_rule(confirmation_requirement=ConfirmationRequirement.REQUIRED)


def test_result_type_and_profile_identity_are_not_collapsed() -> None:
    winner = _bvi_rule()
    prize = _bvi_rule(
        id="admission-benefit:bmstu-2026-shag-physics-prize",
        result_type=OlympiadResultType.PRIZE_WINNER,
        olympiad_profile_id="olympiad-profile:shag-physics",
    )
    assert winner.result_type is not prize.result_type
    assert prize.olympiad_profile_id != winner.olympiad_profile_id


def test_individual_achievement_policy_keeps_year_and_cap_explicit() -> None:
    rule = IndividualAchievementRule(
        id="individual-achievement:bmstu-2026-gto",
        university_id="university:bmstu",
        admission_year=2026,
        achievement_code="gto_gold",
        category="sport",
        official_name="Золотой знак ГТО",
        points=Decimal("2"),
        source_text="За золотой знак ГТО — 2 балла",
        policy_version=VERSIONS,
        provenance=_provenance(),
    )
    policy = IndividualAchievementPolicy(
        university_id="university:bmstu",
        admission_year=2026,
        global_max_points=Decimal("10"),
        rules=(rule,),
        source_text="Суммарно не более 10 баллов",
        policy_version=VERSIONS,
        provenance=_provenance(),
    )
    assert policy.global_max_points == Decimal("10")


def test_applicant_facts_do_not_store_documents_and_reject_duplicate_scores() -> None:
    facts = ApplicantAdmissionFacts(
        ege_scores=(ApplicantExamScore(subject="математика", score=Decimal("88")),),
    )
    assert facts.ege_scores[0].score == Decimal("88")
    with pytest.raises(ValidationError, match="duplicate_exam_subject"):
        ApplicantAdmissionFacts(
            ege_scores=(
                ApplicantExamScore(subject="математика", score=Decimal("88")),
                ApplicantExamScore(subject="МАТЕМАТИКА", score=Decimal("90")),
            ),
        )
