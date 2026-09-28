from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from andromeda.modules.admission_benefits.contracts.policy import BenefitScope, BenefitScopeMode
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
    ConfirmationRequirement,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import BenefitPolicyVersion, RuleDataStatus
from andromeda.modules.admissions.contracts.public import (
    AdmissionCompetitionType,
    AdmissionProvenance,
    PassingScore,
    PassingScoreStatus,
    PassingScoreType,
)
from andromeda.shared.contracts.enums import SourceKind


def _provenance() -> BenefitProvenance:
    return BenefitProvenance(
        source={
            "kind": SourceKind.BMSTU_ADMISSION_BENEFITS,
            "url": "https://api.www.bmstu.ru/file/122150/download",
            "captured_at": datetime(2026, 9, 22, tzinfo=timezone.utc),
            "content_sha256": "e" * 64,
            "locator": "appendix=5.3;page=1;row=1",
            "run_id": "ingest:" + "f" * 32,
        },
        source_snapshot_hash="e" * 64,
        source_run_id="ingest:" + "f" * 32,
        admission_year=2026,
        document_title="Приложение 5.3",
        document_kind="appendix_5_3",
        page=1,
        row=1,
        parser_version="bmstu-admission-parser.v1",
    )


def _rule(**overrides: object) -> AdmissionBenefitRule:
    payload: dict[str, object] = {
        "id": "admission-benefit:contract-test",
        "university_id": "university:bmstu",
        "admission_year": 2026,
        "route": AdmissionRoute.OLYMPIAD,
        "benefit_type": BenefitType.BVI,
        "olympiad_id": "olympiad:contract-test",
        "result_type": OlympiadResultType.WINNER,
        "scope": BenefitScope(mode=BenefitScopeMode.ALL, original_text="все"),
        "validity": ValidityPolicy(source_text="source validity text"),
        "confirmation_requirement": ConfirmationRequirement.UNKNOWN,
        "source_text": "source rule text",
        "status": RuleDataStatus.ACTIVE,
        "policy_version": BenefitPolicyVersion(
            schema_version="admission-benefits-schema.v1",
            parser_version="admission-benefits-parser.v1",
            policy_version="admission-benefits-policy.v1",
        ),
        "provenance": _provenance(),
    }
    payload.update(overrides)
    return AdmissionBenefitRule(**payload)


def test_historical_bvi_observation_remains_distinct_from_eligibility_rule() -> None:
    observation = PassingScore(
        score_type=PassingScoreType.BUDGET,
        competition_type=AdmissionCompetitionType.BVI,
        status=PassingScoreStatus.BVI,
        provenance=AdmissionProvenance(
            source_kind="bmstu_admission_orders_document",
            source_url="https://bmstu.ru/admission/order.pdf",
            captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
            content_sha256="a" * 64,
        ),
    )
    eligibility_rule = _rule()
    assert observation.status is PassingScoreStatus.BVI
    assert eligibility_rule.benefit_type is BenefitType.BVI
    assert observation is not eligibility_rule


@pytest.mark.parametrize(
    ("benefit_type", "points", "subject"),
    (
        (BenefitType.SPECIAL_RIGHT, None, None),
        (BenefitType.PREFERENTIAL_RIGHT, None, None),
        (BenefitType.SPECIAL_QUOTA, None, None),
        (BenefitType.SEPARATE_QUOTA, None, None),
        (BenefitType.TARGETED_ROUTE, None, None),
    ),
)
def test_non_numeric_legal_routes_are_supported_without_fake_scores(
    benefit_type: BenefitType, points: Decimal | None, subject: str | None
) -> None:
    rule = _rule(
        id=f"admission-benefit:contract-{benefit_type.value.replace('_', '-')}",
        route=AdmissionRoute.OTHER,
        benefit_type=benefit_type,
        olympiad_id=None,
        result_type=None,
        points=points,
        target_subject=subject,
    )
    assert rule.points is None


def test_conflict_and_unknown_confirmation_are_not_coerced_to_negative() -> None:
    rule = _rule(status=RuleDataStatus.CONFLICT)
    assert rule.status is RuleDataStatus.CONFLICT
    assert rule.confirmation_requirement is ConfirmationRequirement.UNKNOWN


def test_active_rule_requires_provenance_and_year() -> None:
    payload = _rule().model_dump()
    payload.pop("provenance")
    with pytest.raises(ValidationError):
        AdmissionBenefitRule.model_validate(payload)

    payload = _rule().model_dump()
    payload["admission_year"] = None
    with pytest.raises(ValidationError):
        AdmissionBenefitRule.model_validate(payload)


def test_unknown_result_type_is_not_allowed_for_olympiad_rule() -> None:
    payload = _rule().model_dump()
    payload["result_type"] = None
    with pytest.raises(ValidationError, match="unknown_result_type"):
        AdmissionBenefitRule.model_validate(payload)
