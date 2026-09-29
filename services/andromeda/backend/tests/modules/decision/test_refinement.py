from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from andromeda.modules.decision.contracts.public import (
    DecisionCandidatePartition,
    DecisionRefinementAnswer,
    DecisionRefinementOption,
    DecisionRefinementQuestion,
    DecisionSuggestion,
    DecisionSuggestionReasons,
    DecisionSuggestionsResult,
)
from andromeda.modules.decision.domain.entities import DecisionSnapshot, DecisionState
from andromeda.modules.decision.services.decision import DecisionService
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.programs.contracts.public import Program
from andromeda.modules.proftest.contracts.public import (
    Confidence,
    ProfileScope,
    UserProfile,
    UserProfileSnapshot,
)
from andromeda.shared.contracts.errors import ConflictError


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)
PROGRAM_A = "program:09.03.01-01"
PROGRAM_B = "program:09.03.01-02"


class Repository:
    def __init__(self) -> None:
        self.snapshot: DecisionSnapshot | None = None

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

    def save(self, scope: ProfileScope, state: DecisionState, *, expected_revision: int, expires_at: datetime) -> DecisionSnapshot:
        raise AssertionError("refinement must not mutate the decision repository")


class Programs:
    def get(self, program_id: str) -> Program:
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


class Profiles:
    def __init__(self) -> None:
        self.snapshot = UserProfileSnapshot(
            profile_id="profile:" + "b" * 32,
            profile=UserProfile(
                preferred_subject_weights={DisciplineAreaCode.MATHEMATICS_STATISTICS: Decimal("1")},
                confidence=Confidence(value=Decimal("0.5"), answered_base=1, answered_adaptive=0),
            ),
            revision=1,
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW + timedelta(days=1),
        )

    def get_current(self, scope: ProfileScope) -> UserProfileSnapshot:
        return self.snapshot


class Writer:
    def __init__(self, profiles: Profiles) -> None:
        self.profiles = profiles
        self.calls = []

    def apply_refinement(self, scope, refinement, *, expected_revision: int) -> UserProfileSnapshot:
        self.calls.append((refinement, expected_revision))
        self.profiles.snapshot = self.profiles.snapshot.model_copy(update={"revision": expected_revision + 1})
        return self.profiles.snapshot


class Candidates:
    def build(self, context) -> DecisionSuggestionsResult:
        def suggestion(program_id: str) -> DecisionSuggestion:
            return DecisionSuggestion(
                program_id=program_id,
                program_code=program_id.removeprefix("program:"),
                program_name=program_id,
                partition=DecisionCandidatePartition.PRIMARY,
                reasons=DecisionSuggestionReasons(why_included=("source-backed candidate",)),
            )

        items = (suggestion(PROGRAM_A), suggestion(PROGRAM_B))
        return DecisionSuggestionsResult(
            decision_id=context.decision_id,
            context_revision=context.state.revision,
            primary_candidates=items,
            suggestions=items,
            refinement_question=DecisionRefinementQuestion(
                id="content-tradeoff-a-vs-b",
                prompt="Что ближе?",
                candidate_program_ids=(PROGRAM_A, PROGRAM_B),
                options=(
                    DecisionRefinementOption(
                        id="program-a",
                        label="Программа A",
                        affected_dimension="subject:mathematics_statistics",
                    ),
                    DecisionRefinementOption(
                        id="program-b",
                        label="Программа B",
                        affected_dimension="activity:data",
                    ),
                ),
            ),
        )


def _scope() -> ProfileScope:
    return ProfileScope(session_key_hash="a" * 64)


def _service() -> tuple[DecisionService, Writer]:
    profiles = Profiles()
    writer = Writer(profiles)
    service = DecisionService(
        Repository(),
        Programs(),
        profiles,
        Candidates(),
        ttl_seconds=3600,
        clock=lambda: NOW,
        profile_writer=writer,
    )
    return service, writer


def test_refinement_updates_profile_only_and_rebuilds_suggestions() -> None:
    service, writer = _service()

    result = service.answer_refinement(
        _scope(),
        DecisionRefinementAnswer(question_id="content-tradeoff-a-vs-b", option_id="program-b", expected_revision=1),
    )

    assert result.profile_revision == 2
    assert result.suggestions.context_revision == 1
    assert writer.calls[0][0].affected_dimension == "activity:data"


def test_refinement_rejects_stale_revision_and_question() -> None:
    service, _writer = _service()

    with pytest.raises(ConflictError):
        service.answer_refinement(
            _scope(),
            DecisionRefinementAnswer(question_id="content-tradeoff-a-vs-b", option_id="program-a", expected_revision=2),
        )

    with pytest.raises(ConflictError):
        service.answer_refinement(
            _scope(),
            DecisionRefinementAnswer(question_id="old-question", option_id="program-a", expected_revision=1),
        )
