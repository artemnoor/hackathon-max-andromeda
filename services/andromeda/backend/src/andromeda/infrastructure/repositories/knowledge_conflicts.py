"""Append-only conflict evidence and resolution audit persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    KnowledgeChangeEventModel,
    KnowledgeClaimModel,
    KnowledgeConflictEventModel,
    KnowledgeConflictEvidenceModel,
    KnowledgeConflictGroupModel,
    KnowledgeConflictParticipantModel,
    KnowledgeSourceObservationModel,
    PolicyRuleRelationModel,
    PolicyRuleRevisionModel,
)
from andromeda.infrastructure.repositories.knowledge_evidence import (
    validate_knowledge_evidence,
)
from andromeda.infrastructure.repositories.policy import SqlAlchemyPolicyRuleRepository
from andromeda.modules.knowledge.contracts.public import (
    ConflictParticipantKind,
    ConflictParticipantReference,
    ConflictParticipantRole,
    EvidenceRef,
    KnowledgeConflictAggregate,
    KnowledgeConflictEvent,
    KnowledgeConflictEventKind,
    KnowledgeConflictGroupRevision,
    KnowledgeConflictParticipant,
    create_knowledge_conflict_event,
    derive_knowledge_conflict_state,
)
from andromeda.modules.knowledge.repository.ports import ConflictGroupRepository
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
logger = logging.getLogger("andromeda.infrastructure.repositories.knowledge_conflicts")


class SqlAlchemyConflictGroupRepository(ConflictGroupRepository):
    """Immutable conflict revisions with append-only, exact-hash decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_conflict_group(
        self,
        group: KnowledgeConflictGroupRevision,
    ) -> KnowledgeConflictGroupRevision:
        existing = self.get_conflict_group(group.conflict_id, group.revision)
        if existing is not None:
            if existing.revision != group:
                raise ConflictError("Conflict group revisions are immutable")
            return group
        latest = self._session.scalar(
            select(KnowledgeConflictGroupModel)
            .where(KnowledgeConflictGroupModel.conflict_id == group.conflict_id)
            .order_by(KnowledgeConflictGroupModel.revision.desc())
            .limit(1)
        )
        expected_revision = latest.revision + 1 if latest is not None else 1
        if group.revision != expected_revision:
            raise ConflictError(
                "Conflict group revisions must be appended consecutively"
            )
        if latest is not None and _aware(latest.recorded_at) >= group.recorded_at:
            raise ValidationError(
                "Conflict group knowledge time must increase by revision"
            )
        self._validate_participants(group)
        all_evidence = tuple(
            evidence
            for participant in group.participants
            for evidence in participant.evidence
        )
        validate_knowledge_evidence(
            self._session,
            all_evidence,
            recorded_at=group.recorded_at,
        )

        interval = group.valid_interval
        scope = group.scope
        row = KnowledgeConflictGroupModel(
            conflict_id=group.conflict_id,
            revision=group.revision,
            content_hash=group.content_hash,
            conflict_kind=group.kind.value,
            scope_level=scope.level.value if scope else None,
            scope_id=scope.scope_id if scope else None,
            valid_start=interval.start,
            valid_end=interval.end,
            recorded_at=group.recorded_at,
        )
        self._session.add(row)
        self._session.flush()

        participant_rows: list[KnowledgeConflictParticipantModel] = []
        evidence_rows: list[KnowledgeConflictEvidenceModel] = []
        for participant_ordinal, participant in enumerate(group.participants):
            participant_row = self._participant_model(
                group, participant_ordinal, participant
            )
            participant_rows.append(participant_row)
            for evidence_ordinal, evidence in enumerate(participant.evidence):
                locator = evidence.locator
                evidence_rows.append(
                    KnowledgeConflictEvidenceModel(
                        conflict_id=group.conflict_id,
                        group_revision=group.revision,
                        participant_ordinal=participant_ordinal,
                        ordinal=evidence_ordinal,
                        source_observation_id=evidence.source_observation_id,
                        snapshot_sha256=evidence.snapshot_sha256,
                        source_url=str(evidence.source_url),
                        locator_page=locator.page,
                        locator_table=locator.table,
                        locator_row=locator.row,
                        locator_section=locator.section,
                        locator_field=locator.field,
                        locator_record_key=locator.record_key,
                        inferred=evidence.inferred,
                    )
                )
        self._session.add_all(participant_rows)
        self._session.flush()
        self._session.add_all(evidence_rows)
        opened = create_knowledge_conflict_event(
            conflict_id=group.conflict_id,
            group_revision=group.revision,
            group_hash=group.content_hash,
            sequence=1,
            kind=KnowledgeConflictEventKind.OPENED,
            actor_account_id=None,
            reason="Typed source-backed participants require conflict review.",
            resolution_participant=None,
            recorded_at=group.recorded_at,
        )
        self._session.add(self._event_model(opened, resolution_ordinal=None))
        self._session.flush()
        logger.info(
            "knowledge_conflict_group_appended conflict_id=%s revision=%d hash_prefix=%s",
            group.conflict_id,
            group.revision,
            group.content_hash[:12],
        )
        return group

    def get_conflict_group(
        self,
        conflict_id: str,
        revision: int,
    ) -> KnowledgeConflictAggregate | None:
        row = self._session.get(KnowledgeConflictGroupModel, (conflict_id, revision))
        if row is None:
            return None
        group = self._to_group(row)
        events = self.list_conflict_events(conflict_id, revision)
        state = derive_knowledge_conflict_state(
            events,
            conflict_id=group.conflict_id,
            group_revision=group.revision,
            group_hash=group.content_hash,
            recorded_at=group.recorded_at,
        )
        return KnowledgeConflictAggregate(revision=group, state=state, events=events)

    def list_for_participant(
        self,
        participant: ConflictParticipantReference,
        *,
        limit: int = 100,
    ) -> tuple[KnowledgeConflictAggregate, ...]:
        if not 1 <= limit <= 100:
            raise ValidationError(
                "Conflict participant query limit must be between 1 and 100"
            )
        statement = select(KnowledgeConflictParticipantModel).where(
            KnowledgeConflictParticipantModel.participant_kind == participant.kind.value
        )
        if participant.kind is ConflictParticipantKind.CLAIM_REVISION:
            statement = statement.where(
                KnowledgeConflictParticipantModel.claim_id == participant.object_id,
                KnowledgeConflictParticipantModel.claim_revision
                == participant.revision,
                KnowledgeConflictParticipantModel.claim_hash
                == participant.content_hash,
            )
        elif participant.kind is ConflictParticipantKind.CHANGE_EVENT_REVISION:
            statement = statement.where(
                KnowledgeConflictParticipantModel.change_event_id
                == participant.object_id,
                KnowledgeConflictParticipantModel.change_event_revision
                == participant.revision,
            )
        else:
            statement = statement.where(
                KnowledgeConflictParticipantModel.policy_rule_id
                == participant.object_id,
                KnowledgeConflictParticipantModel.policy_revision
                == participant.revision,
                KnowledgeConflictParticipantModel.policy_hash
                == participant.content_hash,
            )
        rows = self._session.scalars(
            statement.order_by(
                KnowledgeConflictParticipantModel.conflict_id,
                KnowledgeConflictParticipantModel.group_revision.desc(),
            ).limit(limit + 1)
        ).all()
        results = tuple(
            self.get_conflict_group(row.conflict_id, row.group_revision) for row in rows
        )
        if any(item is None for item in results):
            raise ConflictError(
                "Conflict participant references a missing exact group revision"
            )
        return tuple(item for item in results if item is not None)

    def list_conflict_events(
        self,
        conflict_id: str,
        revision: int,
    ) -> tuple[KnowledgeConflictEvent, ...]:
        rows = self._session.scalars(
            select(KnowledgeConflictEventModel)
            .where(
                KnowledgeConflictEventModel.conflict_id == conflict_id,
                KnowledgeConflictEventModel.group_revision == revision,
            )
            .order_by(KnowledgeConflictEventModel.sequence)
            .limit(129)
        ).all()
        if len(rows) > 128:
            raise ValidationError(
                "Conflict resolution audit exceeds its bounded 128-event limit"
            )
        return tuple(self._to_event(row) for row in rows)

    def append_conflict_event(
        self, event: KnowledgeConflictEvent
    ) -> KnowledgeConflictEvent:
        existing = self._session.get(KnowledgeConflictEventModel, event.event_id)
        if existing is not None:
            stored = self._to_event(existing)
            if stored != event:
                raise ConflictError(
                    "Conflict event identity has conflicting immutable metadata"
                )
            return stored
        aggregate = self.get_conflict_group(event.conflict_id, event.group_revision)
        if aggregate is None:
            raise NotFoundError("Conflict group revision does not exist")
        if aggregate.revision.content_hash != event.group_hash:
            raise ConflictError(
                "Conflict event is bound to a stale group revision hash"
            )
        history = aggregate.events
        if event.sequence != len(history) + 1:
            raise ConflictError(
                "Conflict event sequence must be appended consecutively"
            )
        try:
            state = derive_knowledge_conflict_state(
                (*history, event),
                conflict_id=aggregate.revision.conflict_id,
                group_revision=aggregate.revision.revision,
                group_hash=aggregate.revision.content_hash,
                recorded_at=aggregate.revision.recorded_at,
            )
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc

        resolution_ordinal = None
        if event.resolution_participant is not None:
            resolution_ordinal = self._participant_ordinal(
                aggregate.revision, event.resolution_participant
            )
        if event.kind is KnowledgeConflictEventKind.RESOLVED_BY_SUPERSESSION:
            self._validate_supersession_resolution(
                aggregate.revision,
                event.resolution_participant,
                as_known_at=event.recorded_at,
            )
        row = self._event_model(event, resolution_ordinal=resolution_ordinal)
        self._session.add(row)
        self._session.flush()
        logger.info(
            "knowledge_conflict_event_appended conflict_id=%s revision=%d sequence=%d kind=%s state=%s",
            event.conflict_id,
            event.group_revision,
            event.sequence,
            event.kind.value,
            state.value,
        )
        return event

    def _validate_participants(self, group: KnowledgeConflictGroupRevision) -> None:
        intervals: list[tuple[datetime | None, datetime | None]] = []
        for participant in group.participants:
            reference = participant.reference
            if reference.kind is ConflictParticipantKind.CLAIM_REVISION:
                claim_row = self._session.get(
                    KnowledgeClaimModel, (reference.object_id, reference.revision)
                )
                if claim_row is None:
                    raise NotFoundError("Conflict references an unknown claim revision")
                if claim_row.assertion_text_sha256 != reference.content_hash:
                    raise ConflictError(
                        "Conflict claim reference has a stale content hash"
                    )
                if _aware(claim_row.recorded_at) > group.recorded_at:
                    raise ValidationError("Conflict cannot predate a participant claim")
                intervals.append(
                    (
                        _aware(claim_row.valid_start)
                        if claim_row.valid_start
                        else None,
                        _aware(claim_row.valid_end) if claim_row.valid_end else None,
                    )
                )
            elif reference.kind is ConflictParticipantKind.CHANGE_EVENT_REVISION:
                event_row = self._session.get(
                    KnowledgeChangeEventModel,
                    (reference.object_id, reference.revision),
                )
                if event_row is None:
                    raise NotFoundError(
                        "Conflict references an unknown change-event revision"
                    )
                if _aware(event_row.recorded_at) > group.recorded_at:
                    raise ValidationError(
                        "Conflict cannot predate a participant change event"
                    )
                intervals.append(
                    (
                        _aware(event_row.valid_start)
                        if event_row.valid_start
                        else None,
                        _aware(event_row.valid_end) if event_row.valid_end else None,
                    )
                )
            else:
                policy_row = self._session.get(
                    PolicyRuleRevisionModel,
                    (reference.object_id, reference.revision),
                )
                if policy_row is None:
                    raise NotFoundError(
                        "Conflict references an unknown policy revision"
                    )
                if policy_row.content_hash != reference.content_hash:
                    raise ConflictError(
                        "Conflict policy reference has a stale revision hash"
                    )
                if _aware(policy_row.recorded_at) > group.recorded_at:
                    raise ValidationError(
                        "Conflict cannot predate a participant policy revision"
                    )
                starts = tuple(
                    _aware(item)
                    for item in (policy_row.valid_start, policy_row.effective_start)
                    if item is not None
                )
                ends = tuple(
                    _aware(item)
                    for item in (policy_row.valid_end, policy_row.effective_end)
                    if item is not None
                )
                intervals.append(
                    (max(starts) if starts else None, min(ends) if ends else None)
                )
        _validate_interval_intersection(group, tuple(intervals))

    @staticmethod
    def _participant_model(
        group: KnowledgeConflictGroupRevision,
        ordinal: int,
        participant: KnowledgeConflictParticipant,
    ) -> KnowledgeConflictParticipantModel:
        reference = participant.reference
        values: dict[str, object | None] = {
            "claim_id": None,
            "claim_revision": None,
            "claim_hash": None,
            "change_event_id": None,
            "change_event_revision": None,
            "policy_rule_id": None,
            "policy_revision": None,
            "policy_hash": None,
        }
        if reference.kind is ConflictParticipantKind.CLAIM_REVISION:
            values.update(
                claim_id=reference.object_id,
                claim_revision=reference.revision,
                claim_hash=reference.content_hash,
            )
        elif reference.kind is ConflictParticipantKind.CHANGE_EVENT_REVISION:
            values.update(
                change_event_id=reference.object_id,
                change_event_revision=reference.revision,
            )
        else:
            values.update(
                policy_rule_id=reference.object_id,
                policy_revision=reference.revision,
                policy_hash=reference.content_hash,
            )
        return KnowledgeConflictParticipantModel(
            conflict_id=group.conflict_id,
            group_revision=group.revision,
            ordinal=ordinal,
            participant_kind=reference.kind.value,
            role=participant.role.value,
            **values,
        )

    def _validate_supersession_resolution(
        self,
        group: KnowledgeConflictGroupRevision,
        resolution: ConflictParticipantReference | None,
        *,
        as_known_at: datetime,
    ) -> None:
        if resolution is None:
            raise ValidationError(
                "Supersession resolution requires an exact policy participant"
            )
        source_id, source_revision, source_hash = (
            resolution.object_id,
            resolution.revision,
            resolution.content_hash,
        )
        policy_refs = tuple(
            item.reference
            for item in group.participants
            if item.reference.kind is ConflictParticipantKind.POLICY_RULE_REVISION
        )
        if len(policy_refs) < 2 or resolution not in policy_refs:
            raise ValidationError(
                "Superseding rule must be one of the exact policy conflict participants"
            )
        approved_source = SqlAlchemyPolicyRuleRepository(
            self._session
        ).get_approved_revision(
            source_id,
            source_revision,
            as_known_at=as_known_at,
        )
        if approved_source is None or approved_source.content_hash != source_hash:
            raise ValidationError(
                "Conflict resolution requires an exact source revision approved by event time"
            )
        targets = tuple(item for item in policy_refs if item != resolution)
        for target in targets:
            edge = self._session.scalar(
                select(PolicyRuleRelationModel).where(
                    PolicyRuleRelationModel.rule_id == source_id,
                    PolicyRuleRelationModel.rule_revision == source_revision,
                    PolicyRuleRelationModel.target_rule_id == target.object_id,
                    PolicyRuleRelationModel.target_revision == target.revision,
                    PolicyRuleRelationModel.target_hash == target.content_hash,
                    PolicyRuleRelationModel.relation_kind.in_(
                        {"supersedes", "authorized_exception_to"}
                    ),
                )
            )
            if edge is not None:
                if (
                    self._session.scalar(
                        select(PolicyRuleRevisionModel).where(
                            PolicyRuleRevisionModel.rule_id == source_id,
                            PolicyRuleRevisionModel.revision == source_revision,
                            PolicyRuleRevisionModel.content_hash == source_hash,
                        )
                    )
                    is None
                ):
                    raise ConflictError(
                        "Conflict resolution source policy hash is stale"
                    )
                return
        raise ValidationError(
            "No exact approved supersession or authorized-exception edge resolves this group"
        )

    def _participant_ordinal(
        self,
        group: KnowledgeConflictGroupRevision,
        reference: ConflictParticipantReference,
    ) -> int:
        for ordinal, participant in enumerate(group.participants):
            if participant.reference == reference:
                return ordinal
        raise ValidationError(
            "Conflict event resolution reference must be an exact group participant"
        )

    @staticmethod
    def _event_model(
        event: KnowledgeConflictEvent,
        *,
        resolution_ordinal: int | None,
    ) -> KnowledgeConflictEventModel:
        return KnowledgeConflictEventModel(
            event_id=event.event_id,
            conflict_id=event.conflict_id,
            group_revision=event.group_revision,
            group_hash=event.group_hash,
            sequence=event.sequence,
            event_kind=event.kind.value,
            actor_account_id=event.actor_account_id,
            reason=event.reason,
            resolution_participant_ordinal=resolution_ordinal,
            recorded_at=event.recorded_at,
        )

    def _to_group(
        self, row: KnowledgeConflictGroupModel
    ) -> KnowledgeConflictGroupRevision:
        participants = self._session.scalars(
            select(KnowledgeConflictParticipantModel)
            .where(
                KnowledgeConflictParticipantModel.conflict_id == row.conflict_id,
                KnowledgeConflictParticipantModel.group_revision == row.revision,
            )
            .order_by(KnowledgeConflictParticipantModel.ordinal)
        ).all()
        if not 2 <= len(participants) <= 128:
            raise ConflictError("Persisted conflict group participant count is invalid")
        participant_contracts: list[KnowledgeConflictParticipant] = []
        for item in participants:
            evidence_rows = self._session.scalars(
                select(KnowledgeConflictEvidenceModel)
                .where(
                    KnowledgeConflictEvidenceModel.conflict_id == row.conflict_id,
                    KnowledgeConflictEvidenceModel.group_revision == row.revision,
                    KnowledgeConflictEvidenceModel.participant_ordinal == item.ordinal,
                )
                .order_by(KnowledgeConflictEvidenceModel.ordinal)
            ).all()
            if not evidence_rows or len(evidence_rows) > 128:
                raise ConflictError(
                    "Persisted conflict participant is missing bounded evidence"
                )
            kind = ConflictParticipantKind(item.participant_kind)
            if kind is ConflictParticipantKind.CLAIM_REVISION:
                assert item.claim_id is not None and item.claim_revision is not None
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=item.claim_id,
                    revision=item.claim_revision,
                    content_hash=item.claim_hash,
                )
            elif kind is ConflictParticipantKind.CHANGE_EVENT_REVISION:
                assert (
                    item.change_event_id is not None
                    and item.change_event_revision is not None
                )
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=item.change_event_id,
                    revision=item.change_event_revision,
                )
            else:
                assert (
                    item.policy_rule_id is not None and item.policy_revision is not None
                )
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=item.policy_rule_id,
                    revision=item.policy_revision,
                    content_hash=item.policy_hash,
                )
            participant_contracts.append(
                KnowledgeConflictParticipant(
                    reference=reference,
                    role=ConflictParticipantRole(item.role),
                    evidence=tuple(
                        self._to_evidence(evidence) for evidence in evidence_rows
                    ),
                )
            )
        from andromeda.modules.knowledge.contracts.public import (
            ConflictValidInterval,
            KnowledgeConflictGroupRevisionFields,
            KnowledgeConflictKind,
            KnowledgeConflictScope,
            KnowledgeConflictScopeLevel,
            knowledge_conflict_content_hash,
        )

        scope = (
            KnowledgeConflictScope(
                level=KnowledgeConflictScopeLevel(row.scope_level),
                scope_id=row.scope_id,
            )
            if row.scope_level is not None
            else None
        )
        fields = KnowledgeConflictGroupRevisionFields(
            conflict_id=row.conflict_id,
            revision=row.revision,
            kind=KnowledgeConflictKind(row.conflict_kind),
            scope=scope,
            valid_interval=ConflictValidInterval(
                start=_optional_aware(row.valid_start),
                end=_optional_aware(row.valid_end),
            ),
            participants=tuple(participant_contracts),
            recorded_at=_aware(row.recorded_at),
        )
        return KnowledgeConflictGroupRevision(
            **fields.model_dump(mode="python"),
            content_hash=knowledge_conflict_content_hash(fields),
        )

    def _to_event(self, row: KnowledgeConflictEventModel) -> KnowledgeConflictEvent:
        reference = None
        if row.resolution_participant_ordinal is not None:
            participant = self._session.get(
                KnowledgeConflictParticipantModel,
                (
                    row.conflict_id,
                    row.group_revision,
                    row.resolution_participant_ordinal,
                ),
            )
            if participant is None:
                raise ConflictError(
                    "Persisted conflict event references a missing participant"
                )
            kind = ConflictParticipantKind(participant.participant_kind)
            if kind is ConflictParticipantKind.CLAIM_REVISION:
                assert (
                    participant.claim_id is not None
                    and participant.claim_revision is not None
                )
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=participant.claim_id,
                    revision=participant.claim_revision,
                    content_hash=participant.claim_hash,
                )
            elif kind is ConflictParticipantKind.CHANGE_EVENT_REVISION:
                assert (
                    participant.change_event_id is not None
                    and participant.change_event_revision is not None
                )
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=participant.change_event_id,
                    revision=participant.change_event_revision,
                )
            else:
                assert (
                    participant.policy_rule_id is not None
                    and participant.policy_revision is not None
                )
                reference = ConflictParticipantReference(
                    kind=kind,
                    object_id=participant.policy_rule_id,
                    revision=participant.policy_revision,
                    content_hash=participant.policy_hash,
                )
        return KnowledgeConflictEvent(
            event_id=row.event_id,
            conflict_id=row.conflict_id,
            group_revision=row.group_revision,
            group_hash=row.group_hash,
            sequence=row.sequence,
            kind=KnowledgeConflictEventKind(row.event_kind),
            actor_account_id=row.actor_account_id,
            reason=row.reason,
            resolution_participant=reference,
            recorded_at=_aware(row.recorded_at),
        )

    def _to_evidence(self, row: KnowledgeConflictEvidenceModel) -> EvidenceRef:
        from andromeda.modules.knowledge.contracts.public import EvidenceLocator

        observation = self._session.get(
            KnowledgeSourceObservationModel,
            row.source_observation_id,
        )
        if observation is None:
            raise ConflictError("Conflict evidence source observation is missing")
        if observation.snapshot_sha256 != row.snapshot_sha256:
            raise ConflictError(
                "Conflict evidence snapshot hash does not match its observation"
            )
        return EvidenceRef(
            source_id=observation.source_id,
            source_observation_id=observation.source_observation_id,
            snapshot_sha256=observation.snapshot_sha256,
            source_url=_HTTP_URL_ADAPTER.validate_python(row.source_url),
            locator=EvidenceLocator(
                page=row.locator_page,
                table=row.locator_table,
                row=row.locator_row,
                section=row.locator_section,
                field=row.locator_field,
                record_key=row.locator_record_key,
            ),
            inferred=row.inferred,
        )


