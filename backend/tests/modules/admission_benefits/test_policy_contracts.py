from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitScope,
    BenefitScopeMode,
    BenefitTarget,
    BenefitTargetKind,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.status import (
    ApplicabilityStatus,
    BenefitPolicyVersion,
    RuleDataStatus,
    TargetResolutionStatus,
    can_transition_status,
)
from andromeda.shared.contracts.enums import EducationLevel, SourceKind
from andromeda.shared.contracts.ids import IngestRunId
from andromeda.shared.contracts.provenance import SourceAttribution


def _target(kind: BenefitTargetKind, value: str, *, resolved: TargetResolutionStatus = TargetResolutionStatus.RESOLVED) -> BenefitTarget:
    return BenefitTarget(kind=kind, value=value, original_text=value, resolution=resolved)


def test_all_scope_accepts_and_all_except_rejects_only_explicit_exclusions() -> None:
    all_scope = BenefitScope(mode=BenefitScopeMode.ALL, original_text="все направления")
    assert all_scope.applies_to(direction_code="09.03.03").status is ApplicabilityStatus.APPLICABLE

    except_scope = BenefitScope(
        mode=BenefitScopeMode.ALL_EXCEPT,
        targets=(_target(BenefitTargetKind.DIRECTION, "09.03.04"),),
        original_text="все, кроме 09.03.04",
    )
    assert except_scope.applies_to(direction_code="09.03.03").status is ApplicabilityStatus.APPLICABLE
    assert except_scope.applies_to(direction_code="09.03.04").status is ApplicabilityStatus.NOT_APPLICABLE
    assert except_scope.applies_to().status is ApplicabilityStatus.INSUFFICIENT_DATA


def test_only_scope_normalizes_program_ids_and_keeps_source_text() -> None:
    scope = BenefitScope(
        mode=BenefitScopeMode.ONLY,
        targets=(_target(BenefitTargetKind.PROGRAM, "program:09.03.03-01"),),
        original_text="только 09.03.03-01",
    )

    assert scope.targets[0].value == "program:bmstu:09.03.03-01"
    assert scope.targets[0].original_text == "program:09.03.03-01"
    assert scope.applies_to(program_id="program:bmstu:09.03.03-01").status is ApplicabilityStatus.APPLICABLE
    assert scope.applies_to(program_id="program:bmstu:09.03.03-02").status is ApplicabilityStatus.NOT_APPLICABLE


def test_branch_campus_scope_does_not_grant_moscow_or_guess_when_campus_is_missing() -> None:
    scope = BenefitScope(
        mode=BenefitScopeMode.ONLY,
        targets=(
            _target(BenefitTargetKind.CAMPUS, "campus:bmstu-kaluga"),
            _target(BenefitTargetKind.CAMPUS, "campus:bmstu-mytishchi"),
        ),
        original_text="все направления Калужского и Мытищинского филиалов",
    )

    assert scope.applies_to(campus_id="campus:bmstu-kaluga").status is ApplicabilityStatus.APPLICABLE
    assert scope.applies_to(campus_id="campus:bmstu-mytishchi").status is ApplicabilityStatus.APPLICABLE
    assert scope.applies_to(campus_id="campus:bmstu-moscow").status is ApplicabilityStatus.NOT_APPLICABLE
    assert scope.applies_to().status is ApplicabilityStatus.INSUFFICIENT_DATA


def test_unresolved_target_is_review_required_not_not_applicable() -> None:
    scope = BenefitScope(
        mode=BenefitScopeMode.ALL_EXCEPT,
        targets=(_target(BenefitTargetKind.DIRECTION, "ИУ7", resolved=TargetResolutionStatus.UNRESOLVED),),
        original_text="все кроме ИУ7",
    )

    result = scope.applies_to(direction_code="09.03.03")
    assert result.status is ApplicabilityStatus.REVIEW_REQUIRED


def test_scope_requires_targets_for_only_and_all_except() -> None:
    with pytest.raises(ValidationError):
        BenefitScope(mode=BenefitScopeMode.ONLY, original_text="только")
    with pytest.raises(ValidationError):
        BenefitScope(mode=BenefitScopeMode.ALL_EXCEPT, original_text="кроме")


def test_status_transitions_preserve_review_and_conflict_states() -> None:
    assert can_transition_status(RuleDataStatus.ACTIVE, RuleDataStatus.STALE)
    assert can_transition_status(RuleDataStatus.ACTIVE, RuleDataStatus.CONFLICT)
    assert not can_transition_status(RuleDataStatus.CONFLICT, RuleDataStatus.STALE)


def test_active_provenance_requires_matching_snapshot_hash_and_locator() -> None:
    run_id = IngestRunId("ingest:" + "b" * 32)
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url="https://api.www.bmstu.ru/file/122150/download",
        captured_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        content_sha256="a" * 64,
        locator="appendix=5.3;page=1;table=1;row=2",
        run_id=run_id,
    )
    provenance = BenefitProvenance(
        source=source,
        source_snapshot_hash="a" * 64,
        source_run_id=run_id,
        admission_year=2026,
        document_title="Приложение 5.3",
        document_kind="appendix_5_3",
        appendix_number="5.3",
        page=1,
        table="1",
        row=2,
        parser_version="bmstu-admission.v1",
    )
    assert provenance.admission_year == 2026

    invalid_payload = provenance.model_dump()
    invalid_payload["source_snapshot_hash"] = "b" * 64
    with pytest.raises(ValidationError):
        BenefitProvenance.model_validate(invalid_payload)


def test_benefit_policy_versions_are_extensible_strings() -> None:
    versions = BenefitPolicyVersion(
        schema_version="admission-benefits.v1",
        parser_version="bmstu-admission.v1",
        policy_version="scope-policy.v1",
    )
    assert versions.policy_version == "scope-policy.v1"
    with pytest.raises(ValidationError):
        BenefitPolicyVersion(schema_version="v1", parser_version="bmstu.v1", policy_version="policy.v1")


def test_education_level_target_is_normalized() -> None:
    target = _target(BenefitTargetKind.EDUCATION_LEVEL, EducationLevel.BACHELOR.value)
    assert target.value == EducationLevel.BACHELOR.value
