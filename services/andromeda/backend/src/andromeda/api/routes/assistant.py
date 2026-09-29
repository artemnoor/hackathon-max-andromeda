"""Channel-neutral conversation endpoint for supported client applications."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_assistant_service
from andromeda.api.schemas.assistant import AssistantQueryRequest
from andromeda.modules.conversation.contracts.assistant import AssistantResult
from andromeda.modules.conversation.services.assistant import AssistantService
from andromeda.modules.proftest.contracts.public import ProfileScope

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/query", response_model=AssistantResult)
def assistant_query(
    request: AssistantQueryRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: AssistantService = Depends(get_assistant_service),
) -> AssistantResult:
    return service.handle(
        request.text,
        owner_scope=scope,
        session_id=request.session_id,
        expected_revision=request.expected_revision,
        applicant_admission_context=request.applicant_admission_context,
    )


__all__ = ["router"]
