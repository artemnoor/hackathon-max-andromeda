"""Append-only adapters for knowledge claim and change-event candidates."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from andromeda.infrastructure.database.models import (
    KnowledgeChangeEventClaimModel,
    KnowledgeChangeEventEvidenceModel,
    KnowledgeChangeEventModel,
    KnowledgeClaimCandidateClusterMemberModel,
    KnowledgeClaimCandidateClusterModel,
    KnowledgeClaimEvidenceModel,
    KnowledgeClaimModel,
    KnowledgeSourceModel,
    KnowledgeSourceObservationModel,
    KnowledgeSourceRegistryRevisionModel,
)
from andromeda.infrastructure.repositories.knowledge_evidence import (
    validate_knowledge_evidence,
)
from andromeda.modules.knowledge.contracts.public import (
    BitemporalRevision,
    ChangeEvent,
    ChangeEventKind,
    ChangeEventReviewState,
    Claim,
    ClaimCandidateCluster,
    ClaimedPolicyStage,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimFingerprint,
    ClaimProposition,
    ClaimReviewState,
    ClaimRevisionRef,
    ClaimSubjectKind,
    ClaimValueBoolean,
    ClaimValueDate,
    ClaimValueDateTime,
    ClaimValueDecimal,
    ClaimValueIdentifier,
    ClaimValueText,
    EvidenceLocator,
    EvidenceRef,
    KnowledgeClaimLookup,
    KnowledgeSourceKind,
    SourceMilestones,
    SourceReliabilityTier,
    TemporalInterval,
)
from andromeda.modules.knowledge.domain.claim_fingerprint import (
    CLAIM_FINGERPRINT_VERSION,
    build_claim_cluster,
    fingerprint_claim,
)
from andromeda.modules.knowledge.repository.ports import KnowledgeCandidateRepository
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
logger = logging.getLogger("andromeda.infrastructure.repositories.knowledge_candidates")
_EvidenceModel = TypeVar(
    "_EvidenceModel", KnowledgeClaimEvidenceModel, KnowledgeChangeEventEvidenceModel
)


class SqlAlchemyKnowledgeCandidateRepository(KnowledgeCandidateRepository):
    """Immutable staged candidates; this adapter never approves or publishes them."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_claim_candidate(self, claim: Claim) -> Claim:
        if claim.review_state not in {
            ClaimReviewState.UNREVIEWED,
            ClaimReviewState.NEEDS_REVIEW,
        }:
            raise ValidationError("candidate writer only accepts unreviewed claims")
        return self._append_claim_revision(claim)

    def append_reviewed_claim_revision(self, claim: Claim) -> Claim:
        if claim.review_state not in {
            ClaimReviewState.ACCEPTED_AS_SOURCE_ASSERTION,
            ClaimReviewState.REJECTED,
            ClaimReviewState.UNRESOLVED,
            ClaimReviewState.DUPLICATE,
        }:
            raise ValidationError(
                "reviewed claim revisions require an explicit review outcome"
            )
        return self._append_claim_revision(claim)

    def _append_claim_revision(self, claim: Claim) -> Claim:
        previous = self.get_claim_revision(claim.claim_id, claim.clock.revision)
        if previous is not None:
            if previous != claim:
                raise ConflictError("Knowledge claim revisions are immutable")
            self._ensure_exact_cluster_member(previous)
            return previous

        latest = self._latest_claim_row(claim.claim_id)
        expected_revision = latest.revision + 1 if latest is not None else 1
        if claim.clock.revision != expected_revision:
            raise ConflictError(
                "Knowledge claim revisions must be appended consecutively"
            )
        if latest is not None and claim.clock.recorded_at <= _aware(latest.recorded_at):
            raise ValidationError("claim revision recorded_at must increase")
        self._validate_source_evidence(
            tuple(item.evidence for item in claim.evidence),
            recorded_at=claim.clock.recorded_at,
            required_source_observation_id=claim.source_observation_id,
        )
        primary_count = sum(
            item.relationship is ClaimEvidenceRelationship.ORIGINATES_FROM
            for item in claim.evidence
        )
        if primary_count != 1:
            raise ValidationError(
                "claim must have exactly one originating evidence link"
            )
        source_observation = self._session.get(
            KnowledgeSourceObservationModel, claim.source_observation_id
        )
        if source_observation is None:
            raise NotFoundError("Claim source observation does not exist")
        if _utc(_required_capture(claim.source_milestones.captured_at)) != _utc(
            _aware(source_observation.captured_at)
        ):
            raise ValidationError("claim captured_at must match its source observation")

        row = self._claim_model(claim)
        self._session.add(row)
        self._session.flush()
        self._session.add_all(
            self._claim_evidence_models(
                claim.claim_id, claim.clock.revision, claim.evidence
            )
        )
        self._session.flush()
        self._ensure_exact_cluster_member(claim)
        logger.info(
            "knowledge_claim_candidate_recorded claim_id=%s revision=%d observation_id=%s stage=%s",
            claim.claim_id,
            claim.clock.revision,
            claim.source_observation_id,
            claim.claimed_stage.value,
        )
        return claim

    def get_exact_claim_cluster(
        self, fingerprint: ClaimFingerprint
    ) -> ClaimCandidateCluster | None:
        row = self._session.scalar(
            select(KnowledgeClaimCandidateClusterModel).where(
                KnowledgeClaimCandidateClusterModel.fingerprint == fingerprint
            )
        )
        if row is None:
            return None
        if row.fingerprint_version != CLAIM_FINGERPRINT_VERSION:
            raise ConflictError(
                "Claim fingerprint version is unsupported by this repository"
            )
        members = self._session.scalars(
            select(KnowledgeClaimCandidateClusterMemberModel)
            .where(
                KnowledgeClaimCandidateClusterMemberModel.cluster_id == row.cluster_id
            )
            .order_by(
                KnowledgeClaimCandidateClusterMemberModel.claim_id,
                KnowledgeClaimCandidateClusterMemberModel.claim_revision,
            )
            .limit(501)
        ).all()
        if len(members) > 500:
            raise ValidationError(
                "Exact claim cluster exceeds the bounded 500 member limit"
            )
        if not members:
            raise ConflictError("Persisted claim cluster has no members")
        return build_claim_cluster(
            fingerprint,
            tuple(
                ClaimRevisionRef(claim_id=item.claim_id, revision=item.claim_revision)
                for item in members
            ),
        )

    def _ensure_exact_cluster_member(self, claim: Claim) -> None:
        fingerprint = fingerprint_claim(claim)
        cluster_id = str(
            build_claim_cluster(
                fingerprint,
                (
                    ClaimRevisionRef(
                        claim_id=claim.claim_id,
                        revision=claim.clock.revision,
                    ),
                ),
            ).cluster_id
        )
        row = self._session.get(KnowledgeClaimCandidateClusterModel, cluster_id)
        if row is None:
            self._session.add(
                KnowledgeClaimCandidateClusterModel(
                    cluster_id=cluster_id,
                    fingerprint=fingerprint,
                    fingerprint_version=CLAIM_FINGERPRINT_VERSION,
                    created_at=_utc(claim.clock.recorded_at),
                )
            )
            self._session.flush()
        elif (
            row.fingerprint != fingerprint
            or row.fingerprint_version != CLAIM_FINGERPRINT_VERSION
        ):
            raise ConflictError(
                "Claim cluster identity conflicts with its exact fingerprint"
            )
        membership = self._session.get(
            KnowledgeClaimCandidateClusterMemberModel,
            (cluster_id, claim.claim_id, claim.clock.revision),
        )
        if membership is None:
            self._session.add(
                KnowledgeClaimCandidateClusterMemberModel(
                    cluster_id=cluster_id,
                    claim_id=claim.claim_id,
                    claim_revision=claim.clock.revision,
                )
            )
            self._session.flush()

    def get_claim_revision(self, claim_id: str, revision: int) -> Claim | None:
        row = self._session.get(KnowledgeClaimModel, (claim_id, revision))
        return self._to_claim(row) if row is not None else None

    def list_pending_claims(self, *, limit: int = 100) -> tuple[Claim, ...]:
        _validate_limit(limit)
        latest = (
            select(
                KnowledgeClaimModel.claim_id.label("claim_id"),
                func.max(KnowledgeClaimModel.revision).label("revision"),
            )
            .group_by(KnowledgeClaimModel.claim_id)
            .subquery()
        )
        rows = self._session.scalars(
            select(KnowledgeClaimModel)
            .join(
                latest,
                (KnowledgeClaimModel.claim_id == latest.c.claim_id)
                & (KnowledgeClaimModel.revision == latest.c.revision),
            )
            .where(
                KnowledgeClaimModel.review_state.in_(
                    ("unreviewed", "needs_review", "unresolved")
                )
            )
            .order_by(
                KnowledgeClaimModel.recorded_at.desc(), KnowledgeClaimModel.claim_id
            )
            .limit(limit)
        ).all()
        return tuple(self._to_claim(row) for row in rows)

    def list_pending_change_events(
        self, *, limit: int = 100
    ) -> tuple[ChangeEvent, ...]:
        _validate_limit(limit)
        latest = (
            select(
                KnowledgeChangeEventModel.change_event_id.label("change_event_id"),
                func.max(KnowledgeChangeEventModel.revision).label("revision"),
            )
            .group_by(KnowledgeChangeEventModel.change_event_id)
            .subquery()
        )
        rows = self._session.scalars(
            select(KnowledgeChangeEventModel)
            .join(
                latest,
                (KnowledgeChangeEventModel.change_event_id == latest.c.change_event_id)
                & (KnowledgeChangeEventModel.revision == latest.c.revision),
            )
            .where(
                KnowledgeChangeEventModel.review_state.in_(
                    ("needs_review", "unresolved")
                )
            )
            .order_by(
                KnowledgeChangeEventModel.recorded_at.desc(),
                KnowledgeChangeEventModel.change_event_id,
            )
            .limit(limit)
        ).all()
        return tuple(self._to_event(row) for row in rows)

    def get_as_known_at(self, claim_id: str, as_known_at: datetime) -> Claim | None:
        _require_aware(as_known_at, "as_known_at")
        row = self._session.scalar(
            select(KnowledgeClaimModel)
            .where(
                KnowledgeClaimModel.claim_id == claim_id,
                KnowledgeClaimModel.recorded_at <= _utc(as_known_at),
            )
            .order_by(KnowledgeClaimModel.revision.desc())
            .limit(1)
        )
        return self._to_claim(row) if row is not None else None

    def list_for_observation(
        self, source_observation_id: str, *, limit: int = 100
    ) -> tuple[Claim, ...]:
        _validate_limit(limit)
        rows = self._session.scalars(
            select(KnowledgeClaimModel)
            .where(KnowledgeClaimModel.source_observation_id == source_observation_id)
            .order_by(
                KnowledgeClaimModel.recorded_at.desc(),
                KnowledgeClaimModel.claim_id,
                KnowledgeClaimModel.revision.desc(),
            )
            .limit(limit)
        ).all()
        return tuple(self._to_claim(row) for row in rows)

    def list_by_predicate(
        self,
        predicate: str,
        *,
        as_known_at: datetime,
        subject_id: str | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeClaimLookup, ...]:
        _require_aware(as_known_at, "as_known_at")
        _validate_limit(limit)
        latest = (
            select(
                KnowledgeClaimModel.claim_id.label("claim_id"),
                func.max(KnowledgeClaimModel.revision).label("revision"),
            )
            .where(KnowledgeClaimModel.recorded_at <= _utc(as_known_at))
            .group_by(KnowledgeClaimModel.claim_id)
            .subquery()
        )
        statement = (
            select(KnowledgeClaimModel)
            .join(
                latest,
                (KnowledgeClaimModel.claim_id == latest.c.claim_id)
                & (KnowledgeClaimModel.revision == latest.c.revision),
            )
            .where(
                KnowledgeClaimModel.proposition_predicate == predicate,
                KnowledgeClaimModel.review_state.in_(
                    ("accepted_as_source_assertion", "unreviewed", "needs_review", "unresolved")
                ),
            )
        )
        if subject_id is not None:
            statement = statement.where(
                KnowledgeClaimModel.proposition_subject_id == subject_id
            )
        rows = self._session.scalars(
            statement.order_by(
                KnowledgeClaimModel.recorded_at.desc(),
                KnowledgeClaimModel.claim_id,
            ).limit(limit)
        ).all()
        results: list[KnowledgeClaimLookup] = []
        for row in rows:
            claim = self._to_claim(row)
            observation = self._session.get(
                KnowledgeSourceObservationModel, claim.source_observation_id
            )
            if observation is None:
                raise ConflictError("Claim origin observation is missing")
            source = self._session.get(KnowledgeSourceModel, observation.source_id)
            registry = self._session.get(
                KnowledgeSourceRegistryRevisionModel,
                (observation.source_id, observation.registry_revision),
            )
            if source is None or registry is None:
                raise ConflictError("Claim origin source registry revision is missing")
            results.append(
                KnowledgeClaimLookup(
                    claim=claim,
                    source_display_name=source.display_name,
                    source_kind=KnowledgeSourceKind(registry.source_kind),
                    source_reliability=SourceReliabilityTier(registry.reliability_tier),
                )
            )
        return tuple(results)

    def append_change_event_candidate(self, event: ChangeEvent) -> ChangeEvent:
        if event.review_state is not ChangeEventReviewState.NEEDS_REVIEW:
            raise ValidationError(
                "candidate writer only accepts change events needing review"
            )
        return self._append_change_event_revision(event)

    def append_reviewed_change_event_revision(self, event: ChangeEvent) -> ChangeEvent:
        if event.review_state not in {
            ChangeEventReviewState.ACCEPTED_AS_SOURCE_EVENT,
            ChangeEventReviewState.REJECTED,
            ChangeEventReviewState.UNRESOLVED,
            ChangeEventReviewState.DUPLICATE,
        }:
            raise ValidationError(
                "reviewed change events require an explicit review outcome"
            )
        return self._append_change_event_revision(event)

    def _append_change_event_revision(self, event: ChangeEvent) -> ChangeEvent:
        previous = self.get_change_event_revision(
            event.change_event_id, event.clock.revision
        )
        if previous is not None:
            if previous != event:
                raise ConflictError("Knowledge change-event revisions are immutable")
            return previous

        latest = self._session.scalar(
            select(KnowledgeChangeEventModel)
            .where(KnowledgeChangeEventModel.change_event_id == event.change_event_id)
            .order_by(KnowledgeChangeEventModel.revision.desc())
            .limit(1)
        )
        expected_revision = latest.revision + 1 if latest is not None else 1
        if event.clock.revision != expected_revision:
            raise ConflictError(
                "Knowledge change-event revisions must be appended consecutively"
            )
        if latest is not None and event.clock.recorded_at <= _aware(latest.recorded_at):
            raise ValidationError("change-event revision recorded_at must increase")

        for reference in event.claims:
            claim = self.get_claim_revision(reference.claim_id, reference.revision)
            if claim is None:
                raise NotFoundError("Change event references an unknown claim revision")
            if claim.clock.recorded_at > event.clock.recorded_at:
                raise ValidationError(
                    "change event cannot predate a referenced claim revision"
                )
        self._validate_source_evidence(
            event.evidence, recorded_at=event.clock.recorded_at
        )
        primary_observation = self._session.get(
            KnowledgeSourceObservationModel, event.primary_source_observation_id
        )
        if primary_observation is None:
            raise NotFoundError(
                "Change event primary source observation does not exist"
            )
        if _utc(_required_capture(event.source_milestones.captured_at)) != _utc(
            _aware(primary_observation.captured_at)
        ):
            raise ValidationError(
                "change event captured_at must match its primary source observation"
            )

        row = self._event_model(event)
        self._session.add(row)
        self._session.flush()
        self._session.add_all(
            KnowledgeChangeEventClaimModel(
                change_event_id=event.change_event_id,
                event_revision=event.clock.revision,
                ordinal=ordinal,
                claim_id=reference.claim_id,
                claim_revision=reference.revision,
            )
            for ordinal, reference in enumerate(event.claims)
        )
        self._session.add_all(
            self._event_evidence_models(
                event.change_event_id, event.clock.revision, event.evidence
            )
        )
        self._session.flush()
        logger.info(
            "knowledge_change_event_candidate_recorded event_id=%s revision=%d kind=%s claim_count=%d",
            event.change_event_id,
            event.clock.revision,
            event.event_kind.value,
            len(event.claims),
        )
        return event

    def get_change_event_revision(
        self, event_id: str, revision: int
    ) -> ChangeEvent | None:
        row = self._session.get(KnowledgeChangeEventModel, (event_id, revision))
        return self._to_event(row) if row is not None else None

    def _latest_claim_row(self, claim_id: str) -> KnowledgeClaimModel | None:
        return self._session.scalar(
            select(KnowledgeClaimModel)
            .where(KnowledgeClaimModel.claim_id == claim_id)
            .order_by(KnowledgeClaimModel.revision.desc())
            .limit(1)
        )

    def _validate_source_evidence(
        self,
        evidence: tuple[EvidenceRef, ...],
        *,
        recorded_at: datetime,
        required_source_observation_id: str | None = None,
    ) -> None:
        validate_knowledge_evidence(
            self._session,
            evidence,
            recorded_at=recorded_at,
            required_source_observation_id=required_source_observation_id,
        )

    def _claim_model(self, claim: Claim) -> KnowledgeClaimModel:
        proposition = claim.proposition
        value = proposition.value if proposition is not None else None
        value_kind = value.kind if value is not None else None
        values: dict[str, object | None] = {
            "proposition_value_text": None,
            "proposition_value_decimal": None,
            "proposition_value_boolean": None,
            "proposition_value_date": None,
            "proposition_value_datetime": None,
            "proposition_value_identifier": None,
        }
        if value is not None:
            attribute = f"proposition_value_{value_kind}"
            if attribute not in values:
                raise ValidationError("Unsupported typed claim value")
            value_data = value.value
            values[attribute] = (
                _utc(value_data) if isinstance(value_data, datetime) else value_data
            )
        valid_start, valid_end = _interval_columns(claim.clock.valid_time)
        effective_start, effective_end = _interval_columns(
            claim.source_milestones.effective_time
        )
        return KnowledgeClaimModel(
            claim_id=claim.claim_id,
            revision=claim.clock.revision,
            source_observation_id=claim.source_observation_id,
            text_start_offset=claim.text_start_offset,
            text_end_offset=claim.text_end_offset,
            assertion_text=claim.assertion_text,
            assertion_text_sha256=claim.assertion_text_sha256,
            proposition_predicate=proposition.predicate if proposition else None,
            proposition_subject_kind=proposition.subject_kind.value
            if proposition
            else None,
            proposition_subject_id=proposition.subject_id if proposition else None,
            proposition_unit=proposition.unit if proposition else None,
            proposition_value_kind=value_kind,
            **values,
            claimed_stage=claim.claimed_stage.value,
            review_state=claim.review_state.value,
            valid_start=valid_start,
            valid_end=valid_end,
            published_at=_optional_utc(claim.source_milestones.published_at),
            announced_at=_optional_utc(claim.source_milestones.announced_at),
            adopted_at=_optional_utc(claim.source_milestones.adopted_at),
            effective_start=effective_start,
            effective_end=effective_end,
            captured_at=_utc(_required_capture(claim.source_milestones.captured_at)),
            extraction_method=claim.extraction_method.value,
            extractor_id=claim.extractor_id,
            extractor_version=claim.extractor_version,
            extraction_confidence=claim.extraction_confidence,
            recorded_at=_utc(claim.clock.recorded_at),
        )

    def _to_claim(self, row: KnowledgeClaimModel) -> Claim:
        evidence_rows = self._session.execute(
            select(KnowledgeClaimEvidenceModel, KnowledgeSourceObservationModel)
            .join(
                KnowledgeSourceObservationModel,
                KnowledgeClaimEvidenceModel.source_observation_id
                == KnowledgeSourceObservationModel.source_observation_id,
            )
            .where(
                KnowledgeClaimEvidenceModel.claim_id == row.claim_id,
                KnowledgeClaimEvidenceModel.claim_revision == row.revision,
            )
            .order_by(KnowledgeClaimEvidenceModel.ordinal)
        ).all()
        evidence = tuple(
            ClaimEvidenceLink(
                relationship=ClaimEvidenceRelationship(item.relationship),
                evidence=_to_evidence(item, observation),
            )
            for item, observation in evidence_rows
        )
        proposition = _to_proposition(row)
        return Claim(
            claim_id=row.claim_id,
            clock=BitemporalRevision(
                revision=row.revision,
                valid_time=_interval(row.valid_start, row.valid_end),
                recorded_at=_aware(row.recorded_at),
            ),
            source_observation_id=row.source_observation_id,
            text_start_offset=row.text_start_offset,
            text_end_offset=row.text_end_offset,
            assertion_text=row.assertion_text,
            assertion_text_sha256=row.assertion_text_sha256,
            proposition=proposition,
            claimed_stage=ClaimedPolicyStage(row.claimed_stage),
            review_state=ClaimReviewState(row.review_state),
            source_milestones=SourceMilestones(
                published_at=_optional_aware(row.published_at),
                announced_at=_optional_aware(row.announced_at),
                adopted_at=_optional_aware(row.adopted_at),
                effective_time=_interval(row.effective_start, row.effective_end),
                captured_at=_aware(row.captured_at),
            ),
            extraction_method=ClaimExtractionMethod(row.extraction_method),
            extractor_id=row.extractor_id,
            extractor_version=row.extractor_version,
            extraction_confidence=row.extraction_confidence,
            evidence=evidence,
        )

    def _event_model(self, event: ChangeEvent) -> KnowledgeChangeEventModel:
        valid_start, valid_end = _interval_columns(event.clock.valid_time)
        effective_start, effective_end = _interval_columns(
            event.source_milestones.effective_time
        )
        return KnowledgeChangeEventModel(
            change_event_id=event.change_event_id,
            revision=event.clock.revision,
            primary_source_observation_id=event.primary_source_observation_id,
            event_kind=event.event_kind.value,
            review_state=event.review_state.value,
            valid_start=valid_start,
            valid_end=valid_end,
            published_at=_optional_utc(event.source_milestones.published_at),
            announced_at=_optional_utc(event.source_milestones.announced_at),
            adopted_at=_optional_utc(event.source_milestones.adopted_at),
            effective_start=effective_start,
            effective_end=effective_end,
            captured_at=_utc(_required_capture(event.source_milestones.captured_at)),
            recorded_at=_utc(event.clock.recorded_at),
        )

    def _to_event(self, row: KnowledgeChangeEventModel) -> ChangeEvent:
        claims = self._session.scalars(
            select(KnowledgeChangeEventClaimModel)
            .where(
                KnowledgeChangeEventClaimModel.change_event_id == row.change_event_id,
                KnowledgeChangeEventClaimModel.event_revision == row.revision,
            )
            .order_by(KnowledgeChangeEventClaimModel.ordinal)
        ).all()
        evidence_rows = self._session.execute(
            select(KnowledgeChangeEventEvidenceModel, KnowledgeSourceObservationModel)
            .join(
                KnowledgeSourceObservationModel,
                KnowledgeChangeEventEvidenceModel.source_observation_id
                == KnowledgeSourceObservationModel.source_observation_id,
            )
            .where(
                KnowledgeChangeEventEvidenceModel.change_event_id
                == row.change_event_id,
                KnowledgeChangeEventEvidenceModel.event_revision == row.revision,
            )
            .order_by(KnowledgeChangeEventEvidenceModel.ordinal)
        ).all()
        evidence = tuple(
            _to_evidence(item, observation) for item, observation in evidence_rows
        )
        if not claims or not evidence:
            raise ConflictError("Persisted change event is missing claims or evidence")
        return ChangeEvent(
            change_event_id=row.change_event_id,
            clock=BitemporalRevision(
                revision=row.revision,
                valid_time=_interval(row.valid_start, row.valid_end),
                recorded_at=_aware(row.recorded_at),
            ),
            primary_source_observation_id=row.primary_source_observation_id,
            event_kind=ChangeEventKind(row.event_kind),
            review_state=ChangeEventReviewState(row.review_state),
            source_milestones=SourceMilestones(
                published_at=_optional_aware(row.published_at),
                announced_at=_optional_aware(row.announced_at),
                adopted_at=_optional_aware(row.adopted_at),
                effective_time=_interval(row.effective_start, row.effective_end),
                captured_at=_aware(row.captured_at),
            ),
            claims=tuple(
                ClaimRevisionRef(claim_id=item.claim_id, revision=item.claim_revision)
                for item in claims
            ),
            evidence=evidence,
        )

    @staticmethod
    def _claim_evidence_models(
        claim_id: str, revision: int, evidence: tuple[ClaimEvidenceLink, ...]
    ) -> list[KnowledgeClaimEvidenceModel]:
        return [
            _evidence_model(
                KnowledgeClaimEvidenceModel,
                claim_id=claim_id,
                claim_revision=revision,
                ordinal=ordinal,
                relationship=link.relationship.value,
                evidence=link.evidence,
            )
            for ordinal, link in enumerate(evidence)
        ]

    @staticmethod
    def _event_evidence_models(
        event_id: str, revision: int, evidence: tuple[EvidenceRef, ...]
    ) -> list[KnowledgeChangeEventEvidenceModel]:
        return [
            _evidence_model(
                KnowledgeChangeEventEvidenceModel,
                change_event_id=event_id,
                event_revision=revision,
                ordinal=ordinal,
                evidence=reference,
            )
            for ordinal, reference in enumerate(evidence)
        ]


