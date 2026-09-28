"""Persistence adapter for immutable policy revisions and approval-event history."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal, TypeVar, cast

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    KnowledgeClaimModel,
    KnowledgeSourceObservationModel,
    PolicyApprovalEventModel,
    PolicyRuleRelationModel,
    PolicyRuleRevisionClaimModel,
    PolicyRuleRevisionEvidenceModel,
    PolicyRuleRevisionModel,
)
from andromeda.infrastructure.repositories.knowledge_evidence import (
    validate_knowledge_evidence,
)
from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ClaimRevisionRef,
    EvidenceLocator,
    EvidenceRef,
    SourceMilestones,
    TemporalInterval,
)
from andromeda.modules.policy.contracts.approval import (
    ApprovedPolicyRevision,
    PolicyApprovalCapability,
    PolicyApprovalEvent,
    PolicyApprovalEventKind,
    PolicyRuleSubmission,
)
from andromeda.modules.policy.contracts.rule import (
    DomainRuleRef,
    PolicyAuthorityLevel,
    PolicyDomainOwner,
    PolicyRevisionLifecycle,
    PolicyRuleId,
    PolicyRuleRelation,
    PolicyRuleRelationKind,
    PolicyRuleRevision,
    PolicyRuleRevisionFields,
    PolicyScope,
    PolicyScopeLevel,
)
from andromeda.modules.policy.contracts.rule_ast import (
    PolicyContextField,
    PolicySelectorAst,
    PolicySelectorNodeKind,
)
from andromeda.modules.policy.contracts.temporal import PolicyTemporalRevision
from andromeda.modules.policy.domain.approval import (
    create_pending_submission_event,
    derive_approval_state,
    validate_approval_append,
)
from andromeda.modules.policy.repository.ports import PolicyRuleRepository
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("andromeda.infrastructure.repositories.policy")
_T = TypeVar("_T")


class SqlAlchemyPolicyRuleRepository(PolicyRuleRepository):
    """Append-only repository; the caller owns commit/rollback and authorization."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def submit_revision(self, submission: PolicyRuleSubmission) -> PolicyApprovalEvent:
        revision = submission.revision
        existing = self.get_revision(revision.rule_id, revision.revision)
        if existing is not None:
            if existing != revision:
                raise ConflictError("Policy rule revisions are immutable")
            events = self.list_approval_events(revision.rule_id, revision.revision)
            if (
                not events
                or events[0].kind is not PolicyApprovalEventKind.PENDING_SUBMITTED
            ):
                raise ConflictError(
                    "Persisted policy revision has no initial pending event"
                )
            return events[0]

        latest = self._session.scalar(
            select(PolicyRuleRevisionModel)
            .where(PolicyRuleRevisionModel.rule_id == revision.rule_id)
            .order_by(PolicyRuleRevisionModel.revision.desc())
            .limit(1)
            .with_for_update()
        )
        expected_revision = latest.revision + 1 if latest is not None else 1
        if revision.revision != expected_revision:
            raise ConflictError("Policy rule revisions must be appended consecutively")
        if submission.submitted_at < revision.temporal.clock.recorded_at:
            raise ValidationError("pending event cannot predate its policy revision")
        self._validate_rule_sources(revision)

        self._session.add(self._revision_model(revision))
        self._session.flush()
        self._session.add_all(
            PolicyRuleRevisionClaimModel(
                rule_id=revision.rule_id,
                rule_revision=revision.revision,
                ordinal=ordinal,
                claim_id=reference.claim_id,
                claim_revision=reference.revision,
            )
            for ordinal, reference in enumerate(revision.source_claims)
        )
        self._session.add_all(
            self._evidence_model(revision, evidence, ordinal)
            for ordinal, evidence in enumerate(revision.evidence)
        )
        self._session.flush()
        self._session.add_all(self._relation_models(revision))
        pending = create_pending_submission_event(
            revision,
            actor_account_id=submission.submitted_by_account_id,
            reason=submission.reason,
            recorded_at=submission.submitted_at,
        )
        self._session.add(self._approval_model(pending))
        self._session.flush()
        logger.info(
            "policy_rule_revision_submitted rule_id=%s revision=%d hash_prefix=%s",
            revision.rule_id,
            revision.revision,
            revision.content_hash[:12],
        )
        return pending

    def get_revision(
        self, rule_id: PolicyRuleId, revision: int
    ) -> PolicyRuleRevision | None:
        row = self._session.get(PolicyRuleRevisionModel, (rule_id, revision))
        return self._to_revision(row) if row is not None else None

    def list_pending_revisions(
        self, *, limit: int = 100
    ) -> tuple[PolicyRuleRevision, ...]:
        if limit < 1 or limit > 500:
            raise ValidationError(
                "Pending policy query limit must be between 1 and 500"
            )
        latest_events = (
            select(
                PolicyApprovalEventModel.rule_id.label("rule_id"),
                PolicyApprovalEventModel.revision.label("revision"),
                func.max(PolicyApprovalEventModel.sequence).label("sequence"),
            )
            .group_by(
                PolicyApprovalEventModel.rule_id, PolicyApprovalEventModel.revision
            )
            .subquery()
        )
        rows = self._session.scalars(
            select(PolicyRuleRevisionModel)
            .join(
                latest_events,
                (PolicyRuleRevisionModel.rule_id == latest_events.c.rule_id)
                & (PolicyRuleRevisionModel.revision == latest_events.c.revision),
            )
            .join(
                PolicyApprovalEventModel,
                (PolicyApprovalEventModel.rule_id == latest_events.c.rule_id)
                & (PolicyApprovalEventModel.revision == latest_events.c.revision)
                & (PolicyApprovalEventModel.sequence == latest_events.c.sequence),
            )
            .where(
                PolicyApprovalEventModel.kind
                == PolicyApprovalEventKind.PENDING_SUBMITTED.value,
                PolicyApprovalEventModel.revision_hash
                == PolicyRuleRevisionModel.content_hash,
            )
            .order_by(
                PolicyRuleRevisionModel.recorded_at.desc(),
                PolicyRuleRevisionModel.rule_id,
            )
            .limit(limit)
        ).all()
        return self._to_revisions(tuple(rows))

    def get_approved_revision(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> PolicyRuleRevision | None:
        if as_known_at is not None:
            _utc(as_known_at)
        row = self._session.get(PolicyRuleRevisionModel, (rule_id, revision))
        persisted = self.get_revision(rule_id, revision)
        if persisted is None or row is None:
            return None
        if as_known_at is not None and _aware(row.recorded_at) > as_known_at:
            return None
        history = self.list_approval_events(rule_id, revision, as_known_at=as_known_at)
        if (
            derive_approval_state(
                history,
                rule_id=rule_id,
                revision=revision,
                revision_hash=persisted.content_hash,
            ).value
            != "approved"
        ):
            return None
        return persisted

    def list_approved_revision_records(
        self, *, as_known_at: datetime
    ) -> tuple[ApprovedPolicyRevision, ...]:
        normalized_as_known_at = _utc(as_known_at)
        rows = self._session.scalars(
            select(PolicyRuleRevisionModel)
            .where(PolicyRuleRevisionModel.recorded_at <= normalized_as_known_at)
            .order_by(PolicyRuleRevisionModel.rule_id, PolicyRuleRevisionModel.revision)
            .limit(501)
        ).all()
        if len(rows) > 500:
            raise ValidationError(
                "Policy approved-revision scan exceeds its 500-row bound"
            )
        if not rows:
            return ()

        revision_keys = tuple((row.rule_id, row.revision) for row in rows)
        approval_rows: list[PolicyApprovalEventModel] = []
        for key_chunk in _chunks(revision_keys, 400):
            chunk_rows = self._session.scalars(
                select(PolicyApprovalEventModel)
                .where(
                    tuple_(
                        PolicyApprovalEventModel.rule_id,
                        PolicyApprovalEventModel.revision,
                    ).in_(key_chunk),
                    PolicyApprovalEventModel.recorded_at <= normalized_as_known_at,
                )
                .order_by(
                    PolicyApprovalEventModel.rule_id,
                    PolicyApprovalEventModel.revision,
                    PolicyApprovalEventModel.sequence,
                )
                .limit(6401)
            ).all()
            if len(chunk_rows) > 6400 or len(approval_rows) + len(chunk_rows) > 8000:
                raise ValidationError(
                    "Policy approval scan exceeds its 8000-event bound"
                )
            approval_rows.extend(chunk_rows)
        histories: dict[tuple[str, int], list[PolicyApprovalEvent]] = {}
        for approval_event_row in approval_rows:
            key = (approval_event_row.rule_id, approval_event_row.revision)
            history = histories.setdefault(key, [])
            history.append(self._to_approval_event(approval_event_row))
            if len(history) > 16:
                raise ValidationError(
                    "Policy approval history exceeds its bounded 16-event limit"
                )

        approved_rows: list[PolicyRuleRevisionModel] = []
        approved_events: list[PolicyApprovalEvent] = []
        for approved_revision_row in rows:
            approval_history = tuple(
                histories.get(
                    (approved_revision_row.rule_id, approved_revision_row.revision),
                    (),
                )
            )
            state = derive_approval_state(
                approval_history,
                rule_id=approved_revision_row.rule_id,
                revision=approved_revision_row.revision,
                revision_hash=approved_revision_row.content_hash,
            )
            if state.value == "approved":
                approved_rows.append(approved_revision_row)
                approved_events.append(approval_history[-1])
        revisions = self._to_revisions(tuple(approved_rows))
        return tuple(
            ApprovedPolicyRevision(revision=revision, approval_event=approval_event)
            for revision, approval_event in zip(revisions, approved_events, strict=True)
        )

    def list_approved_revisions(
        self, *, as_known_at: datetime
    ) -> tuple[PolicyRuleRevision, ...]:
        """Compatibility projection for callers that do not need event provenance."""

        return tuple(
            record.revision
            for record in self.list_approved_revision_records(
                as_known_at=as_known_at
            )
        )

    def list_approval_events(
        self,
        rule_id: PolicyRuleId,
        revision: int,
        *,
        as_known_at: datetime | None = None,
    ) -> tuple[PolicyApprovalEvent, ...]:
        statement = select(PolicyApprovalEventModel).where(
            PolicyApprovalEventModel.rule_id == rule_id,
            PolicyApprovalEventModel.revision == revision,
        )
        if as_known_at is not None:
            statement = statement.where(
                PolicyApprovalEventModel.recorded_at <= _utc(as_known_at)
            )
        rows = self._session.scalars(
            statement.order_by(PolicyApprovalEventModel.sequence).limit(17)
        ).all()
        if len(rows) > 16:
            raise ValidationError(
                "Policy approval history exceeds its bounded 16-event limit"
            )
        return tuple(self._to_approval_event(row) for row in rows)

    def append_approval_event(self, event: PolicyApprovalEvent) -> PolicyApprovalEvent:
        existing = self._session.get(PolicyApprovalEventModel, event.event_id)
        if existing is not None:
            stored = self._to_approval_event(existing)
            if stored != event:
                raise ConflictError(
                    "Policy approval event ID has conflicting immutable metadata"
                )
            return stored

        revision_row = self._session.scalar(
            select(PolicyRuleRevisionModel)
            .where(
                PolicyRuleRevisionModel.rule_id == event.rule_id,
                PolicyRuleRevisionModel.revision == event.revision,
            )
            .with_for_update()
        )
        if revision_row is None:
            raise NotFoundError("Policy rule revision does not exist")
        if revision_row.content_hash != event.revision_hash:
            raise ConflictError(
                "Policy approval event is bound to a stale revision hash"
            )
        if event.recorded_at < _aware(revision_row.recorded_at):
            raise ValidationError(
                "Policy approval cannot predate the source-backed revision"
            )
        history = self.list_approval_events(event.rule_id, event.revision)
        try:
            validate_approval_append(
                history, event, revision_hash=revision_row.content_hash
            )
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        self._session.add(self._approval_model(event))
        self._session.flush()
        logger.info(
            "policy_approval_event_appended rule_id=%s revision=%d sequence=%d kind=%s",
            event.rule_id,
            event.revision,
            event.sequence,
            event.kind.value,
        )
        return event

    def _validate_rule_sources(self, revision: PolicyRuleRevision) -> None:
        recorded_at = revision.temporal.clock.recorded_at
        validate_knowledge_evidence(
            self._session,
            revision.evidence,
            recorded_at=recorded_at,
        )
        included_observation_ids = {
            item.source_observation_id for item in revision.evidence
        }
        for reference in revision.source_claims:
            row = self._session.get(
                KnowledgeClaimModel, (reference.claim_id, reference.revision)
            )
            if row is None:
                raise NotFoundError(
                    "Policy rule references an unknown source claim revision"
                )
            if row.review_state != "accepted_as_source_assertion":
                raise ValidationError(
                    "Policy rule source claims must be accepted source assertions"
                )
            if _aware(row.recorded_at) > recorded_at:
                raise ValidationError(
                    "Policy rule revision cannot predate its source claim"
                )
            if row.source_observation_id not in included_observation_ids:
                raise ValidationError(
                    "Policy evidence must cite each source claim observation"
                )
        for evidence in revision.evidence:
            observation = self._session.get(
                KnowledgeSourceObservationModel, evidence.source_observation_id
            )
            if observation is None:
                raise NotFoundError("Policy evidence source observation does not exist")

    def _revision_model(self, revision: PolicyRuleRevision) -> PolicyRuleRevisionModel:
        valid_start, valid_end = _interval_columns(revision.temporal.clock.valid_time)
        effective_start, effective_end = _interval_columns(
            revision.temporal.source_milestones.effective_time
        )
        return PolicyRuleRevisionModel(
            rule_id=revision.rule_id,
            revision=revision.revision,
            content_hash=revision.content_hash,
            schema_version=revision.schema_version,
            family_id=revision.family_id,
            authority_level=revision.authority.value if revision.authority else None,
            selector_json=revision.selector.model_dump(mode="json"),
            scope_level=revision.scope.level.value,
            scope_id=revision.scope.scope_id,
            owner_module=revision.domain_rule.owner_module.value,
            owner_rule_id=revision.domain_rule.canonical_rule_id,
            owner_revision=revision.domain_rule.owner_revision,
            owner_revision_hash=revision.domain_rule.owner_revision_hash,
            lifecycle=revision.lifecycle.value,
            valid_start=valid_start,
            valid_end=valid_end,
            published_at=_optional_utc(
                revision.temporal.source_milestones.published_at
            ),
            announced_at=_optional_utc(
                revision.temporal.source_milestones.announced_at
            ),
            adopted_at=_optional_utc(revision.temporal.source_milestones.adopted_at),
            effective_start=effective_start,
            effective_end=effective_end,
            captured_at=_utc(revision.temporal.source_milestones.captured_at),
            recorded_at=_utc(revision.temporal.clock.recorded_at),
        )

    @staticmethod
    def _evidence_model(
        revision: PolicyRuleRevision, evidence: EvidenceRef, ordinal: int
    ) -> PolicyRuleRevisionEvidenceModel:
        locator = evidence.locator
        return PolicyRuleRevisionEvidenceModel(
            rule_id=revision.rule_id,
            rule_revision=revision.revision,
            ordinal=ordinal,
            source_observation_id=evidence.source_observation_id,
            source_url=str(evidence.source_url),
            locator_page=locator.page,
            locator_table=locator.table,
            locator_row=locator.row,
            locator_section=locator.section,
            locator_field=locator.field,
            locator_record_key=locator.record_key,
            inferred=evidence.inferred,
        )

    @staticmethod
    def _relation_models(
        revision: PolicyRuleRevision,
    ) -> tuple[PolicyRuleRelationModel, ...]:
        claim_ordinals = {
            (item.claim_id, item.revision): ordinal
            for ordinal, item in enumerate(revision.source_claims)
        }
        evidence_ordinals = {
            _evidence_key(item): ordinal
            for ordinal, item in enumerate(revision.evidence)
        }
        return tuple(
            PolicyRuleRelationModel(
                rule_id=revision.rule_id,
                rule_revision=revision.revision,
                ordinal=ordinal,
                relation_kind=relation.kind.value,
                target_rule_id=relation.target_rule_id,
                target_revision=relation.target_revision,
                target_hash=relation.target_hash,
                claim_ordinal=claim_ordinals[
                    (relation.source_claim.claim_id, relation.source_claim.revision)
                ],
                evidence_ordinal=evidence_ordinals[_evidence_key(relation.evidence)],
            )
            for ordinal, relation in enumerate(revision.relations)
        )

    @staticmethod
    def _approval_model(event: PolicyApprovalEvent) -> PolicyApprovalEventModel:
        return PolicyApprovalEventModel(
            event_id=event.event_id,
            rule_id=event.rule_id,
            revision=event.revision,
            sequence=event.sequence,
            revision_hash=event.revision_hash,
            kind=event.kind.value,
            actor_account_id=event.actor_account_id,
            capability=event.capability.value,
            reason=event.reason,
            recorded_at=_utc(event.recorded_at),
            preview_fingerprint=event.preview_fingerprint,
        )

    def _to_revisions(
        self, rows: tuple[PolicyRuleRevisionModel, ...]
    ) -> tuple[PolicyRuleRevision, ...]:
        if not rows:
            return ()
        keys = tuple((row.rule_id, row.revision) for row in rows)
        claim_rows: list[PolicyRuleRevisionClaimModel] = []
        evidence_rows: list[PolicyRuleRevisionEvidenceModel] = []
        for key_chunk in _chunks(keys, 400):
            claim_rows.extend(
                self._session.scalars(
                    select(PolicyRuleRevisionClaimModel)
                    .where(
                        tuple_(
                            PolicyRuleRevisionClaimModel.rule_id,
                            PolicyRuleRevisionClaimModel.rule_revision,
                        ).in_(key_chunk)
                    )
                    .order_by(
                        PolicyRuleRevisionClaimModel.rule_id,
                        PolicyRuleRevisionClaimModel.rule_revision,
                        PolicyRuleRevisionClaimModel.ordinal,
                    )
                ).all()
            )
            evidence_rows.extend(
                self._session.scalars(
                    select(PolicyRuleRevisionEvidenceModel)
                    .where(
                        tuple_(
                            PolicyRuleRevisionEvidenceModel.rule_id,
                            PolicyRuleRevisionEvidenceModel.rule_revision,
                        ).in_(key_chunk)
                    )
                    .order_by(
                        PolicyRuleRevisionEvidenceModel.rule_id,
                        PolicyRuleRevisionEvidenceModel.rule_revision,
                        PolicyRuleRevisionEvidenceModel.ordinal,
                    )
                ).all()
            )
        observation_ids = tuple(
            sorted({item.source_observation_id for item in evidence_rows})
        )
        observations: dict[str, KnowledgeSourceObservationModel] = {}
        for id_chunk in _chunks(observation_ids, 400):
            observations.update(
                {
                    item.source_observation_id: item
                    for item in self._session.scalars(
                        select(KnowledgeSourceObservationModel).where(
                            KnowledgeSourceObservationModel.source_observation_id.in_(
                                id_chunk
                            )
                        )
                    ).all()
                }
            )
        relation_keys = tuple(
            (row.rule_id, row.revision)
            for row in rows
            if row.schema_version in {"policy-rule.v2", "policy-rule.v3"}
        )
        relation_rows: list[PolicyRuleRelationModel] = []
        for key_chunk in _chunks(relation_keys, 400):
            relation_rows.extend(
                self._session.scalars(
                    select(PolicyRuleRelationModel)
                    .where(
                        tuple_(
                            PolicyRuleRelationModel.rule_id,
                            PolicyRuleRelationModel.rule_revision,
                        ).in_(key_chunk)
                    )
                    .order_by(
                        PolicyRuleRelationModel.rule_id,
                        PolicyRuleRelationModel.rule_revision,
                        PolicyRuleRelationModel.ordinal,
                    )
                ).all()
            )
        claims_by_key: dict[tuple[str, int], list[PolicyRuleRevisionClaimModel]] = {}
        for claim_row in claim_rows:
            claims_by_key.setdefault(
                (claim_row.rule_id, claim_row.rule_revision), []
            ).append(claim_row)
        evidence_by_key: dict[
            tuple[str, int], list[PolicyRuleRevisionEvidenceModel]
        ] = {}
        for evidence_row in evidence_rows:
            evidence_by_key.setdefault(
                (evidence_row.rule_id, evidence_row.rule_revision), []
            ).append(evidence_row)
        relations_by_key: dict[tuple[str, int], list[PolicyRuleRelationModel]] = {}
        for relation_row in relation_rows:
            relations_by_key.setdefault(
                (relation_row.rule_id, relation_row.rule_revision), []
            ).append(relation_row)
        return tuple(
            self._to_revision(
                row,
                claim_rows=tuple(claims_by_key.get((row.rule_id, row.revision), ())),
                evidence_rows=tuple(
                    evidence_by_key.get((row.rule_id, row.revision), ())
                ),
                relation_rows=tuple(
                    relations_by_key.get((row.rule_id, row.revision), ())
                ),
                source_observations=observations,
            )
            for row in rows
        )

    def _to_revision(
        self,
        row: PolicyRuleRevisionModel,
        *,
        claim_rows: tuple[PolicyRuleRevisionClaimModel, ...] | None = None,
        evidence_rows: tuple[PolicyRuleRevisionEvidenceModel, ...] | None = None,
        relation_rows: tuple[PolicyRuleRelationModel, ...] | None = None,
        source_observations: dict[str, KnowledgeSourceObservationModel] | None = None,
    ) -> PolicyRuleRevision:
        if row.schema_version not in {
            "policy-rule.v1",
            "policy-rule.v2",
            "policy-rule.v3",
        }:
            raise ConflictError(
                "Persisted policy revision uses an unsupported schema version"
            )
        if claim_rows is None:
            claim_rows = tuple(
                self._session.scalars(
                    select(PolicyRuleRevisionClaimModel)
                    .where(
                        PolicyRuleRevisionClaimModel.rule_id == row.rule_id,
                        PolicyRuleRevisionClaimModel.rule_revision == row.revision,
                    )
                    .order_by(PolicyRuleRevisionClaimModel.ordinal)
                ).all()
            )
        if evidence_rows is None:
            evidence_rows = tuple(
                self._session.scalars(
                    select(PolicyRuleRevisionEvidenceModel)
                    .where(
                        PolicyRuleRevisionEvidenceModel.rule_id == row.rule_id,
                        PolicyRuleRevisionEvidenceModel.rule_revision == row.revision,
                    )
                    .order_by(PolicyRuleRevisionEvidenceModel.ordinal)
                ).all()
            )
        if not claim_rows or not evidence_rows:
            raise ConflictError(
                "Persisted policy revision is missing source claims or evidence"
            )
        if relation_rows is None:
            relation_rows = (
                tuple(
                    self._session.scalars(
                        select(PolicyRuleRelationModel)
                        .where(
                            PolicyRuleRelationModel.rule_id == row.rule_id,
                            PolicyRuleRelationModel.rule_revision == row.revision,
                        )
                        .order_by(PolicyRuleRelationModel.ordinal)
                    ).all()
                )
                if row.schema_version in {"policy-rule.v2", "policy-rule.v3"}
                else ()
            )
        claims = tuple(
            ClaimRevisionRef(claim_id=item.claim_id, revision=item.claim_revision)
            for item in claim_rows
        )
        evidence = tuple(
            self._to_evidence(
                item,
                observation=(
                    source_observations.get(item.source_observation_id)
                    if source_observations is not None
                    else None
                ),
                use_preloaded_observations=source_observations is not None,
            )
            for item in evidence_rows
        )
        try:
            selector_payload: dict[str, object] = dict(row.selector_json)
            stored_nodes = selector_payload.get("nodes")
            if not isinstance(stored_nodes, (list, tuple)):
                raise TypeError("Persisted policy selector nodes must be a sequence")
            parsed_nodes = tuple(
                {
                    **node,
                    "kind": PolicySelectorNodeKind(node["kind"]),
                    "field": (
                        PolicyContextField(node["field"])
                        if node.get("field") is not None
                        else None
                    ),
                    "values": tuple(node.get("values", ())),
                }
                for node in stored_nodes
                if isinstance(node, dict)
            )
            if len(parsed_nodes) != len(stored_nodes):
                raise TypeError("Persisted policy selector contains an invalid node")
            selector_payload["nodes"] = parsed_nodes
            selector = PolicySelectorAst.model_validate(selector_payload)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ConflictError("Persisted policy selector AST is invalid") from exc
        fields = PolicyRuleRevisionFields(
            rule_id=row.rule_id,
            revision=row.revision,
            schema_version=cast(
                Literal["policy-rule.v1", "policy-rule.v2", "policy-rule.v3"],
                row.schema_version,
            ),
            family_id=row.family_id,
            authority=(
                PolicyAuthorityLevel(row.authority_level)
                if row.authority_level is not None
                else None
            ),
            selector=selector,
            scope=PolicyScope(
                level=PolicyScopeLevel(row.scope_level), scope_id=row.scope_id
            ),
            domain_rule=DomainRuleRef(
                owner_module=PolicyDomainOwner(row.owner_module),
                canonical_rule_id=row.owner_rule_id,
                owner_revision=row.owner_revision,
                owner_revision_hash=row.owner_revision_hash,
            ),
            lifecycle=PolicyRevisionLifecycle(row.lifecycle),
            temporal=PolicyTemporalRevision(
                clock=BitemporalRevision(
                    revision=row.revision,
                    valid_time=_interval(row.valid_start, row.valid_end),
                    recorded_at=_aware(row.recorded_at),
                ),
                source_milestones=SourceMilestones(
                    published_at=_optional_aware(row.published_at),
                    announced_at=_optional_aware(row.announced_at),
                    adopted_at=_optional_aware(row.adopted_at),
                    effective_time=_interval(row.effective_start, row.effective_end),
                    captured_at=_aware(row.captured_at),
                ),
            ),
            source_claims=claims,
            evidence=evidence,
            relations=tuple(
                PolicyRuleRelation(
                    kind=PolicyRuleRelationKind(item.relation_kind),
                    target_rule_id=item.target_rule_id,
                    target_revision=item.target_revision,
                    target_hash=item.target_hash,
                    source_claim=ClaimRevisionRef(
                        claim_id=claim_rows[item.claim_ordinal].claim_id,
                        revision=claim_rows[item.claim_ordinal].claim_revision,
                    ),
                    evidence=evidence[item.evidence_ordinal],
                )
                for item in relation_rows
                if item.claim_ordinal < len(claim_rows)
                and item.evidence_ordinal < len(evidence)
            ),
        )
        return PolicyRuleRevision(
            **fields.model_dump(mode="python"), content_hash=row.content_hash
        )

    def _to_evidence(
        self,
        row: PolicyRuleRevisionEvidenceModel,
        *,
        observation: KnowledgeSourceObservationModel | None = None,
        use_preloaded_observations: bool = False,
    ) -> EvidenceRef:
        if not use_preloaded_observations:
            observation = self._session.get(
                KnowledgeSourceObservationModel, row.source_observation_id
            )
        if observation is None:
            raise ConflictError("Policy evidence observation is missing")
        from pydantic import HttpUrl, TypeAdapter

        return EvidenceRef(
            source_id=observation.source_id,
            source_observation_id=observation.source_observation_id,
            snapshot_sha256=observation.snapshot_sha256,
            source_url=TypeAdapter(HttpUrl).validate_python(row.source_url),
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

    @staticmethod
    def _to_approval_event(row: PolicyApprovalEventModel) -> PolicyApprovalEvent:
        return PolicyApprovalEvent(
            event_id=row.event_id,
            rule_id=row.rule_id,
            revision=row.revision,
            sequence=row.sequence,
            revision_hash=row.revision_hash,
            kind=PolicyApprovalEventKind(row.kind),
            actor_account_id=row.actor_account_id,
            capability=PolicyApprovalCapability(row.capability),
            reason=row.reason,
            recorded_at=_aware(row.recorded_at),
            preview_fingerprint=row.preview_fingerprint,
        )


def _interval(start: datetime | None, end: datetime | None) -> TemporalInterval | None:
    if start is None and end is None:
        return None
    return TemporalInterval(start=_optional_aware(start), end=_optional_aware(end))


def _interval_columns(
    interval: TemporalInterval | None,
) -> tuple[datetime | None, datetime | None]:
    return (
        _optional_utc(interval.start) if interval else None,
        _optional_utc(interval.end) if interval else None,
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _optional_aware(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _utc(value: datetime | None) -> datetime:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("policy timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _evidence_key(evidence: EvidenceRef) -> tuple[str, str, str, bool]:
    return (
        evidence.source_observation_id,
        str(evidence.source_url),
        evidence.locator.model_dump_json(),
        evidence.inferred,
    )


def _chunks(values: tuple[_T, ...], size: int) -> tuple[tuple[_T, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


__all__ = ["SqlAlchemyPolicyRuleRepository"]
