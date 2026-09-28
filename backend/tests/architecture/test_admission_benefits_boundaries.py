from __future__ import annotations

import ast
from pathlib import Path

from andromeda.modules.admission_benefits import BenefitScope, BenefitTarget
from andromeda.shared.contracts.versions import (
    ADMISSION_BENEFITS_PARSER_VERSION,
    ADMISSION_BENEFITS_POLICY_VERSION,
    ADMISSION_BENEFITS_SCHEMA_VERSION,
)

PROJECT_ROOT = Path(__file__).parents[2]
MODULE_ROOT = PROJECT_ROOT / "src" / "andromeda" / "modules" / "admission_benefits"
FORBIDDEN_IMPORT_PREFIXES = (
    "andromeda.api",
    "andromeda.composition",
    "andromeda.infrastructure",
    "andromeda.ingestion",
    "sqlalchemy",
    "jev",
    "fastapi",
)


def test_admission_benefits_public_surface_and_versions_are_available() -> None:
    assert BenefitScope is not None
    assert BenefitTarget is not None
    assert ADMISSION_BENEFITS_SCHEMA_VERSION == "admission-benefits-schema.v1"
    assert ADMISSION_BENEFITS_PARSER_VERSION == "admission-benefits-parser.v1"
    assert ADMISSION_BENEFITS_POLICY_VERSION == "admission-benefits-policy.v1"


def test_admission_benefits_contracts_have_no_outer_runtime_dependencies() -> None:
    violations: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.append(node.module)
        for imported in imports:
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(MODULE_ROOT)} -> {imported}")
    assert violations == []


def test_bounded_context_exposes_only_contracts_at_root() -> None:
    exported = set(__import__("andromeda.modules.admission_benefits", fromlist=["__all__"]).__all__)
    assert exported == {
        "AdmissionBenefitEvaluation",
        "AdmissionBenefitEvidence",
        "AdmissionDecisionResult",
        "AdmissionBenefitRule",
        "AdmissionEligibilityResult",
        "AdmissionRoute",
        "AchievementCombinationPolicy",
        "ApplicantAdmissionFacts",
        "ApplicantExamScore",
        "ApplicantInternalExamScore",
        "ApplicantIndividualAchievement",
        "ApplicantOlympiadAchievement",
        "ApplicabilityStatus",
        "BenefitCondition",
        "BenefitConditionKind",
        "BenefitPolicyVersion",
        "BenefitProvenance",
        "BenefitScope",
        "BenefitScopeMode",
        "BenefitTarget",
        "BenefitTargetKind",
        "BenefitType",
        "ConfirmationExamKind",
        "ConfirmationRequirement",
        "ConfirmationSubjectRule",
        "EligibilityStatus",
        "IndividualAchievementBreakdown",
        "IndividualAchievementEvaluation",
        "IndividualAchievementStatus",
        "IndividualAchievementPolicy",
        "IndividualAchievementRule",
        "Olympiad",
        "OlympiadProfile",
        "OlympiadProfileSubject",
        "OlympiadResultType",
        "RuleDataStatus",
        "ScopeApplicability",
        "TargetResolutionStatus",
        "ValidityPolicy",
        "can_transition_status",
    }
