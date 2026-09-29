"""Exact, source-linked conflict groups and append-only resolution history."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from andromeda.shared.contracts.base import ContractModel
from andromeda.shared.contracts.ids import AccountId, NonEmptyText, SourceHash

from .evidence import EvidenceRef

KnowledgeConflictGroupId = Annotated[
    str, StringConstraints(pattern=r"^knowledge-conflict:[a-f0-9]{64}$")
]
KnowledgeConflictEventId = Annotated[
    str, StringConstraints(pattern=r"^knowledge-conflict-event:[a-f0-9]{64}$")
]


class KnowledgeConflictKind(StrEnum):
    CONTRADICTORY_CLAIMS = "contradictory_claims"
    POLICY_PRECEDENCE = "policy_precedence"
    STALE_SOURCE_DISAGREEMENT = "stale_source_disagreement"
    SAME_ISSUER_AMENDMENT = "same_issuer_amendment"
    OVERLAPPING_SCOPE_TIME = "overlapping_scope_time"


class KnowledgeConflictScopeLevel(StrEnum):
    FEDERAL = "federal"
    MINISTRY = "ministry"
    UNIVERSITY = "university"
    CAMPUS = "campus"
    FACULTY = "faculty"
    DEPARTMENT = "department"
    EDUCATION_LEVEL = "education_level"
    DIRECTION = "direction"
    PROGRAM = "program"
    ADMISSION_ROUTE = "admission_route"
    COMPETITION_TYPE = "competition_type"
    APPLICANT_CATEGORY = "applicant_category"
    OLYMPIAD = "olympiad"
    OLYMPIAD_PROFILE = "olympiad_profile"
    SUBJECT = "subject"
    UNKNOWN = "unknown"


class KnowledgeConflictScope(ContractModel):
    level: KnowledgeConflictScopeLevel
    scope_id: Annotated[str, StringConstraints(min_length=1, max_length=320)] | None = None

    @model_validator(mode="after")
    def scope_id_matches_level(self) -> KnowledgeConflictScope:
        if self.level in {KnowledgeConflictScopeLevel.FEDERAL, KnowledgeConflictScopeLevel.UNKNOWN}:
            if self.scope_id is not None:
                raise ValueError("federal and unknown conflict scopes cannot carry a scope ID")
            return self
        prefixes = {
            KnowledgeConflictScopeLevel.MINISTRY: "issuer:",
            KnowledgeConflictScopeLevel.UNIVERSITY: "university:",
            KnowledgeConflictScopeLevel.CAMPUS: "campus:",
            KnowledgeConflictScopeLevel.FACULTY: "faculty:",
            KnowledgeConflictScopeLevel.DEPARTMENT: "department:",
            KnowledgeConflictScopeLevel.DIRECTION: "direction:",
            KnowledgeConflictScopeLevel.PROGRAM: "program:",
            KnowledgeConflictScopeLevel.OLYMPIAD: "olympiad:",
            KnowledgeConflictScopeLevel.OLYMPIAD_PROFILE: "olympiad-profile:",
            KnowledgeConflictScopeLevel.SUBJECT: "subject:",
        }
        if self.scope_id is None or ":" not in self.scope_id or any(
            char.isspace() for char in self.scope_id
        ):
            raise ValueError("known non-federal conflict scopes require a canonical ID")
        prefix = prefixes.get(self.level)
        if prefix is not None and not self.scope_id.startswith(prefix):
            raise ValueError("conflict scope ID namespace does not match its dimension")
        return self


class ConflictValidInterval(ContractModel):
    """Known overlap interval; two open bounds mean the whole valid-time axis."""

    start: datetime | None = None
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def normalize_bound(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("conflict valid-time bounds must be timezone-aware")
            return value.astimezone(UTC)
        return None

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> ConflictValidInterval:
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("conflict valid-time interval must have start < end")
        return self


class ConflictParticipantKind(StrEnum):
    CLAIM_REVISION = "claim_revision"
    CHANGE_EVENT_REVISION = "change_event_revision"
    POLICY_RULE_REVISION = "policy_rule_revision"


class ConflictParticipantRole(StrEnum):
    COMPETING = "competing"
    PRIOR = "prior"
    SUCCESSOR = "successor"


class ConflictParticipantReference(ContractModel):
    kind: ConflictParticipantKind
    object_id: Annotated[str, StringConstraints(min_length=1, max_length=140)]
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    content_hash: SourceHash | None = None

    @model_validator(mode="after")
    def exact_namespaced_reference(self) -> ConflictParticipantReference:
        patterns = {
            ConflictParticipantKind.CLAIM_REVISION: r"^claim:[a-f0-9]{64}$",
            ConflictParticipantKind.CHANGE_EVENT_REVISION: r"^change-event:[a-f0-9]{64}$",
            ConflictParticipantKind.POLICY_RULE_REVISION: r"^policy-rule:[a-z0-9][a-z0-9-]{0,127}$",
        }
        import re

        if re.fullmatch(patterns[self.kind], self.object_id) is None:
            raise ValueError("conflict participant ID does not match its typed kind")
        if self.kind in {
            ConflictParticipantKind.CLAIM_REVISION,
            ConflictParticipantKind.POLICY_RULE_REVISION,
        } and self.content_hash is None:
            raise ValueError("claim and policy conflict participants require an exact content hash")
        if self.kind is ConflictParticipantKind.CHANGE_EVENT_REVISION and self.content_hash is not None:
            raise ValueError("change-event participant references use exact ID and revision")
        return self


class KnowledgeConflictParticipant(ContractModel):
    reference: ConflictParticipantReference
    role: ConflictParticipantRole
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def evidence_refs_are_unique(self) -> KnowledgeConflictParticipant:
        keys = tuple(_evidence_key(item) for item in self.evidence)
        if len(keys) != len(set(keys)):
            raise ValueError("conflict participant evidence references must be unique")
        return self


class KnowledgeConflictGroupRevisionFields(ContractModel):
    conflict_id: KnowledgeConflictGroupId
    revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    kind: KnowledgeConflictKind
    scope: KnowledgeConflictScope | None = None
    valid_interval: ConflictValidInterval
    participants: tuple[KnowledgeConflictParticipant, ...] = Field(min_length=2, max_length=128)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("conflict recorded_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def participant_set_is_canonical_and_typed(self) -> KnowledgeConflictGroupRevisionFields:
        identities = tuple(_participant_reference_key(item.reference) for item in self.participants)
        if len(identities) != len(set(identities)):
            raise ValueError("conflict participant references must be unique")
        if self.conflict_id != knowledge_conflict_group_id(
            self.kind,
            self.scope,
            self.valid_interval,
            self.participants,
        ):
            raise ValueError("conflict group ID does not match its typed identity")
        if self.kind is KnowledgeConflictKind.CONTRADICTORY_CLAIMS and any(
            item.reference.kind is not ConflictParticipantKind.CLAIM_REVISION
            for item in self.participants
        ):
            raise ValueError("contradictory-claim groups may contain only exact claim revisions")
        if self.kind is KnowledgeConflictKind.POLICY_PRECEDENCE and any(
            item.reference.kind is not ConflictParticipantKind.POLICY_RULE_REVISION
            for item in self.participants
        ):
            raise ValueError("policy-precedence groups may contain only exact policy revisions")
        return self


class KnowledgeConflictGroupRevision(KnowledgeConflictGroupRevisionFields):
    content_hash: SourceHash

    @model_validator(mode="after")
    def hash_matches_group_revision(self) -> KnowledgeConflictGroupRevision:
        if self.content_hash != knowledge_conflict_content_hash(self):
            raise ValueError("conflict group content hash does not match its immutable revision")
        return self


class KnowledgeConflictState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class KnowledgeConflictEventKind(StrEnum):
    OPENED = "opened"
    RESOLVED_BY_SUPERSESSION = "resolved_by_supersession"
    RESOLVED_BY_HUMAN_REVIEW = "resolved_by_human_review"
    DISMISSED = "dismissed"
    REOPENED = "reopened"


class KnowledgeConflictEventFields(ContractModel):
    event_id: KnowledgeConflictEventId
    conflict_id: KnowledgeConflictGroupId
    group_revision: int = Field(strict=True, ge=1, le=2_147_483_647)
    group_hash: SourceHash
    sequence: int = Field(strict=True, ge=1, le=2_147_483_647)
    kind: KnowledgeConflictEventKind
    actor_account_id: AccountId | None = None
    reason: NonEmptyText
    resolution_participant: ConflictParticipantReference | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("conflict event time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def event_shape_matches_kind(self) -> KnowledgeConflictEventFields:
        if self.kind is KnowledgeConflictEventKind.OPENED:
            if self.sequence != 1 or self.actor_account_id is not None or self.resolution_participant:
                raise ValueError("opening conflict event is system-created and has no resolution target")
        elif self.kind is KnowledgeConflictEventKind.RESOLVED_BY_SUPERSESSION:
            if (
                self.actor_account_id is not None
                or self.resolution_participant is None
                or self.resolution_participant.kind is not ConflictParticipantKind.POLICY_RULE_REVISION
            ):
                raise ValueError("supersession resolution must reference an exact policy participant")
        elif self.kind is KnowledgeConflictEventKind.RESOLVED_BY_HUMAN_REVIEW:
            if self.actor_account_id is None or self.resolution_participant is None:
                raise ValueError("human conflict resolution requires reviewer and exact resolution participant")
        elif self.kind in {
            KnowledgeConflictEventKind.DISMISSED,
            KnowledgeConflictEventKind.REOPENED,
        } and (self.actor_account_id is None or self.resolution_participant is not None):
            raise ValueError("dismissal or reopening requires a reviewer and no resolution participant")
        if self.event_id != knowledge_conflict_event_id(self):
            raise ValueError("conflict event ID does not match its immutable identity")
        return self


class KnowledgeConflictEvent(KnowledgeConflictEventFields):
    pass


class KnowledgeConflictAggregate(ContractModel):
    revision: KnowledgeConflictGroupRevision
    state: KnowledgeConflictState
    events: tuple[KnowledgeConflictEvent, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def event_history_matches_exact_revision(self) -> KnowledgeConflictAggregate:
        expected_state = derive_knowledge_conflict_state(
            self.events,
            conflict_id=self.revision.conflict_id,
            group_revision=self.revision.revision,
            group_hash=self.revision.content_hash,
            recorded_at=self.revision.recorded_at,
        )
        if self.state is not expected_state:
            raise ValueError("conflict aggregate state must be derived from its exact immutable event history")
        allowed_targets = {
            _participant_reference_key(item.reference) for item in self.revision.participants
        }
        if any(
            event.resolution_participant is not None
            and _participant_reference_key(event.resolution_participant) not in allowed_targets
            for event in self.events
        ):
            raise ValueError("conflict resolution must reference an exact participant in the group")
        return self


def knowledge_conflict_group_id(
    kind: KnowledgeConflictKind,
    scope: KnowledgeConflictScope | None,
    valid_interval: ConflictValidInterval,
    participants: tuple[KnowledgeConflictParticipant, ...],
) -> KnowledgeConflictGroupId:
    payload = {
        "kind": kind.value,
        "participants": sorted(_participant_key(item) for item in participants),
        "scope": scope.model_dump(mode="json") if scope is not None else None,
        "valid_interval": valid_interval.model_dump(mode="json"),
    }
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return f"knowledge-conflict:{digest}"


def knowledge_conflict_content_hash(
    revision: KnowledgeConflictGroupRevision | KnowledgeConflictGroupRevisionFields,
) -> SourceHash:
    payload = revision.model_dump(mode="json", exclude={"content_hash"})
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def knowledge_conflict_event_id(
    event: KnowledgeConflictEvent | KnowledgeConflictEventFields,
) -> KnowledgeConflictEventId:
    payload = event.model_dump(mode="json", exclude={"event_id"})
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return f"knowledge-conflict-event:{digest}"


def create_knowledge_conflict_event(
    *,
    conflict_id: KnowledgeConflictGroupId,
    group_revision: int,
    group_hash: SourceHash,
    sequence: int,
    kind: KnowledgeConflictEventKind,
    actor_account_id: AccountId | None,
    reason: str,
    resolution_participant: ConflictParticipantReference | None,
    recorded_at: datetime,
) -> KnowledgeConflictEvent:
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("conflict event time must be timezone-aware")
    fields = KnowledgeConflictEventFields.model_construct(
        event_id="knowledge-conflict-event:" + ("0" * 64),
        conflict_id=conflict_id,
        group_revision=group_revision,
        group_hash=group_hash,
        sequence=sequence,
        kind=kind,
        actor_account_id=actor_account_id,
        reason=reason,
        resolution_participant=resolution_participant,
        recorded_at=recorded_at,
    )
    event_id = knowledge_conflict_event_id(fields)
    return KnowledgeConflictEvent(
        event_id=event_id,
        conflict_id=conflict_id,
        group_revision=group_revision,
        group_hash=group_hash,
        sequence=sequence,
        kind=kind,
        actor_account_id=actor_account_id,
        reason=reason,
        resolution_participant=resolution_participant,
        recorded_at=recorded_at,
    )


def derive_knowledge_conflict_state(
    events: tuple[KnowledgeConflictEvent, ...],
    *,
    conflict_id: KnowledgeConflictGroupId,
    group_revision: int,
    group_hash: SourceHash,
    recorded_at: datetime,
) -> KnowledgeConflictState:
    if not events or len(events) > 128:
        raise ValueError("conflict event history must contain between 1 and 128 records")
    ordered = tuple(sorted(events, key=lambda item: item.sequence))
    if tuple(item.sequence for item in ordered) != tuple(range(1, len(ordered) + 1)):
        raise ValueError("conflict event history sequence must be consecutive")
    if any(
        item.conflict_id != conflict_id
        or item.group_revision != group_revision
        or item.group_hash != group_hash
        or item.recorded_at < recorded_at
        for item in ordered
    ):
        raise ValueError("conflict event must bind to the exact immutable group revision")
    state = KnowledgeConflictState.OPEN
    previous_time = recorded_at
    for event in ordered:
        if event.recorded_at < previous_time:
            raise ValueError("conflict event times must be monotonic")
        previous_time = event.recorded_at
        if event.sequence == 1:
            if event.kind is not KnowledgeConflictEventKind.OPENED:
                raise ValueError("conflict history must begin with OPENED")
            continue
        if state is KnowledgeConflictState.OPEN:
            if event.kind in {
                KnowledgeConflictEventKind.RESOLVED_BY_SUPERSESSION,
                KnowledgeConflictEventKind.RESOLVED_BY_HUMAN_REVIEW,
            }:
                state = KnowledgeConflictState.RESOLVED
            elif event.kind is KnowledgeConflictEventKind.DISMISSED:
                state = KnowledgeConflictState.DISMISSED
            else:
                raise ValueError("open conflict can only be resolved or dismissed")
        elif event.kind is KnowledgeConflictEventKind.REOPENED:
            state = KnowledgeConflictState.OPEN
        else:
            raise ValueError("resolved conflict must be explicitly reopened before another decision")
    return state


def _participant_key(
    participant: KnowledgeConflictParticipant,
) -> tuple[str, str, int, str, str]:
    reference = participant.reference
    return (
        reference.kind.value,
        reference.object_id,
        reference.revision,
        reference.content_hash or "",
        participant.role.value,
    )


def _participant_reference_key(
    reference: ConflictParticipantReference,
) -> tuple[str, str, int, str]:
    return (
        reference.kind.value,
        reference.object_id,
        reference.revision,
        reference.content_hash or "",
    )


def _evidence_key(evidence: EvidenceRef) -> tuple[str, str, str, str]:
    return (
        evidence.source_observation_id,
        str(evidence.source_url),
        evidence.locator.model_dump_json(),
        evidence.snapshot_sha256,
    )


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "ConflictParticipantKind",
    "ConflictParticipantReference",
    "ConflictParticipantRole",
    "ConflictValidInterval",
    "KnowledgeConflictAggregate",
    "KnowledgeConflictEvent",
    "KnowledgeConflictEventFields",
    "KnowledgeConflictEventId",
    "KnowledgeConflictEventKind",
    "KnowledgeConflictGroupId",
    "KnowledgeConflictGroupRevision",
    "KnowledgeConflictGroupRevisionFields",
    "KnowledgeConflictKind",
    "KnowledgeConflictParticipant",
    "KnowledgeConflictScope",
    "KnowledgeConflictScopeLevel",
    "KnowledgeConflictState",
    "create_knowledge_conflict_event",
    "derive_knowledge_conflict_state",
    "knowledge_conflict_content_hash",
    "knowledge_conflict_event_id",
    "knowledge_conflict_group_id",
]
