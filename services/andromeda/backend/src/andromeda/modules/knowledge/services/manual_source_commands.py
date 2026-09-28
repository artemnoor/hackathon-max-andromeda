"""Authorized human submissions through the source-backed candidate path."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from andromeda.modules.knowledge.contracts.public import (
    ApprovedSourceRegistryRevision,
    BitemporalRevision,
    Claim,
    ClaimEvidenceLink,
    ClaimEvidenceRelationship,
    ClaimExtractionMethod,
    ClaimReviewState,
    EvidenceRef,
    KnowledgeManualSubmission,
    ManualClaimDraft,
    ManualClaimMetadataCorrection,
    ManualSourceRegistrationDraft,
    ManualSubmissionKind,
    SourceIdentity,
    SourceObservation,
    claim_id_for_source_assertion,
    manual_request_fingerprint,
    manual_submission_id,
)
from andromeda.modules.knowledge.contracts.review import knowledge_review_target_ref
from andromeda.modules.knowledge.domain.sources import is_allowed_source_url
from andromeda.modules.knowledge.repository.ports import (
    KnowledgeCandidateRepository,
    KnowledgeManualAuthorization,
    KnowledgeManualSnapshotCapture,
    KnowledgeManualSubmissionRepository,
    KnowledgeReviewUnitOfWork,
    KnowledgeSourceRepository,
)
from andromeda.shared.contracts.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("andromeda.modules.knowledge.manual_source_commands")
MAX_MANUAL_DOCUMENT_BYTES = 10 * 1024 * 1024


class ManualSourceCommands:
    """Keep every operator contribution pending, attributable and reproducible."""

    def __init__(
        self,
        *,
        sources: KnowledgeSourceRepository,
        candidates: KnowledgeCandidateRepository,
        submissions: KnowledgeManualSubmissionRepository,
        authorizer: KnowledgeManualAuthorization,
        capture: KnowledgeManualSnapshotCapture,
        unit_of_work: KnowledgeReviewUnitOfWork,
    ) -> None:
        self._sources = sources
        self._candidates = candidates
        self._submissions = submissions
        self._authorizer = authorizer
        self._capture = capture
        self._unit_of_work = unit_of_work

    def register_source(
        self,
        *,
        actor_account_id: str,
        draft: ManualSourceRegistrationDraft,
        now: datetime,
    ) -> ApprovedSourceRegistryRevision:
        """Register a reviewed source route, always disabled for automatic polling."""

        self._authorizer.require_source_steward(actor_account_id)
        now = _utc(now)
        proposed_identity = SourceIdentity(
            source_id=draft.source_id,
            issuer_id=draft.issuer_id,
            jurisdiction=draft.jurisdiction,
            identity_key=draft.identity_key,
            display_name=draft.display_name,
            created_at=now,
        )
        try:
            identity = self._sources.get_source_identity(draft.source_id)
            if identity is None:
                identity = self._sources.register_source_identity(proposed_identity)
            elif (
                identity.issuer_id != proposed_identity.issuer_id
                or identity.jurisdiction != proposed_identity.jurisdiction
                or identity.identity_key != proposed_identity.identity_key
                or identity.display_name != proposed_identity.display_name
            ):
                raise ConflictError("Source identity is immutable")
            latest = self._sources.get_latest_registry_revision(draft.source_id)
            revision_number = latest.revision + 1 if latest is not None else 1
            revision = ApprovedSourceRegistryRevision(
                source_id=draft.source_id,
                revision=revision_number,
                source_kind=draft.source_kind,
                reliability_tier=draft.reliability_tier,
                adapter_id=draft.adapter_id,
                adapter_version=draft.adapter_version,
                start_url=draft.start_url,
                allowlist=draft.allowlist,
                poll_interval_seconds=draft.poll_interval_seconds,
                freshness_budget_seconds=draft.freshness_budget_seconds,
                enabled=False,
                approved_by_account_id=actor_account_id,
                approved_at=now,
                approval_reason=draft.reason,
                recorded_at=now,
            )
            if latest is not None and _same_registry_configuration(latest, revision):
                self._unit_of_work.commit()
                logger.info(
                    "knowledge_manual_source_registration_reused source_id=%s revision=%d",
                    latest.source_id,
                    latest.revision,
                )
                return latest
            stored = self._sources.append_approved_registry_revision(revision)
            self._unit_of_work.commit()
            logger.info(
                "knowledge_manual_source_registered source_id=%s revision=%d polling_enabled=false",
                stored.source_id,
                stored.revision,
            )
            return stored
        except Exception as exc:
            self._unit_of_work.rollback()
            logger.error(
                "knowledge_manual_source_registration_failed actor_account_id=%s error_type=%s",
                actor_account_id,
                type(exc).__name__,
            )
            raise

    def attach_document(
        self,
        *,
        actor_account_id: str,
        source_id: str,
        requested_url: str,
        content_type: str,
        body: bytes,
        reason: str,
        idempotency_key: str,
        expires_at: datetime | None,
        now: datetime,
    ) -> SourceObservation:
        self._authorizer.require_source_steward(actor_account_id)
        now = _utc(now)
        normalized_type = _validate_manual_document(body, content_type)
        if expires_at is not None:
            expires_at = _utc(expires_at)
            if expires_at <= now:
                raise ValidationError("Manual source attachment expiry must be in the future")
        registry = self._sources.get_latest_registry_revision(source_id)
        if registry is None:
            raise NotFoundError("Approved source registry revision does not exist")
        if not any(
            is_allowed_source_url(requested_url, host=route.host, path_prefix=route.path_prefix)
            for route in registry.allowlist
        ):
            raise ValidationError("Manual document URL is outside the approved source allowlist")

        idempotency_digest = _idempotency_digest(idempotency_key)
        request_fingerprint = manual_request_fingerprint(
            {
                "source_id": source_id,
                "registry_revision": registry.revision,
                "requested_url": requested_url,
                "content_type": normalized_type,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "reason": reason,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        )
        existing = self._submissions.get_by_idempotency_key(actor_account_id, idempotency_digest)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise ConflictError("Manual source idempotency key was already used")
            observation = self._sources.get_observation(existing.source_observation_id)
            if observation is None:
                raise ConflictError("Manual source audit points to a missing observation")
            return observation

        observation = self._capture.capture(
            actor_account_id=actor_account_id,
            registry=registry,
            requested_url=requested_url,
            content_type=normalized_type,
            body=body,
            idempotency_key=idempotency_key,
            captured_at=now,
        )
        event = KnowledgeManualSubmission(
            submission_id=manual_submission_id(
                actor_account_id=actor_account_id,
                idempotency_key=idempotency_digest,
                request_fingerprint=request_fingerprint,
            ),
            kind=ManualSubmissionKind.SOURCE_SNAPSHOT,
            idempotency_key=idempotency_digest,
            request_fingerprint=request_fingerprint,
            actor_account_id=actor_account_id,
            reason=reason,
            target_id=observation.source_observation_id,
            target_revision=observation.registry_revision,
            target_hash=observation.snapshot_sha256,
            source_observation_id=observation.source_observation_id,
            expires_at=expires_at,
            recorded_at=now,
        )
        try:
            stored = self._submissions.append_submission(event)
            self._unit_of_work.commit()
            logger.info(
                "knowledge_manual_snapshot_attributed observation_id=%s actor_account_id=%s",
                stored.source_observation_id,
                stored.actor_account_id,
            )
            return observation
        except Exception as exc:
            self._unit_of_work.rollback()
            logger.error(
                "knowledge_manual_snapshot_attribution_failed observation_id=%s error_type=%s",
                observation.source_observation_id,
                type(exc).__name__,
            )
            raise

    def submit_claim(
        self,
        *,
        actor_account_id: str,
        university_id: str,
        draft: ManualClaimDraft,
        now: datetime,
    ) -> Claim:
        self._authorizer.require_university_editor(actor_account_id, university_id)
        now = _utc(now)
        if draft.expires_at is not None and _utc(draft.expires_at) <= now:
            raise ValidationError("Manual claim candidate expiry must be in the future")
        idempotency_digest = _idempotency_digest(draft.idempotency_key)
        fingerprint = manual_request_fingerprint(
            {"university_id": university_id, "draft": draft.model_dump(mode="json")}
        )
        existing = self._submissions.get_by_idempotency_key(actor_account_id, idempotency_digest)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError("Manual claim idempotency key was already used")
            claim = self._candidates.get_claim_revision(existing.target_id, existing.target_revision)
            if claim is None or knowledge_review_target_ref(claim).revision_hash != existing.target_hash:
                raise ConflictError("Manual claim audit points to a missing or changed candidate")
            return claim
        observation = self._sources.get_observation(draft.source_observation_id)
        if observation is None:
            raise NotFoundError("Manual claim source observation does not exist")
        source_text = draft.source_text
        start = source_text.index(draft.assertion_text)
        end = start + len(draft.assertion_text)
        milestones = type(draft.source_milestones).model_validate(
            {
                **draft.source_milestones.model_dump(mode="python"),
                "captured_at": observation.captured_at,
            }
        )
        evidence = EvidenceRef(
            source_id=observation.source_id,
            source_observation_id=observation.source_observation_id,
            snapshot_sha256=observation.snapshot_sha256,
            source_url=observation.final_url,
            locator=draft.locator,
        )
        claim = Claim(
            claim_id=claim_id_for_source_assertion(
                observation.source_observation_id,
                start,
                end,
                hashlib.sha256(draft.assertion_text.encode("utf-8")).hexdigest(),
            ),
            clock=BitemporalRevision(
                revision=1,
                valid_time=draft.valid_time,
                recorded_at=now,
            ),
            source_observation_id=observation.source_observation_id,
            text_start_offset=start,
            text_end_offset=end,
            assertion_text=draft.assertion_text,
            assertion_text_sha256=hashlib.sha256(draft.assertion_text.encode("utf-8")).hexdigest(),
            proposition=draft.proposition,
            claimed_stage=draft.claimed_stage,
            review_state=ClaimReviewState.NEEDS_REVIEW,
            source_milestones=milestones,
            extraction_method=ClaimExtractionMethod.MANUAL,
            extractor_id="manual-operator",
            extractor_version="v1",
            extraction_confidence=None,
            evidence=(
                ClaimEvidenceLink(
                    relationship=ClaimEvidenceRelationship.ORIGINATES_FROM,
                    evidence=evidence,
                ),
            ),
        )
        try:
            candidate = self._candidates.append_claim_candidate(claim)
            target = knowledge_review_target_ref(candidate)
            event = KnowledgeManualSubmission(
                submission_id=manual_submission_id(
                    actor_account_id=actor_account_id,
                    idempotency_key=idempotency_digest,
                    request_fingerprint=fingerprint,
                ),
                kind=ManualSubmissionKind.CLAIM_CANDIDATE,
                idempotency_key=idempotency_digest,
                request_fingerprint=fingerprint,
                actor_account_id=actor_account_id,
                university_id=university_id,
                reason=draft.reason,
                target_id=candidate.claim_id,
                target_revision=candidate.clock.revision,
                target_hash=target.revision_hash,
                source_observation_id=observation.source_observation_id,
                expires_at=draft.expires_at,
                recorded_at=now,
            )
            self._submissions.append_submission(event)
            self._unit_of_work.commit()
            logger.info(
                "knowledge_manual_claim_submitted claim_id=%s revision=%d university_id=%s",
                candidate.claim_id,
                candidate.clock.revision,
                university_id,
            )
            return candidate
        except Exception as exc:
            self._unit_of_work.rollback()
            logger.error(
                "knowledge_manual_claim_submission_failed source_observation_id=%s university_id=%s error_type=%s",
                observation.source_observation_id,
                university_id,
                type(exc).__name__,
            )
            raise

    def correct_claim_metadata(
        self,
        *,
        actor_account_id: str,
        university_id: str,
        correction: ManualClaimMetadataCorrection,
        now: datetime,
    ) -> Claim:
        """Append a university-scoped metadata correction as a new pending revision."""

        self._authorizer.require_university_editor(actor_account_id, university_id)
        now = _utc(now)
        idempotency_digest = _idempotency_digest(correction.idempotency_key)
        fingerprint = manual_request_fingerprint(
            {"university_id": university_id, "correction": correction.model_dump(mode="json")}
        )
        existing = self._submissions.get_by_idempotency_key(actor_account_id, idempotency_digest)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictError("Manual candidate idempotency key was already used")
            claim = self._candidates.get_claim_revision(existing.target_id, existing.target_revision)
            if claim is None or knowledge_review_target_ref(claim).revision_hash != existing.target_hash:
                raise ConflictError("Manual correction audit points to a missing or changed candidate")
            return claim

        if correction.expires_at is not None and _utc(correction.expires_at) <= now:
            raise ValidationError("Manual correction expiry must be in the future")
        current = self._candidates.get_claim_revision(
            correction.claim_id, correction.expected_revision
        )
        if current is None:
            raise NotFoundError("Exact manual claim candidate revision does not exist")
        current_ref = knowledge_review_target_ref(current)
        if current_ref.revision_hash != correction.expected_revision_hash:
            raise ConflictError("Manual correction is bound to a stale claim revision")
        prior_submission = self._submissions.get_latest_for_target(correction.claim_id)
        if (
            prior_submission is None
            or prior_submission.kind is not ManualSubmissionKind.CLAIM_CANDIDATE
            or prior_submission.university_id != university_id
            or prior_submission.target_revision != current.clock.revision
            or prior_submission.target_hash != current_ref.revision_hash
        ):
            raise NotFoundError("Manual claim candidate is outside the requested university scope")
        if prior_submission.expires_at is not None and prior_submission.expires_at <= now:
            raise ConflictError("Expired manual claim candidates cannot be corrected")
        if current.review_state not in {
            ClaimReviewState.NEEDS_REVIEW,
            ClaimReviewState.UNRESOLVED,
        }:
            raise ConflictError("Only pending or unresolved manual claim candidates can be corrected")
        if now <= current.clock.recorded_at:
            raise ValidationError("Manual correction time must follow the candidate revision")

        revised_claim = Claim.model_validate(
            {
                **current.model_dump(mode="python"),
                "clock": {
                    **current.clock.model_dump(mode="python"),
                    "revision": current.clock.revision + 1,
                    "recorded_at": now,
                },
                "proposition": correction.proposition,
                "claimed_stage": correction.claimed_stage,
                "review_state": ClaimReviewState.NEEDS_REVIEW,
            }
        )
        try:
            candidate = self._candidates.append_claim_candidate(revised_claim)
            target = knowledge_review_target_ref(candidate)
            event = KnowledgeManualSubmission(
                submission_id=manual_submission_id(
                    actor_account_id=actor_account_id,
                    idempotency_key=idempotency_digest,
                    request_fingerprint=fingerprint,
                ),
                kind=ManualSubmissionKind.CLAIM_CANDIDATE,
                idempotency_key=idempotency_digest,
                request_fingerprint=fingerprint,
                actor_account_id=actor_account_id,
                university_id=university_id,
                reason=correction.reason,
                target_id=candidate.claim_id,
                target_revision=candidate.clock.revision,
                target_hash=target.revision_hash,
                source_observation_id=candidate.source_observation_id,
                expires_at=correction.expires_at,
                recorded_at=now,
            )
            self._submissions.append_submission(event)
            self._unit_of_work.commit()
            logger.info(
                "knowledge_manual_claim_metadata_corrected claim_id=%s revision=%d university_id=%s",
                candidate.claim_id,
                candidate.clock.revision,
                university_id,
            )
            return candidate
        except Exception as exc:
            self._unit_of_work.rollback()
            logger.error(
                "knowledge_manual_claim_metadata_correction_failed claim_id=%s university_id=%s error_type=%s",
                correction.claim_id,
                university_id,
                type(exc).__name__,
            )
            raise


def _validate_manual_document(body: bytes, content_type: str) -> str:
    if not body or len(body) > MAX_MANUAL_DOCUMENT_BYTES:
        raise ValidationError("Manual documents must be between 1 byte and 10 MiB")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "application/pdf":
        if not (body.startswith(b"%PDF-") or body[:1024].find(b"%PDF-") >= 0):
            raise ValidationError("Uploaded document does not have a valid PDF signature")
        return "application/pdf"
    if media_type == "text/plain":
        try:
            decoded = body.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("Manual text documents must use UTF-8") from exc
        if "\x00" in decoded or any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
            raise ValidationError("Manual text document contains unsupported control bytes")
        return "text/plain"
    raise ValidationError("Manual uploads accept only PDF or UTF-8 plain text")


def _same_registry_configuration(
    left: ApprovedSourceRegistryRevision, right: ApprovedSourceRegistryRevision
) -> bool:
    return (
        left.source_kind == right.source_kind
        and left.reliability_tier == right.reliability_tier
        and left.adapter_id == right.adapter_id
        and left.adapter_version == right.adapter_version
        and left.start_url == right.start_url
        and left.allowlist == right.allowlist
        and left.poll_interval_seconds == right.poll_interval_seconds
        and left.freshness_budget_seconds == right.freshness_budget_seconds
        and not left.enabled
        and left.approved_by_account_id == right.approved_by_account_id
        and left.approval_reason == right.approval_reason
    )


def _idempotency_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError("Manual knowledge timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["MAX_MANUAL_DOCUMENT_BYTES", "ManualSourceCommands"]
