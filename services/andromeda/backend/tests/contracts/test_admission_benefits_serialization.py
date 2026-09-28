from __future__ import annotations

from datetime import datetime, timezone

from andromeda.modules.admission_benefits.contracts.policy import BenefitScope, BenefitScopeMode
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import BenefitPolicyVersion
from andromeda.shared.contracts.enums import SourceKind


def _rule() -> AdmissionBenefitRule:
    return AdmissionBenefitRule(
        id="admission-benefit:serialization-test",
        university_id="university:bmstu",
        admission_year=2026,
        route=AdmissionRoute.OLYMPIAD,
        benefit_type=BenefitType.BVI,
        olympiad_id="olympiad:serialization-test",
        result_type=OlympiadResultType.WINNER,
        scope=BenefitScope(mode=BenefitScopeMode.ALL, original_text="все"),
        validity=ValidityPolicy(source_text="validity source"),
        source_text="rule source",
        policy_version=BenefitPolicyVersion(
            schema_version="admission-benefits-schema.v1",
            parser_version="admission-benefits-parser.v1",
            policy_version="admission-benefits-policy.v1",
        ),
        provenance=BenefitProvenance(
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
        ),
    )


def test_rule_json_round_trip_preserves_versions_and_scope() -> None:
    rule = _rule()
    restored = AdmissionBenefitRule.model_validate_json(rule.model_dump_json(), strict=False)

    assert restored.id == rule.id
    assert restored.policy_version.policy_version == "admission-benefits-policy.v1"
    assert restored.scope.mode is rule.scope.mode
    assert restored.provenance.source_snapshot_hash == rule.provenance.source_snapshot_hash


def test_json_schema_exposes_year_and_provenance_as_contract_fields() -> None:
    schema = AdmissionBenefitRule.model_json_schema()
    serialized = str(schema)
    assert "admission_year" in serialized
    assert "provenance" in serialized
    assert "benefit_type" in serialized
