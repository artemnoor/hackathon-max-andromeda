"""Thin HTTP adapters for the decision context and shortlist."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_decision_analytics_service, get_decision_service
from andromeda.api.schemas.decision import (
    DecisionAnalyticsAcceptedResponse,
    DecisionAnalyticsEventRequest,
    DecisionConstraintsUpdateRequest,
    DecisionContextResponse,
    DecisionMutationResponse,
    DecisionProgramCommandRequest,
    DecisionRevisionRequest,
    DecisionRefinementAnswerRequest,
    DecisionRefinementResponse,
    DecisionShortlistCommandRequest,
    DecisionShortlistRoleRequest,
    DecisionSuggestionsResponse,
    decision_context_response,
    decision_mutation_response,
    decision_refinement_response,
    decision_suggestions_response,
)
from andromeda.modules.decision.contracts.public import (
    ProgramCommand,
    ShortlistRole,
    ShortlistRoleCommand,
)
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.decision.services.analytics import DecisionAnalyticsService
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.ids import ProgramId


router = APIRouter(prefix="/decision", tags=["decision"])


@router.post("/analytics", response_model=DecisionAnalyticsAcceptedResponse)
def append_analytics(
    request: DecisionAnalyticsEventRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionAnalyticsService = Depends(get_decision_analytics_service),
) -> DecisionAnalyticsAcceptedResponse:
    accepted = service.record_client_event(scope, request.to_contract())
    return DecisionAnalyticsAcceptedResponse(accepted=min(accepted, 1))


@router.get("/context", response_model=DecisionContextResponse)
def get_context(
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionContextResponse:
    return decision_context_response(service.get_context(scope).context)


@router.get("/suggestions", response_model=DecisionSuggestionsResponse)
def get_suggestions(
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionSuggestionsResponse:
    return decision_suggestions_response(service.get_suggestions(scope))


@router.post("/refinement/answer", response_model=DecisionRefinementResponse)
def answer_refinement(
    request: DecisionRefinementAnswerRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionRefinementResponse:
    return decision_refinement_response(service.answer_refinement(scope, request.to_contract()))


@router.put("/constraints", response_model=DecisionMutationResponse)
def update_constraints(
    request: DecisionConstraintsUpdateRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(service.update_constraints(scope, request.to_contract()))


@router.post("/considered", response_model=DecisionMutationResponse)
def mark_considered(
    request: DecisionProgramCommandRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(service.mark_considered(scope, request.to_contract()))


@router.post("/shortlist", response_model=DecisionMutationResponse)
def add_shortlist(
    request: DecisionShortlistCommandRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(service.add_shortlist(scope, request.to_contract()))


@router.patch("/shortlist/{program_id}", response_model=DecisionMutationResponse)
def set_shortlist_role(
    program_id: ProgramId,
    request: DecisionShortlistRoleRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.set_shortlist_role(
            scope,
            ShortlistRoleCommand(
                version=request.version,
                program_id=program_id,
                role=request.role,
                expected_revision=request.expected_revision,
            ),
        )
    )


@router.post("/final-choice", response_model=DecisionMutationResponse)
def select_final_choice(
    request: DecisionProgramCommandRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(service.select_final_choice(scope, request.to_contract()))


@router.delete("/final-choice", response_model=DecisionMutationResponse)
def reopen_final_choice(
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.reopen_final_choice(scope, expected_revision=request.expected_revision if request is not None else None)
    )


@router.delete("/shortlist/{program_id}", response_model=DecisionMutationResponse)
def remove_shortlist(
    program_id: ProgramId,
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.remove_shortlist(scope, _program_command(program_id, request))
    )


@router.post("/programs/{program_id}/restore", response_model=DecisionMutationResponse)
def restore_shortlist(
    program_id: ProgramId,
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.restore_shortlist(scope, _program_command(program_id, request))
    )


@router.post("/programs/{program_id}/exclude", response_model=DecisionMutationResponse)
def exclude_program(
    program_id: ProgramId,
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.exclude_program(scope, _program_command(program_id, request))
    )


@router.delete("/programs/{program_id}/exclude", response_model=DecisionMutationResponse)
def restore_excluded_program(
    program_id: ProgramId,
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.restore_excluded_program(scope, _program_command(program_id, request))
    )


@router.post("/suggestions/{program_id}/accept", response_model=DecisionMutationResponse)
def accept_suggestion(
    program_id: ProgramId,
    request: DecisionShortlistRoleRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    role = request.role if request is not None else ShortlistRole.PRIMARY
    expected_revision = request.expected_revision if request is not None else None
    from andromeda.modules.decision.contracts.public import ShortlistCommand

    command = ShortlistCommand(
        program_id=program_id,
        role=role,
        expected_revision=expected_revision,
    )
    return decision_mutation_response(service.accept_suggestion(scope, command))


@router.post("/suggestions/{program_id}/reject", response_model=DecisionMutationResponse)
def reject_suggestion(
    program_id: ProgramId,
    request: DecisionRevisionRequest | None = Body(default=None),
    scope: ProfileScope = Depends(get_profile_scope),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionMutationResponse:
    return decision_mutation_response(
        service.reject_suggestion(scope, _program_command(program_id, request))
    )


def _program_command(program_id: ProgramId, request: DecisionRevisionRequest | None) -> ProgramCommand:
    return ProgramCommand(program_id=program_id, expected_revision=request.expected_revision if request is not None else None)


__all__ = ["router"]
