from __future__ import annotations

from andromeda.modules.admission_benefits.contracts.applicant import (
    ApplicantAdmissionFacts,
)
from andromeda.modules.admission_benefits.contracts.coverage import (
    AdmissionBenefitCoverage,
    AdmissionBenefitCoverageStatus,
)
from andromeda.modules.admission_benefits.contracts.domain_revision import (
    admission_benefit_revision_hash,
    individual_achievement_domain_rule_id,
)
from andromeda.modules.admission_benefits.contracts.policy_evaluation import (
    AdmissionBenefitPolicyEvaluationRequest,
    AdmissionBenefitPolicyEvaluationStatus,
    AdmissionBenefitPolicyRuleRef,
    ApplicantAdmissionContext,
    ApplicantFactDimension,
)
from andromeda.modules.admission_benefits.contracts.snapshot import (
    AdmissionBenefitsSnapshot,
)
from andromeda.modules.admission_benefits.services.policy_evaluation import (
    AdmissionBenefitsPolicyEvaluationService,
)
from andromeda.modules.admissions.contracts.public import ProgramAdmissions

from .test_helpers import (
    DIRECTION_CODE,
    PROGRAM_ID,
    achievement_fact,
    achievement_policy,
    achievement_rule,
    olympiad_fact,
    olympiad_rule,
    provenance,
)

UNIVERSITY_ID = "university:bmstu"


def _snapshot() -> AdmissionBenefitsSnapshot:
    rule = olympiad_rule()
    policy = achievement_policy(achievement_rule("gto_gold", "5"))
    source = provenance().source
    return AdmissionBenefitsSnapshot(
        university_id=UNIVERSITY_ID,
        admission_year=2026,
        sources=(source,),
        benefit_rules=(rule,),
        individual_achievement_policy=policy,
        coverage=AdmissionBenefitCoverage(
            status=AdmissionBenefitCoverageStatus.COMPLETE,
            source_hashes=(source.content_sha256,),
        ),
    )


class _Reader:
    def __init__(self, snapshot: AdmissionBenefitsSnapshot) -> None:
        self.snapshot = snapshot

    def get_catalog(self, _university_id, _admission_year, _education_level=None):
        return self.snapshot

    def get_rules_for_program(
        self, _program_id, _admission_year, *, include_review=False, campus_id=None
    ):
        return self.snapshot.benefit_rules

    def get_individual_achievement_policy(
        self,
        _university_id,
        _admission_year,
        _education_level=None,
        *,
        include_review=False,
    ):
        return self.snapshot.individual_achievement_policy

    def get_rule_revision(self, rule_id, revision_hash):
        return next(
            (
                item
                for item in self.snapshot.benefit_rules
                if item.id == rule_id
                and admission_benefit_revision_hash(item) == revision_hash
            ),
            None,
        )

    def get_individual_achievement_policy_revision(self, _policy_id, revision_hash):
        policy = self.snapshot.individual_achievement_policy
        if (
            policy is not None
            and admission_benefit_revision_hash(policy) == revision_hash
        ):
            return policy
        return None


class _Admissions:
    def get_for_program(self, program_id):
        return ProgramAdmissions(program_id=program_id)


def _request(
    snapshot: AdmissionBenefitsSnapshot, *, complete: bool
) -> AdmissionBenefitPolicyEvaluationRequest:
    rule = snapshot.benefit_rules[0]
    policy = snapshot.individual_achievement_policy
    assert policy is not None
    return AdmissionBenefitPolicyEvaluationRequest(
        university_id=UNIVERSITY_ID,
        program_id=PROGRAM_ID,
        direction_code=DIRECTION_CODE,
        admission_year=2026,
        applicant=ApplicantAdmissionContext(
            facts=ApplicantAdmissionFacts(
                olympiad_achievements=(olympiad_fact(),),
                individual_achievements=(achievement_fact("gto_gold"),),
            ),
            complete_dimensions=(
                ApplicantFactDimension.EGE_SCORES,
                ApplicantFactDimension.INTERNAL_EXAM_SCORES,
                ApplicantFactDimension.OLYMPIAD_ACHIEVEMENTS,
                ApplicantFactDimension.INDIVIDUAL_ACHIEVEMENTS,
                ApplicantFactDimension.CONFIRMATION_CATEGORY,
            )
            if complete
            else (),
        ),
        selected_rules=(
            AdmissionBenefitPolicyRuleRef(
                rule_id=rule.id,
                revision_hash=admission_benefit_revision_hash(rule),
            ),
        ),
        selected_individual_policy_id=individual_achievement_domain_rule_id(policy),
        selected_individual_policy_hash=admission_benefit_revision_hash(policy),
    )


def test_exact_approved_owner_revisions_delegate_to_existing_decision_service() -> None:
    snapshot = _snapshot()
    result = AdmissionBenefitsPolicyEvaluationService(
        _Reader(snapshot),
        _Admissions(),  # type: ignore[arg-type]
    ).evaluate(_request(snapshot, complete=True))

    assert result.status is AdmissionBenefitPolicyEvaluationStatus.EVALUATED
    assert result.decision is not None
    assert result.decision.route.value == "olympiad"
    assert result.decision.individual_achievement_points == 5
    assert result.decision.eligibility is not None
    assert result.decision.eligibility.evaluations[0].evidence[
        0
    ].provenance.source_snapshot_hash == (snapshot.sources[0].content_sha256)


def test_missing_applicant_fact_completeness_fails_closed_before_calculation() -> None:
    snapshot = _snapshot()
    result = AdmissionBenefitsPolicyEvaluationService(
        _Reader(snapshot),
        _Admissions(),  # type: ignore[arg-type]
    ).evaluate(_request(snapshot, complete=False))

    assert result.status is AdmissionBenefitPolicyEvaluationStatus.INSUFFICIENT_DATA
    assert result.decision is None
    assert result.missing_input_codes == (
        "applicant_individual_achievements_completeness_unconfirmed",
        "applicant_olympiad_achievements_completeness_unconfirmed",
    )


def test_selected_revision_hash_must_cover_complete_owner_rule_set() -> None:
    snapshot = _snapshot()
    request = _request(snapshot, complete=True).model_copy(
        update={"selected_rules": ()}
    )
    result = AdmissionBenefitsPolicyEvaluationService(
        _Reader(snapshot),
        _Admissions(),  # type: ignore[arg-type]
    ).evaluate(request)

    assert result.status is AdmissionBenefitPolicyEvaluationStatus.UNAVAILABLE
    assert "effective_policy_does_not_cover_complete_benefit_rule_set" in (
        result.missing_input_codes
    )
