from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from andromeda.infrastructure.repositories.admission_policy import (
    AdmissionsPolicyRuleReader,
)
from andromeda.modules.admissions.contracts.offering_revisions import (
    AdmissionOfferingRevision,
    admission_offering_domain_rule_id,
    admission_offering_revision_hash,
)
from andromeda.modules.admissions.contracts.public import (
    AdmissionOffering,
    AdmissionProvenance,
    AdmissionScope,
    ExamRequirement,
    FundingType,
    StudyForm,
)
from andromeda.modules.admissions.repository.ports import (
    AdmissionOfferingRevisionReader,
)
from andromeda.modules.knowledge.contracts.public import EvidenceLocator, EvidenceRef
from andromeda.modules.knowledge.repository.ports import SourceObservationRepository
from andromeda.modules.policy.contracts.applicability import (
    PolicyApplicabilityContext,
    PolicyContextAvailability,
    PolicyContextValue,
)
from andromeda.modules.policy.contracts.approval import PolicyApprovalCapability
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    ImpactActionability,
    PolicyImpactContext,
)
from andromeda.modules.policy.contracts.rule import DomainRuleRef, PolicyDomainOwner
from andromeda.modules.policy.contracts.rule_ast import PolicyContextField
from andromeda.modules.policy.services.approval import PolicyApprovalCommandService
from andromeda.shared.contracts.errors import ValidationError

NOW = datetime(2027, 12, 15, tzinfo=UTC)
UNIVERSITY_ID = "university:bmstu"
PROGRAM_ID = "program:bmstu:09.03.01-02"
SOURCE_URL = "https://bmstu.example/rules/2028.pdf"


class _Revisions(AdmissionOfferingRevisionReader):
    def __init__(self, revisions: tuple[AdmissionOfferingRevision, ...]) -> None:
        self.rows = {
            (row.domain_rule_id, row.revision, row.content_hash): row
            for row in revisions
        }

    def get_offering_revision(
        self, domain_rule_id: str, revision: int, content_hash: str
    ) -> AdmissionOfferingRevision | None:
        return self.rows.get((domain_rule_id, revision, content_hash))


class _SourceObservations(SourceObservationRepository):
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def resolve_snapshot_evidence(
        self,
        *,
        source_url,
        snapshot_sha256: str,
        locator: EvidenceLocator,
    ) -> EvidenceRef | None:
        if not self.available:
            return None
        return EvidenceRef(
            source_id="source:bmstu-admission",
            source_observation_id="source-observation:" + "a" * 32,
            snapshot_sha256=snapshot_sha256,
            source_url=source_url,
            locator=locator,
        )


def _offering(*, minimum_score: str, admission_year: int = 2028) -> AdmissionOffering:
    source = AdmissionProvenance(
        source_kind="official_university_admission_rules",
        source_url=SOURCE_URL,
        captured_at=NOW,
        content_sha256="b" * 64,
        locator="Section 2, exam requirements",
        university_id=UNIVERSITY_ID,
        field="minimum_score",
        record_key="program-09.03.01-02-exam-math",
    )
    exam = ExamRequirement(
        subject="Mathematics",
        source_name="Mathematics",
        minimum_score=Decimal(minimum_score),
        provenance=source,
    )
    return AdmissionOffering(
        id=f"admission-offering:bmstu:{admission_year}:09.03.01-02:budget",
        program_id=PROGRAM_ID,
        admission_year=admission_year,
        study_form=StudyForm.FULL_TIME,
        funding_type=FundingType.BUDGET,
        scope=AdmissionScope.PROGRAM,
        exams=(exam,),
        provenance=(source,),
    )


def _revision(number: int, minimum_score: str) -> AdmissionOfferingRevision:
    offering = _offering(minimum_score=minimum_score)
    return AdmissionOfferingRevision(
        domain_rule_id=admission_offering_domain_rule_id(offering.id),
        offering_id=offering.id,
        revision=number,
        content_hash=admission_offering_revision_hash(offering),
        recorded_at=datetime(2027, 12, 16, tzinfo=UTC),
        offering=offering,
    )


