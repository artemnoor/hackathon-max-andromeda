"""Exact policy references and semantic diffs for admissions owner revisions."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable

from pydantic import TypeAdapter

from andromeda.modules.admissions.contracts.offering_revisions import (
    AdmissionOfferingRevision,
    admission_offering_domain_rule_id,
)
from andromeda.modules.admissions.contracts.public import AdmissionProvenance
from andromeda.modules.admissions.repository.ports import (
    AdmissionOfferingRevisionReader,
)
from andromeda.modules.knowledge.contracts.public import EvidenceLocator, EvidenceRef
from andromeda.modules.knowledge.repository.ports import SourceObservationRepository
from andromeda.modules.policy.contracts.applicability import (
    PolicyContextAvailability,
    PolicyDomainLookupStatus,
    PolicyDomainRuleLookup,
)
from andromeda.modules.policy.contracts.impact import (
    DomainImpactStatus,
    DomainRuleImpactObservation,
    ImpactActionability,
    PolicyImpactContext,
)
from andromeda.modules.policy.contracts.rule import DomainRuleRef, PolicyDomainOwner
from andromeda.modules.policy.contracts.rule_ast import PolicyContextField
from andromeda.modules.policy.contracts.semantic_diff import (
    PolicyDiffChangeKind,
    PolicyDiffEntry,
)
from andromeda.modules.policy.services.ports import (
    PolicyDomainImpactPort,
    PolicyDomainRuleReader,
)
from andromeda.shared.contracts.ids import ProgramId

logger = logging.getLogger("andromeda.infrastructure.repositories.admission_policy")
_MAX_EVIDENCE = 128
_OMITTED_FIELDS = frozenset({"id", "provenance", "program_id", "admission_year"})
_COLLECTION_IDENTITIES: dict[str, tuple[str, ...]] = {
    "exams": ("subject", "source_name"),
    "quotas": ("quota_type", "source_name"),
    "passing_scores": ("score_type", "competition_type", "status"),
    "tuition": ("currency", "academic_year", "period", "study_form", "is_discounted"),
}
_PROGRAM_ID_ADAPTER = TypeAdapter(ProgramId)


class AdmissionsPolicyRuleReader(PolicyDomainRuleReader, PolicyDomainImpactPort):
    """Confirms exact admissions facts and reports source-backed deltas only."""

    def __init__(
        self,
        revisions: AdmissionOfferingRevisionReader,
        source_observations: SourceObservationRepository,
    ) -> None:
        self._revisions = revisions
        self._source_observations = source_observations

    @property
    def owner_module(self) -> PolicyDomainOwner:
        return PolicyDomainOwner.ADMISSIONS

    def lookup_rule(self, reference: DomainRuleRef) -> PolicyDomainRuleLookup:
        revision, error = self._load_revision(reference)
        if error is not None or revision is None:
            logger.info(
                "admissions_policy_owner_lookup_unavailable rule_id=%s reason=%s",
                reference.canonical_rule_id,
                error or "owner_revision_missing",
            )
            return _lookup(reference, PolicyDomainLookupStatus.NOT_FOUND)
        return _lookup(reference, PolicyDomainLookupStatus.AVAILABLE)

    def compare_policy_rules(
        self,
        before: DomainRuleRef | None,
        after: DomainRuleRef | None,
        *,
        context: PolicyImpactContext,
    ) -> DomainRuleImpactObservation:
        before_revision, before_error = self._load_optional(before)
        after_revision, after_error = self._load_optional(after)
        missing = tuple(code for code in (before_error, after_error) if code is not None)
        if missing:
            return _unavailable(before, after, missing)

        program_value = context.applicability.value_for(PolicyContextField.PROGRAM_ID)
        if (
            program_value.availability is not PolicyContextAvailability.PRESENT
            or not isinstance(program_value.value, str)
        ):
            return _unavailable(before, after, ("admissions_program_context_missing",))
        try:
            program_id = _PROGRAM_ID_ADAPTER.validate_python(program_value.value)
        except ValueError:
            return _unavailable(before, after, ("admissions_program_context_invalid",))

        for revision in (before_revision, after_revision):
            if revision is None:
                continue
            offering = revision.offering
            if offering.program_id != program_id or offering.admission_year != context.admission_year:
                return _unavailable(
                    before,
                    after,
                    ("admissions_owner_revision_context_mismatch",),
                )
            universities = {
                provenance.university_id for provenance in _all_provenance(revision)
            }
            if None in universities:
                return _unavailable(
                    before,
                    after,
                    ("admissions_owner_university_provenance_missing",),
                )
            if universities != {context.university_id}:
                return _unavailable(
                    before,
                    after,
                    ("admissions_owner_university_context_mismatch",),
                )

        before_evidence, before_evidence_error = self._revision_evidence(before_revision)
        after_evidence, after_evidence_error = self._revision_evidence(after_revision)
        evidence_errors = tuple(
            code
            for code in (before_evidence_error, after_evidence_error)
            if code is not None
        )
        if evidence_errors:
            return _unavailable(before, after, evidence_errors)

        before_fields = _semantic_fields(before_revision)
        after_fields = _semantic_fields(after_revision)
        if before_fields is None or after_fields is None:
            return _unavailable(before, after, ("admissions_owner_semantic_identity_ambiguous",))
        paths = sorted(set(before_fields) | set(after_fields))
        if len(paths) > _MAX_EVIDENCE:
            return _unavailable(before, after, ("admissions_owner_semantic_diff_limit_exceeded",))
        changes = tuple(
            _field_change(
                path,
                before_fields.get(path),
                after_fields.get(path),
                before_evidence,
                after_evidence,
            )
            for path in paths
            if before_fields.get(path) != after_fields.get(path)
        )
        evidence = _unique_evidence((*before_evidence, *after_evidence))
        if not changes:
            return DomainRuleImpactObservation(
                owner_module=self.owner_module,
                before_rule=before,
                after_rule=after,
                status=DomainImpactStatus.NO_DOMAIN_CHANGE,
                evidence=evidence,
            )
        # There are no applicant facts in this preview. The admissions owner
        # exposes facts and the existing fit/benefit services remain calculators.
        return DomainRuleImpactObservation(
            owner_module=self.owner_module,
            before_rule=before,
            after_rule=after,
            status=DomainImpactStatus.EVALUATED,
            actionability=ImpactActionability.UNCERTAIN,
            changes=changes,
            evidence=evidence,
        )

    def _load_optional(
        self, reference: DomainRuleRef | None
    ) -> tuple[AdmissionOfferingRevision | None, str | None]:
        if reference is None:
            return None, None
        return self._load_revision(reference)

    def _load_revision(
        self, reference: DomainRuleRef
    ) -> tuple[AdmissionOfferingRevision | None, str | None]:
        if (
            reference.owner_module is not PolicyDomainOwner.ADMISSIONS
            or reference.owner_revision_hash is None
        ):
            return None, "admissions_exact_owner_revision_reference_missing"
        revision = self._revisions.get_offering_revision(
            reference.canonical_rule_id,
            reference.owner_revision,
            reference.owner_revision_hash,
        )
        if revision is None:
            return None, "admissions_exact_owner_revision_unavailable"
        if (
            revision.domain_rule_id != reference.canonical_rule_id
            or revision.revision != reference.owner_revision
            or revision.content_hash != reference.owner_revision_hash
            or revision.domain_rule_id
            != admission_offering_domain_rule_id(revision.offering_id)
        ):
            return None, "admissions_exact_owner_revision_mismatch"
        return revision, None

    def _revision_evidence(
        self,
        revision: AdmissionOfferingRevision | None,
    ) -> tuple[tuple[EvidenceRef, ...], str | None]:
        if revision is None:
            return (), None
        provenances = _all_provenance(revision)
        if not provenances:
            return (), "admissions_owner_source_evidence_missing"
        if len(provenances) > _MAX_EVIDENCE:
            return (), "admissions_owner_source_evidence_limit_exceeded"
        evidence: list[EvidenceRef] = []
        for provenance in provenances:
            if provenance.inferred:
                return (), "admissions_owner_inferred_source_fact_not_applicable"
            locator = EvidenceLocator(
                section=provenance.locator or provenance.field,
                field=provenance.field if provenance.field and len(provenance.field) <= 128 else None,
                record_key=provenance.record_key,
            )
            source_evidence = self._source_observations.resolve_snapshot_evidence(
                source_url=provenance.source_url,
                snapshot_sha256=provenance.content_sha256,
                locator=locator,
            )
            if source_evidence is None:
                return (), "admissions_owner_source_snapshot_not_captured_in_knowledge_registry"
            evidence.append(source_evidence)
        unique = _unique_evidence(evidence)
        if not unique:
            return (), "admissions_owner_source_evidence_missing"
        if len(unique) > _MAX_EVIDENCE:
            return (), "admissions_owner_source_evidence_limit_exceeded"
        return unique, None


def _all_provenance(revision: AdmissionOfferingRevision) -> tuple[AdmissionProvenance, ...]:
    offering = revision.offering
    return (
        *offering.provenance,
        *(item.provenance for item in offering.exams),
        *(item.provenance for item in offering.quotas),
        *(item.provenance for item in offering.passing_scores),
        *(item.provenance for item in offering.tuition),
    )


def _semantic_fields(
    revision: AdmissionOfferingRevision | None,
) -> dict[str, str] | None:
    if revision is None:
        return {}
    payload = revision.offering.model_dump(mode="json")
    payload = {key: value for key, value in payload.items() if key not in _OMITTED_FIELDS}
    for collection_name, identity_fields in _COLLECTION_IDENTITIES.items():
        collection = payload.get(collection_name)
        if not isinstance(collection, list):
            continue
        normalized: dict[str, object] = {}
        for raw in collection:
            if not isinstance(raw, dict):
                return None
            identity = tuple(raw.get(field) for field in identity_fields)
            identity_json = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            identity_hash = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()[:16]
            if identity_hash in normalized:
                return None
            normalized[identity_hash] = {
                key: value
                for key, value in raw.items()
                if key not in _OMITTED_FIELDS
            }
        payload[collection_name] = normalized
    fields: dict[str, str] = {}
    _flatten(payload, ("domain_owner", "admissions"), fields)
    return fields


def _flatten(value: object, path: tuple[str, ...], output: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, item in sorted(value.items()):
            if key in _OMITTED_FIELDS:
                continue
            _flatten(item, (*path, _safe_segment(str(key))), output)
        return
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    output[".".join(path)] = serialized


def _safe_segment(value: str) -> str:
    safe = "".join(char.lower() if char.isalnum() or char in "_.:-" else "-" for char in value)
    safe = safe.strip("-")
    if not safe or len(safe) > 96:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return safe


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
        reason_code="admissions_owner_semantic_change",
    )


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


def _lookup(
    reference: DomainRuleRef, status: PolicyDomainLookupStatus
) -> PolicyDomainRuleLookup:
    return PolicyDomainRuleLookup(
        requested_reference=reference,
        status=status,
        resolved_reference=reference if status is PolicyDomainLookupStatus.AVAILABLE else None,
    )


def _unavailable(
    before: DomainRuleRef | None,
    after: DomainRuleRef | None,
    missing: tuple[str, ...],
) -> DomainRuleImpactObservation:
    return DomainRuleImpactObservation(
        owner_module=PolicyDomainOwner.ADMISSIONS,
        before_rule=before,
        after_rule=after,
        status=DomainImpactStatus.UNAVAILABLE,
        actionability=ImpactActionability.BLOCKED_BY_MISSING_DATA,
        missing_input_codes=missing,
    )


__all__ = ["AdmissionsPolicyRuleReader"]
