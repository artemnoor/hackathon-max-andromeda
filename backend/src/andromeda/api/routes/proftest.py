from __future__ import annotations

from fastapi import APIRouter, Depends

from andromeda.api.dependencies.profile_session import get_profile_scope
from andromeda.api.dependencies.services import get_proftest_service, get_proftest_session_service
from andromeda.api.dependencies.services import get_profile_persistence_service
from andromeda.api.schemas.proftest import ProftestAnalyticsAcceptedResponse, ProftestAnalyticsBatchRequest, ProftestPreviewResponse, ProftestResultsResponse, ProftestSessionResponse, ProftestSessionPatchRequest, ProftestSessionNextRequest, ProftestSubmissionRequest, QuestionnaireResponse, UserProfileCreateRequest, UserProfileSnapshotResponse, UserProfileUpdateRequest, preview_response, questionnaire_response, results_response, session_response, snapshot_response
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.proftest.services.profile_persistence import UserProfilePersistenceService
from andromeda.modules.proftest.services.proftest import ProftestService
from andromeda.modules.proftest.services.session import ProftestSessionService


router = APIRouter(prefix="/proftest", tags=["proftest"])


@router.get(
    "/questions",
    response_model=QuestionnaireResponse,
    deprecated=True,
    summary="Legacy questionnaire compatibility adapter",
    description="Compatibility read path for clients that have not migrated to /proftest/sessions. The canonical user flow is the version-pinned session API.",
)
def get_questions(service: ProftestService = Depends(get_proftest_service)) -> QuestionnaireResponse:
    return questionnaire_response(service.questionnaire())


@router.post(
    "/preview",
    response_model=ProftestPreviewResponse,
    deprecated=True,
    summary="Legacy proftest preview compatibility adapter",
    description="Compatibility adapter over the existing profile/ranking services. New clients must use /proftest/sessions.",
)
def preview(request: ProftestSubmissionRequest, service: ProftestService = Depends(get_proftest_service)) -> ProftestPreviewResponse:
    return preview_response(service.preview(request.to_contract()))


@router.post(
    "/results",
    response_model=ProftestResultsResponse,
    deprecated=True,
    summary="Legacy proftest results compatibility adapter",
    description="Compatibility adapter that delegates to the canonical profile builder and recommendation service. New clients must complete /proftest/sessions.",
)
def results(
    request: ProftestSubmissionRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestService = Depends(get_proftest_service),
) -> ProftestResultsResponse:
    return results_response(service.results(request.to_contract(), profile_scope=scope))


@router.post("/sessions", response_model=ProftestSessionResponse)
def start_session(
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestSessionResponse:
    return session_response(service.start(scope))


@router.get("/sessions/current", response_model=ProftestSessionResponse)
def current_session(
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestSessionResponse:
    return session_response(service.current(scope))


@router.patch("/sessions/current", response_model=ProftestSessionResponse)
def save_session(
    request: ProftestSessionPatchRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestSessionResponse:
    answers = tuple(item.to_contract() for item in request.answers)
    return session_response(service.save(scope, answers, expected_revision=request.expected_revision))


@router.post("/sessions/current/next", response_model=ProftestSessionResponse)
def next_session(
    request: ProftestSessionNextRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestSessionResponse:
    return session_response(service.next(scope, request.to_contract(), expected_revision=request.expected_revision))


@router.post("/sessions/current/complete", response_model=ProftestSessionResponse)
def complete_session(
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestSessionResponse:
    return session_response(service.complete(scope))


@router.post("/analytics", response_model=ProftestAnalyticsAcceptedResponse)
def analytics(
    request: ProftestAnalyticsBatchRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: ProftestSessionService = Depends(get_proftest_session_service),
) -> ProftestAnalyticsAcceptedResponse:
    events = tuple(item.to_contract() for item in request.events)
    return ProftestAnalyticsAcceptedResponse(accepted=service.append_analytics(scope, events))


@router.get("/profile", response_model=UserProfileSnapshotResponse)
def get_profile(
    scope: ProfileScope = Depends(get_profile_scope),
    service: UserProfilePersistenceService = Depends(get_profile_persistence_service),
) -> UserProfileSnapshotResponse:
    snapshot = service.get_current(scope)
    return snapshot_response(snapshot)


@router.post("/profile", response_model=UserProfileSnapshotResponse, status_code=201)
def create_profile(
    request: UserProfileCreateRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: UserProfilePersistenceService = Depends(get_profile_persistence_service),
) -> UserProfileSnapshotResponse:
    snapshot = service.create(scope, request.to_contract())
    return snapshot_response(snapshot)


@router.put("/profile", response_model=UserProfileSnapshotResponse)
def update_profile(
    request: UserProfileUpdateRequest,
    scope: ProfileScope = Depends(get_profile_scope),
    service: UserProfilePersistenceService = Depends(get_profile_persistence_service),
) -> UserProfileSnapshotResponse:
    snapshot = service.update(scope, request.to_contract(), expected_revision=request.expected_revision)
    return snapshot_response(snapshot)