def _reference(revision: AdmissionOfferingRevision) -> DomainRuleRef:
    return DomainRuleRef(
        owner_module=PolicyDomainOwner.ADMISSIONS,
        canonical_rule_id=revision.domain_rule_id,
        owner_revision=revision.revision,
        owner_revision_hash=revision.content_hash,
    )


def _context(*, admission_year: int = 2028) -> PolicyImpactContext:
    return PolicyImpactContext(
        university_id=UNIVERSITY_ID,
        admission_year=admission_year,
        context_fingerprint="c" * 64,
        applicability=PolicyApplicabilityContext(
            values=(
                PolicyContextValue(
                    field=PolicyContextField.PROGRAM_ID,
                    availability=PolicyContextAvailability.PRESENT,
                    value=PROGRAM_ID,
                ),
            )
        ),
    )


def test_admissions_policy_reader_returns_exact_revision_and_source_backed_diff() -> None:
    before = _revision(1, "75")
    after = _revision(2, "80")
    reader = AdmissionsPolicyRuleReader(
        _Revisions((before, after)),
        _SourceObservations(),
    )

    looked_up = reader.lookup_rule(_reference(after))
    impact = reader.compare_policy_rules(
        _reference(before), _reference(after), context=_context()
    )

    assert looked_up.status.value == "available"
    assert looked_up.resolved_reference == _reference(after)
    assert impact.status is DomainImpactStatus.EVALUATED
    assert impact.actionability is ImpactActionability.UNCERTAIN
    assert len(impact.changes) == 1
    assert ".minimum_score" in impact.changes[0].path
    assert impact.changes[0].before == '"75"'
    assert impact.changes[0].after == '"80"'
    assert impact.evidence


def test_admissions_policy_reader_fails_closed_for_wrong_year_or_uncaptured_source() -> None:
    before = _revision(1, "75")
    after = _revision(2, "80")
    revisions = _Revisions((before, after))
    reader = AdmissionsPolicyRuleReader(revisions, _SourceObservations(available=False))

    wrong_year = reader.compare_policy_rules(
        _reference(before), _reference(after), context=_context(admission_year=2027)
    )
    missing_evidence = reader.compare_policy_rules(
        _reference(before), _reference(after), context=_context()
    )
    wrong_hash = reader.lookup_rule(
        _reference(after).model_copy(update={"owner_revision_hash": "d" * 64})
    )

    assert wrong_year.status is DomainImpactStatus.UNAVAILABLE
    assert "admissions_owner_revision_context_mismatch" in wrong_year.missing_input_codes
    assert missing_evidence.status is DomainImpactStatus.UNAVAILABLE
    assert "admissions_owner_source_snapshot_not_captured_in_knowledge_registry" in (
        missing_evidence.missing_input_codes
    )
    assert wrong_hash.status.value == "not_found"


def test_admissions_policy_submission_service_requires_an_exact_v3_owner_reference() -> None:
    revision = SimpleNamespace(
        schema_version="policy-rule.v2",
        domain_rule=SimpleNamespace(owner_module=PolicyDomainOwner.ADMISSIONS),
    )
    submission = SimpleNamespace(
        revision=revision,
        submitted_by_account_id="account:" + "d" * 32,
    )

    class AllowAuthorizer:
        def require_capability(
            self, actor_account_id: str, capability: PolicyApprovalCapability
        ) -> None:
            assert actor_account_id == submission.submitted_by_account_id
            assert capability is PolicyApprovalCapability.SUBMIT_REVISION

    service = PolicyApprovalCommandService(
        repository=object(),  # type: ignore[arg-type]
        authorizer=AllowAuthorizer(),  # type: ignore[arg-type]
        unit_of_work=object(),  # type: ignore[arg-type]
    )

    try:
        service.submit(submission)  # type: ignore[arg-type]
    except ValidationError as error:
        assert "policy-rule.v3" in str(error)
    else:
        raise AssertionError("admissions owner references without exact hashes must be rejected")
