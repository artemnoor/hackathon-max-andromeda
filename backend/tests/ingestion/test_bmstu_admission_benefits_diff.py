from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from andromeda.ingestion.universities.bmstu.admission_benefits.diff import (
    AdmissionBenefitSourceRevision,
    diff_admission_benefits,
)
from andromeda.modules.admission_benefits.contracts.policy import (
    BenefitScope,
    BenefitScopeMode,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    AdmissionRoute,
    BenefitType,
    OlympiadResultType,
    ValidityPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import (
    BenefitPolicyVersion,
    RuleDataStatus,
)
from andromeda.shared.contracts.enums import SourceKind
from andromeda.shared.contracts.provenance import SourceAttribution

VERSIONS = BenefitPolicyVersion(
    schema_version="admission-benefits-schema.v1",
    parser_version="admission-benefits-parser.v1",
    policy_version="admission-benefits-policy.v1",
)


def _rule(document_kind: str, source_hash: str, *, status: RuleDataStatus = RuleDataStatus.ACTIVE) -> AdmissionBenefitRule:
    source = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_BENEFITS,
        url="https://api.www.bmstu.ru/file/122150/download",
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        content_sha256=source_hash,
        locator="page=1;row=2",
        run_id="ingest:" + "a" * 32,
    )
    provenance = BenefitProvenance(
        source=source,
        source_snapshot_hash=source_hash,
        source_run_id="ingest:" + "a" * 32,
        admission_year=2026,
        document_title="BMSTU Appendix 5.3",
        document_kind=document_kind,
        appendix_number="5.3",
        page=1,
        row=2,
        parser_version="admission-benefits-parser.v1",
    )
    return AdmissionBenefitRule(
        id="admission-benefit:formula-math-100",
        university_id="university:bmstu",
        admission_year=2026,
        route=AdmissionRoute.OLYMPIAD,
        benefit_type=BenefitType.ONE_HUNDRED_POINTS,
        olympiad_id="olympiad:formula-edinstva",
        result_type=OlympiadResultType.WINNER,
        scope=BenefitScope(mode=BenefitScopeMode.ALL, original_text="Все направления"),
        validity=ValidityPolicy(source_text="Срок действия не извлечён"),
        target_subject="математика",
        points=Decimal("100"),
        source_text="Официальная строка Appendix 5.3",
        status=status,
        policy_version=VERSIONS,
        provenance=provenance,
    )


def _sources(app5_3_hash: str) -> dict[str, AdmissionBenefitSourceRevision]:
    return {
        "appendix_5_1": AdmissionBenefitSourceRevision(
            document_kind="appendix_5_1",
            source_url="https://api.www.bmstu.ru/file/124777/download",
            content_sha256="1" * 64,
        ),
        "appendix_5_3": AdmissionBenefitSourceRevision(
            document_kind="appendix_5_3",
            source_url="https://api.www.bmstu.ru/file/122150/download",
            content_sha256=app5_3_hash,
        ),
    }


def test_identical_source_run_has_empty_diff() -> None:
    sources = _sources("2" * 64)

    result = diff_admission_benefits(sources, sources)

    assert result.changed is False
    assert result.model_dump() == {
        "added_documents": (),
        "removed_documents": (),
        "changed_documents": (),
        "added_rule_ids": (),
        "removed_rule_ids": (),
        "stale_rule_ids": (),
        "review_rule_ids": (),
    }


def test_changed_appendix_stales_only_its_previous_rules_and_surfaces_review() -> None:
    previous = _sources("2" * 64)
    current = _sources("3" * 64)
    old_rule = _rule("appendix_5_3", "2" * 64)
    unaffected_rule = _rule("appendix_5_1", "1" * 64).model_copy(update={"id": "admission-benefit:shag-bvi"})
    review_rule = _rule("appendix_5_3", "3" * 64, status=RuleDataStatus.REVIEW_REQUIRED)

    result = diff_admission_benefits(
        previous,
        current,
        previous_rules=(old_rule, unaffected_rule),
        current_rules=(review_rule,),
    )

    assert result.changed_documents == ("appendix_5_3",)
    assert result.stale_rule_ids == (old_rule.id,)
    assert unaffected_rule.id not in result.stale_rule_ids
    assert result.review_rule_ids == (review_rule.id,)
