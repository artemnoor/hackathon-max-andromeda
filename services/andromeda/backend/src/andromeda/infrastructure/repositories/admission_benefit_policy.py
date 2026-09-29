"""Adapter from policy owner references to exact admission-benefit revisions."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

from andromeda.modules.admission_benefits.contracts.domain_revision import (
    admission_benefit_revision_hash,
    individual_achievement_domain_rule_id,
)
from andromeda.modules.admission_benefits.contracts.provenance import BenefitProvenance
from andromeda.modules.admission_benefits.contracts.public import (
    AdmissionBenefitRule,
    BenefitCondition,
    IndividualAchievementPolicy,
)
from andromeda.modules.admission_benefits.contracts.status import RuleDataStatus
from andromeda.modules.admission_benefits.repository.ports import AdmissionBenefitReader
from andromeda.modules.knowledge.contracts.public import (
    EvidenceLocator,
    EvidenceRef,
)
from andromeda.modules.knowledge.repository.ports import SourceObservationRepository
from andromeda.modules.policy.contracts.applicability import (
    PolicyDomainLookupStatus,
    PolicyDomainRuleLookup,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    DomainRuleImpactObservation,
    ImpactActionability,
    PolicyImpactContext,
)
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyDomainOwner,
)
from andromeda.modules.policy.contracts.semantic_diff import (
    PolicyDiffChangeKind,
    PolicyDiffEntry,
)
from andromeda.modules.policy.services.ports import (
    PolicyDomainImpactPort,
    PolicyDomainRuleReader,
)

_OMITTED_SEMANTIC_FIELDS = frozenset(
    {"id", "provenance", "source_text", "status", "policy_version"}
)
_SAFE_PATH_SEGMENT = re.compile(r"[^a-z0-9_.:-]+")
logger = logging.getLogger("andromeda.infrastructure.repositories.admission_benefit_policy")


class AdmissionBenefitsPolicyRuleReader(PolicyDomainRuleReader, PolicyDomainImpactPort):
    """Confirms exact owner revisions and compares their typed fields without scoring."""

    def __init__(
        self,
        reader: AdmissionBenefitReader,
        source_observations: SourceObservationRepository | None = None,
    ) -> None:
        self._reader = reader
        self._source_observations = source_observations

    @property
    def owner_module(self) -> PolicyDomainOwner:
        return PolicyDomainOwner.ADMISSION_BENEFITS

    def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup:
        logger.debug(
            "admission_benefit_policy_owner_lookup_started rule_id=%s revision_hash_prefix=%s",
            reference.canonical_rule_id,
            (reference.owner_revision_hash or "")[:12],
        )
        revision, error = self._load_active_revision(reference)
        if error is not None or revision is None:
            logger.info(
                "admission_benefit_policy_owner_lookup_unavailable rule_id=%s reason=%s",
                reference.canonical_rule_id,
                error or "owner_revision_missing",
            )
            return _lookup(reference, PolicyDomainLookupStatus.NOT_FOUND)
        logger.debug(
            "admission_benefit_policy_owner_lookup_available rule_id=%s",
            reference.canonical_rule_id,
        )
        return PolicyDomainRuleLookup(
            requested_reference=reference,
            resolved_reference=reference,
            status=PolicyDomainLookupStatus.AVAILABLE,
        )

    def compare_policy_rules(
        self,
        before: DomainRuleRef | None,
        after: DomainRuleRef | None,
        *,
        context: PolicyImpactContext,
    ) -> DomainRuleImpactObservation:
        """Return evidence-backed field changes; applicant eligibility stays with its owner."""
        before_revision, before_error = self._load_active_revision(before)
        after_revision, after_error = self._load_active_revision(after)
        logger.info(
            "admission_benefit_policy_impact_started before_rule=%s after_rule=%s admission_year=%d",
            before.canonical_rule_id if before is not None else None,
            after.canonical_rule_id if after is not None else None,
            context.admission_year,
        )
        missing = tuple(code for code in (before_error, after_error) if code is not None)
        if missing:
            return _unavailable_impact(before, after, missing)

        for revision in (before_revision, after_revision):
            if revision is not None and (
                revision.university_id != context.university_id
                or revision.admission_year != context.admission_year
            ):
                return _unavailable_impact(
                    before,
                    after,
                    ("domain_owner_context_does_not_match_exact_revision",),
                )

        before_evidence, before_evidence_error = self._revision_evidence(before_revision)
        after_evidence, after_evidence_error = self._revision_evidence(after_revision)
        missing_evidence = tuple(
            code
            for code in (before_evidence_error, after_evidence_error)
            if code is not None
        )
        if missing_evidence:
            return _unavailable_impact(before, after, missing_evidence)

        before_fields = _semantic_fields(before_revision)
        after_fields = _semantic_fields(after_revision)
        all_paths = sorted(set(before_fields) | set(after_fields))
        if len(all_paths) > 128:
            return _unavailable_impact(
                before,
                after,
                ("domain_owner_semantic_diff_limit_exceeded",),
            )
        changes = tuple(
            _field_change(
                path,
                before_fields.get(path),
                after_fields.get(path),
                before_evidence,
                after_evidence,
            )
            for path in all_paths
            if before_fields.get(path) != after_fields.get(path)
        )
        evidence = _unique_evidence((*before_evidence, *after_evidence))
        if not changes:
            result = DomainRuleImpactObservation(
                owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
                before_rule=before,
                after_rule=after,
                status=DomainImpactStatus.NO_DOMAIN_CHANGE,
                evidence=evidence,
            )
            logger.info(
                "admission_benefit_policy_impact_completed status=%s changes=0 evidence=%d",
                result.status.value,
                len(result.evidence),
            )
            return result
        # This review context has no applicant facts; it can show exact rule deltas,
        # but actionability must remain uncertain until AdmissionDecisionService runs.
        result = DomainRuleImpactObservation(
            owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
            before_rule=before,
            after_rule=after,
            status=DomainImpactStatus.EVALUATED,
            actionability=ImpactActionability.UNCERTAIN,
            changes=changes,
            evidence=evidence,
        )
        logger.info(
            "admission_benefit_policy_impact_completed status=%s changes=%d evidence=%d",
            result.status.value,
            len(result.changes),
            len(result.evidence),
        )
        return result

    def _load_active_revision(
        self, reference: DomainRuleRef | None
    ) -> tuple[AdmissionBenefitRule | IndividualAchievementPolicy | None, str | None]:
        if reference is None:
            return None, None
        if (
            reference.owner_module is not PolicyDomainOwner.ADMISSION_BENEFITS
            or reference.owner_revision_hash is None
        ):
            return None, "domain_owner_exact_revision_reference_missing"
        if reference.canonical_rule_id.startswith("admission-benefit:"):
            benefit_revision = self._reader.get_rule_revision(
                reference.canonical_rule_id,
                reference.owner_revision_hash,
            )
            if benefit_revision is None or benefit_revision.status is not RuleDataStatus.ACTIVE:
                return None, "domain_owner_exact_active_revision_unavailable"
            if admission_benefit_revision_hash(benefit_revision) != reference.owner_revision_hash:
                return None, "domain_owner_exact_revision_hash_mismatch"
            return benefit_revision, None
        if reference.canonical_rule_id.startswith("individual-achievement:"):
            suffix = reference.canonical_rule_id.removeprefix("individual-achievement:")
            policy_id = f"individual-achievement-policy:{suffix}"
            achievement_revision = self._reader.get_individual_achievement_policy_revision(
                policy_id,
                reference.owner_revision_hash,
            )
            if achievement_revision is None or achievement_revision.status is not RuleDataStatus.ACTIVE:
                return None, "domain_owner_exact_active_revision_unavailable"
            if admission_benefit_revision_hash(achievement_revision) != reference.owner_revision_hash:
                return None, "domain_owner_exact_revision_hash_mismatch"
            if individual_achievement_domain_rule_id(achievement_revision) != reference.canonical_rule_id:
                return None, "domain_owner_canonical_identity_mismatch"
            return achievement_revision, None
        return None, "domain_owner_rule_kind_unsupported"

    def _revision_evidence(
        self,
        revision: AdmissionBenefitRule | IndividualAchievementPolicy | None,
    ) -> tuple[tuple[EvidenceRef, ...], str | None]:
        if revision is None:
            return (), None
        if self._source_observations is None:
            return (), "domain_owner_source_observation_reader_unavailable"
        provenances = _revision_provenance(revision)
        if len(provenances) > 128:
            return (), "domain_owner_source_evidence_limit_exceeded"
        evidence: list[EvidenceRef] = []
        for provenance in provenances:
            locator = EvidenceLocator(
                page=provenance.page,
                table=provenance.table,
                row=provenance.row,
                section=provenance.section,
                field=provenance.source.field,
                record_key=provenance.source.record_key,
            )
            reference = self._source_observations.resolve_snapshot_evidence(
                source_url=provenance.source.url,
                snapshot_sha256=provenance.source_snapshot_hash,
                locator=locator,
            )
            if reference is None:
                return (), "domain_owner_source_snapshot_not_captured_in_knowledge_registry"
            evidence.append(reference)
        unique = _unique_evidence(evidence)
        if not unique:
            return (), "domain_owner_source_evidence_missing"
        if len(unique) > 128:
            return (), "domain_owner_source_evidence_limit_exceeded"
        return unique, None


def _semantic_fields(
    revision: AdmissionBenefitRule | IndividualAchievementPolicy | None,
) -> dict[str, str]:
    if revision is None:
        return {}
    payload = revision.model_dump(mode="json")
    if isinstance(revision, IndividualAchievementPolicy):
        payload["rules"] = {
            str(rule["id"]): {
                key: value
                for key, value in rule.items()
                if key not in _OMITTED_SEMANTIC_FIELDS
            }
            for rule in payload["rules"]
        }
    fields: dict[str, str] = {}
    _flatten_semantic_fields(payload, ("domain_owner", "admission_benefits"), fields)
    return fields


def _flatten_semantic_fields(
    value: object,
    path: tuple[str, ...],
    output: dict[str, str],
) -> None:
    if isinstance(value, dict):
        for key, item in sorted(value.items()):
            if key in _OMITTED_SEMANTIC_FIELDS:
                continue
            _flatten_semantic_fields(item, (*path, _path_segment(str(key))), output)
        return
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    output[".".join(path)] = serialized


def _field_change(
    path: str,
    before_value: str | None,
    after_value: str | None,
    before_evidence: tuple[EvidenceRef, ...],
    after_evidence: tuple[EvidenceRef, ...],
) -> PolicyDiffEntry:
    if before_value is None:
        kind = PolicyDiffChangeKind.ADDED
    elif after_value is None:
        kind = PolicyDiffChangeKind.REMOVED
    else:
        kind = PolicyDiffChangeKind.CHANGED
    return PolicyDiffEntry(
        path=path,
        kind=kind,
        before=before_value,
        after=after_value,
        before_evidence=before_evidence if before_value is not None else (),
        after_evidence=after_evidence if after_value is not None else (),
        reason_code="admission_benefits_owner_semantic_change",
    )


def _revision_provenance(
    revision: AdmissionBenefitRule | IndividualAchievementPolicy,
) -> tuple[BenefitProvenance, ...]:
    if isinstance(revision, AdmissionBenefitRule):
        conditions: tuple[BenefitCondition, ...] = revision.conditions
        return _unique_provenance(
            (revision.provenance, *(item.provenance for item in conditions if item.provenance))
        )
    sources: list[BenefitProvenance] = [revision.provenance]
    for rule in revision.rules:
        sources.append(rule.provenance)
        sources.extend(item.provenance for item in rule.conditions if item.provenance)
    return _unique_provenance(sources)


def _unique_provenance(items: Iterable[BenefitProvenance]) -> tuple[BenefitProvenance, ...]:
    unique = {
        (
            str(item.source.url),
            item.source_snapshot_hash,
            item.page,
            item.table,
            item.row,
            item.section,
            item.source.field,
            item.source.record_key,
        ): item
        for item in items
    }
    return tuple(unique[key] for key in sorted(unique))


def _unique_evidence(items: Iterable[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    unique = {
        (
            item.source_id,
            item.source_observation_id,
            item.snapshot_sha256,
            str(item.source_url),
            item.locator.model_dump_json(),
        ): item
        for item in items
    }
    return tuple(unique[key] for key in sorted(unique))


def _path_segment(value: str) -> str:
    sanitized = _SAFE_PATH_SEGMENT.sub("-", value.lower()).strip("-")
    return sanitized or "unknown"


def _unavailable_impact(
    before: DomainRuleRef | None,
    after: DomainRuleRef | None,
    missing: tuple[str, ...],
) -> DomainRuleImpactObservation:
    logger.info(
        "admission_benefit_policy_impact_unavailable before_rule=%s after_rule=%s missing_inputs=%s",
        before.canonical_rule_id if before is not None else None,
        after.canonical_rule_id if after is not None else None,
        ",".join(missing),
    )
    return DomainRuleImpactObservation(
        owner_module=PolicyDomainOwner.ADMISSION_BENEFITS,
        before_rule=before,
        after_rule=after,
        status=DomainImpactStatus.UNAVAILABLE,
        actionability=ImpactActionability.BLOCKED_BY_MISSING_DATA,
        missing_input_codes=missing,
    )


def _lookup(reference: DomainRuleRef, status: PolicyDomainLookupStatus) -> PolicyDomainRuleLookup:
    return PolicyDomainRuleLookup(requested_reference=reference, status=status)


__all__ = ["AdmissionBenefitsPolicyRuleReader"]