def _to_evidence(
    item: KnowledgeClaimEvidenceModel | KnowledgeChangeEventEvidenceModel,
    observation: KnowledgeSourceObservationModel,
) -> EvidenceRef:
    return EvidenceRef(
        source_id=observation.source_id,
        source_observation_id=observation.source_observation_id,
        snapshot_sha256=observation.snapshot_sha256,
        source_url=_HTTP_URL_ADAPTER.validate_python(item.source_url),
        locator=EvidenceLocator(
            page=item.locator_page,
            table=item.locator_table,
            row=item.locator_row,
            section=item.locator_section,
            field=item.locator_field,
            record_key=item.locator_record_key,
        ),
        inferred=item.inferred,
    )


def _evidence_model(
    model_type: type[_EvidenceModel], *, evidence: EvidenceRef, **owner: object
) -> _EvidenceModel:
    locator = evidence.locator
    return model_type(
        **cast(Any, owner),
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


def _to_proposition(row: KnowledgeClaimModel) -> ClaimProposition | None:
    if row.proposition_predicate is None:
        return None
    if row.proposition_subject_kind is None:
        raise ConflictError("Persisted claim has no proposition subject kind")
    value_kind = row.proposition_value_kind
    value_data: object | None = {
        "text": row.proposition_value_text,
        "decimal": row.proposition_value_decimal,
        "boolean": row.proposition_value_boolean,
        "date": row.proposition_value_date,
        "datetime": _optional_aware(row.proposition_value_datetime),
        "identifier": row.proposition_value_identifier,
    }.get(value_kind or "")
    if value_data is None:
        raise ConflictError("Persisted claim has an invalid typed proposition value")
    value_model = {
        "text": ClaimValueText,
        "decimal": ClaimValueDecimal,
        "boolean": ClaimValueBoolean,
        "date": ClaimValueDate,
        "datetime": ClaimValueDateTime,
        "identifier": ClaimValueIdentifier,
    }.get(value_kind or "")
    if value_model is None:
        raise ConflictError("Persisted claim has an unsupported proposition value kind")
    return ClaimProposition(
        predicate=row.proposition_predicate,
        subject_kind=ClaimSubjectKind(row.proposition_subject_kind),
        subject_id=row.proposition_subject_id,
        unit=row.proposition_unit,
        value=value_model(kind=value_kind, value=value_data),
    )


def _interval(start: datetime | None, end: datetime | None) -> TemporalInterval | None:
    if start is None and end is None:
        return None
    return TemporalInterval(
        start=_optional_aware(start),
        end=_optional_aware(end),
    )


def _interval_columns(
    interval: TemporalInterval | None,
) -> tuple[datetime | None, datetime | None]:
    return (
        _optional_utc(interval.start) if interval else None,
        _optional_utc(interval.end) if interval else None,
    )


def _validate_limit(limit: int) -> None:
    if limit < 1 or limit > 500:
        raise ValidationError("Candidate query limit must be between 1 and 500")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field_name} must be timezone-aware")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _optional_aware(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _utc(value: datetime) -> datetime:
    _require_aware(value, "datetime")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _required_capture(value: datetime | None) -> datetime:
    if value is None:
        raise ValidationError("candidate source milestones must preserve captured_at")
    return value


__all__ = ["SqlAlchemyKnowledgeCandidateRepository"]
