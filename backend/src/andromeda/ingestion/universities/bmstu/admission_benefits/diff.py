"""Deterministic source-revision and canonical-rule diffing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import Field

from andromeda.modules.admission_benefits.contracts.public import AdmissionBenefitRule
from andromeda.modules.admission_benefits.contracts.status import RuleDataStatus
from andromeda.shared.contracts.base import ContractModel


class AdmissionBenefitSourceRevision(ContractModel):
    """One captured official document revision used by a diff."""

    document_kind: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2_048)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AdmissionBenefitDiff(ContractModel):
    """Safe operator-facing diff; it never deletes or mutates old facts."""

    added_documents: tuple[str, ...] = ()
    removed_documents: tuple[str, ...] = ()
    changed_documents: tuple[str, ...] = ()
    added_rule_ids: tuple[str, ...] = ()
    removed_rule_ids: tuple[str, ...] = ()
    stale_rule_ids: tuple[str, ...] = ()
    review_rule_ids: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added_documents,
                self.removed_documents,
                self.changed_documents,
                self.added_rule_ids,
                self.removed_rule_ids,
                self.stale_rule_ids,
                self.review_rule_ids,
            )
        )


def diff_admission_benefits(
    previous_sources: Mapping[str, AdmissionBenefitSourceRevision],
    current_sources: Mapping[str, AdmissionBenefitSourceRevision],
    *,
    previous_rules: Iterable[AdmissionBenefitRule] = (),
    current_rules: Iterable[AdmissionBenefitRule] = (),
) -> AdmissionBenefitDiff:
    """Compare source revisions and canonical rules without treating absence as deletion.

    A source replacement marks rules from the previous revision as stale. The
    caller can then persist the new snapshot and let the repository's existing
    stale-refresh policy decide which revision is active.
    """

    previous_keys = set(previous_sources)
    current_keys = set(current_sources)
    added_documents = tuple(sorted(current_keys - previous_keys))
    removed_documents = tuple(sorted(previous_keys - current_keys))
    changed_documents = tuple(
        sorted(
            key
            for key in previous_keys & current_keys
            if previous_sources[key].content_sha256 != current_sources[key].content_sha256
        )
    )

    previous_rule_values = tuple(previous_rules)
    current_rule_values = tuple(current_rules)
    previous_ids = {rule.id for rule in previous_rule_values}
    current_ids = {rule.id for rule in current_rule_values}
    stale_rule_ids = tuple(
        sorted(
            rule.id
            for rule in previous_rule_values
            if rule.provenance.document_kind in changed_documents
            or (
                rule.provenance.document_kind in removed_documents
                and rule.provenance.document_kind not in current_keys
            )
        )
    )
    review_rule_ids = tuple(
        sorted(
            rule.id
            for rule in current_rule_values
            if rule.status in {RuleDataStatus.REVIEW_REQUIRED, RuleDataStatus.CONFLICT}
        )
    )
    return AdmissionBenefitDiff(
        added_documents=added_documents,
        removed_documents=removed_documents,
        changed_documents=changed_documents,
        added_rule_ids=tuple(sorted(current_ids - previous_ids)),
        removed_rule_ids=tuple(sorted(previous_ids - current_ids)),
        stale_rule_ids=stale_rule_ids,
        review_rule_ids=review_rule_ids,
    )


__all__ = [
    "AdmissionBenefitDiff",
    "AdmissionBenefitSourceRevision",
    "diff_admission_benefits",
]
