from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from andromeda.modules.decision.contracts.public import (
    DecisionCandidatePartition,
    DecisionConstraintsUpdate,
    DecisionContextMetadata,
    DecisionSuggestion,
    DecisionSuggestionReasons,
    DecisionSuggestionsResult,
    ProgramCommand,
    ShortlistCommand,
    ShortlistRole,
    ShortlistRoleCommand,
)
from andromeda.modules.decision.domain.entities import DecisionSnapshot, DecisionState
from andromeda.modules.decision.domain.values import DecisionSourceKind
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.shared.contracts.errors import ConflictError, NotFoundError, ValidationError


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
PROGRAM_A = "program:09.03.01-01"
PROGRAM_B = "program:09.03.01-02"


def _program(program_id: str) -> Program:
    code = program_id.removeprefix("program:")
    return Program(
        id=program_id,
        direction_id="direction:09.03.01",
        code=code,
        name=f"Программа {code}",
        education_year=2026,
        study_plan_url="https://example.test/plan.pdf",
        source_url="https://example.test/program",
    )


class Repository:
    def __init__(self) -> None:
        self.snapshot: DecisionSnapshot | None = None
        self.save_calls = 0

    def get_current(self, scope: ProfileScope) -> DecisionSnapshot | None:
        return self.snapshot

    def get_or_create(self, scope: ProfileScope, *, expires_at: datetime) -> DecisionSnapshot:
        if self.snapshot is None:
            state = DecisionState(created_at=NOW, updated_at=NOW)
            self.snapshot = DecisionSnapshot(
                decision_id="decision:" + "a" * 32,
                owner_key=scope.owner_key,
                state=state,
                revision=state.revision,
                created_at=NOW,
                updated_at=NOW,
                expires_at=expires_at,
            )
        return self.snapshot

    def save(
        self,
        scope: ProfileScope,
        state: DecisionState,
        *,
        expected_revision: int,
        expires_at: datetime,
    ) -> DecisionSnapshot:
        del scope
        if self.snapshot is None or self.snapshot.revision != expected_revision:
            raise ConflictError("Current decision context revision is stale")
        self.save_calls += 1
        self.snapshot = DecisionSnapshot(
            decision_id=self.snapshot.decision_id,
            owner_key=self.snapshot.owner_key,
            state=state,
            revision=state.revision,
            created_at=self.snapshot.created_at,
            updated_at=state.updated_at,
            expires_at=expires_at,
        )
        return self.snapshot


class Programs:
    def __init__(self) -> None:
        self.items = {PROGRAM_A: _program(PROGRAM_A), PROGRAM_B: _program(PROGRAM_B)}

    def get(self, program_id: str) -> Program | None:
        return self.items.get(program_id)

    def list(self) -> tuple[Program, ...]:
        return tuple(self.items.values())


class Profiles:
    def get_current(self, scope: ProfileScope):
        del scope
        return None


class Candidates:
    def __init__(self) -> None:
        self.calls = 0

    def build(self, context) -> DecisionSuggestionsResult:
        self.calls += 1
        suggestion = DecisionSuggestion(
            program_id=PROGRAM_A,
            program_code="09.03.01-01",
            program_name="Программа A",
            partition=DecisionCandidatePartition.PRIMARY,
            reasons=DecisionSuggestionReasons(why_included=("source-backed candidate",)),
        )
        return DecisionSuggestionsResult(
            decision_id=context.decision_id,
            context_revision=context.state.revision,
            primary_candidates=(suggestion,),
            suggestions=(suggestion,),
        )


def _service(repository: Repository | None = None, candidates: Candidates | None = None) -> tuple[DecisionService, Repository, Candidates]:
    stored = repository or Repository()
    candidate_service = candidates or Candidates()
    return (
        DecisionService(
            stored,
            Programs(),
            Profiles(),
            candidate_service,
            ttl_seconds=3600,
            clock=lambda: NOW,
        ),
        stored,
        candidate_service,
    )


def _scope() -> ProfileScope:
    return ProfileScope(session_key_hash="a" * 64)


def test_explicit_mutation_sequence_never_auto_prunes_and_keeps_roles() -> None:
    service, repository, _ = _service()
    scope = _scope()
    initial = service.get_context(scope).context
    assert initial.state.revision == 1

    considered = service.mark_considered(scope, ProgramCommand(program_id=PROGRAM_A, expected_revision=1))
    added = service.add_shortlist(
        scope,
        ShortlistCommand(program_id=PROGRAM_A, role=ShortlistRole.PRIMARY, expected_revision=considered.context.state.revision),
    )
    alternative = service.set_shortlist_role(
        scope,
        ShortlistRoleCommand(
            program_id=PROGRAM_A,
            role=ShortlistRole.ALTERNATIVE,
            expected_revision=added.context.state.revision,
        ),
    )
    removed = service.remove_shortlist(
        scope,
        ProgramCommand(program_id=PROGRAM_A, expected_revision=alternative.context.state.revision),
    )
    restored = service.restore_shortlist(
        scope,
        ProgramCommand(program_id=PROGRAM_A, expected_revision=removed.context.state.revision),
    )

    entry = restored.context.state.choice.active_shortlist[0]
    assert entry.program_id == PROGRAM_A
    assert entry.role is ShortlistRole.ALTERNATIVE
    assert restored.context.state.choice.considered_program_ids == (PROGRAM_A,)
    assert repository.save_calls == 5


