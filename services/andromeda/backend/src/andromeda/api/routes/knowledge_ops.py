from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Path, UploadFile, status
from sqlalchemy.orm import Session

from andromeda.api.dependencies.auth_session import require_current_account
from andromeda.api.dependencies.composition import get_composition_root
from andromeda.api.dependencies.knowledge_manual import (
    get_knowledge_manual_commands,
    require_knowledge_source_steward,
)
from andromeda.api.dependencies.request_context import get_session
from andromeda.api.dependencies.university_admin import require_university_editor
from andromeda.api.schemas.knowledge_ops import (
    KnowledgeManualClaimResponse,
    KnowledgeSourceObservationResponse,
    KnowledgeSourceRegistrationRequest,
    KnowledgeSourceRegistrationResponse,
    ManualClaimMetadataCorrectionRequest,
    ManualClaimSubmissionRequest,
    ManualPolicyRuleCandidateRequest,
    ManualPolicyRuleCandidateResponse,
)
from andromeda.composition import AndromedaContainer
from andromeda.modules.auth.contracts.public import Account
from andromeda.modules.knowledge.contracts.public import ManualIdempotencyKey, SourceId
from andromeda.modules.knowledge.services.manual_source_commands import (
    MAX_MANUAL_DOCUMENT_BYTES,
    ManualSourceCommands,
)
from andromeda.modules.university_admin.contracts.public import UniversityAdminActor
from andromeda.shared.contracts.errors import ValidationError
from andromeda.shared.contracts.ids import UniversityId

router = APIRouter(tags=["knowledge-ops"])


@router.post(
    "/ops/knowledge/sources",
    response_model=KnowledgeSourceRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register_knowledge_source",
)
def register_knowledge_source(
    body: KnowledgeSourceRegistrationRequest,
    actor: Annotated[Account, Depends(require_knowledge_source_steward)],
    commands: Annotated[ManualSourceCommands, Depends(get_knowledge_manual_commands)],
) -> KnowledgeSourceRegistrationResponse:
    revision = commands.register_source(
        actor_account_id=actor.account_id,
        draft=body.to_draft(),
        now=datetime.now(UTC),
    )
    return KnowledgeSourceRegistrationResponse(
        source_id=revision.source_id,
        revision=revision.revision,
        reliability_tier=revision.reliability_tier,
        enabled=revision.enabled,
        approved_by_account_id=revision.approved_by_account_id,
        recorded_at=revision.recorded_at,
    )


@router.post(
    "/ops/knowledge/sources/{source_id}/snapshots",
    response_model=KnowledgeSourceObservationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="attach_knowledge_source_snapshot",
)
async def attach_knowledge_source_snapshot(
    source_id: SourceId,
    requested_url: Annotated[str, Form(min_length=1, max_length=2048)],
    reason: Annotated[str, Form(min_length=1, max_length=512)],
    document: Annotated[UploadFile, File()],
    idempotency_key: Annotated[ManualIdempotencyKey, Header(alias="Idempotency-Key")],
    actor: Annotated[Account, Depends(require_knowledge_source_steward)],
    commands: Annotated[ManualSourceCommands, Depends(get_knowledge_manual_commands)],
    expires_at: Annotated[datetime | None, Form()] = None,
) -> KnowledgeSourceObservationResponse:
    content_type = document.content_type or ""
    body = await document.read(MAX_MANUAL_DOCUMENT_BYTES + 1)
    if len(body) > MAX_MANUAL_DOCUMENT_BYTES:
        raise ValidationError("Manual documents must be no larger than 10 MiB")
    observation = commands.attach_document(
        actor_account_id=actor.account_id,
        source_id=source_id,
        requested_url=requested_url,
        content_type=content_type,
        body=body,
        reason=reason,
        idempotency_key=idempotency_key,
        expires_at=expires_at,
        now=datetime.now(UTC),
    )
    return KnowledgeSourceObservationResponse(
        source_observation_id=observation.source_observation_id,
        source_id=observation.source_id,
        registry_revision=observation.registry_revision,
        snapshot_sha256=observation.snapshot_sha256,
        captured_at=observation.captured_at,
        access_mode=observation.access_mode,
        content_type=observation.content_type,
    )


