from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from andromeda.modules.decision.contracts.public import DecisionSuggestionsResult
from andromeda.modules.decision.domain.entities import DecisionChoice, DecisionSnapshot, DecisionState
from andromeda.modules.decision.domain.values import DecisionSourceKind, ShortlistRole
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.proftest.contracts.public import Confidence, ProfileScope, UserProfile, UserProfileSnapshot
from andromeda.modules.programs.contracts.public import Program


NOW = datetime.now(timezone.utc)
PROGRAM_A = "program:09.03.01-01"
PROGRAM_B = "program:09.03.01-02"


class Repository:
    def __init__(self, state: DecisionState) -> None:
        self.snapshot = DecisionSnapshot(
            decision_id="decision:" + "a" * 32,
            owner_key="anonymous:" + "b" * 64,
            state=state,
            revision=state.revision,
            created_at=state.created_at,
            updated_at=state.updated_at,
            expires_at=NOW + timedelta(days=30),
        )
        self.save_calls = 0

    def get_current(self, scope: ProfileScope) -> DecisionSnapshot | None:
        del scope
        return self.snapshot

    def get_or_create(self, scope: ProfileScope, *, expires_at: datetime) -> DecisionSnapshot:
        del scope, expires_at
        return self.snapshot

    def save(self, scope: ProfileScope, state: DecisionState, *, expected_revision: int, expires_at: datetime) -> DecisionSnapshot:
        del scope, expected_revision, expires_at
        self.save_calls += 1
        raise AssertionError("profile projection must not persist decision state")


class Programs:
    def get(self, program_id: str) -> Program | None:
        del program_id
        return None

    def list(self) -> tuple[Program, ...]:
        return ()


class Profiles:
    def __init__(self) -> None:
        self.snapshot: UserProfileSnapshot | None = None

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot | None:
        del scope
        return self.snapshot


class Candidates:
    def __init__(self) -> None:
        self.contexts = []

    def build(self, context):
        self.contexts.append(context)
        return DecisionSuggestionsResult(decision_id=context.decision_id, context_revision=context.state.revision)


def _profile() -> UserProfile:
    return UserProfile(
        preferred_subject_weights={
            DisciplineAreaCode.COMPUTER_SCIENCE_DATA: Decimal("0.7"),
            DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("0.3"),
        },
        confidence=Confidence(value=Decimal("0.8"), answered_base=5, answered_adaptive=2),
    )


def _snapshot(profile: UserProfile, revision: int) -> UserProfileSnapshot:
    return UserProfileSnapshot(
        profile_id="profile:" + "c" * 32,
        profile=profile,
        revision=revision,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def _state() -> DecisionState:
    choice = DecisionChoice()
    choice = choice.add_shortlist(PROGRAM_A, role=ShortlistRole.PRIMARY, origin=DecisionSourceKind.USER, now=NOW)
    choice = choice.add_shortlist(PROGRAM_B, role=ShortlistRole.ALTERNATIVE, origin=DecisionSourceKind.USER, now=NOW)
    return DecisionState(choice=choice, created_at=NOW, updated_at=NOW)


def test_profile_is_hydrated_as_a_revisioned_projection_without_duplicate_state() -> None:
    scope = ProfileScope(session_key_hash="b" * 64)
    repository = Repository(_state())
    profiles = Profiles()
    candidates = Candidates()
    service = DecisionService(repository, Programs(), profiles, candidates, ttl_seconds=3600, clock=lambda: NOW)
    before = repository.snapshot.state.model_dump(mode="json")

    profiles.snapshot = _snapshot(_profile(), revision=4)
    context = service.get_context(scope).context
    suggestions = service.get_suggestions(scope)

    assert context.preferences == profiles.snapshot.profile
    assert context.profile_revision == 4
    assert context.metadata.profile_revision == 4
    assert suggestions.context_revision == context.state.revision
    assert candidates.contexts[-1].profile_revision == 4
    assert repository.snapshot.state.model_dump(mode="json") == before
    assert "profile" not in repository.snapshot.state.model_dump(mode="json")
    assert repository.save_calls == 0


def test_reloading_context_does_not_create_a_second_decision_or_duplicate_shortlist() -> None:
    scope = ProfileScope(session_key_hash="b" * 64)
    repository = Repository(_state())
    profiles = Profiles()
    profiles.snapshot = _snapshot(_profile(), revision=1)
    service = DecisionService(repository, Programs(), profiles, Candidates(), ttl_seconds=3600, clock=lambda: NOW)

    first = service.get_context(scope).context
    second = service.get_context(scope).context

    assert first.decision_id == second.decision_id
    assert first.state.revision == second.state.revision
    assert tuple(item.program_id for item in second.state.choice.active_shortlist) == (PROGRAM_A, PROGRAM_B)
