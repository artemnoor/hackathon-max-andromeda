"""Narrow read ports used by policy applicability and owner reference dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from andromeda.modules.admissions.contracts.admission_cycles import (
    AdmissionCycleResolution,
)
from andromeda.modules.policy.contracts.applicability import PolicyDomainRuleLookup
from andromeda.modules.policy.contracts.impact import (
    DomainRuleImpactObservation,
    PolicyImpactContext,
)
from andromeda.modules.policy.contracts.refresh import PolicyProjectionRefreshRecord
from andromeda.modules.policy.contracts.rule import DomainRuleRef, PolicyDomainOwner
from andromeda.shared.contracts.ids import EducationYear, UniversityId


class PolicyAdmissionCycleReader(Protocol):
    """Consumer-owned port to the admissions module's approved cycle read contract."""

    def resolve_for_admission(
        self,
        university_id: UniversityId,
        admission_year: EducationYear,
        *,
        as_known_at: datetime | None = None,
    ) -> AdmissionCycleResolution: ...


class PolicyClock(Protocol):
    def now(self) -> datetime: ...


class PolicyDomainRuleReader(Protocol):
    """An owning module confirms that one exact canonical rule revision exists."""

    @property
    def owner_module(self) -> PolicyDomainOwner: ...

    def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup: ...


class PolicyDomainImpactPort(Protocol):
    """Existing domain owner compares exact rules using its current evaluator semantics."""

    @property
    def owner_module(self) -> PolicyDomainOwner: ...

    def compare_policy_rules(
        self,
        before: DomainRuleRef | None,
        after: DomainRuleRef | None,
        *,
        context: PolicyImpactContext,
    ) -> DomainRuleImpactObservation: ...


class PolicyProjectionRefreshBuilder(Protocol):
    """Rebuilds one typed, non-user-specific projection and returns its content version."""

    def rebuild(self, record: PolicyProjectionRefreshRecord) -> str: ...


__all__ = [
    "PolicyAdmissionCycleReader",
    "PolicyClock",
    "PolicyDomainImpactPort",
    "PolicyDomainRuleReader",
    "PolicyProjectionRefreshBuilder",
]