@router.post(
    "/university-admin/universities/{university_id}/knowledge/claims",
    response_model=KnowledgeManualClaimResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_manual_knowledge_claim_candidate",
)
def submit_manual_knowledge_claim_candidate(
    university_id: UniversityId,
    body: ManualClaimSubmissionRequest,
    actor: Annotated[Account, Depends(require_current_account)],
    _university_actor: Annotated[UniversityAdminActor, Depends(require_university_editor)],
    idempotency_key: Annotated[ManualIdempotencyKey, Header(alias="Idempotency-Key")],
    commands: Annotated[ManualSourceCommands, Depends(get_knowledge_manual_commands)],
) -> KnowledgeManualClaimResponse:
    claim = commands.submit_claim(
        actor_account_id=actor.account_id,
        university_id=university_id,
        draft=body.to_draft(idempotency_key=idempotency_key),
        now=datetime.now(UTC),
    )
    return KnowledgeManualClaimResponse(
        claim_id=claim.claim_id,
        revision=claim.clock.revision,
        review_state=claim.review_state.value,
        source_observation_id=claim.source_observation_id,
        recorded_at=claim.clock.recorded_at,
    )


@router.put(
    "/university-admin/universities/{university_id}/knowledge/claims/{claim_id}/metadata",
    response_model=KnowledgeManualClaimResponse,
    status_code=status.HTTP_200_OK,
    operation_id="correct_manual_knowledge_claim_metadata",
)
def correct_manual_knowledge_claim_metadata(
    university_id: UniversityId,
    claim_id: Annotated[str, Path(pattern=r"^claim:[a-f0-9]{64}$")],
    body: ManualClaimMetadataCorrectionRequest,
    actor: Annotated[Account, Depends(require_current_account)],
    _university_actor: Annotated[UniversityAdminActor, Depends(require_university_editor)],
    idempotency_key: Annotated[ManualIdempotencyKey, Header(alias="Idempotency-Key")],
    commands: Annotated[ManualSourceCommands, Depends(get_knowledge_manual_commands)],
) -> KnowledgeManualClaimResponse:
    claim = commands.correct_claim_metadata(
        actor_account_id=actor.account_id,
        university_id=university_id,
        correction=body.to_contract(claim_id=claim_id, idempotency_key=idempotency_key),
        now=datetime.now(UTC),
    )
    return KnowledgeManualClaimResponse(
        claim_id=claim.claim_id,
        revision=claim.clock.revision,
        review_state=claim.review_state.value,
        source_observation_id=claim.source_observation_id,
        recorded_at=claim.clock.recorded_at,
    )


@router.post(
    "/university-admin/universities/{university_id}/knowledge/policy-rules",
    response_model=ManualPolicyRuleCandidateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="submit_manual_policy_rule_candidate",
)
def submit_manual_policy_rule_candidate(
    university_id: UniversityId,
    body: ManualPolicyRuleCandidateRequest,
    actor: Annotated[Account, Depends(require_current_account)],
    _university_actor: Annotated[UniversityAdminActor, Depends(require_university_editor)],
    container: Annotated[AndromedaContainer, Depends(get_composition_root)],
    session: Annotated[Session, Depends(get_session)],
) -> ManualPolicyRuleCandidateResponse:
    event = container.manual_policy_candidate_commands(
        session,
        actor_account_id=actor.account_id,
        university_id=university_id,
    ).submit(
        actor_account_id=actor.account_id,
        university_id=university_id,
        revision=body.revision,
        reason=body.reason,
        submitted_at=datetime.now(UTC),
    )
    return ManualPolicyRuleCandidateResponse(
        rule_id=event.rule_id,
        revision=event.revision,
        revision_hash=event.revision_hash,
        approval_event_id=event.event_id,
        review_state=event.kind.value,
        submitted_by_account_id=event.actor_account_id,
        submitted_at=event.recorded_at,
    )


__all__ = ["router"]