def test_idempotent_shortlist_add_does_not_advance_revision() -> None:
    service, repository, _ = _service()
    scope = _scope()
    added = service.add_shortlist(scope, ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))
    repeated = service.add_shortlist(
        scope,
        ShortlistCommand(program_id=PROGRAM_A, expected_revision=added.context.state.revision),
    )

    assert added.changed is True
    assert repeated.changed is False
    assert repeated.context.state.revision == added.context.state.revision
    assert repository.save_calls == 1


def test_stale_revision_is_rejected_and_unknown_program_is_not_created() -> None:
    service, repository, _ = _service()
    scope = _scope()
    with pytest.raises(NotFoundError):
        service.add_shortlist(scope, ShortlistCommand(program_id="program:09.03.01-99", expected_revision=1))

    service.add_shortlist(scope, ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))
    with pytest.raises(ConflictError):
        service.add_shortlist(scope, ShortlistCommand(program_id=PROGRAM_B, expected_revision=1))
    assert repository.snapshot is not None
    assert repository.snapshot.state.choice.active_shortlist[0].program_id == PROGRAM_A


def test_exclusion_requires_explicit_removal_and_can_be_restored() -> None:
    service, _, _ = _service()
    scope = _scope()
    added = service.add_shortlist(scope, ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))
    with pytest.raises(ValidationError):
        service.exclude_program(scope, ProgramCommand(program_id=PROGRAM_A, expected_revision=added.context.state.revision))

    removed = service.remove_shortlist(scope, ProgramCommand(program_id=PROGRAM_A, expected_revision=added.context.state.revision))
    excluded = service.exclude_program(scope, ProgramCommand(program_id=PROGRAM_A, expected_revision=removed.context.state.revision))
    assert excluded.context.state.choice.excluded_program_ids == (PROGRAM_A,)
    restored = service.restore_excluded_program(
        scope,
        ProgramCommand(program_id=PROGRAM_A, expected_revision=excluded.context.state.revision),
    )
    assert restored.context.state.choice.excluded_program_ids == ()
    assert restored.context.state.choice.active_shortlist == ()


def test_suggestions_are_read_only_and_acceptance_is_explicit() -> None:
    service, repository, candidates = _service()
    scope = _scope()
    before = service.get_context(scope).context.state.model_dump(mode="json")
    first = service.get_suggestions(scope)
    second = service.get_suggestions(scope)

    assert first == second
    assert candidates.calls == 2
    assert repository.snapshot is not None
    assert repository.snapshot.state.model_dump(mode="json") == before
    accepted = service.accept_suggestion(scope, ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))
    assert accepted.context.state.choice.active_shortlist[0].origin is DecisionSourceKind.SUGGESTION_ACCEPTED


def test_constraint_update_preserves_profile_as_separate_projection() -> None:
    service, _, _ = _service()
    result = service.update_constraints(
        _scope(),
        DecisionConstraintsUpdate(constraints=None, expected_revision=1),
    )
    assert result.context.preferences is None
    assert result.context.profile_revision is None


def test_analytics_failure_does_not_roll_back_committed_shortlist() -> None:
    class BrokenAnalytics:
        def record_mutation(self, **kwargs):
            del kwargs
            raise RuntimeError("analytics unavailable")

    repository = Repository()
    service = DecisionService(
        repository,
        Programs(),
        Profiles(),
        Candidates(),
        ttl_seconds=3600,
        clock=lambda: NOW,
        analytics=BrokenAnalytics(),
    )

    result = service.add_shortlist(_scope(), ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))

    assert result.changed is True
    assert repository.snapshot is not None
    assert repository.snapshot.state.choice.active_shortlist[0].program_id == PROGRAM_A


def test_server_analytics_receives_the_committed_state_transition() -> None:
    class RecordingAnalytics:
        def __init__(self) -> None:
            self.calls = []

        def record_mutation(self, scope, **kwargs):
            self.calls.append((scope, kwargs))

    analytics = RecordingAnalytics()
    repository = Repository()
    service = DecisionService(
        repository,
        Programs(),
        Profiles(),
        Candidates(),
        ttl_seconds=3600,
        clock=lambda: NOW,
        analytics=analytics,
    )

    result = service.add_shortlist(_scope(), ShortlistCommand(program_id=PROGRAM_A, expected_revision=1))

    assert result.changed is True
    assert len(analytics.calls) == 1
    _, event = analytics.calls[0]
    assert event["operation"] == "add_shortlist"
    assert event["program_id"] == PROGRAM_A
    assert len(event["before"].choice.active_shortlist) == 0
    assert len(event["after"].choice.active_shortlist) == 1
    assert repository.save_calls == 1