def _validate_interval_intersection(
    group: KnowledgeConflictGroupRevision,
    intervals: tuple[tuple[datetime | None, datetime | None], ...],
) -> None:
    if any(start is None and end is None for start, end in intervals):
        raise ValidationError(
            "Conflict participants need known valid-time bounds before grouping"
        )
    starts = tuple(start for start, _ in intervals if start is not None)
    ends = tuple(end for _, end in intervals if end is not None)
    intersection_start = max(starts) if starts else None
    intersection_end = min(ends) if ends else None
    if (
        intersection_start is not None
        and intersection_end is not None
        and intersection_start >= intersection_end
    ):
        raise ValidationError("Conflict participants do not overlap in valid time")
    claimed = group.valid_interval
    if (
        claimed.start is not None
        and intersection_start is not None
        and claimed.start < intersection_start
    ):
        raise ValidationError(
            "Conflict interval starts before participant valid-time overlap"
        )
    if (
        claimed.end is not None
        and intersection_end is not None
        and claimed.end > intersection_end
    ):
        raise ValidationError(
            "Conflict interval ends after participant valid-time overlap"
        )
    if claimed.start is None and intersection_start is not None:
        raise ValidationError("Conflict interval must preserve its known overlap start")
    if claimed.end is None and intersection_end is not None:
        raise ValidationError("Conflict interval must preserve its known overlap end")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_aware(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


__all__ = ["SqlAlchemyConflictGroupRepository"]
